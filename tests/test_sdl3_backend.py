from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from app.input.controller_service import map_gamepad_state
from lib import sdl3 as sdl3_loader
from lib.controller import ControllerVariant
from lib.input.presets import PresetConfig, load_preset
from lib.input.sdl3_backend import Sdl3Host
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
    assert PresetConfig.default().rumble_enabled is True


def test_sdl3_host_initializes_and_quits_cleanly():
    host = Sdl3Host()
    assert host.init()
    try:
        devices = host.list_devices()
        assert isinstance(devices, list)
    finally:
        host.quit()


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
