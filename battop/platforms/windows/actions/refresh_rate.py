from __future__ import annotations

import logging

from battop.actions.base import Action

from .. import display

log = logging.getLogger(__name__)

_MIN_HZ = 60  # Lower than this tends to look flickery or isn't offered anyway.


class RefreshRateAction(Action):
    key = "refresh_rate"
    title = "Lower screen refresh rate"
    settings_keys = ("refresh_rate_enabled",)

    def apply(self, settings):
        device = display.primary_display()
        current = display.current_mode(device)
        rates = [hz for hz in display.supported_rates(device, current) if hz >= _MIN_HZ]
        if not rates or current.dmDisplayFrequency <= min(rates):
            return None
        target = min(rates)
        display.set_refresh_rate(device, target)
        log.info("Screen refresh rate: %d Hz -> %d Hz", current.dmDisplayFrequency, target)
        return {"device": device, "previous": current.dmDisplayFrequency, "set_to": target}

    def restore(self, saved):
        device = saved["device"]
        if display.current_mode(device).dmDisplayFrequency != saved["set_to"]:
            log.info("The refresh rate was changed by something else, so Battop left it as is")
            return
        display.set_refresh_rate(device, saved["previous"])
        log.info("Screen refresh rate restored to %d Hz", saved["previous"])
