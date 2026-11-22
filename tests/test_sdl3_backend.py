from __future__ import annotations

import math
import runpy
import struct
from pathlib import Path

import pytest

from app.input.controller_service import map_gamepad_state
from lib import sdl3 as sdl3_loader
from lib.controller import ControllerTypes, ControllerVariant
from lib.input.imu import (
    ACCEL_SCALE,
    GYRO_SCALE,
    ImuBuffer,
    encode_imu_sample,
    pack_imu_frames,
)
from lib.input.presets import PresetConfig, load_preset
from lib.input.sdl3_backend import STANDARD_GRAVITY, ImuSample, Sdl3Host
from lib.input.state import NEUTRAL, Button, ControllerState


@pytest.mark.parametrize(
    ("buttons", "triggers", "left", "right", "expected"),
    [
        (frozenset(), {}, (0.03, -0.03), (-0.02, 0.03), NEUTRAL),
        (frozenset(), {"left_trigger": 0.9}, (0.0, 0.0), (0.0, 0.0), ControllerState(Button.ZL)),
        (frozenset(), {"right_trigger": 0.9}, (0.0, 0.0), (0.0, 0.0), ControllerState(Button.ZR)),
        (frozenset(), {}, (0.0, 0.0), (1.0, 0.0), ControllerState(right=(1.0, 0.0))),
        (frozenset(), {}, (0.0, 0.0), (0.0, 1.0), ControllerState(right=(0.0, 1.0))),
        (frozenset(), {}, (0.0, 1.0), (0.0, 0.0), ControllerState(left=(0.0, 1.0))),
        (frozenset({"dpad_up"}), {}, (0.0, 0.0), (0.0, 0.0), ControllerState(Button.UP)),
        (frozenset({"guide"}), {}, (0.0, 0.0), (0.0, 0.0), ControllerState(Button.HOME)),
        (frozenset({"left_stick"}), {}, (0.0, 0.0), (0.0, 0.0), ControllerState(Button.STICK_L)),
        (frozenset({"right_stick"}), {}, (0.0, 0.0), (0.0, 0.0), ControllerState(Button.STICK_R)),
        (frozenset({"south", "east"}), {}, (0.0, 0.0), (0.0, 0.0), ControllerState(Button.B | Button.A)),
    ],
)
@pytest.mark.parametrize("preset_name", ["xbox", "playstation", "switch"])
def test_builtin_presets_map_canonical_sdl3_inputs(
    preset_name, buttons, triggers, left, right, expected
):
    preset = load_preset(preset_name)
    state = map_gamepad_state(buttons, triggers, left, right, preset)
    assert state == expected


def test_mapping_switches_across_controller_variants():
    preset = load_preset("xbox")
    pressed = frozenset({"south", "left_shoulder", "dpad_up"})
    pro = map_gamepad_state(
        pressed, {}, (1.0, 0.0), (0.0, 0.0), preset.mapping_for(ControllerVariant.PRO)
    )
    jc_l = map_gamepad_state(
        pressed, {}, (1.0, 0.0), (0.0, 0.0), preset.mapping_for(ControllerVariant.LEFT)
    )
    jc_r = map_gamepad_state(
        pressed, {}, (1.0, 0.0), (0.0, 0.0), preset.mapping_for(ControllerVariant.RIGHT)
    )
    combined = map_gamepad_state(
        pressed, {}, (1.0, 0.0), (0.0, 0.0), preset.mapping_for(ControllerVariant.COMBINED)
    )

    assert pro == ControllerState(Button.B | Button.L | Button.UP, left=(1.0, 0.0))
    assert jc_l == ControllerState(Button.LEFT | Button.SL, left=(1.0, 0.0))
    assert jc_r == ControllerState(Button.A | Button.SL, right=(1.0, 0.0))
    assert combined == pro
    assert PresetConfig.default().motion_enabled is True


def test_imu_encoding_orientations_and_scaling():
    # Resting controller: +1g on SDL +Y, 90 deg/s yaw around SDL +Y.
    yaw = math.pi / 2
    sample = ImuSample(accel=(0.0, STANDARD_GRAVITY, 0.0), gyro=(0.0, yaw, 0.0))

    pro = struct.unpack("<6h", encode_imu_sample(sample, ControllerTypes.PRO_CONTROLLER))
    assert pro[:3] == (0, 0, 4096)
    assert pro[3:5] == (0, 0)
    assert pro[5] == round(yaw * GYRO_SCALE)

    jc_r_upright = struct.unpack("<6h", encode_imu_sample(sample, ControllerTypes.JOYCON_R))
    assert jc_r_upright[:3] == (0, 0, -4096)
    assert jc_r_upright[5] == -round(yaw * GYRO_SCALE)

    # Horizontal solo Joy-Con L: +X = -sdl_x, +Y = +sdl_z, +Z = +sdl_y.
    tilt = ImuSample(accel=(STANDARD_GRAVITY, 0.0, 0.0), gyro=(0.0, 0.0, 1.0))
    jc_l_horiz = struct.unpack(
        "<6h", encode_imu_sample(tilt, ControllerTypes.JOYCON_L, horizontal=True)
    )
    assert jc_l_horiz[:3] == (-4096, 0, 0)
    assert jc_l_horiz[3:] == (0, round(1.0 * GYRO_SCALE), 0)

    # Clamping prevents int16 overflow on extreme spikes.
    huge = ImuSample(accel=(1000.0, -1000.0, 0.0), gyro=(1000.0, -1000.0, 0.0))
    clamped = struct.unpack("<6h", encode_imu_sample(huge, ControllerTypes.PRO_CONTROLLER))
    assert all(-32768 <= v <= 32767 for v in clamped)
    assert ACCEL_SCALE > 0


