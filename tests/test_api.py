"""Test HTTP and WebSocket behaviour with an input manager that requires no controller hardware."""

from __future__ import annotations

import queue
import shutil
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

import lib.input.presets as presets_module
from app.bluetooth import AdapterSession
from app.input.manager import InputManager, MacroActiveError
from app.main import SessionState
from app.server import build_app
from lib.config import Config, ConfigStore
from lib.input.state import NEUTRAL, Button, ControllerState
from lib.server.files import JsonDocStore


class StubControllerService:
    """Minimal ControllerService stand-in."""

    def __init__(self, controllers, active):
        self._controllers = controllers
        self._active = active

    def status(self):
        return {
            "controllers": self._controllers,
            "active": self._active,
            "available": True,
        }

    def select(self, ident):
        for c in self._controllers:
            if c["guid"] == ident or c["name"] == ident or c["index"] == ident:
                self._active = c["guid"]
                return type("Info", (), {"to_dict": lambda self=self, c=c: c})()
        raise ValueError(f"no controller matches {ident!r}")

    def set_preset(self, preset, source=None):
        return None


class Fixture:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self.macros_dir = tmp_path / "macros"
        self.macros_dir.mkdir()
        (self.macros_dir / "example.json").write_text(
            '{"version": 1, "name": "example", "actions": [{"do": "press", "button": "A"}]}',
            encoding="utf-8",
        )
        # Isolate the presets directory (copy builtins in) so custom
        # preset writes never touch the repo.
        self.presets_dir = tmp_path / "presets"
        self.presets_dir.mkdir()
        for name in presets_module.BUILTIN_PRESETS:
            shutil.copy(
                presets_module.PRESETS_DIR / f"{name}.json",
                self.presets_dir / f"{name}.json",
            )
        monkeypatch.setattr(presets_module, "PRESETS_DIR", self.presets_dir)
        self.command_queue: queue.Queue = queue.Queue()
        self.manager = InputManager(self.command_queue, self.macros_dir)
        self.manager.bind_loop(None)
        monkeypatch.setattr("lib.config.config_path", lambda: tmp_path / "config.json")
        self.config_store = ConfigStore(Config(transport_spec="usb:0", ws_auth_required=False))
        self.manager.set_controller_service(
            StubControllerService(
                [
                    {
                        "guid": "g1",
                        "index": 0,
                        "name": "Pad One",
                        "axes": 6,
                        "buttons": 11,
                        "hats": 1,
                    },
                    {
                        "guid": "g2",
                        "index": 1,
                        "name": "Pad Two",
                        "axes": 4,
                        "buttons": 9,
                        "hats": 0,
                    },
                ],
                "g1",
            )
        )

    def client(self) -> TestClient:
        app = build_app(
            self.manager,
            self.config_store,
            Path("/nonexistent-dist"),
            macro_store=JsonDocStore(self.macros_dir),
        )
        return TestClient(app)


@pytest.fixture()
def fx(tmp_path, monkeypatch):
    fixture = Fixture(tmp_path, monkeypatch)
    yield fixture
    fixture.manager.shutdown()


def test_bluetooth_commands_are_scoped_to_one_adapter(fx):
    primary = AdapterSession("primary", "usb:0", fx.command_queue, None)
    secondary = AdapterSession("adapter-2", "usb:1", queue.Queue(), None)
    primary.bluetooth.set_pairing = AsyncMock()
    secondary.bluetooth.set_pairing = AsyncMock()
    app = build_app(
        fx.manager,
        fx.config_store,
        Path("/nonexistent-dist"),
        bluetooth=primary.bluetooth,
        adapter_sessions={slot.id: slot for slot in (primary, secondary)},
    )
    with TestClient(app) as client:
        response = client.put("/api/adapters/adapter-2/bluetooth", json={"pairing": True})
        assert response.status_code == 200
        secondary.bluetooth.set_pairing.assert_awaited_once_with(True)
        primary.bluetooth.set_pairing.assert_not_awaited()

        response = client.put("/api/bluetooth", json={"pairing": True})
        assert response.status_code == 200
        primary.bluetooth.set_pairing.assert_awaited_once_with(True)
        assert client.get("/api/adapters/unknown/bluetooth").status_code == 404


