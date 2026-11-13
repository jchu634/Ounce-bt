import argparse
import asyncio
import logging
import queue
import sys
from collections.abc import Callable
from time import perf_counter

import bumble.logging
import uvicorn
from bumble.device import Device
from bumble.hci import HCI_Write_Default_Link_Policy_Settings_Command
from bumble.keys import JsonKeyStore
from bumble.l2cap import ClassicChannelSpec
from bumble.pairing import PairingConfig, PairingDelegate
from bumble.transport import open_transport

from app.bluetooth import BluetoothService
from app.input.controller_service import ControllerService
from app.input.macro_source import MacroPlayerThread
from app.input.manager import InputManager
from app.server import build_app
from lib.bluetooth_transport import prepare_hci_socket
from lib.config import (
    Config,
    ConfigStore,
    application_dir,
    config_path,
    resolve_config_file,
    state_dir,
)
from lib.controller import ControllerTypes
from lib.firmware import missing_firmware, prepare_bluetooth
from lib.input import NEUTRAL, apply_to_protocol, parse_rumble
from lib.input import presets as presets_module
from lib.input.macros import load_macro
from lib.input.presets import (
    PresetConfig,
    PresetSelection,
    load_preset,
    resolve_controller_preset,
)
from lib.input.state import ControllerState
from lib.sdp_records import DEVICE_CLASS_GAMEPAD, sdp_record
from lib.switch_protocol import ControllerProtocol

HID_CONTROL_PSM = 0x0011
HID_INTERRUPT_PSM = 0x0013
TICK_RATE_HZ = 132

logger = logging.getLogger("switch_pair")


def setup_logging(bumble_logging: bool = True):
    bumble.logging.setup_basic_logging("info")
    logging.getLogger("bumble").setLevel(
        logging.INFO if bumble_logging else logging.CRITICAL + 1
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    log_dir = state_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "switch_packets.log")
    file_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s - %(message)s")
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def controller_spec_info(specs) -> tuple[bool, int | None]:
    """Scan input specs for controller entries.

    Returns ``(enabled, index_hint)`` where ``enabled`` is True when any
    ``controller[:idx]`` spec is present and ``index_hint`` is the first
    explicit index (None otherwise).
    """
    for spec in specs:
        spec = spec.strip()
        if spec == "controller":
            return True, None
        if spec.startswith("controller:"):
            try:
                return True, int(spec.split(":", 1)[1])
            except ValueError:
                return True, None
    return False, None


def build_input_sources(specs, command_queue):
    """Construct (not yet start) the daemon input threads for each --input spec.

    Spec formats:
      * ``controller`` / ``controller:<index>``  -> handled by the
        ControllerService (created in ``main``); skipped here
      * ``macro:<path>``                         -> JSON macro player
    """
    threads = []
    for spec in specs:
        spec = spec.strip()
        if spec == "controller" or spec.startswith("controller:"):
            continue  # owned by the ControllerService
        elif spec.startswith("macro:"):
            path = spec.split(":", 1)[1]
            macro = load_macro(path)
            threads.append(MacroPlayerThread(macro, command_queue))
        else:
            raise ValueError(f"Unknown --input spec: {spec!r}")
    return threads


async def run_pairing_handshake(protocol, interrupt_channel, incoming):
    """Exchange subcommands with the Switch until the handshake completes.

    The Switch considers the controller ready once vibration has been
    configured and a player number has been assigned.
    """
    received_first_message = False
    while True:
        try:
            reply = incoming.get_nowait()
        except asyncio.QueueEmpty:
            reply = None

        if reply:
            received_first_message = True
            logger.debug(f"Switch -> {reply.hex()}")

        protocol.process_commands(reply)
        report = protocol.get_report()
        if report:
            logger.debug(f"Controller -> {report.hex()}")
            interrupt_channel.send_pdu(report)

        if (
            reply
            and len(reply) > 45
            and protocol.vibration_configured
            and protocol.player_number
        ):
            logger.info(f"Handshake complete (player {protocol.player_number})")
            return

        # Before the Switch has spoken, poll slowly to avoid flooding;
        # once it starts talking, respond at ~15 Hz.
        if not received_first_message:
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(1 / 15)


