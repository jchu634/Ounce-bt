from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import threading
from dataclasses import asdict, dataclass, field, fields, replace
from hashlib import sha256
from pathlib import Path

from lib.colours import (
    DEFAULT_CONTROLLER_COLOURS,
    default_colours,
    normalize_controller_colours,
)
from lib.controller import ControllerVariant
from lib.device_names import normalize_device_names

logger = logging.getLogger("switch_pair")

APP_NAME = "ounce-bt"


def _normalize_controller_presets(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        guid.casefold(): preset
        for guid, preset in value.items()
        if isinstance(guid, str)
        and guid.strip()
        and isinstance(preset, str)
        and preset.strip()
    }


def _normalize_adapter_colours(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise TypeError("adapter_colours must be an object")
    return {
        transport.casefold(): normalize_controller_colours(colours)
        for transport, colours in value.items()
        if isinstance(transport, str) and transport.strip()
    }


def _config_dir() -> Path:
    """
    Locate the per-user config directory.

    Preference order: ``%APPDATA%`` (Windows), ``$XDG_CONFIG_HOME`` (POSIX),
    then ``~/.config``. Created on first save, not on read.
    """
    appdata = os.environ.get("APPDATA")
    if sys.platform == "win32" and appdata:
        return Path(appdata) / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def application_dir() -> Path:
    # PyInstaller keeps bundled assets beside its embedded Python libraries.
    if bundle := getattr(sys, "_MEIPASS", None):
        return Path(bundle)
    # Nuitka onefile extracts __file__ into a temporary directory. argv[0]
    # locates the executable and its external, writable configuration.
    if "__compiled__" in globals() or getattr(sys, "frozen", False):
        return Path(sys.argv[0]).resolve().parent
    return Path(__file__).resolve().parent.parent


def packaged_linux() -> bool:
    return sys.platform == "linux" and (
        "__compiled__" in globals() or getattr(sys, "frozen", False)
    )


def data_dir() -> Path:
    if sys.platform == "linux":
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
        return base / APP_NAME
    return application_dir()


def state_dir() -> Path:
    if sys.platform == "linux":
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        return base / APP_NAME
    return _config_dir()


def resolve_config_file(name: str) -> Path:
    path = Path(name).expanduser()
    if path.is_absolute():
        return path
    local = application_dir() / "config" / path
    return local if local.is_file() else _config_dir() / path


def config_path() -> Path:
    if packaged_linux():
        return _config_dir() / "config.json"
    return resolve_config_file("config.json")


def normalize_controller_bool_map(value: object, *, label: str = "controller_vibration") -> dict[str, bool]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not key.strip() or not isinstance(enabled, bool)
        for key, enabled in value.items()
    ):
        raise ValueError(f"{label} must map controller IDs to booleans")
    return {key.strip().casefold(): enabled for key, enabled in value.items()}


def normalize_controller_vibration(value: object) -> dict[str, bool]:
    return normalize_controller_bool_map(value, label="controller_vibration")


def normalize_controller_motion(value: object) -> dict[str, bool]:
    return normalize_controller_bool_map(value, label="controller_motion")


@dataclass(frozen=True)
class AdapterProfile:
    address: str
    controller_guid: str = ""
    preset: str = ""
    colours: dict[str, str] = field(default_factory=dict)
    legacy_keystore: bool = False
    controller_type: ControllerVariant = ControllerVariant.PRO
    combined_with: int | None = None
    joycon_colours: dict[str, dict[str, str]] = field(default_factory=dict)

    def colours_for(self, variant: ControllerVariant) -> dict[str, str]:
        if variant == ControllerVariant.PRO:
            return self.colours
        return self.joycon_colours.get(variant, default_colours(variant))


def new_profile_address(used: set[str]) -> str:
    while True:
        address = ":".join(f"{byte:02X}" for byte in b"\x02" + secrets.token_bytes(5))
        if address not in used:
            return address


def _valid_profile_address(address: object) -> bool:
    if not isinstance(address, str):
        return False
    parts = address.upper().split(":")
    return len(parts) == 6 and all(
        len(part) == 2 and all(c in "0123456789ABCDEF" for c in part) for part in parts
    )


