import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from bumble.core import ConnectionError as BluetoothConnectionError
from bumble.core import PhysicalTransport
from bumble.hci import Address
from bumble.keys import JsonKeyStore, MemoryKeyStore, PairingKeys

import app.main as application
from app.bluetooth import BluetoothDisconnectingError, BluetoothService
from app.main import SessionState, make_l2cap_handler, run_until_disconnected
from lib.config import Config

ADDRESS = "12:34:56:78:90:AB"


def test_old_channel_callbacks_cannot_stop_a_new_session():
    from pyee import EventEmitter

    state = SessionState()

    def channel():
        result = EventEmitter()
        result.State = SimpleNamespace(OPEN="open")
        result.state = "open"
        return result

    old = channel()
    make_l2cap_handler(0x13, state)(old)
    state.reset_for_session()
    current = channel()
    make_l2cap_handler(0x13, state)(current)
    state.hid_opened = True
    closed = Mock()
    state.on_hid_close = closed
    old.emit("close")
    old.emit("open")
    old.sink(b"stale command")
    assert not state.session_stop.is_set()
    assert state.intr_ready.is_set()
    assert state.incoming.empty()
    closed.assert_not_called()
    current.emit("close")
    assert state.session_stop.is_set()
    closed.assert_called_once()


@pytest.mark.parametrize("headless", [False, True])
@pytest.mark.parametrize("realtek", [False, True])
def test_startup_pairing_requires_ui_action_unless_headless(
    monkeypatch, headless, realtek
):
    async def scenario():
        powered = asyncio.Event()
        scan_settings = []
        device = SimpleNamespace(
            name="Pro Controller",
            host=object(),
            public_address=Address(ADDRESS, Address.PUBLIC_DEVICE_ADDRESS),
            on=Mock(),
            create_l2cap_server=Mock(),
            send_command=AsyncMock(),
        )

        async def power_on():
            scan_settings.append((device.discoverable, device.connectable))
            powered.set()

        device.power_on = power_on

        @asynccontextmanager
        async def transport():
            yield SimpleNamespace(source=None, sink=None)

        async def serve(*args, **kwargs):
            await asyncio.Future()

        monkeypatch.setattr(
            application,
            "sys",
            SimpleNamespace(platform="win32" if realtek else "linux"),
        )
        monkeypatch.setattr(
            application, "setup_logging", lambda _bumble_logging=True: None
        )
        monkeypatch.setattr(application, "missing_firmware", lambda _: None)
        prepare = Mock()
        monkeypatch.setattr(application, "prepare_bluetooth", prepare)
        monkeypatch.setattr(application, "serve_web", serve)
        monkeypatch.setattr(
            application, "open_transport", AsyncMock(return_value=transport())
        )
        monkeypatch.setattr(
            application.Device, "from_config_file_with_hci", Mock(return_value=device)
        )
        monkeypatch.setattr(
            application.Config,
            "load",
            lambda _: Config(
                input_specs=[],
                transport_spec="usb:0" if realtek else "hci-socket:0",
                bt_address=ADDRESS if realtek else "98:B6:E9:12:34:57",
                web_host=None if headless else "127.0.0.1",
                web_port=None if headless else 9127,
            ),
        )
        monkeypatch.setattr("sys.argv", ["main.py"])
        task = asyncio.create_task(application.main())
        try:
            await asyncio.wait_for(powered.wait(), 2)
            assert prepare.call_count == int(realtek)
            assert scan_settings == [(headless, headless)]
            assert device.public_address.to_string(with_type_qualifier=False) == ADDRESS
            device.send_command.assert_awaited_once()
            assert not task.done()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


async def setup_service():
    keys = MemoryKeyStore()
    await keys.update(ADDRESS, PairingKeys(link_key=PairingKeys.Key(value=b"x" * 16)))
    await keys.update("AB:CD:EF:12:34:56", PairingKeys())
    device = SimpleNamespace(
        discoverable=True,
        keystore=keys,
        on=Mock(),
        set_discoverable=AsyncMock(),
        set_connectable=AsyncMock(),
        connect_classic=AsyncMock(),
    )
    service = BluetoothService()
    service.attach(device, SessionState(), Mock(return_value=Mock()))
    connection = SimpleNamespace(
        peer_address=ADDRESS,
        on=Mock(),
        authenticate=AsyncMock(),
        encrypt=AsyncMock(),
        create_l2cap_channel=AsyncMock(),
    )

    async def disconnect():
        connection.on.call_args.args[1](0)

    connection.disconnect = AsyncMock(side_effect=disconnect)

    async def connect(*args, **kwargs):
        service._on_connection(connection)
        return connection

    device.connect_classic.side_effect = connect
    return service, device, connection


