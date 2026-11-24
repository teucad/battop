"""AniMe action tests. The device is a pure mock: nothing here may reach the real hardware."""

import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from battop.status import PowerStatus

if sys.platform == "win32":
    from battop.platforms.windows.actions import anime_battery


def status(on_battery=True, percent=64):
    return PowerStatus(on_battery, True, percent, None, False, False)


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class AnimeBatteryActionTests(unittest.TestCase):
    def setUp(self):
        self.current = status()
        self.matrix = mock.MagicMock()
        self.matrix.__enter__.return_value = self.matrix
        self.ghelper_running = True
        patchers = [
            mock.patch.object(anime_battery.anime, "AnimeMatrix", mock.MagicMock(open=mock.Mock(return_value=self.matrix))),
            mock.patch.object(anime_battery.anime, "ghelper_conflict", return_value=None),
            mock.patch.object(anime_battery.processes, "is_running", side_effect=lambda name: self.ghelper_running),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.action = anime_battery.AnimeBatteryAction(lambda: self.current)
        self.settings = SimpleNamespace(anime_brightness=2)

    def test_apply_takes_over_and_draws_the_current_charge(self):
        saved = self.action.apply(self.settings)
        self.matrix.start.assert_called_once_with(2)
        self.matrix.show_battery.assert_called_once_with(64)
        self.assertEqual(saved, {"ghelper_was_running": True})

    def test_refresh_redraws_every_time_to_beat_ghelper(self):
        self.current = status(percent=63)
        self.assertEqual(self.action.refresh(self.settings, {"x": 1}), {"x": 1})
        self.matrix.show_battery.assert_called_once_with(63)

    def test_refresh_survives_a_busy_device_and_warns_only_once(self):
        anime_battery.anime.AnimeMatrix.open.side_effect = OSError("busy")
        with self.assertLogs(anime_battery.log, "WARNING") as logs:
            for _ in range(3):
                self.assertEqual(self.action.refresh(self.settings, {}), {})
        self.assertEqual(len(logs.output), 1)

    def test_unknown_percentage_is_drawn_as_zero(self):
        self.current = PowerStatus(True, True, None, None, False, False)
        self.action.apply(self.settings)
        self.matrix.show_battery.assert_called_once_with(0)

    def test_plugging_in_hands_back_to_ghelper_without_touching_the_display(self):
        self.current = status(on_battery=False)
        self.action.restore({})
        anime_battery.anime.AnimeMatrix.open.assert_not_called()

    def test_plugging_in_without_ghelper_clears_the_display(self):
        self.current, self.ghelper_running = status(on_battery=False), False
        self.action.restore({})
        self.matrix.clear.assert_called_once()

    def test_pausing_while_unplugged_clears_the_stale_level(self):
        self.action.restore({})  # Still on battery; G-Helper wouldn't redraw.
        self.matrix.clear.assert_called_once()

    def test_asks_the_engine_for_frequent_refreshes(self):
        self.assertLessEqual(self.action.refresh_every_sec, 5)


if __name__ == "__main__":
    unittest.main()