def test_selected_adapter_receives_manual_input_and_owns_its_macro(fx):
    fx.manager.adapter_id = "primary"
    primary = AdapterSession(
        "primary", "usb:0", fx.command_queue, None, input_manager=fx.manager
    )
    secondary_queue = queue.Queue()
    secondary_input = InputManager(secondary_queue, fx.macros_dir, adapter_id="adapter-2")
    secondary = AdapterSession(
        "adapter-2", "usb:1", secondary_queue, None, input_manager=secondary_input
    )
    app = build_app(
        fx.manager,
        fx.config_store,
        Path("/nonexistent-dist"),
        adapter_sessions={slot.id: slot for slot in (primary, secondary)},
    )

    try:
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["adapter_id"] == "primary"
            assert ws.receive_json()["type"] == "controllers"
            ws.send_json({"type": "state", "buttons": ["A"]})
            ws.send_json({"type": "select_adapter", "adapter_id": "adapter-2"})
            assert ws.receive_json()["adapter_id"] == "adapter-2"
            assert fx.manager.mix_manual_input(NEUTRAL) == NEUTRAL

            ws.send_json({"type": "state", "buttons": ["B"]})
            ws.send_json({"type": "select_adapter", "adapter_id": "adapter-2"})
            assert ws.receive_json()["adapter_id"] == "adapter-2"
            assert secondary_input.mix_manual_input(ControllerState(Button.ZR)).buttons == (
                Button.B | Button.ZR
            )
            assert fx.command_queue.empty()

            ws.send_json({
                "type": "macro", "op": "start",
                "macro": {
                    "version": 1, "name": "hold-b", "repeat": 0,
                    "actions": [{"do": "press", "button": "B"}, {"do": "wait", "ms": 100}],
                },
            })
            assert ws.receive_json()["mode"] == "macro"
            assert secondary_queue.get(timeout=1).buttons == Button.B
            ws.send_json({"type": "select_adapter", "adapter_id": "primary"})
            assert ws.receive_json()["mode"] == "manual"
            assert secondary_input.status()["macro"]["name"] == "hold-b"
            assert fx.command_queue.empty()
            ws.send_json({"type": "select_adapter", "adapter_id": "adapter-2"})
            assert ws.receive_json()["mode"] == "macro"
            ws.send_json({"type": "macro", "op": "cancel"})
            assert ws.receive_json()["mode"] == "manual"
            assert secondary_queue.get(timeout=1) == NEUTRAL
    finally:
        secondary_input.shutdown()


def test_multi_adapter_controls_preserve_independent_playback(fx):
    fx.manager.adapter_id = "primary"
    managers = {
        "primary": fx.manager,
        **{
            adapter_id: InputManager(queue.Queue(), fx.macros_dir, adapter_id=adapter_id)
            for adapter_id in ("adapter-2", "adapter-3")
        },
    }
    sessions = {
        adapter_id: AdapterSession(
            adapter_id, f"usb:{index}", manager.command_queue, None, input_manager=manager
        )
        for index, (adapter_id, manager) in enumerate(managers.items())
    }
    app = build_app(
        fx.manager, fx.config_store, Path("/nonexistent-dist"), adapter_sessions=sessions
    )
    hold = {
        "version": 1, "name": "hold", "repeat": 0,
        "actions": [{"do": "press", "button": "A"}, {"do": "wait", "ms": 100}],
    }
    (fx.macros_dir / "hold.json").write_text(
        '{"version": 1, "repeat": 0, "actions": [{"do": "wait", "ms": 100}]}',
        encoding="utf-8",
    )
    secondary = managers["adapter-2"]
    unselected = managers["adapter-3"]
    try:
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.receive_json()

            def select(*ids):
                ws.send_json({"type": "select_adapters", "adapter_ids": list(ids)})

            def macro(op, **payload):
                ws.send_json({"type": "macro", "op": op, **payload})

            def flush_commands():
                # The server processes inbound messages in order.
                ws.send_json({"type": "invalid"})
                while ws.receive_json()["type"] != "error":
                    pass

            select("primary", "adapter-2")
            assert list(ws.receive_json()["adapter_statuses"]) == ["primary", "adapter-2"]
            ws.send_json({"type": "state", "buttons": ["B"]})
            flush_commands()
            assert fx.manager.mix_manual_input(NEUTRAL).buttons == Button.B
            assert secondary.mix_manual_input(NEUTRAL).buttons == Button.B
            assert unselected.mix_manual_input(NEUTRAL) == NEUTRAL

            select("adapter-3")
            assert ws.receive_json()["adapter_id"] == "adapter-3"
            assert fx.manager.mix_manual_input(NEUTRAL) == NEUTRAL
            assert secondary.mix_manual_input(NEUTRAL) == NEUTRAL
            macro("start", macro=hold)
            select("adapter-2")
            macro("start", macro={**hold, "name": "first"})
            macro("pause")
            select("primary", "adapter-2")
            flush_commands()

            ws.send_json({"type": "event", "action": {"do": "press", "button": "X"}})
            flush_commands()
            assert fx.manager.mix_manual_input(NEUTRAL).buttons == Button.X
            assert secondary.mix_manual_input(NEUTRAL) == NEUTRAL

            macro("start", name="hold")
            snapshot = ws.receive_json()["adapter_statuses"]
            assert snapshot["primary"]["macro"] == {"name": "hold", "state": "running"}
            assert snapshot["adapter-2"]["macro"] == {"name": "first", "state": "paused"}
            macro("pause")
            flush_commands()
            assert fx.manager.status()["macro"]["state"] == "paused"
            assert unselected.status()["macro"]["state"] == "running"

            select("primary")
            macro("resume")
            flush_commands()
            assert fx.manager.status()["macro"]["state"] == "running"
            assert secondary.status()["macro"]["state"] == "paused"
            select("primary", "adapter-2")
            macro("resume")
            flush_commands()
            assert secondary.status()["macro"] == {"name": "first", "state": "running"}
            macro("start", macro={**hold, "name": "replacement"})
            flush_commands()
            assert fx.manager.status()["macro"]["name"] == "hold"
            assert secondary.status()["macro"]["name"] == "first"

            select("primary", "unknown")
            while ws.receive_json()["type"] != "error":
                pass
            macro("cancel")
            flush_commands()
            assert fx.manager.status()["macro"] is None
            assert secondary.status()["macro"] is None
            assert unselected.status()["macro"]["state"] == "running"

            macro("start", macro=hold)
            flush_commands()
            assert fx.manager.status()["macro"]["name"] == "hold"
            assert secondary.status()["macro"]["name"] == "hold"
            macro("cancel")
            ws.send_json({"type": "state", "buttons": ["Y"]})
            flush_commands()
            assert fx.manager.mix_manual_input(NEUTRAL).buttons == Button.Y
            assert secondary.mix_manual_input(NEUTRAL).buttons == Button.Y
        assert fx.manager.mix_manual_input(NEUTRAL) == NEUTRAL
        assert secondary.mix_manual_input(NEUTRAL) == NEUTRAL
    finally:
        secondary.shutdown()
        unselected.shutdown()


