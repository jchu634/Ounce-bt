import argparse
import asyncio
import logging
import os
import queue
import shutil
import sys
import tempfile
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from time import perf_counter

import bumble.logging
import uvicorn
from bumble.device import Device
from bumble.hci import (
    HCI_StatusReturnParameters,
    HCI_Write_Default_Link_Policy_Settings_Command,
)
from bumble.keys import JsonKeyStore
from bumble.l2cap import ClassicChannelSpec
from bumble.pairing import PairingConfig, PairingDelegate
from starlette.applications import Starlette

from app.bluetooth import AdapterSession, configure_adapter_outputs
from app.input.controller_service import ControllerService
from app.input.macro_source import MacroPlayerThread
from app.input.manager import InputManager
from app.server import build_app
from lib.bluetooth_transport import WindowsUsbDevice, open_transport, prepare_hci_socket
from lib.colours import default_colours
from lib.config import (
    Config,
    ConfigStore,
    application_dir,
    config_path,
    resolve_config_file,
    state_dir,
)
from lib.controller import ControllerVariant
from lib.firmware import (
    CONFIG_NAME,
    FIRMWARE_NAME,
    missing_firmware,
    patch_address,
)
from lib.input import NEUTRAL, apply_to_protocol, parse_rumble
from lib.input import presets as presets_module
from lib.input.macros import load_macro, seed_default_macros
from lib.input.presets import (
    PresetConfig,
    PresetSelection,
    load_preset,
    resolve_controller_preset,
)
from lib.input.state import ControllerState
from lib.sdp_records import DEVICE_CLASS_GAMEPAD, sdp_record
from lib.switch_protocol import ControllerProtocol
from lib.windows_adapters import discover_winusb_adapters

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


