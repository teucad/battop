from __future__ import annotations

import logging

from battop.actions.base import Action
from battop.i18n import _, N_

from .. import ps

log = logging.getLogger(__name__)

# Built-in laptop panels expose brightness through WMI; external monitors don't.
_GET = (
    "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop"
    " | Select-Object -First 1).CurrentBrightness"
)
_SET = (
    "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop"
    " | Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=0; Brightness={level}}}"
    " | Out-Null; " + _GET
)


def _brightness_command(command: str) -> int:
    output = ps.run(command)
    if not output.isdigit():
        raise OSError("screen brightness can't be controlled on this display")
    return int(output)


def get_brightness() -> int:
    return _brightness_command(_GET)


def set_brightness(level: int) -> int:
    """Set brightness and return the level the display actually settled on."""
    return _brightness_command(_SET.format(level=int(level)))


class BrightnessAction(Action):
    key = "brightness"
    title = N_("Dimmed screen")
    settings_keys = ("brightness_enabled", "brightness_percent")

    def apply(self, settings):
        previous = get_brightness()
        target = settings.brightness_percent
        if previous <= target:
            return None  # Only ever dim, never brighten.
        actual = set_brightness(target)
        log.info(_("Dimmed screen from %d%% to %d%%"), previous, actual)
        return {"previous": previous, "set_to": actual}

    def restore(self, saved):
        if get_brightness() != saved["set_to"]:
            log.info(_("You adjusted the brightness yourself, so Battop left it as is"))
            return
        set_brightness(saved["previous"])
        log.info(_("Screen brightness restored to %d%%"), saved["previous"])
