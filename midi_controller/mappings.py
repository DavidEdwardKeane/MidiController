from .keyboard_actions import make_shift_key_action
from .mpv_control import send_mpv_command, mpv_seek_scrub_knob, toggle_or_launch_mpv, mpv_save_and_quit
from .vlc_control import (
    VIDEO_VLC,
    video_toggle_and_raise,
    vlc_absolute_seek_knob,
    vlc_jog_knob,
)
from .scrub import fine_scrub_press, fine_scrub_release
from .system_actions import make_monitor_toggle_action, toggle_mute, restart_obs, volume_knob

PAD_PRESS = {
    36: toggle_or_launch_mpv,
    37: send_mpv_command(["playlist-next"]),
    38: make_shift_key_action("v"),
    39: video_toggle_and_raise,
    40: mpv_save_and_quit,
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