def test_adapter_colours_are_saved_independently(fx):
    primary = AdapterSession("primary", "usb:0", queue.Queue(), None)
    secondary = AdapterSession("adapter-2", "usb:1", queue.Queue(), None)
    primary.bluetooth.connected = True
    app = build_app(
        fx.manager,
        fx.config_store,
        Path("/nonexistent-dist"),
        adapter_sessions={slot.id: slot for slot in (primary, secondary)},
    )
    with TestClient(app) as client:
        secondary_path = "/api/adapters/adapter-2/colours"
        primary_path = "/api/adapters/primary/colours"
        result = client.patch(secondary_path, json={"body": "#aa0011"})
        assert result.status_code == 200
        assert result.json()["colours_reconnect_required"] is False
        assert client.get(secondary_path).json()["controller_colours"]["body"] == "#AA0011"
        assert client.get(primary_path).json()["controller_colours"]["body"] == "#000000"
        assert Config.load().adapter_colours["usb:1"]["body"] == "#AA0011"



def test_macro_list_get(fx):
    with fx.client() as c:
        assert "example" in c.get("/api/macros").json()["names"]
        r = c.get("/api/macros/example")
        assert r.status_code == 200
        assert "press" in r.json()["contents"]


def test_bluetooth_unavailable_and_validation(fx):
    with fx.client() as c:
        status = c.get("/api/bluetooth")
        assert status.status_code == 200
        assert status.json()["available"] is False
        assert status.json()["peers"] == []
        assert c.put("/api/bluetooth", json={"pairing": "yes"}).status_code == 400
        assert c.post("/api/bluetooth", json={"address": 12}).status_code == 400
        assert c.put("/api/bluetooth", json={"pairing": True}).status_code == 503


def test_bluetooth_disconnect_and_delete_routes(fx):
    with fx.client() as c:
        service = c.app.state.bluetooth
        service.disconnect = AsyncMock()
        service.forget = AsyncMock()
        assert c.post("/api/bluetooth", json={"action": "disconnect"}).status_code == 200
        service.disconnect.assert_awaited_once()
        response = c.request("DELETE", "/api/bluetooth", json={"address": "12:34:56:78:90:AB/P"})
        assert response.status_code == 200
        service.forget.assert_awaited_once_with("12:34:56:78:90:AB/P")
        assert c.request("DELETE", "/api/bluetooth", json={}).status_code == 400
        service.forget.side_effect = ValueError("Select a previously paired device")
        assert c.request("DELETE", "/api/bluetooth", json={"address": "unknown"}).status_code == 409


def test_bluetooth_cleanup_is_reported_as_a_retryable_conflict(fx):
    with fx.client() as c:
        service = c.app.state.bluetooth
        service.device = object()
        service.state = SessionState()
        service.state.session_stop.set()
        for method, body in (
            ("POST", {"address": "12:34:56:78:90:AB/P"}),
            ("PUT", {"pairing": True}),
        ):
            response = c.request(method, "/api/bluetooth", json=body)
            assert response.status_code == 409
            assert response.json()["code"] == "disconnecting"
            assert "wait a moment" in response.json()["error"]