def test_pairing_stop_start_and_connected_stop():
    async def scenario():
        service, device, connection = await setup_service()
        await service.set_pairing(False)
        device.set_discoverable.assert_awaited_with(False)
        device.set_connectable.assert_awaited_with(False)
        await service.set_pairing(True)
        assert (await service.status())["pairing"]
        service._on_connection(connection)
        await service.set_pairing(False)
        connection.disconnect.assert_awaited_once()
        assert service.state.session_stop.is_set()
        service._on_connection(connection)
        service.connected = True
        await service.set_pairing(False)
        assert connection.disconnect.await_count == 1

    asyncio.run(scenario())


def test_reconnect_saved_bond_and_disconnect():
    async def scenario():
        service, device, connection = await setup_service()
        assert (await service.status())["peers"] == [ADDRESS]
        with pytest.raises(ValueError, match="previously paired"):
            await service.reconnect("unknown")
        device.connect_classic.assert_not_awaited()
        await service.reconnect(ADDRESS)
        connection.authenticate.assert_awaited_once()
        connection.encrypt.assert_awaited_once()
        assert [
            call.args[0].psm for call in connection.create_l2cap_channel.await_args_list
        ] == [0x11, 0x13]
        assert service.channel_handler.call_count == 2
        assert (await service.status())["state"] == "connecting"
        with pytest.raises(ValueError, match="already active"):
            await service.reconnect(ADDRESS)
        await connection.disconnect()
        assert (await service.status())["state"] == "disconnecting"
        state = service.state
        await application.cleanup_session(service)
        state.reset_for_session()
        assert (await service.status())["state"] == "disconnected"

    asyncio.run(scenario())


def test_failed_reconnect_cleans_up_and_allows_retry():
    async def scenario():
        service, _, connection = await setup_service()
        connection.authenticate.side_effect = TimeoutError("authentication timed out")
        with pytest.raises(TimeoutError):
            await service.reconnect(ADDRESS)
        assert not service.reconnecting
        assert service.connection is None
        service.state.reset_for_session()
        connection.authenticate.side_effect = None
        await service.reconnect(ADDRESS)
        assert service.connection is connection

    asyncio.run(scenario())


def test_reconnect_and_pairing_rejected_until_disconnect_and_session_cleanup_finish():
    async def scenario():
        service, device, connection = await setup_service()
        service._on_connection(connection)
        service.connected = True
        scan_started = asyncio.Event()
        finish_scan = asyncio.Event()
        disconnect_started = asyncio.Event()
        emit_disconnection = asyncio.Event()
        disconnected = asyncio.Event()
        finish_disconnect = asyncio.Event()

        async def scan(_enabled):
            scan_started.set()
            await finish_scan.wait()

        async def disconnect():
            disconnect_started.set()
            await emit_disconnection.wait()
            connection.on.call_args.args[1](0x16)
            disconnected.set()
            await finish_disconnect.wait()

        async def assert_blocked():
            assert (await service.status())["state"] == "disconnecting"
            for operation in (service.reconnect(ADDRESS), service.set_pairing(True)):
                with pytest.raises(BluetoothDisconnectingError, match="wait a moment"):
                    await asyncio.wait_for(operation, 1)
            device.connect_classic.assert_not_awaited()

        device.set_discoverable.side_effect = scan
        connection.disconnect.side_effect = disconnect
        task = asyncio.create_task(service.disconnect())
        try:
            await asyncio.wait_for(scan_started.wait(), 1)
            await assert_blocked()
            finish_scan.set()
            await asyncio.wait_for(disconnect_started.wait(), 1)
            await assert_blocked()
            emit_disconnection.set()
            await asyncio.wait_for(disconnected.wait(), 1)
            assert service.connection is None
            await assert_blocked()
            finish_disconnect.set()
            await asyncio.wait_for(task, 1)
            # The HCI command has returned but the session loop has not yet
            # cancelled its tasks and reset its channel references/events.
            await assert_blocked()
            await application.cleanup_session(service)
            service.state.reset_for_session()
            assert (await service.status())["state"] == "disconnected"
            await service.reconnect(ADDRESS)
            device.connect_classic.assert_awaited_once()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("error_code", [0x0B, 0x04])
