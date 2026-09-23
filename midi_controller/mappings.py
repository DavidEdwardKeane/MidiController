from .keyboard_actions import make_key_action
from .mpv_control import send_mpv_command, mpv_seek_scrub_knob, toggle_or_launch_mpv, mpv_save_and_quit
from .vlc_control import (
    VIDEO_VLC,
    video_toggle_and_raise,
    vlc_absolute_seek_knob,
    vlc_jog_knob,
)
from .system_actions import make_monitor_toggle_action, toggle_mute, restart_obs, volume_knob

PAD_PRESS_BY_MODE = {
    1: {  # VLC video
        36: video_toggle_and_raise,
        37: lambda: VIDEO_VLC.rc_send("seek -4"),  # short jump back
        38: make_key_action('v'),                    # cycle subtitle track
        39: make_key_action('b'),                     # cycle audio track
        40: VIDEO_VLC.save_and_quit,
    },
    2: {  # MPV
        36: toggle_or_launch_mpv,
        37: send_mpv_command(["playlist-next"]),
        40: mpv_save_and_quit,
        # P3/P4 left blank per spec
    },
    3: {},  # Karaoke (Ultrastar Deluxe) — placeholder
    4: {},  # System actions — placeholder
}

PAD_PRESS_FIXED = {}

PAD_RELEASE = {}

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