"""Talks to the root helper through pkexec (see helper.py and setup.py)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ...i18n import _
from . import commands
from .setup import HELPER_PATH, POLICY_PATH

SETUP_SCRIPT = Path(__file__).resolve().with_name("setup.py")


def available() -> bool:
    return os.access(HELPER_PATH, os.X_OK) and os.path.exists(POLICY_PATH) and commands.available("pkexec")


def call(*args: str) -> dict:
    """Run a helper operation as root and return its JSON answer."""
    return json.loads(commands.run(["pkexec", HELPER_PATH, *args], timeout=30))


def install() -> None:
    """Ask for the administrator password and install the helper."""
    result = commands.run_raw(["pkexec", sys.executable, str(SETUP_SCRIPT), "install"], timeout=300)
    if result.returncode in (126, 127):  # pkexec: dialog dismissed / not authorised.
        raise OSError(_("The setup was cancelled."))
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or f"pkexec exited with {result.returncode}")
