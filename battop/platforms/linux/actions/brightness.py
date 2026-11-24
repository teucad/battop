from __future__ import annotations

import logging
from pathlib import Path

from battop.actions.base import Action
from battop.i18n import N_, _

from .. import commands, sysfs

log = logging.getLogger(__name__)

# Prefer the interface the firmware/ACPI exposes over raw hardware registers.
_TYPE_ORDER = {"firmware": 0, "platform": 1, "raw": 2}


def find_backlight(root: Path | None = None) -> str | None:
    """Name of the laptop panel's backlight device, or None."""
    base = (root or sysfs.sysfs_root()) / "class" / "backlight"
    try:
        candidates = sorted(base.iterdir())
    except OSError:
        return None
    usable = [d for d in candidates if (_number(d / "max_brightness") or 0) > 0]
    usable.sort(key=lambda d: _TYPE_ORDER.get((_text(d / "type") or ""), 3))
    return usable[0].name if usable else None


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _number(path: Path) -> int | None:
    text = _text(path)
    return int(text) if text and text.isdigit() else None


def read_brightness(device: str) -> tuple[int, int]:
    """(current, maximum) raw values."""
    folder = sysfs.sysfs_root() / "class" / "backlight" / device
    current, maximum = _number(folder / "brightness"), _number(folder / "max_brightness")
    if current is None or not maximum:
        raise OSError(f"can't read the brightness of {device}")
    return current, maximum


def set_brightness(device: str, value: int) -> int:
    """Set the raw brightness through systemd-logind (allowed for the active session, no root)."""
    commands.run([
        "busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
        "org.freedesktop.login1.Session", "SetBrightness", "ssu", "backlight", device, str(value),
    ])
    return read_brightness(device)[0]


class BacklightAction(Action):
    key = "brightness"
    title = N_("Dimmed screen")
    settings_keys = ("brightness_enabled", "brightness_percent")

    def apply(self, settings):
        device = find_backlight()
        if device is None:
            return None
        current, maximum = read_brightness(device)
        previous_percent = round(100 * current / maximum)
        if previous_percent <= settings.brightness_percent:
            return None  # Only ever dim, never brighten.
        target = max(1, round(maximum * settings.brightness_percent / 100))  # 0 can mean "off" on some panels.
        actual = set_brightness(device, target)
        log.info(_("Dimmed screen from %d%% to %d%%"), previous_percent, round(100 * actual / maximum))
        return {"device": device, "previous": current, "set_to": actual}

    def restore(self, saved):
        if read_brightness(saved["device"])[0] != saved["set_to"]:
            log.info(_("You adjusted the brightness yourself, so Battop left it as is"))
            return
        current, maximum = read_brightness(saved["device"])
        set_brightness(saved["device"], saved["previous"])
        log.info(_("Screen brightness restored to %d%%"), round(100 * saved["previous"] / maximum))
