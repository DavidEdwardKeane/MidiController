import time

fine_scrub = False

_scrub_state = {5: {"value": None, "time": None}}


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

    elapsed = 0.1 if previous_time is None else now - previous_time
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
