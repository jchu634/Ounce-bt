from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag

from lib.controller import ControllerTypes, ControllerVariant
from lib.input.stick import PRO_LEFT, PRO_RIGHT, calibrate_stick


class Button(IntFlag):
    """
    Switch Pro Controller buttons as a single 24-bit bitmask.

    The bytes map directly to the standard input report (report[4..6]):

        bits  0-7  -> report[4]
        bits  8-15 -> report[5]
        bits 16-23 -> report[6]
    """

    # --- byte 1 -> report[4] ---
    Y = 1 << 0
    X = 1 << 1
    B = 1 << 2
    A = 1 << 3
    SR_R = 1 << 4  # Joy-Con only
    SL_R = 1 << 5  # Joy-Con only
    R = 1 << 6
    ZR = 1 << 7

    # --- byte 2 -> report[5] ---
    MINUS = 1 << 8
    PLUS = 1 << 9
    STICK_L = 1 << 10  # left stick click
    STICK_R = 1 << 11  # right stick click
    HOME = 1 << 12
    CAPTURE = 1 << 13

    # --- byte 3 -> report[6] ---
    DOWN = 1 << 16
    UP = 1 << 17
    RIGHT = 1 << 18
    LEFT = 1 << 19
    SR_L = 1 << 20  # Joy-Con only
    SL_L = 1 << 21  # Joy-Con only
    L = 1 << 22
    ZL = 1 << 23

    # Side-independent aliases for macros and on-screen rail buttons.
    SL = SL_L | SL_R
    SR = SR_L | SR_R

    NONE = 0

    @staticmethod
    def by_name(name: str) -> Button:
        """Look up a button by its enum name (case-insensitive)."""
        return Button[name.strip().upper()]


@dataclass(frozen=True, slots=True)
class ControllerState:
    """
    Device-agnostic snapshot of a controller's instantaneous state.

    Sticks are normalized to the [-1.0, 1.0] range with the usual
    convention: X positive = right, Y positive = up.
    """

    buttons: Button = Button.NONE
    left: tuple[float, float] = (0.0, 0.0)
    right: tuple[float, float] = (0.0, 0.0)


NEUTRAL = ControllerState()


JOYCON_BUTTONS = {
    ControllerTypes.JOYCON_L: (
        Button.UP | Button.DOWN | Button.LEFT | Button.RIGHT | Button.MINUS
        | Button.CAPTURE | Button.STICK_L | Button.L | Button.ZL | Button.SL_L | Button.SR_L
    ),
    ControllerTypes.JOYCON_R: (
        Button.A | Button.B | Button.X | Button.Y | Button.PLUS | Button.HOME
        | Button.STICK_R | Button.R | Button.ZR | Button.SL_R | Button.SR_R
    ),
}

# Position on a horizontal gamepad -> the Joy-Con's native HID button.
HORIZONTAL_BUTTONS = {
    ControllerVariant.LEFT: {
        Button.A: Button.DOWN, Button.B: Button.LEFT,
        Button.X: Button.RIGHT, Button.Y: Button.UP,
        Button.L: Button.SL_L, Button.R: Button.SR_L,
        Button.ZR: Button.L, Button.PLUS: Button.MINUS,
        Button.HOME: Button.CAPTURE,
    },
    ControllerVariant.RIGHT: {
        Button.A: Button.X, Button.B: Button.A,
        Button.X: Button.Y, Button.Y: Button.B,
        Button.L: Button.SL_R, Button.R: Button.SR_R,
        Button.ZL: Button.R, Button.MINUS: Button.PLUS,
        Button.STICK_L: Button.STICK_R,
    },
}


def horizontal_manual_input(state: ControllerState, variant: ControllerVariant) -> ControllerState:
    targets = HORIZONTAL_BUTTONS.get(variant)
    if targets is None:
        return state
    buttons = Button.NONE
    for button in Button:
        if button & state.buttons:
            if button in (Button.L, Button.R, Button.ZL, Button.ZR):
                buttons |= button
            else:
                buttons |= targets.get(button, button)
    right = state.right
    if variant == ControllerVariant.RIGHT and right == NEUTRAL.right:
        right = state.left
    return ControllerState(buttons, state.left, right)


def rotate_joycon_stick(state: ControllerState, variant: ControllerVariant) -> ControllerState:
    # Input is in the player's horizontal coordinates. HID coordinates use
    # the upright orientation, with rails facing toward each other.
    if variant == ControllerVariant.LEFT:
        x, y = state.left
        return ControllerState(state.buttons, (y, -x))
    if variant == ControllerVariant.RIGHT:
        x, y = state.right
        return ControllerState(state.buttons, right=(-y, x))
    return state


def apply_to_protocol(protocol, state: ControllerState) -> None:
    """
    Push a controller state onto a Switch ControllerProtocol.
    """
    controller_type = getattr(protocol, "controller_type", ControllerTypes.PRO_CONTROLLER)
    mask = JOYCON_BUTTONS.get(controller_type)
    b = int(state.buttons if mask is None else state.buttons & mask)
    protocol.set_button_inputs(b & 0xFF, (b >> 8) & 0xFF, (b >> 16) & 0xFF)
    if controller_type != ControllerTypes.JOYCON_R:
        protocol.set_left_stick_inputs(calibrate_stick(state.left, PRO_LEFT))
    if controller_type != ControllerTypes.JOYCON_L:
        protocol.set_right_stick_inputs(calibrate_stick(state.right, PRO_RIGHT))
