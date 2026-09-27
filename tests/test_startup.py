import asyncio
import queue

import pytest
from starlette.testclient import TestClient

import main as application
from lib.config import Config, ConfigStore
from lib.input.manager import InputManager
from lib.server import build_app
from lib.startup import (
    CONFIG_HEADER,
    CONFIG_NAME,
    FIRMWARE_NAME,
    missing_firmware,
    prepare_bluetooth,
)


def test_generated_address_is_persisted_and_binary_matches(tmp_path, monkeypatch):
    monkeypatch.setattr("lib.config.config_path", lambda: tmp_path / "config.json")
    monkeypatch.setenv("BUMBLE_RTK_FIRMWARE_DIR", "unused")
    config = Config()
    prepare_bluetooth(config, tmp_path)
    assert config.bt_address.startswith("98:B6:E9:")
    assert Config.load().bt_address == config.bt_address
    expected = CONFIG_HEADER + bytes.fromhex(config.bt_address.replace(":", ""))[::-1]
    assert (tmp_path / CONFIG_NAME).read_bytes() == expected
    original = config.bt_address
    prepare_bluetooth(config, tmp_path)
    assert config.bt_address == original


def test_existing_address_generates_matching_binary_without_saving(
    tmp_path, monkeypatch
):
    config = Config(bt_address="98:B6:E9:01:02:03")
    monkeypatch.setattr(
        config, "save", lambda: pytest.fail("Existing identity should not be saved")
    )
    monkeypatch.setenv("BUMBLE_RTK_FIRMWARE_DIR", "unused")
    prepare_bluetooth(config, tmp_path)
    assert (tmp_path / CONFIG_NAME).read_bytes() == CONFIG_HEADER + bytes.fromhex(
        "030201e9b698"
    )


def test_firmware_must_be_nonempty_file_in_root(tmp_path):
    assert missing_firmware(tmp_path) == FIRMWARE_NAME
    firmware = tmp_path / FIRMWARE_NAME
    firmware.touch()
    assert missing_firmware(tmp_path) == FIRMWARE_NAME
    firmware.write_bytes(b"firmware")
    assert missing_firmware(tmp_path) is None


def test_missing_firmware_signal_and_close(tmp_path):
    stop = asyncio.Event()
    manager = InputManager(queue.Queue(), tmp_path / "macros")
    app = build_app(
        manager,
        ConfigStore(Config()),
        tmp_path / "dist",
        missing_firmware=FIRMWARE_NAME,
        shutdown_event=stop,
    )
    with TestClient(app) as client:
        assert client.get("/api/startup").json() == {
            "kind": "missing_firmware",
            "filename": FIRMWARE_NAME,
            "ws_auth_required": True,
        }
        assert client.post("/api/application/close").status_code == 415
        assert not stop.is_set()
        assert client.post("/api/application/close", json={}).json() == {
            "closing": True
        }
        assert stop.is_set()


@pytest.mark.parametrize("headless", [False, True])
def test_missing_firmware_never_opens_transport(tmp_path, monkeypatch, headless):
    config = Config(web_host=None if headless else "127.0.0.1")
    monkeypatch.setattr(application.Config, "load", lambda _: config)
    monkeypatch.setattr(application, "application_dir", lambda: tmp_path)
    monkeypatch.setattr(application, "setup_logging", lambda: None)
    monkeypatch.setattr(
        application, "open_transport", lambda _: pytest.fail("Transport opened")
    )
    monkeypatch.setattr("sys.argv", ["main.py"])
    served = []

    async def serve(app, host, port, stop, **kwargs):
        served.append(app.state.missing_firmware)
        stop.set()

    monkeypatch.setattr(application, "serve_web", serve)
    if headless:
        with pytest.raises(SystemExit, match="Missing firmware"):
            asyncio.run(application.main())
        assert not served
    else:
        asyncio.run(application.main())
        assert served == [FIRMWARE_NAME]