async def run_mainloop(
    protocol,
    interrupt_channel,
    incoming,
    stop_event,
    command_queue,
    rumble_enabled: bool = True,
    controller_service: ControllerService | None = None,
    vibration_allowed: Callable[[], bool] | None = None,
    tick_rate_hz: int = TICK_RATE_HZ,
):
    """Steady-state loop: apply the latest controller input, process one
    Switch PDU per tick, forward rumble, and emit reports.

    Caches the last report payload so we don't flood the Switch with
    identical packets (important on the "Change Grip/Order" menu), and
    sends a keepalive every 132 ticks (~1 s) regardless.

    Console vibration state, the current preset and the saved setting gate playback.
    """
    tick = 0
    cached = None
    latest_state: ControllerState = NEUTRAL
    duration_start = perf_counter()

    try:
        while not stop_event.is_set():
            if (
                not interrupt_channel
                or interrupt_channel.state != interrupt_channel.State.OPEN
            ):
                logger.warning("Interrupt channel no longer open")
                return

            # Pull the latest input state from the command queue (latest-wins).
            # Held buttons/sticks persist across ticks when no new state arrives.
            while True:
                try:
                    latest_state = command_queue.get_nowait()
                except queue.Empty:
                    break

            # One Switch PDU per tick (non-blocking)
            try:
                reply = incoming.get_nowait()
            except asyncio.QueueEmpty:
                reply = None

            protocol.process_commands(reply)

            # Apply the latest input state (buttons + sticks) to the report.
            apply_to_protocol(protocol, latest_state)

            report = protocol.get_report()

            # Settings and presets are checked live, including ticks without a PDU.
            allowed = rumble_enabled and protocol.vibration_enabled
            if vibration_allowed is not None:
                allowed = allowed and vibration_allowed()
            if controller_service is not None:
                if not allowed:
                    controller_service.set_rumble(None)
                elif reply:
                    rumble = parse_rumble(reply)
                    if rumble is not None:
                        controller_service.set_rumble(rumble)

            try:
                if report[3:] != cached:
                    interrupt_channel.send_pdu(report)
                    cached = report[3:]
                elif tick >= tick_rate_hz:
                    interrupt_channel.send_pdu(report)
                    tick = 0
            except Exception as e:
                logger.warning(f"Failed to send report: {e}")
                return

            tick += 1

            # Maintain the target tick rate, accounting for processing time.
            duration_end = perf_counter()
            elapsed = duration_end - duration_start
            duration_start = duration_end
            sleep_time = max(0.0, 1 / tick_rate_hz - elapsed)
            await asyncio.sleep(sleep_time)

    finally:
        if controller_service is not None:
            controller_service.set_rumble(None)


class SessionState:
    """Mutable state shared between the L2CAP callbacks and the session loop."""

    def __init__(self):
        self.ctrl_channel = None
        self.intr_channel = None
        self.incoming = asyncio.Queue()
        self.ctrl_ready = asyncio.Event()
        self.intr_ready = asyncio.Event()
        self.session_stop = asyncio.Event()
        self.hid_opened = False
        self.on_hid_close = lambda: None

    def reset_for_session(self):
        self.hid_opened = False
        self.ctrl_channel = None
        self.intr_channel = None
        self.ctrl_ready.clear()
        self.intr_ready.clear()
        self.session_stop.clear()
        while not self.incoming.empty():
            try:
                self.incoming.get_nowait()
            except asyncio.QueueEmpty:
                break


def make_l2cap_handler(psm, state):
    """Build an L2CAP server handler for a given PSM."""

    def on_open(channel):
        if not is_current(channel):
            return
        if psm == HID_CONTROL_PSM:
            logger.info("HID Control channel opened")
            state.ctrl_ready.set()
        else:
            logger.info("HID Interrupt channel opened")
            state.intr_ready.set()

    def is_current(channel):
        return channel is (
            state.ctrl_channel if psm == HID_CONTROL_PSM else state.intr_channel
        )

    def on_close(channel):
        if not is_current(channel):
            logger.debug(
                "Ignoring close from an obsolete HID channel on PSM 0x%04X", psm
            )
            return
        if state.hid_opened:
            state.hid_opened = False
            state.on_hid_close()
        if psm == HID_INTERRUPT_PSM:
            logger.warning("HID Interrupt channel closed")
            state.intr_ready.clear()
            state.session_stop.set()
        else:
            logger.warning("HID Control channel closed")
            state.ctrl_ready.clear()
            state.session_stop.set()

    def handler(channel):
        logger.info(f"Incoming L2CAP connection on PSM 0x{psm:04X}")
        if psm == HID_CONTROL_PSM:
            state.ctrl_channel = channel
            # The Switch may send HID control transactions (SET_PROTOCOL, HANDSHAKE).
            # They aren't required, so we just observe them.
            channel.sink = lambda pdu: logger.debug(
                f"Control PDU (ignored): {pdu.hex() if isinstance(pdu, bytes) else pdu}"
            )
        else:
            state.intr_channel = channel
            channel.sink = lambda pdu: (
                state.incoming.put_nowait(pdu) if is_current(channel) else None
            )

        channel.on("open", lambda: on_open(channel))
        channel.on("close", lambda: on_close(channel))

        # The channel may already be OPEN by the time the handler runs.
        if channel.state == channel.State.OPEN:
            on_open(channel)

    return handler


