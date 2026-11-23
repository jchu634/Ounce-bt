"""Open platform Bluetooth transports and handle host compatibility."""

import asyncio
import logging
import re
import socket
import sys
from collections.abc import Callable
from threading import Event, Lock

import usb1
from bumble.device import Device
from bumble.hci import HCI_Reset_Command
from bumble.host import Host
from bumble.transport import _wrap_transport
from bumble.transport import open_transport as open_bumble_transport
from bumble.transport.common import TransportInitError
from bumble.transport.usb import (
    UsbPacketSink,
    UsbPacketSource,
    UsbTransport,
    find_endpoints,
)

from lib.windows_adapters import is_bluetooth_usb, load_libusb

logger = logging.getLogger(__name__)
_usb_open_lock = Lock()


def _usb_selector(spec: str) -> tuple[Callable[[usb1.USBDevice], bool], int] | None:
    if re.fullmatch(r"\d+", spec):
        return is_bluetooth_usb, int(spec)
    if re.fullmatch(r"\d+-\d+(?:\.\d+)*", spec):
        def matches_port(device):
            ports = ".".join(map(str, device.getPortNumberList()))
            return spec == f"{device.getBusNumber()}-{ports}"

        return matches_port, 0
    match = re.fullmatch(r"([0-9a-fA-F]+):([0-9a-fA-F]+)(?:/([\w-]+)|#(\d+))?", spec)
    if match is None:
        return None
    vendor, product = int(match[1], 16), int(match[2], 16)
    serial = match[3]

    def matches_id(device):
        if (device.getVendorID(), device.getProductID()) != (vendor, product):
            return False
        if serial is None:
            return True
        try:
            return device.getSerialNumber() == serial
        except usb1.USBError:
            return False

    return matches_id, int(match[4] or 0)


def _open_usb_device(matches: Callable[[usb1.USBDevice], bool], index: int):
    """Return a configured native handle without creating asyncio packet tasks."""
    load_libusb()
    context = usb1.USBContext()
    devices: list[usb1.USBDevice] = []
    try:
        context.open()
        # Enumerate outside _usb_open_lock so multiple adapters scan concurrently.
        devices = context.getDeviceList(skip_on_error=True)
        # Serial lookups and device.open() may briefly open the same WinUSB device.
        with _usb_open_lock:
            matched: usb1.USBDevice | None = None
            for device in devices:
                if matched is None and matches(device):
                    if index == 0:
                        matched = device
                        continue
                    index -= 1
                device.close()
            devices = [matched] if matched is not None else []
            if matched is None:
                raise TransportInitError("device not found")

            endpoints = find_endpoints(matched, forced_mode=False)
            if endpoints is None:
                raise TransportInitError("no compatible interface found for device")
            metadata = {
                "vendor_id": matched.getVendorID(),
                "product_id": matched.getProductID(),
            }
            handle = matched.open()
            # Keep `matched` open: USBDeviceHandle registers its finalizer on
            # `matched`, so closing `matched` would immediately libusb_close(handle).
            devices = []
            if usb1.hasCapability(usb1.CAP_SUPPORTS_DETACH_KERNEL_DRIVER):
                try:
                    handle.setAutoDetachKernelDriver(True)
                except usb1.USBError as error:
                    logger.warning("Unable to auto-detach USB kernel driver: %s", error)
            try:
                current_configuration = handle.getConfiguration()
            except usb1.USBError:
                current_configuration = None
            if current_configuration != endpoints[0]:
                try:
                    handle.setConfiguration(endpoints[0])
                except usb1.USBError as error:
                    logger.warning("Unable to configure the USB device: %s", error)
            return context, handle, metadata, endpoints
    except BaseException:
        for device in devices:
            try:
                device.close()
            except usb1.USBError:
                logger.debug("Failed to close enumerated USB device", exc_info=True)
        context.close()
        raise


async def open_transport(spec: str):
    if sys.platform not in ("win32", "linux") or not spec.startswith("usb:"):
        return await open_bumble_transport(spec)
    selector = _usb_selector(spec[4:])
    if selector is None:
        return await open_bumble_transport(spec)

    cancelled = Event()

    def open_device():
        if cancelled.is_set():
            return None
        return _open_usb_device(*selector)

    opening = asyncio.create_task(asyncio.to_thread(open_device))
    try:
        context, handle, metadata, endpoints = await asyncio.shield(opening)
    except asyncio.CancelledError:
        # The worker may still return a libusb handle after shutdown starts.
        cancelled.set()
        result, = await asyncio.gather(opening, return_exceptions=True)
        if result is not None and not isinstance(result, BaseException):
            await asyncio.to_thread(result[0].close)
        raise

    _, acl, sco, interrupt_in, bulk_in, iso_in, bulk_out, iso_out = endpoints
    try:
        source = UsbPacketSource(handle, metadata, interrupt_in, bulk_in, iso_in)
        sink = UsbPacketSink(handle, bulk_out, iso_out)
        return _wrap_transport(UsbTransport(context, handle, acl, sco, source, sink))
    except BaseException:
        context.close()
        raise


class WindowsUsbHost(Host):
    """Keep stale USB command completions out of the next HCI transaction."""

    async def send_sync_command(self, command, response_timeout=None):
        if isinstance(command, HCI_Reset_Command) and response_timeout is not None:
            # Give the Realtek probe's first reset time to complete before it
            # issues another reset with the same opcode.
            response_timeout = max(response_timeout, 1.0)
        return await super().send_sync_command(command, response_timeout)

    def on_command_processed(self, event):
        if self.pending_response is not None and (
            self.pending_response.done()
            or (
                self.pending_command is not None
                and self.pending_command.op_code != event.command_opcode
            )
        ):
            return
        super().on_command_processed(event)


class WindowsUsbDevice(Device):
    @classmethod
    def from_config_with_hci(cls, config, hci_source, hci_sink):
        return cls(config=config, host=WindowsUsbHost(hci_source, hci_sink))


def prepare_hci_socket() -> None:
    if sys.platform != "linux":
        return
    # python-build-standalone (used by uv and our AppImage build) may omit
    # Bluetooth constants. Bumble binds sockaddr_hci through libc, so it only
    # needs these stable Linux UAPI values, not Python's sockaddr support.
    if not hasattr(socket, "AF_BLUETOOTH"):
        socket.AF_BLUETOOTH = 31
    if not hasattr(socket, "BTPROTO_HCI"):
        socket.BTPROTO_HCI = 1
