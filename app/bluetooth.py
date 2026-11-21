"""UI control of the Switch radio and saved Classic Bluetooth bonds."""

import asyncio
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from queue import Queue
from time import monotonic

from bumble.core import ConnectionError as BluetoothConnectionError
from bumble.hci import (
    HCI_CONNECTION_ALREADY_EXISTS_ERROR,
    HCI_PAGE_TIMEOUT_ERROR,
    Address,
    HCI_Write_Local_Name_Command,
)
from bumble.keys import JsonKeyStore
from bumble.l2cap import ClassicChannelSpec

from app.input.controller_service import ControllerRoute, ControllerService, LatestInput
from app.input.manager import InputManager
from lib.config import AdapterProfile
from lib.controller import ControllerVariant
from lib.input.state import (
    NEUTRAL,
    Button,
    ControllerState,
    horizontal_manual_input,
    rotate_joycon_stick,
)
from lib.sdp_records import sdp_record
from lib.switch_protocol import ControllerProtocol

logger = logging.getLogger("switch_pair")
JOYCON_GRIP_HOLD_SECONDS = 1.0


class BluetoothDisconnectingError(ValueError):
    """A new connection must wait for the previous one to close."""


class BluetoothPageTimeoutError(ConnectionError):
    """The Switch did not respond to a Classic connection attempt."""


class BluetoothService:
    def __init__(self):
        self.device = None
        self.state = None
        self.connection = None
        self.connected = False
        self.player_number: int | None = None
        self.pairing = False
        self.reconnecting = False
        self.reconnect_address = None
        self.failure_id = 0
        self.grip_reminder_id = 0
        self.failure = None
        self._intentional_disconnect = False
        self._disconnect_requested = False
        self._lock = asyncio.Lock()
        self._disconnect_lock = asyncio.Lock()
        self.controller_type = ControllerVariant.PRO
        self._pro_name = None
        self._pro_keystore = None

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

    def attach(self, device, state, channel_handler, *, pro_name=None):
        self.device = device
        self.state = state
        self.channel_handler = channel_handler
        self._pro_name = pro_name
        self._pro_keystore = getattr(device, "keystore", None)
        self.set_controller_type(self.controller_type)
        state.on_hid_close = self.record_hid_channel_closed
        self.pairing = device.discoverable
        device.on("connection", self._on_connection)

    def check_output_change(self):
        if (
            self.pairing or self.connection or self.connected or self.reconnecting
            or self.disconnecting or self._lock.locked()
        ):
            raise ValueError("Disconnect and stop pairing before changing the controller output.")

    def set_controller_type(self, variant: ControllerVariant) -> None:
        self.controller_type = variant
        if self.device is None:
            return
        self.device.keystore = self._pro_keystore
        if variant != ControllerVariant.PRO:
            base = self._pro_keystore
            if not isinstance(base, JsonKeyStore):
                base = JsonKeyStore.from_device(self.device)
            filename = base.filename.with_name(f"{base.filename.stem}-{variant}.json")
            self.device.keystore = JsonKeyStore(namespace=base.namespace, filename=str(filename))

    async def _apply_controller_identity(self):
        if self._pro_name is None:
            return
        name = self._pro_name if self.controller_type == ControllerVariant.PRO else (
            self.controller_type.bluetooth_name
        )
        if self.device.name != name:
            await self.device.send_sync_command(
                HCI_Write_Local_Name_Command(local_name=name.encode("utf-8"))
            )
            self.device.name = name
            self.device.inquiry_response = None
        self.device.sdp_service_records = sdp_record(self.controller_type)

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
            "player_number": self.player_number if self.connected else None,
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
            "grip_reminder_id": self.grip_reminder_id,
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
            if enabled:
                await self._apply_controller_identity()
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

    async def forget_all(self):
        """Disconnect before removing every bond for the current controller identity."""
        async with self._lock:
            if self.device is None:
                raise RuntimeError(
                    "Bluetooth must be ready before regenerating its address"
                )
            await self._disconnect()
            if self.device.keystore is not None:
                await self.device.keystore.delete_all()

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
                await self._apply_controller_identity()
                await self.device.set_discoverable(False)
                await self.device.set_connectable(False)
                self.pairing = False
                async with asyncio.timeout(30):
                    connection = await self._connect_peer(address)
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

    async def _connect_peer(self, address):
        peer = Address(address, Address.PUBLIC_DEVICE_ADDRESS)
        for attempt in range(3):
            try:
                return await self.device.connect_classic(peer, timeout=15)
            except BluetoothConnectionError as error:
                if error.error_namespace != "hci" or error.error_code != HCI_PAGE_TIMEOUT_ERROR:
                    raise
                if attempt == 2:
                    raise BluetoothPageTimeoutError(
                        "The Switch did not respond after three attempts. Wake the console "
                        "and open Controllers → Change Grip/Order, then try reconnecting."
                    ) from error
                logger.warning(
                    "Switch page timeout: adapter=%s peer=%s attempt=%s; retrying",
                    getattr(self.device, "public_address", "unknown"), address, attempt + 1,
                )
                await asyncio.sleep(0.35)


