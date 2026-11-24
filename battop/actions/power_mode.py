from __future__ import annotations

import logging

from .. import power
from .base import Action

log = logging.getLogger(__name__)


class PowerModeAction(Action):
    key = "power_mode"
    title = "Best power efficiency mode"
    settings_keys = ("power_mode_enabled",)

    def apply(self, settings):
        previous = power.get_power_mode()
        if previous == power.MODE_BEST_EFFICIENCY:
            return None
        power.set_power_mode(power.MODE_BEST_EFFICIENCY)
        log.info("Switched power mode from %s to Best power efficiency", power.mode_name(previous))
        return {"previous": previous}

    def restore(self, saved):
        # Windows 11 can keep separate modes for battery and plugged-in, and
        # may already have switched by itself; only undo our own change.
        if power.get_power_mode() != power.MODE_BEST_EFFICIENCY:
            return
        power.set_power_mode(saved["previous"])
        log.info("Power mode restored to %s", power.mode_name(saved["previous"]))
