"""User settings, persisted as JSON under %APPDATA%\\Battop."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

log = logging.getLogger(__name__)

# (min, max) for every numeric setting; values outside are clamped on load/save.
_RANGES = {
    "poll_interval_sec": (2, 300),
    "brightness_percent": (5, 100),
    "cpu_max_percent": (30, 100),
    "battery_saver_threshold": (0, 100),
    "screen_off_minutes": (1, 60),
    "sleep_minutes": (1, 120),
    "low_tier_threshold": (5, 50),
    "low_brightness_percent": (5, 100),
    "low_cpu_max_percent": (30, 100),
}


def data_dir() -> Path:
    path = Path(os.environ.get("APPDATA") or Path.home()) / "Battop"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class Settings:
    # Master switch: when False, Battop only watches and never changes anything.
    enabled: bool = True
    # Power events wake the engine instantly; polling is only a fallback.
    poll_interval_sec: int = 30

    # Each action's on/off toggle comes first, followed by its parameters.
    power_mode_enabled: bool = True
    brightness_enabled: bool = True
    brightness_percent: int = 40
    cpu_limit_enabled: bool = False
    cpu_max_percent: int = 80
    battery_saver_enabled: bool = True
    battery_saver_threshold: int = 30
    refresh_rate_enabled: bool = False
    timeouts_enabled: bool = False
    screen_off_minutes: int = 3
    sleep_minutes: int = 10
    bluetooth_enabled: bool = False
    app_efficiency_enabled: bool = False
    efficiency_apps: tuple[str, ...] = field(default_factory=tuple)

    # Extra savings once the charge drops to `low_tier_threshold` (see `effective`).
    low_tier_enabled: bool = True
    low_tier_threshold: int = 20
    low_brightness_percent: int = 20
    low_cpu_max_percent: int = 60

    # Stay hidden in the tray when launched automatically at sign-in.
    start_minimized: bool = True
    notifications: bool = True

    def normalized(self) -> Settings:
        """Return a copy with numbers clamped and app names cleaned up."""
        changes: dict = {
            name: min(max(getattr(self, name), lo), hi) for name, (lo, hi) in _RANGES.items()
        }
        changes["efficiency_apps"] = normalize_app_names(self.efficiency_apps)
        return replace(self, **changes)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["efficiency_apps"] = list(self.efficiency_apps)
        return data

    @classmethod
    def from_dict(cls, raw: dict) -> Settings:
        """Build settings from JSON, ignoring unknown keys and wrongly-typed values."""
        defaults = cls()
        kwargs = {}
        for f in fields(cls):
            if f.name not in raw:
                continue
            value = raw[f.name]
            expected = type(getattr(defaults, f.name))
            if expected is tuple:
                if isinstance(value, list) and all(isinstance(v, str) for v in value):
                    kwargs[f.name] = tuple(value)
            elif expected is int:
                if isinstance(value, int) and not isinstance(value, bool):
                    kwargs[f.name] = value
            elif isinstance(value, expected):
                kwargs[f.name] = value
            else:
                log.warning("Ignoring invalid value for %s: %r", f.name, value)
        return cls(**kwargs).normalized()


def effective(settings: Settings, low: bool) -> Settings:
    """The settings the actions should use right now.

    While the battery is low, the screen is dimmed further and the processor limit is
    forced on. Anything the user already set stricter is kept.
    """
    if not (low and settings.low_tier_enabled):
        return settings
    cpu_max = settings.cpu_max_percent if settings.cpu_limit_enabled else 100
    return replace(
        settings,
        brightness_percent=min(settings.brightness_percent, settings.low_brightness_percent),
        cpu_limit_enabled=True,
        cpu_max_percent=min(cpu_max, settings.low_cpu_max_percent),
    )


def normalize_app_names(names) -> tuple[str, ...]:
    """Lower-case, add '.exe' where missing, drop blanks and duplicates (order kept)."""
    result: list[str] = []
    for name in names:
        name = name.strip().lower()
        if not name:
            continue
        if not name.endswith(".exe"):
            name += ".exe"
        if name not in result:
            result.append(name)
    return tuple(result)


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "settings.json"

    def load(self) -> Settings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Settings()
        except (OSError, ValueError) as exc:
            log.warning("Couldn't read settings (%s); using defaults", exc)
            return Settings()
        if not isinstance(raw, dict):
            return Settings()
        return Settings.from_dict(raw)

    def save(self, settings: Settings) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(self.path)
