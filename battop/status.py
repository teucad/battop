from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PowerStatus:
    on_battery: bool
    has_battery: bool
    percent: int | None
    seconds_left: int | None
    charging: bool
    battery_saver_on: bool
