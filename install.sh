#!/usr/bin/env bash
set -e

BASE=/home/davix/Nextcloud/00_Coding/MidiController

mkdir -p "$BASE/midi_controller"

touch "$BASE/midi_controller/__init__.py"

cat > "$BASE/midi_controller/config.py" << 'EOF'
MPV_SOCKET_PATH = "/tmp/mpvsocket"
MPV_PLAYLIST = "/home/davix/Documents/allmusic.m3u"

SCREENSHOT_PATH = "/home/davix/sofa_screenshot.png"
OBS_RESTART_SCRIPT = "/home/davix/.local/bin/restart-obs.sh"

AUDIO_VLC_CONFIG = dict(
    name="audio",
    host="127.0.0.1",
    port=4213,
    playlist="/home/davix/Documents/audio.m3u",
    resume_file="/home/davix/.vlc_audio_resume",
    extra_args=["--intf", "dummy", "--width=400", "--height=400"],
)

VIDEO_VLC_CONFIG = dict(
    name="video",
    host="127.0.0.1",
    port=4212,
    playlist="/home/davix/Documents/video.m3u",
    resume_file="/home/davix/.vlc_video_resume",
    extra_args=["--fullscreen", "--no-spu", "--avcodec-hw=none"],
)
EOF

cat > "$BASE/midi_controller/keyboard_actions.py" << 'EOF'
from pynput.keyboard import Controller, Key

keyboard = Controller()


def make_key_action(key):
    def action():
        keyboard.press(key)
        keyboard.release(key)
    return action


def make_shift_key_action(key):
    def action():
        keyboard.press(Key.shift)
        keyboard.press(key)
        keyboard.release(key)
        keyboard.release(Key.shift)
    return action
EOF

cat > "$BASE/midi_controller/system_actions.py" << 'EOF'
import subprocess

from .config import SCREENSHOT_PATH, OBS_RESTART_SCRIPT


def make_screenshot_action():
    def action():
        subprocess.Popen(["spectacle", "-b", "-o", SCREENSHOT_PATH, "-m", "-n"])
    return action


def make_monitor_toggle_action():
    state = {"asleep": False}

    def action():
        if not state["asleep"]:
            print("Action: Blanking DP-1 and DP-2 (DPMS off)")
            subprocess.Popen(["kscreen-doctor", "output.DP-1.power.off", "output.DP-2.power.off"])
            state["asleep"] = True
        else:
            print("Action: Restoring DP-1 and DP-2 (DPMS on)")
            subprocess.Popen(["kscreen-doctor", "output.DP-1.power.on", "output.DP-2.power.on"])
            state["asleep"] = False

    return action


def toggle_mute():
    subprocess.Popen("pactl set-sink-mute @DEFAULT_SINK@ toggle", shell=True)


def restart_obs():
    subprocess.Popen([OBS_RESTART_SCRIPT])


def volume_knob(value):
    pct = round(value / 127 * 100)
    subprocess.Popen(f"pactl set-sink-volume @DEFAULT_SINK@ {pct}%", shell=True)
EOF

cat > "$BASE/midi_controller/scrub.py" << 'EOF'
import time

fine_scrub = False

_scrub_state = {5: {"value": None, "time": None}}


def scrub_delta(control, value):
    state = _scrub_state[control]
    now = time.monotonic()
    previous = state["value"]
    previous_time = state["time"]

    state["value"] = value
    state["time"] = now

    if previous is None:
        return 0, 0.0

    delta = value - previous
    if delta > 64:
        delta -= 128
    elif delta < -64:
        delta += 128

    elapsed = 0.1 if previous_time is None else now - previous_time
    return delta, elapsed


def scrub_seconds(delta, elapsed):
    if delta == 0:
        return 0

    if fine_scrub:
        return delta

    speed = abs(delta) / max(elapsed, 0.001)

    if speed < 2:
        seconds_per_step = 1
    elif speed < 5:
        seconds_per_step = 2
    elif speed < 10:
        seconds_per_step = 5
    elif speed < 20:
        seconds_per_step = 15
    else:
        seconds_per_step = 30

    return delta * seconds_per_step


