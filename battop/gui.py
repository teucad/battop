"""The settings window (tkinter)."""

from __future__ import annotations

import logging
import os
import queue
import sys
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, scrolledtext, ttk

from . import __version__
from .config import Settings, data_dir, normalize_app_names
from .engine import Engine
from .platforms.base import Platform
from .tray import Tray

FONT = "Segoe UI"
COLORS = {
    "bg": "#f3f5f8",
    "card": "#ffffff",
    "border": "#e3e7ee",
    "text": "#1f2937",
    "muted": "#6b7280",
    "accent": "#16a34a",
    "warn": "#d97706",
    "danger": "#dc2626",
    "idle": "#9ca3af",
}
_BOOL_KEYS = (
    "enabled",
    "power_mode_enabled",
    "brightness_enabled",
    "cpu_limit_enabled",
    "battery_saver_enabled",
    "refresh_rate_enabled",
    "timeouts_enabled",
    "bluetooth_enabled",
    "anime_battery_enabled",
    "low_tier_enabled",
    "app_efficiency_enabled",
    "start_minimized",
)
_NUMBER_KEYS = (
    "brightness_percent",
    "cpu_max_percent",
    "battery_saver_threshold",
    "screen_off_minutes",
    "sleep_minutes",
    "low_tier_threshold",
    "low_brightness_percent",
    "low_cpu_max_percent",
    "anime_brightness",
)
_SAVE_DELAY_MS = 600
_POLL_MS = 500
_MAX_LOG_LINES = 300


class QueueLogHandler(logging.Handler):
    """Forwards log records to the GUI thread."""

    def __init__(self, target: queue.Queue):
        super().__init__(logging.INFO)
        self.target = target
        self.setFormatter(logging.Formatter("%(asctime)s   %(message)s", "%H:%M"))

    def emit(self, record):
        self.target.put(self.format(record))


def _format_duration(seconds: int) -> str:
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


