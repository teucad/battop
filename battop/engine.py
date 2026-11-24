"""Watches the power source and applies / undoes battery-saving actions."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from .actions.base import Action
from .config import Settings, SettingsStore, effective
from .status import PowerStatus

log = logging.getLogger(__name__)


class Engine:
    """Runs a background thread that polls the power status.

    While unplugged (and enabled) every enabled action is applied; when
    plugged back in, paused, or stopped, each change is undone. Undo data is
    written to `state_path` so a crash or reboot never leaves the laptop stuck
    in battery-saving mode: leftovers are undone on the next start.
    """

    def __init__(
        self,
        store: SettingsStore,
        actions: Sequence[Action],
        status_provider: Callable[[], PowerStatus],
        state_path: Path | None = None,
        on_event: Callable[[str], None] | None = None,
    ):
        self._store = store
        self._settings = store.load()
        self._pending: Settings | None = None
        self._actions = list(actions)
        self._by_key = {a.key: a for a in self._actions}
        self._status_provider = status_provider
        self._state_path = state_path
        self._on_event = on_event
        self._active: dict[str, dict] = {}  # action key -> undo data
        self._saving = False
        self._low = False  # Battery is low (see `config.effective`).
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.status: PowerStatus | None = None

    # --- Public API (safe to call from any thread) -------------------------

    @property
    def settings(self) -> Settings:
        with self._lock:
            return self._pending or self._settings

    @property
    def saving(self) -> bool:
        return self._saving

    def active_titles(self) -> list[str]:
        with self._lock:
            return [self._by_key[k].title for k in self._active if k in self._by_key]

    def wake(self) -> None:
        """Check the power status right away (e.g. after a power-source event)."""
        self._wake.set()

    def submit_settings(self, settings: Settings) -> None:
        """Save new settings; the engine thread picks them up right away."""
        settings = settings.normalized()
        self._store.save(settings)
        with self._lock:
            self._pending = settings
        self._wake.set()

    def start(self) -> None:
        self._recover_previous_session()
        self._thread = threading.Thread(target=self._run, name="battop-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=30)
        with self._lock:
            if self._saving or self._active:
                log.info("Battop is closing - restoring your normal settings")
                self._restore_all()

    def tick(self) -> None:
        """Check the power status once and react to it."""
        status = self._status_provider()
        with self._lock:
            self.status = status
            old = self._eff()
            if self._pending is not None:
                self._settings, self._pending = self._pending, None
            self._update_low(status)
            self._reconcile(old, self._eff())
            self._sync()

    # --- Internals ----------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Unexpected error while checking the power status")
            self._wake.wait(self._settings.poll_interval_sec)
            self._wake.clear()

    def _eff(self) -> Settings:
        return effective(self._settings, self._low)

    def _update_low(self, status: PowerStatus) -> None:
        s = self._settings
        if not (status.on_battery and s.enabled and s.low_tier_enabled and status.percent is not None):
            self._low = False
            return
        # A little hysteresis so the tier doesn't flap around the threshold.
        was_low = self._low
        self._low = status.percent <= s.low_tier_threshold or (was_low and status.percent < s.low_tier_threshold + 3)
        if self._low and not was_low:
            log.info("Battery is low (%d%%) - saving extra power", status.percent)
            self._emit("low_tier")

    def _sync(self) -> None:
        status = self.status
        on_battery = bool(status and status.on_battery)
        want = on_battery and self._settings.enabled
        if want and not self._saving:
            pct = f" ({status.percent}%)" if status.percent is not None else ""
            log.info("Running on battery%s - battery saving is on", pct)
            for action in self._actions:
                if action.enabled(self._eff()):
                    self._apply(action)
            self._saving = True
            self._emit("saving_on")
        elif not want and self._saving:
            if on_battery:
                log.info("Battery saving paused - restoring your normal settings")
            else:
                log.info("Plugged in - restoring your normal settings")
            self._restore_all()
            self._emit("saving_off")
        elif want:
            self._refresh_all()

    def _emit(self, kind: str) -> None:
        if self._on_event is None or not self._settings.notifications:
            return
        try:
            self._on_event(kind)
        except Exception:
            log.exception("Event handler failed for %s", kind)

    def _reconcile(self, old: Settings, new: Settings) -> None:
        """While saving, re-run only the actions whose settings changed."""
        if not self._saving or old == new:
            return
        for action in self._actions:
            if all(getattr(old, k) == getattr(new, k) for k in action.settings_keys):
                continue
            if action.key in self._active:
                self._restore(action.key)
            if action.enabled(new):
                self._apply(action)

    def _apply(self, action: Action) -> None:
        try:
            saved = action.apply(self._eff())
        except Exception as exc:
            log.warning("%s: couldn't apply (%s)", action.title, exc)
            return
        if saved is not None:
            self._active[action.key] = saved
            self._persist()

    def _restore(self, key: str) -> None:
        saved = self._active.pop(key)
        action = self._by_key.get(key)
        if action is not None:
            try:
                action.restore(saved)
            except Exception as exc:
                log.warning("%s: couldn't restore (%s)", action.title, exc)
        self._persist()

    def _restore_all(self) -> None:
        for key in reversed(list(self._active)):
            self._restore(key)
        self._saving = False

    def _refresh_all(self) -> None:
        for key, saved in list(self._active.items()):
            try:
                updated = self._by_key[key].refresh(self._eff(), saved)
            except Exception as exc:
                log.warning("%s: refresh failed (%s)", self._by_key[key].title, exc)
                continue
            if updated != saved:
                self._active[key] = updated
                self._persist()

    def _persist(self) -> None:
        if self._state_path is None:
            return
        try:
            if self._active:
                self._state_path.write_text(json.dumps({"active": self._active}), encoding="utf-8")
            else:
                self._state_path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Couldn't save undo information: %s", exc)

    def _recover_previous_session(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            active = json.loads(self._state_path.read_text(encoding="utf-8"))["active"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("Ignoring unreadable undo information: %s", exc)
            self._state_path.unlink(missing_ok=True)
            return
        with self._lock:
            self._active = {k: v for k, v in active.items() if k in self._by_key}
            if self._active:
                log.info("Undoing changes left over from the last session")
            self._restore_all()
            self._persist()
