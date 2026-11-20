from app.input.switch2_pro import decode_report, is_wired_switch2_pro


def test_wired_switch2_pro_uses_product_and_bus_instead_of_generic_sdl_name():
    assert is_wired_switch2_pro("0300bbe87e0500006920000000000000")
    assert not is_wired_switch2_pro("0300bbe87e0500000920000000000000")
    assert not is_wired_switch2_pro("0500bbe87e0500006920000000000000")


def test_switch2_pro_report_decodes_switch_button_order_and_both_sticks():
    report = bytearray(64)
    report[0] = 0x05
    report[5] = 0x08 | 0x40 | 0x80  # A, R, ZR.
    report[6] = 0x20  # Capture.
    report[7] = 0x02 | 0x08  # Up-left.
    report[11:14] = (3072 | 1024 << 12).to_bytes(3, "little")
    report[14:17] = (1024 | 3072 << 12).to_bytes(3, "little")
    axes, buttons = decode_report(bytes(report))
    assert axes == (0.5, 0.5, -0.5, -0.5, -1.0, 1.0)
    assert {index for index, pressed in enumerate(buttons) if pressed} == {
        0,
        10,
        11,
        13,
        15,
    }
    assert decode_report(bytes(report[:16])) is None