async def run_pairing_handshake(
    protocol, interrupt_channel, incoming, pairing_grip=None, *, single_joycon=False,
):
    """Exchange subcommands with the Switch until the handshake completes.

    A solo Joy-Con can send SL + SR only after reports are enabled,
    and the Switch may wait for that chord before assigning player lights.
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
        if pairing_grip is not None:
            grip = pairing_grip(protocol, NEUTRAL)
            if grip != NEUTRAL:
                apply_to_protocol(protocol, grip)
        report = protocol.get_report()
        if report:
            logger.debug(f"Controller -> {report.hex()}")
            interrupt_channel.send_pdu(report)

        ready = (
            protocol.device_info_queried and protocol.mode == "standard"
            if single_joycon else bool(protocol.player_number)
        )
        if (
            reply
            and len(reply) > 45
            and protocol.vibration_configured
            and ready
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
    player_changed: Callable[[int | None], None] | None = None,
    mix_manual_input: Callable[[ControllerState], ControllerState] | None = None,
    tick_rate_hz: int = TICK_RATE_HZ,
    output_input: Callable[[ControllerState], ControllerState] | None = None,
    pairing_grip: Callable[[ControllerProtocol, ControllerState], ControllerState] | None = None,
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

            previous_player = protocol.player_number if player_changed else None
            protocol.process_commands(reply)
            if player_changed and protocol.player_number != previous_player:
                player_changed(protocol.player_number)

            # Apply the latest input state (buttons + sticks) to the report.
            state = mix_manual_input(latest_state) if mix_manual_input else latest_state
            if output_input is not None:
                state = output_input(state)
            if pairing_grip is not None:
                state = pairing_grip(protocol, state)
            apply_to_protocol(protocol, state)

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
    app,
    host: str,
    port: int,
    stop_event: asyncio.Event | None = None,
    on_started: Callable[[], None] | None = None,
) -> None:
    """Ask Uvicorn to finish in-flight requests before closing the server."""
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

    async def report_ready(callback: Callable[[], None]):
        while not server.started:
            await asyncio.sleep(0.01)
        callback()

    ready_task = (
        asyncio.create_task(report_ready(on_started)) if on_started is not None else None
    )
    stop_task = asyncio.create_task(stop_when_requested()) if stop_event else None
    server_task = asyncio.create_task(server.serve())
    try:
        await asyncio.shield(server_task)
    except asyncio.CancelledError:
        server.should_exit = True
        await server_task
        raise
    finally:
        watchers = [task for task in (ready_task, stop_task) if task is not None]
        for task in watchers:
            task.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)


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
    parser.add_argument(
        "--adapter",
        action="append",
        default=[],
        metavar="TRANSPORT",
        help="Use an additional adapter instead of auto-detection (repeat up to seven times)",
    )
    parser.add_argument(
        "--no-auto-adapters",
        action="store_true",
        help="Use only the configured transport and any explicit --adapter options",
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

    specs = [config.transport_spec, *args.adapter]
    if len(specs) > 8 or len({spec.casefold() for spec in specs}) != len(specs):
        parser.error("Specify up to eight distinct adapter transports")
    if args.adapter and not config.web_enabled:
        parser.error("Additional adapters require the Connections UI")
    args.auto_adapters = (
        sys.platform == "win32"
        and not args.no_auto_adapters
        and args.transport_spec is None
        and config.transport_spec == "usb:0"
        and not args.adapter
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

    command_queue: queue.Queue[ControllerState] = queue.Queue()
    manager = InputManager(
        command_queue,
        config.resolve_folder(config.macros_dir),
        macro_rate_hz=config.macro_rate_hz,
    )
    manager.bind_loop(asyncio.get_running_loop())
    presets_module.PRESETS_DIR = config.resolve_folder(config.presets_dir)

    if not config.web_enabled:
        try:
            await run_bluetooth(config_store, args, manager)
        finally:
            manager.shutdown()
        return

    stop_event = shutdown_event or asyncio.Event()
    try:
        seed_default_macros(manager.macros_dir)
    except OSError:
        logger.exception("Could not install the default macro")
    app = build_app(
        manager,
        config_store,
        application_dir() / "frontend" / "dist",
        shutdown_event=stop_event,
        ws_token=ws_token,
        restart_callback=restart_callback,
    )
    app.state.startup_phase = "preparing_bluetooth"
    web_started = asyncio.Event()

    def on_started():
        if ready is not None:
            ready.set()
        web_started.set()

    async def start_bluetooth():
        await web_started.wait()
        if stop_event.is_set():
            return
        try:
            await run_bluetooth(config_store, args, manager, app)
        except Exception as error:
            logger.exception("Bluetooth startup failed")
            app.state.bluetooth_error = f"Could not initialize Bluetooth: {error}"
            app.state.startup_phase = None

    bluetooth_task = asyncio.create_task(start_bluetooth())
    try:
        await serve_web(
            app, config.web_host, config.web_port, stop_event, on_started=on_started
        )
    finally:
        bluetooth_task.cancel()
        await asyncio.gather(bluetooth_task, return_exceptions=True)
        manager.shutdown()


async def run_bluetooth(
    config_store: ConfigStore,
    args: argparse.Namespace,
    manager: InputManager,
    app: Starlette | None = None,
) -> None:
    config = config_store.config
    command_queue = manager.command_queue
    transports = [config.transport_spec, *getattr(args, "adapter", ())]
    discovery_error = None
    if getattr(args, "auto_adapters", False):
        if app is not None:
            app.state.startup_phase = "discovering_adapters"
        try:
            detected = await asyncio.to_thread(discover_winusb_adapters)
        except Exception as error:
            logger.exception("WinUSB adapter discovery failed")
            discovery_error = f"Could not detect WinUSB Bluetooth adapters: {error}"
        else:
            if detected:
                transports = detected[:8] if config.web_enabled else detected[:1]
                logger.info("Detected WinUSB Bluetooth adapters: %s", ", ".join(transports))
            else:
                discovery_error = (
                    "No USB Bluetooth adapter using WinUSB was detected. "
                    "Connect a dedicated Bluetooth adapter configured with the WinUSB driver."
                )

    firmware_root = config.bluetooth_firmware_dir
    # Linux uses the adapter's existing firmware and public address. Legacy
    # realtek_firmware config keys are ignored by Config.load.
    patch_firmware = sys.platform == "win32"
    if app is not None and patch_firmware:
        app.state.startup_phase = "checking_firmware"
    firmware = (
        await asyncio.to_thread(missing_firmware, firmware_root) if patch_firmware else None
    )
    if app is not None and app.state.shutdown_event.is_set():
        return
    if firmware:
        message = f"Missing required Bluetooth file: {firmware_root / firmware}. Bluetooth files are not distributed with this application."
        logger.error(message)
        if app is None:
            raise SystemExit(message)
        app.state.missing_firmware = str(firmware_root / firmware)
        app.state.startup_phase = None
        return

    if discovery_error:
        if app is None:
            raise RuntimeError(discovery_error)
        app.state.bluetooth_error = discovery_error
        app.state.startup_phase = None
        return

    explicit_address = getattr(args, "bt_address", None)
    profiles = config_store.ensure_adapter_profiles(transports, persist=not explicit_address)
    primary_preset_name = args.preset or profiles[0].preset or config.preset

    # Load the configured preset as the initial fallback. Once pygame selects
    # a controller, its saved GUID mapping or detected controller type replaces
    # this value. An explicit --preset keeps its session-wide override behavior.
    try:
        preset = load_preset(primary_preset_name)
    except (FileNotFoundError, ValueError, TypeError) as e:
        logger.warning(f"Could not load preset {primary_preset_name!r}: {e}; using defaults")
        preset = PresetConfig.default()
    manager.set_preset(preset, primary_preset_name)
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
        initial_ident = profiles[0].controller_guid or controller_index
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

        profile_indices = {
            "primary" if index == 0 else f"adapter-{index + 1}": index
            for index in range(len(profiles))
        }

        def save_assignment(session_id: str, guid: str) -> None:
            config_store.update_adapter_profile(profile_indices[session_id], controller_guid=guid)

        controller_service = ControllerService(
            command_queue,
            preset=preset,
            initial_ident=initial_ident,
            on_change=manager.on_controllers_changed,
            preset_resolver=preset_resolver,
            on_preset_changed=manager.on_controller_preset_changed,
            saved_assignments={
                session_id: profiles[index].controller_guid
                for session_id, index in profile_indices.items()
            } if app is not None else None,
            on_assignment=save_assignment,
            primary_preset_override=bool(profiles[0].preset),
        )
        manager.set_controller_service(controller_service)

    input_threads = build_input_sources(config.input_specs, command_queue)
    if controller_service is not None:
        input_threads.append(controller_service)
    manager.attach_pygame_threads(input_threads)

    manager.adapter_id = "primary"
    primary = AdapterSession(
        "primary",
        transports[0],
        command_queue,
        controller_service,
        expected_address=(explicit_address or profiles[0].address) if patch_firmware else None,
        input_manager=manager,
        profile_index=0,
        legacy_keystore=profiles[0].legacy_keystore,
    )
    sessions = {primary.id: primary}
    for index, spec in enumerate(transports[1:], 2):
        session_id = f"adapter-{index}"
        route = controller_service.add_route(session_id, config.preset) if controller_service else None
        profile = profiles[index - 1]
        if route and (saved_preset := profile.preset):
            try:
                route.preset = load_preset(saved_preset)
            except (FileNotFoundError, ValueError, TypeError):
                logger.warning("Could not load preset %r for %s", saved_preset, spec)
            else:
                route.preset_name = saved_preset
                route.preset_override = PresetSelection(saved_preset, route.preset)
        input_queue = route.input_queue if route else queue.Queue()
        adapter_input = InputManager(
            input_queue, manager.macros_dir, config.macro_rate_hz, adapter_id=session_id,
            pause_capture=route.pause if route else None,
            resume_capture=route.resume if route else None,
        )
        adapter_input.bind_loop(asyncio.get_running_loop())
        sessions[session_id] = AdapterSession(
            session_id, spec, input_queue, route,
            expected_address=profile.address if patch_firmware else None,
            input_manager=adapter_input,
            profile_index=index - 1,
            legacy_keystore=profile.legacy_keystore,
        )

    configure_adapter_outputs(sessions, profiles)
    for session in sessions.values():
        session.input_manager.map_manual_input = session.map_manual_input
        if session.controller is not None:
            session.controller.mapping_variant = session.mapping_variant

    if app is not None:
        app.state.bluetooth = primary.bluetooth
        app.state.adapter_sessions = sessions
        app.state.startup_phase = "starting_adapters"

    power_lock = asyncio.Lock()
    addresses = set()

    def adapter_ready(session):
        if app is not None:
            app.state.startup_phase = None
        if session.primary:
            for thread in input_threads:
                if thread is not controller_service:
                    thread.start()

    async def supervise(session, firmware_dir):
        def vibration_allowed():
            controller = session.controller
            selected = (
                (manager.current_preset or preset)
                if session.primary
                else (controller.preset if controller else preset)
            )
            return (
                config_store.config.allows_controller_vibration(
                    controller.active_guid if controller else None
                )
                and selected.rumble_enabled
            )

        try:
            if patch_firmware:
                stage_adapter_firmware(session, firmware_root, firmware_dir)
            await run_adapter(
                session,
                config_store,
                power_lock,
                addresses,
                lambda: adapter_ready(session),
                vibration_allowed,
            )
        except Exception as error:
            if app is None:
                raise
            logger.exception("Adapter %s stopped", session.transport)
            session.error = bluetooth_startup_error(session.transport, error)
            if len(sessions) == 1:
                causes = [error]
                while causes[-1].__cause__ is not None:
                    causes.append(causes[-1].__cause__)
                if patch_firmware and any(
                    "LIBUSB_ERROR_NOT_SUPPORTED" in str(cause) for cause in causes
                ):
                    app.state.usb_driver_error = True
                else:
                    app.state.bluetooth_error = session.error
            if all(item.error for item in sessions.values()):
                app.state.startup_phase = None

    tasks = []
    firmware_workspace = (
        tempfile.TemporaryDirectory(prefix="ounce-bt-firmware-")
        if patch_firmware
        else nullcontext()
    )
    with firmware_workspace as tmp:
        try:
            if controller_service is not None:
                controller_service.start()
            tasks = [
                asyncio.create_task(supervise(session, Path(tmp) if tmp else None))
                for session in sessions.values()
            ]
            if app is not None:
                # Keep controller input available until the web server stops.
                await asyncio.Future()
            else:
                await tasks[0]
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for session in sessions.values():
                if not session.primary and session.input_manager:
                    session.input_manager.shutdown()
            if controller_service is not None and controller_service.ident is not None:
                controller_service.stop()
                await asyncio.to_thread(controller_service.join, 3)


def stage_adapter_firmware(
    session: AdapterSession,
    source: Path,
    workspace: Path,
) -> None:
    assert session.expected_address is not None
    session.firmware_dir = workspace / session.id
    session.firmware_dir.mkdir()
    shutil.copyfile(source / FIRMWARE_NAME, session.firmware_dir / FIRMWARE_NAME)
    patch_address(
        source / CONFIG_NAME,
        session.firmware_dir / CONFIG_NAME,
        session.expected_address,
    )


class HciStartupError(RuntimeError):
    """The adapter failed to complete HCI initialization."""


class IncompleteHciResponse(HciStartupError):
    """The radio responded to a capability query with a status byte only."""


async def run_adapter(
    session, config_store, power_lock, addresses, on_ready, vibration_allowed
):
    for attempt in range(3):
        try:
            await run_adapter_once(
                session, config_store, power_lock, addresses, on_ready, vibration_allowed
            )
            return
        except HciStartupError as error:
            if attempt == 2:
                raise
            logger.warning("Reopening %s after HCI startup failure: %s", session.transport, error)
            await asyncio.sleep(0.25)


async def power_on_adapter(device):
    try:
        async with asyncio.timeout(20):
            await device.power_on()
    except TimeoutError as error:
        raise HciStartupError(
            "The adapter timed out during Bluetooth initialization. "
            "Unplug and reconnect the adapter, then try again."
        ) from error
    except AttributeError as error:
        if error.name != "supported_commands" or not isinstance(
            error.obj, HCI_StatusReturnParameters
        ):
            raise
        raise IncompleteHciResponse(
            "The adapter did not return its supported Bluetooth commands. "
            "Unplug and reconnect it, then retry."
        ) from error


async def run_adapter_once(
    session, config_store, power_lock, addresses, on_ready, vibration_allowed
):
    config = config_store.config
    bluetooth = session.bluetooth
    if session.transport.startswith("hci-socket:"):
        prepare_hci_socket()
    transport = await open_transport(session.transport)
    async with transport as hci_transport:
        device_class = WindowsUsbDevice if sys.platform == "win32" and session.transport.startswith("usb:") else Device
        device = device_class.from_config_file_with_hci(
            str(resolve_config_file(config.device_config)),
            hci_transport.source,
            hci_transport.sink,
        )

        # Classic / HID service configuration
        pro_name = device.name
        variant = bluetooth.controller_type
        if variant != ControllerVariant.PRO:
            device.name = variant.bluetooth_name
            device.inquiry_response = None
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
        device.sdp_service_records = sdp_record(variant)

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

        async with power_lock:
            if session.firmware_dir is None:
                await power_on_adapter(device)
            else:
                # Bumble reads this process-wide setting during power_on().
                # Serialize initialization and restore it before unlocking.
                key = "BUMBLE_RTK_FIRMWARE_DIR"
                previous = os.environ.get(key)
                os.environ[key] = str(session.firmware_dir)
                try:
                    await power_on_adapter(device)
                finally:
                    if previous is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = previous

        address = device.public_address.to_string(with_type_qualifier=False).upper()
        if session.expected_address and address != session.expected_address.upper():
            raise RuntimeError(
                "The adapter address does not match the patched firmware. "
                "Unplug/replug the adapter before retrying."
            )
        if address in addresses:
            raise RuntimeError(
                f"Another adapter already uses Bluetooth address {address}"
            )
        addresses.add(address)
        session.local_address = address
        try:
            await run_powered_adapter(
                session,
                config_store,
                device,
                state,
                on_ready,
                vibration_allowed,
                getattr(hci_transport.source, "wait_for_termination", None),
                pro_name=pro_name,
            )
        finally:
            addresses.discard(address)
            bluetooth.device = None
            bluetooth.connected = False
            bluetooth.connection = None


async def run_powered_adapter(
    session, config_store, device, state, on_ready, vibration_allowed, wait_transport,
    pro_name=None,
):
    config = config_store.config
    bluetooth = session.bluetooth
    command_queue = session.input_queue
    controller_service = session.controller
    if config.pairing_dir or (
        not session.legacy_keystore and (session.expected_address is not None or not session.primary)
    ):
        pairing_dir = (
            config.resolve_folder(config.pairing_dir)
            if config.pairing_dir
            else state_dir() / "pairing"
        )
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

    bluetooth.attach(device, state, make_l2cap_handler, pro_name=pro_name)
    on_ready()
    logger.info("Adapter %s ready at %s", session.transport, session.local_address)

    async def watch_transport():
        try:
            await wait_transport()
        finally:
            state.session_stop.set()

    transport_task = asyncio.create_task(watch_transport()) if wait_transport else None
    try:
        # Reconnect loop: each iteration is one full controller session.
        while True:
            if transport_task is not None and transport_task.done():
                await transport_task
                raise ConnectionError("Adapter disconnected")
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
            variant = bluetooth.controller_type
            protocol = ControllerProtocol(variant.bluetooth_type, str(device.public_address))
            colours = (
                config.adapter_profiles[session.profile_index].colours_for(variant)
                if session.profile_index is not None
                else config.colours_for_adapter(session.transport, primary=session.primary)
                if variant == ControllerVariant.PRO else default_colours(variant)
            )
            protocol.set_colours(**colours)
            owner = session.input_owner
            single_joycon = session.mapping_variant().is_single_joycon
            session.reset_grip(pairing=bluetooth.pairing)

            try:
                if not await run_until_disconnected(
                    asyncio.wait_for(
                        run_pairing_handshake(
                            protocol, interrupt_channel, state.incoming, session.apply_pairing_grip,
                            single_joycon=single_joycon,
                        ),
                        timeout=30,
                    ),
                    state,
                ):
                    continue
                bluetooth.player_number = protocol.player_number
                bluetooth.connected = True
                if single_joycon and bluetooth.pairing:
                    bluetooth.grip_reminder_id += 1
                if config.web_enabled:
                    await bluetooth.set_pairing(False)
                await run_mainloop(
                    protocol,
                    interrupt_channel,
                    state.incoming,
                    state.session_stop,
                    command_queue,
                    controller_service=controller_service if owner is session else None,
                    tick_rate_hz=config.tick_rate_hz,
                    vibration_allowed=vibration_allowed,
                    player_changed=lambda number: setattr(
                        bluetooth, "player_number", number
                    ),
                    mix_manual_input=session.input_manager.mix_manual_input
                    if session.input_manager else None,
                    output_input=session.output_input,
                    pairing_grip=session.apply_pairing_grip,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Session ended with an error")
            else:
                logger.info("Session ended cleanly")
            finally:
                session.combined_input = NEUTRAL
                session.reset_grip()
                bluetooth.connected = False
                await cleanup_session(bluetooth)

            logger.info("Re-listening for a new Switch connection...")
    finally:
        if transport_task is not None:
            transport_task.cancel()
            await asyncio.gather(transport_task, return_exceptions=True)


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


def bluetooth_startup_error(transport: str, error: Exception) -> str:
    reason = str(error).strip() or type(error).__name__
    message = f"Could not start Bluetooth transport {transport}: {reason.rstrip('.')}."
    if sys.platform == "linux":
        if transport.startswith("hci-socket:"):
            message += (
                " The adapter must be powered off in BlueZ, unblocked by rfkill, "
                "and available exclusively to Bumble. HCI user channels require "
                "CAP_NET_RAW and CAP_NET_ADMIN. See the Linux setup instructions."
            )
        elif transport.startswith("usb:"):
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
