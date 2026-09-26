from __future__ import annotations

import json
import logging
import os
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


def config_path() -> Path:
    return _config_dir() / "config.json"


@dataclass
class Config:
    """Runtime configuration. Add new fields here; defaults are picked up
    automatically when the on-disk file is missing keys."""

    web_host: str = "127.0.0.1"
    web_port: int = 9127
    bt_address: str = "98:b6:e9:12:34:57"
    transport_spec: str | None = None
    device_config: str = "pro_controller.json"
    input_specs: list[str] = field(default_factory=list)
    last_camera_device_id: str = ""
    tick_rate_hz: int = 132
    macro_rate_hz: int = 120
    preset: str = "xbox"
    controller_guid: str = ""
    controller_presets: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.controller_presets = _normalize_controller_presets(self.controller_presets)

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
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not read config {path}: {e}; using defaults")
                data = {}
        if overrides:
            data = {**data, **overrides}
        valid = cls._valid_keys()
        filtered = {k: v for k, v in data.items() if k in valid and v is not None}
        return cls(**filtered)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self) -> None:
        """Atomically persist current state to disk."""
        path = config_path()
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
