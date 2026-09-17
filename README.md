# LPD8 Media & Desktop Controller

A Python-based MIDI controller mapper for the **Akai LPD8**, turning its pads and knobs into a physical control surface for **VLC (audio and video, as two independent instances)**, **MPV**, system audio, OBS, screenshots, and monitor power control.

The mapper listens for MIDI messages from the LPD8 and translates them into application commands (via VLC's RC interface and MPV's IPC socket), keyboard shortcuts, or system actions.

## Features

- 🎬 **VLC — two independent instances**
  - **Audio instance:** launch/toggle, save position + quit
  - **Video instance:** launch/toggle + raise window, save position + quit
  - Absolute seeking, jog/shuttle control, frame-by-frame stepping
  - Subtitle toggle
  - Resume playback position (time + playlist item) on next launch, per instance
- 🎵 **MPV control**
  - Play/pause, next/previous track, quit
  - Speed-sensitive scrubbing, with a fine 1-second-per-step modifier
- 🔊 **System audio** — volume control, mute toggle
- 🖥️ **Desktop control** — toggle secondary monitors via DPMS, screenshots via Spectacle
- 🎥 **OBS** — restart via a user-provided script

## Why two VLC instances

VLC has one playhead per process — one current item, one play/pause/stop state. Running audio and video as two separate VLC processes, each with its own RC interface on a distinct port, lets a pad independently start/stop one without touching the other. A single VLC instance can't do this: stopping "the playlist" stops the only thing it's playing.

## Hardware Layout

```
Top:       P5  P6  P7  P8   | K1  K2  K3  K4
Bottom:    P1  P2  P3  P4   | K5  K6  K7  K8
```

Three operating modes, switched via the corresponding buttons on the device:

- **PAD** — note messages
- **PROG CHNG** — program-change messages
- **CC** — control-change messages

---

## Project Structure

```
MidiController/
├── lpd8_mapper.py              # entry point only
├── midi_listen.py              # standalone debug utility — dumps raw MIDI messages
├── install.sh                  # generates the package below from scratch
└── midi_controller/
    ├── __init__.py
    ├── config.py                # paths, ports, playlists — all constants
    ├── keyboard_actions.py      # make_key_action, make_shift_key_action
    ├── system_actions.py        # screenshot, monitor toggle, mute, OBS restart, volume
    ├── scrub.py                 # scrub_delta, scrub_seconds, fine_scrub state
    ├── mpv_control.py           # MPV IPC functions
    ├── vlc_control.py           # VLCInstance class, AUDIO_VLC/VIDEO_VLC, jog/seek knobs
    ├── mappings.py              # PAD_PRESS / PAD_RELEASE / PAD_PROGRAM_PRESS / CC_HANDLERS
    └── dispatcher.py            # find_port, handle_message, main()
```

---

## Installation

### Requirements

- Linux desktop (developed against KDE Plasma; `kscreen-doctor` and `spectacle` are KDE-specific)
- An Akai LPD8 connected over USB
- `mpv`, `vlc`, `pactl`, `spectacle`, `kscreen-doctor`, `xdotool`
- An OBS restart script (user-provided, executable)
- Python packages: `mido`, `pynput`, and a MIDI backend (`python-rtmidi`)

```
python3 -m pip install mido pynput python-rtmidi
```

Debian/Ubuntu-based systems may prefer the system packages instead:

```
sudo apt install python3-mido python3-pynput python3-rtmidi
```

### Building the package

`install.sh` generates the full `midi_controller/` package (all files listed above) plus the thin `lpd8_mapper.py` entry point from scratch, writing everything under a hard-coded `BASE` path near the top of the script. Edit `BASE` to match your environment, then:

```
bash install.sh
```

This is idempotent — rerunning it regenerates every file from the same source-of-truth content, overwriting any local edits.

---

## Configuration

Constants live in `midi_controller/config.py`:

```python
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
```

Change these paths, ports, and playlists to match your system — they're hard-coded, not read from environment variables.

### VLC — audio instance

Launched with `--intf dummy` (no RC-interface overlap issues) and a fixed small window (`400x400`) so embedded cover art has somewhere to render. If a file lacks embedded art, VLC just shows its default placeholder in that window.

### VLC — video instance

Launched `--fullscreen`, subtitles suppressed by default (`--no-spu`; toggle via P3), hardware decode disabled (`--avcodec-hw=none`).

### VLC resume state

Each instance has its own resume file (`resume_file` in its config). On save-and-quit, the current playback time and playlist index are written there; on next launch, that instance seeks back to the saved position before playback resumes. The two instances never share state.

### Window raising (video only)

`raise_window()` uses `xdotool` to bring the video instance's window to the front by its tracked PID — this requires an X11 session. On Wayland it will silently fail unless swapped for a Wayland-native equivalent (e.g. `kdotool` under KWin), which isn't implemented here.

---

## Pad Mapping — PAD / Note Mode

| Pad | Note | Action |
| --- | ---- | ------ |
| P1 | 36 | VLC **audio**: launch/toggle |
| P2 | 37 | MPV next track |
| P3 | 38 | VLC subtitle toggle (simulated Shift+V) |
| P4 | 39 | VLC **video**: launch/toggle + raise window |
| P5 | 40 | VLC **audio**: save position + quit |
| P6 | 41 | MPV previous track |
| P7 | 42 | Hold for fine MPV scrubbing |
| P8 | 43 | VLC **video**: save position + quit |

