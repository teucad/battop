from __future__ import annotations

import sys

from .base import Platform


def current() -> Platform:
    if sys.platform == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform()
    raise RuntimeError(f"Battop doesn't support {sys.platform} yet")
