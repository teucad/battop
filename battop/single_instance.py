"""Make sure only one Battop runs per user session."""

from __future__ import annotations

import ctypes

_ERROR_ALREADY_EXISTS = 183
_handle = None  # Held for the life of the process.


def acquire() -> bool:
    """True if we're the only instance."""
    global _handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    _handle = kernel32.CreateMutexW(None, False, r"Local\BattopSingleInstance")
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS
