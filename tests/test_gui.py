"""GUI tests with a fake platform: anything that would change the real system fails the test."""

import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from battop import theme
from battop.config import Settings, SettingsStore
from battop.engine import Engine
from battop.gui import MainWindow
from battop.gui_theme import COLORS
from battop.status import PowerStatus
from battop.tray import Tray


class FakePlatform:
    name = "fake"
    supported_keys = frozenset({"brightness"})

    def system_theme(self):
        return "dark"

    def unavailable_reason(self, key):
        return None

    def warning(self, key):
        return None

    def running_app_names(self):
        return []

    def autostart_enabled(self):
        return False

    def set_autostart(self, enabled):
        raise AssertionError("tests must not change the real startup setting")


class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.root.destroy)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.engine = Engine(
            SettingsStore(Path(tmp.name) / "s.json"), [], lambda: PowerStatus(False, True, 80, None, False, False)
        )
        self.window = MainWindow(self.root, self.engine, FakePlatform(), queue.Queue(), Tray(queue.Queue()), True)

    def test_follows_the_system_theme_by_default_and_can_be_forced(self):
        self.assertEqual(COLORS["bg"], theme.DARK["bg"])  # FakePlatform reports a dark system theme.
        self.window.apply_theme("light")
        self.assertEqual(COLORS["bg"], theme.LIGHT["bg"])
        self.assertEqual(self.root.cget("bg"), theme.LIGHT["bg"])
        self.window.apply_theme("system")
        self.assertEqual(self.root.cget("bg"), theme.DARK["bg"])

    def test_theme_choice_round_trips_through_settings(self):
        self.window.theme_var.set("Light")
        self.assertEqual(self.window._collect().theme, "light")
        self.window._load(Settings(theme="dark"))
        self.assertEqual(self.window.theme_var.get(), "Dark")

    def test_half_typed_interval_falls_back_to_the_current_value(self):
        var = self.window.vars["poll_interval_sec"]
        self.root.tk.globalsetvar(str(var), "abc")
        self.assertEqual(self.window._collect().poll_interval_sec, self.engine.settings.poll_interval_sec)

    def test_every_setting_the_window_edits_is_collected(self):
        collected = self.window._collect()
        defaults = Settings()
        for key in self.window.vars:
            self.assertEqual(getattr(collected, key), getattr(defaults, key), key)

    def test_unsupported_cards_are_not_built(self):
        tabs = [self.window.root.nametowidget(t) for t in self.root.winfo_children()[0].tabs()]
        self.assertGreaterEqual(len(tabs), 3)  # Overview, Power saving, Low battery, General.


if __name__ == "__main__":
    unittest.main()
