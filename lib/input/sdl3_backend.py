"""Generic SDL3 controller discovery, input polling, motion sensors, and rumble."""

from __future__ import annotations

import ctypes
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

from lib.sdl3 import load_sdl3, sdl3_error

logger = logging.getLogger("switch_pair")

STANDARD_GRAVITY = 9.80665

# Canonical semantic input names (matching SDL3 SDL_GamepadButton / Axis).
GAMEPAD_BUTTONS: tuple[str, ...] = (
    "south",
    "east",
    "west",
    "north",
    "back",
    "guide",
    "start",
    "left_stick",
    "right_stick",
    "left_shoulder",
    "right_shoulder",
    "dpad_up",
    "dpad_down",
    "dpad_left",
    "dpad_right",
    "misc1",
    "right_paddle1",
    "left_paddle1",
    "right_paddle2",
    "left_paddle2",
    "touchpad",
)
GAMEPAD_TRIGGERS: tuple[str, ...] = ("left_trigger", "right_trigger")
GAMEPAD_STICKS: tuple[str, ...] = ("left", "right")

_BUTTON_ATTRS: tuple[tuple[str, str], ...] = (
    ("south", "SDL_GAMEPAD_BUTTON_SOUTH"),
    ("east", "SDL_GAMEPAD_BUTTON_EAST"),
    ("west", "SDL_GAMEPAD_BUTTON_WEST"),
    ("north", "SDL_GAMEPAD_BUTTON_NORTH"),
    ("back", "SDL_GAMEPAD_BUTTON_BACK"),
    ("guide", "SDL_GAMEPAD_BUTTON_GUIDE"),
    ("start", "SDL_GAMEPAD_BUTTON_START"),
    ("left_stick", "SDL_GAMEPAD_BUTTON_LEFT_STICK"),
    ("right_stick", "SDL_GAMEPAD_BUTTON_RIGHT_STICK"),
    ("left_shoulder", "SDL_GAMEPAD_BUTTON_LEFT_SHOULDER"),
    ("right_shoulder", "SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER"),
    ("dpad_up", "SDL_GAMEPAD_BUTTON_DPAD_UP"),
    ("dpad_down", "SDL_GAMEPAD_BUTTON_DPAD_DOWN"),
    ("dpad_left", "SDL_GAMEPAD_BUTTON_DPAD_LEFT"),
    ("dpad_right", "SDL_GAMEPAD_BUTTON_DPAD_RIGHT"),
    ("misc1", "SDL_GAMEPAD_BUTTON_MISC1"),
    ("right_paddle1", "SDL_GAMEPAD_BUTTON_RIGHT_PADDLE1"),
    ("left_paddle1", "SDL_GAMEPAD_BUTTON_LEFT_PADDLE1"),
    ("right_paddle2", "SDL_GAMEPAD_BUTTON_RIGHT_PADDLE2"),
    ("left_paddle2", "SDL_GAMEPAD_BUTTON_LEFT_PADDLE2"),
    ("touchpad", "SDL_GAMEPAD_BUTTON_TOUCHPAD"),
)

_TYPE_ATTRS: tuple[tuple[str, str], ...] = (
    ("SDL_GAMEPAD_TYPE_STANDARD", "standard"),
    ("SDL_GAMEPAD_TYPE_XBOX360", "xbox360"),
    ("SDL_GAMEPAD_TYPE_XBOXONE", "xboxone"),
    ("SDL_GAMEPAD_TYPE_PS3", "ps3"),
    ("SDL_GAMEPAD_TYPE_PS4", "ps4"),
    ("SDL_GAMEPAD_TYPE_PS5", "ps5"),
    ("SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_PRO", "switch_pro"),
    ("SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_LEFT", "joycon_l"),
    ("SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_RIGHT", "joycon_r"),
    ("SDL_GAMEPAD_TYPE_NINTENDO_SWITCH_JOYCON_PAIR", "joycon_pair"),
    ("SDL_GAMEPAD_TYPE_GAMECUBE", "gamecube"),
)

# SDL3 reports some newer controllers under an older model's name; override by (VID, PID).
_PRODUCT_NAME_OVERRIDES: dict[tuple[int, int], str] = {
    (0x057E, 0x2069): "Nintendo Switch 2 Pro Controller",
}


