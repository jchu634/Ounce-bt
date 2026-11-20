import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from starlette.testclient import TestClient

import app.main as application
import lib.config as paths
from lib.bluetooth_transport import prepare_hci_socket
from lib.config import Config


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_platform_bluetooth_defaults(monkeypatch, platform):
    monkeypatch.setattr(paths.sys, "platform", platform)
    config = Config()
    assert config.transport_spec == "usb:0"
    assert not hasattr(config, "realtek_firmware")


def test_linux_python_without_bluetooth_headers(monkeypatch):
    import socket

    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.delattr(socket, "AF_BLUETOOTH", raising=False)
    monkeypatch.delattr(socket, "BTPROTO_HCI", raising=False)
    prepare_hci_socket()
    assert socket.AF_BLUETOOTH == 31
    assert socket.BTPROTO_HCI == 1


@pytest.mark.parametrize("platform", ["linux", "win32"])
@pytest.mark.parametrize("with_device_config", [False, True])
def test_usb_cli_and_old_firmware_setting(tmp_path, monkeypatch, platform, with_device_config):
    path = tmp_path / "config.json"
    path.write_text('{"transport_spec":"usb:1","realtek_firmware":true}')
    monkeypatch.setattr(paths, "config_path", lambda: path)
    monkeypatch.setattr(application, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(
        paths.sys, "argv",
        ["main.py", *(["pro_controller.json"] if with_device_config else []), "usb:0"],
    )
    config, _ = application.load_options()
    assert config.transport_spec == "usb:0"
    assert config.device_config == "pro_controller.json"
    assert not hasattr(config, "realtek_firmware")
    assert Config.load().transport_spec == "usb:1"


def test_removed_realtek_flag_is_rejected(monkeypatch):
    monkeypatch.setattr(paths.sys, "argv", ["main.py", "usb:0", "--realtek-firmware"])
    with pytest.raises(SystemExit) as error:
        application.load_options()
    assert error.value.code == 2


def test_packaged_linux_keeps_writes_outside_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "readonly-bundle"
    (bundle / "config").mkdir(parents=True)
    (bundle / "config/config.json").write_text('{"transport_spec":"usb:9"}')
    device = bundle / "config/pro_controller.json"
    device.write_text("{}")
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("APPDATA", str(bundle))  # Ignore Windows paths on Linux.
    config = Config.load()
    assert config.transport_spec == "usb:0"
    assert paths.application_dir() == bundle
    assert paths.resolve_config_file("pro_controller.json") == device
    assert config.resolve_folder("macros") == tmp_path / "data/ounce-bt/macros"
    assert config.resolve_folder("presets") == tmp_path / "data/ounce-bt/presets"
    assert config.bluetooth_firmware_dir == tmp_path / "data/ounce-bt/firmware"
    assert paths.state_dir() == tmp_path / "state/ounce-bt"
    config.save()
    assert (
        json.loads((tmp_path / "config/ounce-bt/config.json").read_text())[
            "transport_spec"
        ]
        == "usb:0"
    )
    assert (
        json.loads((bundle / "config/config.json").read_text())["transport_spec"]
        == "usb:9"
    )


@pytest.mark.parametrize("headless", [False, True])
def test_linux_starts_without_realtek_files_and_reports_transport_failure(
    tmp_path, monkeypatch, headless
):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(application, "setup_logging", lambda _bumble_logging=True: None)
    monkeypatch.setattr(application, "application_dir", lambda: tmp_path)
    monkeypatch.setattr(
        application,
        "missing_firmware",
        Mock(side_effect=AssertionError("Firmware checked")),
    )
    monkeypatch.setattr(
        application,
        "prepare_bluetooth",
        Mock(side_effect=AssertionError("Firmware patched")),
    )
    config = Config(web_host=None if headless else "127.0.0.1", input_specs=[])
    opened = []

    async def open_transport(spec):
        opened.append(spec)
        raise PermissionError("Operation not permitted")

    async def serve(app, host, port, stop, **kwargs):
        with TestClient(app) as client:
            response = client.get("/api/startup").json()
            assert response["kind"] == "bluetooth_error"
            assert "usb:0" in response["message"]
            assert "CAP_NET_RAW" in response["message"]
            assert "run-with-hci-caps.sh" in response["message"]
        stop.set()

    monkeypatch.setattr(application, "open_transport", open_transport)
    monkeypatch.setattr(application, "serve_web", serve)
    args = SimpleNamespace(nolog=False, preset=None)
    if headless:
        with pytest.raises(PermissionError, match="Operation not permitted"):
            asyncio.run(application.main(config, args))
    else:
        asyncio.run(application.main(config, args))
    assert opened == ["usb:0"]
