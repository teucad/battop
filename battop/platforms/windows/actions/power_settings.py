"""Actions that tweak the battery-side values of power-scheme settings."""

from __future__ import annotations

import logging

from battop.actions.base import Action
from battop.i18n import _, N_

from .. import power

log = logging.getLogger(__name__)


class _DcValueAction(Action):
    """Sets one or more battery ("DC") values of the active power plan, then puts them back."""

    label: str
    unit = "%"

    def entries(self, settings) -> list[tuple[str, str, int]]:
        """(subgroup, setting, target value) for every value this action manages."""
        raise NotImplementedError

    def should_change(self, current: int, target: int) -> bool:
        return current != target

    def apply(self, settings):
        scheme = power.get_active_scheme()
        previous: dict[str, list] = {}
        for subgroup, setting, target in self.entries(settings):
            current = power.read_dc_value(scheme, subgroup, setting)
            if not self.should_change(current, target):
                continue
            power.write_dc_value(scheme, subgroup, setting, target)
            previous[setting] = [subgroup, current]
            log.info(_("%s: %d%s -> %d%s"), _(self.label), current, self.unit, target, self.unit)
        return {"scheme": scheme, "previous": previous} if previous else None

    def restore(self, saved):
        for setting, (subgroup, value) in saved["previous"].items():
            power.write_dc_value(saved["scheme"], subgroup, setting, value)
            log.info(_("%s restored to %d%s"), _(self.label), value, self.unit)


class CpuLimitAction(_DcValueAction):
    key = "cpu_limit"
    title = N_("Limited processor speed")
    settings_keys = ("cpu_limit_enabled", "cpu_max_percent")
    label = N_("Maximum processor speed")

    def entries(self, settings):
        return [(power.SUB_PROCESSOR, power.PROCESSOR_MAX_STATE, settings.cpu_max_percent)]

    def should_change(self, current, target):
        return current > target  # Never loosen a stricter limit the user set.


class BatterySaverAction(_DcValueAction):
    key = "battery_saver"
    title = N_("Earlier Windows battery saver")
    settings_keys = ("battery_saver_enabled", "battery_saver_threshold")
    label = N_("Battery saver turns on at")

    def entries(self, settings):
        return [(power.SUB_ENERGY_SAVER, power.ENERGY_SAVER_THRESHOLD, settings.battery_saver_threshold)]

    def should_change(self, current, target):
        return current < target  # Only make it kick in earlier, never later.


class TimeoutsAction(_DcValueAction):
    key = "timeouts"
    title = N_("Shorter screen-off and sleep times")
    settings_keys = ("timeouts_enabled", "screen_off_minutes", "sleep_minutes")
    label = N_("Idle timeout")
    unit = " s"

    def entries(self, settings):
        return [
            (power.SUB_VIDEO, power.VIDEO_IDLE, settings.screen_off_minutes * 60),
            (power.SUB_SLEEP, power.STANDBY_IDLE, settings.sleep_minutes * 60),
        ]

    def should_change(self, current, target):
        return current == 0 or current > target  # 0 means "never"; only ever shorten.
