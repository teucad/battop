from __future__ import annotations

import logging

from battop.actions.base import Action
from battop.i18n import N_, _

from .. import commands

log = logging.getLogger(__name__)

SCREEN = ("org.gnome.desktop.session", "idle-delay")  # Seconds until the screen blanks; 0 = never.
SLEEP = ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-timeout")
SLEEP_TYPE = ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type")


def get_value(schema: str, key: str) -> str:
    return commands.run(["gsettings", "get", schema, key]).strip("'\" ")


def get_seconds(schema: str, key: str) -> int:
    """gsettings prints e.g. 'uint32 300' or '300': the number is the last word."""
    try:
        return int(get_value(schema, key).split()[-1])
    except (ValueError, IndexError):
        raise OSError(f"unexpected value for {schema} {key}") from None


def available() -> bool:
    try:
        commands.run(["gsettings", "get", *SCREEN])
        commands.run(["gsettings", "get", *SLEEP])
        return True
    except OSError:
        return False


class GnomeTimeoutsAction(Action):
    """Shortens the screen-blank and sleep delays on battery (GNOME's settings)."""

    key = "timeouts"
    title = N_("Shorter screen-off and sleep times")
    settings_keys = ("timeouts_enabled", "screen_off_minutes", "sleep_minutes")

    def apply(self, settings):
        wanted = [(SCREEN, settings.screen_off_minutes * 60)]
        if get_value(*SLEEP_TYPE) != "nothing":  # With "nothing" the timeout is unused; leave it alone.
            wanted.append((SLEEP, settings.sleep_minutes * 60))
        changed: dict[str, list] = {}
        for (schema, key), target in wanted:
            current = get_seconds(schema, key)
            if current != 0 and current <= target:  # 0 means "never"; only ever shorten.
                continue
            commands.run(["gsettings", "set", schema, key, str(target)])
            changed[f"{schema} {key}"] = [schema, key, current, target]
            log.info(_("Idle timeout %s: %d s -> %d s"), key, current, target)
        return {"changed": changed} if changed else None

    def restore(self, saved):
        for schema, key, previous, set_to in saved["changed"].values():
            if get_seconds(schema, key) != set_to:
                continue  # Changed by the user since; leave it.
            commands.run(["gsettings", "set", schema, key, str(previous)])
            log.info(_("Idle timeout %s restored to %d s"), key, previous)
