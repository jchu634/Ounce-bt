import argparse
import asyncio
import logging
import queue
from time import perf_counter

import bumble.logging
import uvicorn
from bumble.device import Device
from bumble.hci import Address, HCI_Write_Default_Link_Policy_Settings_Command
from bumble.keys import JsonKeyStore
from bumble.l2cap import ClassicChannelSpec
from bumble.pairing import PairingConfig, PairingDelegate
from bumble.transport import open_transport

from lib.bluetooth import BluetoothService
from lib.config import (
    Config,
    ConfigStore,
    application_dir,
    config_path,
    resolve_config_file,
)
from lib.controller import ControllerTypes
from lib.input import NEUTRAL, apply_to_protocol, parse_rumble
from lib.input import presets as presets_module
from lib.input.controller_service import ControllerService
from lib.input.macro_source import MacroPlayerThread, load_macro
from lib.input.manager import InputManager
from lib.input.presets import (
    PresetConfig,
    PresetSelection,
    load_preset,
    resolve_controller_preset,
)
from lib.input.state import ControllerState
from lib.sdp_records import DEVICE_CLASS_GAMEPAD, sdp_record
from lib.server import build_app
from lib.startup import missing_firmware, prepare_bluetooth
from lib.switch_protocol import ControllerProtocol

HID_CONTROL_PSM = 0x0011
HID_INTERRUPT_PSM = 0x0013
TICK_RATE_HZ = 132

logger = logging.getLogger("switch_pair")


