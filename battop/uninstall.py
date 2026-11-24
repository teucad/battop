"""Remove everything Battop installed or changed on this PC."""

from __future__ import annotations

import logging
import shutil

from .config import data_dir
from .i18n import _
from .platforms.base import Platform


def uninstall(platform: Platform) -> list[str]:
    """Remove the startup entry and Battop's data folder. Returns a list of problems (empty = all good).

    Changes Battop made to the system are undone separately: by `Engine.stop()` for a running
    Battop, or `Engine.recover_previous_session()` for leftovers from a crash.
    """
    problems = []
    try:
        platform.set_autostart(False)
    except OSError as exc:
        problems.append(_("couldn't remove it from the startup list ({error})").format(error=exc))
    problems += platform.uninstall_extras()
    folder = data_dir()
    for handler in list(logging.getLogger("battop").handlers):  # The log file must be closed to delete it.
        handler.close()
        logging.getLogger("battop").removeHandler(handler)
    shutil.rmtree(folder, ignore_errors=True)
    if folder.exists():
        problems.append(_("couldn't delete {folder}").format(folder=folder))
    return problems
