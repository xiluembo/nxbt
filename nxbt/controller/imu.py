from __future__ import annotations

import math
from typing import Iterable, Sequence


IMU_SAMPLE_COUNT = 3
IMU_SAMPLE_SIZE = 12
IMU_REPORT_SIZE = IMU_SAMPLE_COUNT * IMU_SAMPLE_SIZE
STANDARD_GRAVITY = 9.80665
SWITCH_ACCEL_COUNTS_PER_G = 4096.0
SWITCH_GYRO_DPS_PER_DIGIT = 0.07

# Switch raw Pro Controller IMU samples are not laid out in the same axis order
# as SDL's controller sensors. This mapping matches the raw report layout used
# by the Pro Controller motion packet:
#   raw_accel_x <- report[1], raw_accel_y <- report[0], raw_accel_z <- report[2]
#   raw_gyro_x  <- report[4], raw_gyro_y  <- report[3], raw_gyro_z  <- report[5]
# with the corresponding Pro Controller sign conventions applied after decode.
# Keeping the report in this raw Switch order makes the resulting motion line up
# with the expected Pro Controller orientation.
SWITCH_ACCEL_AXIS_MAP = (
    (2, -1.0),
    (0, -1.0),
    (1, 1.0),
)

# Apply the same inverse mapping to the gyroscope so the raw Switch report
# decodes back into the expected controller-space motion:
#   gyro_x = SDL X, gyro_y = -SDL Z, gyro_z = SDL Y
SWITCH_GYRO_AXIS_MAP = (
    (2, -1.0),
    (0, -1.0),
    (1, 1.0),
)

DEFAULT_IMU_DATA = [
    0x75,
    0xFD,
    0xFD,
    0xFF,
    0x09,
    0x10,
    0x21,
    0x00,
    0xD5,
    0xFF,
    0xE0,
    0xFF,
    0x72,
    0xFD,
    0xF9,
    0xFF,
    0x0A,
    0x10,
    0x22,
    0x00,
    0xD5,
    0xFF,
    0xE0,
    0xFF,
    0x76,
    0xFD,
    0xFC,
    0xFF,
    0x09,
    0x10,
    0x23,
    0x00,
    0xD5,
    0xFF,
    0xE0,
    0xFF,
]


def copy_default_imu_data() -> list[int]:
    return list(DEFAULT_IMU_DATA)


def normalize_imu_data(imu_data: Sequence[int] | None) -> list[int] | None:
    if imu_data is None or len(imu_data) != IMU_REPORT_SIZE:
        return None

    normalized = []
    for value in imu_data:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return None
        normalized.append(numeric & 0xFF)
    return normalized


def convert_sdl_accelerometer(value_mps2: float) -> int:
    return clamp_int16(
        round((float(value_mps2) / STANDARD_GRAVITY) * SWITCH_ACCEL_COUNTS_PER_G)
    )


def convert_sdl_gyroscope(value_rads: float) -> int:
    value_dps = math.degrees(float(value_rads))
    return clamp_int16(round(value_dps / SWITCH_GYRO_DPS_PER_DIGIT))


def map_switch_axes(
    values: Sequence[float],
    axis_map: Sequence[tuple[int, float]],
) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("Expected exactly 3 axes")
    return tuple(float(values[index]) * sign for index, sign in axis_map)


def build_motion_sample(
    accel_values_mps2: Sequence[float],
    gyro_values_rads: Sequence[float],
) -> list[int]:
    accel_axes = map_switch_axes(accel_values_mps2, SWITCH_ACCEL_AXIS_MAP)
    gyro_axes = map_switch_axes(gyro_values_rads, SWITCH_GYRO_AXIS_MAP)

    sample = []
    for value in accel_axes:
        sample.extend(pack_int16_le(convert_sdl_accelerometer(value)))
    for value in gyro_axes:
        sample.extend(pack_int16_le(convert_sdl_gyroscope(value)))
    return sample


def build_motion_report(samples: Iterable[Sequence[int]]) -> list[int]:
    normalized_samples = []
    for sample in samples:
        normalized = normalize_imu_sample(sample)
        if normalized is not None:
            normalized_samples.append(normalized)

    if not normalized_samples:
        return copy_default_imu_data()

    newest_sample = normalized_samples[-1]
    while len(normalized_samples) < IMU_SAMPLE_COUNT:
        normalized_samples.insert(0, list(newest_sample))

    report = []
    for sample in normalized_samples[-IMU_SAMPLE_COUNT:]:
        report.extend(sample)
    return report


def normalize_imu_sample(sample: Sequence[int] | None) -> list[int] | None:
    if sample is None or len(sample) != IMU_SAMPLE_SIZE:
        return None

    normalized = []
    for value in sample:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return None
        normalized.append(numeric & 0xFF)
    return normalized


def pack_int16_le(value: int) -> list[int]:
    value &= 0xFFFF
    return [value & 0xFF, (value >> 8) & 0xFF]


def clamp_int16(value: int) -> int:
    return max(-32768, min(32767, int(value)))
