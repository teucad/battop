#!/usr/bin/python3
"""Battop's root helper (Linux). Installed to /usr/local/libexec/battop-helper and run through pkexec.

It does exactly three things and nothing else, and validates every argument:

    set-cpu-max <30-100>      limit the processor's maximum speed (only ever lowers it)
    restore-cpu <json>        put back what set-cpu-max reported
    renice <pid> <0-19>       set the nice value of a process owned by the user who asked

Standard library only: this file runs as root, so it is kept small enough to read in one sitting.
"""

import json
import os
import re
import sys

SYSFS = "/sys"
PROC = "/proc"
MIN_PERCENT, MAX_PERCENT = 30, 100
_CPU_NAME = re.compile(r"^cpu[0-9]{1,4}$")
_MAX_KHZ = 20_000_000  # 20 GHz: anything above is certainly not a real frequency.


class HelperError(Exception):
    pass


def _read(path):
    with open(path, encoding="ascii") as f:
        return f.read().strip()


def _write(path, value):
    with open(path, "w", encoding="ascii") as f:
        f.write(str(value))


def _int(text, low, high, what):
    if not isinstance(text, (str, int)) or isinstance(text, bool):
        raise HelperError(f"{what} must be a number")
    try:
        value = int(text)
    except ValueError:
        raise HelperError(f"{what} must be a number") from None
    if not low <= value <= high:
        raise HelperError(f"{what} must be between {low} and {high}")
    return value


def _intel_path():
    return f"{SYSFS}/devices/system/cpu/intel_pstate/max_perf_pct"


def _cpufreq_dirs():
    base = f"{SYSFS}/devices/system/cpu"
    try:
        names = sorted(n for n in os.listdir(base) if _CPU_NAME.match(n))
    except OSError:
        return []
    return [n for n in names if os.path.isdir(f"{base}/{n}/cpufreq")]


def set_cpu_max(percent):
    percent = _int(percent, MIN_PERCENT, MAX_PERCENT, "percent")
    intel = _intel_path()
    if os.path.exists(intel):
        current = _int(_read(intel), 1, 100, "current limit")
        if current <= percent:
            return {"changed": False}
        _write(intel, percent)
        return {"changed": True, "state": {"mode": "intel_pstate", "value": current}}
    previous = {}
    for name in _cpufreq_dirs():
        folder = f"{SYSFS}/devices/system/cpu/{name}/cpufreq"
        highest = _int(_read(f"{folder}/cpuinfo_max_freq"), 1, _MAX_KHZ, "cpuinfo_max_freq")
        current = _int(_read(f"{folder}/scaling_max_freq"), 1, _MAX_KHZ, "scaling_max_freq")
        target = max(1, highest * percent // 100)
        if current > target:
            _write(f"{folder}/scaling_max_freq", target)
            previous[name] = current
    if not previous:
        return {"changed": False}
    return {"changed": True, "state": {"mode": "cpufreq", "value": previous}}


def restore_cpu(state):
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except ValueError:
            raise HelperError("state isn't valid JSON") from None
    if not isinstance(state, dict) or state.get("mode") not in ("intel_pstate", "cpufreq"):
        raise HelperError("unknown state")
    value = state.get("value")
    if state["mode"] == "intel_pstate":
        _write(_intel_path(), _int(value, 1, 100, "limit"))
        return {"restored": True}
    if not isinstance(value, dict) or not value:
        raise HelperError("unknown state")
    checked = {}
    for name, khz in value.items():
        if not isinstance(name, str) or not _CPU_NAME.match(name):
            raise HelperError("bad processor name")
        checked[name] = _int(khz, 1, _MAX_KHZ, "frequency")
    for name, khz in checked.items():
        _write(f"{SYSFS}/devices/system/cpu/{name}/cpufreq/scaling_max_freq", khz)
    return {"restored": True}


def _owner_of(pid):
    with open(f"{PROC}/{pid}/status", encoding="ascii", errors="replace") as f:
        for line in f:
            if line.startswith("Uid:"):
                return int(line.split()[1])  # The real uid.
    raise HelperError("can't tell who owns that process")


def renice(pid, nice, caller_uid):
    if caller_uid is None:
        raise HelperError("must be run through pkexec")
    pid = _int(pid, 2, 4_194_304, "pid")
    nice = _int(nice, 0, 19, "nice value")  # Never negative: this can't be used to speed anything up.
    try:
        owner = _owner_of(pid)
    except OSError:
        raise HelperError("no such process") from None
    if owner != caller_uid:
        raise HelperError("that process doesn't belong to you")
    os.setpriority(os.PRIO_PROCESS, pid, nice)
    return {"reniced": True}


def run(argv, caller_uid):
    """Run one operation from a command line; returns the JSON-able result."""
    operations = {
        "set-cpu-max": (1, lambda a: set_cpu_max(a[0])),
        "restore-cpu": (1, lambda a: restore_cpu(a[0])),
        "renice": (2, lambda a: renice(a[0], a[1], caller_uid)),
    }
    if not argv or argv[0] not in operations:
        raise HelperError("usage: battop-helper set-cpu-max|restore-cpu|renice ...")
    count, function = operations[argv[0]]
    if len(argv) - 1 != count:
        raise HelperError(f"{argv[0]} takes {count} argument(s)")
    return function(argv[1:])


def main(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    try:
        caller = int(environ["PKEXEC_UID"]) if "PKEXEC_UID" in environ else None
    except ValueError:
        caller = None
    try:
        result = run(sys.argv[1:] if argv is None else argv, caller)
    except HelperError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc.strerror or exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