def _adapter_profiles(value: object) -> list[AdapterProfile]:
    if not isinstance(value, list):
        raise TypeError("adapter_profiles must be an array")
    profiles = []
    addresses = set()
    for entry in value:
        if isinstance(entry, AdapterProfile):
            profile = entry
        elif isinstance(entry, dict):
            profile = AdapterProfile(**{key: value for key, value in entry.items() if key != "joycon_orientation"})
        else:
            raise TypeError("each adapter profile must be an object")
        if not _valid_profile_address(profile.address) or profile.address.upper() in addresses:
            raise ValueError("adapter profiles must have distinct Bluetooth addresses")
        address = profile.address.upper()
        if not isinstance(profile.controller_guid, str) or not isinstance(profile.preset, str):
            raise TypeError("adapter profile controller and preset must be strings")
        if not isinstance(profile.legacy_keystore, bool):
            raise TypeError("adapter profile legacy_keystore must be a boolean")
        variant = ControllerVariant(profile.controller_type)
        if variant == ControllerVariant.COMBINED:
            raise ValueError("an adapter profile must identify one Bluetooth controller")
        partner = profile.combined_with
        if partner is not None and (
            type(partner) is not int or not 0 <= partner < len(value) or partner == len(profiles)
        ):
            raise ValueError("invalid combined adapter index")
        if not isinstance(profile.joycon_colours, dict):
            raise TypeError("joycon_colours must be an object")
        joycon_colours = {}
        for side, palette in profile.joycon_colours.items():
            if side not in (ControllerVariant.LEFT, ControllerVariant.RIGHT):
                raise ValueError("invalid Joy-Con colour variant")
            joycon_colours[side] = normalize_controller_colours(
                palette, default_colours(ControllerVariant(side))
            )
        addresses.add(address)
        profiles.append(replace(
            profile, address=address, colours=normalize_controller_colours(profile.colours),
            controller_type=variant, joycon_colours=joycon_colours,
        ))
    for index, profile in enumerate(profiles):
        if profile.combined_with is not None:
            partner = profiles[profile.combined_with]
            if (
                partner.combined_with != index
                or {profile.controller_type, partner.controller_type}
                != {ControllerVariant.LEFT, ControllerVariant.RIGHT}
            ):
                raise ValueError("combined adapters must link a left and right Joy-Con")
    return profiles


