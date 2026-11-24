"""Actions that tweak the battery-side value of a power-scheme setting."""

from __future__ import annotations

import logging

from .. import power
from .base import Action

log = logging.getLogger(__name__)


class _DcValueAction(Action):
    subgroup: str
    setting: str
    label: str

    def target(self, settings) -> int:
        raise NotImplementedError

    def should_change(self, current: int, target: int) -> bool:
        return current != target

    def apply(self, settings):
        scheme = power.get_active_scheme()
        previous = power.read_dc_value(scheme, self.subgroup, self.setting)
        target = self.target(settings)
        if not self.should_change(previous, target):
            return None
        power.write_dc_value(scheme, self.subgroup, self.setting, target)
        log.info("%s: %d%% -> %d%%", self.label, previous, target)
        return {"scheme": scheme, "previous": previous}

    def restore(self, saved):
        power.write_dc_value(saved["scheme"], self.subgroup, self.setting, saved["previous"])
        log.info("%s restored to %d%%", self.label, saved["previous"])


class CpuLimitAction(_DcValueAction):
    key = "cpu_limit"
    title = "Limited processor speed"
    settings_keys = ("cpu_limit_enabled", "cpu_max_percent")
    subgroup = power.SUB_PROCESSOR
    setting = power.PROCESSOR_MAX_STATE
    label = "Maximum processor speed"

    def target(self, settings):
        return settings.cpu_max_percent

    def should_change(self, current, target):
        return current > target  # Never loosen a stricter limit the user set.


class BatterySaverAction(_DcValueAction):
    key = "battery_saver"
    title = "Earlier Windows battery saver"
    settings_keys = ("battery_saver_enabled", "battery_saver_threshold")
    subgroup = power.SUB_ENERGY_SAVER
    setting = power.ENERGY_SAVER_THRESHOLD
    label = "Battery saver turns on at"

    def target(self, settings):
        return settings.battery_saver_threshold

    def should_change(self, current, target):
        return current < target  # Only make it kick in earlier, never later.