def test_adapter_connection_conflict_asks_user_to_wait_without_retry(error_code):
    async def scenario():
        service, device, _ = await setup_service()
        error = BluetoothConnectionError(
            error_code, PhysicalTransport.BR_EDR, ADDRESS, "hci"
        )
        device.connect_classic.side_effect = error
        if error_code == 0x0B:
            with pytest.raises(
                BluetoothDisconnectingError, match="wait a moment"
            ) as result:
                await service.reconnect(ADDRESS)
            assert result.value.__cause__ is error
        else:
            with pytest.raises(BluetoothConnectionError) as result:
                await service.reconnect(ADDRESS)
            assert result.value is error
        device.connect_classic.assert_awaited_once()
        assert not service.reconnecting
        assert (await service.status())["state"] == "disconnected"

    asyncio.run(scenario())


def test_reconnecting_status_retains_target_before_connection_exists():
    async def scenario():
        service, device, _ = await setup_service()
        connecting = asyncio.Event()
        release = asyncio.Event()

        async def connect(*args, **kwargs):
            connecting.set()
            await release.wait()
            raise TimeoutError("connection failed")

        device.connect_classic.side_effect = connect
        task = asyncio.create_task(service.reconnect(ADDRESS))
        try:
            await asyncio.wait_for(connecting.wait(), 1)
            status = await service.status()
            assert status["state"] == "reconnecting"
            assert status["address"] == ADDRESS
            assert service.connection is None
            release.set()
            with pytest.raises(TimeoutError):
                await task
            assert (await service.status())["address"] is None
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_hid_close_reports_one_failure_but_manual_disconnect_does_not():
    async def scenario():
        service, _, connection = await setup_service()
        service._on_connection(connection)
        state = service.state
        control = SimpleNamespace(
            state="closed", State=SimpleNamespace(OPEN="open"), on=Mock()
        )
        interrupt = SimpleNamespace(
            state="closed", State=SimpleNamespace(OPEN="open"), on=Mock()
        )
        make_l2cap_handler(0x11, state)(control)
        make_l2cap_handler(0x13, state)(interrupt)

        state.hid_opened = True
        control.on.call_args_list[1].args[1]()
        interrupt.on.call_args_list[1].args[1]()
        status = await service.status()
        assert status["failure_id"] == 1
        assert "HID channels closed" in status["failure"]

        service._on_connection(connection)
        state.hid_opened = True
        await service.disconnect()
        control.on.call_args_list[1].args[1]()
        assert (await service.status())["failure_id"] == 1

    asyncio.run(scenario())


def test_disconnect_cancels_handshake():
    async def scenario():
        state = SessionState()
        cancelled = asyncio.Event()

        async def handshake():
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        task = asyncio.create_task(run_until_disconnected(handshake(), state))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        state.session_stop.set()
        assert not await task
        assert cancelled.is_set()

    asyncio.run(scenario())


def test_disconnect_keeps_saved_bond_and_can_be_repeated():
    async def scenario():
        service, device, connection = await setup_service()
        service._on_connection(connection)
        service.connected = True
        await service.disconnect()
        assert (await service.status())["state"] == "disconnecting"
        service.state.reset_for_session()
        assert (await service.status())["state"] == "disconnected"
        assert (await service.status())["peers"] == [ADDRESS]
        assert not service.pairing
        device.set_connectable.assert_awaited_with(False)
        await service.disconnect()
        connection.disconnect.assert_awaited_once()

    asyncio.run(scenario())


