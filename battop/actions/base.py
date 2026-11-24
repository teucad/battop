from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..config import Settings


class Action(ABC):
    """One battery-saving change that Battop makes while unplugged.

    Actions are stateless: `apply` returns whatever is needed to undo the
    change, the engine persists it (so undo works even after a crash or
    reboot) and hands it back to `restore` when the laptop is plugged in.
    """

    key: ClassVar[str]
    title: ClassVar[str]
    # Settings fields this action depends on. The first one is its on/off
    # toggle. When any of them change while unplugged, the action is re-run.
    settings_keys: ClassVar[tuple[str, ...]]

    def enabled(self, settings: Settings) -> bool:
        return bool(getattr(settings, self.settings_keys[0]))

    @abstractmethod
    def apply(self, settings: Settings) -> dict | None:
        """Make the change. Return JSON-serialisable undo data, or None if nothing changed."""

    @abstractmethod
    def restore(self, saved: dict) -> None:
        """Undo the change described by `saved`."""

    def refresh(self, settings: Settings, saved: dict) -> dict:
        """Called on every check while unplugged; return updated undo data."""
        return saved