def test_macro_put_validation(fx):
    with fx.client() as c:
        # Syntax error with line info.
        r = c.put(
            "/api/macros/bad",
            json={"contents": "{\n  \"actions\": ["},
        )
        assert r.status_code == 400
        body = r.json()
        assert body["error"] == "invalid JSON"
        assert body["line"] == 2

        # Semantic error with path.
        r = c.put(
            "/api/macros/bad",
            json={"contents": '{"version": 1, "actions": [{"do": "press", "button": "Q"}]}'},
        )
        assert r.status_code == 400
        body = r.json()
        assert body["error"] == "invalid macro"
        assert body["path"] == ["actions", 0, "button"]

        # Bad name (leading dot / traversal shapes are structurally
        # rejected by the name validator).
        r = c.put("/api/macros/.hidden", json={"contents": "{}"})
        assert r.status_code == 400


def test_macro_crud_roundtrip(fx):
    with fx.client() as c:
        contents = '{"version": 1, "name": "t", "actions": [{"do": "wait", "ms": 5}]}'
        assert c.put("/api/macros/new-one", json={"contents": contents}).status_code == 200
        assert c.get("/api/macros/new-one").json()["contents"] == contents
        assert c.delete("/api/macros/new-one").status_code == 200
        assert c.get("/api/macros/new-one").status_code == 404


def test_macro_delete_running_conflict(fx, monkeypatch):
    fx.manager.mode = "macro"
    monkeypatch.setattr(
        fx.manager,
        "status",
        lambda: {"mode": "macro", "macro": {"name": "example", "state": "running"}},
        raising=True,
    )
    with fx.client() as c:
        assert c.delete("/api/macros/example").status_code == 409



def test_controllers_get_and_select(fx):
    with fx.client() as c:
        r = c.get("/api/controllers").json()
        assert r["active"] == "g1"
        assert len(r["controllers"]) == 2

        r = c.put("/api/controllers/active", json={"guid": "g2"})
        assert r.status_code == 200
        assert r.json()["active"] == "g2"
        # Persisted.
        assert fx.config_store.config.controller_guid == "g2"

        assert c.put("/api/controllers/active", json={"guid": "nope"}).status_code == 404


def test_controller_select_refused_during_macro(fx, monkeypatch):
    def boom(ident):
        raise MacroActiveError("macro running")

    monkeypatch.setattr(fx.manager, "select_controller", boom)
    with fx.client() as c:
        r = c.put("/api/controllers/active", json={"guid": "g2"})
        assert r.status_code == 409



def test_presets_list(fx):
    with fx.client() as c:
        r = c.get("/api/presets").json()
        names = {p["name"] for p in r["presets"]}
        assert {"Xbox", "PlayStation", "Switch Pro Controller"} <= names
        filenames = {p["filename"] for p in r["presets"]}
        assert {"xbox", "playstation", "switch_pro"} <= filenames
        assert r["active"] == "xbox"


def test_preset_builtin_guards(fx):
    with fx.client() as c:
        assert c.put("/api/presets/xbox", json={"contents": "{}"}).status_code == 403
        assert c.delete("/api/presets/xbox").status_code == 403


def test_preset_custom_crud_and_activate(fx):
    contents = (
        '{"name": "Custom", "buttons": {"0": "A"}, '
        '"left_stick": {"x_axis": 0, "y_axis": 1}}'
    )
    with fx.client() as c:
        assert c.put("/api/presets/my-pad", json={"contents": contents}).status_code == 200
        listed = c.get("/api/presets").json()["presets"]
        assert any(
            p["name"] == "Custom"
            and p["filename"] == "my-pad"
            and not p["builtin"]
            for p in listed
        )

        r = c.get("/api/presets/my-pad")
        assert r.status_code == 200

        r = c.post("/api/presets/my-pad/activate")
        assert r.status_code == 200
        assert fx.config_store.config.preset == "my-pad"
        assert fx.config_store.config.controller_presets["g1"] == "my-pad"
        assert fx.manager.current_preset is not None
        assert fx.manager.current_preset.name == "Custom"
        assert fx.manager.current_preset_name == "my-pad"

        # Deleting the active preset is refused.
        assert c.delete("/api/presets/my-pad").status_code == 409

        # Switch back, then delete works.
        assert c.post("/api/presets/xbox/activate").status_code == 200
        assert c.delete("/api/presets/my-pad").status_code == 200


def test_preset_validation_path(fx):
    with fx.client() as c:
        r = c.put(
            "/api/presets/bad-pad",
            json={"contents": '{"buttons": {"0": "NOT_A_BUTTON"}}'},
        )
        assert r.status_code == 400
        assert r.json()["path"] == ["buttons", "0"]


def test_preset_name_rejects_path_traversal(fx):
    with fx.client() as c:
        r = c.put(
            "/api/presets/bad%5Cname",
            json={"contents": '{"name": "Bad"}'},
        )
        assert r.status_code == 403



