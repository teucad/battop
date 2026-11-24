import ast
import json
import re
import unittest
from pathlib import Path

from battop import i18n

PACKAGE = Path(__file__).resolve().parent.parent / "battop"
CATALOG = PACKAGE / "locales" / "tr.json"
_PLACEHOLDER = re.compile(r"%(?:\([^)]+\))?[sdrf%]|\{[A-Za-z_]+\}")
# `_(x)` is allowed with a variable only when it is one of these (their values are all `N_("...")`).
_DYNAMIC_OK = {"title", "message", "label"}


def source_strings() -> tuple[dict[str, str], list[str]]:
    """Every literal passed to _() / N_() in the package, plus problems found while scanning."""
    found: dict[str, str] = {}
    problems: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "N_")):
                continue
            where = f"{path.relative_to(PACKAGE.parent)}:{node.lineno}"
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found[arg.value] = where
                continue
            name = arg.id if isinstance(arg, ast.Name) else arg.attr if isinstance(arg, ast.Attribute) else None
            if node.func.id == "_" and name in _DYNAMIC_OK:
                continue
            problems.append(f"{where}: {node.func.id}() needs a string literal (or one of {sorted(_DYNAMIC_OK)})")
    return found, problems


_BUILDERS = {"_toggle_card", "_slider_card", "_sliders_card", "_description"}
_DIALOGS = {"showinfo", "showwarning", "showerror", "askyesno"}
_UI_FILES = ("gui.py", "tray.py", "app.py")


def _looks_like_prose(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.search(r"[A-Za-z]", node.value) is not None
        and (" " in node.value or re.search(r"[A-Z]", node.value) is not None)
    )


def unwrapped_ui_strings() -> list[str]:
    """Strings passed straight to widgets/dialogs without _() (they would stay English)."""
    problems = []
    for name in _UI_FILES:
        path = PACKAGE / name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            callee = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            suspects = [kw.value for kw in node.keywords if kw.arg == "text"]
            if callee in _BUILDERS | _DIALOGS:
                suspects += list(node.args)
            for value in suspects:
                nodes = value.elts if isinstance(value, (ast.Tuple, ast.List)) else [value]
                for item in nodes:
                    if _looks_like_prose(item):
                        problems.append(f"{name}:{item.lineno}: {item.value[:50]!r}")
    return problems


def placeholders(text: str) -> list[str]:
    return sorted(_PLACEHOLDER.findall(text))


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.strings, cls.problems = source_strings()
        cls.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def test_translation_calls_use_literals(self):
        self.assertEqual(self.problems, [])

    def test_no_ui_strings_are_left_unwrapped(self):
        self.assertEqual(unwrapped_ui_strings(), [])

    def test_there_are_strings_to_translate(self):
        self.assertGreater(len(self.strings), 100)

    def test_every_string_has_a_turkish_translation(self):
        missing = [f"{where}: {text!r}" for text, where in self.strings.items() if not self.catalog.get(text, "").strip()]
        self.assertEqual(missing, [], "untranslated strings")

    def test_no_stale_translations(self):
        stale = [text for text in self.catalog if text not in self.strings]
        self.assertEqual(stale, [], "entries in tr.json that no code uses")

    def test_placeholders_match_the_english_text(self):
        bad = [
            f"{text!r} -> {translation!r}"
            for text, translation in self.catalog.items()
            if placeholders(text) != placeholders(translation)
        ]
        self.assertEqual(bad, [])

    def test_translations_are_not_just_copies_of_long_english_text(self):
        copies = [t for t, tr in self.catalog.items() if t == tr and len(t) > 40]
        self.assertEqual(copies, [], "long strings left in English")


class LookupTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_turkish_lookup_and_fallback(self):
        i18n.set_language("tr")
        self.assertEqual(i18n._("Dark"), "Koyu")
        self.assertEqual(i18n._("A string that is not in the catalog"), "A string that is not in the catalog")

    def test_english_is_a_passthrough(self):
        i18n.set_language("en")
        self.assertEqual(i18n._("Dark"), "Dark")

    def test_unknown_language_falls_back_to_english(self):
        i18n.set_language("xx")
        self.assertEqual(i18n.current_language(), "en")

    def test_every_language_has_a_name_and_a_catalog_file(self):
        for code in i18n.SUPPORTED:
            self.assertIn(code, i18n.LANGUAGE_NAMES)
            if code != "en":
                self.assertTrue((PACKAGE / "locales" / f"{code}.json").exists())


if __name__ == "__main__":
    unittest.main()
