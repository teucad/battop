"""Colour palettes for the settings window."""

from __future__ import annotations

LIGHT = {
    "bg": "#f3f5f8",
    "card": "#ffffff",
    "border": "#d5dae3",
    "text": "#1f2937",
    "muted": "#556070",
    "accent": "#15803d",
    "warn": "#b45309",
    "danger": "#b91c1c",
    "idle": "#9ca3af",  # Disabled controls only (exempt from contrast rules).
    "on_accent": "#ffffff",  # Text on accent / warn backgrounds.
    "pill_idle_bg": "#4b5563",
    "pill_idle_fg": "#ffffff",
    "field": "#eef1f6",  # Text boxes and list backgrounds.
    "switch_off": "#8a94a6",
}

DARK = {
    "bg": "#0f1520",
    "card": "#1a2230",
    "border": "#2f3a4d",
    "text": "#eef1f6",
    "muted": "#a3adbd",
    "accent": "#4ade80",
    "warn": "#fbbf24",
    "danger": "#f87171",
    "idle": "#5b6678",
    "on_accent": "#0b1220",
    "pill_idle_bg": "#374151",
    "pill_idle_fg": "#f3f4f6",
    "field": "#111826",
    "switch_off": "#6b7689",
}

PALETTES = {"light": LIGHT, "dark": DARK}

# (foreground, background) pairs that must stay readable (WCAG AA, 4.5:1).
READABLE_PAIRS = [
    ("text", "bg"), ("text", "card"), ("text", "field"),
    ("muted", "bg"), ("muted", "card"),
    ("accent", "card"), ("warn", "card"), ("danger", "card"),
    ("on_accent", "accent"), ("on_accent", "warn"),
    ("pill_idle_fg", "pill_idle_bg"),
]


def _channel(value: int) -> float:
    v = value / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def resolve(setting: str, system_theme: str) -> str:
    """'light' or 'dark' for a theme setting of 'system', 'light' or 'dark'."""
    return setting if setting in PALETTES else (system_theme if system_theme in PALETTES else "light")
