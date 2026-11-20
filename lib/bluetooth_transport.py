"""Compatibility for Linux Python builds without Bluetooth header definitions."""

import socket
import sys

from bumble.device import Device
from bumble.hci import HCI_Reset_Command
from bumble.host import Host


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
