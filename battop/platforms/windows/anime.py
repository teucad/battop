"""ASUS AniMe Matrix (ROG Strix SCAR 16/18, G635/G835 and similar) battery display.

The USB protocol and LED layout were worked out by the G-Helper and asusctl projects;
this is an independent implementation of the same device facts.

Packets are 640-byte HID feature reports starting with report ID 0x5E. The display is
810 LEDs arranged as a 45-degree-rotated triangle; `led_index` maps ordinary bitmap
coordinates onto it (same mapping G-Helper uses for its clock and text modes, so the
picture appears the right way up).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from ...i18n import _
from . import hid

log = logging.getLogger(__name__)

VENDOR_ID = 0x0B05
PRODUCT_ID = 0x193B
REPORT_ID = 0x5E
REPORT_LENGTH = 640

LED_COUNT = 810
ROWS = 68
FULL_ROWS = 29
PAGE_LENGTH = 490

BRIGHTNESS_NAMES = {1: "Dim", 2: "Medium", 3: "Full"}

# --- Packets ---------------------------------------------------------------------


def packet(*payload: int | bytes) -> bytes:
    data = bytearray([REPORT_ID])
    for part in payload:
        data += bytes([part]) if isinstance(part, int) else part
    if len(data) > REPORT_LENGTH - 1:  # The last byte of the report is never used.
        raise ValueError("payload too long")
    return bytes(data.ljust(REPORT_LENGTH, b"\0"))


WAKE_UP = packet(b"ASUS Tech.Inc.")
BUILT_IN_ANIMATION_OFF = packet(0xC4, 0x01, 0x80)
DISPLAY_ON = packet(0xC3, 0x01, 0x00)
END_OF_FRAME = packet(0xC0, 0x03)


def brightness_packet(level: int) -> bytes:
    """level: 0 = off, 1 = dim, 2 = medium, 3 = full."""
    if not 0 <= level <= 3:
        raise ValueError("brightness must be 0-3")
    return packet(0xC0, 0x04, level)


def frame_packets(leds: bytes) -> list[bytes]:
    """Split one frame (one byte per LED) into the packets that draw it."""
    if len(leds) != LED_COUNT:
        raise ValueError(f"a frame has {LED_COUNT} LEDs, got {len(leds)}")
    packets = []
    for start in range(0, LED_COUNT, PAGE_LENGTH):
        end = min(LED_COUNT, start + PAGE_LENGTH)
        # Addresses are 1-based, and both fields are little-endian 16-bit numbers.
        packets.append(
            packet(0xC0, 0x02, (start + 1).to_bytes(2, "little"), (end - start).to_bytes(2, "little"), leds[start:end])
        )
    packets.append(END_OF_FRAME)
    return packets


# --- LED layout ------------------------------------------------------------------


def _width(y: int) -> int:
    return 1 + y // 2


def _first_x(y: int) -> int:
    return (max(0, y - FULL_ROWS) + 1) // 2  # ceil(max(0, y - 29) / 2)


_ROW_START: list[int] = []
_total = 0
for _y in range(ROWS):
    _ROW_START.append(_total)
    _total += _width(_y) - _first_x(_y)
assert _total == LED_COUNT


def led_index(x: int, y: int) -> int | None:
    """LED for pixel (x, y) of a bitmap, or None if that pixel isn't on the display.

    Only bitmap rows 24-38 reach the LEDs; columns 5-44 of those rows all do.
    """
    dx, dy = x + 9, y - 24
    plane_x, plane_y = int((dx - dy) / 2), dx + dy  # int() truncates toward zero.
    if dx - dy == -1:
        plane_x = -1
    if not 0 <= plane_y < ROWS or not _first_x(plane_y) <= plane_x < _width(plane_y):
        return None
    return _ROW_START[plane_y] - _first_x(plane_y) + plane_x


# Safe drawing area: every pixel inside it is a real LED.
CANVAS_X, CANVAS_Y, CANVAS_W, CANVAS_H = 5, 24, 40, 15

_DIGITS = {
    "0": [".##.", "#..#", "#..#", "#..#", "#..#", "#..#", ".##."],
    "1": ["..#.", ".##.", "..#.", "..#.", "..#.", "..#.", ".###"],
    "2": [".##.", "#..#", "...#", "..#.", ".#..", "#...", "####"],
    "3": [".##.", "#..#", "...#", "..#.", "...#", "#..#", ".##."],
    "4": ["...#", "..##", ".#.#", "#..#", "####", "...#", "...#"],
    "5": ["####", "#...", "###.", "...#", "...#", "#..#", ".##."],
    "6": [".##.", "#...", "#...", "###.", "#..#", "#..#", ".##."],
    "7": ["####", "...#", "..#.", "..#.", ".#..", ".#..", ".#.."],
    "8": [".##.", "#..#", "#..#", ".##.", "#..#", "#..#", ".##."],
    "9": [".##.", "#..#", "#..#", ".###", "...#", "...#", ".##."],
}


def battery_pixels(percent: int) -> set[tuple[int, int]]:
    """Pixels (u, v) of a battery icon with the charge number, in a 40x15 canvas."""
    percent = max(0, min(100, percent))
    pixels: set[tuple[int, int]] = set()
    for u in range(20):  # Body outline, 20x13.
        pixels |= {(u, 1), (u, 13)}
    for v in range(1, 14):
        pixels |= {(0, v), (19, v)}
    pixels |= {(u, v) for u in (20, 21) for v in range(5, 10)}  # Terminal nub.
    inner = 16  # Fill area: u 2-17, v 3-11.
    filled = round(inner * percent / 100)
    if percent > 0:
        filled = max(1, filled)
    pixels |= {(2 + i, v) for i in range(filled) for v in range(3, 12)}
    for n, digit in enumerate(str(percent)):  # Number to the right, 4x7 digits, vertically centred.
        for row, line in enumerate(_DIGITS[digit]):
            for col, ch in enumerate(line):
                if ch == "#":
                    pixels.add((24 + n * 5 + col, 4 + row))
    return pixels


def render_battery(percent: int) -> bytes:
    """One frame (one byte per LED) showing the battery icon and charge."""
    leds = bytearray(LED_COUNT)
    for u, v in battery_pixels(percent):
        index = led_index(CANVAS_X + u, CANVAS_Y + v)
        if index is not None:
            leds[index] = 255
    return bytes(leds)


# --- G-Helper compatibility --------------------------------------------------------

_MATRIX_MODES = {0: "Banner", 1: "Logo", 2: "Picture", 3: "Clock", 4: "Audio", 5: "Text"}


def ghelper_config_path() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "GHelper" / "config.json"


def ghelper_conflict(config_path: Path | None = None) -> str | None:
    """Warn about G-Helper matrix settings that would fight with Battop (read-only check)."""
    try:
        config = json.loads((config_path or ghelper_config_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(config, dict):
        return None
    if config.get("matrix_auto") == 1:
        return _(
            "G-Helper is set to turn the matrix off on battery (“Auto” turn off when unplugged), "
            "so the battery level won't show. Turn that option off in G-Helper."
        )
    mode = config.get("matrix_running", 0)
    animated = {3: "Clock", 4: "Audio", 2: "Picture"}.get(mode)
    scrolling_text = mode == 5 and config.get("matrix_text_running") == 1
    if animated in ("Clock", "Audio") or scrolling_text:
        name = "scrolling Text" if scrolling_text else animated
        return _(
            "G-Helper is showing {name}, which redraws the matrix constantly and will flicker against "
            "Battop. Switch G-Helper's matrix to a static mode (Text without scrolling, Logo or Banner)."
        ).format(name=name)
    if animated == "Picture":
        return _("If your G-Helper picture is an animated GIF, it will flicker against Battop.")
    return None


# --- Device ----------------------------------------------------------------------


def find_interface() -> hid.HidInterface | None:
    """The AniMe control interface: the one that takes 640-byte feature reports."""
    for interface in hid.find_interfaces(VENDOR_ID, PRODUCT_ID):
        if interface.feature_report_length == REPORT_LENGTH:
            return interface
    return None


def is_present() -> bool:
    try:
        return find_interface() is not None
    except OSError:
        return False


class AnimeMatrix:
    def __init__(self, device: hid.HidDevice):
        self._device = device

    @classmethod
    def open(cls) -> AnimeMatrix:
        interface = find_interface()
        if interface is None:
            raise OSError("AniMe Matrix not found")
        return cls(hid.HidDevice.open(interface.path))

    def close(self) -> None:
        self._device.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def start(self, brightness: int) -> None:
        """Take over the display: static frames only, at the given brightness."""
        for data in (WAKE_UP, brightness_packet(brightness), DISPLAY_ON, BUILT_IN_ANIMATION_OFF):
            self._device.set_feature(data)

    def draw(self, leds: bytes) -> None:
        for data in frame_packets(leds):
            self._device.set_feature(data)

    def show_battery(self, percent: int) -> None:
        self.draw(render_battery(percent))

    def clear(self) -> None:
        self.draw(bytes(LED_COUNT))