def fine_scrub_press():
    global fine_scrub
    fine_scrub = True
    print("Fine scrub: ON")


def fine_scrub_release():
    global fine_scrub
    fine_scrub = False
    print("Fine scrub: OFF")
EOF

cat > "$BASE/midi_controller/mpv_control.py" << 'EOF'
import json
import socket
import subprocess

from .config import MPV_SOCKET_PATH, MPV_PLAYLIST
from .scrub import scrub_delta, scrub_seconds


def send_mpv_command(command):
    def action():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(MPV_SOCKET_PATH)
                s.sendall(json.dumps({"command": command}).encode() + b"\n")
        except (FileNotFoundError, ConnectionRefusedError):
            pass
    return action


def toggle_or_launch_mpv():
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(MPV_SOCKET_PATH)
            s.sendall(json.dumps({"command": ["cycle", "pause"]}).encode() + b"\n")
    except (FileNotFoundError, ConnectionRefusedError):
        subprocess.Popen([
            "mpv",
            "--player-operation-mode=pseudo-gui",
            f"--input-ipc-server={MPV_SOCKET_PATH}",
            "--shuffle",
            "--",
            MPV_PLAYLIST,
        ])


def mpv_seek_scrub_knob(value):
    delta, elapsed = scrub_delta(5, value)
    if delta == 0:
        return
    seconds = scrub_seconds(delta, elapsed)
    print(f"MPV seek: {seconds:+.0f}s")
    send_mpv_command(["seek", str(seconds), "relative"])()
EOF

cat > "$BASE/midi_controller/vlc_control.py" << 'EOF'
import os
import socket
import subprocess
import threading
import time

from .config import AUDIO_VLC_CONFIG, VIDEO_VLC_CONFIG


class VLCInstance:
    def __init__(self, name, host, port, playlist, resume_file, extra_args=None):
        self.name = name
        self.host = host
        self.port = port
        self.playlist = playlist
        self.resume_file = resume_file
        self.extra_args = extra_args or []
        self.socket = None
        self.lock = threading.Lock()
        self.process = None

    def get_socket(self):
        if self.socket is None:
            try:
                self.socket = socket.create_connection((self.host, self.port), timeout=0.3)
                self.socket.settimeout(0.2)
                while True:
                    try:
                        if not self.socket.recv(4096):
                            break
                    except socket.timeout:
                        break
            except OSError:
                self.socket = None
        return self.socket

    def rc_send(self, command):
        with self.lock:
            s = self.get_socket()
            if s is None:
                return None
            try:
                s.sendall(f"{command}\n".encode())
                try:
                    return s.recv(4096)
                except socket.timeout:
                    return None
            except OSError:
                self.socket = None
                return None

    def raise_window(self):
        if self.process is not None:
            try:
                subprocess.Popen(
                    ["xdotool", "search", "--pid", str(self.process.pid), "windowactivate"]
                )
            except FileNotFoundError:
                print(f"VLC [{self.name}]: xdotool not found, skipping window raise")

    def launch_or_toggle(self):
        try:
            with socket.create_connection((self.host, self.port), timeout=0.3) as s:
                s.sendall(b"pause\n")
            print(f"VLC [{self.name}]: toggled play/pause")
            return
        except (ConnectionRefusedError, TimeoutError, OSError):
            pass

        print(f"VLC [{self.name}]: launching")

        resume_index = None
        resume_time = None

        if os.path.exists(self.resume_file):
            try:
                with open(self.resume_file) as f:
                    lines = f.read().splitlines()
                if len(lines) >= 2 and lines[0].isdigit() and lines[1].isdigit():
                    resume_time, resume_index = lines[0], lines[1]
                os.remove(self.resume_file)
            except OSError:
                pass

        args = [
            "vlc",
            "--extraintf=rc",
            f"--rc-host={self.host}:{self.port}",
            "--no-random",
            *self.extra_args,
            self.playlist,
        ]
        self.process = subprocess.Popen(args)

        if resume_index and resume_time:
            def resume():
                for _ in range(20):
                    try:
                        with socket.create_connection((self.host, self.port), timeout=0.5) as s:
                            s.settimeout(0.3)
                            while True:
                                try:
                                    if not s.recv(4096):
                                        break
                                except socket.timeout:
                                    break
                            s.sendall(f"goto {resume_index}\n".encode())
                            time.sleep(0.3)
                            s.sendall(f"seek {resume_time}\n".encode())
                        return
                    except (ConnectionRefusedError, OSError):
                        time.sleep(0.5)
            threading.Thread(target=resume, daemon=True).start()

    def save_and_quit(self):
        try:
            with socket.create_connection((self.host, self.port), timeout=0.3) as s:
                s.settimeout(0.2)
                while True:
                    try:
                        if not s.recv(4096):
                            break
                    except socket.timeout:
                        break

                s.settimeout(0.5)
                s.sendall(b"get_time\n")
                time_resp = s.recv(1024).decode().strip()
                current_time = next(
                    (p for p in reversed(time_resp.split()) if p.isdigit()), None
                )

                s.sendall(b"playlist\n")
                playlist_resp = s.recv(4096).decode()
                current_index = None
                for line in playlist_resp.splitlines():
                    line = line.strip()
                    if line.startswith("|") and "*" in line:
                        after_pipe = line.split("*", 1)
                        if len(after_pipe) > 1:
                            num_str = after_pipe[1].split("-", 1)[0].strip()
                            if num_str.isdigit():
                                current_index = num_str
                                break

                if current_time and current_index:
                    with open(self.resume_file, "w") as f:
                        f.write(f"{current_time}\n{current_index}")
        except Exception:
            pass

        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                print(f"VLC [{self.name}]: terminate timed out, killing")
                self.process.kill()
                self.process.wait()
            self.process = None
        else:
            print(f"VLC [{self.name}]: no tracked PID — kill manually")


