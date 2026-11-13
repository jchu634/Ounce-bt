"""UI control of the Switch radio and saved Classic Bluetooth bonds."""

import asyncio
import logging

from bumble.core import ConnectionError as BluetoothConnectionError
from bumble.hci import HCI_CONNECTION_ALREADY_EXISTS_ERROR, Address
from bumble.l2cap import ClassicChannelSpec

logger = logging.getLogger("switch_pair")


class BluetoothDisconnectingError(ValueError):
    """A new connection must wait for the previous one to close."""


class BluetoothService:
    def __init__(self):
        self.device = None
        self.state = None
        self.connection = None
        self.connected = False
        self.pairing = False
        self.reconnecting = False
        self.reconnect_address = None
        self.failure_id = 0
        self.failure = None
        self._intentional_disconnect = False
        self._disconnect_requested = False
        self._lock = asyncio.Lock()
        self._disconnect_lock = asyncio.Lock()

    @property
    def disconnecting(self):
        # ACL loss wakes the session loop before its tasks and channels finish
        # cleanup. Only reset_for_session() acknowledges that cleanup is done.
        return (
            self._disconnect_requested
            or self._disconnect_lock.locked()
            or (self.state is not None and self.state.session_stop.is_set())
        )

    def _check_disconnecting(self):
        if self.disconnecting:
            raise BluetoothDisconnectingError(
                "The previous connection is still closing. "
                "Please wait a moment before reconnecting or starting pairing."
            )

    def attach(self, device, state, channel_handler):
        self.device = device
        self.state = state
        self.channel_handler = channel_handler
        state.on_hid_close = self.record_hid_channel_closed
        self.pairing = device.discoverable
        device.on("connection", self._on_connection)

    def _on_connection(self, connection):
        logger.info("Bluetooth ACL connected: peer=%s", connection.peer_address)
        self.connection = connection
        self._intentional_disconnect = False

        def disconnected(_reason):
            logger.info(
                "Bluetooth ACL disconnected: peer=%s reason=0x%02X intentional=%s",
                connection.peer_address,
                _reason,
                self._intentional_disconnect,
            )
            if self.connection is connection:
                self.connection = None
                self.connected = False
                self.state.session_stop.set()

        connection.on("disconnection", disconnected)

    def record_hid_channel_closed(self):
        if not self._intentional_disconnect:
            self.failure_id += 1
            self.failure = "The controller's HID channels closed unexpectedly."

    async def status(self):
        peers = []
        if self.device and self.device.keystore:
            peers = [
                address
                for address, keys in await self.device.keystore.get_all()
                if keys.link_key is not None
            ]
        return {
            "available": self.device is not None,
            "pairing": self.pairing,
            "state": "disconnecting"
            if self.disconnecting
            else "reconnecting"
            if self.reconnecting
            else (
                "connected"
                if self.connected
                else ("connecting" if self.connection else "disconnected")
            ),
            "address": str(self.connection.peer_address)
            if self.connection
            else self.reconnect_address,
            "peers": peers,
            "failure_id": self.failure_id,
            "failure": self.failure,
        }

    async def set_pairing(self, enabled):
        if enabled:
            self._check_disconnecting()
        async with self._lock:
            if self.device is None:
                raise RuntimeError("Bluetooth is not ready")
            if enabled:
                self._check_disconnecting()
            if enabled and (self.connection or self.reconnecting):
                raise ValueError("A Switch connection is already active")
            await self.device.set_discoverable(enabled)
            await self.device.set_connectable(enabled)
            self.pairing = enabled
            if not enabled and self.connection and not self.connected:
                self._intentional_disconnect = True
                await self.disconnect_connection(self.connection)

    async def disconnect(self):
        async with self._lock:
            await self._disconnect()

    async def disconnect_connection(self, connection):
        # The UI, reconnect error handler and session loop can all reach cleanup.
        # Bumble sends a new HCI command for every disconnect() call.
        async with self._disconnect_lock:
            if connection is not None and self.connection is connection:
                async with asyncio.timeout(10):
                    await connection.disconnect()

    async def _disconnect(self):
        if self.device is None:
            raise RuntimeError("Bluetooth is not ready")
        self._disconnect_requested = True
        try:
            await self.device.set_discoverable(False)
            await self.device.set_connectable(False)
            self.pairing = False
            if self.connection is not None:
                self._intentional_disconnect = True
                await self.disconnect_connection(self.connection)
        finally:
            self._disconnect_requested = False

    async def forget(self, address):
        async with self._lock:
            if self.device is None:
                raise RuntimeError("Bluetooth is not ready")
            if address not in (await self.status())["peers"]:
                raise ValueError("Select a previously paired device")
            # End the selected session before deleting its authentication keys.
            # Another saved peer can be removed without interrupting this session.
            if self.connection is None or str(self.connection.peer_address) == address:
                await self._disconnect()
            await self.device.keystore.delete(address)

    async def reconnect(self, address):
        self._check_disconnecting()
        async with self._lock:
            if self.device is None:
                raise RuntimeError("Bluetooth is not ready")
            self._check_disconnecting()
            if self.connection or self.reconnecting:
                raise ValueError("A Switch connection is already active")
            if address not in (await self.status())["peers"]:
                raise ValueError("Select a previously paired device")
            self.reconnecting = True
            self.reconnect_address = address
            try:
                await self.device.set_discoverable(False)
                await self.device.set_connectable(False)
                self.pairing = False
                async with asyncio.timeout(30):
                    connection = await self.device.connect_classic(
                        Address(address, Address.PUBLIC_DEVICE_ADDRESS), timeout=15
                    )
                    await connection.authenticate()
                    await connection.encrypt()
                    for psm in (0x11, 0x13):
                        channel = await connection.create_l2cap_channel(
                            ClassicChannelSpec(psm=psm)
                        )
                        self.channel_handler(psm, self.state)(channel)
            except BaseException as error:
                if self.connection:
                    await self.disconnect_connection(self.connection)
                if (
                    isinstance(error, BluetoothConnectionError)
                    and error.error_namespace == "hci"
                    and error.error_code == HCI_CONNECTION_ALREADY_EXISTS_ERROR
                ):
                    logger.warning(
                        "Adapter reports an existing Bluetooth connection: peer=%s",
                        address,
                        exc_info=True,
                    )
                    raise BluetoothDisconnectingError(
                        "Bluetooth still reports an existing connection to this Switch. "
                        "Please wait a moment, then try reconnecting again."
                    ) from error
                # Bumble also uses CancelledError to signal a lost ACL. It is
                # an operation failure unless our caller actually cancelled us.
                if (
                    isinstance(error, asyncio.CancelledError)
                    and not asyncio.current_task().cancelling()
                ):
                    raise ConnectionError(
                        "Switch disconnected during reconnect"
                    ) from error
                raise
            finally:
                self.reconnecting = False
                self.reconnect_address = None
