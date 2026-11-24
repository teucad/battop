from __future__ import annotations

import logging

from battop.actions.base import Action
from battop.i18n import N_, _

from .. import commands

log = logging.getLogger(__name__)


def read_status() -> tuple[str, int] | None:
    """(radio state 'on'/'off', number of connected devices), or None without a Bluetooth adapter."""
    info = commands.run(["bluetoothctl", "show"])
    if "No default controller" in info or "Powered:" not in info:
        return None
    state = "on" if "Powered: yes" in info else "off"
    devices = commands.run(["bluetoothctl", "devices", "Connected"])
    return state, sum(1 for line in devices.splitlines() if line.startswith("Device "))


def set_state(on: bool) -> None:
    commands.run(["bluetoothctl", "power", "on" if on else "off"])


class BluetoothAction(Action):
    key = "bluetooth"
    title = N_("Bluetooth off")
    settings_keys = ("bluetooth_enabled",)

    def apply(self, settings):
        status = read_status()
        if status is None or status[0] != "on":
            return None
        if status[1] > 0:
            log.info(_("Bluetooth left on because %d device(s) are connected"), status[1])
            return None
        set_state(False)
        log.info(_("Bluetooth turned off (nothing was connected)"))
        return {"was_on": True}

    def restore(self, saved):
        status = read_status()
        if status is not None and status[0] == "off":
            set_state(True)
            log.info(_("Bluetooth turned back on"))
