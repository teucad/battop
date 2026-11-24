from battop.actions.base import Action

from .app_efficiency import AppEfficiencyAction
from .brightness import BrightnessAction
from .power_mode import PowerModeAction
from .power_settings import BatterySaverAction, CpuLimitAction


def default_actions() -> list[Action]:
    """All built-in actions, in the order they're applied (undone in reverse)."""
    return [
        PowerModeAction(),
        BrightnessAction(),
        CpuLimitAction(),
        BatterySaverAction(),
        AppEfficiencyAction(),
    ]
