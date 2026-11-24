"""Instant reactions to power-source changes, theme changes and being asked to stop (Linux)."""

from __future__ import annotations

import logging
import signal
import subprocess
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

_POWER_MONITOR = ["udevadm", "monitor", "--udev", "--subsystem-match=power_supply"]
_THEME_MONITOR = ["gsettings", "monitor", "org.gnome.desktop.interface", "color-scheme"]


class _LineWatcher:
    """Runs a long-lived command and calls back for each line it prints."""

    def __init__(self, command: list[str], on_line: Callable[[str], None]):
        self._command = command
        self._on_line = on_line
        self._process: subprocess.Popen | None = None

    def start(self) -> bool:
        try:
            self._process = subprocess.Popen(
                self._command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1
            )
        except OSError:
            return False  # Not installed: polling still works.
        threading.Thread(target=self._read, name="battop-" + self._command[0], daemon=True).start()
        return True

    def _read(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        for line in self._process.stdout:
            try:
                self._on_line(line)
            except Exception:
                log.exception("Error while handling %s output", self._command[0])

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()


class EventListener:
    def __init__(
        self,
        on_power_change: Callable[[], None],
        on_end_session: Callable[[], None],
        on_theme_change: Callable[[], None],
    ):
        self._on_end_session = on_end_session
        self._watchers = [
            _LineWatcher(_POWER_MONITOR, lambda line: on_power_change() if "power_supply" in line else None),
            _LineWatcher(_THEME_MONITOR, lambda line: on_theme_change()),
        ]
        self._previous_handlers: dict[int, object] = {}

    def start(self) -> None:
        for watcher in self._watchers:
            watcher.start()
        # Restore everything before the system stops us (logout/shutdown send SIGTERM or SIGHUP).
        # Must be called from the main thread, which is where Tk runs.
        for name in ("SIGTERM", "SIGHUP"):
            number = getattr(signal, name, None)
            if number is not None:
                try:
                    self._previous_handlers[number] = signal.signal(number, self._handle_signal)
                except ValueError:  # Not the main thread.
                    pass

    def _handle_signal(self, number, frame) -> None:
        self._on_end_session()
        raise SystemExit(0)  # Leaves Tk's main loop so the normal shutdown path runs.

    def stop(self) -> None:
        for watcher in self._watchers:
            watcher.stop()
        for number, handler in self._previous_handlers.items():
            try:
                signal.signal(number, handler)
            except (ValueError, TypeError):
                pass
