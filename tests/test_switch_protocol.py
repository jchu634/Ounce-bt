import pytest

from lib.controller import ControllerTypes
from lib.switch_protocol import ControllerProtocol


@pytest.mark.parametrize("suffix", ["", "/P"])
def test_device_info_uses_public_bluetooth_address(suffix):
    protocol = ControllerProtocol(
        ControllerTypes.PRO_CONTROLLER, f"98:B6:E9:7E:E9:8D{suffix}"
    )

    protocol.set_device_info()

    assert protocol.report[20:26] == list(bytes.fromhex("98B6E97EE98D"))
