from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from lib.controller import ControllerVariant
from lib.input.state import JOYCON_BUTTONS, Button

MACRO_BUTTON_ALIASES = frozenset({"SL_OR_L", "SR_OR_R"})
VALID_BUTTONS = (frozenset(Button.__members__) - {"NONE"}) | MACRO_BUTTON_ALIASES
MACRO_VERSION = 1


def resolve_macro_button(
    name: str,
    variant: ControllerVariant = ControllerVariant.PRO,
) -> Button:
    """Resolve a macro button name for the target controller variant."""
    normalized = name.strip().upper()
    if normalized == "SL_OR_L":
        return Button.SL if variant.is_single_joycon else Button.L
    if normalized == "SR_OR_R":
        return Button.SR if variant.is_single_joycon else Button.R
    return Button.by_name(normalized)


def seed_default_macros(directory: Path) -> None:
    """Install the editable grip macro once in each macro directory."""
    marker = directory / ".grip-macro-initialized"
    if marker.exists():
        return
    directory.mkdir(parents=True, exist_ok=True)
    try:
        file = (directory / "Press SL and SR.json").open("x", encoding="utf-8")
    except FileExistsError:
        pass
    else:
        with file:
            json.dump({
                "version": MACRO_VERSION,
                "name": "Press SL and SR",
                "actions": [
                    {"do": "press", "button": "SL"},
                    {"do": "press", "button": "SR"},
                    {"do": "wait", "ms": 350},
                    {"do": "release", "button": "SR"},
                    {"do": "release", "button": "SL"},
                ],
            }, file, indent=2)
            file.write("\n")
    marker.touch()


def load_macro(path: str | Path) -> dict:
    """Load and minimally validate a JSON macro file."""
    with open(path, "r", encoding="utf-8") as f:
        macro = json.load(f)
    if not isinstance(macro, dict) or "actions" not in macro:
        raise ValueError("Macro JSON must be an object with an 'actions' list")
    if not isinstance(macro["actions"], list):
        raise ValueError("'actions' must be a list")
    return macro


class MacroValidationError(ValueError):
    """A macro failed semantic validation.

    ``path`` is the JSON path of the offending element, e.g.
    ``["actions", 3, "button"]`` so editors can locate the error in the
    source text.
    """

    def __init__(self, path: list[str | int], message: str):
        self.path = path
        self.message = message
        where = "".join(
            f"[{p}]" if isinstance(p, int) else f".{p}" for p in path
        ).lstrip(".")
        super().__init__(f"{where or '<root>'}: {message}" if where else message)


class MacroCapabilityError(MacroValidationError):
    """A valid macro uses a control missing from the selected controller."""


def validate_macro_capabilities(macro: dict, variant: ControllerVariant) -> None:
    """Check a structurally validated macro against the controller's native controls."""
    if variant == ControllerVariant.COMBINED:
        return
    if variant.is_single_joycon:
        buttons = JOYCON_BUTTONS[variant.bluetooth_type]
        sticks = {"left" if variant == ControllerVariant.LEFT else "right"}
    else:
        buttons = ~(Button.SL_L | Button.SR_L | Button.SL_R | Button.SR_R)
        sticks = {"left", "right"}

    def visit(actions: list, path: list[str | int]) -> None:
        for index, action in enumerate(actions):
            here = [*path, index]
            kind = action["do"]
            if kind in ("press", "release"):
                button = resolve_macro_button(action["button"], variant)
                if not button & buttons:
                    label = {
                        Button.STICK_L: "left stick click",
                        Button.STICK_R: "right stick click",
                        Button.SL_L: "left SL button",
                        Button.SR_L: "left SR button",
                        Button.SL_R: "right SL button",
                        Button.SR_R: "right SR button",
                    }.get(button, f"{button.name} button")
                    raise MacroCapabilityError(
                        [*here, "button"], f"{variant.bluetooth_name} has no {label}.",
                    )
            elif kind == "stick":
                side = action.get("side", "left")
                if side not in sticks:
                    raise MacroCapabilityError(
                        [*here, "side"], f"{variant.bluetooth_name} has no {side} stick.",
                    )
            elif kind == "loop":
                visit(action.get("actions", []), [*here, "actions"])

    visit(macro["actions"], ["actions"])


def _expect_number(value: Any, path: list[str | int], key: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise MacroValidationError(path, f"'{key}' must be a number")
    if not math.isfinite(float(value)):
        raise MacroValidationError(path, f"'{key}' must be finite")
    return float(value)


def validate_macro(macro: dict) -> dict:
    """Recursively validate a parsed macro document. Returns it unchanged.

    Raises :class:`MacroValidationError` on the first problem found.
    Mirrors exactly what :class:`MacroPlayerThread` can execute:
    ``press`` / ``release`` / ``wait`` / ``stick`` / nested ``loop``.
    """
    if macro.get("version") != MACRO_VERSION:
        raise MacroValidationError(
            ["version"], f"must be {MACRO_VERSION}"
        )

    if "actions" not in macro:
        raise MacroValidationError([], "missing required key 'actions'")
    if not isinstance(macro["actions"], list):
        raise MacroValidationError(["actions"], "must be a list")

    if "repeat" in macro:
        repeat = macro["repeat"]
        if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 0:
            raise MacroValidationError(
                ["repeat"], "must be a non-negative integer (0 = loop forever)"
            )

    if "name" in macro and not isinstance(macro["name"], str):
        raise MacroValidationError(["name"], "must be a string")

    _validate_actions(macro["actions"], ["actions"], depth=0)
    return macro


def _validate_actions(actions: list, path: list[str | int], depth: int) -> None:
    if depth > 16:
        raise MacroValidationError(path, "loops nested too deeply (max 16)")
    for i, action in enumerate(actions):
        action_path = [*path, i]
        if not isinstance(action, dict):
            raise MacroValidationError(action_path, "each action must be an object")
        kind = action.get("do")
        if kind == "press" or kind == "release":
            if "button" not in action:
                raise MacroValidationError(
                    action_path, f"'{kind}' requires a 'button'"
                )
            button = action["button"]
            if not isinstance(button, str) or button.strip().upper() not in VALID_BUTTONS:
                valid = ", ".join(sorted(VALID_BUTTONS))
                raise MacroValidationError(
                    [*action_path, "button"],
                    f"unknown button {button!r} for '{kind}' (valid: {valid})",
                )
        elif kind == "wait":
            if "unit" in action and action["unit"] not in ("ms", "seconds"):
                raise MacroValidationError(
                    [*action_path, "unit"], "must be 'ms' or 'seconds'"
                )
            ms = action.get("ms", 0)
            if not isinstance(ms, (int, float)) or isinstance(ms, bool):
                raise MacroValidationError(
                    [*action_path, "ms"], "'wait' duration must be a number"
                )
            if float(ms) < 0 or not math.isfinite(float(ms)):
                raise MacroValidationError(
                    [*action_path, "ms"], "'wait' duration must be >= 0"
                )
        elif kind == "stick":
            side = action.get("side", "left")
            if side not in ("left", "right"):
                raise MacroValidationError(
                    [*action_path, "side"], "must be 'left' or 'right'"
                )
            for key in ("x", "y"):
                _expect_number(action.get(key, 0.0), [*action_path, key], key)
        elif kind == "loop":
            count = action.get("count", 1)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise MacroValidationError(
                    [*action_path, "count"],
                    "must be a non-negative integer",
                )
            inner = action.get("actions", [])
            if not isinstance(inner, list):
                raise MacroValidationError(
                    [*action_path, "actions"], "'loop' actions must be a list"
                )
            _validate_actions(inner, [*action_path, "actions"], depth + 1)
        else:
            raise MacroValidationError(
                action_path,
                "unknown action (expected 'press', 'release', 'wait', 'stick' "
                "or 'loop')",
            )