class MainWindow:
    def __init__(
        self, root: tk.Tk, engine: Engine, platform: Platform, log_queue: queue.Queue, tray: Tray, start_hidden: bool
    ):
        self.root = root
        self.platform = platform
        self.engine = engine
        self.log_queue = log_queue
        self.tray = tray
        self._save_job: str | None = None
        self._loading = False
        self._told_about_tray = False

        scale = root.winfo_fpixels("1i") / 96
        root.title("Battop - Battery Saver")
        root.geometry(f"{int(640 * scale)}x{int(660 * scale)}")
        root.minsize(int(580 * scale), int(560 * scale))
        root.configure(bg=COLORS["bg"])
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._init_style()
        self.vars: dict[str, tk.Variable] = {k: tk.BooleanVar() for k in _BOOL_KEYS}
        self.vars.update({k: tk.DoubleVar() for k in _NUMBER_KEYS})
        self.vars["anime_brightness"] = tk.IntVar()  # Radio buttons need an exact integer match.

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=14, pady=(14, 4))
        notebook.add(self._build_overview(notebook), text="Overview")
        notebook.add(self._build_power_page(notebook), text="Power saving")
        if platform.supported_keys & {"refresh_rate", "timeouts", "bluetooth", "anime_battery"}:
            notebook.add(self._build_extras_page(notebook), text="Extras")
        notebook.add(self._build_low_battery_page(notebook), text="Low battery")
        if "app_efficiency" in platform.supported_keys:
            notebook.add(self._build_apps_page(notebook), text="Apps")
        notebook.add(self._build_general_page(notebook), text="General")
        self.footer = ttk.Label(root, text="Changes are saved automatically.", style="Footer.TLabel")
        self.footer.pack(fill="x", padx=18, pady=(0, 10))

        self._load(engine.settings)
        for var in self.vars.values():
            var.trace_add("write", self._schedule_save)

        if start_hidden and tray.available:
            root.withdraw()
        self._poll()

    # --- Layout helpers -----------------------------------------------------

    def _init_style(self) -> None:
        c = COLORS
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=c["bg"], foreground=c["text"], font=(FONT, 10))
        style.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=0)
        style.configure("TNotebook.Tab", padding=(14, 6), background=c["bg"], borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", c["card"])])
        style.configure("Page.TFrame", background=c["bg"])
        style.configure("Card.TFrame", background=c["card"])
        style.configure("Card.TLabel", background=c["card"])
        style.configure("Title.TLabel", background=c["card"], font=(FONT, 11, "bold"))
        style.configure("Muted.TLabel", background=c["card"], foreground=c["muted"], font=(FONT, 9))
        style.configure("Big.TLabel", background=c["card"], font=(FONT, 26, "bold"))
        style.configure("Value.TLabel", background=c["card"], foreground=c["accent"], font=(FONT, 11, "bold"))
        style.configure("Footer.TLabel", background=c["bg"], foreground=c["muted"], font=(FONT, 9))
        style.configure("Card.TCheckbutton", background=c["card"], font=(FONT, 11, "bold"))
        style.map("Card.TCheckbutton", background=[("active", c["card"])])
        style.configure("Plain.TCheckbutton", background=c["card"])
        style.configure("Plain.TRadiobutton", background=c["card"])
        style.map("Plain.TRadiobutton", background=[("active", c["card"])])
        style.configure("Warn.TLabel", background=c["card"], foreground=c["warn"], font=(FONT, 9))
        style.map("Plain.TCheckbutton", background=[("active", c["card"])])
        style.configure("Horizontal.TScale", background=c["card"], troughcolor=c["border"])
        style.configure("TButton", padding=(10, 4))

    def _page(self, notebook) -> ttk.Frame:
        page = ttk.Frame(notebook, style="Page.TFrame", padding=(0, 12, 0, 0))
        return page

    def _card(self, parent, expand: bool = False) -> ttk.Frame:
        outer = tk.Frame(
            parent, bg=COLORS["card"], highlightthickness=1, highlightbackground=COLORS["border"], bd=0
        )
        outer.pack(fill="both" if expand else "x", expand=expand, pady=(0, 10))
        inner = ttk.Frame(outer, style="Card.TFrame", padding=14)
        inner.pack(fill="both", expand=True)
        return inner

    def _description(self, parent, text: str) -> ttk.Label:
        label = ttk.Label(parent, text=text, style="Muted.TLabel", justify="left")
        label.pack(fill="x", anchor="w", pady=(4, 0))
        label.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(e.width - 4, 120)))
        return label

    def _toggle_card(self, parent, key: str, title: str, text: str, unavailable: str | None = None) -> ttk.Frame:
        card = self._card(parent)
        check = ttk.Checkbutton(card, text=title, variable=self.vars[key], style="Card.TCheckbutton")
        check.pack(anchor="w")
        self._description(card, unavailable or text)
        if unavailable:
            check.state(["disabled"])
            if sys.platform == "win32":
                ttk.Button(
                    card, text="Open power settings", command=lambda: os.startfile("ms-settings:powersleep")
                ).pack(anchor="w", pady=(8, 0))
        return card

    def _slider_card(self, parent, toggle_key, value_key, title, text, low, high, unit="%", step=5) -> None:
        self._sliders_card(parent, toggle_key, title, text, [(value_key, None, low, high, unit, step)])

    def _sliders_card(self, parent, toggle_key, title, text, sliders) -> None:
        """A toggle with one or more sliders; each slider is (key, caption, low, high, unit, step).

        A lone slider shows its value on the title row; several get a captioned row each.
        """
        card = self._card(parent)
        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill="x")
        toggle = self.vars[toggle_key]
        ttk.Checkbutton(top, text=title, variable=toggle, style="Card.TCheckbutton").pack(side="left")
        widgets = []
        for key, caption, low, high, unit, step in sliders:
            value = self.vars[key]
            row = top if caption is None else ttk.Frame(card, style="Card.TFrame")
            if caption is not None:
                row.pack(fill="x", pady=(8, 0))
                ttk.Label(row, text=caption, style="Card.TLabel").pack(side="left")
            value_label = ttk.Label(row, style="Value.TLabel")
            value_label.pack(side="right")
            slider = ttk.Scale(
                card, from_=low, to=high, variable=value, orient="horizontal",
                command=lambda v, value=value, low=low, step=step: value.set(max(low, round(float(v) / step) * step)),
            )
            slider.pack(fill="x", pady=(8 if caption is None else 2, 0))
            widgets.append((value, value_label, slider, unit))
        self._description(card, text)

        def refresh(*_):
            on = toggle.get()
            for value, label, slider, unit in widgets:
                label.configure(text=f"{value.get():.0f}{unit}", foreground=COLORS["accent" if on else "idle"])
                slider.state(["!disabled"] if on else ["disabled"])

        toggle.trace_add("write", refresh)
        for value, *_ in widgets:
            value.trace_add("write", refresh)
        refresh()

    # --- Pages ----------------------------------------------------------------

    def _build_overview(self, notebook) -> ttk.Frame:
        page = self._page(notebook)

        card = self._card(page)
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        self.battery_canvas = tk.Canvas(row, width=96, height=52, bg=COLORS["card"], highlightthickness=0)
        self.battery_canvas.pack(side="left", padx=(0, 16))
        info = ttk.Frame(row, style="Card.TFrame")
        info.pack(side="left", fill="x", expand=True)
        self.percent_label = ttk.Label(info, text="--", style="Big.TLabel")
        self.percent_label.pack(anchor="w")
        self.status_label = ttk.Label(info, text="Checking your battery...", style="Card.TLabel")
        self.status_label.pack(anchor="w")
        self.pill = tk.Label(card, font=(FONT, 9, "bold"), fg="white", padx=10, pady=3)
        self.pill.pack(anchor="w", pady=(12, 0))
        self.active_label = self._description(card, "")

        self._toggle_card(
            page,
            "enabled",
            "Save battery automatically when unplugged",
            "Battop applies the changes you pick under “Power saving” and “Apps” "
            "whenever you unplug, and undoes them as soon as you plug back in.",
        )

        card = self._card(page, expand=True)
        ttk.Label(card, text="Recent activity", style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        self.activity = scrolledtext.ScrolledText(
            card, height=6, wrap="word", relief="flat", font=(FONT, 9),
            bg=COLORS["bg"], fg=COLORS["text"], borderwidth=0, padx=8, pady=6,
        )
        self.activity.pack(fill="both", expand=True)
        self.activity.configure(state="disabled")
        return page

    def _build_power_page(self, notebook) -> ttk.Frame:
        page = self._page(notebook)
        supported = self.platform.supported_keys
        if "power_mode" in supported:
            self._toggle_card(
                page,
                "power_mode_enabled",
                "Use “Best power efficiency” mode",
                "Switches Windows to its most efficient power mode. Your previous mode comes back when you plug in.",
                unavailable=self.platform.unavailable_reason("power_mode"),
            )
        if "brightness" in supported:
            self._slider_card(
                page, "brightness_enabled", "brightness_percent", "Dim the screen to",
                "The screen is only ever dimmed, never brightened. If you change the brightness "
                "yourself while unplugged, Battop won't touch it when you plug back in.",
                5, 100,
            )
        if "cpu_limit" in supported:
            self._slider_card(
                page, "cpu_limit_enabled", "cpu_max_percent", "Limit processor speed to",
                "Lower values keep the laptop cooler and the battery going longer, "
                "but apps may feel slower. 70-90% is a good balance.",
                30, 100,
            )
        if "battery_saver" in supported:
            self._slider_card(
                page, "battery_saver_enabled", "battery_saver_threshold", "Turn on battery saver at",
                "Makes Windows' own battery saver kick in earlier. It reduces background activity "
                "and notifications once your charge drops below this level.",
                5, 100,
            )
        return page

    def _build_extras_page(self, notebook) -> ttk.Frame:
        page = self._page(notebook)
        supported = self.platform.supported_keys
        if "refresh_rate" in supported:
            self._toggle_card(
                page,
                "refresh_rate_enabled",
                "Lower the screen refresh rate",
                "Switches to the lowest smooth rate (60 Hz or more). High-refresh screens use noticeably more "
                "power; motion looks a little less fluid. Your normal rate returns when you plug in.",
            )
        if "timeouts" in supported:
            self._sliders_card(
                page, "timeouts_enabled", "Turn off the screen and sleep sooner",
                "Only ever shortens your Windows battery timeouts, never lengthens them.",
                [
                    ("screen_off_minutes", "Turn off screen after", 1, 30, " min", 1),
                    ("sleep_minutes", "Sleep after", 1, 60, " min", 1),
                ],
            )
        if "bluetooth" in supported:
            self._toggle_card(
                page,
                "bluetooth_enabled",
                "Turn Bluetooth off when nothing is connected",
                "If a mouse, headset or other device is connected, Bluetooth is left on. "
                "It is switched back on when you plug in.",
            )
        if "anime_battery" in supported:
            self._build_anime_card(page)
        return page

    def _build_anime_card(self, page) -> None:
        card = self._toggle_card(
            page,
            "anime_battery_enabled",
            "Show the battery level on the AniMe Matrix",
            "While unplugged, the lid display shows a battery icon and your charge. When you plug in, "
            "G-Helper takes the display back and shows whatever you had before.",
        )
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Brightness", style="Card.TLabel").pack(side="left", padx=(0, 12))
        for level, name in ((1, "Dim"), (2, "Medium"), (3, "Full")):
            ttk.Radiobutton(
                row, text=name, value=level, variable=self.vars["anime_brightness"], style="Plain.TRadiobutton"
            ).pack(side="left", padx=(0, 10))
        warning = self.platform.warning("anime_battery")
        if warning:
            note = ttk.Label(card, text="⚠ " + warning, style="Warn.TLabel", justify="left")
            note.pack(fill="x", anchor="w", pady=(8, 0))
            note.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(e.width - 4, 120)))

    def _build_low_battery_page(self, notebook) -> ttk.Frame:
        page = self._page(notebook)
        self._sliders_card(
            page, "low_tier_enabled", "Save extra power when the battery is low",
            "Once the charge drops to the level below, Battop dims the screen further and limits the "
            "processor, even if those options are off above. It backs off again once the charge "
            "recovers a little. Stricter settings you chose elsewhere are kept.",
            [
                ("low_tier_threshold", "When the charge is at or below", 5, 50, "%", 5),
                ("low_brightness_percent", "Dim the screen to", 5, 100, "%", 5),
                ("low_cpu_max_percent", "Limit processor speed to", 30, 100, "%", 5),
            ],
        )
        return page

    def _build_apps_page(self, notebook) -> ttk.Frame:
        page = self._page(notebook)
        self._toggle_card(
            page,
            "app_efficiency_enabled",
            "Put these apps in efficiency mode",
            "Efficiency mode (the same one Task Manager uses) gives an app lower priority and lets "
            "Windows run it on power-saving settings. Good candidates: chat apps, game launchers, "
            "cloud sync and updaters.",
        )
        card = self._card(page, expand=True)
        add_row = ttk.Frame(card, style="Card.TFrame")
        add_row.pack(fill="x")
        self.app_entry = ttk.Combobox(
            add_row, postcommand=lambda: self.app_entry.configure(values=self.platform.running_app_names())
        )
        self.app_entry.pack(side="left", fill="x", expand=True)
        self.app_entry.bind("<Return>", lambda _: self._add_app())
        ttk.Button(add_row, text="Add", command=self._add_app).pack(side="left", padx=(8, 0))
        self._description(card, "Type an app name (e.g. discord.exe) or pick one that's running from the list.")

        self.app_list = tk.Listbox(
            card, height=6, relief="flat", font=(FONT, 10), activestyle="none",
            bg=COLORS["bg"], highlightthickness=0, selectbackground=COLORS["accent"], selectmode="extended",
        )
        self.app_list.pack(fill="both", expand=True, pady=(10, 8))
        self.app_list.bind("<Delete>", lambda _: self._remove_apps())
        ttk.Button(card, text="Remove selected", command=self._remove_apps).pack(anchor="e")
        return page

    def _build_general_page(self, notebook) -> ttk.Frame:
        page = self._page(notebook)
        card = self._card(page)
        ttk.Label(card, text="Startup", style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        self.autostart_var = tk.BooleanVar(value=self.platform.autostart_enabled())
        ttk.Checkbutton(
            card, text="Start Battop when I sign in to Windows", variable=self.autostart_var,
            style="Plain.TCheckbutton", command=self._toggle_autostart,
        ).pack(anchor="w")
        minimized = ttk.Checkbutton(
            card, text="When starting with Windows, stay hidden in the system tray", variable=self.vars["start_minimized"],
            style="Plain.TCheckbutton",
        )
        minimized.pack(anchor="w", pady=(4, 0))
        if not self.tray.available:
            minimized.state(["disabled"])
            self._description(card, "Tray icon unavailable: install it with “pip install pystray Pillow”.")

        card = self._card(page)
        ttk.Label(card, text="Settings", style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Reset to defaults", command=self._reset).pack(side="left")
        ttk.Button(buttons, text="Open data folder", command=lambda: os.startfile(data_dir())).pack(
            side="left", padx=(8, 0)
        )

        card = self._card(page)
        ttk.Label(card, text=f"Battop {__version__}", style="Title.TLabel").pack(anchor="w")
        self._description(
            card,
            "Every change Battop makes is undone when you plug in or quit. If the PC shuts down "
            "while unplugged, the changes are undone the next time Battop starts.",
        )
        return page

    # --- Settings <-> widgets -------------------------------------------------

    def _load(self, settings: Settings) -> None:
        self._loading = True
        try:
            for key, var in self.vars.items():
                var.set(getattr(settings, key))
            self.app_list.delete(0, "end")
            for name in settings.efficiency_apps:
                self.app_list.insert("end", name)
        finally:
            self._loading = False

    def _collect(self) -> Settings:
        values = {
            key: int(round(var.get())) if key in _NUMBER_KEYS else bool(var.get())
            for key, var in self.vars.items()
        }
        values["efficiency_apps"] = tuple(self.app_list.get(0, "end"))
        return replace(self.engine.settings, **values)

    def _schedule_save(self, *_):
        if self._loading:
            return
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(_SAVE_DELAY_MS, self._save)

    def _save(self) -> None:
        self._save_job = None
        try:
            self.engine.submit_settings(self._collect())
        except OSError as exc:
            self.footer.configure(text=f"Couldn't save settings: {exc}", foreground=COLORS["danger"])
            return
        self.footer.configure(text="✓ Saved", foreground=COLORS["accent"])
        self.root.after(
            2000, lambda: self.footer.configure(text="Changes are saved automatically.", foreground=COLORS["muted"])
        )

    def _add_app(self) -> None:
        names = normalize_app_names([self.app_entry.get()])
        existing = self.app_list.get(0, "end")
        for name in names:
            if name not in existing:
                self.app_list.insert("end", name)
                self._schedule_save()
        self.app_entry.set("")

    def _remove_apps(self) -> None:
        for index in reversed(self.app_list.curselection()):
            self.app_list.delete(index)
        self._schedule_save()

    def _toggle_autostart(self) -> None:
        try:
            self.platform.set_autostart(self.autostart_var.get())
        except OSError as exc:
            self.autostart_var.set(self.platform.autostart_enabled())
            messagebox.showerror("Battop", f"Couldn't change the startup setting:\n{exc}")

    def _reset(self) -> None:
        if messagebox.askyesno("Battop", "Reset all settings to their defaults?"):
            self._load(Settings())
            self._schedule_save()

    # --- Live updates ---------------------------------------------------------

    def _poll(self) -> None:
        self._drain_log()
        self._handle_commands()
        self._update_status()
        self.root.after(_POLL_MS, self._poll)

    def _drain_log(self) -> None:
        lines = []
        while True:
            try:
                lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if not lines:
            return
        self.activity.configure(state="normal")
        self.activity.insert("end", "\n".join(lines) + "\n")
        excess = int(self.activity.index("end-1c").split(".")[0]) - _MAX_LOG_LINES
        if excess > 0:
            self.activity.delete("1.0", f"{excess + 1}.0")
        self.activity.see("end")
        self.activity.configure(state="disabled")

    def _handle_commands(self) -> None:
        while True:
            try:
                command = self.tray.commands.get_nowait()
            except queue.Empty:
                return
            if command == "show":
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            elif command == "toggle":
                self.vars["enabled"].set(not self.vars["enabled"].get())
            elif command == "quit":
                self.quit()
                return

    def _update_status(self) -> None:
        status = self.engine.status
        enabled = self.vars["enabled"].get()
        if status is None:
            percent_text, line, fill = "--", "Checking your battery...", None
        elif not status.has_battery:
            percent_text, line, fill = "--", "No battery found, so there's nothing to save on this PC.", None
        else:
            fill = status.percent
            percent_text = f"{status.percent}%" if status.percent is not None else "--"
            if status.on_battery:
                line = "On battery"
                if status.seconds_left:
                    line += f" · about {_format_duration(status.seconds_left)} left"
            elif status.charging:
                line = "Plugged in · charging"
            else:
                line = "Plugged in"
        self.percent_label.configure(text=percent_text)
        self.status_label.configure(text=line)
        self._draw_battery(fill, plugged=status is not None and not status.on_battery)

        if self.engine.saving:
            state, pill, color = "saving", "Battery saving is ON", COLORS["accent"]
        elif not enabled:
            state, pill, color = "paused", "Paused", COLORS["warn"]
        else:
            state, pill, color = "idle", "Standing by · starts when you unplug", COLORS["idle"]
        self.pill.configure(text=pill, bg=color)
        titles = self.engine.active_titles()
        self.active_label.configure(text=("Active now: " + ", ".join(titles)) if titles else "")
        self.tray.update(state, f"Battop - {percent_text} · {pill}", paused=not enabled)

    def _draw_battery(self, percent: int | None, plugged: bool) -> None:
        c = self.battery_canvas
        c.delete("all")
        c.create_rectangle(3, 6, 84, 46, outline=COLORS["text"], width=3)
        c.create_rectangle(85, 18, 92, 34, fill=COLORS["text"], outline="")
        if percent is None:
            return
        color = COLORS["danger"] if percent <= 15 else COLORS["warn"] if percent <= 35 else COLORS["accent"]
        width = max(2, int(74 * percent / 100))
        c.create_rectangle(8, 11, 8 + width, 41, fill=color, outline="")
        if plugged:  # Lightning bolt.
            c.create_polygon(48, 10, 34, 28, 44, 28, 38, 42, 54, 23, 44, 23, 50, 10, fill="white", outline="")

    # --- Window lifecycle -----------------------------------------------------

    def on_close(self) -> None:
        if not self.tray.available:
            self.quit()
            return
        self.root.withdraw()
        if not self._told_about_tray:
            self._told_about_tray = True
            logging.getLogger("battop").info("Battop keeps running in the system tray")

    def quit(self) -> None:
        if self._save_job:
            self.root.after_cancel(self._save_job)
            self._save()
        self.root.withdraw()
        self.root.update()
        self.engine.stop()
        self.tray.stop()
        self.root.destroy()
