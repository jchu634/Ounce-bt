"""Load, validate, save, and select controller mappings from built-in and custom JSON presets."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from lib.controller import ControllerVariant
from lib.input.sdl3_backend import GAMEPAD_BUTTONS, GAMEPAD_STICKS, GAMEPAD_TRIGGERS
from lib.input.state import HORIZONTAL_BUTTONS, JOYCON_BUTTONS, Button

logger = logging.getLogger("switch_pair")

BUILTIN_PRESETS_DIR = Path(__file__).resolve().parents[2] / "presets"
PRESETS_DIR = BUILTIN_PRESETS_DIR
BUILTIN_PRESETS = frozenset({"xbox", "playstation", "switch"})
PRESET_VERSION = 2

VALID_BUTTON_INPUTS = frozenset(GAMEPAD_BUTTONS)
VALID_TRIGGER_INPUTS = frozenset(GAMEPAD_TRIGGERS)
VALID_STICK_INPUTS = frozenset(GAMEPAD_STICKS)

StickSide = Literal["left", "right"]

# SDL GUIDs store the USB vendor ID as a little-endian 16-bit value at bytes 4-5.
_VENDOR_PRESETS = {
    "5e04": "xbox",
    "4c05": "playstation",
    "7e05": "switch",
}

_GAMEPAD_TYPE_PRESETS = {
    "xbox360": "xbox",
    "xboxone": "xbox",
    "ps3": "playstation",
    "ps4": "playstation",
    "ps5": "playstation",
    "switch_pro": "switch",
    "joycon_l": "switch",
    "joycon_r": "switch",
    "joycon_pair": "switch",
}

_WRITE_LOCK = threading.Lock()


def _preset_doc_path(name: str) -> tuple[str, Path]:
    """Validate an API-facing preset stem without importing the server
    package while this module itself is being initialised."""
    from lib.server.files import doc_path, validate_name

    clean_name = validate_name(name)
    return clean_name, doc_path(PRESETS_DIR, clean_name)


class PresetValidationError(ValueError):
    """A preset document failed semantic validation.

    ``path`` is the JSON path of the offending element, e.g.
    ``["mappings", "pro", "buttons", "south"]``.
    """

    def __init__(self, path: list[str | int], message: str):
        self.path = path
        self.message = message
        where = "".join(
            f"[{p}]" if isinstance(p, int) else f".{p}" for p in path
        ).lstrip(".")
        super().__init__(f"{where or '<root>'}: {message}" if where else message)


@dataclass(frozen=True, slots=True)
class PresetConfig:
    """Resolved, ready-to-use semantic SDL3 gamepad mapping preset."""

    name: str = "Default"
    rumble_enabled: bool = True
    motion_enabled: bool = True
    button_map: dict[str, Button] = field(default_factory=dict)
    trigger_map: dict[str, Button] = field(default_factory=dict)
    left_stick: StickSide | None = "left"
    right_stick: StickSide | None = "right"
    mappings: dict[ControllerVariant, PresetConfig] = field(default_factory=dict)

    def mapping_for(self, variant: ControllerVariant) -> PresetConfig:
        if variant == ControllerVariant.PRO:
            return self
        mapping = self.mappings.get(variant)
        if mapping is None:
            mapping = _default_mapping(self, variant)
        return mapping

    @classmethod
    def default(cls) -> PresetConfig:
        """Fallback preset matching canonical SDL3 positional gamepad layout."""
        return cls(
            name="Default",
            rumble_enabled=True,
            motion_enabled=True,
            button_map={
                "south": Button.B,
                "east": Button.A,
                "west": Button.Y,
                "north": Button.X,
                "left_shoulder": Button.L,
                "right_shoulder": Button.R,
                "back": Button.MINUS,
                "start": Button.PLUS,
                "left_stick": Button.STICK_L,
                "right_stick": Button.STICK_R,
                "guide": Button.HOME,
                "misc1": Button.CAPTURE,
                "dpad_up": Button.UP,
                "dpad_down": Button.DOWN,
                "dpad_left": Button.LEFT,
                "dpad_right": Button.RIGHT,
            },
            trigger_map={
                "left_trigger": Button.ZL,
                "right_trigger": Button.ZR,
            },
            left_stick="left",
            right_stick="right",
        )


def load_preset(source: str | Path) -> PresetConfig:
    """Load a preset by builtin name or filesystem path."""
    path = _resolve_preset_path(source)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"Preset {path} must be a JSON object")
    return validate_preset(data)


def validate_preset(data: dict) -> PresetConfig:
    """Validate a parsed preset document and build its config."""
    if not isinstance(data, dict):
        raise PresetValidationError([], "must be a JSON object")
    version = data.get("version")
    if type(version) is not int or version != PRESET_VERSION:
        raise PresetValidationError(["version"], f"must be {PRESET_VERSION}")
    if "name" in data and not isinstance(data["name"], str):
        raise PresetValidationError(["name"], "must be a string")
    for flag in ("rumble_enabled", "motion_enabled"):
        if flag in data and not isinstance(data[flag], bool):
            raise PresetValidationError([flag], "must be a boolean")

    mappings = data.get("mappings")
    if not isinstance(mappings, dict):
        raise PresetValidationError(["mappings"], "must be an object")
    for key in mappings:
        if key not in tuple(ControllerVariant):
            raise PresetValidationError(["mappings", key], "unknown controller variant")
    resolved = {}
    for variant in ControllerVariant:
        if variant not in mappings:
            raise PresetValidationError(["mappings", variant], "missing controller mapping")
        mapping = mappings[variant]
        if not isinstance(mapping, dict):
            raise PresetValidationError(["mappings", variant], "must be an object")
        try:
            _validate_mapping(mapping)
        except PresetValidationError as error:
            raise PresetValidationError(
                ["mappings", variant, *error.path], error.message
            ) from None
        resolved[variant] = _build_preset(mapping, data)
    pro = resolved.pop(ControllerVariant.PRO)
    return replace(pro, mappings=resolved)


def _validate_mapping(data: dict) -> None:
    for key, valid_inputs in (
        ("buttons", VALID_BUTTON_INPUTS),
        ("triggers", VALID_TRIGGER_INPUTS),
    ):
        raw = data.get(key, {})
        if not isinstance(raw, dict):
            raise PresetValidationError([key], "must be an object")
        for input_name, value in raw.items():
            path = [key, str(input_name)]
            if not isinstance(input_name, str) or input_name not in valid_inputs:
                allowed = ", ".join(sorted(valid_inputs))
                raise PresetValidationError(
                    path, f"unknown input {input_name!r} (valid: {allowed})"
                )
            if not isinstance(value, str):
                raise PresetValidationError(path, "must map to a button name")
            try:
                Button[value.strip().upper()]
            except KeyError:
                valid = ", ".join(sorted(b.name for b in Button if b.name))
                raise PresetValidationError(
                    path, f"unknown button {value!r} (valid: {valid})"
                ) from None

    sticks = data.get("sticks", {})
    if not isinstance(sticks, dict):
        raise PresetValidationError(["sticks"], "must be an object")
    for side, source in sticks.items():
        if side not in VALID_STICK_INPUTS:
            raise PresetValidationError(["sticks", str(side)], "must be 'left' or 'right'")
        if source is not None and (not isinstance(source, str) or source not in VALID_STICK_INPUTS):
            raise PresetValidationError(
                ["sticks", str(side)], "must be 'left', 'right', or null"
            )


def preset_name_is_builtin(name: str) -> bool:
    return name in BUILTIN_PRESETS


def read_preset_text(name: str) -> str:
    """Raw text of a preset by name (builtin or custom)."""
    _, path = _preset_doc_path(name)
    if name in BUILTIN_PRESETS and not path.is_file():
        path = BUILTIN_PRESETS_DIR / f"{name}.json"
    return path.read_text(encoding="utf-8")


def save_preset_text(name: str, contents: str) -> None:
    """Atomically write a custom preset. Builtin names are refused."""
    name, path = _preset_doc_path(name)
    if preset_name_is_builtin(name):
        raise PermissionError(
            f"'{name}' is a built-in preset and cannot be overwritten; "
            f"duplicate it under a new name instead"
        )
    with _WRITE_LOCK:
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(contents, encoding="utf-8")
        os.replace(tmp, path)


def delete_preset(name: str) -> None:
    name, path = _preset_doc_path(name)
    if preset_name_is_builtin(name):
        raise PermissionError(f"'{name}' is a built-in preset and cannot be deleted")
    if not path.is_file():
        raise FileNotFoundError(f"preset '{name}' does not exist")
    with _WRITE_LOCK:
        path.unlink()


def list_preset_infos() -> list[dict]:
    """Metadata for every available preset (builtins + customs)."""
    filenames = BUILTIN_PRESETS | {
        path.stem for path in PRESETS_DIR.glob("*.json") if path.is_file()
    }
    infos = []
    for filename in sorted(filenames):
        name = filename
        description = ""
        try:
            data = json.loads(read_preset_text(filename))
            if isinstance(data, dict):
                name = str(data.get("name", filename))
                description = str(data.get("description", ""))
        except (ValueError, OSError):
            description = "(unreadable)"
        infos.append({
            "name": name,
            "filename": filename,
            "builtin": filename in BUILTIN_PRESETS,
            "description": description,
        })
    return infos


@dataclass(frozen=True, slots=True)
class PresetSelection:
    """A preset together with the filename used to load it."""

    source: str
    config: PresetConfig


def detect_controller_preset(
    name: str, guid: str = "", gamepad_type: str = ""
) -> str:
    """Return the built-in preset that best matches an SDL3 controller."""
    if gamepad_type and (by_type := _GAMEPAD_TYPE_PRESETS.get(gamepad_type.casefold())):
        return by_type
    normalized_name = name.casefold()
    if any(
        marker in normalized_name
        for marker in (
            "dualsense",
            "dualshock",
            "playstation",
            "sony",
            "ps3",
            "ps4",
            "ps5",
        )
    ):
        return "playstation"
    if any(
        marker in normalized_name
        for marker in ("switch", "joy-con", "joycon", "nintendo")
    ):
        return "switch"
    if any(marker in normalized_name for marker in ("xbox", "x-box", "xinput")):
        return "xbox"

    normalized_guid = "".join(c for c in guid.casefold() if c in "0123456789abcdef")
    if len(normalized_guid) >= 12:
        vendor_preset = _VENDOR_PRESETS.get(normalized_guid[8:12])
        if vendor_preset is not None:
            return vendor_preset
    return "xbox"


def resolve_controller_preset(
    guid: str,
    name: str,
    saved_presets: dict[str, str] | None = None,
    gamepad_type: str = "",
) -> PresetSelection:
    """Load the saved GUID preset, or detect a built-in default."""
    normalized_guid = guid.casefold()
    saved_source = (saved_presets or {}).get(normalized_guid)
    detected_source = detect_controller_preset(name, guid, gamepad_type)
    sources = [saved_source, detected_source, "xbox"]
    tried: set[str] = set()
    for source in sources:
        if not source or source in tried:
            continue
        tried.add(source)
        try:
            return PresetSelection(source, load_preset(source))
        except (FileNotFoundError, ValueError, TypeError) as error:
            logger.warning(
                "Could not load preset %r for controller %r (%s): %s",
                source,
                name,
                guid,
                error,
            )
    return PresetSelection("xbox", PresetConfig.default())


def list_presets() -> list[str]:
    return [info["filename"] for info in list_preset_infos()]


def _resolve_preset_path(source: str | Path) -> Path:
    source = str(source).strip()
    if source in BUILTIN_PRESETS:
        path = PRESETS_DIR / f"{source}.json"
        return path if path.is_file() else BUILTIN_PRESETS_DIR / f"{source}.json"
    by_name = PRESETS_DIR / f"{source}.json"
    if by_name.is_file():
        return by_name
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(
            f"Preset not found: {source!r}. "
            f"Known builtins: {sorted(BUILTIN_PRESETS)}; "
            f"or provide a path to a JSON file."
        )
    return path


def _build_preset(data: dict, metadata: dict) -> PresetConfig:
    button_map = _parse_button_map(data.get("buttons") or {}, "buttons")
    trigger_map = _parse_button_map(data.get("triggers") or {}, "triggers")
    sticks = data.get("sticks") or {}
    left_stick = sticks.get("left", "left")
    right_stick = sticks.get("right", "right")

    return PresetConfig(
        name=metadata.get("name", "Unnamed"),
        rumble_enabled=metadata.get("rumble_enabled", True),
        motion_enabled=metadata.get("motion_enabled", True),
        button_map=button_map,
        trigger_map=trigger_map,
        left_stick=left_stick,
        right_stick=right_stick,
    )


def _default_mapping(pro: PresetConfig, variant: ControllerVariant) -> PresetConfig:
    if variant == ControllerVariant.COMBINED:
        return replace(pro, mappings={})
    targets = HORIZONTAL_BUTTONS[variant]
    mask = JOYCON_BUTTONS[variant.bluetooth_type]

    def translate(mapping: dict[str, Button]) -> dict[str, Button]:
        translated = {
            name: targets.get(button, button) for name, button in mapping.items()
        }
        return {name: button for name, button in translated.items() if button & mask}

    return replace(
        pro,
        button_map=translate(pro.button_map),
        trigger_map=translate(pro.trigger_map),
        left_stick=pro.left_stick if variant == ControllerVariant.LEFT else None,
        right_stick=pro.left_stick if variant == ControllerVariant.RIGHT else None,
        mappings={},
    )


def _parse_button_map(raw: dict, label: str) -> dict[str, Button]:
    result: dict[str, Button] = {}
    for input_name, value in raw.items():
        button_name = str(value).strip().upper()
        try:
            result[str(input_name)] = Button[button_name]
        except KeyError:
            valid = ", ".join(sorted(b.name for b in Button if b.name))
            raise ValueError(
                f"Unknown button name {value!r} in preset '{label}' "
                f"(input {input_name!r}). Valid names: {valid}"
            ) from None
    return result
