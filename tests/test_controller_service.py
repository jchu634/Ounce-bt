from __future__ import annotations

import queue
from concurrent.futures import Future
from unittest.mock import Mock

import pytest

from app.input.controller_service import ControllerInfo, ControllerService
from lib.controller import ControllerVariant
from lib.input.presets import (
    PresetConfig,
    PresetSelection,
    detect_controller_preset,
    load_preset,
    resolve_controller_preset,
)
from lib.input.sdl3_backend import STANDARD_GRAVITY, ImuSample
from lib.input.state import NEUTRAL, Button, ControllerState


class FakeDevice:
    def __init__(self, info: ControllerInfo):
        self.info = info
        self.pressed: frozenset[str] = frozenset()
        self.triggers: dict[str, float] = {}
        self.left = (0.0, 0.0)
        self.right = (0.0, 0.0)
        self.imu: list[ImuSample] = []
        self.sensors_enabled = False
        self.closed = False
        self.rumble_calls: list[tuple[float, float, int]] = []
        self.stop_rumble_calls = 0

    def read_state(self):
        return self.pressed, self.triggers, self.left, self.right

    def set_sensors_enabled(self, enabled: bool) -> None:
        self.sensors_enabled = enabled

    def drain_imu(self) -> list[ImuSample]:
        out, self.imu = list(self.imu), []
        return out

    def rumble(self, low: float, high: float, duration_ms: int) -> bool:
        self.rumble_calls.append((low, high, duration_ms))
        return True

    def stop_rumble(self) -> None:
        self.stop_rumble_calls += 1

    def close(self) -> None:
        self.closed = True


class FakeHost:
    def __init__(self, devices: list[ControllerInfo] | None = None):
        self.devices: list[ControllerInfo] = list(devices or [])
        self.pending_changed = False
        self.pending_removed: set[int] = set()
        self.opened: list[FakeDevice] = []
        self.quit_called = False

    def init(self) -> bool:
        return True

    def quit(self) -> None:
        self.quit_called = True

    def list_devices(self, open_devices=None) -> list[ControllerInfo]:
        return list(self.devices)

    def poll_events(self, open_devices):
        changed, removed = self.pending_changed, set(self.pending_removed)
        self.pending_changed = False
        self.pending_removed.clear()
        return changed, removed

    def open_device(self, info: ControllerInfo) -> FakeDevice:
        device = FakeDevice(info)
        self.opened.append(device)
        return device


def test_controller_type_detection_uses_sdl_type_name_and_vendor_guid():
    assert detect_controller_preset("Generic Pad", "", "ps5") == "playstation"
    assert detect_controller_preset("Generic Pad", "", "switch_pro") == "switch"
    assert detect_controller_preset("Generic Pad", "", "xboxone") == "xbox"
    assert detect_controller_preset("Xbox Wireless Controller") == "xbox"
    assert detect_controller_preset("DualSense Wireless Controller") == "playstation"
    assert detect_controller_preset("Sony Interactive Entertainment Pad") == "playstation"
    assert detect_controller_preset("Nintendo Switch Pro Controller") == "switch"
    assert detect_controller_preset("Steam Controller") == "steam"
    assert detect_controller_preset("Steam Deck") == "steam"
    assert detect_controller_preset("Valve Software Steam Virtual Gamepad") == "steam"
    assert (
        detect_controller_preset(
            "Wireless Controller", "030000004c050000cc09000000000000"
        )
        == "playstation"
    )
    assert (
        detect_controller_preset(
            "Wireless Controller", "03000000de2800000512000000000000"
        )
        == "steam"
    )


def test_saved_guid_preset_overrides_detected_default(monkeypatch):
    configs = {
        "xbox": PresetConfig(name="Xbox"),
        "playstation": PresetConfig(name="PlayStation"),
    }
    monkeypatch.setattr(
        "lib.input.presets.load_preset", lambda source: configs[source]
    )

    selection = resolve_controller_preset(
        "ABC", "Xbox Wireless Controller", {"abc": "playstation"}
    )

    assert selection.source == "playstation"
    assert selection.config.name == "PlayStation"


def test_assign_resolves_and_reports_controller_preset():
    reported = []
    preset = PresetConfig(name="PlayStation")
    controller = ControllerInfo(10, "guid-1", "DualSense", "ps5", has_gyro=True)
    host = FakeHost([controller])
    service = ControllerService(
        queue.Queue(),
        preset_resolver=lambda guid, name, gtype="": PresetSelection("playstation", preset),
        on_preset_changed=reported.append,
        host=host,
    )
    service._refresh_controllers()
    service._assign("primary", 10)

    assert service.primary.preset is preset
    assert reported == [PresetSelection("playstation", preset)]
    assert len(host.opened) == 1


