from __future__ import annotations

import logging

from .. import power
from battop.actions.base import Action

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


class PowerPlanAction(Action):
    """For people who use a custom power plan, where Windows' power mode doesn't apply."""

    key = "power_plan"
    title = "Power saver plan"
    settings_keys = ("power_mode_enabled",)

    def apply(self, settings):
        previous = power.get_active_scheme()
        if previous in (power.SCHEME_BALANCED, power.SCHEME_POWER_SAVER):
            return None  # Balanced is handled by PowerModeAction.
        try:
            power.set_active_scheme(power.SCHEME_POWER_SAVER)
        except OSError as exc:
            log.info("No Power saver plan to switch to (%s)", exc)
            return None
        log.info("Switched power plan from %s to Power saver", previous)
        return {"previous": previous}

    def restore(self, saved):
        if power.get_active_scheme() != power.SCHEME_POWER_SAVER:
            return  # The user picked a plan themselves.
        power.set_active_scheme(saved["previous"])
        log.info("Power plan restored")
