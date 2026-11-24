import json
import sys
import tempfile
import unittest
from pathlib import Path

if sys.platform == "win32":
    from battop.platforms.windows import anime


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class PacketTests(unittest.TestCase):
    def test_every_packet_is_a_640_byte_report_with_id_5e(self):
        for data in (anime.WAKE_UP, anime.DISPLAY_ON, anime.END_OF_FRAME, anime.brightness_packet(2)):
            self.assertEqual(len(data), 640)
            self.assertEqual(data[0], 0x5E)

    def test_fixed_command_bytes(self):
        self.assertEqual(anime.WAKE_UP[1:15], b"ASUS Tech.Inc.")
        self.assertEqual(anime.DISPLAY_ON[:4], bytes([0x5E, 0xC3, 0x01, 0x00]))
        self.assertEqual(anime.BUILT_IN_ANIMATION_OFF[:4], bytes([0x5E, 0xC4, 0x01, 0x80]))
        self.assertEqual(anime.brightness_packet(3)[:4], bytes([0x5E, 0xC0, 0x04, 0x03]))
        self.assertEqual(anime.END_OF_FRAME[:3], bytes([0x5E, 0xC0, 0x03]))

    def test_brightness_is_validated(self):
        with self.assertRaises(ValueError):
            anime.brightness_packet(4)

    def test_frame_is_two_pages_plus_end_marker(self):
        leds = bytes(range(256)) * 4  # 1024 bytes; trim to a frame.
        leds = leds[: anime.LED_COUNT]
        pages = anime.frame_packets(leds)
        self.assertEqual(len(pages), 3)
        # Page 1: LEDs 0-489, address 1, length 490 (0x01EA), little-endian.
        self.assertEqual(pages[0][:7], bytes([0x5E, 0xC0, 0x02, 0x01, 0x00, 0xEA, 0x01]))
        self.assertEqual(pages[0][7:497], leds[:490])
        # Page 2: LEDs 490-809, address 491 (0x01EB), length 320 (0x0140).
        self.assertEqual(pages[1][:7], bytes([0x5E, 0xC0, 0x02, 0xEB, 0x01, 0x40, 0x01]))
        self.assertEqual(pages[1][7:327], leds[490:])
        self.assertEqual(pages[2], anime.END_OF_FRAME)

    def test_frame_size_is_validated(self):
        with self.assertRaises(ValueError):
            anime.frame_packets(bytes(100))


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class LayoutTests(unittest.TestCase):
    def test_row_table_matches_the_device_geometry(self):
        self.assertEqual(anime._ROW_START[29], 225)
        self.assertEqual(anime._ROW_START[30], 240)
        self.assertEqual(anime._ROW_START[67], 795)

    def test_whole_safe_canvas_maps_to_distinct_real_leds(self):
        indexes = [
            anime.led_index(anime.CANVAS_X + u, anime.CANVAS_Y + v)
            for u in range(anime.CANVAS_W)
            for v in range(anime.CANVAS_H)
        ]
        self.assertNotIn(None, indexes)
        self.assertEqual(len(set(indexes)), anime.CANVAS_W * anime.CANVAS_H)
        self.assertTrue(all(0 <= i < anime.LED_COUNT for i in indexes))

    def test_pixels_above_the_visible_rows_are_off_the_display(self):
        self.assertIsNone(anime.led_index(10, 0))
        self.assertIsNone(anime.led_index(10, 23))
        self.assertIsNone(anime.led_index(-50, 30))


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class RenderTests(unittest.TestCase):
    def test_battery_fits_the_canvas_for_every_percentage(self):
        for percent in range(101):
            for u, v in anime.battery_pixels(percent):
                self.assertTrue(0 <= u < anime.CANVAS_W and 0 <= v < anime.CANVAS_H, (percent, u, v))

    def test_rendering_lights_exactly_the_battery_pixels(self):
        for percent in (0, 1, 50, 64, 100):
            frame = anime.render_battery(percent)
            self.assertEqual(len(frame), anime.LED_COUNT)
            self.assertEqual(sum(1 for b in frame if b), len(anime.battery_pixels(percent)))

    def test_fill_grows_with_charge_and_is_visible_at_one_percent(self):
        counts = [len(anime.battery_pixels(p)) for p in (0, 1, 50)]
        self.assertLess(counts[0], counts[1])
        fills = [sum(1 for u, v in anime.battery_pixels(p) if 2 <= u <= 17 and 3 <= v <= 11) for p in (0, 1, 50, 100)]
        self.assertEqual(fills[0], 0)
        self.assertEqual(fills[1], 9)  # One column.
        self.assertEqual(fills[3], 16 * 9)
        self.assertLess(fills[2], fills[3])

    def test_out_of_range_percentages_are_clamped(self):
        self.assertEqual(anime.battery_pixels(150), anime.battery_pixels(100))
        self.assertEqual(anime.battery_pixels(-5), anime.battery_pixels(0))


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class GHelperConflictTests(unittest.TestCase):
    def check(self, config):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            if config is not None:
                path.write_text(json.dumps(config), encoding="utf-8")
            return anime.ghelper_conflict(path)

    def test_static_text_is_compatible(self):
        self.assertIsNone(self.check({"matrix_running": 5, "matrix_brightness": 3}))

    def test_missing_or_broken_config_is_not_a_problem(self):
        self.assertIsNone(self.check(None))

    def test_animated_modes_and_auto_off_are_flagged(self):
        self.assertIn("Clock", self.check({"matrix_running": 3}))
        self.assertIn("Audio", self.check({"matrix_running": 4}))
        self.assertIn("scrolling", self.check({"matrix_running": 5, "matrix_text_running": 1}))
        self.assertIn("turn the matrix off", self.check({"matrix_running": 5, "matrix_auto": 1}))
        self.assertIn("GIF", self.check({"matrix_running": 2}))

    def test_built_in_modes_are_compatible(self):
        self.assertIsNone(self.check({"matrix_running": 0}))
        self.assertIsNone(self.check({"matrix_running": 1}))


if __name__ == "__main__":
    unittest.main()
