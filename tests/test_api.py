"""REST API tests against a stubbed InputManager (no pygame, no
hardware, no asyncio loop needed)."""

from __future__ import annotations

import queue
import shutil
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

import lib.input.presets as presets_module
from lib.config import Config, ConfigStore
from lib.input.manager import InputManager, MacroActiveError
from lib.server import build_app
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



def test_macro_list_get(fx):
    with fx.client() as c:
        assert c.get("/api/macros").json() == {"names": ["example"]}
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
        assert r.json()["applied"] == "Custom"
        assert fx.config_store.config.preset == "my-pad"
        assert fx.config_store.config.controller_presets["g1"] == "my-pad"
        assert fx.manager.current_preset is not None
        assert fx.manager.current_preset.name == "Custom"
        assert fx.manager.current_preset_name == "my-pad"
        assert r.json()["preset"] == "my-pad"

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
        assert c.get("/api/macros").json() == {"names": ["NEW NAME"]}
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
        assert c.get("/api/macros").json() == {"names": ["target"]}
