from __future__ import annotations

import json
import logging
import os
import sys
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

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


def _config_dir() -> Path:
    """
    Locate the per-user config directory.

    Preference order: ``%APPDATA%`` (Windows), ``$XDG_CONFIG_HOME`` (POSIX),
    then ``~/.config``. Created on first save, not on read.
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def application_dir() -> Path:
    # Nuitka onefile extracts __file__ into a temporary directory. argv[0]
    # locates the executable and its external, writable configuration.
    if "__compiled__" in globals() or getattr(sys, "frozen", False):
        return Path(sys.argv[0]).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_config_file(name: str) -> Path:
    path = Path(name).expanduser()
    if path.is_absolute():
        return path
    local = application_dir() / "config" / path
    return local if local.is_file() else _config_dir() / path


def config_path() -> Path:
    return resolve_config_file("config.json")


@dataclass
class Config:
    """Runtime configuration. Add new fields here; defaults are picked up
    automatically when the on-disk file is missing keys."""

    web_host: str | None = "127.0.0.1"
    web_port: int | None = 9127
    bt_address: str = ""
    transport_spec: str = "usb:0"
    device_config: str = "pro_controller.json"
    input_specs: list[str] = field(default_factory=lambda: ["controller"])
    macros_dir: str = "macros"
    presets_dir: str = "presets"
    pairing_dir: str | None = None
    nolog: bool = False
    last_camera_device_id: str = ""
    tick_rate_hz: int = 132
    macro_rate_hz: int = 120
    preset: str = "xbox"
    controller_guid: str = ""
    controller_presets: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.controller_presets = _normalize_controller_presets(self.controller_presets)

    @property
    def web_enabled(self) -> bool:
        return bool(self.web_host and self.web_port)

    def resolve_folder(self, folder: str) -> Path:
        path = Path(folder).expanduser()
        return path if path.is_absolute() else application_dir() / path

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
        nullable = {"web_host", "web_port", "pairing_dir"}
        filtered = {
            k: v
            for k, v in data.items()
            if k in valid and (v is not None or k in nullable)
        }
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

    def update(self, changes: dict) -> dict:
        """Apply a partial update and persist. Returns the actually-changed
        key/value pairs (keys that were unknown or unchanged are skipped)."""
        valid = Config._valid_keys()
        with self._lock:
            changed: dict = {}
            for k, v in changes.items():
                if k not in valid:
                    continue
                if k == "controller_presets":
                    if not isinstance(v, dict):
                        continue
                    v = _normalize_controller_presets(v)
                if getattr(self._config, k) != v:
                    setattr(self._config, k, v)
                    changed[k] = v
            if changed:
                self._config.save()
        return changed
