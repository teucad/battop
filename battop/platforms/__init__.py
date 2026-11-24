from __future__ import annotations

import sys

from .base import Platform


def current() -> Platform:
    if sys.platform == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform()
    if sys.platform.startswith("linux"):
        from .linux import LinuxPlatform

        return LinuxPlatform()
    raise RuntimeError(f"Battop doesn't support {sys.platform} yet")