AUDIO_VLC = VLCInstance(**AUDIO_VLC_CONFIG)
VIDEO_VLC = VLCInstance(**VIDEO_VLC_CONFIG)


def video_toggle_and_raise():
    VIDEO_VLC.launch_or_toggle()
    VIDEO_VLC.raise_window()


def vlc_absolute_seek_knob(value):
    pct = round(value / 127 * 100)
    VIDEO_VLC.rc_send(f"seek {pct}%")
    print(f"VLC video seek: {pct}%")


_vlc_jog_state = {"zone": None, "value": None, "stop_event": None, "thread": None}


def _vlc_jog_classify(value):
    if value <= 15:
        return "ff_rewind"
    elif value <= 31:
        return "fast_rewind"
    elif value <= 47:
        return "slow_rewind"
    elif value <= 79:
        return "normal"
    elif value <= 95:
        return "step_forward"
    elif value <= 111:
        return "fast_forward"
    else:
        return "ff_forward"


def _vlc_jog_stop_repeat():
    if _vlc_jog_state["stop_event"] is not None:
        _vlc_jog_state["stop_event"].set()
    _vlc_jog_state["stop_event"] = None
    _vlc_jog_state["thread"] = None


def _vlc_jog_start_repeat(command, interval):
    stop_event = threading.Event()

    def loop():
        while not stop_event.wait(interval):
            VIDEO_VLC.rc_send(command)

    t = threading.Thread(target=loop, daemon=True)
    _vlc_jog_state["stop_event"] = stop_event
    _vlc_jog_state["thread"] = t
    t.start()


