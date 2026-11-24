import tempfile
import unittest
from pathlib import Path
from unittest import mock

from battop import uninstall as uninstall_module


class FakePlatform:
    def __init__(self, fail=False):
        self.fail = fail
        self.autostart_calls = []

    def set_autostart(self, enabled):
        self.autostart_calls.append(enabled)
        if self.fail:
            raise OSError("registry is locked")


class UninstallTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "Battop"
        self.folder.mkdir()
        (self.folder / "settings.json").write_text("{}", encoding="utf-8")
        patcher = mock.patch.object(uninstall_module, "data_dir", return_value=self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_removes_startup_entry_and_data(self):
        platform = FakePlatform()
        self.assertEqual(uninstall_module.uninstall(platform), [])
        self.assertEqual(platform.autostart_calls, [False])
        self.assertFalse(self.folder.exists())

    def test_reports_problems_but_still_removes_the_data(self):
        problems = uninstall_module.uninstall(FakePlatform(fail=True))
        self.assertEqual(len(problems), 1)
        self.assertIn("startup", problems[0])
        self.assertFalse(self.folder.exists())


if __name__ == "__main__":
    unittest.main()
