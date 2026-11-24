from __future__ import annotations

import ctypes
import os
import winreg

from ...i18n import _
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
            return _("Windows is already set to use Best power efficiency whenever you're on battery.")
        return _(
            "Windows keeps a separate power mode for battery, which Battop can't safely switch "
            "back afterwards. Change it in Settings › System › Power & battery."
        )

    def fix_action(self, key: str):
        if key == "power_mode" and self.unavailable_reason(key):
            return _("Open power settings"), lambda: os.startfile("ms-settings:powersleep")
        return None

    open_path = staticmethod(os.startfile)

    def notify(self, title: str, message: str) -> bool:
        return False  # The tray icon's balloon is used.

    def uninstall_extras(self) -> list[str]:
        return []

    def actions(self):
        blocked = self.unavailable_reason("power_mode") is not None
        actions = [a for a in default_actions() if not (blocked and a.key == "power_mode")]
        if self.has_anime_matrix:
            actions.append(AnimeBatteryAction(power.get_power_status))
        return actions

    def warning(self, key: str) -> str | None:
        return anime.ghelper_conflict() if key == "anime_battery" else None

    def start_events(self, on_power_change, on_end_session, on_show, on_theme_change):
        window = events.EventWindow(
            on_power_change=on_power_change,
            on_end_session=on_end_session,
            on_show=on_show,
            on_theme_change=on_theme_change,
        )
        window.start()  # If it fails we just fall back to polling.
        return window.stop

    signal_existing_instance = staticmethod(events.signal_existing_instance)

    def system_language(self) -> str:
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF  # Primary language ID.
        return {0x1F: "tr", 0x09: "en"}.get(primary, "en")

    def system_theme(self) -> str:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as key:
                return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
        except OSError:
            return "light"
