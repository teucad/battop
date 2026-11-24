"""Put chosen apps into Windows "Efficiency mode" (the Task Manager feature)."""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes

from battop.actions.base import Action

log = logging.getLogger(__name__)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.OpenProcess.restype = wintypes.HANDLE

_TH32CS_SNAPPROCESS = 0x2
_INVALID_HANDLE = wintypes.HANDLE(-1).value
_PROCESS_SET_INFORMATION = 0x0200
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_POWER_THROTTLING = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
_THROTTLE_EXECUTION_SPEED = 0x1
_IDLE_PRIORITY_CLASS = 0x40


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.ULONG),
        ("ControlMask", wintypes.ULONG),
        ("StateMask", wintypes.ULONG),
    ]


def iter_processes():
    """Yield (pid, exe name) for every running process."""
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot in (None, _INVALID_HANDLE):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            yield entry.th32ProcessID, entry.szExeFile
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(wintypes.HANDLE(snapshot))


def running_process_names() -> list[str]:
    return sorted({name.lower() for pid, name in iter_processes() if pid > 4})


def _set_efficiency(pid: int, on: bool, priority: int | None = None) -> int:
    """Turn efficiency mode on/off for a process; returns its previous priority class."""
    handle = _kernel32.OpenProcess(
        _PROCESS_SET_INFORMATION | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    handle = wintypes.HANDLE(handle)
    try:
        mask = _THROTTLE_EXECUTION_SPEED if on else 0
        state = _PROCESS_POWER_THROTTLING_STATE(1, mask, mask)
        if not _kernel32.SetProcessInformation(
            handle, _PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        previous = _kernel32.GetPriorityClass(handle)
        new_priority = _IDLE_PRIORITY_CLASS if on else priority
        if new_priority and not _kernel32.SetPriorityClass(handle, new_priority):
            raise ctypes.WinError(ctypes.get_last_error())
        return previous
    finally:
        _kernel32.CloseHandle(handle)


class AppEfficiencyAction(Action):
    key = "app_efficiency"
    title = "Apps in efficiency mode"
    settings_keys = ("app_efficiency_enabled", "efficiency_apps")

    def apply(self, settings):
        # Always returns undo data so `refresh` keeps catching newly started apps.
        return self.refresh(settings, {"processes": {}})

    def refresh(self, settings, saved):
        targets = set(settings.efficiency_apps)
        known = saved["processes"]
        if not targets:
            return saved
        updated = dict(known)
        for pid, name in iter_processes():
            name = name.lower()
            if name not in targets or str(pid) in known or pid == os.getpid():
                continue
            try:
                priority = _set_efficiency(pid, on=True)
            except OSError as exc:
                log.debug("Can't throttle %s (pid %d): %s", name, pid, exc)
                updated[str(pid)] = None  # Don't retry every few seconds.
                continue
            updated[str(pid)] = {"name": name, "priority": priority}
            log.info("Put %s into efficiency mode", name)
        return {"processes": updated} if updated != known else saved

    def restore(self, saved):
        running = {str(pid): name.lower() for pid, name in iter_processes()}
        restored = set()
        for pid, info in saved["processes"].items():
            # Skip failures, exited apps and recycled process IDs.
            if info is None or running.get(pid) != info["name"]:
                continue
            try:
                _set_efficiency(int(pid), on=False, priority=info["priority"])
                restored.add(info["name"])
            except OSError as exc:
                log.debug("Can't restore %s (pid %s): %s", info["name"], pid, exc)
        if restored:
            log.info("Took %s out of efficiency mode", ", ".join(sorted(restored)))
