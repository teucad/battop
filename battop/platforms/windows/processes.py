"""Process lookups shared by actions."""

from __future__ import annotations

from .actions.app_efficiency import iter_processes


def is_running(exe_name: str) -> bool:
    exe_name = exe_name.lower()
    return any(name.lower() == exe_name for _, name in iter_processes())
