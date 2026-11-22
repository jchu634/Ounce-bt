"""Encode SDL3 SI motion samples into Nintendo Switch 0x30 3-frame IMU payloads."""

from __future__ import annotations

import math
import struct
import threading
from collections import deque
from collections.abc import Sequence

from lib.controller import ControllerTypes
from lib.input.sdl3_backend import STANDARD_GRAVITY, ImuSample

# Zero-origin factory calibration matches Switch defaults (4096 LSB/g, 13371 LSB / 936 dps).
ACCEL_SCALE = 4096.0 / STANDARD_GRAVITY
GYRO_SCALE = 13371.0 / (936.0 * math.pi / 180.0)

_FRAME_STRUCT = struct.Struct("<6h")


RESTING_IMU = ImuSample()


def _clamp_i16(value: float) -> int:
    rounded = round(value)
    if rounded < -32768:
        return -32768
    if rounded > 32767:
        return 32767
    return rounded


def _orient_vector(
    vec: tuple[float, float, float],
    controller_type: ControllerTypes,
    *,
    horizontal: bool = False,
) -> tuple[float, float, float]:
    """Rotate an SDL3 (+X right, +Y up, +Z toward player) vector into Switch IMU space."""
    x, y, z = vec
    if controller_type == ControllerTypes.JOYCON_L:
        if horizontal:
            return (-x, z, y)
        return (-z, -x, y)
    if controller_type == ControllerTypes.JOYCON_R:
        if horizontal:
            return (x, z, -y)
        return (-z, x, -y)
    # Pro Controller: +X forward (-Z), +Y left (-X), +Z up (+Y).
    return (-z, -x, y)


def encode_imu_sample(
    sample: ImuSample,
    controller_type: ControllerTypes = ControllerTypes.PRO_CONTROLLER,
    *,
    horizontal: bool = False,
) -> bytes:
    """Pack one ``ImuSample`` into a 12-byte Switch IMU frame."""
    ax, ay, az = _orient_vector(sample.accel, controller_type, horizontal=horizontal)
    gx, gy, gz = _orient_vector(sample.gyro, controller_type, horizontal=horizontal)
    return _FRAME_STRUCT.pack(
        _clamp_i16(ax * ACCEL_SCALE),
        _clamp_i16(ay * ACCEL_SCALE),
        _clamp_i16(az * ACCEL_SCALE),
        _clamp_i16(gx * GYRO_SCALE),
        _clamp_i16(gy * GYRO_SCALE),
        _clamp_i16(gz * GYRO_SCALE),
    )


def pack_imu_frames(
    samples: Sequence[ImuSample],
    controller_type: ControllerTypes = ControllerTypes.PRO_CONTROLLER,
    *,
    horizontal: bool = False,
) -> bytes:
    """Pack 1..N samples into the 3-frame (36-byte) Switch 0x30 IMU payload."""
    if not samples:
        frame = encode_imu_sample(RESTING_IMU, controller_type, horizontal=horizontal)
        return frame * 3
    if len(samples) == 1:
        frame = encode_imu_sample(samples[0], controller_type, horizontal=horizontal)
        return frame * 3
    if len(samples) == 2:
        first = encode_imu_sample(samples[0], controller_type, horizontal=horizontal)
        second = encode_imu_sample(samples[1], controller_type, horizontal=horizontal)
        return first + second + second
    # Pick 3 evenly spaced frames from oldest..newest so high-rate IMUs (e.g. 250 Hz)
    # preserve full motion span across one 15 ms Switch packet.
    last = len(samples) - 1
    chosen = (samples[0], samples[last // 2], samples[last])
    return b"".join(
        encode_imu_sample(sample, controller_type, horizontal=horizontal)
        for sample in chosen
    )


class ImuBuffer:
    """Thread-safe bounded IMU sample buffer supporting multiple independent readers.

    Each consumer tracks its own monotonic cursor so paired Combined Joy-Cons
    can both read fresh IMU samples from one physical controller without
    starving each other.
    """

    def __init__(self, maxlen: int = 24):
        self._lock = threading.Lock()
        self._samples: deque[tuple[int, ImuSample]] = deque(maxlen=maxlen)
        self._seq = 0

    def push(self, samples: Sequence[ImuSample]) -> None:
        if not samples:
            return
        with self._lock:
            for sample in samples:
                self._seq += 1
                self._samples.append((self._seq, sample))

    def read_since(self, cursor: int) -> tuple[int, list[ImuSample]]:
        with self._lock:
            if not self._samples or cursor >= self._seq:
                return self._seq, []
            fresh = [sample for seq, sample in self._samples if seq > cursor]
            return self._seq, fresh

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()