@dataclass(frozen=True, slots=True)
class ImuSample:
    """One paired accelerometer (m/s^2) and gyroscope (rad/s) reading in SDL3 coordinates.

    SDL3 right-handed coordinates: +X = right, +Y = up, +Z = toward player.
    """

    accel: tuple[float, float, float] = (0.0, STANDARD_GRAVITY, 0.0)
    gyro: tuple[float, float, float] = (0.0, 0.0, 0.0)
    timestamp_ns: int = 0


@dataclass(frozen=True)
class DeviceInfo:
    """Metadata and capabilities for one connected physical controller."""

    instance_id: int
    guid: str
    name: str
    gamepad_type: str = "standard"
    has_gyro: bool = False
    has_accel: bool = False
    has_rumble: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "guid": self.guid,
            "name": self.name,
            "gamepad_type": self.gamepad_type,
            "has_gyro": self.has_gyro,
            "has_accel": self.has_accel,
            "has_rumble": self.has_rumble,
        }


def _norm_stick(raw: int) -> float:
    return max(-1.0, min(1.0, raw / 32767.0))


def _norm_trigger(raw: int) -> float:
    return max(0.0, min(1.0, raw / 32767.0))


class Sdl3Device:
    """One opened SDL3 gamepad handle with on-demand IMU and rumble support."""

    def __init__(self, sdl: Any, pad: Any, info: DeviceInfo):
        self._sdl = sdl
        self._pad = pad
        self.info = info
        self._buttons = tuple(
            (name, getattr(sdl, attr))
            for name, attr in _BUTTON_ATTRS
            if hasattr(sdl, attr)
        )
        self._sensors_enabled = False
        self._last_accel: tuple[float, float, float] = (0.0, STANDARD_GRAVITY, 0.0)
        self._imu_samples: deque[ImuSample] = deque(maxlen=16)

    def read_state(
        self,
    ) -> tuple[
        frozenset[str], dict[str, float], tuple[float, float], tuple[float, float]
    ]:
        sdl = self._sdl
        pad = self._pad
        buttons = frozenset(
            name for name, code in self._buttons if sdl.SDL_GetGamepadButton(pad, code)
        )
        triggers = {
            "left_trigger": _norm_trigger(
                sdl.SDL_GetGamepadAxis(pad, sdl.SDL_GAMEPAD_AXIS_LEFT_TRIGGER)
            ),
            "right_trigger": _norm_trigger(
                sdl.SDL_GetGamepadAxis(pad, sdl.SDL_GAMEPAD_AXIS_RIGHT_TRIGGER)
            ),
        }
        # SDL reports stick Y positive = down; flip to +Y = up once here.
        left = (
            _norm_stick(sdl.SDL_GetGamepadAxis(pad, sdl.SDL_GAMEPAD_AXIS_LEFTX)),
            -_norm_stick(sdl.SDL_GetGamepadAxis(pad, sdl.SDL_GAMEPAD_AXIS_LEFTY)),
        )
        right = (
            _norm_stick(sdl.SDL_GetGamepadAxis(pad, sdl.SDL_GAMEPAD_AXIS_RIGHTX)),
            -_norm_stick(sdl.SDL_GetGamepadAxis(pad, sdl.SDL_GAMEPAD_AXIS_RIGHTY)),
        )
        return buttons, triggers, left, right

    def set_sensors_enabled(self, enabled: bool) -> None:
        if enabled == self._sensors_enabled:
            return
        sdl = self._sdl
        if self.info.has_accel:
            sdl.SDL_SetGamepadSensorEnabled(self._pad, sdl.SDL_SENSOR_ACCEL, enabled)
        if self.info.has_gyro:
            sdl.SDL_SetGamepadSensorEnabled(self._pad, sdl.SDL_SENSOR_GYRO, enabled)
        self._sensors_enabled = enabled
        if not enabled:
            self._imu_samples.clear()

    def push_sensor(
        self, sensor_type: int, x: float, y: float, z: float, timestamp_ns: int
    ) -> None:
        if not self._sensors_enabled:
            return
        sdl = self._sdl
        if sensor_type == sdl.SDL_SENSOR_ACCEL:
            self._last_accel = (x, y, z)
            if not self.info.has_gyro:
                self._imu_samples.append(
                    ImuSample(self._last_accel, (0.0, 0.0, 0.0), timestamp_ns)
                )
        elif sensor_type == sdl.SDL_SENSOR_GYRO:
            self._imu_samples.append(
                ImuSample(self._last_accel, (x, y, z), timestamp_ns)
            )

    def drain_imu(self) -> list[ImuSample]:
        if not self._imu_samples:
            return []
        samples = list(self._imu_samples)
        self._imu_samples.clear()
        return samples

    def rumble(self, low: float, high: float, duration_ms: int) -> bool:
        lo = max(0, min(0xFFFF, round(low * 0xFFFF)))
        hi = max(0, min(0xFFFF, round(high * 0xFFFF)))
        return bool(self._sdl.SDL_RumbleGamepad(self._pad, lo, hi, duration_ms))

    def stop_rumble(self) -> None:
        self._sdl.SDL_RumbleGamepad(self._pad, 0, 0, 0)

    def close(self) -> None:
        if self._pad is not None:
            pad, self._pad = self._pad, None
            try:
                self.set_sensors_enabled(False)
            except (OSError, RuntimeError, ValueError):
                logger.debug("failed to disable SDL3 sensors on close", exc_info=True)
            self._sdl.SDL_CloseGamepad(pad)


