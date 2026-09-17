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
