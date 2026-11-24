"""Applies a colour palette to the settings window: ttk styles, switches, plain tk widgets."""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from . import theme

# One shared dict, updated in place when the theme changes, so code that reads
# COLORS["x"] at call time always sees the current palette.
COLORS: dict[str, str] = dict(theme.LIGHT)

_FONT_CANDIDATES = ("Segoe UI", "Cantarell", "Noto Sans", "DejaVu Sans", "Ubuntu")
_SWITCH_W, _SWITCH_H, _SWITCH_GAP = 36, 20, 10  # Logical pixels; the gap is transparent padding.


def pick_font(root: tk.Misc) -> str:
    families = set(tkfont.families(root))
    return next((name for name in _FONT_CANDIDATES if name in families), "TkDefaultFont")


def _blend(a: str, b: str, amount: float) -> str:
    """Mix colour `a` into `b` (amount 0 = all b, 1 = all a)."""
    mixed = [
        round(int(a[i : i + 2], 16) * amount + int(b[i : i + 2], 16) * (1 - amount)) for i in (1, 3, 5)
    ]
    return "#" + "".join(f"{v:02x}" for v in mixed)


def _switch_image(on: bool, disabled: bool, scale: float) -> Image.Image:
    c = COLORS
    k = 4  # Supersampling for smooth edges.
    w, h, gap = (round(v * scale) for v in (_SWITCH_W, _SWITCH_H, _SWITCH_GAP))
    img = Image.new("RGBA", ((w + gap) * k, h * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    track = c["accent"] if on else c["switch_off"]
    knob = c["on_accent"] if on else c["card"]
    if disabled:
        track, knob = _blend(track, c["card"], 0.35), _blend(knob, c["card"], 0.6)
    draw.rounded_rectangle([0, 0, w * k - 1, h * k - 1], radius=h * k // 2, fill=track)
    margin = 3 * scale * k
    d = h * k - 2 * margin
    x0 = w * k - margin - d if on else margin
    draw.ellipse([x0, margin, x0 + d, margin + d], fill=knob)
    return img.resize((w + gap, h), Image.LANCZOS)


class ThemeManager:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.font = pick_font(root)
        self.scale = root.winfo_fpixels("1i") / 96
        self.name = "light"
        self._tracked: list[tuple[tk.Misc, dict[str, str]]] = []
        self._images: list[ImageTk.PhotoImage] = []
        self._generation = 0
        self.style = ttk.Style(root)
        self.style.theme_use("clam")

    def track(self, widget: tk.Misc, **options: str) -> None:
        """Keep a plain tk widget coloured: options map a widget option to a palette key."""
        self._tracked.append((widget, options))
        widget.configure(**{opt: COLORS[key] for opt, key in options.items()})

    def apply(self, name: str) -> None:
        self.name = name
        COLORS.clear()
        COLORS.update(theme.PALETTES[name])
        self._configure_styles()
        self._tracked = [(w, o) for w, o in self._tracked if w.winfo_exists()]
        for widget, options in self._tracked:
            widget.configure(**{opt: COLORS[key] for opt, key in options.items()})
        self.root.configure(bg=COLORS["bg"])
        self.root.option_add("*TCombobox*Listbox.background", COLORS["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", COLORS["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", COLORS["on_accent"])
        self._set_title_bar(dark=name == "dark")

    # --- ttk styles -----------------------------------------------------------

    def _configure_styles(self) -> None:
        c, f, s = COLORS, self.font, self.style
        s.configure(".", background=c["bg"], foreground=c["text"], font=(f, 10), bordercolor=c["border"],
                    focuscolor=c["accent"], troughcolor=c["border"])
        s.map(".", foreground=[("disabled", c["idle"])])
        s.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=0, bordercolor=c["border"],
                    lightcolor=c["border"], darkcolor=c["border"])
        s.configure("TNotebook.Tab", padding=(14, 6), background=c["bg"], foreground=c["muted"], borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", c["card"])], foreground=[("selected", c["text"])])
        s.configure("Page.TFrame", background=c["bg"])
        s.configure("Card.TFrame", background=c["card"])
        s.configure("Card.TLabel", background=c["card"], foreground=c["text"])
        s.configure("Title.TLabel", background=c["card"], font=(f, 11, "bold"))
        s.configure("Muted.TLabel", background=c["card"], foreground=c["muted"], font=(f, 9))
        s.configure("Big.TLabel", background=c["card"], font=(f, 26, "bold"))
        s.configure("Value.TLabel", background=c["card"], foreground=c["accent"], font=(f, 11, "bold"))
        s.configure("Footer.TLabel", background=c["bg"], foreground=c["muted"], font=(f, 9))
        s.configure("Warn.TLabel", background=c["card"], foreground=c["warn"], font=(f, 9))
        s.configure("Plain.TRadiobutton", background=c["card"], foreground=c["text"],
                    indicatorbackground=c["field"], indicatorforeground=c["text"])
        s.map("Plain.TRadiobutton", background=[("active", c["card"])], indicatorbackground=[("selected", c["accent"])],
              indicatorforeground=[("selected", c["on_accent"])])
        s.configure("Horizontal.TScale", background=c["card"], troughcolor=c["border"], bordercolor=c["muted"],
                    lightcolor=c["card"], darkcolor=c["card"])
        s.map("Horizontal.TScale", background=[("disabled", c["border"])], bordercolor=[("disabled", c["border"])])
        s.configure("TButton", padding=(12, 5), background=c["field"], foreground=c["text"], bordercolor=c["border"],
                    lightcolor=c["field"], darkcolor=c["field"])
        s.map("TButton", background=[("active", c["border"]), ("pressed", c["border"])],
              foreground=[("disabled", c["idle"])])
        s.configure("TCombobox", fieldbackground=c["field"], background=c["field"], foreground=c["text"],
                    arrowcolor=c["text"], bordercolor=c["border"], lightcolor=c["field"], darkcolor=c["field"])
        s.map("TCombobox", fieldbackground=[("readonly", c["field"])], foreground=[("readonly", c["text"])],
              selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["text"])])
        s.configure("TSpinbox", fieldbackground=c["field"], background=c["field"], foreground=c["text"],
                    arrowcolor=c["text"], bordercolor=c["border"], lightcolor=c["field"], darkcolor=c["field"])
        s.configure("Vertical.TScrollbar", background=c["border"], troughcolor=c["field"], bordercolor=c["field"],
                    arrowcolor=c["muted"], lightcolor=c["border"], darkcolor=c["border"])
        s.map("Vertical.TScrollbar", background=[("active", c["muted"])])
        self._configure_switches()

    def _configure_switches(self) -> None:
        """Toggle switches replace the checkbox indicator (images are redrawn per palette)."""
        self._generation += 1
        element = f"Switch.indicator{self._generation}"
        images = {
            (on, disabled): ImageTk.PhotoImage(_switch_image(on, disabled, self.scale))
            for on in (False, True)
            for disabled in (False, True)
        }
        self._images = list(images.values())  # Tk doesn't keep a reference to these.
        self.style.element_create(
            element, "image", images[(False, False)],
            ("disabled", "selected", images[(True, True)]),
            ("disabled", images[(False, True)]),
            ("selected", images[(True, False)]),
            sticky="w",
        )
        layout = [
            ("Checkbutton.padding", {"sticky": "nswe", "children": [
                (element, {"side": "left", "sticky": ""}),
                ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                    ("Checkbutton.label", {"sticky": "nswe"}),
                ]}),
            ]}),
        ]
        f, c = self.font, COLORS
        for name, font in (("Card.TCheckbutton", (f, 11, "bold")), ("Plain.TCheckbutton", (f, 10))):
            self.style.layout(name, layout)
            self.style.configure(name, background=c["card"], foreground=c["text"], font=font)
            self.style.map(name, background=[("active", c["card"])])

    # --- Windows title bar ----------------------------------------------------

    def _set_title_bar(self, dark: bool) -> None:
        if sys.platform != "win32":
            return
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            value = ctypes.c_int(1 if dark else 0)
            for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on older Windows 10).
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), 4) == 0:
                    break
        except (AttributeError, OSError):
            pass
