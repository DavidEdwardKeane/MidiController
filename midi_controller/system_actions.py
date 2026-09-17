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
