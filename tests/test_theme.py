import unittest

from battop import theme


class ThemeTests(unittest.TestCase):
    def test_palettes_define_the_same_keys(self):
        self.assertEqual(set(theme.LIGHT), set(theme.DARK))

    def test_text_is_readable_in_both_themes(self):
        for name, palette in theme.PALETTES.items():
            for fg, bg in theme.READABLE_PAIRS:
                ratio = theme.contrast(palette[fg], palette[bg])
                self.assertGreaterEqual(ratio, 4.5, f"{name}: {fg} on {bg} is only {ratio:.2f}:1")

    def test_contrast_formula(self):
        self.assertAlmostEqual(theme.contrast("#000000", "#ffffff"), 21.0, places=1)
        self.assertAlmostEqual(theme.contrast("#777777", "#777777"), 1.0)

    def test_resolve(self):
        self.assertEqual(theme.resolve("dark", "light"), "dark")
        self.assertEqual(theme.resolve("system", "dark"), "dark")
        self.assertEqual(theme.resolve("system", "unknown"), "light")


if __name__ == "__main__":
    unittest.main()
