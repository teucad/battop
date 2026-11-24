"""Locate bundled data files, both from source and from a PyInstaller build."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(*parts: str) -> Path:
    """Path inside the `battop` package (PyInstaller unpacks it under `_MEIPASS`)."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root.joinpath("battop", *parts)
