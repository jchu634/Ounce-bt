from __future__ import annotations

import queue

import pygame
from pygame import event

from app.input.controller_service import ControllerInfo, ControllerService
from lib.input.presets import (
    PresetConfig,
    PresetSelection,
    detect_controller_preset,
    resolve_controller_preset,
)


def test_controller_type_detection_uses_name_and_sdl_vendor_guid():
    assert detect_controller_preset("Xbox Wireless Controller") == "xbox"
    assert detect_controller_preset("DualSense Wireless Controller") == "playstation"
    assert detect_controller_preset("Sony Interactive Entertainment Pad") == "playstation"
    assert detect_controller_preset("Nintendo Switch Pro Controller") == "switch_pro"
    assert (
        detect_controller_preset(
            "Wireless Controller", "030000004c050000cc09000000000000"
        )
        == "playstation"
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


def test_select_resolves_and_reports_controller_preset(monkeypatch):
    reported = []
    preset = PresetConfig(name="PlayStation")
    service = ControllerService(
        queue.Queue(),
        preset_resolver=lambda guid, name: PresetSelection("playstation", preset),
        on_preset_changed=reported.append,
    )
    controller = ControllerInfo("guid-1", 0, "DualSense", 6, 16, 0)
    service._controllers = [controller]

    class Capture:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr("app.input.controller_service.PygameInputThread", Capture)

    service._do_select(controller.guid)

    assert service._preset is preset
    assert reported == [PresetSelection("playstation", preset)]


def test_poll_without_hotplug_does_not_reprobe_active_joystick(monkeypatch):
    """Routine polling must not invalidate the active capture joystick."""
    service = ControllerService(queue.Queue())
    monkeypatch.setattr(event, "pump", lambda: None)
    monkeypatch.setattr(event, "get", list)
    monkeypatch.setattr(
        service,
        "_refresh_controllers",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected probe")),
    )

    service._pump_and_handle_hotplug()


def test_hotplug_stops_capture_before_enumeration_and_reselects(monkeypatch):
    """Hotplug enumeration must stop capture before probing and reopen it."""
    service = ControllerService(queue.Queue())
    controller = ControllerInfo("guid-1", 0, "Pad", 4, 10, 1)
    service._controllers = [controller]
    service._active_guid = controller.guid
    service._capture = object()  # Only its presence matters to this test.
    calls = []

    monkeypatch.setattr(event, "pump", lambda: None)
    monkeypatch.setattr(event, "get", lambda: [event.Event(pygame.JOYDEVICEADDED, device_index=0)])
    monkeypatch.setattr(service, "_stop_capture", lambda: calls.append("stop"))
    monkeypatch.setattr(
        service, "_refresh_controllers", lambda: calls.append("refresh") or False
    )
    monkeypatch.setattr(
        service, "_do_select", lambda ident: calls.append(("select", ident)) or controller
    )

    service._pump_and_handle_hotplug()

    assert calls == ["stop", "refresh", ("select", controller.guid)]


def test_service_initializes_event_queue_without_capture():
    from pygame import display, joystick

    display.quit()
    joystick.quit()
    service = ControllerService(queue.Queue())
    try:
        assert service._init_pygame()
        event.pump()
        event.get()
    finally:
        joystick.quit()
        display.quit()


def test_hotplug_connect_disconnect_reconnect(monkeypatch):
    from app.input.pygame_source import PygameInputThread
    from lib.input.state import NEUTRAL

    notifications = []
    service = ControllerService(
        queue.Queue(), on_change=lambda devices, active: notifications.append((devices, active))
    )
    controller = ControllerInfo("guid-1", 0, "Pad", 4, 10, 1)
    connected = []
    pending = []
    captures = []

    # Use actual Thread start/stop/join to exercise Python's thread lifecycle.
    class Capture(PygameInputThread):
        def run(self):
            captures.append(self)
            self._stop_event.wait()

    def refresh():
        changed = service._controllers != connected
        service._controllers = list(connected)
        return changed

    def get_events():
        events = list(pending)
        pending.clear()
        return events

    monkeypatch.setattr("app.input.controller_service.PygameInputThread", Capture)
    monkeypatch.setattr(service, "_refresh_controllers", refresh)
    monkeypatch.setattr(event, "pump", lambda: None)
    monkeypatch.setattr(event, "get", get_events)

    try:
        for _ in range(2):
            connected.append(controller)
            pending.append(event.Event(pygame.JOYDEVICEADDED, device_index=0))
            service._pump_and_handle_hotplug()
            assert service._active_guid == controller.guid
            assert service._capture.is_alive()
            assert notifications[-1] == ([controller.to_dict()], controller.guid)

            connected.clear()
            pending.append(event.Event(pygame.JOYDEVICEREMOVED, instance_id=1))
            service._pump_and_handle_hotplug()
            assert service._active_guid is None
            assert service._capture is None
            assert notifications[-1] == ([], None)
            assert service._queue.get_nowait() == NEUTRAL
        assert len(captures) == 2
        assert all(not capture.is_alive() for capture in captures)
    finally:
        service._shutdown_captures()


def test_service_can_stop_and_join_without_controllers(monkeypatch):
    service = ControllerService(queue.Queue())
    monkeypatch.setattr(service, "_init_pygame", lambda: True)
    monkeypatch.setattr(service, "_refresh_controllers", lambda: False)
    monkeypatch.setattr(service, "_pump_and_handle_hotplug", lambda: None)
    service.start()
    try:
        assert service.status()["controllers"] == []
    finally:
        service.stop()
        service.join(timeout=2)
    assert not service.is_alive()
