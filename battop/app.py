"""Entry point: wires the engine, tray icon and settings window together."""

from __future__ import annotations

import argparse
import ctypes
import logging
import queue
import sys
import tkinter as tk
from logging.handlers import RotatingFileHandler
from tkinter import messagebox

from .actions import default_actions
from .config import SettingsStore, data_dir
from .engine import Engine
from .gui import MainWindow, QueueLogHandler
from .power import get_power_status
from .tray import Tray

_ERROR_ALREADY_EXISTS = 183


def _acquire_single_instance():
    """Return a mutex handle, or None if Battop is already running."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\BattopSingleInstance")
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        return None
    return handle


def _setup_logging(debug: bool) -> queue.Queue:
    log_queue: queue.Queue = queue.Queue()
    logger = logging.getLogger("battop")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    file_handler = RotatingFileHandler(data_dir() / "battop.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(QueueLogHandler(log_queue))
    if debug and sys.stderr:
        logger.addHandler(logging.StreamHandler())
    return log_queue


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="battop", description="Automatic battery saving for Windows laptops.")
    parser.add_argument("--startup", action="store_true", help="launched at sign-in (may start hidden)")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    args = parser.parse_args(argv)

    mutex = _acquire_single_instance()
    if mutex is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Battop", "Battop is already running. Look for its icon in the system tray.")
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Crisp text on high-DPI screens.
    except (AttributeError, OSError):
        pass

    log_queue = _setup_logging(args.debug)
    engine = Engine(SettingsStore(), default_actions(), get_power_status, data_dir() / "state.json")
    engine.start()

    tray = Tray(queue.Queue())
    tray.start()

    root = tk.Tk()
    MainWindow(root, engine, log_queue, tray, start_hidden=args.startup and engine.settings.start_minimized)
    try:
        root.mainloop()
    finally:
        engine.stop()  # No-op if the window already shut it down.
