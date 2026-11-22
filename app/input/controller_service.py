"""Own SDL3 controller operations on one 120 Hz daemon thread with a thread-safe mailbox."""

from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from lib.controller import ControllerVariant
from lib.input.imu import ImuBuffer
from lib.input.presets import PresetConfig, PresetSelection
from lib.input.rumble import RumbleData
from lib.input.sdl3_backend import DeviceInfo, ImuSample, Sdl3Host
from lib.input.state import NEUTRAL, Button, ControllerState

logger = logging.getLogger("switch_pair")

OP_TIMEOUT_SECONDS = 5.0
RUMBLE_TIMEOUT_SECONDS = 0.25
RUMBLE_DURATION_MS = 100
RUMBLE_REFRESH_SECONDS = 0.05

ControllerInfo = DeviceInfo


def _apply_deadzone(value: float, deadzone: float) -> float:
    if abs(value) <= deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * min(1.0, abs(value))


def map_gamepad_state(
    pressed: frozenset[str],
    triggers: dict[str, float],
    left_stick: tuple[float, float],
    right_stick: tuple[float, float],
    mapping: PresetConfig,
    *,
    deadzone: float = 0.12,
    trigger_threshold: float = 0.30,
) -> ControllerState:
    """Translate one normalized SDL3 gamepad sample through a resolved preset."""
    buttons = Button(0)
    for name in pressed:
        target = mapping.button_map.get(name)
        if target is not None:
            buttons |= target

    for name, target in mapping.trigger_map.items():
        if triggers.get(name, 0.0) >= trigger_threshold:
            buttons |= target

    sticks = {
        "left": (
            _apply_deadzone(left_stick[0], deadzone),
            _apply_deadzone(left_stick[1], deadzone),
        ),
        "right": (
            _apply_deadzone(right_stick[0], deadzone),
            _apply_deadzone(right_stick[1], deadzone),
        ),
    }
    out_left = sticks[mapping.left_stick] if mapping.left_stick is not None else (0.0, 0.0)
    out_right = sticks[mapping.right_stick] if mapping.right_stick is not None else (0.0, 0.0)
    return ControllerState(buttons, out_left, out_right)


