"""Autostart and application-menu entries (freedesktop .desktop files, no root)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from ...resources import resource_path

_ENTRY = """[Desktop Entry]
Type=Application
Name=Battop
Comment=Automatic battery saving
Exec={exec}
Icon={icon}
Terminal=false
Categories=Utility;System;
{extra}"""


def _home(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / fallback)


def autostart_path() -> Path:
    return _home("XDG_CONFIG_HOME", ".config") / "autostart" / "battop.desktop"


def menu_entry_path() -> Path:
    return _home("XDG_DATA_HOME", ".local/share") / "applications" / "battop.desktop"


def icon_path() -> Path:
    return _home("XDG_DATA_HOME", ".local/share") / "icons" / "hicolor" / "256x256" / "apps" / "battop.png"


def _quote(argument: str) -> str:
    """Quote one argument for a .desktop Exec line."""
    if argument and all(c.isalnum() or c in "-_./:=@%+" for c in argument):
        return argument
    escaped = argument.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'"{escaped}"'


def launch_command(*extra: str) -> str:
    return " ".join(_quote(part) for part in (sys.executable, "-m", "battop", *extra))


def autostart_enabled() -> bool:
    return autostart_path().exists()


def set_autostart(enabled: bool) -> None:
    path = autostart_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _ENTRY.format(exec=launch_command("--startup"), icon=_icon_name(), extra="X-GNOME-Autostart-enabled=true\n"),
        encoding="utf-8",
    )


def _icon_name() -> str:
    return "battop" if icon_path().exists() else str(resource_path("assets", "battop.png"))


def install_desktop_entry() -> None:
    """Add Battop to the application menu (with its icon)."""
    icon = icon_path()
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(resource_path("assets", "battop.png"), icon)
    entry = menu_entry_path()
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(_ENTRY.format(exec=launch_command(), icon="battop", extra=""), encoding="utf-8")


def remove_entries() -> list[str]:
    """Delete the autostart file, menu entry and icon. Returns problems (empty = all good)."""
    problems = []
    for path in (autostart_path(), menu_entry_path(), icon_path()):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            problems.append(f"{path}: {exc}")
    return problems
