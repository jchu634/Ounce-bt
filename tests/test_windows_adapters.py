import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.main as application
from lib import bluetooth_transport
from lib.config import Config
from lib.windows_adapters import UsbRadio, _transport_specs


def test_usb_open_leaves_application_loop_free_and_cleans_up_on_cancel(monkeypatch):
    monkeypatch.setattr(bluetooth_transport, "sys", SimpleNamespace(platform="win32"))

    async def scenario():
        context = Mock()
        release = Event()
        started = asyncio.Event()
        loop = asyncio.get_running_loop()

        def open_device(*selector):
            loop.call_soon_threadsafe(started.set)
            release.wait(3)
            return context, None, None, None

        monkeypatch.setattr(bluetooth_transport, "_open_usb_device", open_device)
        task = asyncio.create_task(bluetooth_transport.open_transport("usb:5-2.4"))
        try:
            await asyncio.wait_for(started.wait(), 2)
            assert not task.done()
            assert not release.is_set()
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            context.close.assert_called_once()
        finally:
            release.set()

    asyncio.run(scenario())


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


def test_open_usb_device_enumerates_concurrently_outside_open_lock(monkeypatch):
    import threading

    both_enumerating = threading.Barrier(2, timeout=2)

    class _FakeHandle:
        def setAutoDetachKernelDriver(self, _value):
            pass

        def getConfiguration(self):
            return 1

    class _FakeDevice:
        def __init__(self, vid: int, pid: int):
            self._vid = vid
            self._pid = pid
            self.closed = False

        def getVendorID(self):
            return self._vid

        def getProductID(self):
            return self._pid

        def open(self):
            return _FakeHandle()

        def close(self):
            self.closed = True

    created_devices: list[list[_FakeDevice]] = []

    class _FakeContext:
        def open(self):
            pass

        def close(self):
            pass

        def getDeviceList(self, skip_on_error=False):
            # Both worker threads must reach enumeration concurrently.
            both_enumerating.wait()
            pair = [_FakeDevice(0x2357, 0x0604), _FakeDevice(0x0BDA, 0x8771)]
            created_devices.append(pair)
            return pair

    monkeypatch.setattr(bluetooth_transport, "load_libusb", lambda: None)
    monkeypatch.setattr(bluetooth_transport.usb1, "USBContext", _FakeContext)
    monkeypatch.setattr(bluetooth_transport.usb1, "hasCapability", lambda _cap: False)
    monkeypatch.setattr(
        bluetooth_transport,
        "find_endpoints",
        lambda _dev, forced_mode=False: (1, None, None, None, None, None, None, None),
    )

    results = []
    errors = []

    def worker(vid: int):
        try:
            results.append(
                bluetooth_transport._open_usb_device(lambda d: d.getVendorID() == vid, 0)
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(0x2357,))
    t2 = threading.Thread(target=worker, args=(0x0BDA,))
    t1.start()
    t2.start()
    t1.join(timeout=3)
    t2.join(timeout=3)
    assert errors == []
    assert len(results) == 2
    # Each scan must close the unmatched device while keeping the matched USBDevice alive
    # so its child USBDeviceHandle is not finalized before UsbTransport uses it.
    assert len(created_devices) == 2
    for pair in created_devices:
        assert sorted(device.closed for device in pair) == [False, True]