def setup_logging():
    bumble.logging.setup_basic_logging("info")
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    file_handler = logging.FileHandler("switch_packets.log")
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
    enabled and a player number has been assigned. Mirrors the proven
    flow in nxbt_bumble's ControllerServer._run_pairing_handshake.
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
            and protocol.vibration_enabled
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
):
    """Steady-state loop: apply the latest controller input, process one
    Switch PDU per tick, decode rumble, and emit reports.

    Caches the last report payload so we don't flood the Switch with
    identical packets (important on the "Change Grip/Order" menu), and
    sends a keepalive every 132 ticks (~1 s) regardless.

    When ``rumble_enabled`` is False the rumble block is skipped entirely
    (no decoding, no logging) — e.g. for presets that disable rumble.
    """
    tick = 0
    cached = None
    latest_state: ControllerState = NEUTRAL
    last_rumble = None
    duration_start = perf_counter()

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

        # Decode rumble from the Switch packet and log changes only.
        if reply and rumble_enabled:
            rumble = parse_rumble(reply)
            if rumble is not None:
                sig = (
                    round(rumble.left.frequency_hz),
                    round(rumble.left.amplitude, 3),
                    round(rumble.right.frequency_hz),
                    round(rumble.right.amplitude, 3),
                )
                if sig != last_rumble:
                    last_rumble = sig
                    logger.info(
                        f"Rumble: L={rumble.left.frequency_hz:.0f}Hz@"
                        f"{rumble.left.amplitude:.2f} "
                        f"R={rumble.right.frequency_hz:.0f}Hz@"
                        f"{rumble.right.amplitude:.2f}"
                    )

        try:
            if report[3:] != cached:
                interrupt_channel.send_pdu(report)
                cached = report[3:]
            elif tick >= TICK_RATE_HZ:
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
        sleep_time = max(0.0, 1 / TICK_RATE_HZ - elapsed)
        await asyncio.sleep(sleep_time)


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

    def on_open():
        if psm == HID_CONTROL_PSM:
            logger.info("HID Control channel opened")
            state.ctrl_ready.set()
        else:
            logger.info("HID Interrupt channel opened")
            state.intr_ready.set()

    def on_close():
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
            channel.sink = lambda pdu: state.incoming.put_nowait(pdu)

        channel.on("open", on_open)
        channel.on("close", on_close)

        # The channel may already be OPEN by the time the handler runs.
        if channel.state == channel.State.OPEN:
            on_open()

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
        help="e.g. usb:0 (defaults to config.json)",
    )
    parser.add_argument(
        "bt_address",
        nargs="?",
        default=None,
        help="controller Bluetooth address (defaults to config.json)",
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

    # Load persistent config (under %APPDATA%), override with CLI flags.
    # CLI flags are session-only and do not write back; use the
    # ``/api/config`` endpoint to persist changes.
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

    config = Config.load(overrides or None)
    if not config.transport_spec:
        parser.error(
            "transport_spec is required (provide it as the second positional "
            "argument or set transport_spec in config.json)"
        )

    return config, args


async def main(
    config=None, args=None, *, ws_token=None, ready=None, shutdown_event=None
):
    if config is None:
        config, args = load_options()
    if config.nolog or args.nolog:
        logging.disable(logging.CRITICAL)
    else:
        setup_logging()
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

    firmware = missing_firmware(project_root)
    if firmware:
        message = f"Missing firmware: {project_root / firmware}. Firmware is not distributed with this application."
        logger.error(message)
        if not config.web_enabled:
            raise SystemExit(message)
        stop_event = shutdown_event or asyncio.Event()
        app = build_app(
            manager,
            config_store,
            project_root / "frontend" / "dist",
            missing_firmware=firmware,
            shutdown_event=stop_event,
            ws_token=ws_token,
        )
        try:
            await serve_web(
                app, config.web_host, config.web_port, stop_event, ready=ready
            )
        finally:
            manager.shutdown()
        return

    prepare_bluetooth(config, project_root)

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
            manager, config_store, frontend_dist, bluetooth=bluetooth,
            shutdown_event=stop_event, ws_token=ws_token
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
        transport = await open_transport(config.transport_spec)
        if app is not None:
            app.state.transport_pending = False
    except Exception as error:
        causes = [error]
        while causes[-1].__cause__ is not None:
            causes.append(causes[-1].__cause__)
        if app is None or not any(
            "LIBUSB_ERROR_NOT_SUPPORTED" in str(cause) for cause in causes
        ):
            raise
        logger.exception("Bluetooth USB transport is not supported")
        app.state.usb_driver_error = True
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
        device.public_address = Address(config.bt_address)
        if config.pairing_dir:
            pairing_dir = config.resolve_folder(config.pairing_dir)
            filename = str(device.public_address).lower().replace(":", "-") + ".json"
            device.keystore = JsonKeyStore(
                namespace=str(device.public_address),
                filename=str(pairing_dir / filename),
            )
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

        await device.power_on()
        # Enable authentication + encryption + secure connections policy.
        await device.send_command(
            HCI_Write_Default_Link_Policy_Settings_Command(
                default_link_policy_settings=0x0005
            )
        )

        bluetooth.attach(device, state, make_l2cap_handler)

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
                    if bluetooth.connection is not None:
                        await bluetooth.connection.disconnect()
                    continue

                interrupt_channel = state.intr_channel
                if interrupt_channel is None:
                    logger.warning("Interrupt channel missing; retrying.")
                    continue

                logger.info("Both HID channels open; starting controller session.")
                state.hid_opened = True
                protocol = ControllerProtocol(
                    ControllerTypes.PRO_CONTROLLER, config.bt_address
                )

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
                    active_preset = manager.current_preset or preset
                    await run_mainloop(
                        protocol,
                        interrupt_channel,
                        state.incoming,
                        state.session_stop,
                        command_queue,
                        rumble_enabled=active_preset.rumble_enabled,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Session ended with an error")
                else:
                    logger.info("Session ended cleanly")
                finally:
                    bluetooth.connected = False
                    if bluetooth.connection is not None:
                        await bluetooth.connection.disconnect()

                logger.info("Re-listening for a new Switch connection...")
        finally:
            manager.shutdown()
            if web_task is not None:
                web_task.cancel()
                try:
                    await web_task
                except asyncio.CancelledError:
                    pass


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


if __name__ == "__main__":
    from lib.desktop import run_application

    config, args = load_options()
    run_application(config, args, main)