@dataclass
class Config:
    """Runtime configuration. Add new fields here; defaults are picked up
    automatically when the on-disk file is missing keys."""

    web_host: str | None = "127.0.0.1"
    web_port: int | None = 9127
    webview_enabled: bool = True
    ws_auth_required: bool = True
    bt_address: str = ""
    adapter_address_seed: str = ""
    adapter_addresses: dict[str, str] = field(default_factory=dict)
    adapter_profiles: list[AdapterProfile] = field(default_factory=list)
    transport_spec: str = "usb:0"
    firmware_dir: str | None = None
    device_config: str = "pro_controller.json"
    input_specs: list[str] = field(default_factory=lambda: ["controller"])
    macros_dir: str = "macros"
    presets_dir: str = "presets"
    pairing_dir: str | None = None
    debug_enabled: bool = False
    bumble_logging: bool = True
    nolog: bool = False
    last_camera_device_id: str = ""
    tick_rate_hz: int = 132
    macro_rate_hz: int = 120
    preset: str = "xbox"
    vibration_enabled: bool = True
    controller_vibration: dict[str, bool] = field(default_factory=dict)
    motion_enabled: bool = True
    controller_motion: dict[str, bool] = field(default_factory=dict)
    controller_guid: str = ""
    controller_presets: dict[str, str] = field(default_factory=dict)
    controller_colours: dict[str, str] = field(default_factory=dict)
    adapter_colours: dict[str, dict[str, str]] = field(default_factory=dict)
    adapter_presets: dict[str, str] = field(default_factory=dict)
    switch_device_names: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.vibration_enabled, bool):
            raise TypeError("vibration_enabled must be a boolean")
        if not isinstance(self.motion_enabled, bool):
            raise TypeError("motion_enabled must be a boolean")
        self.controller_presets = _normalize_controller_presets(self.controller_presets)
        self.controller_vibration = normalize_controller_vibration(self.controller_vibration)
        self.controller_motion = normalize_controller_motion(self.controller_motion)
        self.controller_colours = normalize_controller_colours(self.controller_colours)
        self.adapter_colours = _normalize_adapter_colours(self.adapter_colours)
        self.adapter_presets = _normalize_controller_presets(self.adapter_presets)
        self.adapter_addresses = _normalize_controller_presets(self.adapter_addresses)
        self.adapter_profiles = _adapter_profiles(self.adapter_profiles)
        self.switch_device_names = normalize_device_names(self.switch_device_names)

    @property
    def web_enabled(self) -> bool:
        return bool(self.web_host and self.web_port)

    @staticmethod
    def _allows_controller_feature(
        global_enabled: bool, per_controller: dict[str, bool], guid: str | None
    ) -> bool:
        return global_enabled and per_controller.get((guid or "").casefold(), True)

    def allows_controller_vibration(self, guid: str | None) -> bool:
        return self._allows_controller_feature(
            self.vibration_enabled, self.controller_vibration, guid
        )

    def allows_controller_motion(self, guid: str | None) -> bool:
        return self._allows_controller_feature(
            self.motion_enabled, self.controller_motion, guid
        )

    def colours_for_adapter(self, transport: str, *, primary: bool) -> dict[str, str]:
        return self.controller_colours if primary else self.adapter_colours.get(
            transport.casefold(), DEFAULT_CONTROLLER_COLOURS
        )

    def resolve_folder(self, folder: str) -> Path:
        path = Path(folder).expanduser()
        root = data_dir() if packaged_linux() else application_dir()
        return path if path.is_absolute() else root / path

    @property
    def bluetooth_firmware_dir(self) -> Path:
        if self.firmware_dir:
            return self.resolve_folder(self.firmware_dir)
        return data_dir() / "firmware" if sys.platform == "linux" else application_dir()

    @classmethod
    def _valid_keys(cls) -> set[str]:
        return {f.name for f in fields(cls)}

    @classmethod
    def load(cls, overrides: dict | None = None) -> Config:
        """Load from disk, then apply ``overrides`` (CLI args typically).

        Unknown keys in the file are ignored so old configs don't break
        after a schema change. Missing keys pick up dataclass defaults.
        """
        path = config_path()
        data: dict = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise TypeError("config must be a JSON object")
            except (ValueError, TypeError, OSError) as e:
                logger.warning(f"Could not read config {path}: {e}; using defaults")
                data = {}
        if overrides:
            data = {**data, **overrides}
        valid = cls._valid_keys()
        nullable = {"web_host", "web_port", "pairing_dir", "firmware_dir"}
        filtered = {
            k: v
            for k, v in data.items()
            if k in valid and (v is not None or k in nullable)
        }
        for key, normalize in (
            ("controller_colours", normalize_controller_colours),
            ("adapter_colours", _normalize_adapter_colours),
            ("adapter_profiles", _adapter_profiles),
            ("controller_vibration", normalize_controller_vibration),
            ("controller_motion", normalize_controller_motion),
            ("switch_device_names", normalize_device_names),
        ):
            if key not in filtered:
                continue
            try:
                filtered[key] = normalize(filtered[key])
            except (TypeError, ValueError) as e:
                logger.warning(f"Invalid {key}: {e}; using defaults")
                del filtered[key]
        for flag in ("vibration_enabled", "motion_enabled"):
            if flag in filtered and not isinstance(filtered[flag], bool):
                logger.warning(f"Invalid {flag}; using default")
                del filtered[flag]
        config = cls(**filtered)
        config._path = path
        return config

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self) -> None:
        """Atomically persist current state to disk."""
        path = getattr(self, "_path", None) or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, sort_keys=True)
        os.replace(tmp, path)


