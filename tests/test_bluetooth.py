import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from bumble.keys import JsonKeyStore, MemoryKeyStore, PairingKeys

import main as application
from lib.bluetooth import BluetoothService
from lib.config import Config
from main import SessionState, make_l2cap_handler, run_until_disconnected

ADDRESS = "12:34:56:78:90:AB"


@pytest.mark.parametrize("headless", [False, True])
def test_startup_pairing_requires_ui_action_unless_headless(monkeypatch, headless):
    async def scenario():
        powered = asyncio.Event()
        scan_settings = []
        device = SimpleNamespace(
            name="Pro Controller",
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

        async def serve(*args):
            await asyncio.Future()

        monkeypatch.setattr(application, "setup_logging", lambda: None)
        monkeypatch.setattr(application, "missing_firmware", lambda _: None)
        monkeypatch.setattr(application, "prepare_bluetooth", lambda *_: None)
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
                bt_address="98:B6:E9:12:34:57",
                web_host=None if headless else "127.0.0.1",
                web_port=None if headless else 9127,
            ),
        )
        monkeypatch.setattr("sys.argv", ["main.py"])
        task = asyncio.create_task(application.main())
        try:
            await asyncio.wait_for(powered.wait(), 2)
            assert scan_settings == [(headless, headless)]
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
        connection.authenticate.side_effect = None
        await service.reconnect(ADDRESS)
        assert service.connection is connection

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
