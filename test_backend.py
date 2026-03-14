import sys
import unittest

from nxbt.backend import get_backend, resolve_backend_name


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


if __name__ == "__main__":
    unittest.main()
