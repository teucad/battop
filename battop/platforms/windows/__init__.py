from __future__ import annotations

import ctypes

from . import autostart, power
from .actions import default_actions
from .actions.app_efficiency import running_process_names


class WindowsPlatform:
    name = "windows"
    supported_keys = frozenset(
        {"power_mode", "brightness", "cpu_limit", "battery_saver", "app_efficiency"}
    )

    def init_process(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Crisp text on high-DPI screens.
        except (AttributeError, OSError):
            pass

    power_status = staticmethod(power.get_power_status)
    actions = staticmethod(default_actions)
    running_app_names = staticmethod(running_process_names)
    autostart_enabled = staticmethod(autostart.is_enabled)
    set_autostart = staticmethod(autostart.set_enabled)

    def unavailable_reason(self, key: str) -> str | None:
        return None
