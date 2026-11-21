import pytest

from lib.controller import ControllerTypes, ControllerVariant
from lib.input.presets import PresetValidationError, validate_preset
from lib.input.state import (
    Button,
    ControllerState,
    apply_to_protocol,
    rotate_joycon_stick,
)
from lib.input.stick import PRO_LEFT, PRO_RIGHT, calibrate_stick
from lib.switch_protocol import ControllerProtocol


@pytest.mark.parametrize(
    "variant, controller_id, button_bytes, stick_bytes",
    [
        (ControllerVariant.LEFT, 1, b"\x00\x01\x21", bytes(calibrate_stick((0, -1), PRO_LEFT)) + bytes(3)),
        (ControllerVariant.RIGHT, 2, b"\x28\x10\x00", bytes(3) + bytes(calibrate_stick((-1, 0), PRO_RIGHT))),
    ],
)
def test_joycon_reports_contain_only_their_own_buttons_and_rotated_stick(
    variant, controller_id, button_bytes, stick_bytes
):
    protocol = ControllerProtocol(variant.bluetooth_type, "98:B6:E9:7E:E9:8D")
    request = bytes.fromhex("A2 01 00 00 00 00 00 00 00 00 00 02")
    protocol.process_commands(request.ljust(50, b"\x00"))
    assert protocol.get_report()[18] == controller_id

    state = ControllerState(
        Button.A | Button.DOWN | Button.MINUS | Button.HOME | Button.SL_L | Button.SL_R,
        left=(1, 0), right=(0, 1),
    )
    apply_to_protocol(protocol, rotate_joycon_stick(state, variant))
    report = protocol.get_report()
    assert report[4:7] == button_bytes
    assert report[7:13] == stick_bytes


def test_v2_controller_mappings_resolve_independently():
    data = {
        "version": 2,
        "mappings": {
            "pro": {"buttons": {"0": "A", "4": "L"}, "left_stick": {"x_axis": 3, "y_axis": 4}},
            "joycon_l": {"buttons": {"7": "SR_L"}, "dpad": {"hat": None}},
            "joycon_r": {"buttons": {"0": "X", "4": "SL_R"}, "right_stick": {"x_axis": 3, "y_axis": 4}},
            "combined": {"buttons": {"0": "B"}},
        },
    }
    preset = validate_preset(data)
    assert preset.mapping_for(ControllerVariant.PRO).button_map == {0: Button.A, 4: Button.L}
    assert preset.mapping_for(ControllerVariant.LEFT).button_map == {7: Button.SR_L}
    assert preset.mapping_for(ControllerVariant.RIGHT).button_map == {0: Button.X, 4: Button.SL_R}
    assert preset.mapping_for(ControllerVariant.RIGHT).right_stick == (3, 4)
    assert preset.mapping_for(ControllerVariant.COMBINED).button_map == {0: Button.B}

    data["mappings"]["joycon_l"]["buttons"]["7"] = "invalid"
    with pytest.raises(PresetValidationError) as invalid:
        validate_preset(data)
    assert invalid.value.path == ["mappings", "joycon_l", "buttons", "7"]


@pytest.mark.parametrize(
    "pattern, player", [(0x09, 5), (0x50, 6), (0x0D, 7), (0x60, 8)]
)
def test_player_light_patterns_above_four(pattern, player):
    protocol = ControllerProtocol(ControllerTypes.PRO_CONTROLLER, "98:B6:E9:7E:E9:8D")
    request = bytes.fromhex("A2 01 00 00 00 00 00 00 00 00 00 30") + bytes([pattern])
    protocol.process_commands(request.ljust(50, b"\0"))
    assert protocol.get_report()[14:16] == bytes.fromhex("80 30")
    assert protocol.player_number == player


@pytest.mark.parametrize("suffix", ["", "/P"])
def test_device_info_uses_public_bluetooth_address(suffix):
    protocol = ControllerProtocol(
        ControllerTypes.PRO_CONTROLLER, f"98:B6:E9:7E:E9:8D{suffix}"
    )

    protocol.set_device_info()

    assert protocol.report[20:26] == list(bytes.fromhex("98B6E97EE98D"))