def test_forget_disconnects_selected_peer_and_preserves_other_bonds():
    async def scenario():
        service, device, connection = await setup_service()
        other = "11:22:33:44:55:66/P"
        await device.keystore.update(
            other, PairingKeys(link_key=PairingKeys.Key(value=b"y" * 16))
        )
        service._on_connection(connection)
        service.connected = True
        await service.forget(other)
        connection.disconnect.assert_not_awaited()
        assert (await service.status())["peers"] == [ADDRESS]
        await device.keystore.update(
            other, PairingKeys(link_key=PairingKeys.Key(value=b"y" * 16))
        )
        await service.forget(ADDRESS)
        connection.disconnect.assert_awaited_once()
        service.state.reset_for_session()
        assert (await service.status())["state"] == "disconnected"
        assert (await service.status())["peers"] == [other]
        with pytest.raises(ValueError, match="previously paired"):
            await service.reconnect(ADDRESS)
        with pytest.raises(ValueError, match="previously paired"):
            await service.forget(ADDRESS)

    asyncio.run(scenario())


def test_failed_disconnect_preserves_pairing_keys():
    async def scenario():
        service, device, connection = await setup_service()
        service._on_connection(connection)
        connection.disconnect.side_effect = RuntimeError("disconnect failed")
        with pytest.raises(RuntimeError, match="disconnect failed"):
            await service.forget(ADDRESS)
        assert await device.keystore.get(ADDRESS) is not None

    asyncio.run(scenario())


def test_session_cleanup_and_ui_disconnect_share_one_hci_disconnect():
    async def scenario():
        service, _, connection = await setup_service()
        service._on_connection(connection)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def disconnect():
            entered.set()
            await release.wait()
            connection.on.call_args.args[1](0)

        connection.disconnect.side_effect = disconnect
        ui = asyncio.create_task(service.disconnect())
        await entered.wait()
        cleanup = asyncio.create_task(service.disconnect_connection(connection))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(ui, cleanup)
        connection.disconnect.assert_awaited_once()

    asyncio.run(scenario())


def test_bumble_disconnection_cancellation_is_a_connection_error():
    async def scenario():
        service, _, connection = await setup_service()

        async def authenticate():
            connection.on.call_args.args[1](0x13)
            raise asyncio.CancelledError("abort: disconnection event occurred.")

        connection.authenticate.side_effect = authenticate
        with pytest.raises(ConnectionError, match="disconnected during reconnect"):
            await service.reconnect(ADDRESS)
        assert not service.reconnecting
        assert service.connection is None

    asyncio.run(scenario())


def test_reconnect_preserves_cancellation_requested_by_the_caller():
    async def scenario():
        service, _, connection = await setup_service()
        entered = asyncio.Event()

        async def authenticate():
            entered.set()
            await asyncio.Future()

        connection.authenticate.side_effect = authenticate
        task = asyncio.create_task(service.reconnect(ADDRESS))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.connection is None
        assert not service.reconnecting

    asyncio.run(scenario())


def test_cleanup_failure_does_not_escape_the_session_loop():
    async def scenario():
        service, _, connection = await setup_service()
        service._on_connection(connection)
        connection.disconnect.side_effect = RuntimeError("HCI disconnect rejected")
        await application.cleanup_session(service)

    asyncio.run(scenario())


def test_forget_persists_across_key_store_reload(tmp_path):
    async def scenario():
        service, device, _ = await setup_service()
        filename = str(tmp_path / "keys.json")
        device.keystore = JsonKeyStore(namespace="controller", filename=filename)
        await device.keystore.update(
            ADDRESS, PairingKeys(link_key=PairingKeys.Key(value=b"x" * 16))
        )
        await service.forget(ADDRESS)
        reloaded = JsonKeyStore(namespace="controller", filename=filename)
        assert await reloaded.get(ADDRESS) is None

    asyncio.run(scenario())


def test_forget_all_disconnects_before_deleting_pairing_keys():
    async def scenario():
        service, device, connection = await setup_service()
        service._on_connection(connection)
        service.connected = True
        original_delete = device.keystore.delete_all

        async def delete_after_disconnect():
            assert service.connection is None
            assert not service.connected
            assert not service.pairing
            await original_delete()

        device.keystore.delete_all = delete_after_disconnect
        await service.forget_all()
        connection.disconnect.assert_awaited_once()
        assert await device.keystore.get_all() == []

    asyncio.run(scenario())
