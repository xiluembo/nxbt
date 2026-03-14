import argparse
import unittest

from nxbt.cli import resolve_reconnect_target


class CliReconnectResolutionTests(unittest.TestCase):
    def make_args(self, **overrides):
        values = {
            "reconnect": False,
            "address": False,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_explicit_address_is_used(self):
        target, message = resolve_reconnect_target(
            self.make_args(address="AA:BB:CC:DD:EE:FF"),
            ["11:22:33:44:55:66"],
        )

        self.assertEqual(target, "AA:BB:CC:DD:EE:FF")
        self.assertIn("AA:BB:CC:DD:EE:FF", message)

    def test_default_uses_single_saved_address(self):
        target, message = resolve_reconnect_target(
            self.make_args(),
            ["AA:BB:CC:DD:EE:FF"],
        )

        self.assertEqual(target, "AA:BB:CC:DD:EE:FF")
        self.assertIn("--address", message)

    def test_default_uses_all_saved_addresses(self):
        addresses = ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]
        target, message = resolve_reconnect_target(
            self.make_args(),
            addresses,
        )

        self.assertEqual(target, addresses)
        self.assertIn("--address", message)

    def test_reconnect_without_saved_addresses_falls_back_to_pairing(self):
        target, message = resolve_reconnect_target(
            self.make_args(reconnect=True),
            [],
        )

        self.assertIsNone(target)
        self.assertIn("new pairing", message)

    def test_invalid_address_raises(self):
        with self.assertRaises(ValueError):
            resolve_reconnect_target(
                self.make_args(address="not-a-mac"),
                [],
            )


if __name__ == "__main__":
    unittest.main()