@dataclass
class AdapterSession:
    id: str
    transport: str
    input_queue: Queue[ControllerState] | LatestInput
    controller: ControllerService | ControllerRoute | None
    bluetooth: BluetoothService = field(default_factory=BluetoothService)
    expected_address: str | None = None
    firmware_dir: Path | None = None
    local_address: str | None = None
    error: str | None = None
    input_manager: InputManager | None = None
    profile_index: int | None = None
    legacy_keystore: bool = False
    combined_partner: "AdapterSession | None" = field(default=None, repr=False, compare=False)
    combined_input: ControllerState = NEUTRAL
    _grip_pending: bool = field(default=False, init=False)
    _grip_ready: bool = field(default=False, init=False)
    _grip_until: float = field(default=0.0, init=False)

    @property
    def primary(self) -> bool:
        return self.id == "primary"

    def mapping_variant(self) -> ControllerVariant:
        return ControllerVariant.COMBINED if self.combined_partner else self.bluetooth.controller_type

    def map_manual_input(self, state: ControllerState) -> ControllerState:
        return horizontal_manual_input(state, self.mapping_variant())

    def output_input(self, state: ControllerState) -> ControllerState:
        if not self.combined_partner:
            return rotate_joycon_stick(state, self.bluetooth.controller_type)
        owner = self.input_owner
        if owner is self:
            self.combined_input = state
        return owner.combined_input

    def reset_grip(self, *, pairing: bool = False) -> None:
        self._grip_pending = pairing and self.combined_partner is not None
        self._grip_ready = False
        self._grip_until = 0.0

    def apply_pairing_grip(self, protocol: ControllerProtocol, state: ControllerState) -> ControllerState:
        partner = self.combined_partner
        if partner is None or not protocol.device_info_queried or protocol.mode != "standard":
            return state
        self._grip_ready = True
        now = monotonic()
        if (
            (self._grip_pending or partner._grip_pending)
            and partner._grip_ready
            and self.bluetooth.connection is not None
            and partner.bluetooth.connection is not None
            and self.bluetooth.connection.peer_address == partner.bluetooth.connection.peer_address
        ):
            for side in (self, partner):
                side._grip_pending = False
                side._grip_until = now + JOYCON_GRIP_HOLD_SECONDS

        if now >= self._grip_until:
            return state
        buttons = Button.L if self.bluetooth.controller_type == ControllerVariant.LEFT else Button.R
        return replace(state, buttons=state.buttons | buttons)

    @property
    def input_owner(self) -> "AdapterSession":
        if self.combined_partner and self.bluetooth.controller_type == ControllerVariant.RIGHT:
            return self.combined_partner
        return self


def configure_adapter_outputs(
    sessions: dict[str, AdapterSession], profiles: list[AdapterProfile]
) -> None:
    by_index = {session.profile_index: session for session in sessions.values()}
    for index, session in by_index.items():
        if index is None:
            continue
        profile = profiles[index]
        partner = by_index.get(profile.combined_with) if profile.combined_with is not None else None
        if session.combined_partner is not partner:
            session.combined_input = NEUTRAL
            session.combined_partner = partner
        if session.bluetooth.controller_type != profile.controller_type:
            session.bluetooth.set_controller_type(profile.controller_type)
