import queue
from unittest.mock import Mock

import pytest

from lib.input.presets import load_preset
from app.input.pygame_source import PygameInputThread, XboxGamepad
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


@pytest.mark.parametrize("driver", ["linux", "windows"])
@pytest.mark.parametrize(
    ("axes", "buttons", "expected"),
    [
        ([0.03, -0.03, -0.02, -0.03, -1, -1], [], NEUTRAL),
        ([0, 0, 0, 0, 1, -1], [], ControllerState(Button.ZL)),
        ([0, 0, 0, 0, -1, 1], [], ControllerState(Button.ZR)),
        ([0, 0, 1, 0, -1, -1], [], ControllerState(right=(1, 0))),
        ([0, 0, 0, -1, -1, -1], [], ControllerState(right=(0, 1))),
        ([0, -1, 0, 0, -1, -1], [], ControllerState(left=(0, 1))),
        ([0, 0, 0, 0, -1, -1], [11], ControllerState(Button.UP)),
        ([0, 0, 0, 0, -1, -1], [5], ControllerState(Button.HOME)),
        ([0, 0, 0, 0, -1, -1], [7], ControllerState(Button.STICK_L)),
        ([0, 0, 0, 0, -1, -1], [8], ControllerState(Button.STICK_R)),
    ],
)
def test_builtin_xbox_uses_sdl_mapping(monkeypatch, driver, axes, buttons, expected):
    from app.input import pygame_source as source

    # The same physical positions have different raw axis indices per driver.
    order = (0, 1, 3, 4, 2, 5) if driver == "linux" else (0, 1, 2, 3, 4, 5)
    raw = [0.0] * 6
    for index, value in zip(order, axes):
        raw[index] = value
    stick = Mock(wraps=XboxJoystick(raw, (0, 0)))
    stick.get_name = Mock(return_value="Xbox")
    stick.init = Mock()
    stick.quit = Mock()

    def mapped_axis(index):
        value = raw[order[index]]
        return round(((value + 1) / 2 if index >= 4 else value) * 32767)

    gamepad = Mock()
    gamepad.get_axis.side_effect = mapped_axis
    gamepad.get_button.side_effect = lambda index: index in buttons
    monkeypatch.setattr(source, "pygame_init", lambda: None)
    monkeypatch.setattr(source.joystick, "get_count", lambda: 1)
    monkeypatch.setattr(source.joystick, "Joystick", lambda _: stick)
    monkeypatch.setattr(source.sdl_controller, "init", lambda: None)
    monkeypatch.setattr(source.sdl_controller, "is_controller", lambda _: True)
    monkeypatch.setattr(source.sdl_controller, "Controller", lambda _: gamepad)
    states = queue.Queue()
    capture = PygameInputThread(states, preset=load_preset("xbox"), pump=False)
    monkeypatch.setattr(source.time, "sleep", lambda _: capture.stop())
    capture.run()
    assert states.get_nowait() == expected
    assert states.empty()
    gamepad.quit.assert_called_once()
    stick.quit.assert_called_once()


def test_custom_xbox_presets_keep_raw_indices(tmp_path):
    from lib.input.presets import BUILTIN_PRESETS_DIR, PresetConfig

    path = tmp_path / "custom-xbox.json"
    path.write_bytes((BUILTIN_PRESETS_DIR / "xbox.json").read_bytes())
    assert load_preset("xbox").standard_gamepad
    assert PresetConfig.default().standard_gamepad
    assert not load_preset(path).standard_gamepad


def test_sdl_sticks_clamp_negative_endpoint_and_rumble():
    pad = Mock()
    pad.get_axis.return_value = -32768
    stick = Mock()
    source = XboxGamepad(pad, stick)
    assert source.get_axis(0) == -1
    source.rumble(0.5, 0.25, 100)
    stick.rumble.assert_called_once_with(0.5, 0.25, 100)
    source.stop_rumble()
    stick.stop_rumble.assert_called_once()
