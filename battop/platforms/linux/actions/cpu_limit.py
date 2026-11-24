from __future__ import annotations

import json
import logging

from battop.actions.base import Action
from battop.i18n import N_, _

from .. import helper_client

log = logging.getLogger(__name__)


class CpuLimitAction(Action):
    key = "cpu_limit"
    title = N_("Limited processor speed")
    settings_keys = ("cpu_limit_enabled", "cpu_max_percent")

    def apply(self, settings):
        if not helper_client.available():
            log.info(_("The processor limit needs the one-time setup, so it was skipped"))
            return None
        answer = helper_client.call("set-cpu-max", str(settings.cpu_max_percent))
        if not answer.get("changed"):
            return None  # Already at or below the limit.
        log.info(_("Maximum processor speed limited to %d%%"), settings.cpu_max_percent)
        return {"state": answer["state"]}

    def restore(self, saved):
        helper_client.call("restore-cpu", json.dumps(saved["state"]))
        log.info(_("Maximum processor speed restored"))

