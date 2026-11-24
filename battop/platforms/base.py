"""What the rest of Battop needs from an operating system."""

from __future__ import annotations

from collections.abc import Callable
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

    def start_events(
        self, on_power_change: Callable[[], None], on_end_session: Callable[[], None], on_show: Callable[[], None]
    ) -> Callable[[], None]:
        """Listen for OS events; returns a function that stops listening."""

    def signal_existing_instance(self) -> bool:
        """Ask an already-running Battop to show its window."""

    def autostart_enabled(self) -> bool: ...

    def set_autostart(self, enabled: bool) -> None: ...
