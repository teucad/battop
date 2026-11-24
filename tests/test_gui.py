"""GUI tests with a fake platform: anything that would change the real system fails the test."""

import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest import mock

from battop import i18n, theme
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

    def system_language(self):
        return "en"

    def unavailable_reason(self, key):
        return None

    def warning(self, key):
        return None

    def fix_action(self, key):
        return None

    def open_path(self, path):
        raise AssertionError("tests must not open folders")

    def running_app_names(self):
        return []

    def autostart_enabled(self):
        return False

    def set_autostart(self, enabled):
        raise AssertionError("tests must not change the real startup setting")


class SetupNeededPlatform(FakePlatform):
    """cpu_limit is unavailable until its fix ("Set up…") has run, like the Linux root helper."""

    supported_keys = frozenset({"brightness", "cpu_limit"})

    def __init__(self, fails=False):
        self.ready, self.fails, self.fix_calls = False, fails, 0

    def unavailable_reason(self, key):
        return "Needs a one-time setup." if key == "cpu_limit" and not self.ready else None

    def fix_action(self, key):
        return ("Set up…", self._fix) if key == "cpu_limit" and not self.ready else None

    def _fix(self):
        self.fix_calls += 1
        if self.fails:
            raise OSError("The setup was cancelled.")
        self.ready = True


def widgets_of(root, kind):
    found = []
    for child in root.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found += widgets_of(child, kind)
    return found


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
        self.addCleanup(self.window._cancel_timers)  # Runs before the window is destroyed.

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

    def test_switching_language_rebuilds_the_window_and_keeps_values(self):
        self.addCleanup(i18n.set_language, "en")
        self.window.vars["brightness_percent"].set(55)
        self.window.vars["brightness_enabled"].set(True)
        tabs_before = len(self.window.notebook.tabs())
        self.window.notebook.select(1)
        self.window.language_var.set("Türkçe")
        self.window.apply_language("tr")
        self.root.update()
        self.assertEqual(i18n.current_language(), "tr")
        self.assertEqual(len(self.window.notebook.tabs()), tabs_before)
        self.assertEqual(self.window.notebook.index("current"), 1)
        self.assertEqual(self.window.notebook.tab(0, "text"), "Genel Bakış")
        self.assertEqual(self.window.vars["brightness_percent"].get(), 55)
        self.assertEqual(self.window.theme_var.get(), self.window._theme_names()["system"])
        collected = self.window._collect()
        self.assertEqual((collected.language, collected.theme), ("tr", "system"))
        # Changing a value afterwards must not poke widgets that were destroyed by the rebuild.
        self.window.vars["brightness_enabled"].set(False)
        self.window.vars["brightness_percent"].set(30)
        self.root.update()

    def test_activity_history_survives_a_language_switch(self):
        self.addCleanup(i18n.set_language, "en")
        self.window.log_queue.put("12:00   Something happened")
        self.window._drain_log()
        self.window.apply_language("tr")
        self.assertIn("Something happened", self.window.activity.get("1.0", "end"))

    def test_switching_back_to_english_works_too(self):
        self.addCleanup(i18n.set_language, "en")
        self.window.apply_language("tr")
        self.window.language_var.set("English")
        self.window.apply_language("en")
        self.assertEqual(self.window.notebook.tab(0, "text"), "Overview")
        self.assertEqual(self.window._collect().language, "en")

    def build(self, platform):
        self.window.platform = platform
        self.window._rebuild(self.window._collect())  # The same path a language change or a fix uses.
        self.root.update()

    def setup_buttons(self):
        return [b for b in widgets_of(self.root, ttk.Button) if str(b.cget("text")) == "Set up…"]

    def test_unavailable_card_explains_why_and_offers_the_fix(self):
        platform = SetupNeededPlatform()
        self.build(platform)
        labels = [str(w.cget("text")) for w in widgets_of(self.root, ttk.Label)]
        self.assertIn("Needs a one-time setup.", labels)
        self.assertEqual(len(self.setup_buttons()), 1)
        # The slider card for the unavailable feature is switched off.
        scales = widgets_of(self.root, ttk.Scale)
        self.assertTrue(any(scale.instate(["disabled"]) for scale in scales))

    def test_clicking_the_fix_runs_it_and_refreshes_the_card(self):
        platform = SetupNeededPlatform()
        self.build(platform)
        self.setup_buttons()[0].invoke()
        self.root.update()
        self.assertEqual(platform.fix_calls, 1)
        self.assertEqual(self.setup_buttons(), [], "the button disappears once the feature is available")
        labels = [str(w.cget("text")) for w in widgets_of(self.root, ttk.Label)]
        self.assertNotIn("Needs a one-time setup.", labels)

    def test_a_failing_fix_is_reported_and_leaves_the_card_as_it_was(self):
        platform = SetupNeededPlatform(fails=True)
        self.build(platform)
        with mock.patch("battop.gui.messagebox.showerror") as shown:
            self.setup_buttons()[0].invoke()
            self.root.update()
        shown.assert_called_once()
        self.assertIn("cancelled", shown.call_args[0][1])
        self.assertEqual(len(self.setup_buttons()), 1)

    def test_unsupported_cards_are_not_built(self):
        tabs = [self.window.root.nametowidget(t) for t in self.root.winfo_children()[0].tabs()]
        self.assertGreaterEqual(len(tabs), 3)  # Overview, Power saving, Low battery, General.


if __name__ == "__main__":
    unittest.main()
