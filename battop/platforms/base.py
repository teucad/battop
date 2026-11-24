"""What the rest of Battop needs from an operating system."""

from __future__ import annotations

from typing import Protocol

from ..actions.base import Action
from ..status import PowerStatus


class Platform(Protocol):
    name: str
    # Action keys (see Action.key) that this OS can do; the GUI only shows these.
    supported_keys: frozenset[str]

    def init_process(self) -> None:
        """One-time process setup (e.g. DPI awareness)."""

    def power_status(self) -> PowerStatus: ...

    def actions(self) -> list[Action]: ...

    def unavailable_reason(self, key: str) -> str | None:
        """Why a supported action can't be used right now, or None if it can."""

    def running_app_names(self) -> list[str]: ...

    def autostart_enabled(self) -> bool: ...

    def set_autostart(self, enabled: bool) -> None: ...
