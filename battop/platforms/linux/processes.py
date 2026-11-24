"""List running processes from /proc."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


def iter_processes(proc_root: Path = Path("/proc")) -> Iterator[tuple[int, str, int]]:
    """Yield (pid, command name, owner uid) for every process."""
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
            yield int(entry.name), name, entry.stat().st_uid
        except OSError:
            continue  # The process ended while we were looking.


def running_process_names(proc_root: Path = Path("/proc")) -> list[str]:
    return sorted({name.lower() for pid, name, _uid in iter_processes(proc_root) if pid > 2 and name})
