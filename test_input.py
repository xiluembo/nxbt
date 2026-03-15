import unittest

from nxbt.controller.input import DIRECT_INPUT_IDLE_PACKET, InputParser


class _FakeProtocol:
    def __init__(self):
        self.upper = None
        self.shared = None
        self.lower = None
        self.left = None
        self.right = None

    def set_button_inputs(self, upper, shared, lower):
        self.upper = upper
        self.shared = shared
        self.lower = lower

    def set_left_stick_inputs(self, left):
        self.left = left

    def set_right_stick_inputs(self, right):
        self.right = right


class InputParserTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
