from __future__ import annotations

import ctypes

from . import anime, autostart, events, power
from .actions import default_actions
from .actions.anime_battery import AnimeBatteryAction
from .actions.app_efficiency import running_process_names


class WindowsPlatform:
    name = "windows"
    _BASE_KEYS = frozenset(
        {
            "power_mode", "brightness", "cpu_limit", "battery_saver", "app_efficiency",
            "refresh_rate", "timeouts", "bluetooth",
        }
    )

    def __init__(self):
        self.has_anime_matrix = anime.is_present()
        self.supported_keys = self._BASE_KEYS | ({"anime_battery"} if self.has_anime_matrix else frozenset())

    def init_process(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Crisp text on high-DPI screens.
        except (AttributeError, OSError):
            pass

    power_status = staticmethod(power.get_power_status)
    running_app_names = staticmethod(running_process_names)
    autostart_enabled = staticmethod(autostart.is_enabled)
    set_autostart = staticmethod(autostart.set_enabled)

    def unavailable_reason(self, key: str) -> str | None:
        if key != "power_mode" or power.get_active_scheme() != power.SCHEME_BALANCED:
            return None  # (On other plans the Power saver fallback is used.)
        dc = power.get_dc_overlay()
        if dc is None:
            return None
        if dc == power.MODE_BEST_EFFICIENCY:
            return "Windows is already set to use Best power efficiency whenever you're on battery."
        return (
            "Windows keeps a separate power mode for battery, which Battop can't safely switch "
            "back afterwards. Change it in Settings › System › Power & battery."
        )

    def actions(self):
        blocked = self.unavailable_reason("power_mode") is not None
        actions = [a for a in default_actions() if not (blocked and a.key == "power_mode")]
        if self.has_anime_matrix:
            actions.append(AnimeBatteryAction(power.get_power_status))
        return actions

    def warning(self, key: str) -> str | None:
        return anime.ghelper_conflict() if key == "anime_battery" else None

    def start_events(self, on_power_change, on_end_session, on_show):
        window = events.EventWindow(
            on_power_change=on_power_change, on_end_session=on_end_session, on_show=on_show
        )
        window.start()  # If it fails we just fall back to polling.
        return window.stop

    signal_existing_instance = staticmethod(events.signal_existing_instance)