def test_config_patch_applies_preset(fx):
    with fx.client() as c:
        r = c.patch("/api/config", json={"preset": "playstation"})
        assert r.status_code == 200
        assert r.json()["changed"].get("preset") == "playstation"
        assert fx.manager.current_preset is not None
        assert fx.manager.current_preset.name == "PlayStation"
        assert fx.manager.current_preset_name == "playstation"
        assert fx.config_store.config.controller_presets["g1"] == "playstation"


@pytest.mark.parametrize("connected", [False, True])
def test_save_colours_preserves_connection_and_reports_pending_change(fx, connected):
    from unittest.mock import Mock

    with fx.client() as c:
        bluetooth = c.app.state.bluetooth
        bluetooth.connected = connected
        connection = Mock() if connected else None
        bluetooth.connection = connection
        bluetooth.disconnect = AsyncMock()
        bluetooth.reconnect = AsyncMock()
        response = c.patch(
            "/api/config", json={"controller_colours": {"left_grip": "#ff0000"}}
        )
        assert response.status_code == 200
        assert response.json()["colours_reconnect_required"] is connected
        assert response.json()["config"]["controller_colours"]["left_grip"] == "#FF0000"
        bluetooth.disconnect.assert_not_called()
        bluetooth.reconnect.assert_not_called()
        assert bluetooth.connection is connection
        assert bluetooth.connected is connected
        assert Config.load().controller_colours["left_grip"] == "#FF0000"


@pytest.mark.parametrize(
    "colours", [None, [], {"body": "red"}, {"body": "#GGGGGG"}, {"unknown": "#123456"}]
)
def test_invalid_colours_rejected_before_other_settings_change(fx, colours):
    with fx.client() as c:
        before = c.get("/api/config").json()
        response = c.patch(
            "/api/config", json={"controller_colours": colours, "preset": "playstation"}
        )
        assert response.status_code == 400
        assert c.get("/api/config").json() == before
        assert fx.manager.current_preset_name != "playstation"


def test_switch_device_defaults_and_rename_persist_without_reconnecting(fx):
    with fx.client() as c:
        service = c.app.state.bluetooth
        first, second = "12:34:56:78:90:AB/P", "AB:CD:EF:12:34:56/P"
        status = {**c.get("/api/bluetooth").json(), "peers": [first, second]}
        service.status = AsyncMock(side_effect=lambda: dict(status))
        service.reconnect = AsyncMock()
        service.disconnect = AsyncMock()
        assert c.get("/api/bluetooth").json()["names"] == {
            first: "Switch Device 1", second: "Switch Device 2",
        }
        response = c.patch("/api/bluetooth", json={"address": first, "name": "  Living room  "})
        assert response.status_code == 200
        assert response.json()["names"][first] == "Living room"
        assert Config.load().switch_device_names == {first: "Living room"}
        assert c.get("/api/bluetooth").json()["names"][first] == "Living room"
        service.reconnect.assert_not_called()
        service.disconnect.assert_not_called()
        for name in ("", " ", "x" * 65, "bad\nname", 123):
            assert c.patch("/api/bluetooth", json={"address": first, "name": name}).status_code == 409
        assert c.patch("/api/bluetooth", json={"address": "unknown", "name": "Test"}).status_code == 409
        assert Config.load().switch_device_names == {first: "Living room"}
        service.forget = AsyncMock()
        assert c.request("DELETE", "/api/bluetooth", json={"address": first}).status_code == 200
        assert Config.load().switch_device_names == {}


def test_config_patch_does_not_persist_unusable_preset(fx):
    with fx.client() as c:
        r = c.patch("/api/config", json={"preset": "missing"})
        assert r.status_code == 404
        assert fx.config_store.config.preset == "xbox"



def test_ws_handshake_and_status(fx):
    with fx.client() as c, c.websocket_connect("/ws") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "status"
        assert frame["mode"] == "manual"
        # Second initial frame: controllers snapshot.
        frame = ws.receive_json()
        assert frame["type"] == "controllers"
        assert frame["active"] == "g1"

        # Start an inline macro; expect a status flip. The long wait
        # keeps it running until we cancel below (no finish race).
        ws.send_json(
            {
                "type": "macro",
                "op": "start",
                "macro": {
                    "version": 1,
                    "name": "hold",
                    "repeat": 0,
                    "actions": [
                        {"do": "press", "button": "A"},
                        {"do": "wait", "ms": 60000},
                    ],
                },
            }
        )
        frame = ws.receive_json()
        assert frame["type"] == "status"
        assert frame["mode"] == "macro"
        assert frame["macro"]["name"] == "hold"

        fx.manager.cancel_macro()
        # Drain frames until the manager reports manual again so the
        # macro thread is fully finished before the socket closes
        # (its finish broadcast otherwise races session teardown).
        for _ in range(5):
            frame = ws.receive_json()
            if frame["type"] == "status" and frame["mode"] == "manual":
                break
        else:
            pytest.fail("expected a manual status frame after cancel")

        # Invalid macro returns an error frame, not a crash.
        ws.send_json(
            {
                "type": "macro",
                "op": "start",
                "macro": {
                    "version": 1,
                    "name": "bad",
                    "actions": [{"do": "nope"}],
                },
            }
        )
        # cancel + error frames may interleave; drain until error.
        for _ in range(4):
            frame = ws.receive_json()
            if frame["type"] == "error":
                assert "invalid macro" in frame["message"]
                break
        else:
            pytest.fail("expected an error frame")