def test_identical_controllers_keep_independent_routes_after_hotplug():
    first = ControllerInfo(10, "same-guid", "Pad", "standard")
    second = ControllerInfo(11, "same-guid", "Pad", "standard")
    host = FakeHost([first, second])
    service = ControllerService(queue.Queue(), host=host)
    route = service.add_route("adapter-2")
    service._refresh_controllers()

    service._assign("primary", 10)
    service._assign("adapter-2", 11)
    with pytest.raises(ValueError, match="already assigned"):
        service._assign("adapter-2", 10)

    second_device = service._devices[11]
    second_device.pressed = frozenset({"east"})
    service._tick_sdl()
    assert route.input_queue.get_nowait() == ControllerState(Button.A)

    # Disconnect controller 10: surviving controller 11 is NOT closed or reopened!
    host.devices = [second]
    host.pending_changed = True
    host.pending_removed = {10}
    service._tick_sdl()

    assert service.active_guid is None
    assert route.controller == second
    assert service._devices[11] is second_device
    assert not second_device.closed
    assert service.primary.input_queue.get_nowait() == NEUTRAL

    service._assign("adapter-2", None)
    assert second_device.closed
    assert route.input_queue.get_nowait() == NEUTRAL


def test_profile_controller_restore_requires_an_available_unambiguous_match():
    saved = Mock()
    first = ControllerInfo(10, "shared", "Pad")
    second = ControllerInfo(11, "shared", "Pad")
    host = FakeHost([first, second])
    service = ControllerService(
        queue.Queue(),
        saved_assignments={"primary": "missing", "adapter-2": "shared"},
        on_assignment=saved,
        host=host,
    )
    route = service.add_route("adapter-2")
    service._refresh_controllers()

    service._restore_assignments()
    assert service.active_guid is None
    assert route.controller is None

    host.devices = [second]
    service._refresh_controllers()
    service._restore_assignments()
    assert route.controller == second
    saved.assert_not_called()

    assigned = Future()
    service._handle("assign", ("adapter-2", None), assigned)
    assert assigned.result() is None
    saved.assert_called_once_with("adapter-2", "")
    service._restore_assignments()
    assert route.controller is None


def test_hotplug_connect_disconnect_reconnect():
    notifications = []
    controller = ControllerInfo(
        1,
        "0300b7e67e0500000920000000006803",
        "Nintendo Switch Pro Controller",
        "switch_pro",
        has_gyro=True,
        has_accel=True,
        has_rumble=True,
    )
    host = FakeHost([])
    service = ControllerService(
        queue.Queue(),
        on_change=lambda devices, active: notifications.append((devices, active)),
        host=host,
    )

    for _ in range(2):
        host.devices = [controller]
        host.pending_changed = True
        service._tick_sdl()
        assert service.active_guid == controller.guid
        assert notifications[-1] == ([controller.to_dict()], controller.guid)

        host.devices = []
        host.pending_changed = True
        host.pending_removed = {1}
        service._tick_sdl()
        assert service.active_guid is None
        assert notifications[-1] == ([], None)
        assert service.primary.input_queue.get_nowait() == NEUTRAL

    # Manual unassign disables auto-select on subsequent reconnect.
    service._assign("primary", None)
    host.devices = [controller]
    host.pending_changed = True
    service._tick_sdl()
    assert service._controllers == [controller]
    assert service.active_guid is None


def test_on_demand_imu_sensors_and_live_variant_switching():
    controller = ControllerInfo(5, "guid-pro", "Switch Pro", "switch_pro", has_gyro=True, has_accel=True)
    host = FakeHost([controller])
    out = queue.Queue()
    service = ControllerService(out, preset=load_preset("switch"), host=host)
    imu_on = [False]
    variant = [ControllerVariant.PRO]
    service.imu_requested = lambda: imu_on[0]
    service.mapping_variant = lambda: variant[0]

    service._refresh_controllers()
    service._assign("primary", 5)
    device = service._devices[5]
    device.pressed = frozenset({"south"})

    service._tick_sdl()
    assert not device.sensors_enabled
    assert out.get_nowait() == ControllerState(Button.B)

    imu_on[0] = True
    sample = ImuSample((0.0, STANDARD_GRAVITY, 0.0), (0.5, 0.0, 0.0), 100)
    device.imu = [sample]
    variant[0] = ControllerVariant.LEFT
    service._tick_sdl()
    assert device.sensors_enabled
    assert out.get_nowait() == ControllerState(Button.LEFT)
    cursor, read = service.read_imu_since(0)
    assert cursor == 1
    assert read == [sample]

    imu_on[0] = False
    service._tick_sdl()
    assert not device.sensors_enabled


def test_service_can_stop_and_join_without_controllers():
    host = FakeHost([])
    service = ControllerService(queue.Queue(), host=host)
    service.start()
    try:
        assert service.status()["controllers"] == []
    finally:
        service.stop()
        service.join(timeout=2)
    assert not service.is_alive()
    assert host.quit_called
