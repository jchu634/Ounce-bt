import queue

import pytest

from lib.input.presets import load_preset
from app.input.pygame_source import PygameInputThread
from lib.input.state import NEUTRAL, Button, ControllerState


class XboxJoystick:
    """SDL layout reported by the Windows Xbox Series X driver."""

    def __init__(self, axes, hat):
        self.axes = axes
        self.hat = hat

    def get_numaxes(self):
        return 6

    def get_numbuttons(self):
        return 16

    def get_numhats(self):
        return 1

    def get_axis(self, index):
        return self.axes[index]

    def get_button(self, index):
        return False

    def get_hat(self, index):
        return self.hat


@pytest.mark.parametrize(
    ("axes", "hat", "expected"),
    [
        ([0, 0, 0, 0, -1, -1], (0, 0), NEUTRAL),
        ([0, 0, 0, 0, 1, -1], (0, 0), ControllerState(Button.ZL)),
        ([0, 0, 0, 0, -1, 1], (0, 0), ControllerState(Button.ZR)),
        ([0, 0, 1, 0, -1, -1], (0, 0), ControllerState(right=(1, 0))),
        ([0, 0, 0, -1, -1, -1], (0, 0), ControllerState(right=(0, 1))),
        ([0, -1, 0, 0, -1, -1], (0, 0), ControllerState(left=(0, 1))),
        ([0, 0, 0, 0, -1, -1], (0, 1), ControllerState(Button.UP)),
    ],
)
def test_xbox_inputs_and_release(monkeypatch, axes, hat, expected):
    states = queue.Queue()
    capture = PygameInputThread(states, preset=load_preset("xbox"), pump=False)
    stick = XboxJoystick(axes, hat)

    def next_frame(_period):
        if states.qsize() == 1:
            stick.axes = [0, 0, 0, 0, -1, -1]
            stick.hat = (0, 0)
        else:
            capture.stop()

    monkeypatch.setattr("app.input.pygame_source.time.sleep", next_frame)
    capture._loop(stick)

    assert states.get_nowait() == expected
    assert states.get_nowait() == NEUTRAL
    assert states.empty()