def test_ws_threadsafety_of_broadcast(fx):
    """Broadcasts from a foreign thread must not raise even without a
    bound asyncio loop."""
    fx.manager._emit_status()  # no subscribers: no-op path
    fx.manager.subscribe()
    thread = threading.Thread(target=fx.manager._emit_status)
    thread.start()
    thread.join()


def test_macro_rename(fx):
    with fx.client() as c:
        original = c.get("/api/macros/example").json()["contents"]
        assert c.patch("/api/macros/example", json={"name": "New name"}).status_code == 200
        assert c.get("/api/macros/example").status_code == 404
        assert c.get("/api/macros/New name").json()["contents"] == original
        assert c.patch("/api/macros/New name", json={"name": "NEW NAME"}).status_code == 200
        assert c.get("/api/macros").json()["names"] == ["NEW NAME"]
        assert c.put("/api/macros/other", json={"contents": original}).status_code == 200
        assert c.patch("/api/macros/NEW NAME", json={"name": "../bad"}).status_code == 400
        assert c.patch("/api/macros/missing", json={"name": "new"}).status_code == 404
        assert c.patch("/api/macros/NEW NAME", json={"name": 1}).status_code == 400


def test_macro_rename_running_conflict(fx, monkeypatch):
    monkeypatch.setattr(fx.manager, "status", lambda: {
        "macro": {"name": "example", "state": "paused"}
    })
    with fx.client() as c:
        assert c.patch("/api/macros/example", json={"name": "new"}).status_code == 409
        assert c.get("/api/macros/example").status_code == 200


def test_renamed_macro_runs_with_file_name(fx, monkeypatch):
    started = []
    monkeypatch.setattr(fx.manager, "start_macro", started.append)
    with fx.client() as c:
        assert c.patch("/api/macros/example", json={"name": "Renamed"}).status_code == 200
        fx.manager.start_macro_by_name("Renamed")
    assert started[0]["name"] == "Renamed"


def test_macro_rename_overwrites_destination(fx):
    with fx.client() as c:
        original = c.get("/api/macros/example").json()["contents"]
        replacement = '{"version": 1, "actions": [{"do": "wait", "ms": 10}]}'
        assert c.put("/api/macros/target", json={"contents": replacement}).status_code == 200
        assert c.patch("/api/macros/example", json={"name": "target"}).status_code == 200
        assert c.get("/api/macros/target").json()["contents"] == original
        assert c.get("/api/macros/example").status_code == 404


def test_vibration_defaults_on_and_persists_live_change(fx):
    with fx.client() as client:
        assert client.get("/api/config").json()["vibration_enabled"] is True
        result = client.patch("/api/config", json={"vibration_enabled": False})
        assert result.status_code == 200
        assert result.json()["config"]["vibration_enabled"] is False
        assert fx.config_store.config.vibration_enabled is False
        assert Config.load().vibration_enabled is False


def test_controller_vibration_preferences_are_independent_and_respect_global_switch(fx):
    with fx.client() as client:
        first = client.patch("/api/config", json={"controller_vibration": {"Pad-A": False}})
        assert first.status_code == 200
        result = client.patch("/api/config", json={"controller_vibration": {"pad-b": True}})
        assert result.json()["config"]["controller_vibration"] == {"pad-a": False, "pad-b": True}
        assert not fx.config_store.config.allows_controller_vibration("PAD-A")
        assert fx.config_store.config.allows_controller_vibration("pad-b")
        assert fx.config_store.config.allows_controller_vibration("unconfigured")
        client.patch("/api/config", json={"vibration_enabled": False})
        assert not Config.load().allows_controller_vibration("pad-b")
        client.patch("/api/config", json={"vibration_enabled": True})
        assert Config.load().allows_controller_vibration("pad-b")
        assert not Config.load().allows_controller_vibration("pad-a")


@pytest.mark.parametrize("invalid", [None, "false", 0, 1, [], {}])
def test_invalid_vibration_rejected_atomically(fx, invalid):
    with fx.client() as client:
        before = client.get("/api/config").json()
        result = client.patch(
            "/api/config", json={"vibration_enabled": invalid, "preset": "playstation"}
        )
        assert result.status_code == 400
        assert client.get("/api/config").json() == before


