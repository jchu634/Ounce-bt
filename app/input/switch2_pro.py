"""Wired Switch 2 Pro input for Windows builds that bundle SDL2."""

import ctypes
import time
from contextlib import closing
from functools import cache
from pathlib import Path

import pygame
import usb1
from bumble.transport.usb import load_libusb

from lib.windows_adapters import usb_port_chains_for_hid_path

NAME = "Nintendo Switch 2 Pro Controller"

# The raw indices follow the existing Switch Pro preset. The Xbox preset
# instead uses face-button positions and a hat for the D-pad.
_BUTTON_BITS = (
    (5, 0x08),
    (5, 0x04),
    (5, 0x02),
    (5, 0x01),  # A, B, X, Y
    (6, 0x01),
    (6, 0x10),
    (6, 0x02),
    (6, 0x04),
    (6, 0x08),
    (7, 0x40),
    (5, 0x40),  # L, R
    (7, 0x02),
    (7, 0x01),
    (7, 0x08),
    (7, 0x04),
    (6, 0x20),
)
_XBOX_ORDER = (1, 0, 3, 2, 9, 10, 4, 6, 8, 7, 5)

# Requests for input report mode, based on SDL's Switch 2 USB driver.
_REPORT_SETUP = (
    bytes.fromhex("0c9100020004000027000000"),
    bytes.fromhex("0c9100040004000027000000"),
    bytes.fromhex("0391000a0004000005000000"),
    bytes.fromhex("0391000d000800000100ffffffffffff"),
)


def is_wired_switch2_pro(guid: str) -> bool:
    guid = guid.casefold()
    return guid[:4] == "0300" and guid[8:12] == "7e05" and guid[16:20] == "6920"


def decode_report(report: bytes) -> tuple[tuple[float, ...], tuple[bool, ...]] | None:
    if len(report) != 64 or report[0] != 0x05:
        return None
    axes = []
    for offset in (11, 14):
        packed = int.from_bytes(report[offset : offset + 3], "little")
        axes.extend(((packed & 0xFFF) / 2048 - 1, 1 - (packed >> 12) / 2048))
    axes.extend((1.0 if report[7] & 0x80 else -1.0, 1.0 if report[5] & 0x80 else -1.0))
    return tuple(axes), tuple(bool(report[byte] & mask) for byte, mask in _BUTTON_BITS)


@cache
def _sdl():
    # SDL's HID functions expose vendor reports from the same device path
    # as SDL's generic joystick, without opening a second SDL joystick.
    dll = Path(pygame.__file__).parent / "SDL2.dll"
    sdl = ctypes.CDLL(str(dll) if dll.is_file() else "SDL2.dll")
    for name, args, result in (
        ("SDL_JoystickPathForIndex", [ctypes.c_int], ctypes.c_char_p),
        ("SDL_hid_open_path", [ctypes.c_char_p, ctypes.c_int], ctypes.c_void_p),
        (
            "SDL_hid_read_timeout",
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int],
            ctypes.c_int,
        ),
        ("SDL_hid_close", [ctypes.c_void_p], None),
    ):
        function = getattr(sdl, name)
        function.argtypes, function.restype = args, result
    return sdl


def _enable_reports(path: bytes) -> None:
    locations = usb_port_chains_for_hid_path(path)
    load_libusb()
    with usb1.USBContext() as context:
        matches = [
            device
            for device in context.getDeviceIterator(skip_on_error=True)
            if (device.getVendorID(), device.getProductID()) == (0x057E, 0x2069)
            and tuple(device.getPortNumberList()) in locations
        ]
        if len(matches) != 1:
            raise RuntimeError(
                "Could not identify the Switch 2 Pro Controller's USB interface"
            )
        try:
            with closing(matches[0].open()) as handle, handle.claimInterface(1):
                for request in _REPORT_SETUP:
                    handle.bulkWrite(0x02, request, timeout=300)
                    reply = handle.bulkRead(0x82, 64, timeout=300)
                    if (
                        len(reply) < 4
                        or reply[0] != request[0]
                        or reply[3] != request[3]
                    ):
                        raise RuntimeError(
                            "Unexpected Switch 2 Pro Controller setup reply"
                        )
        except (usb1.USBErrorAccess, usb1.USBErrorBusy) as error:
            raise RuntimeError(
                "Close Steam or another app using the Switch 2 Pro Controller"
            ) from error


class Switch2ProInput:
    def __init__(self, index: int, *, xbox_layout: bool):
        self._sdl = _sdl()
        path = self._sdl.SDL_JoystickPathForIndex(index)
        if not path or b"vid_057e&pid_2069" not in path.lower():
            raise RuntimeError(
                "The Switch 2 Pro Controller is no longer at the selected index"
            )
        self._hid = self._sdl.SDL_hid_open_path(path, 0)
        if not self._hid:
            raise RuntimeError(
                "Could not open the Switch 2 Pro Controller's HID interface"
            )
        try:
            _enable_reports(path)
        except BaseException:
            self.close()
            raise
        self._buffer = ctypes.create_string_buffer(64)
        self._order = _XBOX_ORDER if xbox_layout else tuple(range(len(_BUTTON_BITS)))
        self._xbox_layout = xbox_layout
        self._axes = (0.0, 0.0, 0.0, 0.0, -1.0, -1.0)
        self._buttons = (False,) * len(_BUTTON_BITS)
        self._last_report = time.monotonic()

    def update(self) -> None:
        for _ in range(16):
            count = self._sdl.SDL_hid_read_timeout(self._hid, self._buffer, 64, 0)
            if count < 0:
                raise OSError("Switch 2 Pro Controller HID input disconnected")
            if count == 0:
                break
            if (sample := decode_report(self._buffer.raw[:count])) is not None:
                self._axes, self._buttons = sample
                self._last_report = time.monotonic()
        if time.monotonic() - self._last_report > 0.35:
            self._axes = (0.0, 0.0, 0.0, 0.0, -1.0, -1.0)
            self._buttons = (False,) * len(_BUTTON_BITS)

    def close(self) -> None:
        self._sdl.SDL_hid_close(self._hid)

    def get_numaxes(self) -> int:
        return len(self._axes)

    def get_numbuttons(self) -> int:
        return len(self._order)

    def get_numhats(self) -> int:
        return int(self._xbox_layout)

    def get_axis(self, index: int) -> float:
        return self._axes[index]

    def get_button(self, index: int) -> bool:
        return self._buttons[self._order[index]]

    def get_hat(self, index: int) -> tuple[int, int]:
        up, down, left, right = self._buttons[11:15]
        return int(right) - int(left), int(up) - int(down)

    def rumble(self, *_args) -> bool:
        return False
