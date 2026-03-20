import unittest

from nxbt.controller.imu import copy_default_imu_data
from nxbt.controller.input import DIRECT_INPUT_IDLE_PACKET, InputParser
from nxbt.controller.protocol import ControllerProtocol
from nxbt.controller.controller import ControllerTypes


class _FakeProtocol:
    def __init__(self):
        self.upper = None
        self.shared = None
        self.lower = None
        self.left = None
        self.right = None
        self.imu_data = None

    def set_button_inputs(self, upper, shared, lower):
        self.upper = upper
        self.shared = shared
        self.lower = lower

    def set_left_stick_inputs(self, left):
        self.left = left

    def set_right_stick_inputs(self, right):
        self.right = right

    def set_imu_data(self, imu_data=None):
        self.imu_data = imu_data


class InputParserTests(unittest.TestCase):
    def test_direct_input_idle_packet_contains_default_imu_data(self):
        self.assertEqual(DIRECT_INPUT_IDLE_PACKET["IMU_DATA"], copy_default_imu_data())

    def test_direct_input_plus_minus_matches_macro_encoding(self):
        protocol = _FakeProtocol()
        parser = InputParser(protocol)

        controller_input = {
            **DIRECT_INPUT_IDLE_PACKET,
            "L_STICK": dict(DIRECT_INPUT_IDLE_PACKET["L_STICK"]),
            "R_STICK": dict(DIRECT_INPUT_IDLE_PACKET["R_STICK"]),
            "PLUS": True,
            "MINUS": True,
        }

        parser.parse_controller_input(controller_input)
        direct_shared = protocol.shared

        parser.set_macro_input(["PLUS", "MINUS", "0.0s"])
        macro_shared = protocol.shared

        self.assertEqual(direct_shared, macro_shared)
        self.assertEqual(direct_shared, 0b00000011)

    def test_direct_input_passes_custom_imu_data_to_protocol(self):
        protocol = _FakeProtocol()
        parser = InputParser(protocol)
        custom_imu = list(range(36))

        controller_input = {
            **DIRECT_INPUT_IDLE_PACKET,
            "L_STICK": dict(DIRECT_INPUT_IDLE_PACKET["L_STICK"]),
            "R_STICK": dict(DIRECT_INPUT_IDLE_PACKET["R_STICK"]),
            "IMU_DATA": custom_imu,
        }

        parser.parse_controller_input(controller_input)

        self.assertEqual(protocol.imu_data, custom_imu)


class ControllerProtocolImuTests(unittest.TestCase):
    def test_set_imu_data_without_argument_uses_default_report(self):
        protocol = ControllerProtocol(ControllerTypes.PRO_CONTROLLER, "00:11:22:33:44:55")
        protocol.imu_enabled = True
        protocol.set_empty_report()

        protocol.set_imu_data()

        self.assertEqual(protocol.report[14:50], copy_default_imu_data())

    def test_set_imu_data_uses_custom_report_when_present(self):
        protocol = ControllerProtocol(ControllerTypes.PRO_CONTROLLER, "00:11:22:33:44:55")
        protocol.imu_enabled = True
        protocol.set_empty_report()
        custom_imu = list(range(36))

        protocol.set_imu_data(custom_imu)

        self.assertEqual(protocol.report[14:50], custom_imu)


if __name__ == "__main__":
    unittest.main()
