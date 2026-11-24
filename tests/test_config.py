import tempfile
import unittest
from pathlib import Path

from battop.config import Settings, SettingsStore, effective


class SettingsTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SettingsStore(Path(tmp) / "settings.json")
            original = Settings(brightness_percent=55, efficiency_apps=("discord.exe",))
            store.save(original)
            self.assertEqual(store.load(), original)

    def test_missing_or_corrupt_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            self.assertEqual(SettingsStore(path).load(), Settings())
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(SettingsStore(path).load(), Settings())

    def test_invalid_values_are_ignored_or_clamped(self):
        settings = Settings.from_dict(
            {"brightness_percent": 500, "cpu_max_percent": True, "enabled": "yes", "unknown": 1}
        )
        self.assertEqual(settings.brightness_percent, 100)
        self.assertEqual(settings.cpu_max_percent, Settings().cpu_max_percent)
        self.assertTrue(settings.enabled)

    def test_app_names_are_normalized(self):
        settings = Settings.from_dict({"efficiency_apps": [" Discord ", "discord.exe", "", "Steam.EXE"]})
        self.assertEqual(settings.efficiency_apps, ("discord.exe", "steam.exe"))

    def test_effective_only_changes_anything_while_low(self):
        base = Settings(brightness_enabled=False, brightness_percent=50, cpu_limit_enabled=False)
        self.assertIs(effective(base, False), base)
        low = effective(base, True)
        self.assertTrue(low.brightness_enabled)
        self.assertEqual(low.brightness_percent, base.low_brightness_percent)
        self.assertTrue(low.cpu_limit_enabled)
        self.assertEqual(low.cpu_max_percent, base.low_cpu_max_percent)

    def test_effective_keeps_stricter_user_values(self):
        base = Settings(brightness_percent=10, cpu_limit_enabled=True, cpu_max_percent=40)
        low = effective(base, True)
        self.assertEqual((low.brightness_percent, low.cpu_max_percent), (10, 40))

    def test_effective_respects_disabled_tier(self):
        base = Settings(low_tier_enabled=False)
        self.assertIs(effective(base, True), base)

    def test_new_numeric_settings_are_clamped(self):
        s = Settings.from_dict({"screen_off_minutes": 0, "sleep_minutes": 9999, "low_tier_threshold": 99})
        self.assertEqual((s.screen_off_minutes, s.sleep_minutes, s.low_tier_threshold), (1, 120, 50))


if __name__ == "__main__":
    unittest.main()
