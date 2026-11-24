from __future__ import annotations

import logging

from battop.actions.base import Action
from battop.i18n import _, N_

from .. import ps

log = logging.getLogger(__name__)

_PRELUDE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
foreach ($t in 'Windows.Devices.Radios.Radio,Windows.System.Devices',
               'Windows.Devices.Radios.RadioState,Windows.System.Devices',
               'Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices',
               'Windows.Devices.Enumeration.DeviceInformation,Windows.Devices.Enumeration',
               'Windows.Devices.Bluetooth.BluetoothDevice,Windows.Devices.Bluetooth',
               'Windows.Devices.Bluetooth.BluetoothLEDevice,Windows.Devices.Bluetooth',
               'Windows.Devices.Bluetooth.BluetoothConnectionStatus,Windows.Devices.Bluetooth') {
    [void][Type]::GetType("$t,ContentType=WindowsRuntime")
}
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$radio = $radios | Where-Object { $_.Kind -eq 'Bluetooth' } | Select-Object -First 1
"""

_STATUS = _PRELUDE + r"""
if (-not $radio) { 'none'; exit }
$connected = 0
foreach ($cls in [Windows.Devices.Bluetooth.BluetoothDevice], [Windows.Devices.Bluetooth.BluetoothLEDevice]) {
    $selector = $cls::GetDeviceSelectorFromConnectionStatus([Windows.Devices.Bluetooth.BluetoothConnectionStatus]::Connected)
    $found = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($selector)) ([Windows.Devices.Enumeration.DeviceInformationCollection])
    $connected += $found.Count
}
"$($radio.State.ToString().ToLower()) $connected"
"""

_SET = _PRELUDE + r"""
if (-not $radio) { 'none'; exit }
(Await ($radio.SetStateAsync([Windows.Devices.Radios.RadioState]::{state})) ([Windows.Devices.Radios.RadioAccessStatus])).ToString()
"""


def read_status() -> tuple[str, int] | None:
    """(radio state 'on'/'off', number of connected devices), or None without Bluetooth."""
    output = ps.run(_STATUS, timeout=30)
    if output == "none":
        return None
    state, connected = output.split()
    return state, int(connected)


def set_state(on: bool) -> None:
    output = ps.run(_SET.replace("{state}", "On" if on else "Off"), timeout=30)
    if output != "Allowed":
        raise OSError(f"Windows didn't allow changing Bluetooth ({output})")


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
