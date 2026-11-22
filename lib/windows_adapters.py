"""Find present USB Bluetooth radios backed by the Windows WinUSB driver."""

import ctypes
import re
import threading
from collections import Counter
from dataclasses import dataclass
from uuid import UUID

import usb1
from bumble.transport.usb import USB_BT_HCI_CLASS_TUPLE
from bumble.transport.usb import load_libusb as _load_bumble_libusb

from lib.sdl3 import bundled_libusb_path

_libusb_lock = threading.Lock()
_libusb_loaded = False


def load_libusb() -> None:
    """Load the bundled Windows libusb-1.0.dll when available, else fall back to Bumble."""
    global _libusb_loaded
    if _libusb_loaded:
        return
    with _libusb_lock:
        if _libusb_loaded:
            return
        bundled = bundled_libusb_path()
        if bundled is not None:
            usb1.loadLibrary(
                ctypes.WinDLL(str(bundled), use_errno=True, use_last_error=True)
            )
        else:
            _load_bumble_libusb()
        _libusb_loaded = True


@dataclass(frozen=True)
class UsbRadio:
    vendor: int
    product: int
    bus: int
    ports: tuple[int, ...]
    serial: str | None

    @property
    def location(self) -> tuple[int, int, tuple[int, ...]]:
        return self.vendor, self.product, self.ports


def _transport_specs(
    radios: list[UsbRadio], winusb_locations: set[tuple[int, int, tuple[int, ...]]]
) -> list[str]:
    locations = Counter(radio.location for radio in radios)
    serials = Counter((radio.vendor, radio.product, radio.serial) for radio in radios)
    specs = []
    for radio in radios:
        # A location path's USB ports do not identify its root controller.
        # Skip ambiguous matches across buses rather than opening the wrong radio.
        if (
            not radio.ports
            or locations[radio.location] != 1
            or radio.location not in winusb_locations
        ):
            continue
        serial = radio.serial
        if (
            serial
            and serials[radio.vendor, radio.product, serial] == 1
            and re.fullmatch(r"[a-zA-Z0-9_-]+", serial)
        ):
            specs.append(f"usb:{radio.vendor:04x}:{radio.product:04x}/{serial}")
        else:
            port_path = ".".join(str(port) for port in radio.ports)
            specs.append(f"usb:{radio.bus}-{port_path}")
    return specs


def discover_winusb_adapters() -> list[str]:
    locations = _winusb_locations()
    if not locations:
        return []
    load_libusb()
    radios = []
    with usb1.USBContext() as context:
        for device in context.getDeviceIterator(skip_on_error=True):
            if not is_bluetooth_usb(device):
                continue
            try:
                serial = device.getSerialNumber()
            except usb1.USBError:
                serial = None
            radios.append(
                UsbRadio(
                    device.getVendorID(),
                    device.getProductID(),
                    device.getBusNumber(),
                    tuple(device.getPortNumberList()),
                    serial,
                )
            )
    return _transport_specs(radios, locations)


def is_bluetooth_usb(device: usb1.USBDevice) -> bool:
    device_class = device.getDeviceClass()
    if (
        device_class,
        device.getDeviceSubClass(),
        device.getDeviceProtocol(),
    ) == USB_BT_HCI_CLASS_TUPLE:
        return True
    return device_class == 0 and any(
        (setting.getClass(), setting.getSubClass(), setting.getProtocol())
        == USB_BT_HCI_CLASS_TUPLE
        for configuration in device
        for interface in configuration
        for setting in interface
    )


class _PropertyKey(ctypes.Structure):
    _fields_ = [("guid", ctypes.c_ubyte * 16), ("pid", ctypes.c_uint32)]


def _winusb_locations() -> set[tuple[int, int, tuple[int, ...]]]:
    """Read USB port chains from present WinUSB device nodes via cfgmgr32."""
    cfgmgr = _location_api()
    ulong = ctypes.c_uint32
    ulong_ptr = ctypes.POINTER(ulong)
    cfgmgr.CM_Get_Device_ID_List_SizeW.argtypes = [ulong_ptr, ctypes.c_wchar_p, ulong]
    cfgmgr.CM_Get_Device_ID_ListW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ulong,
        ulong,
    ]
    # SERVICE | PRESENT | DONOTGENERATE. Listing leaves device nodes untouched.
    flags = 0x2 | 0x100 | 0x10000040
    buffer_small = 0x1A
    size = ulong()
    for _ in range(3):
        result = cfgmgr.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), "WinUSB", flags)
        if result:
            raise OSError(f"Could not list WinUSB devices (CONFIGRET 0x{result:X})")
        ids = ctypes.create_unicode_buffer(size.value)
        result = cfgmgr.CM_Get_Device_ID_ListW("WinUSB", ids, len(ids), flags)
        if result != buffer_small:
            break
    if result:
        raise OSError(f"Could not list WinUSB devices (CONFIGRET 0x{result:X})")

    locations = set()
    for instance in ids[:].split("\0"):
        match = re.match(
            r"USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})[&\\]", instance, re.I
        )
        if match is None:
            continue
        node = ulong()
        if not cfgmgr.CM_Locate_DevNodeW(ctypes.byref(node), instance, 0):
            locations.update(
                (int(match[1], 16), int(match[2], 16), chain)
                for chain in _port_chains(cfgmgr, node)
            )
    return locations


def _location_api():
    cfgmgr = ctypes.WinDLL("cfgmgr32")
    ulong = ctypes.c_uint32
    ulong_ptr = ctypes.POINTER(ulong)
    cfgmgr.CM_Locate_DevNodeW.argtypes = [ulong_ptr, ctypes.c_wchar_p, ulong]
    cfgmgr.CM_Get_DevNode_PropertyW.argtypes = [
        ulong,
        ctypes.POINTER(_PropertyKey),
        ulong_ptr,
        ctypes.c_void_p,
        ulong_ptr,
        ulong,
    ]
    return cfgmgr


def _port_chains(cfgmgr, node) -> set[tuple[int, ...]]:
    # DEVPKEY_Device_LocationPaths, as defined in devpkey.h.
    guid = UUID("a45c254e-df1c-4efd-8020-67d146a850e0")
    key = _PropertyKey((ctypes.c_ubyte * 16).from_buffer_copy(guid.bytes_le), 37)
    prop_type, size = ctypes.c_uint32(), ctypes.c_uint32()
    args = (node, ctypes.byref(key), ctypes.byref(prop_type))
    if cfgmgr.CM_Get_DevNode_PropertyW(*args, None, ctypes.byref(size), 0) != 0x1A:
        return set()
    value = ctypes.create_string_buffer(size.value)
    if cfgmgr.CM_Get_DevNode_PropertyW(*args, value, ctypes.byref(size), 0):
        return set()
    chains = set()
    for path in value.raw.decode("utf-16-le").split("\0"):
        ports = re.search(r"#USBROOT\(\d+\)((?:#USB\(\d+\))+)", path)
        if ports:
            chains.add(
                tuple(int(port) for port in re.findall(r"USB\((\d+)\)", ports[1]))
            )
    return chains
