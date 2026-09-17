from pynput.keyboard import Controller, Key

keyboard = Controller()


def make_key_action(key):
    def action():
        keyboard.press(key)
        keyboard.release(key)
    return action


def make_shift_key_action(key):
    def action():
        keyboard.press(Key.shift)
        keyboard.press(key)
        keyboard.release(key)
        keyboard.release(Key.shift)
    return action
