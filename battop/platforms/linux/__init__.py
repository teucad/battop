from __future__ import annotations

import os
import subprocess

from ...i18n import _
from . import commands, desktop, events, helper_client, processes, single_instance, sysfs
from .actions import brightness, timeouts
from .actions.app_priority import AppPriorityAction
from .actions.bluetooth import BluetoothAction
from .actions.brightness import BacklightAction
from .actions.cpu_limit import CpuLimitAction
from .actions.power_profile import PowerProfileAction
from .actions.timeouts import GnomeTimeoutsAction

# These two need the root helper (the one-time "Set up…").
_HELPER_KEYS = frozenset({"cpu_limit", "app_efficiency"})


class LinuxPlatform:
    name = "linux"
    supported_keys = frozenset({"power_mode", "brightness", "timeouts", "bluetooth", "cpu_limit", "app_efficiency"})

    def init_process(self) -> None:
        pass

    power_status = staticmethod(sysfs.read_power_status)
    running_app_names = staticmethod(processes.running_process_names)
    autostart_enabled = staticmethod(desktop.autostart_enabled)
    set_autostart = staticmethod(desktop.set_autostart)

    def unavailable_reason(self, key: str) -> str | None:
        if key == "power_mode" and not commands.available("powerprofilesctl"):
            return _("Power profiles aren't available. Install power-profiles-daemon to use this.")
        if key == "brightness" and brightness.find_backlight() is None:
            return _("No controllable screen backlight was found.")
        if key == "timeouts" and not timeouts.available():
            return _("Changing screen-off and sleep times is only supported on GNOME.")
        if key == "bluetooth" and not commands.available("bluetoothctl"):
            return _("bluetoothctl isn't installed.")
        if key in _HELPER_KEYS and not helper_client.available():
            return _("This needs a one-time setup that asks for your administrator password.")
        return None

    def fix_action(self, key: str):
        if key in _HELPER_KEYS and not helper_client.available():
            return _("Set up…"), helper_client.install
        return None

    def warning(self, key: str) -> str | None:
        return None

    def actions(self):
        candidates = [
            PowerProfileAction(), BacklightAction(), CpuLimitAction(),
            GnomeTimeoutsAction(), BluetoothAction(), AppPriorityAction(),
        ]
        # Helper-backed actions stay in the list: they become usable once the helper is installed.
        return [a for a in candidates if a.key in _HELPER_KEYS or self.unavailable_reason(a.key) is None]

    def start_events(self, on_power_change, on_end_session, on_show, on_theme_change):
        listener = events.EventListener(on_power_change, on_end_session, on_theme_change)
        listener.start()
        stop_serving = single_instance.serve(on_show)

        def stop() -> None:
            listener.stop()
            stop_serving()

        return stop

    def signal_existing_instance(self) -> bool:
        return single_instance.signal_existing()

    def system_theme(self) -> str:
        try:
            if "dark" in commands.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"]):
                return "dark"
            if commands.run(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"]).lower().endswith("dark'"):
                return "dark"
        except OSError:
            pass
        return "light"

    def system_language(self) -> str:
        for variable in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
            value = os.environ.get(variable, "")
            if value:
                return value.split(":")[0].split(".")[0].split("_")[0].lower()
        return "en"

    def open_path(self, path) -> None:
        try:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass  # No file manager to open it with.

    def notify(self, title: str, message: str) -> bool:
        try:
            result = commands.run_raw(
                ["notify-send", "--app-name=Battop", "--icon=battery", title, message], timeout=5
            )
        except OSError:
            return False  # notify-send isn't installed: the tray icon is used instead.
        return result.returncode == 0

    def uninstall_extras(self) -> list[str]:
        return desktop.remove_entries()