MPV's own play/pause pad from the earlier single-instance design was reassigned to VLC audio control — if you still want a dedicated MPV toggle pad, it isn't currently mapped anywhere.

## Pad Mapping — PROG CHNG Mode

| Pad | Program | Action |
| --- | ------- | ------ |
| P1 | 0 | Toggle secondary monitors |
| P2 | 1 | Toggle system mute |
| P3 | 2 | Restart OBS |
| P4 | 3 | Toggle secondary monitors (shares state with P1) |
| P5 | 4 | **UNSET** |
| P6 | 5 | **UNSET** |
| P7 | 6 | **UNSET** |
| P8 | 7 | **UNSET** |

Programs 4–7 are deliberately unmapped — the interface was pared back rather than filled in.

## Knob Mapping — CC Mode

| Knob | CC | Action |
| ---- | -- | ------ |
| K3 | 3 | VLC (video) absolute seek, 0–100% |
| K4 | 4 | VLC (video) jog/shuttle |
| K5 | 5 | MPV speed-sensitive scrub |
| K8 | 8 | System volume, 0–100% |

K1, K2, K6, K7 are unused.

### K4 — jog/shuttle zones

| MIDI value | Zone | Behaviour |
| ---------- | ---- | --------- |
| 0–15 | Fast fast rewind | Repeated `-10s` seeks |
| 16–31 | Fast rewind | Repeated `-3s` seeks |
| 32–47 | Slow rewind | Repeated `-1s` seeks |
| 48–79 | Normal | Normal playback |
| 80–95 | Step forward | Frame-by-frame advance, speed follows knob position |
| 96–111 | Fast forward | 2× rate |
| 112–127 | Fast fast forward | 4× rate |

VLC doesn't reliably support negative playback rates, so rewind is simulated via repeated backward seeks rather than a negative rate.

### K5 — MPV scrub speed curve

| Knob movement speed | Seek per MIDI step |
| -------------------- | ------------------- |
| < 2 steps/sec | 1 second |
| < 5 steps/sec | 2 seconds |
| < 10 steps/sec | 5 seconds |
| < 20 steps/sec | 15 seconds |
| ≥ 20 steps/sec | 30 seconds |

Hold P7 for fine mode: exactly 1 second per MIDI step, regardless of speed.

---

## Running

```
python3 lpd8_mapper.py
```

The mapper searches available MIDI input ports for one whose name contains `LPD8`. On success:

```
Listening on <port name> — Ctrl+C to stop
```

Stop with `Ctrl+C`.

### Debugging raw MIDI

`midi_listen.py` is a separate, standalone script — not used by the mapper — that connects to a hard-coded port name and prints every incoming MIDI message verbatim. Useful for checking exact note/CC/program numbers your device sends, or confirming the port name matches what `find_port()` expects:

```
python3 midi_listen.py
```

Edit the `PORT` constant at the top of the file if your device enumerates under a different name.

---

## Autostart (systemd user service)

```
~/.config/systemd/user/lpd8-mapper.service
```

```ini
[Unit]
Description=Akai LPD8 Controller
After=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 /path/to/lpd8_mapper.py
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

```
systemctl --user daemon-reload
systemctl --user enable --now lpd8-mapper.service
systemctl --user status lpd8-mapper.service
journalctl --user -u lpd8-mapper.service -f
```

**Caution:** an unguarded dependency failure (e.g. `xdotool` missing) throws an unhandled exception that kills the *entire* service, not just the failing action — systemd then restart-loops it. Confirm all required external commands are installed before relying on the service; a crash loop here also leaves orphaned VLC processes running untracked, since each restart starts with no memory of the previous instance's `self.process`.

---

## Troubleshooting

**`LPD8 not found`** — list MIDI inputs and confirm the device appears:

```
python3 -c "import mido; print(mido.get_input_names())"
```

Install the RtMidi backend if missing: `python3 -m pip install python-rtmidi`.

**VLC controls do nothing** — confirm the relevant instance is listening on its configured port:

```
ss -ltn | grep -E '4212|4213'
```

If VLC was started manually without `--extraintf=rc` on the matching port, the mapper can't reach it.

**Video window doesn't raise** — confirm `xdotool` is installed and you're on X11 (`echo $XDG_SESSION_TYPE`); this feature has no Wayland equivalent implemented.

**Monitor toggle does nothing** — check actual output names:

```
kscreen-doctor output
```

The script expects `DP-1` and `DP-2`; update `system_actions.py` if your outputs use different names.

**Volume control does nothing** — test the sink directly:

```
pactl get-default-sink
pactl set-sink-volume @DEFAULT_SINK@ 50%
```

**Screenshot does nothing** — test Spectacle directly:

```
spectacle -b -o /tmp/test-screenshot.png -m -n
```

---

## Known limitations

- Hard-coded, user-specific absolute paths throughout `config.py` — must be edited before use on another machine.
- `xdotool`-based window raising requires X11; no Wayland path exists yet.
- PROG CHNG programs 4–7 are intentionally unmapped.
- `save_and_quit()` blocks the calling thread for up to ~3 seconds if VLC doesn't respond to `SIGTERM` promptly, before falling back to `SIGKILL`. Since this runs inside the MIDI message-handling loop, a hung VLC process delays processing of the next pad/knob event for that window.
- Thread safety for VLC RC commands is enforced via a per-instance `threading.Lock()`, since the jog/shuttle repeat thread and other actions may issue commands concurrently.

---

## License

Released into the public domain under The Unlicense. See the `LICENSE` file for full text.