def test_pack_imu_frames_handles_zero_to_many_samples():
    s1 = ImuSample((0.0, STANDARD_GRAVITY, 0.0), (1.0, 0.0, 0.0), 1)
    s2 = ImuSample((0.0, STANDARD_GRAVITY, 0.0), (2.0, 0.0, 0.0), 2)
    s3 = ImuSample((0.0, STANDARD_GRAVITY, 0.0), (3.0, 0.0, 0.0), 3)
    s4 = ImuSample((0.0, STANDARD_GRAVITY, 0.0), (4.0, 0.0, 0.0), 4)

    assert len(pack_imu_frames([], ControllerTypes.PRO_CONTROLLER)) == 36
    assert len(pack_imu_frames([s1], ControllerTypes.PRO_CONTROLLER)) == 36
    assert len(pack_imu_frames([s1, s2], ControllerTypes.PRO_CONTROLLER)) == 36
    packed = pack_imu_frames([s1, s2, s3, s4], ControllerTypes.PRO_CONTROLLER)
    assert len(packed) == 36
    # Picks oldest, middle, newest (s1, s2, s4).
    frames = [struct.unpack("<6h", packed[i : i + 12]) for i in range(0, 36, 12)]
    assert frames[0][4] == -round(1.0 * GYRO_SCALE)
    assert frames[2][4] == -round(4.0 * GYRO_SCALE)


def test_imu_buffer_supports_independent_consumers():
    buf = ImuBuffer()
    s1 = ImuSample((0.0, STANDARD_GRAVITY, 0.0), (0.1, 0.0, 0.0), 1)
    s2 = ImuSample((0.0, STANDARD_GRAVITY, 0.0), (0.2, 0.0, 0.0), 2)
    buf.push([s1, s2])

    left_cursor, left_samples = buf.read_since(0)
    right_cursor, right_samples = buf.read_since(0)
    assert left_samples == [s1, s2]
    assert right_samples == [s1, s2]
    assert buf.read_since(left_cursor) == (left_cursor, [])
    assert buf.read_since(right_cursor) == (right_cursor, [])


def test_sdl3_host_initializes_and_quits_cleanly():
    host = Sdl3Host()
    assert host.init()
    try:
        devices = host.list_devices()
        assert isinstance(devices, list)
    finally:
        host.quit()


def test_sdl3_host_distinguishes_switch2_pro_from_switch_pro():
    class _FakeSdl:
        def SDL_GetJoystickVendorForID(self, jid: int) -> int:
            return 0x057E

        def SDL_GetJoystickProductForID(self, jid: int) -> int:
            return 0x2069 if jid == 1 else 0x2009

        def SDL_GetGamepadNameForID(self, jid: int) -> bytes:
            return b"Nintendo Switch Pro Controller"

        def SDL_GetJoystickNameForID(self, jid: int) -> bytes:
            return b"Nintendo Switch Pro Controller"

    host = Sdl3Host(sdl=_FakeSdl())
    assert host._device_name(1) == "Nintendo Switch 2 Pro Controller"
    assert host._device_name(2) == "Nintendo Switch Pro Controller"


def test_build_sdl3_verify_requires_libusb_and_switch2_markers(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "build-sdl3.py"
    verify = runpy.run_path(str(script))["verify_sdl3_binary"]

    missing = tmp_path / "missing.dll"
    with pytest.raises(RuntimeError, match="Missing SDL3 binary"):
        verify(missing)

    no_libusb = tmp_path / "no-libusb.dll"
    no_libusb.write_bytes(b"SDL3 binary without switch2 or libusb")
    with pytest.raises(RuntimeError, match="HIDAPI_SWITCH2"):
        verify(no_libusb)

    no_switch2 = tmp_path / "only-libusb.dll"
    no_switch2.write_bytes(b"SDL3 binary with libusb-1.0 only")
    with pytest.raises(RuntimeError, match="HIDAPI_SWITCH2"):
        verify(no_switch2)

    valid = tmp_path / "valid.dll"
    valid.write_bytes(b"SDL3 binary with HIDAPI_SWITCH2 and libusb-1.0")
    verify(valid)


def test_sdl3_loader_prefers_bundled_binary_and_fails_packaged_when_missing(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("SDL_BINARY_PATH", raising=False)
    monkeypatch.delenv("SDL_DISABLE_METADATA", raising=False)
    monkeypatch.delenv("SDL_DOWNLOAD_BINARIES", raising=False)
    monkeypatch.delenv("SDL_FIND_BINARIES", raising=False)
    monkeypatch.setattr(sdl3_loader, "application_dir", lambda: tmp_path)

    # Packaged build must refuse to fall back to non-libusb runtime downloads.
    monkeypatch.setattr(sdl3_loader, "_is_packaged", lambda: True)
    with pytest.raises(RuntimeError, match="Bundled libusb-enabled SDL3 binary is missing"):
        sdl3_loader.configure_sdl3_environment()

    # Once sdl3/bin is present, configure_sdl3_environment pins SDL_BINARY_PATH to it.
    bundled = tmp_path / "sdl3" / "bin"
    bundled.mkdir(parents=True)
    (bundled / "SDL3.dll").write_bytes(b"stub")
    sdl3_loader.configure_sdl3_environment()
    assert sdl3_loader.os.environ["SDL_BINARY_PATH"] == str(bundled)
    assert sdl3_loader.os.environ["SDL_DOWNLOAD_BINARIES"] == "0"
    assert sdl3_loader.os.environ["SDL_FIND_BINARIES"] == "0"
