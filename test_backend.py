import sys
import unittest

from nxbt.backend import get_backend, resolve_backend_name
from nxbt.backend_bumble import BumbleControllerAdapter


class BackendSelectionTests(unittest.TestCase):
    def test_auto_backend_matches_platform(self):
        if sys.platform.startswith("linux"):
            self.assertEqual(resolve_backend_name("auto"), "linux")
        elif sys.platform == "win32":
            self.assertEqual(resolve_backend_name("auto"), "bumble")
        else:
            self.assertEqual(resolve_backend_name("auto"), "bumble")

    def test_default_backend_exposes_status(self):
        backend = get_backend()
        status = backend.get_status()

        self.assertEqual(status["name"], resolve_backend_name("auto"))
        self.assertIn("message", status)


class _FakeBumbleError(Exception):
    def __init__(self, error_name=""):
        super().__init__(error_name)
        self.error_name = error_name


class _FakeReconnectRuntime:
    def __init__(self, error):
        self.error = error
        self.alias = ""
        self.class_of_device = 0
        self.connectable = False
        self.discoverable = False
        self.sdp_record_xml = None
        self.address = "00:00:00:00:00:00"

    def start(self):
        return None

    def reconnect(self, address):
        return address

    def call(self, _coroutine):
        raise self.error


class BumbleReconnectErrorTests(unittest.TestCase):
    def test_reconnect_page_timeout_has_helpful_message(self):
        adapter = BumbleControllerAdapter(adapter_path="usb:0")
        adapter.runtime = _FakeReconnectRuntime(
            _FakeBumbleError(error_name="PAGE_TIMEOUT_ERROR")
        )

        with self.assertRaisesRegex(
            OSError, "Wake the Switch and keep it on the Home screen"
        ):
            adapter.create_reconnect_transport("B8:8A:EC:89:03:0E")

    def test_reconnect_other_errors_keep_generic_message(self):
        adapter = BumbleControllerAdapter(adapter_path="usb:0")
        adapter.runtime = _FakeReconnectRuntime(
            _FakeBumbleError(error_name="CONNECTION_ALREADY_EXISTS_ERROR")
        )

        with self.assertRaisesRegex(
            OSError, "Unable to reconnect to sockets at the given address"
        ):
            adapter.create_reconnect_transport("B8:8A:EC:89:03:0E")


if __name__ == "__main__":
    unittest.main()