def test_debug_visibility_persists_without_restart(fx):
    with fx.client() as client:
        assert client.get("/api/config").json()["debug_enabled"] is False
        response = client.patch("/api/config", json={"debug_enabled": True})
        assert response.status_code == 200
        assert response.json()["config"]["debug_enabled"] is True
        assert Config.load().debug_enabled is True
        status = client.get("/api/debug").json()
        assert status["bd_address"] is None
        assert status["acl_connected"] is False
        assert status["hid_control_ready"] is False
        assert status["controllers"]["active"] == "g1"


@pytest.mark.parametrize(
    "changes",
    [
        {"tick_rate_hz": 0},
        {"macro_rate_hz": 1001},
        {"tick_rate_hz": True},
        {"macro_rate_hz": 1.5},
        {"nolog": "yes"},
        {"bumble_logging": None},
        {"ws_auth_required": 1},
        {"debug_enabled": "true"},
    ],
)
def test_invalid_debug_settings_do_not_persist(fx, changes):
    with fx.client() as client:
        before = fx.config_store.snapshot()
        assert client.patch("/api/config", json=changes).status_code == 400
        assert fx.config_store.snapshot() == before


def test_debug_changes_require_explicit_restart(fx):
    with fx.client() as client:
        before = fx.config_store.snapshot()
        assert (
            client.patch("/api/config", json={"tick_rate_hz": 144}).status_code == 409
        )
        assert (
            client.post(
                "/api/debug", json={"changes": {"tick_rate_hz": 144}}
            ).status_code
            == 403
        )
        client.patch("/api/config", json={"debug_enabled": True})
        assert (
            client.post(
                "/api/debug", json={"changes": {"tick_rate_hz": 144}}
            ).status_code
            == 409
        )
        assert fx.config_store.config.tick_rate_hz == before["tick_rate_hz"]


