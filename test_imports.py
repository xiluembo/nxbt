import unittest


class ImportSmokeTests(unittest.TestCase):
    def test_package_import(self):
        import nxbt

        self.assertTrue(hasattr(nxbt, "Nxbt"))

    def test_cli_import(self):
        import nxbt.cli

        self.assertTrue(hasattr(nxbt.cli, "main"))

    def test_qt_import(self):
        import nxbt.qt

        self.assertTrue(hasattr(nxbt.qt, "start_qt_app"))

    def test_controller_server_import(self):
        from nxbt.controller.server import ControllerServer

        self.assertIsNotNone(ControllerServer)


if __name__ == "__main__":
    unittest.main()
