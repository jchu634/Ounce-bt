import asyncio
import queue
from unittest.mock import Mock

import pytest

from app.input.pygame_source import PygameInputThread
from app.main import run_mainloop
from lib.controller import ControllerTypes
from lib.input.rumble import parse_rumble
from lib.switch_protocol import ControllerProtocol

NEUTRAL = bytes.fromhex("00 01 40 40")


def packet(left=NEUTRAL, right=NEUTRAL, report_id=0x10):
    result = bytes([0xA2, report_id, 0x07]) + left + right
    return result + b"\x30\x01" if report_id == 1 else result


@pytest.mark.parametrize("report_id", [1, 0x10, 0x11])
def test_frames_decode_identically_with_or_without_padding(report_id):
    raw = packet(bytes.fromhex("00 03 c0 40"), report_id=report_id)
    decoded = parse_rumble(raw)
    assert decoded == parse_rumble(raw.ljust(50, b"\x00"))
    assert decoded.left.high_frequency_hz == pytest.approx(320)
    assert decoded.left.low_frequency_hz == pytest.approx(160)
    assert decoded.left.high_amplitude == pytest.approx(0.007843)
    assert decoded.left.low_amplitude == pytest.approx(0.007843)
    assert not decoded.right.active


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        packet()[:10],
        b"\xa1" + packet()[1:],
        packet(report_id=0x12),
        packet(report_id=1)[:11],
    ],
)
def test_invalid_reports_are_ignored(raw):
    assert parse_rumble(raw) is None


def test_independent_bands_mix_by_max_and_clamp():
    rumble = parse_rumble(
        packet(bytes.fromhex("00 01 40 60"), bytes.fromhex("00 ff 40 40"))
    )
    assert rumble.left.low_amplitude == pytest.approx(0.459817)
    assert rumble.left.high_amplitude == 0
    assert rumble.right.low_amplitude == 0
    assert rumble.strengths() == pytest.approx((0.459817, 1.0))
    assert parse_rumble(packet()).strengths() == (0, 0)
    assert not parse_rumble(packet(b"\x00" * 4, b"\x00" * 4)).active


def test_console_enable_disable_and_padded_rumble_are_distinct():
    protocol = ControllerProtocol(ControllerTypes.PRO_CONTROLLER, "98:B6:E9:7E:E9:8D")
    for value in (1, 0):
        raw = packet(report_id=1)[:11] + bytes([0x48, value])
        protocol.process_commands(raw.ljust(50, b"\x00"))
        assert protocol.vibration_enabled is bool(value)
        assert protocol.vibration_configured
    # The first trailing byte in a rumble report is not a subcommand.
    raw = packet() + bytes.fromhex("48 01")
    protocol.process_commands(raw.ljust(50, b"\x00"))
    assert not protocol.vibration_enabled


def test_playback_refresh_neutral_restart_and_timeout(monkeypatch):
    now = [10.0]
    monkeypatch.setattr("app.input.pygame_source.time.monotonic", lambda: now[0])
    capture = PygameInputThread(queue.Queue())
    stick = Mock()
    stick.rumble.return_value = True
    rumble = parse_rumble(packet(bytes.fromhex("00 81 40 40")))
    capture.set_rumble(rumble)
    capture._update_rumble(stick)
    stick.rumble.assert_called_once_with(0.0, 0.459817, 100)
    capture._update_rumble(stick)
    assert stick.rumble.call_count == 1
    now[0] += 0.06
    capture.set_rumble(rumble)
    capture._update_rumble(stick)
    assert stick.rumble.call_count == 2
    capture.set_rumble(None)
    capture._update_rumble(stick)
    stick.stop_rumble.assert_called_once()
    capture.set_rumble(rumble)
    capture._update_rumble(stick)
    assert stick.rumble.call_count == 3
    now[0] += 0.26
    capture._update_rumble(stick)
    assert stick.stop_rumble.call_count == 2


def test_unsupported_controller_is_not_retried():
    capture = PygameInputThread(queue.Queue())
    stick = Mock()
    stick.rumble.return_value = False
    capture.set_rumble(parse_rumble(packet(bytes.fromhex("00 81 40 40"))))
    capture._update_rumble(stick)
    capture._update_rumble(stick)
    assert stick.rumble.call_count == 1


def test_mainloop_live_setting_and_cleanup(monkeypatch):
    async def exercise():
        protocol = ControllerProtocol(
            ControllerTypes.PRO_CONTROLLER, "98:B6:E9:7E:E9:8D"
        )
        protocol.vibration_enabled = True
        incoming = asyncio.Queue()
        incoming.put_nowait(packet(bytes.fromhex("00 81 40 40")))
        stop = asyncio.Event()
        channel = Mock()
        channel.state = channel.State.OPEN
        service = Mock()
        enabled = [True]
        ticks = [0]

        async def advance(_delay):
            ticks[0] += 1
            if ticks[0] == 1:
                enabled[0] = False
            else:
                stop.set()

        monkeypatch.setattr("app.main.asyncio.sleep", advance)
        await run_mainloop(
            protocol,
            channel,
            incoming,
            stop,
            queue.Queue(),
            controller_service=service,
            vibration_allowed=lambda: enabled[0],
        )
        effects = [call.args[0] for call in service.set_rumble.call_args_list]
        assert effects[0].active
        assert effects[1:] == [None, None]

    asyncio.run(exercise())


def test_mainloop_cancellation_stops_rumble():
    async def exercise():
        protocol = ControllerProtocol(
            ControllerTypes.PRO_CONTROLLER, "98:B6:E9:7E:E9:8D"
        )
        service = Mock()
        channel = Mock()
        channel.state = channel.State.OPEN
        task = asyncio.create_task(
            run_mainloop(
                protocol,
                channel,
                asyncio.Queue(),
                asyncio.Event(),
                queue.Queue(),
                controller_service=service,
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.set_rumble.call_args.args == (None,)

    asyncio.run(exercise())


def test_joystick_cleanup_stops_effect_before_close(monkeypatch):
    capture = PygameInputThread(queue.Queue(), pump=False)
    stick = Mock()
    monkeypatch.setattr("app.input.pygame_source.joystick.get_count", lambda: 1)
    monkeypatch.setattr("app.input.pygame_source.joystick.Joystick", lambda _: stick)

    def loop(device):
        capture.set_rumble(parse_rumble(packet(bytes.fromhex("00 81 40 40"))))
        capture._update_rumble(device)
        raise RuntimeError("disconnected")

    monkeypatch.setattr(capture, "_loop", loop)
    capture.run()
    names = [call[0] for call in stick.method_calls]
    assert names[-2:] == ["stop_rumble", "quit"]


def test_rumble_service_routes_only_to_selected_capture():
    from app.input.controller_service import ControllerService

    service = ControllerService(queue.Queue())
    effect = parse_rumble(packet())
    service.set_rumble(effect)  # No selected device is a valid state.
    first = Mock()
    second = Mock()
    service._capture = first
    service.set_rumble(effect)
    first.set_rumble.assert_called_once_with(effect)
    service._capture = second
    service.set_rumble(None)
    second.set_rumble.assert_called_once_with(None)
    assert first.set_rumble.call_count == 1
