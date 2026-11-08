"""UI control of the Switch radio and saved Classic Bluetooth bonds."""

import asyncio

from bumble.hci import Address
from bumble.l2cap import ClassicChannelSpec


class BluetoothService:
    def __init__(self):
        self.device = None
        self.connection = None
        self.connected = False
        self.pairing = False
        self.reconnecting = False
        self.failure_id = 0
        self.failure = None
        self._intentional_disconnect = False
        self._lock = asyncio.Lock()

    def attach(self, device, state, channel_handler):
        self.device = device
        self.state = state
        self.channel_handler = channel_handler
        state.on_hid_close = self.record_hid_channel_closed
        self.pairing = device.discoverable
        device.on("connection", self._on_connection)

    def _on_connection(self, connection):
        self.connection = connection
        self._intentional_disconnect = False

        def disconnected(_reason):
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
            "state": "reconnecting"
            if self.reconnecting
            else (
                "connected"
                if self.connected
                else ("connecting" if self.connection else "disconnected")
            ),
            "address": str(self.connection.peer_address) if self.connection else None,
            "peers": peers,
            "failure_id": self.failure_id,
            "failure": self.failure,
        }

    async def set_pairing(self, enabled):
        async with self._lock:
            if self.device is None:
                raise RuntimeError("Bluetooth is not ready")
            if enabled and (self.connection or self.reconnecting):
                raise ValueError("A Switch connection is already active")
            await self.device.set_discoverable(enabled)
            await self.device.set_connectable(enabled)
            self.pairing = enabled
            if not enabled and self.connection and not self.connected:
                self._intentional_disconnect = True
                await self.connection.disconnect()

    async def disconnect(self):
        async with self._lock:
            await self._disconnect()

    async def _disconnect(self):
        if self.device is None:
            raise RuntimeError("Bluetooth is not ready")
        await self.device.set_discoverable(False)
        await self.device.set_connectable(False)
        self.pairing = False
        if self.connection is not None:
            self._intentional_disconnect = True
            await self.connection.disconnect()

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
        async with self._lock:
            if self.device is None:
                raise RuntimeError("Bluetooth is not ready")
            if self.connection or self.reconnecting:
                raise ValueError("A Switch connection is already active")
            if address not in (await self.status())["peers"]:
                raise ValueError("Select a previously paired device")
            self.reconnecting = True
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
            except BaseException:
                if self.connection:
                    await self.connection.disconnect()
                raise
            finally:
                self.reconnecting = False
