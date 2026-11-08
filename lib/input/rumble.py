from __future__ import annotations

from dataclasses import dataclass

# https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering/blob/master/rumble_data_table.md
# Index shared by HA >> 1 and ((LA - 0x40) << 1) | the LA half-step bit.
# fmt: off
_AMPLITUDES = (
    0.000000, 0.007843, 0.011823, 0.014061, 0.016720, 0.019885, 0.023648, 0.028123,
    0.033442, 0.039771, 0.047296, 0.056246, 0.066886, 0.079542, 0.094592, 0.112491,
    0.117471, 0.122671, 0.128102, 0.133774, 0.139697, 0.145882, 0.152341, 0.159085,
    0.166129, 0.173484, 0.181166, 0.189185, 0.197561, 0.206308, 0.215442, 0.224982,
    0.229908, 0.234943, 0.240087, 0.245345, 0.250715, 0.256206, 0.261816, 0.267549,
    0.273407, 0.279394, 0.285514, 0.291765, 0.298154, 0.304681, 0.311353, 0.318171,
    0.325138, 0.332258, 0.339534, 0.346969, 0.354566, 0.362331, 0.370265, 0.378372,
    0.386657, 0.395124, 0.403777, 0.412619, 0.421652, 0.430885, 0.440321, 0.449964,
    0.459817, 0.469885, 0.480174, 0.490689, 0.501433, 0.512413, 0.523633, 0.535100,
    0.546816, 0.558790, 0.571027, 0.583530, 0.596307, 0.609365, 0.622708, 0.636344,
    0.650279, 0.664518, 0.679069, 0.693939, 0.709133, 0.724662, 0.740529, 0.756745,
    0.773316, 0.790249, 0.807554, 0.825237, 0.843307, 0.861772, 0.880643, 0.899928,
    0.919633, 0.939771, 0.960348, 0.981378, 1.002867, 1.024826, 1.047266, 1.070197,
    1.093630, 1.117576, 1.142045, 1.167051, 1.192603, 1.218715, 1.245398, 1.272665,
    1.300529, 1.329003, 1.358100, 1.387834, 1.418218, 1.449268, 1.480997, 1.513420,
    1.546553, 1.580411, 1.615010, 1.650366, 1.686497, 1.723417, 1.761146, 1.799701,
)
# fmt: on


@dataclass(frozen=True, slots=True)
class MotorRumble:
    """Independent high and low bands for one Switch actuator."""

    high_frequency_hz: float
    high_amplitude: float
    low_frequency_hz: float
    low_amplitude: float

    @property
    def active(self) -> bool:
        return self.high_amplitude > 0 or self.low_amplitude > 0


@dataclass(frozen=True, slots=True)
class RumbleData:
    left: MotorRumble
    right: MotorRumble

    @property
    def active(self) -> bool:
        return self.left.active or self.right.active

    def strengths(self) -> tuple[float, float]:
        """Mix each band across both actuators without doubling its strength."""
        return (
            min(1.0, max(self.left.low_amplitude, self.right.low_amplitude)),
            min(1.0, max(self.left.high_amplitude, self.right.high_amplitude)),
        )


def _decode_motor(b0: int, b1: int, b2: int, b3: int) -> MotorRumble:
    hf = (b0 | ((b1 & 1) << 8)) // 4 + 0x60
    lf = (b2 & 0x7F) + 0x40
    low_index = ((b3 - 0x40) << 1) | (b2 >> 7)
    # Zero-filled initialization words have no valid LF amplitude encoding.
    low_amplitude = _AMPLITUDES[low_index] if 0 <= low_index < 128 else 0.0
    return MotorRumble(
        10.0 * 2 ** (hf / 32),
        _AMPLITUDES[b1 >> 1],
        10.0 * 2 ** (lf / 32),
        low_amplitude,
    )


def parse_rumble(packet: bytes) -> RumbleData | None:
    """Decode framed Bluetooth HID output, including rumble-only reports."""
    if len(packet) < 11 or packet[0] != 0xA2 or packet[1] not in (0x01, 0x10, 0x11):
        return None
    if packet[1] == 0x01 and len(packet) < 12:
        return None
    return RumbleData(_decode_motor(*packet[3:7]), _decode_motor(*packet[7:11]))
