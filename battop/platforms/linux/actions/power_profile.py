from __future__ import annotations

import logging

from battop.actions.base import Action
from battop.i18n import N_, _

from .. import commands

log = logging.getLogger(__name__)

PROFILE = "power-saver"


class PowerProfileAction(Action):
    key = "power_mode"
    title = N_("Power Saver profile")
    settings_keys = ("power_mode_enabled",)

    def apply(self, settings):
        previous = commands.run(["powerprofilesctl", "get"])
        if previous == PROFILE:
            return None
        commands.run(["powerprofilesctl", "set", PROFILE])
        log.info(_("Switched power profile from %s to Power Saver"), previous)
        return {"previous": previous}

    def restore(self, saved):
        if commands.run(["powerprofilesctl", "get"]) != PROFILE:
            return  # Something else (e.g. the desktop's automatic mode) already changed it.
        commands.run(["powerprofilesctl", "set", saved["previous"]])
        log.info(_("Power profile restored to %s"), saved["previous"])
