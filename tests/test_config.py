import tempfile
import unittest
from pathlib import Path

from battop.config import Settings, SettingsStore


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


if __name__ == "__main__":
    unittest.main()
