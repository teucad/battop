"""Optional system-tray icon (needs `pystray` and `Pillow`)."""

from __future__ import annotations

import queue

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:  # Battop still works, just without a tray icon.
    pystray = None

_COLORS = {"saving": "#16a34a", "idle": "#6b7280", "paused": "#d97706"}


def _battery_image(color: str):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((4, 16, 54, 48), radius=6, outline=color, width=5)
    draw.rectangle((54, 26, 60, 38), fill=color)
    draw.rectangle((12, 24, 46, 40), fill=color)
    return img


class Tray:
    """Tray menu clicks are posted as strings ('show', 'toggle', 'quit') on `commands`."""

    available = pystray is not None

    def __init__(self, commands: queue.Queue):
        self.commands = commands
        self._icon = None
        self._state = None
        self._paused = False

    def start(self) -> None:
        if not self.available:
            return
        post = self.commands.put
        menu = pystray.Menu(
            pystray.MenuItem("Open Battop", lambda: post("show"), default=True),
            pystray.MenuItem(
                "Pause battery saving", lambda: post("toggle"), checked=lambda _: self._paused
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: post("quit")),
        )
        self._icon = pystray.Icon("battop", _battery_image(_COLORS["idle"]), "Battop", menu)
        self._icon.run_detached()

    def update(self, state: str, tooltip: str, paused: bool) -> None:
        """`state` is 'saving', 'idle' or 'paused'."""
        if self._icon is None:
            return
        if state != self._state:
            self._state = state
            self._icon.icon = _battery_image(_COLORS[state])
        self._icon.title = tooltip
        if paused != self._paused:
            self._paused = paused
            self._icon.update_menu()

    def notify(self, title: str, message: str) -> None:
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
            except Exception:  # Notifications are best-effort.
                pass

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
