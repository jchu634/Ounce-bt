"""Compatibility for Linux Python builds without Bluetooth header definitions."""

import socket
import sys


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