async def serve_web(
    app, host: str, port: int, stop_event: asyncio.Event | None = None, ready=None
) -> None:
    """Run the Starlette app under uvicorn until cancelled.

    Shutdown is driven by task cancellation; ``should_exit`` is set on
    cancel so uvicorn finishes in-flight requests cleanly.
    """
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        lifespan="off",
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)

    async def stop_when_requested():
        await stop_event.wait()
        server.should_exit = True

    async def report_ready():
        while not server.started:
            await asyncio.sleep(0.01)
        ready.set()

    ready_task = asyncio.create_task(report_ready()) if ready is not None else None
    stop_task = asyncio.create_task(stop_when_requested()) if stop_event else None
    server_task = asyncio.create_task(server.serve())
    try:
        await asyncio.shield(server_task)
    except asyncio.CancelledError:
        server.should_exit = True
        await server_task
        raise
    finally:
        if ready_task:
            ready_task.cancel()
            await asyncio.gather(ready_task, return_exceptions=True)
        if stop_task:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)


def load_options():
    parser = argparse.ArgumentParser(
        description="Pro Controller (Bumble) for Nintendo Switch"
    )
    parser.add_argument(
        "device_config",
        nargs="?",
        default=None,
        help="Bumble device config JSON (defaults to config.json or pro_controller.json)",
    )
    parser.add_argument(
        "transport_spec",
        nargs="?",
        default=None,
        help="Bumble transport, e.g. usb:0 (defaults to config.json)",
    )
    parser.add_argument(
        "--firmware-dir",
        default=None,
        help="Windows: directory containing RTL8761BU firmware/config binaries",
    )
    parser.add_argument(
        "bt_address",
        nargs="?",
        default=None,
        help="Bluetooth address for the Realtek firmware patch (defaults to config.json)",
    )
    parser.add_argument(
        "--input",
        action="append",
        default=None,
        metavar="controller|controller:<idx>|macro:<path>",
        help="enable an input source (may be repeated). Overrides config.input_specs.",
    )
    parser.add_argument(
        "--web-host",
        default=None,
        help="web server bind host (default: from config, or 127.0.0.1)",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=None,
        help="web server bind port (default: from config, or 9127)",
    )
    parser.add_argument(
        "--nolog",
        action="store_true",
        help="disable logging for this run",
    )
    parser.add_argument(
        "--preset",
        default=None,
        metavar="xbox|playstation|switch_pro|<path.json>",
        help="controller mapping preset name or path to a JSON preset file "
        "(default: from config, or xbox)",
    )
    args = parser.parse_args()
    # Allow the release launcher to use just `AppImage usb:0` as well as the
    # historical `AppImage pro_controller.json usb:0` positional arguments.
    if (
        args.device_config is not None
        and args.device_config.startswith(("usb:", "hci-socket:"))
        and args.transport_spec is None
    ):
        args.transport_spec, args.device_config = args.device_config, None

    # Load persistent config, then apply non-persistent CLI overrides.
    # CLI flags are not persistent.
    overrides: dict = {}
    if args.device_config is not None:
        overrides["device_config"] = args.device_config
    if args.transport_spec is not None:
        overrides["transport_spec"] = args.transport_spec
    if args.bt_address is not None:
        overrides["bt_address"] = args.bt_address
    if args.input is not None:
        overrides["input_specs"] = list(args.input)
    if args.web_host is not None:
        overrides["web_host"] = args.web_host
    if args.web_port is not None:
        overrides["web_port"] = args.web_port
    if args.preset is not None:
        overrides["preset"] = args.preset
    if args.firmware_dir is not None:
        overrides["firmware_dir"] = args.firmware_dir

    config = Config.load(overrides or None)
    if not config.transport_spec:
        parser.error(
            "transport_spec is required (provide it as the second positional "
            "argument or set transport_spec in config.json)"
        )

    return config, args


