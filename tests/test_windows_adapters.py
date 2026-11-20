import pytest

import app.main as application
from lib.config import Config
from lib.windows_adapters import UsbRadio, _transport_specs


def test_winusb_discovery_uses_unique_serials_and_disambiguates_usb_locations():
    first = UsbRadio(0x2357, 0x0604, 5, (2, 4), "UNIQUE")
    second = UsbRadio(0x0BDA, 0x8771, 5, (2, 3, 1), "SHARED")
    third = UsbRadio(0x0BDA, 0x8771, 5, (2, 3, 2), "SHARED")
    system_radio = UsbRadio(0x0E8D, 0x7925, 5, (1,), None)
    ambiguous = UsbRadio(0x2357, 0x0604, 5, (3,), "ONE")
    other_bus = UsbRadio(0x2357, 0x0604, 6, (3,), "TWO")
    locations = {radio.location for radio in (first, second, third, ambiguous)}

    assert _transport_specs(
        [first, system_radio, second, third, ambiguous, other_bus], locations
    ) == ["usb:2357:0604/UNIQUE", "usb:5-2.3.1", "usb:5-2.3.2"]


@pytest.mark.parametrize(
    "platform, arguments, configured, expected",
    [
        ("win32", [], "usb:0", True),
        ("win32", ["usb:0"], "usb:0", False),
        ("win32", ["--adapter", "usb:1"], "usb:0", False),
        ("win32", ["--no-auto-adapters"], "usb:0", False),
        ("win32", [], "usb:2", False),
        ("linux", [], "usb:0", False),
    ],
)
def test_winusb_detection_respects_explicit_transports(
    monkeypatch, platform, arguments, configured, expected
):
    monkeypatch.setattr(application.sys, "argv", ["main.py", *arguments])
    monkeypatch.setattr(application.sys, "platform", platform)
    monkeypatch.setattr(
        Config,
        "load",
        lambda overrides: Config(**({"transport_spec": configured} | (overrides or {}))),
    )
    _, args = application.load_options()
    assert args.auto_adapters is expected
