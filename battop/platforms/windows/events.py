"""Hidden window that turns Windows messages into callbacks.

Handles: power-source changes and resume from sleep, sign-out/shutdown, dark/light
theme changes, and a "show yourself" ping from a second Battop launch.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes

from .power import GUID

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CLASS_NAME = "BattopEventWindow"
WM_SETTINGCHANGE = 0x001A
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_POWERBROADCAST = 0x0218
WM_CLOSE = 0x0010
WM_APP_SHOW = 0x8000 + 1  # WM_APP + 1
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_POWERSETTINGCHANGE = 0x8013
GUID_ACDC_POWER_SOURCE = "5d3e9a59-e9d5-4b00-a6bd-ff34ff516548"
GUID_BATTERY_PERCENTAGE_REMAINING = "a7ad8041-b45a-4cae-87a3-eecbb468a9e1"

LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = LRESULT
_user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
_user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
_user32.RegisterPowerSettingNotification.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.DWORD]
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.FindWindowW.restype = wintypes.HWND
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE


def signal_existing_instance() -> bool:
    """Ask a running Battop to show its window. False if none was found."""
    hwnd = _user32.FindWindowW(CLASS_NAME, None)
    return bool(hwnd and _user32.PostMessageW(hwnd, WM_APP_SHOW, 0, 0))


def _noop() -> None:
    pass


# The window class is registered once per process, so its procedure can't belong to one
# EventWindow: it looks the owner up by window handle instead.
_owners: dict[int, EventWindow] = {}


def _dispatch(hwnd, msg, wparam, lparam):
    owner = _owners.get(hwnd)
    if owner is None:  # Messages sent while the window is still being created.
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    return owner._handle(hwnd, msg, wparam, lparam)


_wndproc = _WNDPROC(_dispatch)  # Module-level so it is never garbage collected.


class EventWindow:
    """Runs a hidden window on its own thread. All callbacks run on that thread."""

    def __init__(
        self,
        on_power_change: Callable[[], None] = _noop,
        on_end_session: Callable[[], None] = _noop,
        on_theme_change: Callable[[], None] = _noop,
        on_show: Callable[[], None] = _noop,
    ):
        self._on_power_change = on_power_change
        self._on_end_session = on_end_session
        self._on_theme_change = on_theme_change
        self._on_show = on_show
        self._hwnd = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="battop-events", daemon=True)

    def start(self) -> bool:
        """Start listening. Returns False if the window couldn't be created."""
        self._thread.start()
        self._ready.wait(5)
        return self._hwnd is not None

    def stop(self) -> None:
        if self._hwnd:
            _user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            self._thread.join(timeout=2)

    def _run(self) -> None:
        hinstance = _kernel32.GetModuleHandleW(None)
        wc = _WNDCLASSW()
        wc.lpfnWndProc = _wndproc
        wc.hInstance = hinstance
        wc.lpszClassName = CLASS_NAME
        if not _user32.RegisterClassW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:  # Already registered.
            log.debug("RegisterClassW failed: %s", ctypes.WinError(ctypes.get_last_error()))
            self._ready.set()
            return
        # A hidden top-level window (not message-only) so it also receives broadcast messages.
        hwnd = _user32.CreateWindowExW(0, CLASS_NAME, "Battop", 0, 0, 0, 0, 0, None, None, hinstance, None)
        if not hwnd:
            log.debug("CreateWindowExW failed: %s", ctypes.WinError(ctypes.get_last_error()))
            self._ready.set()
            return
        self._hwnd = hwnd
        _owners[hwnd] = self
        for guid in (GUID_ACDC_POWER_SOURCE, GUID_BATTERY_PERCENTAGE_REMAINING):
            if not _user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(GUID.from_str(guid)), 0):
                log.debug("RegisterPowerSettingNotification(%s) failed", guid)
        self._ready.set()
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _handle(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_POWERBROADCAST and wparam in (PBT_POWERSETTINGCHANGE, PBT_APMRESUMEAUTOMATIC):
                self._on_power_change()
            elif msg == WM_SETTINGCHANGE and lparam:
                if ctypes.wstring_at(lparam) == "ImmersiveColorSet":
                    self._on_theme_change()
            elif msg == WM_QUERYENDSESSION:
                return 1  # Don't block shutdown.
            elif msg == WM_ENDSESSION and wparam:
                self._on_end_session()
                return 0
            elif msg == WM_APP_SHOW:
                self._on_show()
                return 0
            elif msg == WM_CLOSE:
                _owners.pop(hwnd, None)
                _user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("Error while handling window message 0x%04x", msg)
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
