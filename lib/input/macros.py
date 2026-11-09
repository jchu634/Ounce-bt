from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from lib.input.state import Button

VALID_BUTTONS = frozenset(b.name for b in Button if b.name)
MACRO_VERSION = 1


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
        where = "".join(
            f"[{p}]" if isinstance(p, int) else f".{p}" for p in path
        ).lstrip(".")
        super().__init__(f"{where or '<root>'}: {message}" if where else message)


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