class ConfigStore:
    """Thread-safe wrapper around a :class:`Config` instance.

    Holds a lock so request handlers can mutate the config from worker
    threads while the main loop reads it. The lock is reentrant so
    ``update`` can call ``save`` internally.
    """

    def __init__(self, config: Config):
        self._config = config
        self._lock = threading.RLock()

    @property
    def config(self) -> Config:
        # Reads of a reference are atomic; callers may read fields directly
        # without the lock for non-destructive inspection.
        return self._config

    def snapshot(self) -> dict:
        with self._lock:
            return self._config.to_dict()

    def ensure_adapter_profiles(
        self, transports: list[str], *, persist: bool = True
    ) -> list[AdapterProfile]:
        """Bind the active list to existing slots, importing legacy identities once."""
        with self._lock:
            config = self._config
            profiles = list(config.adapter_profiles)
            migrating = not profiles
            used = {profile.address for profile in profiles}
            for index in range(len(profiles), len(transports)):
                transport = transports[index]
                key = transport.casefold()
                address = config.adapter_addresses.get(key, "") if migrating else ""
                if migrating and not address:
                    if index == 0:
                        address = config.bt_address
                    elif seed := config.adapter_address_seed or config.bt_address:
                        suffix = sha256(f"{seed.upper()}/{transport}".encode()).digest()[:5]
                        address = ":".join(f"{byte:02X}" for byte in b"\x02" + suffix)
                address = address.upper()
                legacy_keystore = bool(migrating and index == 0 and address)
                if not _valid_profile_address(address) or address in used:
                    address = new_profile_address(used)
                    legacy_keystore = False
                used.add(address)
                colours = (
                    config.colours_for_adapter(transport, primary=index == 0)
                    if migrating else dict(DEFAULT_CONTROLLER_COLOURS)
                )
                profiles.append(AdapterProfile(
                    address,
                    controller_guid=config.controller_guid if migrating and index == 0 else "",
                    preset=config.adapter_presets.get(key, "") if migrating and index > 0 else "",
                    colours=colours,
                    legacy_keystore=legacy_keystore,
                ))
            if profiles != config.adapter_profiles:
                self._save_adapter_profiles(profiles, persist=persist)
            return profiles[:len(transports)]

    def update_adapter_profile(self, index: int, **changes) -> None:
        self.update_adapter_profiles({index: changes})

    def update_adapter_profiles(self, changes: dict[int, dict]) -> None:
        with self._lock:
            profiles = list(self._config.adapter_profiles)
            for index, fields in changes.items():
                profiles[index] = replace(profiles[index], **fields)
            if profiles != self._config.adapter_profiles:
                self._save_adapter_profiles(profiles)

    def _save_adapter_profiles(self, profiles: list[AdapterProfile], *, persist: bool = True) -> None:
        previous = self._config.adapter_profiles
        self._config.adapter_profiles = profiles
        if persist:
            try:
                self._config.save()
            except OSError:
                self._config.adapter_profiles = previous
                raise

    def update(self, changes: dict) -> dict:
        """Apply a partial update and persist. Returns the actually-changed
        key/value pairs (keys that were unknown or unchanged are skipped)."""
        for flag in ("vibration_enabled", "motion_enabled"):
            if flag in changes and not isinstance(changes[flag], bool):
                raise TypeError(f"{flag} must be a boolean")
        valid = Config._valid_keys()
        with self._lock:
            for key, normalize in (
                ("controller_vibration", normalize_controller_vibration),
                ("controller_motion", normalize_controller_motion),
            ):
                if key in changes:
                    changes = {
                        **changes,
                        key: {
                            **getattr(self._config, key),
                            **normalize(changes[key]),
                        },
                    }
            if "switch_device_names" in changes:
                changes = {
                    **changes,
                    "switch_device_names": normalize_device_names(
                        changes["switch_device_names"]
                    ),
                }
            if "controller_colours" in changes:
                changes = {
                    **changes,
                    "controller_colours": normalize_controller_colours(
                        changes["controller_colours"], self._config.controller_colours
                    ),
                }
            changed: dict = {}
            for k, v in changes.items():
                if k not in valid:
                    continue
                if k in {"controller_presets", "adapter_presets"}:
                    if not isinstance(v, dict):
                        continue
                    v = _normalize_controller_presets(v)
                elif k == "adapter_colours":
                    v = _normalize_adapter_colours(v)
                if getattr(self._config, k) != v:
                    setattr(self._config, k, v)
                    changed[k] = v
            if changed:
                self._config.save()
        return changed
