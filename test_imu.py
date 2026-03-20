import unittest

from nxbt.controller.imu import (
    IMU_REPORT_SIZE,
    SWITCH_ACCEL_COUNTS_PER_G,
    build_motion_report,
    build_motion_sample,
    convert_sdl_accelerometer,
    convert_sdl_gyroscope,
)


class ImuConversionTests(unittest.TestCase):
    def test_accelerometer_conversion_uses_switch_gravity_scale(self):
        self.assertEqual(convert_sdl_accelerometer(0.0), 0)
        self.assertEqual(convert_sdl_accelerometer(9.80665), int(SWITCH_ACCEL_COUNTS_PER_G))

    def test_gyroscope_conversion_uses_switch_2000dps_scale(self):
        self.assertEqual(convert_sdl_gyroscope(0.0), 0)
        self.assertEqual(convert_sdl_gyroscope(1.0), 819)

    def test_motion_sample_reorders_axes_into_switch_layout(self):
        sample = build_motion_sample(
            accel_values_mps2=(1.0, 2.0, 9.80665),
            gyro_values_rads=(0.1, 0.2, 0.3),
        )

        self.assertEqual(len(sample), 12)
        # Accelerometer is packed in the raw Pro Controller report order.
        self.assertEqual(sample[0:2], [0x00, 0xF0])
        self.assertEqual(sample[2:4], [0x5E, 0xFE])
        self.assertEqual(sample[4:6], [0x43, 0x03])
        # Gyroscope follows the same raw report ordering.
        self.assertEqual(sample[6:8], [0x0A, 0xFF])
        self.assertEqual(sample[8:10], [0xAE, 0xFF])
        self.assertEqual(sample[10:12], [0xA4, 0x00])

    def test_motion_report_uses_three_samples_and_pads_with_latest(self):
        first_sample = list(range(12))
        second_sample = list(range(12, 24))

        report = build_motion_report([first_sample, second_sample])

        self.assertEqual(len(report), IMU_REPORT_SIZE)
        self.assertEqual(report[0:12], second_sample)
        self.assertEqual(report[12:24], first_sample)
        self.assertEqual(report[24:36], second_sample)


if __name__ == "__main__":
    unittest.main()
