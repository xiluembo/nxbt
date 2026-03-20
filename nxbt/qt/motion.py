from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Sequence

from ..controller.imu import (
    IMU_SAMPLE_COUNT,
    build_motion_report,
    build_motion_sample,
    copy_default_imu_data,
)


MOTION_STATUS_SENSOR = "Motion Sensor: SDL3"
MOTION_STATUS_DEFAULT = "Motion Sensor: Default IMU"


@dataclass
class MotionBuffer:
    motion_available: bool = False
    motion_status: str = MOTION_STATUS_DEFAULT
    status_detail: str = ""
    samples: deque[list[int]] = field(
        default_factory=lambda: deque(maxlen=IMU_SAMPLE_COUNT)
    )

    def push_sensor_sample(
        self,
        accelerometer_values: Sequence[float],
        gyroscope_values: Sequence[float],
    ) -> None:
        self.samples.append(
            build_motion_sample(accelerometer_values, gyroscope_values)
        )

    def build_report(self) -> list[int]:
        if not self.motion_available:
            return copy_default_imu_data()
        return build_motion_report(self.samples)


def motion_details(
    *,
    provider_name: str,
    instance_id: int,
    motion_status: str,
    status_detail: str = "",
) -> str:
    details = (
        f"Detected mapping: SDL3 Gamepad | Name: {provider_name} | "
        f"Instance ID: {instance_id} | {motion_status}"
    )
    if status_detail:
        details = f"{details} | {status_detail}"
    return details