class LatestInput:
    """Keep at most one unread physical input sample."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: ControllerState | None = None

    def put(self, state: ControllerState) -> None:
        with self._lock:
            self._state = state

    def put_nowait(self, state: ControllerState) -> None:
        self.put(state)

    def get_nowait(self) -> ControllerState:
        with self._lock:
            if self._state is None:
                raise queue.Empty
            state, self._state = self._state, None
            return state

    def empty(self) -> bool:
        with self._lock:
            return self._state is None


class ControllerRoute:
    """Per-adapter input queue, IMU stream, rumble state, and preset mapping."""

    def __init__(
        self,
        session_id: str,
        preset: PresetConfig,
        preset_name: str,
        *,
        input_queue: LatestInput | queue.Queue | None = None,
    ):
        self.session_id = session_id
        self.input_queue = input_queue if input_queue is not None else LatestInput()
        self.imu_buffer = ImuBuffer()
        self.controller: DeviceInfo | None = None
        self.preset = preset
        self.preset_name = preset_name
        self.preset_override: PresetSelection | None = None
        self.mapping_variant: Callable[[], ControllerVariant] | None = None
        self.imu_requested: Callable[[], bool] | None = None
        self._paused = False
        self._rumble_lock = threading.Lock()
        self._rumble: tuple[float, float] = (0.0, 0.0)
        self._rumble_deadline = 0.0
        self._rumble_playing = False
        self._rumble_supported = True
        self._rumble_refresh = 0.0
        self._played_rumble: tuple[float, float] = (0.0, 0.0)

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def active_guid(self) -> str | None:
        return self.controller.guid if self.controller else None

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def is_paused(self) -> bool:
        return self._paused

    def set_rumble(self, rumble: RumbleData | None) -> None:
        with self._rumble_lock:
            self._rumble = rumble.strengths() if rumble is not None else (0.0, 0.0)
            self._rumble_deadline = time.monotonic() + RUMBLE_TIMEOUT_SECONDS

    def read_imu_since(self, cursor: int) -> tuple[int, list[ImuSample]]:
        return self.imu_buffer.read_since(cursor)

    def reset_device_state(self) -> None:
        self._rumble_playing = False
        self._rumble_supported = True
        self._rumble_refresh = 0.0
        self._played_rumble = (0.0, 0.0)
        self.imu_buffer.clear()

    def clear_input(self) -> None:
        while True:
            try:
                self.input_queue.get_nowait()
            except queue.Empty:
                break
        if not self._paused:
            self.input_queue.put(NEUTRAL)

    def update_rumble(self, device: Any) -> None:
        if not self._rumble_supported:
            return
        now = time.monotonic()
        with self._rumble_lock:
            strengths = self._rumble if now < self._rumble_deadline else (0.0, 0.0)
        try:
            if strengths == (0.0, 0.0):
                if self._rumble_playing:
                    device.stop_rumble()
                    self._rumble_playing = False
            elif (
                not self._rumble_playing
                or now >= self._rumble_refresh
                or strengths != self._played_rumble
            ):
                self._rumble_supported = device.rumble(*strengths, RUMBLE_DURATION_MS)
                self._rumble_playing = self._rumble_supported
                self._played_rumble = strengths
                self._rumble_refresh = now + RUMBLE_REFRESH_SECONDS
                if not self._rumble_supported:
                    logger.info("Selected controller does not support vibration")
        except Exception:
            self._rumble_supported = False
            logger.warning("Controller vibration unavailable", exc_info=True)


class ControllerService(threading.Thread):
    """Mailbox-driven single-thread SDL3 controller owner.

    ``on_change`` fires from the service thread whenever the device list
    or active selection changes (including hotplug); marshal it onto the
    asyncio loop in the callback (see ``InputManager``).
    """

    def __init__(
        self,
        command_queue,
        preset: PresetConfig | None = None,
        *,
        on_change: Callable[[list[dict], str | None], None] | None = None,
        preset_resolver: Callable[[str, str, str], PresetSelection] | None = None,
        on_preset_changed: Callable[[PresetSelection], None] | None = None,
        rate_hz: int = 120,
        deadzone: float = 0.12,
        trigger_threshold: float = 0.30,
        saved_assignments: dict[str, str] | None = None,
        on_assignment: Callable[[str, str], None] | None = None,
        primary_preset_override: bool = False,
        host: Sdl3Host | None = None,
    ):
        super().__init__(name="controller-service", daemon=True)
        self._host = host or Sdl3Host()
        self._on_change = on_change
        self._preset_resolver = preset_resolver
        self._on_preset_changed = on_preset_changed
        self._period = 1.0 / rate_hz
        self._deadzone = deadzone
        self._trigger_threshold = trigger_threshold
        self._mailbox: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._sdl_ok = False
        self._controllers: list[DeviceInfo] = []
        self._devices: dict[int, Any] = {}
        self._auto_select_primary = True
        self._saved_assignments = saved_assignments
        self._on_assignment = on_assignment

        initial_preset = preset or PresetConfig.default()
        primary = ControllerRoute(
            "primary",
            initial_preset,
            initial_preset.name,
            input_queue=command_queue,
        )
        if primary_preset_override:
            primary.preset_override = PresetSelection(initial_preset.name, initial_preset)
        self._routes: dict[str, ControllerRoute] = {"primary": primary}
        self._status_lock = threading.Lock()
        self._status_snapshot: dict[str, Any] = self._build_status()

    @property
    def primary(self) -> ControllerRoute:
        return self._routes["primary"]

    @property
    def active_guid(self) -> str | None:
        return self.primary.active_guid

    @property
    def mapping_variant(self) -> Callable[[], ControllerVariant] | None:
        return self.primary.mapping_variant

    @mapping_variant.setter
    def mapping_variant(self, value: Callable[[], ControllerVariant] | None) -> None:
        self.primary.mapping_variant = value

    @property
    def imu_requested(self) -> Callable[[], bool] | None:
        return self.primary.imu_requested

    @imu_requested.setter
    def imu_requested(self, value: Callable[[], bool] | None) -> None:
        self.primary.imu_requested = value

    def add_route(self, session_id: str, preset_name: str = "xbox") -> ControllerRoute:
        route = ControllerRoute(session_id, self.primary.preset, preset_name)
        self._routes[session_id] = route
        self._publish_status()
        return route

    def assign(self, session_id: str, instance_id: int | None) -> None:
        result = self._request("assign", (session_id, instance_id))
        if isinstance(result, Exception):
            raise result

    def set_rumble(self, rumble: RumbleData | None) -> None:
        self.primary.set_rumble(rumble)

    def read_imu_since(self, cursor: int) -> tuple[int, list[ImuSample]]:
        return self.primary.read_imu_since(cursor)

    def pause(self) -> None:
        self.primary.pause()

    def resume(self) -> None:
        self.primary.resume()

    def is_paused(self) -> bool:
        return self.primary.is_paused()

    def stop(self) -> None:
        self._stop_event.set()
        self._mailbox.put(("wake", None, None))

    def _build_status(self) -> dict[str, Any]:
        return {
            "controllers": [c.to_dict() for c in self._controllers],
            "active": self.active_guid,
            "assignments": {
                key: route.controller.instance_id if route.controller else None
                for key, route in self._routes.items()
            },
            "available": self._sdl_ok,
        }

    def _publish_status(self) -> None:
        snapshot = self._build_status()
        with self._status_lock:
            self._status_snapshot = snapshot

    def status(self) -> dict:
        if not self.is_alive():
            return {"controllers": [], "active": None, "assignments": {}, "available": False}
        with self._status_lock:
            snap = self._status_snapshot
            return {
                "controllers": [dict(c) for c in snap["controllers"]],
                "active": snap["active"],
                "assignments": dict(snap["assignments"]),
                "available": snap["available"],
            }

    def enumerate(self) -> list[dict]:
        return list(self.status().get("controllers", []))

    def set_preset(
        self, preset: PresetConfig, source: str | None = None, *, session_id: str = "primary"
    ) -> None:
        result = self._request("set_preset", (preset, source, session_id))
        if isinstance(result, Exception):
            raise result

    def _request(self, op: str, payload: Any = None) -> Any:
        if not self.is_alive():
            raise RuntimeError("controller service is not running")
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._mailbox.put((op, payload, fut))
        try:
            return fut.result(timeout=OP_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise RuntimeError(
                f"controller service did not answer '{op}' in time"
            ) from None

    def run(self) -> None:
        self._sdl_ok = self._host.init()
        if not self._sdl_ok:
            logger.warning(
                "ControllerService: SDL3 unavailable; "
                "controller enumeration and capture disabled"
            )
        try:
            if self._sdl_ok:
                self._refresh_controllers()
                if self._saved_assignments is not None:
                    self._restore_assignments()
                elif self._controllers:
                    self._assign("primary", self._controllers[0].instance_id)
                self._publish_status()
                self._notify()
            else:
                self._publish_status()

            while not self._stop_event.is_set():
                deadline = time.monotonic() + self._period
                while not self._stop_event.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        op, payload, fut = self._mailbox.get(timeout=remaining)
                    except queue.Empty:
                        break
                    if fut is None:
                        continue
                    if fut.set_running_or_notify_cancel():
                        self._handle(op, payload, fut)
                if self._sdl_ok and not self._stop_event.is_set():
                    self._tick_sdl()
        finally:
            self._sdl_ok = False
            self._shutdown_devices()
            self._publish_status()
            self._host.quit()

    def _handle(self, op: str, payload: Any, fut: concurrent.futures.Future) -> None:
        try:
            if op == "status":
                fut.set_result(self._build_status())
            elif op == "set_preset":
                preset, source, session_id = payload
                route = self._routes[session_id]
                if route.paused:
                    raise ValueError("Cannot change presets while a macro is active")
                selection = PresetSelection(source or preset.name, preset)
                route.preset = preset
                route.preset_name = selection.source
                route.preset_override = selection
                if session_id == "primary":
                    self._report_preset(selection)
                fut.set_result(None)
            elif op == "assign":
                session_id, instance_id = payload
                self._assign(session_id, instance_id)
                self._remember_assignment(session_id, self._routes[session_id].controller)
                fut.set_result(None)
            elif op == "shutdown":
                self._stop_event.set()
                fut.set_result(None)
            else:
                fut.set_result(ValueError(f"unknown op: {op!r}"))
        except Exception as e:
            logger.exception("ControllerService op '%s' failed", op)
            fut.set_result(e)

    def _tick_sdl(self) -> None:
        try:
            changed, removed = self._host.poll_events(self._devices)
        except Exception:
            logger.exception("SDL3 event polling failed")
            return

        if changed:
            self._handle_hotplug(removed)

        for route in self._routes.values():
            controller = route.controller
            if controller is None:
                continue
            device = self._devices.get(controller.instance_id)
            if device is None:
                continue
            try:
                route.update_rumble(device)
                want_imu = bool(
                    not route.paused
                    and route.preset.motion_enabled
                    and route.imu_requested is not None
                    and route.imu_requested()
                )
                device.set_sensors_enabled(want_imu)
                if want_imu:
                    route.imu_buffer.push(device.drain_imu())
                if route.paused:
                    continue
                variant = (
                    route.mapping_variant()
                    if route.mapping_variant is not None
                    else ControllerVariant.PRO
                )
                mapping = route.preset.mapping_for(variant)
                pressed, triggers, left, right = device.read_state()
                route.input_queue.put(
                    map_gamepad_state(
                        pressed,
                        triggers,
                        left,
                        right,
                        mapping,
                        deadzone=self._deadzone,
                        trigger_threshold=self._trigger_threshold,
                    )
                )
            except Exception:
                logger.exception(
                    "Controller read failed for '%s'; detaching route '%s'",
                    controller.name,
                    route.session_id,
                )
                self._close_device(controller.instance_id)
                route.controller = None
                route.reset_device_state()
                route.clear_input()
                self._publish_status()
                self._notify()

    def _refresh_controllers(self) -> bool:
        infos = self._host.list_devices(self._devices)
        changed = infos != self._controllers
        self._controllers = infos
        if changed:
            self._publish_status()
        return changed

    def _handle_hotplug(self, removed: set[int]) -> None:
        previous_primary = self.active_guid
        changed = self._refresh_controllers()
        present_ids = {c.instance_id for c in self._controllers}
        gone = removed | (set(self._devices) - present_ids)

        for jid in gone:
            self._close_device(jid)

        for route in self._routes.values():
            if route.controller is not None and route.controller.instance_id not in present_ids:
                logger.warning(
                    "Controller '%s' (%s) disconnected from '%s'",
                    route.controller.name,
                    route.controller.guid,
                    route.session_id,
                )
                route.controller = None
                route.reset_device_state()
                route.clear_input()
            elif route.controller is not None:
                # Refresh metadata in place without reopening the live device.
                updated = next(
                    (c for c in self._controllers if c.instance_id == route.controller.instance_id),
                    None,
                )
                if updated is not None:
                    route.controller = updated

        if self._saved_assignments is not None:
            self._restore_assignments()
        elif self.primary.controller is None and self._auto_select_primary:
            assigned = {
                r.controller.instance_id
                for r in self._routes.values()
                if r.controller is not None
            }
            candidate = next(
                (pad for pad in self._controllers if pad.instance_id not in assigned),
                None,
            )
            if candidate is not None:
                try:
                    self._assign("primary", candidate.instance_id)
                    logger.info("Fell back to '%s'", candidate.name)
                except ValueError:
                    pass

        self._publish_status()
        if changed or self.active_guid != previous_primary:
            self._notify()

    def _remember_assignment(
        self, session_id: str, match: DeviceInfo | None
    ) -> None:
        if self._saved_assignments is None:
            return
        guid = match.guid if match else ""
        if self._on_assignment is not None:
            self._on_assignment(session_id, guid)
        self._saved_assignments[session_id] = guid

    def _restore_assignments(self) -> None:
        if self._saved_assignments is None:
            return
        for session_id, guid in self._saved_assignments.items():
            route = self._routes.get(session_id)
            if not guid or route is None or route.controller is not None:
                continue
            assigned_ids = {
                r.controller.instance_id
                for r in self._routes.values()
                if r.controller is not None
            }
            matches = [
                pad
                for pad in self._controllers
                if pad.guid == guid and pad.instance_id not in assigned_ids
            ]
            if len(matches) == 1:
                try:
                    self._assign(session_id, matches[0].instance_id)
                except ValueError:
                    continue

    def _assign(self, session_id: str, instance_id: int | None) -> None:
        route = self._routes[session_id]
        if route.paused:
            raise ValueError("Cannot change controllers while a macro is active")
        match: DeviceInfo | None = None
        if instance_id is not None:
            match = next(
                (c for c in self._controllers if c.instance_id == instance_id), None
            )
            if match is None:
                raise ValueError("Controller is no longer connected")
            if any(
                other is not route
                and other.controller is not None
                and other.controller.instance_id == match.instance_id
                for other in self._routes.values()
            ):
                raise ValueError("Controller is already assigned to another adapter")

        if route.controller is not None and match is not None and route.controller.instance_id == match.instance_id:
            return
        if route.controller is None and match is None:
            if session_id == "primary":
                self._auto_select_primary = False
            return

        if route.controller is not None:
            self._close_device(route.controller.instance_id)
            route.controller = None
            route.reset_device_state()
            route.clear_input()

        if match is None:
            if session_id == "primary":
                self._auto_select_primary = False
            self._publish_status()
            self._notify()
            return

        if route.preset_override is None and self._preset_resolver is not None:
            selection = self._preset_resolver(match.guid, match.name, match.gamepad_type)
            route.preset = selection.config
            route.preset_name = selection.source
            if session_id == "primary":
                self._report_preset(selection)

        device = self._host.open_device(match)
        opened_info = getattr(device, "info", match)
        if isinstance(opened_info, DeviceInfo) and opened_info != match:
            match = opened_info
            self._controllers = [
                opened_info if c.instance_id == opened_info.instance_id else c
                for c in self._controllers
            ]
        self._devices[match.instance_id] = device
        route.controller = match
        route.reset_device_state()
        if session_id == "primary":
            self._auto_select_primary = True
        logger.info("Controller assigned to '%s': '%s' (%s)", session_id, match.name, match.guid)
        self._publish_status()
        self._notify()

    def _close_device(self, instance_id: int) -> None:
        device = self._devices.pop(instance_id, None)
        if device is None:
            return
        try:
            device.stop_rumble()
        except Exception:
            logger.debug("stop_rumble failed on close", exc_info=True)
        try:
            device.close()
        except Exception:
            logger.debug("failed to close SDL3 controller", exc_info=True)

    def _shutdown_devices(self) -> None:
        for jid in list(self._devices):
            self._close_device(jid)
        for route in self._routes.values():
            route.controller = None
            route.reset_device_state()

    def _report_preset(self, selection: PresetSelection) -> None:
        callback = self._on_preset_changed
        if callback is None:
            return
        try:
            callback(selection)
        except Exception:
            logger.exception("controller preset callback failed")

    def _notify(self) -> None:
        cb = self._on_change
        if cb is None:
            return
        try:
            cb([c.to_dict() for c in self._controllers], self.active_guid)
        except Exception:
            logger.exception("controller on_change callback failed")
