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
