"""Read and change the primary display's refresh rate (user32)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)

ENUM_CURRENT_SETTINGS = -1
DM_DISPLAYFREQUENCY = 0x400000
CDS_TEST = 0x2
DISP_CHANGE_SUCCESSFUL = 0
_DISPLAY_DEVICE_PRIMARY = 0x4


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        # Printer / display union: the display variant is used here.
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


_user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
_user32.ChangeDisplaySettingsExW.argtypes = [
    wintypes.LPCWSTR, ctypes.POINTER(DEVMODEW), wintypes.HWND, wintypes.DWORD, wintypes.LPVOID,
]
_user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_DISPLAY_DEVICEW), wintypes.DWORD]


def _new_devmode() -> DEVMODEW:
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    return mode


def primary_display() -> str:
    device = _DISPLAY_DEVICEW()
    device.cb = ctypes.sizeof(device)
    index = 0
    while _user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
        if device.StateFlags & _DISPLAY_DEVICE_PRIMARY:
            return device.DeviceName
        index += 1
    raise OSError("no primary display found")


def current_mode(device: str) -> DEVMODEW:
    mode = _new_devmode()
    if not _user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(mode)):
        raise OSError("couldn't read the display settings")
    return mode


def supported_rates(device: str, like: DEVMODEW) -> list[int]:
    """Refresh rates (Hz) available at the same resolution and colour depth as `like`."""
    rates = set()
    index = 0
    mode = _new_devmode()
    while _user32.EnumDisplaySettingsW(device, index, ctypes.byref(mode)):
        if (mode.dmPelsWidth, mode.dmPelsHeight, mode.dmBitsPerPel) == (
            like.dmPelsWidth, like.dmPelsHeight, like.dmBitsPerPel,
        ):
            rates.add(mode.dmDisplayFrequency)
        index += 1
    return sorted(rates)


def set_refresh_rate(device: str, hz: int, test_only: bool = False) -> None:
    """Switch the refresh rate for this session only (it isn't written to the registry)."""
    mode = current_mode(device)
    mode.dmDisplayFrequency = hz
    mode.dmFields = DM_DISPLAYFREQUENCY
    result = _user32.ChangeDisplaySettingsExW(device, ctypes.byref(mode), None, CDS_TEST if test_only else 0, None)
    if result != DISP_CHANGE_SUCCESSFUL:
        raise OSError(f"Windows refused to change the refresh rate to {hz} Hz (code {result})")
