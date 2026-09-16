#!/usr/bin/env python3
"""
LPD8 -> keyboard/script mapper.

Physical layout (2 rows: 4 pads + 4 knobs each):

  Top:    P5 P6 P7 P8 | K1 K2 K3 K4
  Bottom: P1 P2 P3 P4 | K5 K6 K7 K8

Note mode (notes 36-43):
  P1 36  VLC audio launch/toggle   P5 40  VLC audio save+quit
  P2 37  MPV next                 P6 41  MPV prev
  P3 38  VLC subs                 P7 42  Fine scrub (hold)
  P4 39  VLC video launch/toggle  P8 43  VLC video save+quit

Prog Chng mode (programs 0-7):
  P1 0  Toggle monitors     P5 4  UNSET
  P2 1  Toggle mute         P6 5  UNSET
  P3 2  Restart OBS         P7 6  UNSET
  P4 3  Toggle monitors     P8 7  UNSET

Knobs (CC):
  K3  VLC (video) absolute seek (0-100%)
  K4  VLC (video) jog/shuttle
  K5  MPV scrub
  K8  Volume

Switch modes on the device via the PAD / PROG CHNG / CC buttons.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time

import mido
from pynput.keyboard import Controller, Key


keyboard = Controller()

# ============================================================
# Config / paths
# ============================================================

MPV_SOCKET_PATH = "/tmp/mpvsocket"
MPV_PLAYLIST = "/home/davix/Documents/allmusic.m3u"

SCREENSHOT_PATH = "/home/davix/sofa_screenshot.png"
OBS_RESTART_SCRIPT = "/home/davix/.local/bin/restart-obs.sh"


# ============================================================
# MIDI port
# ============================================================

def find_port():
    for name in mido.get_input_names():
        if "LPD8" in name:
            return name

    raise RuntimeError("LPD8 not found — is it connected?")


PORT_NAME = find_port()


# ============================================================
# Utils
# ============================================================

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


def make_screenshot_action():
    def action():
        subprocess.Popen([
            "spectacle",
            "-b",
            "-o",
            SCREENSHOT_PATH,
            "-m",
            "-n",
        ])

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


# ============================================================
# Scrub engine (shared by MPV scrub knob)
# ============================================================

fine_scrub = False

_scrub_state = {
    5: {"value": None, "time": None},
}


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

    if previous_time is None:
        elapsed = 0.1
    else:
        elapsed = now - previous_time

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


# ============================================================
# MPV
# ============================================================

def send_mpv_command(command):
    def action():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(MPV_SOCKET_PATH)
                s.sendall(
                    json.dumps({"command": command}).encode() + b"\n"
                )
        except (FileNotFoundError, ConnectionRefusedError):
            pass

    return action


def toggle_or_launch_mpv():
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(MPV_SOCKET_PATH)
            s.sendall(
                json.dumps(
                    {"command": ["cycle", "pause"]}
                ).encode() + b"\n"
            )

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

    send_mpv_command([
        "seek",
        str(seconds),
        "relative",
    ])()


# ============================================================
# VLC — per-instance class
# ============================================================

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
                self.socket = socket.create_connection(
                    (self.host, self.port), timeout=0.3
                )
                self.socket.settimeout(0.2)
                while True:
                    try:
                        chunk = self.socket.recv(4096)
                        if not chunk:
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
            subprocess.Popen(
                ["xdotool", "search", "--pid", str(self.process.pid), "windowactivate"]
            )

    def launch_or_toggle(self):
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=0.3
            ) as s:
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
                if (
                    len(lines) >= 2
                    and lines[0].isdigit()
                    and lines[1].isdigit()
                ):
                    resume_time = lines[0]
                    resume_index = lines[1]
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
                        with socket.create_connection(
                            (self.host, self.port), timeout=0.5
                        ) as s:
                            s.settimeout(0.3)
                            while True:
                                try:
                                    chunk = s.recv(4096)
                                    if not chunk:
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
            with socket.create_connection(
                (self.host, self.port), timeout=0.3
            ) as s:
                s.settimeout(0.2)
                while True:
                    try:
                        chunk = s.recv(4096)
                        if not chunk:
                            break
                    except socket.timeout:
                        break

                s.settimeout(0.5)

                s.sendall(b"get_time\n")
                time_resp = s.recv(1024).decode().strip()
                time_parts = time_resp.split()
                current_time = next(
                    (p for p in reversed(time_parts) if p.isdigit()), None
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


AUDIO_VLC = VLCInstance(
    name="audio",
    host="127.0.0.1",
    port=4213,
    playlist="/home/davix/Documents/audio.m3u",
    resume_file="/home/davix/.vlc_audio_resume",
    extra_args=["--intf", "dummy", "--no-video"],
)

VIDEO_VLC = VLCInstance(
    name="video",
    host="127.0.0.1",
    port=4212,
    playlist="/home/davix/Documents/video.m3u",
    resume_file="/home/davix/.vlc_video_resume",
    extra_args=["--fullscreen", "--no-spu", "--avcodec-hw=none"],
)


def video_toggle_and_raise():
    VIDEO_VLC.launch_or_toggle()
    VIDEO_VLC.raise_window()


def vlc_absolute_seek_knob(value):
    pct = round(value / 127 * 100)
    VIDEO_VLC.rc_send(f"seek {pct}%")
    print(f"VLC video seek: {pct}%")


# --- Knob 4: jog/shuttle wheel (video instance) ---

_vlc_jog_state = {
    "zone": None,
    "value": None,
    "stop_event": None,
    "thread": None,
}


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


# ============================================================
# Pad mappings — Note mode
# ============================================================

PAD_PRESS = {
    # Pad 1 - VLC audio launch / toggle
    36: AUDIO_VLC.launch_or_toggle,

    # Pad 2 - MPV next
    37: send_mpv_command(["playlist-next"]),

    # Pad 3 - VLC toggle subtitles
    38: make_shift_key_action("v"),

    # Pad 4 - VLC video launch / toggle + raise window
    39: video_toggle_and_raise,

    # Pad 5 - VLC audio save state + quit
    40: AUDIO_VLC.save_and_quit,

    # Pad 6 - MPV previous
    41: send_mpv_command(["playlist-prev"]),

    # Pad 7 - Fine scrub modifier
    42: fine_scrub_press,

    # Pad 8 - VLC video save state + quit
    43: VIDEO_VLC.save_and_quit,
}


PAD_RELEASE = {
    # Pad 7 - Release fine scrub modifier
    42: fine_scrub_release,
}


# ============================================================
# Pad mappings — Prog Chng mode
# ============================================================

_monitor_toggle_action = make_monitor_toggle_action()

PAD_PROGRAM_PRESS = {
    # Pad 1 - Toggle secondary monitors
    0: _monitor_toggle_action,

    # Pad 2 - Toggle mute
    1: lambda: subprocess.Popen(
        "pactl set-sink-mute @DEFAULT_SINK@ toggle",
        shell=True,
    ),

    # Pad 3 - Restart OBS
    2: lambda: subprocess.Popen([OBS_RESTART_SCRIPT]),

    # Pad 4 - Toggle secondary monitors
    3: _monitor_toggle_action,
}


# ============================================================
# Knob mappings
# ============================================================

def volume_knob(value):
    pct = round(value / 127 * 100)

    subprocess.Popen(
        f"pactl set-sink-volume @DEFAULT_SINK@ {pct}%",
        shell=True,
    )


CC_HANDLERS = {
    # Knob 3 - VLC video absolute seek (0-100%)
    3: vlc_absolute_seek_knob,

    # Knob 4 - VLC video jog/shuttle
    4: vlc_jog_knob,

    # Knob 5 - MPV scrub
    5: mpv_seek_scrub_knob,

    # Knob 8 - Volume
    8: volume_knob,
}


# ============================================================
# MIDI message handler
# ============================================================

def handle_message(msg):
    if msg.type == "note_on":

        if msg.velocity == 0:
            action = PAD_RELEASE.get(msg.note)

            if action:
                action()

            return

        action = PAD_PRESS.get(msg.note)

        if action:
            print(
                f"PAD PRESS: note={msg.note}, "
                f"velocity={msg.velocity}"
            )

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


# ============================================================
# Main
# ============================================================

def main():
    try:
        with mido.open_input(PORT_NAME) as inport:

            print(
                f"Listening on {PORT_NAME} — Ctrl+C to stop"
            )

            for msg in inport:
                handle_message(msg)

    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()