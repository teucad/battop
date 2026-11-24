from __future__ import annotations

import logging
import os

from battop.actions.base import Action
from battop.i18n import N_, _

from .. import helper_client, processes

log = logging.getLogger(__name__)

LOW_PRIORITY = 10  # Nice value given to the chosen apps (0 is normal, 19 the lowest).


class AppPriorityAction(Action):
    """Lowers the priority of chosen apps. Lowering needs no privilege, putting it back does,
    so this only runs when the root helper is installed (every change must be undoable)."""

    key = "app_efficiency"
    title = N_("Apps in efficiency mode")
    settings_keys = ("app_efficiency_enabled", "efficiency_apps")

    def apply(self, settings):
        if not helper_client.available():
            log.info(_("Lowering app priorities needs the one-time setup, so it was skipped"))
            return None
        # Always returns undo data so `refresh` keeps catching apps that start later.
        return self.refresh(settings, {"processes": {}})

    def refresh(self, settings, saved):
        targets = {name.casefold() for name in settings.efficiency_apps}
        known = saved["processes"]
        if not targets:
            return saved
        updated = dict(known)
        for pid, name, uid in processes.iter_processes():
            if name.casefold() not in targets or str(pid) in known or pid == os.getpid() or uid != os.getuid():
                continue
            try:
                current = os.getpriority(os.PRIO_PROCESS, pid)
                if current >= LOW_PRIORITY:
                    updated[str(pid)] = None  # Already low; nothing to undo.
                    continue
                os.setpriority(os.PRIO_PROCESS, pid, LOW_PRIORITY)
            except OSError:
                updated[str(pid)] = None  # Gone, or not ours to change; don't retry every few seconds.
                continue
            updated[str(pid)] = {"name": name, "nice": current}
            log.info(_("Put %s into efficiency mode"), name)
        return {"processes": updated} if updated != known else saved

    def restore(self, saved):
        running = {str(pid): name for pid, name, _uid in processes.iter_processes()}
        restored = set()
        for pid, info in saved["processes"].items():
            if info is None or running.get(pid) != info["name"]:
                continue  # Skip apps that ended, and recycled process IDs.
            try:
                helper_client.call("renice", pid, str(info["nice"]))
                restored.add(info["name"])
            except OSError as exc:
                log.debug("Can't restore %s (pid %s): %s", info["name"], pid, exc)
        if restored:
            log.info(_("Took %s out of efficiency mode"), ", ".join(sorted(restored)))
