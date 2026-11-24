from __future__ import annotations

import logging
from collections.abc import Callable

from battop.actions.base import Action
from battop.status import PowerStatus

from .. import anime, processes

log = logging.getLogger(__name__)


class AnimeBatteryAction(Action):
    """Show the charge level on the AniMe Matrix while unplugged.

    G-Helper (if running) redraws its own matrix mode whenever the power source changes,
    so on plug-in this only has to stop drawing; if G-Helper isn't running there is nothing
    to hand back to, so the display is cleared instead (see `restore`).
    """

    key = "anime_battery"
    title = "Battery level on the AniMe Matrix"
    settings_keys = ("anime_battery_enabled", "anime_brightness")
    # G-Helper repaints its own picture a few seconds after the power source changes.
    refresh_every_sec = 3

    def __init__(self, power_status: Callable[[], PowerStatus]):
        self._power_status = power_status
        self._failing = False

    def _percent(self) -> int:
        percent = self._power_status().percent
        return 0 if percent is None else percent

    def apply(self, settings):
        conflict = anime.ghelper_conflict()
        if conflict:
            log.info("AniMe Matrix: %s", conflict)
        with anime.AnimeMatrix.open() as matrix:
            matrix.start(settings.anime_brightness)
            matrix.show_battery(self._percent())
        log.info("Showing the battery level on the AniMe Matrix")
        return {"ghelper_was_running": processes.is_running("ghelper.exe")}

    def refresh(self, settings, saved):
        try:
            with anime.AnimeMatrix.open() as matrix:
                matrix.show_battery(self._percent())
            self._failing = False
        except OSError as exc:  # Don't flood the log if the device is busy or unplugged.
            if not self._failing:
                log.warning("AniMe Matrix: couldn't update (%s)", exc)
            self._failing = True
        return saved

    def restore(self, saved):
        # G-Helper only redraws when the power source changes, so it can take the display back
        # only after a plug-in. Pausing or quitting while still unplugged would leave a stale
        # charge level on the lid, so blank it instead.
        if not self._power_status().on_battery and processes.is_running("ghelper.exe"):
            log.info("Handing the AniMe Matrix back to G-Helper")
            return
        with anime.AnimeMatrix.open() as matrix:
            matrix.clear()
        if self._power_status().on_battery:
            log.info("AniMe Matrix cleared (G-Helper redraws it next time you plug in)")
        else:
            log.info("AniMe Matrix cleared (G-Helper isn't running to restore it)")
