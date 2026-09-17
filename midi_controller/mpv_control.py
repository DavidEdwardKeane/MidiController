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
