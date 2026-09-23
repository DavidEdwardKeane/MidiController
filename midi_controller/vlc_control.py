import os
import socket
import subprocess
import threading
import time
import json

from .config import VIDEO_VLC_CONFIG


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
                    all_state = json.load(f)
                entry = all_state.get(self.name)
                if entry:
                    resume_time = entry.get("time")
                    resume_index = entry.get("index")
            except (OSError, json.JSONDecodeError):
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

                playlist_resp = ""
                s.settimeout(5.0)
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    try:
                        chunk = s.recv(8192)
                        if not chunk:
                            break
                        playlist_resp += chunk.decode(errors="replace")
                        if playlist_resp.rstrip().endswith(">"):
                            break
                    except socket.timeout:
                        break

            if current_time and current_index:
                all_state = {}
                if os.path.exists(self.resume_file):
                    try:
                        with open(self.resume_file) as f:
                            all_state = json.load(f)
                    except (OSError, json.JSONDecodeError):
                        all_state = {}

                all_state[self.name] = {
                    "time": current_time,
                    "index": current_index,
                }

                with open(self.resume_file, "w") as f:
                    json.dump(all_state, f)

                print(f"VLC [{self.name}]: saved resume state -> {self.resume_file}")
            else:
                print(f"VLC [{self.name}]: no time/index captured, resume not saved (time={current_time}, index={current_index})")
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


def stop_video_jog():
    _vlc_jog_stop_repeat()


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
