"""Thin ctypes wrappers around the Windows power APIs (kernel32 + powrprof)."""

from __future__ import annotations

import ctypes
import uuid
import winreg
from ctypes import wintypes

from ...i18n import N_, _
from ...status import PowerStatus

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_powrprof = ctypes.WinDLL("powrprof")


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_str(cls, text: str) -> GUID:
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)

    def __str__(self) -> str:
        return str(uuid.UUID(bytes_le=bytes(self)))


# Windows 11 "Power mode" overlays (Settings > System > Power & battery).
MODE_BEST_EFFICIENCY = "961cc777-2547-4f9d-8174-7d86181b8a7a"
MODE_BALANCED = "00000000-0000-0000-0000-000000000000"
MODE_BEST_PERFORMANCE = "ded574b5-45a0-4f42-8737-46345c09c238"
MODE_NAMES = {
    MODE_BEST_EFFICIENCY: N_("Best power efficiency"),
    MODE_BALANCED: N_("Balanced"),
    MODE_BEST_PERFORMANCE: N_("Best performance"),
}

# Built-in power plans.
SCHEME_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
SCHEME_POWER_SAVER = "a1841308-3541-4fab-bc81-f71556f20b4a"

# Power-scheme settings (see `powercfg /query`).
SUB_PROCESSOR = "54533251-82be-4824-96c1-47b60b740d00"
PROCESSOR_MAX_STATE = "bc5038f7-23e0-4960-96da-33abaf5935ec"
SUB_VIDEO = "7516b95f-f776-4464-8c53-06167f40cc99"
VIDEO_IDLE = "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"  # Turn off display after (seconds)
SUB_SLEEP = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
STANDBY_IDLE = "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"  # Sleep after (seconds)
SUB_ENERGY_SAVER ="de830923-a562-41af-a086-e3a2c6bad2da"
ENERGY_SAVER_THRESHOLD = "e69653ca-cf7f-4f05-aa73-cb833fa90ad4"


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def get_power_status() -> PowerStatus:
    s = _SYSTEM_POWER_STATUS()
    if not _kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        raise ctypes.WinError(ctypes.get_last_error())
    unknown_flag = s.BatteryFlag == 255
    return PowerStatus(
        on_battery=s.ACLineStatus == 0,
        has_battery=not unknown_flag and not s.BatteryFlag & 128,
        percent=None if s.BatteryLifePercent == 255 else s.BatteryLifePercent,
        seconds_left=None if s.BatteryLifeTime == 0xFFFFFFFF else s.BatteryLifeTime,
        charging=not unknown_flag and bool(s.BatteryFlag & 8),
        battery_saver_on=bool(s.SystemStatusFlag & 1),
    )


def _check(result: int, func: str) -> None:
    if result != 0:
        raise OSError(result, f"{func} failed: {ctypes.FormatError(result).strip()}")


# --- Power mode overlay -----------------------------------------------------


def get_power_mode() -> str:
    """The power mode the user selected (not the one battery saver may force)."""
    func = getattr(_powrprof, "PowerGetActualOverlayScheme", None) or _powrprof.PowerGetEffectiveOverlayScheme
    guid = GUID()
    _check(func(ctypes.byref(guid)), "PowerGetActualOverlayScheme")
    return str(guid)


def set_power_mode(mode: str) -> None:
    func = _powrprof.PowerSetActiveOverlayScheme
    func.argtypes = [GUID]
    _check(func(GUID.from_str(mode)), "PowerSetActiveOverlayScheme")


def mode_name(mode: str) -> str:
    label = MODE_NAMES.get(mode, N_("Custom"))
    return _(label)


def get_dc_overlay() -> str | None:
    """The power mode Windows 11 uses on battery, or None if it has no per-source modes.

    Windows keeps separate modes for plugged-in and battery. Setting the overlay while
    unplugged changes the battery one, and it can't be changed back after plugging in
    (that would write the plugged-in slot), so Battop leaves it alone when this exists.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes"
        ) as key:
            return str(winreg.QueryValueEx(key, "ActiveOverlayDcPowerScheme")[0]).lower()
    except OSError:
        return None


# --- Power scheme values (battery / "DC" side only) ------------------------


def get_active_scheme() -> str:
    ptr = ctypes.POINTER(GUID)()
    _check(_powrprof.PowerGetActiveScheme(None, ctypes.byref(ptr)), "PowerGetActiveScheme")
    try:
        return str(ptr.contents)
    finally:
        _kernel32.LocalFree(ptr)


def set_active_scheme(scheme: str) -> None:
    _check(_powrprof.PowerSetActiveScheme(None, ctypes.byref(GUID.from_str(scheme))), "PowerSetActiveScheme")


def read_dc_value(scheme: str, subgroup: str, setting: str) -> int:
    value = wintypes.DWORD()
    _check(
        _powrprof.PowerReadDCValueIndex(
            None,
            ctypes.byref(GUID.from_str(scheme)),
            ctypes.byref(GUID.from_str(subgroup)),
            ctypes.byref(GUID.from_str(setting)),
            ctypes.byref(value),
        ),
        "PowerReadDCValueIndex",
    )
    return value.value


def write_dc_value(scheme: str, subgroup: str, setting: str, value: int) -> None:
    scheme_guid = GUID.from_str(scheme)
    _check(
        _powrprof.PowerWriteDCValueIndex(
            None,
            ctypes.byref(scheme_guid),
            ctypes.byref(GUID.from_str(subgroup)),
            ctypes.byref(GUID.from_str(setting)),
            wintypes.DWORD(value),
        ),
        "PowerWriteDCValueIndex",
    )
    # Re-activating the scheme makes Windows pick up the new value immediately.
    if get_active_scheme() == scheme:
        _check(_powrprof.PowerSetActiveScheme(None, ctypes.byref(scheme_guid)), "PowerSetActiveScheme")
