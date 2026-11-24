"""Entry point: wires the engine, tray icon and settings window together."""

from __future__ import annotations

import argparse
import logging
import queue
import sys
from logging.handlers import RotatingFileHandler

from . import i18n, platforms, single_instance
from .config import SettingsStore, data_dir
from .engine import Engine
from .i18n import N_, _
from .tray import Tray
from .uninstall import uninstall


def _import_gui():
    """Import the window code, with a clear hint if Tk (or Pillow's ImageTk) isn't installed."""
    try:
        from . import gui
    except ImportError as exc:
        sys.exit(
            f"Battop needs Tk and Pillow's ImageTk to show its window ({exc}).\n"
            "On Debian/Ubuntu: sudo apt install python3-tk python3-pil.imagetk"
        )
    return gui


def _show_message(text: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(_("Battop"), text)
        root.destroy()
    except Exception:  # No Tk or no display: say it on the console instead.
        print(text)


def _setup_logging(debug: bool, gui) -> queue.Queue:
    log_queue: queue.Queue = queue.Queue()
    logger = logging.getLogger("battop")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    file_handler = RotatingFileHandler(data_dir() / "battop.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(gui.QueueLogHandler(log_queue))
    if debug and sys.stderr:
        logger.addHandler(logging.StreamHandler())
    return log_queue


_NOTIFICATIONS = {
    "saving_on": (N_("Battery saving is on"), N_("Running on battery. Your power-saving settings are active.")),
    "saving_off": (N_("Battery saving is off"), N_("Your usual settings are back.")),
    "low_tier": (N_("Battery is low"), N_("Battop is saving extra power.")),
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="battop", description="Automatic battery saving for laptops.")
    parser.add_argument("--startup", action="store_true", help="launched at sign-in (may start hidden)")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument("--setup-linux-helper", action="store_true", help="Linux: install the optional root helper (run as root)")
    parser.add_argument("--remove-linux-helper", action="store_true", help="Linux: remove the root helper (run as root)")
    parser.add_argument("--install-desktop-entry", action="store_true", help="Linux: add Battop to the application menu")
    parser.add_argument(
        "--uninstall", action="store_true", help="undo Battop's changes, remove its startup entry and data, then exit"
    )
    args = parser.parse_args(argv)

    if args.setup_linux_helper or args.remove_linux_helper or args.install_desktop_entry:
        if not sys.platform.startswith("linux"):
            parser.error("these options only exist on Linux")
        from .platforms.linux import desktop, setup

        status = 0
        if args.install_desktop_entry:
            desktop.install_desktop_entry()
            print("Battop was added to the application menu.")
        if args.setup_linux_helper:
            status = setup.main(["install"])
        elif args.remove_linux_helper:
            status = setup.main(["remove"])
        sys.exit(status)

    platform = platforms.current()
    platform.init_process()
    i18n.set_language(i18n.resolve(SettingsStore().load().language, platform.system_language()))

    if not single_instance.acquire():
        if not platform.signal_existing_instance():
            _show_message(_("Battop is already running. Look for its icon in the system tray."))
        return

    if args.uninstall:
        engine = Engine(SettingsStore(), platform.actions(), platform.power_status, data_dir() / "state.json")
        engine.recover_previous_session()
        problems = uninstall(platform)
        print("Battop was removed." if not problems else "Battop was removed, but: " + "; ".join(problems))
        return

    gui = _import_gui()
    import tkinter as tk

    log_queue = _setup_logging(args.debug, gui)
    commands: queue.Queue = queue.Queue()
    tray = Tray(commands)
    tray.start()

    def notify(kind: str) -> None:
        title, message = _NOTIFICATIONS[kind]
        if not platform.notify(_(title), _(message)):
            tray.notify(_(title), _(message))

    engine = Engine(
        SettingsStore(), platform.actions(), platform.power_status, data_dir() / "state.json", on_event=notify
    )
    engine.start()
    stop_events = platform.start_events(
        on_power_change=engine.wake,
        on_end_session=engine.stop,  # Restore everything before the session ends.
        on_show=lambda: commands.put("show"),
        on_theme_change=lambda: commands.put("theme"),
    )

    root = tk.Tk()
    gui.MainWindow(
        root, engine, platform, log_queue, tray, start_hidden=args.startup and engine.settings.start_minimized
    )
    try:
        root.mainloop()
    finally:
        stop_events()
        engine.stop()  # No-op if the window already shut it down.
