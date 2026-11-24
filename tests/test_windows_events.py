import ctypes
import sys
import threading
import unittest
from ctypes import wintypes

if sys.platform == "win32":
    from battop.platforms.windows import events

    _user32 = ctypes.WinDLL("user32")
    _user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.SendMessageW.restype = ctypes.c_ssize_t


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class EventWindowTests(unittest.TestCase):
    def setUp(self):
        self.hits = {k: threading.Event() for k in ("power", "end", "theme", "show")}
        self.window = events.EventWindow(
            on_power_change=self.hits["power"].set,
            on_end_session=self.hits["end"].set,
            on_theme_change=self.hits["theme"].set,
            on_show=self.hits["show"].set,
        )
        self.assertTrue(self.window.start(), "hidden window should be created")
        self.addCleanup(self.window.stop)

    def send(self, msg, wparam=0, lparam=0):
        return _user32.SendMessageW(self.window._hwnd, msg, wparam, lparam)

    def test_power_change_and_resume(self):
        self.send(events.WM_POWERBROADCAST, events.PBT_POWERSETTINGCHANGE)
        self.assertTrue(self.hits["power"].is_set())
        self.hits["power"].clear()
        self.send(events.WM_POWERBROADCAST, events.PBT_APMRESUMEAUTOMATIC)
        self.assertTrue(self.hits["power"].is_set())

    def test_theme_change_only_for_immersive_color_set(self):
        other = ctypes.create_unicode_buffer("Environment")
        self.send(events.WM_SETTINGCHANGE, 0, ctypes.addressof(other))
        self.assertFalse(self.hits["theme"].is_set())
        theme = ctypes.create_unicode_buffer("ImmersiveColorSet")
        self.send(events.WM_SETTINGCHANGE, 0, ctypes.addressof(theme))
        self.assertTrue(self.hits["theme"].is_set())

    def test_end_session_only_when_actually_ending(self):
        self.assertEqual(self.send(events.WM_QUERYENDSESSION), 1)
        self.send(events.WM_ENDSESSION, 0)  # Session end was cancelled.
        self.assertFalse(self.hits["end"].is_set())
        self.send(events.WM_ENDSESSION, 1)
        self.assertTrue(self.hits["end"].is_set())

    def test_second_launch_can_ask_first_to_show(self):
        self.assertTrue(events.signal_existing_instance())
        self.assertTrue(self.hits["show"].wait(2))


if __name__ == "__main__":
    unittest.main()