class Sdl3Host:
    """Own SDL3 gamepad subsystem lifecycle, hotplug events, and device handles."""

    def __init__(self, sdl: Any | None = None):
        self._sdl = sdl
        self._initialized = False
        self._subsystems = 0
        self._type_names: dict[int, str] = {}
        self._device_cache: dict[int, DeviceInfo] = {}

    def init(self) -> bool:
        try:
            sdl = self._sdl or load_sdl3()
            self._sdl = sdl
            sdl.SDL_SetHint(sdl.SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, b"1")
            sdl.SDL_SetHint(sdl.SDL_HINT_JOYSTICK_ENHANCED_REPORTS, b"1")
            sdl.SDL_SetHint(
                getattr(sdl, "SDL_HINT_HIDAPI_LIBUSB", b"SDL_HIDAPI_LIBUSB"),
                b"1",
            )
            if hasattr(sdl, "SDL_HINT_JOYSTICK_HIDAPI_SWITCH2"):
                sdl.SDL_SetHint(sdl.SDL_HINT_JOYSTICK_HIDAPI_SWITCH2, b"1")
            subsystems = sdl.SDL_INIT_GAMEPAD | sdl.SDL_INIT_JOYSTICK
            if not sdl.SDL_InitSubSystem(subsystems):
                logger.error("SDL3 gamepad init failed: %s", sdl3_error(sdl))
                return False
            self._subsystems = subsystems
            self._initialized = True
            self._type_names = {
                getattr(sdl, attr): label
                for attr, label in _TYPE_ATTRS
                if hasattr(sdl, attr)
            }
            return True
        except (ImportError, OSError, RuntimeError, AttributeError) as error:
            logger.error("SDL3 gamepad init failed: %s", error)
            return False

    def quit(self) -> None:
        self._device_cache.clear()
        if self._initialized and self._sdl is not None:
            self._initialized = False
            try:
                self._sdl.SDL_QuitSubSystem(self._subsystems)
            except Exception:
                logger.debug("SDL3 QuitSubSystem failed", exc_info=True)

    def _guid_string(self, jid: int) -> str:
        sdl = self._sdl
        guid = sdl.SDL_GetJoystickGUIDForID(jid)
        buf = ctypes.create_string_buffer(33)
        sdl.SDL_GUIDToString(guid, buf, 33)
        return buf.value.decode("ascii", errors="ignore")

    def _device_name(self, jid: int) -> str:
        sdl = self._sdl
        if hasattr(sdl, "SDL_GetJoystickVendorForID") and hasattr(
            sdl, "SDL_GetJoystickProductForID"
        ):
            vid = int(sdl.SDL_GetJoystickVendorForID(jid))
            pid = int(sdl.SDL_GetJoystickProductForID(jid))
            override = _PRODUCT_NAME_OVERRIDES.get((vid, pid))
            if override is not None:
                return override
        raw_name = sdl.SDL_GetGamepadNameForID(jid) or sdl.SDL_GetJoystickNameForID(jid)
        return (
            raw_name.decode("utf-8", errors="replace") if raw_name else f"Gamepad {jid}"
        )

    def _read_capabilities(self, pad: Any) -> tuple[bool, bool, bool]:
        sdl = self._sdl
        has_gyro = bool(sdl.SDL_GamepadHasSensor(pad, sdl.SDL_SENSOR_GYRO))
        has_accel = bool(sdl.SDL_GamepadHasSensor(pad, sdl.SDL_SENSOR_ACCEL))
        props = sdl.SDL_GetGamepadProperties(pad)
        has_rumble = bool(
            sdl.SDL_GetBooleanProperty(
                props, sdl.SDL_PROP_GAMEPAD_CAP_RUMBLE_BOOLEAN, False
            )
        )
        return has_gyro, has_accel, has_rumble

    def _probe_device(
        self, jid: int, open_devices: dict[int, Any]
    ) -> DeviceInfo | None:
        sdl = self._sdl
        if not sdl.SDL_IsGamepad(jid):
            return None
        guid = self._guid_string(jid)
        name = self._device_name(jid)
        gtype = self._type_names.get(sdl.SDL_GetGamepadTypeForID(jid), "standard")
        # Reuse capabilities from an already-open handle without churning SDL state.
        # Unassigned devices are not opened during enumeration; capabilities are
        # queried once when the gamepad is actually opened in open_device().
        if jid in open_devices and isinstance(open_devices[jid], Sdl3Device):
            existing = open_devices[jid].info
            return DeviceInfo(
                instance_id=jid,
                guid=guid,
                name=name,
                gamepad_type=gtype,
                has_gyro=existing.has_gyro,
                has_accel=existing.has_accel,
                has_rumble=existing.has_rumble,
            )
        return DeviceInfo(
            instance_id=jid,
            guid=guid,
            name=name,
            gamepad_type=gtype,
        )

    def list_devices(
        self, open_devices: dict[int, Any] | None = None
    ) -> list[DeviceInfo]:
        sdl = self._sdl
        open_map = open_devices or {}
        count = ctypes.c_int(0)
        ids = sdl.SDL_GetJoysticks(ctypes.byref(count))
        try:
            current_ids = [int(ids[i]) for i in range(count.value)] if ids else []
        finally:
            if ids:
                sdl.SDL_free(ids)
        present = set(current_ids)
        for stale in list(self._device_cache):
            if stale not in present:
                del self._device_cache[stale]
        devices: list[DeviceInfo] = []
        for jid in current_ids:
            info = self._device_cache.get(jid)
            if info is None:
                info = self._probe_device(jid, open_map)
                if info is not None:
                    self._device_cache[jid] = info
            if info is not None:
                devices.append(info)
        return devices

    def poll_events(self, open_devices: dict[int, Any]) -> tuple[bool, set[int]]:
        """Drain SDL3 events, updating open device sensors and reporting hotplug changes."""
        sdl = self._sdl
        ev = sdl.SDL_Event()
        changed = False
        removed: set[int] = set()
        added_types = (sdl.SDL_EVENT_JOYSTICK_ADDED, sdl.SDL_EVENT_GAMEPAD_ADDED)
        removed_types = (sdl.SDL_EVENT_JOYSTICK_REMOVED, sdl.SDL_EVENT_GAMEPAD_REMOVED)
        sensor_type = sdl.SDL_EVENT_GAMEPAD_SENSOR_UPDATE
        while sdl.SDL_PollEvent(ctypes.byref(ev)):
            etype = ev.type
            if etype == sensor_type:
                gs = ev.gsensor
                device = open_devices.get(int(gs.which))
                if isinstance(device, Sdl3Device):
                    device.push_sensor(
                        int(gs.sensor),
                        float(gs.data[0]),
                        float(gs.data[1]),
                        float(gs.data[2]),
                        int(gs.sensor_timestamp),
                    )
            elif etype in added_types:
                changed = True
            elif etype in removed_types:
                changed = True
                jid = int(ev.jdevice.which)
                removed.add(jid)
                self._device_cache.pop(jid, None)
        return changed, removed

    def open_device(self, info: DeviceInfo) -> Sdl3Device:
        pad = self._sdl.SDL_OpenGamepad(info.instance_id)
        if not pad:
            raise RuntimeError(
                f"Could not open gamepad '{info.name}': {sdl3_error(self._sdl)}"
            )
        has_gyro, has_accel, has_rumble = self._read_capabilities(pad)
        resolved = DeviceInfo(
            instance_id=info.instance_id,
            guid=info.guid,
            name=info.name,
            gamepad_type=info.gamepad_type,
            has_gyro=has_gyro,
            has_accel=has_accel,
            has_rumble=has_rumble,
        )
        self._device_cache[info.instance_id] = resolved
        logger.info(
            "SDL3 gamepad opened: '%s' (type=%s, gyro=%s, rumble=%s)",
            resolved.name,
            resolved.gamepad_type,
            resolved.has_gyro,
            resolved.has_rumble,
        )
        return Sdl3Device(self._sdl, pad, resolved)
