"""Run a PowerShell snippet and return its output (for things only WMI/WinRT expose)."""

from __future__ import annotations

import subprocess


def run(command: str, timeout: float = 20) -> str:
    """Return stdout of a PowerShell command; raise OSError if it fails."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("PowerShell took too long") from exc
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or f"PowerShell exited with {result.returncode}")
    return result.stdout.strip()
