"""Make sure only one Battop runs per user session."""

from __future__ import annotations

import sys

_handle = None  # Held for the life of the process (Windows mutex handle).


def acquire() -> bool:
    """True if we're the only instance."""
    global _handle
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        ctypes.set_last_error(0)
        _handle = kernel32.CreateMutexW(None, False, r"Local\BattopSingleInstance")
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    from .platforms.linux import single_instance

    return single_instance.acquire()
