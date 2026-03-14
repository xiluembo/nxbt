import unittest
from unittest.mock import patch

import psutil

from nxbt.tui import InputTUI


class _FakeProcess:
    def __init__(self, name, parent_pid):
        self._name = name
        self._parent_pid = parent_pid

    def name(self):
        return self._name

    def ppid(self):
        return self._parent_pid


class TuiRemoteDetectionTests(unittest.TestCase):
    def test_detect_remote_connection_returns_false_when_parent_disappears(self):
        tui = InputTUI.__new__(InputTUI)

        with patch("nxbt.tui.os.getppid", return_value=5232):
            with patch(
                "nxbt.tui.psutil.Process",
                side_effect=psutil.NoSuchProcess(pid=5232),
            ):
                self.assertFalse(tui.detect_remote_connection())

    def test_detect_remote_connection_finds_remote_parent(self):
        tui = InputTUI.__new__(InputTUI)
        processes = {
            200: _FakeProcess("powershell.exe", 100),
            100: _FakeProcess("sshd", 0),
        }

        with patch("nxbt.tui.os.getppid", return_value=200):
            with patch(
                "nxbt.tui.psutil.Process",
                side_effect=lambda pid: processes[pid],
            ):
                self.assertTrue(tui.detect_remote_connection())


if __name__ == "__main__":
    unittest.main()
