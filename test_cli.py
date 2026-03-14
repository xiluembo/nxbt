import argparse
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from nxbt.cli import _start_webapp, resolve_reconnect_target


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

    def test_webapp_missing_dependency_prints_helpful_message(self):
        output = io.StringIO()

        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "flask_socketio":
                raise ModuleNotFoundError("No module named 'flask_socketio'")
            return real_import(name, globals, locals, fromlist, level)

        original_web = sys.modules.pop("nxbt.web", None)
        original_web_app = sys.modules.pop("nxbt.web.app", None)
        try:
            with redirect_stdout(output):
                with patch("builtins.__import__", side_effect=fake_import):
                    _start_webapp("0.0.0.0", 8000, False, None)
        finally:
            if original_web is not None:
                sys.modules["nxbt.web"] = original_web
            if original_web_app is not None:
                sys.modules["nxbt.web.app"] = original_web_app

        self.assertIn("webapp dependencies are not installed", output.getvalue())
        self.assertIn("Flask-SocketIO", output.getvalue())

    def test_webapp_bind_error_prints_helpful_message(self):
        output = io.StringIO()
        fake_web_module = types.SimpleNamespace(
            start_web_app=lambda **kwargs: (_ for _ in ()).throw(
                OSError("Unable to bind the NXBT webapp to 0.0.0.0:8000.")
            )
        )
        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "nxbt.web":
                return fake_web_module
            return real_import(name, globals, locals, fromlist, level)

        with redirect_stdout(output):
            with patch("builtins.__import__", side_effect=fake_import):
                _start_webapp("0.0.0.0", 8000, False, None)

        self.assertIn("Unable to bind the NXBT webapp", output.getvalue())


if __name__ == "__main__":
    unittest.main()
