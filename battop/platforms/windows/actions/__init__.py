from battop.actions.base import Action

from .app_efficiency import AppEfficiencyAction
from .bluetooth import BluetoothAction
from .brightness import BrightnessAction
from .power_mode import PowerModeAction, PowerPlanAction
from .power_settings import BatterySaverAction, CpuLimitAction, TimeoutsAction
from .refresh_rate import RefreshRateAction


def default_actions() -> list[Action]:
    """All built-in actions, in the order they're applied (undone in reverse)."""
    return [
        PowerPlanAction(),  # First, so later actions write to the plan that stays active.
        PowerModeAction(),
        BrightnessAction(),
        RefreshRateAction(),
        CpuLimitAction(),
        BatterySaverAction(),
        TimeoutsAction(),
        BluetoothAction(),
        AppEfficiencyAction(),
    ]
