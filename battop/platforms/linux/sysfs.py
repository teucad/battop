"""Battery and charger state from /sys/class/power_supply (no root, no extra packages)."""

from __future__ import annotations

import os
from pathlib import Path

from ...status import PowerStatus

_CHARGER_TYPES = {"Mains", "USB", "USB_C", "USB_PD", "USB_PD_DRP", "USB_DCP", "USB_CDP", "USB_ACA", "Wireless"}


def sysfs_root() -> Path:
    # Overridable so tests (and curious people) can point Battop at a fake tree.
    return Path(os.environ.get("BATTOP_SYSFS_ROOT", "/sys"))


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _number(path: Path) -> int | None:
    text = _read(path)
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def _seconds_left(battery: Path) -> int | None:
    """Time until empty, from energy/power (µWh / µW) or charge/current (µAh / µA)."""
    for stored, rate in (("energy_now", "power_now"), ("charge_now", "current_now")):
        amount, draw = _number(battery / stored), _number(battery / rate)
        if amount is not None and draw:  # Skips None and 0.
            return int(amount * 3600 / abs(draw))
    return None


def read_power_status(root: Path | None = None) -> PowerStatus:
    supplies = (root or sysfs_root()) / "class" / "power_supply"
    charger_seen = charger_online = False
    battery: Path | None = None
    try:
        entries = sorted(supplies.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        kind = _read(entry / "type")
        if _read(entry / "scope") == "Device":  # A wireless mouse or phone, not this computer.
            continue
        if kind in _CHARGER_TYPES:
            charger_seen = True
            charger_online = charger_online or _read(entry / "online") == "1"
        elif kind == "Battery" and battery is None:
            battery = entry
    if battery is None:
        return PowerStatus(False, False, None, None, False, False)

    status = _read(battery / "status") or "Unknown"
    capacity = _number(battery / "capacity")
    percent = None if capacity is None else max(0, min(100, capacity))
    if charger_online:
        on_battery = False
    elif charger_seen:
        on_battery = True
    else:  # No charger node at all: trust the battery's own report.
        on_battery = status == "Discharging"
    seconds_left = _seconds_left(battery) if on_battery and status == "Discharging" else None
    return PowerStatus(on_battery, True, percent, seconds_left, status == "Charging", False)
