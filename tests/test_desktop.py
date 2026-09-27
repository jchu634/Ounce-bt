import asyncio
import queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from lib.config import Config, ConfigStore
from lib.desktop import DesktopBridge, run_application
from lib.input.manager import InputManager
from lib.server import build_app


def app_for(tmp_path, **kwargs):
    config = Config(**kwargs)
    return build_app(
        InputManager(queue.Queue(), tmp_path),
        ConfigStore(config),
        tmp_path / "dist",
        ws_token="test-secret",
    )


@pytest.mark.parametrize(
    "protocols",
    [[], ["ounce-bt"], ["ounce-bt", "ounce-auth.wrong"], ["ounce-auth.test-secret"]],
)
def test_websocket_rejects_unauthenticated_connections(tmp_path, protocols):
    with (
        TestClient(app_for(tmp_path)) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws", subprotocols=protocols),
    ):
        pytest.fail("Unauthenticated WebSocket accepted")


def test_token_acceptance_and_no_http_secret(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/startup").json() == {
            "kind": "ready",
            "ws_auth_required": True,
        }
        assert "test-secret" not in client.get("/api/config").text
        with client.websocket_connect(
            "/ws", subprotocols=["ounce-bt", "ounce-auth.test-secret"]
        ) as ws:
            assert ws.accepted_subprotocol == "ounce-bt"
            assert ws.receive_json()["type"] == "status"
        # Runtime config changes must not downgrade the current session.
        app.state.config_store.config.ws_auth_required = False
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws"):
            pytest.fail("Session authentication was disabled")


def test_browser_mode_does_not_require_token(tmp_path):
    with TestClient(app_for(tmp_path, ws_auth_required=False)) as client:
        assert not client.get("/api/startup").json()["ws_auth_required"]
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "status"


def test_usb_driver_failure_is_reported_at_startup(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        app.state.transport_pending = True
        assert client.get("/api/startup").json()["kind"] == "checking"
        app.state.usb_driver_error = True
        assert client.get("/api/startup").json() == {
            "kind": "usb_driver_error",
            "ws_auth_required": True,
        }


def test_bridge_only_exposes_token_to_local_application():
    bridge = DesktopBridge("secret", ("http", "127.0.0.1:9127"))
    window = SimpleNamespace(
        get_current_url=lambda: "http://127.0.0.1:9127/macros", destroy=Mock()
    )
    bridge._window = window
    assert bridge.get_auth_token() == "secret"
    bridge.close_application()
    window.destroy.assert_called_once()
    for url in [
        "https://example.com",
        "http://127.0.0.1:9999",
        "http://127.0.0.1:9127.evil.test",
        "file:///test.html",
    ]:
        window.get_current_url = lambda url=url: url
        with pytest.raises(PermissionError):
            bridge.get_auth_token()
        with pytest.raises(PermissionError):
            bridge.close_application()


def test_browser_launcher_rejects_unreachable_authentication():
    with pytest.raises(ValueError, match="ws_auth_required=false"):
        run_application(Config(webview_enabled=False), None, Mock())


def test_window_close_cancels_backend(monkeypatch):
    import webview

    class Event:
        def __iadd__(self, callback):
            self.callback = callback
            return self

    closed = Event()
    window = SimpleNamespace(events=SimpleNamespace(closed=closed), destroy=Mock())
    monkeypatch.setattr(webview, "create_window", Mock(return_value=window))
    monkeypatch.setattr(webview, "start", lambda *args, **kwargs: closed.callback())
    cleaned = []

    async def backend(config, args, *, ws_token, ready, shutdown_event):
        assert len(ws_token) == 43
        ready.set()
        try:
            await asyncio.Future()
        finally:
            cleaned.append(True)

    run_application(Config(), None, backend)
    assert cleaned == [True]


def test_backend_failure_prevents_window_open(monkeypatch):
    import webview

    create = Mock()
    monkeypatch.setattr(webview, "create_window", create)

    async def backend(*args, **kwargs):
        raise OSError("Port unavailable")

    with pytest.raises(OSError, match="Port unavailable"):
        run_application(Config(), None, backend)
    create.assert_not_called()


def test_web_server_closes_active_websockets_before_cancellation(tmp_path, monkeypatch):
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed

    import main as application

    async def scenario():
        servers = []
        original = application.uvicorn.Server

        def make_server(config):
            server = original(config)
            servers.append(server)
            return server

        monkeypatch.setattr(application.uvicorn, "Server", make_server)
        app = app_for(tmp_path)
        task = asyncio.create_task(application.serve_web(app, "127.0.0.1", 0))
        try:

            async def started():
                while not servers or not servers[0].started:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(started(), 3)
            port = servers[0].servers[0].sockets[0].getsockname()[1]
            async with connect(
                f"ws://127.0.0.1:{port}/ws",
                subprotocols=["ounce-bt", "ounce-auth.test-secret"],
            ) as ws:
                await ws.recv()
                await ws.recv()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 3)
                with pytest.raises(ConnectionClosed):
                    await ws.recv()
            assert not servers[0].server_state.connections
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