def test_debug_save_requests_restart_and_persists_new_identity(fx, monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock

    from bumble.keys import JsonKeyStore, PairingKeys

    monkeypatch.setattr("app.server.sys.platform", "win32")
    address = "AA:BB:CC:DD:EE:FF"
    key_file = tmp_path / "bonds.json"
    keys = JsonKeyStore(namespace="old-controller", filename=str(key_file))
    asyncio.run(keys.update(address, PairingKeys(link_key=PairingKeys.Key(bytes(16)))))
    with fx.client() as client:
        restart = Mock()
        client.app.state.restart_callback = restart
        client.app.state.shutdown_event = asyncio.Event()
        client.app.state.bluetooth.device = SimpleNamespace(
            keystore=keys, set_discoverable=AsyncMock(), set_connectable=AsyncMock(),
        )
        client.patch("/api/config", json={
            "debug_enabled": True, "switch_device_names": {address: "Living room Switch"},
        })
        assert asyncio.run(keys.get_all())
        response = client.post("/api/debug", json={
            "changes": {"tick_rate_hz": 144, "macro_rate_hz": 60, "bumble_logging": False},
            "regenerate_address": True,
        })
        assert response.status_code == 200
        restart.assert_called_once()
        assert client.app.state.shutdown_event.is_set()
        saved = Config.load()
        assert saved.tick_rate_hz == 144
        assert saved.macro_rate_hz == 60
        assert saved.bumble_logging is False
        assert saved.bt_address.startswith("98:B6:E9:")
        assert len(saved.bt_address) == 17
        assert saved.switch_device_names == {}
        reopened = JsonKeyStore(namespace="old-controller", filename=str(key_file))
        assert asyncio.run(reopened.get_all()) == []


def test_regeneration_failure_preserves_config_and_does_not_restart(fx, monkeypatch):
    import asyncio
    from unittest.mock import Mock

    monkeypatch.setattr("app.server.sys.platform", "win32")
    with fx.client() as client:
        restart = Mock()
        client.app.state.restart_callback = restart
        client.app.state.shutdown_event = asyncio.Event()
        client.patch("/api/config", json={"debug_enabled": True})
        before = fx.config_store.snapshot()
        response = client.post("/api/debug", json={"regenerate_address": True})
        assert response.status_code == 503
        assert fx.config_store.snapshot() == before
        restart.assert_not_called()
        assert not client.app.state.shutdown_event.is_set()


def test_debug_status_includes_switch_name_and_address(fx):
    with fx.client() as client:
        response = client.patch("/api/config", json={
            "switch_device_names": {"AA:BB:CC:DD:EE:FF": "Living room Switch"},
        })
        assert response.status_code == 200
        assert client.get("/api/debug").json()["switch_devices"] == [
            {"address": "AA:BB:CC:DD:EE:FF", "name": "Living room Switch"},
        ]


@pytest.mark.parametrize("target", [True, "adapter-2"])
@pytest.mark.parametrize("profiled", [False, True])
def test_debug_regenerates_only_the_target_adapter(
    fx, monkeypatch, target, tmp_path, profiled
):
    import asyncio
    from types import SimpleNamespace

    monkeypatch.setattr("app.server.sys.platform", "win32")
    primary_address = "98:B6:E9:12:34:56"
    first_switch = "AA:BB:CC:DD:EE:01"
    second_switch = "AA:BB:CC:DD:EE:02"
    names = {first_switch: "Living room Switch", second_switch: "Bedroom Switch"}
    fx.config_store.update({
        "bt_address": primary_address,
        "debug_enabled": True,
        "switch_device_names": names,
    })
    primary = AdapterSession("primary", "usb:0", fx.command_queue, None)
    secondary = AdapterSession("adapter-2", "usb:1", queue.Queue(), None)
    if profiled:
        primary.profile_index = 0
        secondary.profile_index = 1
        profiles = fx.config_store.ensure_adapter_profiles([primary.transport, secondary.transport])
    for slot, bd_address, peer in (
        (primary, primary_address, first_switch),
        (secondary, "02:12:34:56:78:9A", second_switch),
    ):
        slot.bluetooth.device = SimpleNamespace(
            public_address=bd_address,
            keystore=SimpleNamespace(
                get_all=AsyncMock(return_value=[(peer, SimpleNamespace(link_key=b"key"))]),
                delete_all=AsyncMock(),
            ),
            set_discoverable=AsyncMock(),
            set_connectable=AsyncMock(),
        )
        slot.bluetooth.state = SessionState()
    secondary.bluetooth.state.intr_ready.set()
    app = build_app(
        fx.manager, fx.config_store, Path("/nonexistent-dist"),
        bluetooth=primary.bluetooth,
        adapter_sessions={slot.id: slot for slot in (primary, secondary)},
        restart_callback=lambda: None,
        shutdown_event=asyncio.Event(),
    )
    with TestClient(app) as client:
        first, second = client.get("/api/debug").json()["adapters"]
        assert first["id"] == "primary"
        assert first["bd_address"] == primary_address
        assert first["switch_devices"] == [{"address": first_switch, "name": names[first_switch]}]
        assert not first["hid_interrupt_ready"]
        assert second["id"] == "adapter-2"
        assert second["bd_address"] == "02:12:34:56:78:9A"
        assert second["switch_devices"] == [{"address": second_switch, "name": names[second_switch]}]
        assert second["hid_interrupt_ready"]

        assert first["address_regeneration_available"]
        assert second["address_regeneration_available"]
        assert client.post("/api/debug", json={"regenerate_address": "unknown"}).status_code == 404
        assert client.post("/api/debug", json={"regenerate_address": target}).status_code == 200
        saved = Config.load()
        assert saved.switch_device_names == names
        if profiled:
            index = 0 if target is True else 1
            changed, unchanged = (primary, secondary) if index == 0 else (secondary, primary)
            changed.bluetooth.device.keystore.delete_all.assert_awaited_once()
            unchanged.bluetooth.device.keystore.delete_all.assert_not_awaited()
            assert saved.adapter_profiles[index].address != profiles[index].address
            assert saved.adapter_profiles[1 - index] == profiles[1 - index]
            assert saved.adapter_addresses == {}
            return
        if target is True:
            primary.bluetooth.device.keystore.delete_all.assert_awaited_once()
            secondary.bluetooth.device.keystore.delete_all.assert_not_awaited()
            assert saved.bt_address != primary_address
            assert saved.adapter_address_seed == primary_address
            assert saved.adapter_addresses == {}
        else:
            from app.main import stage_adapter_firmware
            from lib.firmware import (
                CONFIG_HEADER,
                CONFIG_NAME,
                FIRMWARE_NAME,
                prepare_bluetooth,
            )

            primary.bluetooth.device.keystore.delete_all.assert_not_awaited()
            secondary.bluetooth.device.keystore.delete_all.assert_awaited_once()
            assert saved.bt_address == primary_address
            address = saved.adapter_addresses["usb:1"]
            assert address.startswith("02:")
            assert address != second["bd_address"]
            (tmp_path / CONFIG_NAME).write_bytes(CONFIG_HEADER + bytes(6))
            (tmp_path / FIRMWARE_NAME).write_bytes(b"firmware")
            secondary.expected_address = address
            stage_adapter_firmware(secondary, tmp_path, tmp_path)
            assert secondary.expected_address == address
            assert (tmp_path / secondary.id / CONFIG_NAME).read_bytes() == (
                CONFIG_HEADER + bytes.fromhex(address.replace(":", ""))[::-1]
            )
            # The selected transport can become primary when a radio is removed.
            monkeypatch.setenv("BUMBLE_RTK_FIRMWARE_DIR", "unused")
            prepare_bluetooth(saved, tmp_path, address_override=address)
            assert (tmp_path / CONFIG_NAME).read_bytes() == (
                CONFIG_HEADER + bytes.fromhex(address.replace(":", ""))[::-1]
            )
            assert saved.bt_address == primary_address
