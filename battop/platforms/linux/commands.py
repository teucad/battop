"""Run external programs. Everything on Linux goes through here so tests can replace it."""

from __future__ import annotations

import shutil
import subprocess


def available(program: str) -> bool:
    return shutil.which(program) is not None


def run_raw(command: list[str], timeout: float = 10) -> subprocess.CompletedProcess:
    """Run a command and return the result, whatever the exit code."""
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise OSError(f"{command[0]} isn't installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise OSError(f"{command[0]} took too long") from exc


def run(command: list[str], timeout: float = 10) -> str:
    """Return stdout of a command; raise OSError if it can't run or exits with an error."""
    result = run_raw(command, timeout)
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or f"{command[0]} exited with {result.returncode}")
    return result.stdout.strip()
