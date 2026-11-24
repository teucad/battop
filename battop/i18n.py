"""Translations. `_("English text")` returns the text in the active language.

Every user-facing string is written in English in the code and looked up in
`locales/<language>.json` (English text -> translation); unknown strings stay English.
`N_("text")` marks a string that is translated later, at the point where it is shown
(class-level titles, strings kept in tables).
"""

from __future__ import annotations

import json
import logging

from .resources import resource_path

log = logging.getLogger(__name__)

SUPPORTED = ("en", "tr")
# Each language is listed under its own name, so people can find theirs.
LANGUAGE_NAMES = {"en": "English", "tr": "Türkçe"}

_catalog: dict[str, str] = {}
_language = "en"


def N_(text: str) -> str:
    """Mark a string for translation without translating it yet."""
    return text


def _(text: str) -> str:
    return _catalog.get(text, text)


def load_catalog(language: str) -> dict[str, str]:
    if language == "en":
        return {}
    try:
        data = json.loads(resource_path("locales", f"{language}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Couldn't load the %s translation (%s); using English", language, exc)
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}


def set_language(language: str) -> None:
    global _catalog, _language
    _language = language if language in SUPPORTED else "en"
    _catalog = load_catalog(_language)


def current_language() -> str:
    return _language


def resolve(setting: str, system_language: str) -> str:
    """'en' or 'tr' for a language setting of 'system', 'en' or 'tr'."""
    if setting in SUPPORTED:
        return setting
    return system_language if system_language in SUPPORTED else "en"