async def main(
    config=None,
    args=None,
    *,
    ws_token=None,
    ready=None,
    shutdown_event=None,
    restart_callback=None,
):
    if config is None:
        config, args = load_options()
    if config.nolog or args.nolog:
        logging.disable(logging.CRITICAL)
    else:
        setup_logging(config.bumble_logging)
    config_store = ConfigStore(config)
    logger.info(f"Config path: {config_path()}")
    logger.info(f"Config: {config_store.snapshot()}")

    # Shared, thread-safe command queue. Input-source threads are producers;
    # the asyncio main loop is the consumer. The InputManager arbitrates
    # between physical / WebSocket input and macro playback.
    command_queue: queue.Queue[ControllerState] = queue.Queue()
    project_root = application_dir()
    macros_dir = config.resolve_folder(config.macros_dir)
    presets_module.PRESETS_DIR = config.resolve_folder(config.presets_dir)
    manager = InputManager(
        command_queue,
        macros_dir,
        macro_rate_hz=config.macro_rate_hz,
    )
    manager.bind_loop(asyncio.get_running_loop())

    firmware_root = config.bluetooth_firmware_dir
    # Linux uses the adapter's existing firmware and public address. Legacy
    # realtek_firmware config keys are ignored by Config.load.
    patch_firmware = sys.platform == "win32"
    firmware = missing_firmware(firmware_root) if patch_firmware else None
    if firmware:
        message = f"Missing required Bluetooth file: {firmware_root / firmware}. Bluetooth files are not distributed with this application."
        logger.error(message)
        if not config.web_enabled:
            raise SystemExit(message)
        stop_event = shutdown_event or asyncio.Event()
        app = build_app(
            manager,
            config_store,
            project_root / "frontend" / "dist",
            missing_firmware=str(firmware_root / firmware),
            shutdown_event=stop_event,
            ws_token=ws_token,
            restart_callback=restart_callback,
        )
        try:
            await serve_web(
                app, config.web_host, config.web_port, stop_event, ready=ready
            )
        finally:
            manager.shutdown()
        return

    if patch_firmware:
        prepare_bluetooth(config, firmware_root)

    # Load the configured preset as the initial fallback. Once pygame selects
    # a controller, its saved GUID mapping or detected controller type replaces
    # this value. An explicit --preset keeps its session-wide override behavior.
    try:
        preset = load_preset(config.preset)
    except (FileNotFoundError, ValueError, TypeError) as e:
        logger.warning(f"Could not load preset {config.preset!r}: {e}; using defaults")
        preset = PresetConfig.default()
    manager.set_preset(preset, config.preset)
    logger.info(
        f"Controller preset: {preset.name} "
        f"(rumble {'on' if preset.rumble_enabled else 'off'})"
    )

    # Physical gamepads are owned by the ControllerService (single pygame
    # thread: enumeration, selection, hotplug). Macro specs still become
    # standalone MacroPlayerThreads.
    controllers_enabled, controller_index = controller_spec_info(config.input_specs)
    controller_service: ControllerService | None = None
    if controllers_enabled:
        initial_ident = config.controller_guid or controller_index
        if args.preset is not None:

            def preset_resolver(_guid: str, _name: str) -> PresetSelection:
                return PresetSelection(args.preset, preset)
        else:

            def preset_resolver(guid: str, name: str) -> PresetSelection:
                return resolve_controller_preset(
                    guid,
                    name,
                    config_store.config.controller_presets,
                )

        controller_service = ControllerService(
            command_queue,
            preset=preset,
            initial_ident=initial_ident,
            on_change=manager.on_controllers_changed,
            preset_resolver=preset_resolver,
            on_preset_changed=manager.on_controller_preset_changed,
        )
        manager.set_controller_service(controller_service)

    input_threads = build_input_sources(config.input_specs, command_queue)
    if controller_service is not None:
        input_threads.append(controller_service)
    manager.attach_pygame_threads(input_threads)

    # Launch the web server (Starlette + uvicorn) on the same loop so the
    # WS endpoint can submit states directly to ``command_queue``.
    bluetooth = BluetoothService()
    web_task: asyncio.Task | None = None
    stop_event = shutdown_event or asyncio.Event()
    app = None
    if config.web_enabled:
        frontend_dist = project_root / "frontend" / "dist"
        app = build_app(
            manager,
            config_store,
            frontend_dist,
            bluetooth=bluetooth,
            shutdown_event=stop_event,
            ws_token=ws_token,
            restart_callback=restart_callback,
        )
        app.state.transport_pending = True
        web_task = asyncio.create_task(
            serve_web(app, config.web_host, config.web_port, stop_event, ready=ready)
        )
        logger.info(
            f"Web UI: http://{config.web_host}:{config.web_port} "
            f"(ws://{config.web_host}:{config.web_port}/ws)"
        )
    else:
        logger.info("Web server disabled (host or port is unset)")

    try:
        if config.transport_spec.startswith("hci-socket:"):
            prepare_hci_socket()
        transport = await open_transport(config.transport_spec)
    except Exception as error:
        causes = [error]
        while causes[-1].__cause__ is not None:
            causes.append(causes[-1].__cause__)
        windows_driver_error = sys.platform == "win32" and any(
            "LIBUSB_ERROR_NOT_SUPPORTED" in str(cause) for cause in causes
        )
        if app is None:
            raise
        logger.exception("Bluetooth transport could not start")
        if windows_driver_error:
            app.state.usb_driver_error = True
        else:
            app.state.bluetooth_error = bluetooth_startup_error(config, error)
        try:
            await stop_event.wait()
        finally:
            manager.shutdown()
            if web_task is not None:
                web_task.cancel()
                await asyncio.gather(web_task, return_exceptions=True)
        return

    async with transport as hci_transport:
        device = Device.from_config_file_with_hci(
            str(resolve_config_file(config.device_config)),
            hci_transport.source,
            hci_transport.sink,
        )

        # Classic / HID service configuration
        device.classic_enabled = True
        device.class_of_device = DEVICE_CLASS_GAMEPAD
        # Headless mode has no pairing button. Web sessions start idle.
        device.discoverable = not config.web_enabled
        device.connectable = not config.web_enabled
        device.pairing_config_factory = lambda _: PairingConfig(
            sc=True,
            mitm=False,
            bonding=True,
            delegate=PairingDelegate(
                io_capability=PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT
            ),
        )
        device.sdp_service_records = sdp_record()

        state = SessionState()

        # Register the HID L2CAP servers once. They persist across
        # reconnects: a new Switch connection re-triggers the handler,
        # re-points the channel references, and re-arms the ready events.
        device.create_l2cap_server(
            spec=ClassicChannelSpec(psm=HID_CONTROL_PSM),
            handler=make_l2cap_handler(HID_CONTROL_PSM, state),
        )
        device.create_l2cap_server(
            spec=ClassicChannelSpec(psm=HID_INTERRUPT_PSM),
            handler=make_l2cap_handler(HID_INTERRUPT_PSM, state),
        )

        try:
            await device.power_on()
            # power_on reads the actual address from the controller. Assigning
            # Device.public_address cannot change the radio's BD_ADDR.
            if (
                patch_firmware
                and device.public_address.to_string(with_type_qualifier=False).upper()
                != config.bt_address.upper()
            ):
                raise RuntimeError(
                    "The adapter address does not match the patched firmware. "
                    "Unplug/replug the adapter before retrying."
                )
        except Exception as error:
            if app is None:
                raise
            logger.exception("Bluetooth controller initialization failed")
            app.state.bluetooth_error = bluetooth_startup_error(config, error)
            try:
                await stop_event.wait()
            finally:
                manager.shutdown()
                if web_task is not None:
                    web_task.cancel()
                    await asyncio.gather(web_task, return_exceptions=True)
            return
        if config.pairing_dir:
            pairing_dir = config.resolve_folder(config.pairing_dir)
            filename = str(device.public_address).lower().replace(":", "-") + ".json"
            device.keystore = JsonKeyStore(
                namespace=str(device.public_address),
                filename=str(pairing_dir / filename),
            )
        # Enable authentication + encryption + secure connections policy.
        await device.send_command(
            HCI_Write_Default_Link_Policy_Settings_Command(
                default_link_policy_settings=0x0005
            )
        )

        bluetooth.attach(device, state, make_l2cap_handler)
        if app is not None:
            app.state.transport_pending = False

        logger.info(f"Powered on. address={device.public_address} name={device.name!r}")
        if not config.web_enabled:
            logger.info("Advertising as Pro Controller. Waiting for a Switch...")
        else:
            logger.info(
                "Bluetooth ready. Use Start pairing or Reconnect in the web UI."
            )

        # Start input sources now that the radio is up. They are daemon
        # threads; they keep producing states whether or not a session
        # is active, and the main loop drains stale entries per session.
        # ``InputManager`` may pause them when a macro is running.
        for t in input_threads:
            t.start()
            logger.info(f"Started input source: {t.name}")

        try:
            # Reconnect loop: each iteration is one full controller session.
            while True:
                state.reset_for_session()
                # Drop any stale input that accumulated before this session.
                while not command_queue.empty():
                    try:
                        command_queue.get_nowait()
                    except queue.Empty:
                        break

                logger.info("Waiting for both HID channels to open...")

                async def wait_for_channels():
                    await state.ctrl_ready.wait()
                    await state.intr_ready.wait()

                if not await run_until_disconnected(wait_for_channels(), state):
                    await cleanup_session(bluetooth)
                    continue

                interrupt_channel = state.intr_channel
                if interrupt_channel is None:
                    logger.warning("Interrupt channel missing; retrying.")
                    continue

                logger.info("Both HID channels open; starting controller session.")
                state.hid_opened = True
                protocol = ControllerProtocol(
                    ControllerTypes.PRO_CONTROLLER, str(device.public_address)
                )
                protocol.set_colours(**config_store.snapshot()["controller_colours"])

                try:
                    if not await run_until_disconnected(
                        asyncio.wait_for(
                            run_pairing_handshake(
                                protocol, interrupt_channel, state.incoming
                            ),
                            timeout=30,
                        ),
                        state,
                    ):
                        continue
                    bluetooth.connected = True
                    if config.web_enabled:
                        await bluetooth.set_pairing(False)
                    await run_mainloop(
                        protocol,
                        interrupt_channel,
                        state.incoming,
                        state.session_stop,
                        command_queue,
                        controller_service=controller_service,
                        tick_rate_hz=config.tick_rate_hz,
                        vibration_allowed=lambda: (
                            config_store.config.vibration_enabled
                            and (manager.current_preset or preset).rumble_enabled
                        ),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Session ended with an error")
                else:
                    logger.info("Session ended cleanly")
                finally:
                    bluetooth.connected = False
                    await cleanup_session(bluetooth)

                logger.info("Re-listening for a new Switch connection...")
        finally:
            manager.shutdown()
            if web_task is not None:
                web_task.cancel()
                try:
                    await web_task
                except asyncio.CancelledError:
                    pass


async def cleanup_session(bluetooth):
    try:
        await bluetooth.disconnect_connection(bluetooth.connection)
    except Exception:
        logger.exception("Bluetooth session cleanup failed; keeping session loop alive")


async def run_until_disconnected(awaitable, state):
    operation = asyncio.ensure_future(awaitable)
    stopped = asyncio.create_task(state.session_stop.wait())
    try:
        done, _ = await asyncio.wait(
            {operation, stopped}, return_when=asyncio.FIRST_COMPLETED
        )
        if stopped in done:
            return False
        await operation
        return True
    finally:
        operation.cancel()
        stopped.cancel()
        await asyncio.gather(operation, stopped, return_exceptions=True)


def bluetooth_startup_error(config: Config, error: Exception) -> str:
    message = f"Could not start Bluetooth transport {config.transport_spec}: {error}."
    if sys.platform == "linux":
        if config.transport_spec.startswith("hci-socket:"):
            message += (
                " The adapter must be powered off in BlueZ, unblocked by rfkill, "
                "and available exclusively to Bumble. HCI user channels require "
                "CAP_NET_RAW and CAP_NET_ADMIN. See the Linux setup instructions."
            )
        elif config.transport_spec.startswith("usb:"):
            message += (
                " Launch with run-with-hci-caps.sh (CAP_NET_RAW and CAP_NET_ADMIN), "
                "and check USB device permissions and adapter availability. "
                "See the Linux setup instructions."
            )
    return message


def launch():
    from app.desktop import run_application

    config, args = load_options()
    if run_application(config, args, main):
        import os

        packaged = "__compiled__" in globals() or getattr(sys, "frozen", False)
        argv = (
            [sys.executable, *sys.argv[1:]] if packaged else [sys.executable, *sys.argv]
        )
        os.execv(sys.executable, argv)
