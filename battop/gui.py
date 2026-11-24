"""The settings window (tkinter)."""

from __future__ import annotations

import logging
import queue
import sys
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from . import __version__, theme
from . import i18n
from .i18n import N_, _
from .config import Settings, data_dir, normalize_app_names
from .engine import Engine
from .gui_theme import COLORS, ThemeManager
from .platforms.base import Platform
from .resources import resource_path
from .tray import Tray
from .uninstall import uninstall

FONT = "Segoe UI"
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
    "notifications",
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
    "poll_interval_sec",
)
_THEME_CHOICES = (("system", N_("Follow system")), ("light", N_("Light")), ("dark", N_("Dark")))
_LANGUAGE_CHOICES = ("system", "en", "tr")
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
    if hours:
        return _("{h} h {m} min").format(h=hours, m=minutes)
    return _("{m} min").format(m=minutes)


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
        self._poll_job: str | None = None
        self._log_lines: list[str] = []  # Activity history, re-shown after the window is rebuilt.
        self._loading = False
        self._told_about_tray = False
        self._uninstalled = False
        self._refreshers: list = []
        self._traces: list = []  # (variable, trace id) added by cards, removed on rebuild.
        self.app_list: tk.Listbox | None = None  # Only exists on platforms with per-app efficiency mode.

        global FONT
        self.theme = ThemeManager(root)
        FONT = self.theme.font
        scale = root.winfo_fpixels("1i") / 96
        root.geometry(f"{int(640 * scale)}x{int(660 * scale)}")
        root.minsize(int(580 * scale), int(560 * scale))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Escape>", lambda _: self.on_close())
        self._set_icon()
        self.theme.apply(self._resolved_theme(engine.settings.theme))
        self.vars: dict[str, tk.Variable] = {k: tk.BooleanVar() for k in _BOOL_KEYS}
        self.vars.update({k: tk.DoubleVar() for k in _NUMBER_KEYS})
        for key in ("anime_brightness", "poll_interval_sec"):
            self.vars[key] = tk.IntVar()  # Radio buttons and spinboxes need exact integers.
        self.theme_var = tk.StringVar()
        self.language_var = tk.StringVar()

        self._build_ui()
        self._load(engine.settings)
        for var in (*self.vars.values(), self.theme_var, self.language_var):
            var.trace_add("write", self._schedule_save)

        if start_hidden and tray.available:
            root.withdraw()
        self._poll()

    def _build_ui(self) -> None:
        root, platform = self.root, self.platform
        root.title(_("Battop - Battery Saver"))
        self.notebook = notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=14, pady=(14, 4))
        notebook.enable_traversal()  # Ctrl+Tab / Ctrl+Shift+Tab switch tabs.
        notebook.add(self._build_overview(notebook), text=_("Overview"))
        notebook.add(self._build_power_page(notebook), text=_("Power saving"))
        if platform.supported_keys & {"refresh_rate", "timeouts", "bluetooth", "anime_battery"}:
            notebook.add(self._build_extras_page(notebook), text=_("Extras"))
        notebook.add(self._build_low_battery_page(notebook), text=_("Low battery"))
        if "app_efficiency" in platform.supported_keys:
            notebook.add(self._build_apps_page(notebook), text=_("Apps"))
        notebook.add(self._build_general_page(notebook), text=_("General"))
        self.footer = ttk.Label(root, text=_("Changes are saved automatically."), style="Footer.TLabel")
        self.footer.pack(fill="x", padx=18, pady=(0, 10))
        if self._log_lines:  # Rebuilding after a language change: bring the history back.
            self.activity.configure(state="normal")
            self.activity.insert("end", "\n".join(self._log_lines) + "\n")
            self.activity.see("end")
            self.activity.configure(state="disabled")

    def apply_language(self, setting: str) -> None:
        """Switch language and rebuild the window, keeping every value and the selected tab."""
        current = self._collect()  # Read the widgets (and their translated names) before they change.
        i18n.set_language(i18n.resolve(setting, self.platform.system_language()))
        self._rebuild(current)
        self.tray.retranslate()

    def _rebuild(self, current: Settings) -> None:
        """Recreate every tab (after a language change, or when something became available)."""
        selected = self.notebook.index("current")
        for var, trace_id in self._traces:
            var.trace_remove("write", trace_id)
        self._traces.clear()
        self._refreshers.clear()
        self.app_list = None
        self.notebook.destroy()
        self.footer.destroy()
        self._build_ui()
        self._load(current)
        self.notebook.select(min(selected, len(self.notebook.tabs()) - 1))
        self._update_status()

    def _trace(self, var: tk.Variable, callback) -> None:
        self._traces.append((var, var.trace_add("write", callback)))

    def _theme_names(self) -> dict[str, str]:
        return {key: _(label) for key, label in _THEME_CHOICES}

    def _language_names(self) -> dict[str, str]:
        return {"system": _("Follow system"), **i18n.LANGUAGE_NAMES}

    def _set_icon(self) -> None:
        try:
            if sys.platform == "win32":
                self.root.iconbitmap(default=str(resource_path("assets", "battop.ico")))
            else:
                self._icon_image = ImageTk.PhotoImage(Image.open(resource_path("assets", "battop.png")))
                self.root.iconphoto(True, self._icon_image)
        except (tk.TclError, OSError):
            pass  # A missing icon isn't worth failing over.

    def _resolved_theme(self, setting: str) -> str:
        return theme.resolve(setting, self.platform.system_theme())

    def apply_theme(self, setting: str) -> None:
        self.theme.apply(self._resolved_theme(setting))
        for refresh in self._refreshers:
            refresh()
        self._update_status()

    # --- Layout helpers -----------------------------------------------------

    def _page(self, notebook) -> ttk.Frame:
        page = ttk.Frame(notebook, style="Page.TFrame", padding=(0, 12, 0, 0))
        return page

    def _card(self, parent, expand: bool = False) -> ttk.Frame:
        outer = tk.Frame(parent, highlightthickness=1, bd=0)
        self.theme.track(outer, bg="card", highlightbackground="border")
        outer.pack(fill="both" if expand else "x", expand=expand, pady=(0, 10))
        inner = ttk.Frame(outer, style="Card.TFrame", padding=14)
        inner.pack(fill="both", expand=True)
        return inner

    def _description(self, parent, text: str) -> ttk.Label:
        label = ttk.Label(parent, text=text, style="Muted.TLabel", justify="left")
        label.pack(fill="x", anchor="w", pady=(4, 0))
        label.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(e.width - 4, 120)))
        return label

    def _fix_button(self, card, fix) -> None:
        """`fix` is (button label, callback) from Platform.fix_action, or None."""
        if fix:
            label, callback = fix
            ttk.Button(card, text=label, command=lambda: self._run_fix(callback)).pack(anchor="w", pady=(8, 0))

    def _run_fix(self, callback) -> None:
        try:
            callback()
        except OSError as exc:
            messagebox.showerror(_("Battop"), str(exc))
        # Re-evaluate what is available (after the button's own widget has finished its click).
        self.root.after_idle(lambda: self._rebuild(self._collect()))

    def _availability(self, toggle_key: str, unavailable, fix):
        """Ask the platform whether a card's feature works here, unless the caller already did."""
        if unavailable is None:
            feature = toggle_key.removesuffix("_enabled")
            unavailable = self.platform.unavailable_reason(feature)
            if fix is None:
                fix = self.platform.fix_action(feature)
        return unavailable, fix

    def _toggle_card(self, parent, key: str, title: str, text: str, unavailable=None, fix=None) -> ttk.Frame:
        unavailable, fix = self._availability(key, unavailable, fix)
        card = self._card(parent)
        check = ttk.Checkbutton(card, text=title, variable=self.vars[key], style="Card.TCheckbutton")
        check.pack(anchor="w")
        self._description(card, unavailable or text)
        if unavailable:
            check.state(["disabled"])
            self._fix_button(card, fix)
        return card

    def _slider_card(
        self, parent, toggle_key, value_key, title, text, low, high, unit="%", step=5, unavailable=None, fix=None
    ) -> None:
        self._sliders_card(
            parent, toggle_key, title, text, [(value_key, None, low, high, unit, step)], unavailable, fix
        )

    def _sliders_card(self, parent, toggle_key, title, text, sliders, unavailable=None, fix=None) -> None:
        """A toggle with one or more sliders; each slider is (key, caption, low, high, unit, step).

        A lone slider shows its value on the title row; several get a captioned row each.
        """
        unavailable, fix = self._availability(toggle_key, unavailable, fix)
        card = self._card(parent)
        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill="x")
        toggle = self.vars[toggle_key]
        check = ttk.Checkbutton(top, text=title, variable=toggle, style="Card.TCheckbutton")
        check.pack(side="left")
        if unavailable:
            check.state(["disabled"])
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
            # Arrow keys move by one step (the default increments would be rounded away).
            for keys, direction in ((("<Left>", "<Down>"), -1), (("<Right>", "<Up>"), 1)):
                for key_name in keys:
                    slider.bind(
                        key_name,
                        lambda e, value=value, low=low, high=high, step=step, d=direction: (
                            value.set(min(high, max(low, round(value.get()) + d * step))),
                            "break",
                        )[1],
                    )
            widgets.append((value, value_label, slider, unit))
        self._description(card, unavailable or text)
        if unavailable:
            self._fix_button(card, fix)

        def refresh(*_):
            on = toggle.get() and not unavailable
            for value, label, slider, unit in widgets:
                label.configure(text=f"{value.get():.0f}{unit}", foreground=COLORS["accent" if on else "idle"])
                slider.state(["!disabled"] if on else ["disabled"])

        self._refreshers.append(refresh)
        self._trace(toggle, refresh)
        for value, *rest in widgets:
            self._trace(value, refresh)
        refresh()

    # --- Pages ----------------------------------------------------------------

    def _build_overview(self, notebook) -> ttk.Frame:
        page = self._page(notebook)

        card = self._card(page)
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        self.battery_canvas = tk.Canvas(row, width=96, height=52, highlightthickness=0)
        self.theme.track(self.battery_canvas, bg="card")
        self.battery_canvas.pack(side="left", padx=(0, 16))
        info = ttk.Frame(row, style="Card.TFrame")
        info.pack(side="left", fill="x", expand=True)
        self.percent_label = ttk.Label(info, text="--", style="Big.TLabel")
        self.percent_label.pack(anchor="w")
        self.status_label = ttk.Label(info, text=_("Checking your battery..."), style="Card.TLabel")
        self.status_label.pack(anchor="w")
        self.pill = tk.Label(card, font=(FONT, 9, "bold"), padx=10, pady=3)
        self.pill.pack(anchor="w", pady=(12, 0))
        self.active_label = self._description(card, "")

        self._toggle_card(
            page,
            "enabled",
            _("Save battery automatically when unplugged"),
            _("Battop applies the changes you pick under “Power saving” and “Apps” "
            "whenever you unplug, and undoes them as soon as you plug back in."),
        )

        card = self._card(page, expand=True)
        ttk.Label(card, text=_("Recent activity"), style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        log_frame = ttk.Frame(card, style="Card.TFrame")
        log_frame.pack(fill="both", expand=True)
        self.activity = tk.Text(
            log_frame, height=6, wrap="word", relief="flat", font=(FONT, 9), borderwidth=0, padx=8, pady=6,
            highlightthickness=0, takefocus=False,
        )
        self.theme.track(self.activity, bg="field", fg="text")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.activity.yview)
        self.activity.configure(yscrollcommand=scrollbar.set, state="disabled")
        scrollbar.pack(side="right", fill="y")
        self.activity.pack(side="left", fill="both", expand=True)
        return page

    def _build_power_page(self, notebook) -> ttk.Frame:
        page = self._page(notebook)
        supported = self.platform.supported_keys
        if "power_mode" in supported:
            self._toggle_card(
                page,
                "power_mode_enabled",
                _("Use the most efficient power mode"),
                _("Switches to the most power-efficient mode (“Best power efficiency” on Windows, “Power Saver” on Linux). "
                  "Your previous mode comes back when you plug in."),
                unavailable=self.platform.unavailable_reason("power_mode"),
                fix=self.platform.fix_action("power_mode"),
            )
        if "brightness" in supported:
            self._slider_card(
                page, "brightness_enabled", "brightness_percent", _("Dim the screen to"),
                _("The screen is only ever dimmed, never brightened. If you change the brightness "
                "yourself while unplugged, Battop won't touch it when you plug back in."),
                5, 100,
            )
        if "cpu_limit" in supported:
            self._slider_card(
                page, "cpu_limit_enabled", "cpu_max_percent", _("Limit processor speed to"),
                _("Lower values keep the laptop cooler and the battery going longer, "
                "but apps may feel slower. 70-90% is a good balance."),
                30, 100,
                unavailable=self.platform.unavailable_reason("cpu_limit"),
                fix=self.platform.fix_action("cpu_limit"),
            )
        if "battery_saver" in supported:
            self._slider_card(
                page, "battery_saver_enabled", "battery_saver_threshold", _("Turn on battery saver at"),
                _("Makes Windows' own battery saver kick in earlier. It reduces background activity "
                "and notifications once your charge drops below this level."),
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
                _("Lower the screen refresh rate"),
                _("Switches to the lowest smooth rate (60 Hz or more). High-refresh screens use noticeably more "
                "power; motion looks a little less fluid. Your normal rate returns when you plug in."),
            )
        if "timeouts" in supported:
            self._sliders_card(
                page, "timeouts_enabled", _("Turn off the screen and sleep sooner"),
                _("Only ever shortens your screen-off and sleep timeouts on battery, never lengthens them."),
                [
                    ("screen_off_minutes", _("Turn off screen after"), 1, 30, _(" min"), 1),
                    ("sleep_minutes", _("Sleep after"), 1, 60, _(" min"), 1),
                ],
            )
        if "bluetooth" in supported:
            self._toggle_card(
                page,
                "bluetooth_enabled",
                _("Turn Bluetooth off when nothing is connected"),
                _("If a mouse, headset or other device is connected, Bluetooth is left on. "
                "It is switched back on when you plug in."),
            )
        if "anime_battery" in supported:
            self._build_anime_card(page)
        return page

    def _build_anime_card(self, page) -> None:
        card = self._toggle_card(
            page,
            "anime_battery_enabled",
            _("Show the battery level on the AniMe Matrix"),
            _("While unplugged, the lid display shows a battery icon and your charge. When you plug in, "
            "G-Helper takes the display back and shows whatever you had before."),
        )
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text=_("Brightness"), style="Card.TLabel").pack(side="left", padx=(0, 12))
        for level, name in ((1, _("Dim")), (2, _("Medium")), (3, _("Full"))):
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
            page, "low_tier_enabled", _("Save extra power when the battery is low"),
            _("Once the charge drops to the level below, Battop dims the screen further and limits the "
            "processor, even if those options are off above. It backs off again once the charge "
            "recovers a little. Stricter settings you chose elsewhere are kept."),
            [
                ("low_tier_threshold", _("When the charge is at or below"), 5, 50, "%", 5),
                ("low_brightness_percent", _("Dim the screen to"), 5, 100, "%", 5),
                ("low_cpu_max_percent", _("Limit processor speed to"), 30, 100, "%", 5),
            ],
        )
        return page

    def _build_apps_page(self, notebook) -> ttk.Frame:
        page = self._page(notebook)
        self._toggle_card(
            page,
            "app_efficiency_enabled",
            _("Put these apps in efficiency mode"),
            _("Gives an app lower priority so it uses less power (on Windows this is the same Efficiency "
            "mode Task Manager uses). Good candidates: chat apps, game launchers, cloud sync and updaters."),
            unavailable=self.platform.unavailable_reason("app_efficiency"),
            fix=self.platform.fix_action("app_efficiency"),
        )
        card = self._card(page, expand=True)
        add_row = ttk.Frame(card, style="Card.TFrame")
        add_row.pack(fill="x")
        self.app_entry = ttk.Combobox(
            add_row, postcommand=lambda: self.app_entry.configure(values=self.platform.running_app_names())
        )
        self.app_entry.pack(side="left", fill="x", expand=True)
        self.app_entry.bind("<Return>", lambda _: self._add_app())
        ttk.Button(add_row, text=_("Add"), command=self._add_app).pack(side="left", padx=(8, 0))
        self._description(card, _("Type an app name (e.g. discord) or pick one that's running from the list."))

        self.app_list = tk.Listbox(
            card, height=6, relief="flat", font=(FONT, 10), activestyle="none", highlightthickness=0,
            selectmode="extended",
        )
        self.theme.track(
            self.app_list, bg="field", fg="text", selectbackground="accent", selectforeground="on_accent"
        )
        self.app_list.pack(fill="both", expand=True, pady=(10, 8))
        self.app_list.bind("<Delete>", lambda _: self._remove_apps())
        ttk.Button(card, text=_("Remove selected"), command=self._remove_apps).pack(anchor="e")
        return page

    def _build_general_page(self, notebook) -> ttk.Frame:
        page = self._page(notebook)
        card = self._card(page)
        ttk.Label(card, text=_("Startup"), style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        self.autostart_var = tk.BooleanVar(value=self.platform.autostart_enabled())
        ttk.Checkbutton(
            card, text=_("Start Battop when I sign in"), variable=self.autostart_var,
            style="Plain.TCheckbutton", command=self._toggle_autostart,
        ).pack(anchor="w")
        minimized = ttk.Checkbutton(
            card, text=_("When starting at sign-in, stay hidden in the system tray"), variable=self.vars["start_minimized"],
            style="Plain.TCheckbutton",
        )
        minimized.pack(anchor="w", pady=(4, 0))
        if not self.tray.available:
            minimized.state(["disabled"])
            self._description(card, _("Tray icon unavailable: install it with “pip install pystray Pillow”."))

        card = self._card(page)
        ttk.Label(card, text=_("Appearance and behaviour"), style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text=_("Theme"), style="Card.TLabel", width=10).pack(side="left", padx=(0, 10))
        self.theme_box = ttk.Combobox(
            row, textvariable=self.theme_var, state="readonly", width=14, values=list(self._theme_names().values())
        )
        self.theme_box.pack(side="left")
        self.theme_box.bind("<<ComboboxSelected>>", lambda event: self.apply_theme(self._theme_setting()))
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text=_("Language"), style="Card.TLabel", width=10).pack(side="left", padx=(0, 10))
        self.language_box = ttk.Combobox(
            row, textvariable=self.language_var, state="readonly", width=14, values=list(self._language_names().values())
        )
        self.language_box.pack(side="left")
        # Rebuild after the combobox has finished handling its own event.
        self.language_box.bind(
            "<<ComboboxSelected>>",
            lambda event: self.root.after_idle(self.apply_language, self._language_setting()),
        )
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text=_("Check the power status at least every"), style="Card.TLabel").pack(side="left")
        ttk.Spinbox(row, from_=5, to=300, increment=5, width=5, textvariable=self.vars["poll_interval_sec"]).pack(
            side="left", padx=8
        )
        ttk.Label(row, text=_("seconds"), style="Card.TLabel").pack(side="left")
        ttk.Checkbutton(
            card, text=_("Show a notification when saving turns on or off"), variable=self.vars["notifications"],
            style="Plain.TCheckbutton",
        ).pack(anchor="w", pady=(8, 0))

        card = self._card(page)
        ttk.Label(card, text=_("Settings"), style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.pack(fill="x")
        ttk.Button(buttons, text=_("Reset to defaults"), command=self._reset).pack(side="left")
        ttk.Button(buttons, text=_("Open data folder"), command=lambda: self.platform.open_path(data_dir())).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(buttons, text=_("Remove Battop from this PC\u2026"), command=self._uninstall).pack(
            side="left", padx=(8, 0)
        )

        card = self._card(page)
        ttk.Label(card, text=f"Battop {__version__}", style="Title.TLabel").pack(anchor="w")
        self._description(
            card,
            _("Every change Battop makes is undone when you plug in or quit. If the PC shuts down "
            "while unplugged, the changes are undone the next time Battop starts."),
        )
        return page

    # --- Settings <-> widgets -------------------------------------------------

    def _load(self, settings: Settings) -> None:
        self._loading = True
        try:
            for key, var in self.vars.items():
                var.set(getattr(settings, key))
            self.theme_var.set(self._theme_names()[settings.theme])
            self.language_var.set(self._language_names()[settings.language])
            if self.app_list is not None:
                self.app_list.delete(0, "end")
                for name in settings.efficiency_apps:
                    self.app_list.insert("end", name)
        finally:
            self._loading = False

    def _collect(self) -> Settings:
        current = self.engine.settings
        values = {}
        for key, var in self.vars.items():
            if key not in _NUMBER_KEYS:
                values[key] = bool(var.get())
                continue
            try:
                values[key] = int(round(var.get()))
            except (tk.TclError, ValueError):  # E.g. half-typed text in the interval box.
                values[key] = getattr(current, key)
        if self.app_list is not None:
            values["efficiency_apps"] = tuple(self.app_list.get(0, "end"))
        values["theme"] = self._theme_setting()
        values["language"] = self._language_setting()
        return replace(self.engine.settings, **values)

    def _theme_setting(self) -> str:
        by_name = {name: key for key, name in self._theme_names().items()}
        return by_name.get(self.theme_var.get(), "system")

    def _language_setting(self) -> str:
        by_name = {name: key for key, name in self._language_names().items()}
        return by_name.get(self.language_var.get(), "system")

    def _schedule_save(self, *_):
        if self._loading:
            return
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(_SAVE_DELAY_MS, self._save)

    def _save(self) -> None:
        self._save_job = None
        if self._uninstalled:
            return
        try:
            self.engine.submit_settings(self._collect())
        except OSError as exc:
            self.footer.configure(text=_("Couldn't save settings: {error}").format(error=exc), foreground=COLORS["danger"])
            return
        self.footer.configure(text=_("✓ Saved"), foreground=COLORS["accent"])
        self.root.after(
            2000, lambda: self.footer.configure(text=_("Changes are saved automatically."), foreground=COLORS["muted"])
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
            messagebox.showerror(_("Battop"), _("Couldn't change the startup setting:") + f"\n{exc}")

    def _reset(self) -> None:
        if messagebox.askyesno(_("Battop"), _("Reset all settings to their defaults?")):
            self._load(Settings())
            self._schedule_save()

    def _uninstall(self) -> None:
        if not messagebox.askyesno(
            _("Battop"),
            _("Remove Battop from this PC?\n\nThis restores your normal settings, stops Battop starting at "
            "sign-in, deletes its settings and logs, and closes Battop. The Battop program files stay where "
            "they are, so you can delete that folder afterwards."),
            icon="warning",
        ):
            return
        self._cancel_timers()
        self._uninstalled = True
        self.engine.stop()
        problems = uninstall(self.platform)
        self.tray.stop()
        if problems:
            messagebox.showwarning(_("Battop"), _("Battop was removed, but:") + "\n\n" + "\n".join(problems))
        else:
            messagebox.showinfo(_("Battop"), _("Battop has been removed from this PC. You can delete its folder now."))
        self.root.destroy()

    # --- Live updates ---------------------------------------------------------

    def _poll(self) -> None:
        self._drain_log()
        self._handle_commands()
        self._update_status()
        self._poll_job = self.root.after(_POLL_MS, self._poll)

    def _drain_log(self) -> None:
        lines = []
        while True:
            try:
                lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if not lines:
            return
        self._log_lines = (self._log_lines + lines)[-_MAX_LOG_LINES:]
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
            elif command == "theme":
                if self._theme_setting() == "system":
                    self.apply_theme("system")
            elif command == "toggle":
                self.vars["enabled"].set(not self.vars["enabled"].get())
            elif command == "quit":
                self.quit()
                return

    def _update_status(self) -> None:
        status = self.engine.status
        enabled = self.vars["enabled"].get()
        if status is None:
            percent_text, line, fill = "--", _("Checking your battery..."), None
        elif not status.has_battery:
            percent_text, line, fill = "--", _("No battery found, so there's nothing to save on this PC."), None
        else:
            fill = status.percent
            percent_text = f"{status.percent}%" if status.percent is not None else "--"
            if status.on_battery:
                line = _("On battery")
                if status.seconds_left:
                    line += _(" · about {time} left").format(time=_format_duration(status.seconds_left))
            elif status.charging:
                line = _("Plugged in · charging")
            else:
                line = _("Plugged in")
        self.percent_label.configure(text=percent_text)
        self.status_label.configure(text=line)
        self._draw_battery(fill, plugged=status is not None and not status.on_battery)

        if self.engine.saving:
            state, pill, colors = "saving", _("Battery saving is ON"), (COLORS["accent"], COLORS["on_accent"])
        elif not enabled:
            state, pill, colors = "paused", _("Paused"), (COLORS["warn"], COLORS["on_accent"])
        else:
            state, pill = "idle", _("Standing by · starts when you unplug")
            colors = (COLORS["pill_idle_bg"], COLORS["pill_idle_fg"])
        self.pill.configure(text=pill, bg=colors[0], fg=colors[1])
        titles = self.engine.active_titles()
        self.active_label.configure(text=_("Active now: {titles}").format(titles=", ".join(_(title) for title in titles)) if titles else "")
        self.tray.update(state, _("Battop - {percent} · {state}").format(percent=percent_text, state=pill), paused=not enabled)

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
            c.create_polygon(48, 10, 34, 28, 44, 28, 38, 42, 54, 23, 44, 23, 50, 10, fill=COLORS["on_accent"], outline=COLORS["text"])

    # --- Window lifecycle -----------------------------------------------------

    def on_close(self) -> None:
        if not self.tray.available:
            self.quit()
            return
        self.root.withdraw()
        if not self._told_about_tray:
            self._told_about_tray = True
            logging.getLogger("battop").info("Battop keeps running in the system tray")

    def _cancel_timers(self) -> None:
        """Stop the polling and delayed-save timers (they must not fire into a destroyed window)."""
        for job in (self._poll_job, self._save_job):
            if job:
                self.root.after_cancel(job)
        self._poll_job = self._save_job = None

    def quit(self) -> None:
        if self._save_job:
            self.root.after_cancel(self._save_job)
            self._save()
        self._cancel_timers()
        self.root.withdraw()
        self.root.update()
        self.engine.stop()
        self.tray.stop()
        self.root.destroy()