def vlc_jog_knob(value):
    zone = _vlc_jog_classify(value)

    if 80 <= value <= 85:
        previous = _vlc_jog_state["value"]
        _vlc_jog_stop_repeat()
        if previous is not None and 80 <= previous <= 85:
            if value > previous:
                VIDEO_VLC.rc_send("key frame-next")
            elif value < previous:
                VIDEO_VLC.rc_send("key frame-prev")
        _vlc_jog_state["zone"] = zone
        _vlc_jog_state["value"] = value
        return

    if zone == _vlc_jog_state["zone"]:
        if zone == "step_forward":
            _vlc_jog_stop_repeat()
            interval = 0.25 - ((value - 86) / 9.0) * 0.20
            _vlc_jog_start_repeat("key frame-next", interval)
        _vlc_jog_state["value"] = value
        return

    _vlc_jog_stop_repeat()
    _vlc_jog_state["zone"] = zone
    _vlc_jog_state["value"] = value
    print(f"VLC video jog: {zone}")

    if zone == "ff_rewind":
        _vlc_jog_start_repeat("seek -10", 0.3)
    elif zone == "fast_rewind":
        _vlc_jog_start_repeat("seek -3", 0.3)
    elif zone == "slow_rewind":
        _vlc_jog_start_repeat("seek -1", 0.4)
    elif zone == "normal":
        VIDEO_VLC.rc_send("rate 1")
        VIDEO_VLC.rc_send("play")
    elif zone == "step_forward":
        interval = 0.25 - ((value - 86) / 9.0) * 0.20
        _vlc_jog_start_repeat("key frame-next", interval)
    elif zone == "fast_forward":
        VIDEO_VLC.rc_send("rate 2")
        VIDEO_VLC.rc_send("play")
    elif zone == "ff_forward":
        VIDEO_VLC.rc_send("rate 4")
        VIDEO_VLC.rc_send("play")
EOF

cat > "$BASE/midi_controller/mappings.py" << 'EOF'
from .keyboard_actions import make_shift_key_action
from .mpv_control import send_mpv_command, mpv_seek_scrub_knob
from .vlc_control import (
    AUDIO_VLC,
    VIDEO_VLC,
    video_toggle_and_raise,
    vlc_absolute_seek_knob,
    vlc_jog_knob,
)
from .scrub import fine_scrub_press, fine_scrub_release
from .system_actions import make_monitor_toggle_action, toggle_mute, restart_obs, volume_knob

PAD_PRESS = {
    36: AUDIO_VLC.launch_or_toggle,
    37: send_mpv_command(["playlist-next"]),
    38: make_shift_key_action("v"),
    39: video_toggle_and_raise,
    40: AUDIO_VLC.save_and_quit,
    41: send_mpv_command(["playlist-prev"]),
    42: fine_scrub_press,
    43: VIDEO_VLC.save_and_quit,
}

PAD_RELEASE = {
    42: fine_scrub_release,
}

_monitor_toggle_action = make_monitor_toggle_action()

PAD_PROGRAM_PRESS = {
    0: _monitor_toggle_action,
    1: toggle_mute,
    2: restart_obs,
    3: _monitor_toggle_action,
}

CC_HANDLERS = {
    3: vlc_absolute_seek_knob,
    4: vlc_jog_knob,
    5: mpv_seek_scrub_knob,
    8: volume_knob,
}
EOF

cat > "$BASE/midi_controller/dispatcher.py" << 'EOF'
import sys

import mido

from .mappings import PAD_PRESS, PAD_RELEASE, PAD_PROGRAM_PRESS, CC_HANDLERS


def find_port():
    for name in mido.get_input_names():
        if "LPD8" in name:
            return name
    raise RuntimeError("LPD8 not found — is it connected?")


def handle_message(msg):
    if msg.type == "note_on":
        if msg.velocity == 0:
            action = PAD_RELEASE.get(msg.note)
            if action:
                action()
            return
        action = PAD_PRESS.get(msg.note)
        if action:
            print(f"PAD PRESS: note={msg.note}, velocity={msg.velocity}")
            action()
    elif msg.type == "note_off":
        action = PAD_RELEASE.get(msg.note)
        if action:
            action()
    elif msg.type == "control_change":
        handler = CC_HANDLERS.get(msg.control)
        if handler:
            handler(msg.value)
    elif msg.type == "program_change":
        action = PAD_PROGRAM_PRESS.get(msg.program)
        if action:
            action()


def main():
    try:
        port_name = find_port()
        with mido.open_input(port_name) as inport:
            print(f"Listening on {port_name} — Ctrl+C to stop")
            for msg in inport:
                handle_message(msg)
    except KeyboardInterrupt:
        sys.exit(0)
EOF

cat > "$BASE/lpd8_mapper.py" << 'EOF'
#!/usr/bin/env python3
from midi_controller.dispatcher import main

if __name__ == "__main__":
    main()
EOF

chmod +x "$BASE/lpd8_mapper.py"

echo "Done. Structure created under $BASE"