@pytest.mark.parametrize(
    "controller_type, colour_mode, left_grip",
    [
        (ControllerTypes.PRO_CONTROLLER, 0x02, "828282"),
        (ControllerTypes.JOYCON_L, 0x01, "FFFFFF"),
        (ControllerTypes.JOYCON_R, 0x01, "FFFFFF"),
    ],
)
def test_handshake_advertises_and_returns_grip_colours(
    controller_type, colour_mode, left_grip
):
    protocol = ControllerProtocol(controller_type, "98:B6:E9:7E:E9:8D")

    def exchange(subcommand):
        request = bytes.fromhex("A2 01 00 00 00 00 00 00 00 00 00")
        protocol.process_commands(
            (request + bytes.fromhex(subcommand)).ljust(50, b"\x00")
        )
        return protocol.get_report()

    device_info = exchange("02")
    assert device_info[:2] == bytes.fromhex("A1 21")
    assert device_info[14:16] == bytes.fromhex("82 02")
    assert device_info[27] == colour_mode

    colours = exchange("10 50 60 00 00 0D")
    assert colours[:2] == bytes.fromhex("A1 21")
    assert colours[14:21] == bytes.fromhex("90 10 50 60 00 00 0D")
    assert colours[21:27] == bytes.fromhex("000000 FFFFFF")
    assert colours[27:30] == bytes.fromhex(left_grip)
    right_grip = (
        "828282" if controller_type == ControllerTypes.PRO_CONTROLLER else "FFFFFF"
    )
    assert colours[30:34] == bytes.fromhex(right_grip + "FF")


def test_custom_colours_agree_across_spi_reads_and_device_info():
    protocol = ControllerProtocol(ControllerTypes.PRO_CONTROLLER, "98:B6:E9:7E:E9:8D")
    protocol.set_colours(
        body="#123456", buttons="#abcdef", left_grip="#ff0000", right_grip="#0000ff"
    )

    def read(address, length):
        request = bytes.fromhex("A2 01 00 00 00 00 00 00 00 00 00 10")
        request += address.to_bytes(4, "little") + bytes([length])
        protocol.process_commands(request.ljust(50, b"\x00"))
        return protocol.get_report()[21 : 21 + length]

    expected = bytes.fromhex("123456 ABCDEF FF0000 0000FF FF")
    assert read(0x6050, 13) == expected
    assert read(0x603D, 25)[19:] == expected[:6]
    assert read(0x6056, 3) == bytes.fromhex("FF0000")
    assert read(0x6054, 8) == expected[4:12]
    protocol.set_device_info()
    assert read(0x601B, 1) == bytes([protocol.colour_mode])
    snapshot = protocol.get_colours()
    snapshot["left_grip"] = "#FFFFFF"
    assert protocol.get_colours()["left_grip"] == "#FF0000"


@pytest.mark.parametrize("colour", ["#FF000", "#GG0000", [255, 0, 0], 123])
def test_invalid_colour_updates_leave_palette_unchanged(colour):
    protocol = ControllerProtocol(ControllerTypes.PRO_CONTROLLER, "98:B6:E9:7E:E9:8D")
    original = protocol.get_colours()
    with pytest.raises(ValueError):
        protocol.set_colours(body="#123456", left_grip=colour)
    assert protocol.get_colours() == original


def test_constructor_accepts_existing_rgb_byte_arguments():
    protocol = ControllerProtocol(
        ControllerTypes.PRO_CONTROLLER,
        "98:B6:E9:7E:E9:8D",
        colour_body=[12, 34, 56],
        colour_left_grip=bytes([255, 0, 0]),
    )
    assert protocol.get_colours()["body"] == "#0C2238"
    assert protocol.get_colours()["left_grip"] == "#FF0000"
