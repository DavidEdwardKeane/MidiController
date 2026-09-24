import sys

import threading
import time

import mido

from .mappings import PAD_PRESS_BY_MODE, PAD_PRESS_FIXED, PAD_RELEASE, PAD_PROGRAM_PRESS, CC_HANDLERS
from .vlc_control import stop_video_jog
from .scrub import fine_scrub_release

_outport = None
_current_mode = 1

MODE_NOTES = {1: 36, 2: 37, 3: 38, 4: 39}
MODE_PROGRAMS = {4: 1, 5: 2, 6: 3, 7: 4}


def find_port():
    for name in mido.get_input_names():
        if "LPD8" in name:
            return name
    raise RuntimeError("LPD8 not found — is it connected?")


def get_outport():
    global _outport
    if _outport is None:
        for name in mido.get_output_names():
            if "LPD8" in name:
                _outport = mido.open_output(name)
                break
    return _outport


def light_pad(note, on=True):
    outport = get_outport()
    if outport is None:
        return
    if on:
        outport.send(mido.Message('note_on', note=note, velocity=127))
    else:
        outport.send(mido.Message('note_off', note=note))


def apply_mode_leds():
    for mode, note in MODE_NOTES.items():
        light_pad(note, on=(mode == _current_mode))


_led_retry_stop = None


def set_mode(n):
    global _current_mode, _led_retry_stop

    stop_video_jog()
    fine_scrub_release()

    _current_mode = n

    if _led_retry_stop is not None:
        _led_retry_stop.set()

    stop_event = threading.Event()
    _led_retry_stop = stop_event

    def retry_leds():
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and not stop_event.is_set():
            apply_mode_leds()
            time.sleep(0.2)

    threading.Thread(target=retry_leds, daemon=True).start()

    print(f"Mode: {n}")


def handle_message(msg):
    if msg.type == "note_on":
        if msg.velocity == 0:
            action = PAD_RELEASE.get(msg.note)
            if action:
                action()
            return

        apply_mode_leds()

        action = PAD_PRESS_BY_MODE.get(_current_mode, {}).get(msg.note) or PAD_PRESS_FIXED.get(msg.note)
        if action:
            print(f"PAD PRESS: note={msg.note}, velocity={msg.velocity}, mode={_current_mode}")
            action()

    elif msg.type == "note_off":
        action = PAD_RELEASE.get(msg.note)
        if action:
            action()
        if msg.note in MODE_NOTES.values():
            apply_mode_leds()

    elif msg.type == "control_change":
        handler = CC_HANDLERS.get(msg.control)
        if handler:
            handler(msg.value)

    elif msg.type == "program_change":
        print(f"PROGRAM CHANGE: program={msg.program}")

        if msg.program in MODE_PROGRAMS:
            set_mode(MODE_PROGRAMS[msg.program])
            return

        action = PAD_PROGRAM_PRESS.get(msg.program)
        if action:
            action()


def main():
    try:
        port_name = find_port()
        with mido.open_input(port_name) as inport:
            print(f"Listening on {port_name} — Ctrl+C to stop")
            set_mode(1)
            for msg in inport:
                handle_message(msg)
    except KeyboardInterrupt:
        sys.exit(0)