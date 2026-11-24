"""Check the AniMe Matrix battery display by eye.

    python tools/anime_probe.py info              read-only: list the device's HID interfaces
    python tools/anime_probe.py border            outline the drawable area, with a 2x2 block in its top-left corner
    python tools/anime_probe.py show 64           draw the battery icon at 64%

`border` and `show` draw on the lid for a few seconds (--seconds), then blank it. G-Helper only redraws
its own picture when the power source changes, so afterwards plug/unplug, or change its matrix
setting, to bring your usual display back.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from battop.platforms.windows import anime, hid  # noqa: E402


def info() -> None:
    interfaces = hid.find_interfaces(anime.VENDOR_ID, anime.PRODUCT_ID)
    if not interfaces:
        print("No AniMe Matrix (VID 0B05, PID 193B) found.")
        return
    for i in interfaces:
        use = "  <- used by Battop" if i.feature_report_length == anime.REPORT_LENGTH else ""
        print(f"usage page 0x{i.usage_page:04x}, feature report {i.feature_report_length} bytes{use}")
    print("G-Helper note:", anime.ghelper_conflict() or "its matrix mode is compatible with Battop")


def border_frame() -> bytes:
    leds = bytearray(anime.LED_COUNT)
    cells = set()
    for u in range(anime.CANVAS_W):
        cells |= {(u, 0), (u, anime.CANVAS_H - 1)}
    for v in range(anime.CANVAS_H):
        cells |= {(0, v), (anime.CANVAS_W - 1, v)}
    cells |= {(1, 1), (2, 1), (1, 2), (2, 2)}  # Marks the top-left corner.
    for u, v in cells:
        leds[anime.led_index(anime.CANVAS_X + u, anime.CANVAS_Y + v)] = 255
    return bytes(leds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["info", "border", "show"])
    parser.add_argument("percent", nargs="?", type=int, default=64)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--brightness", type=int, default=2, choices=[1, 2, 3])
    args = parser.parse_args()

    if args.command == "info":
        info()
        return
    frame = border_frame() if args.command == "border" else anime.render_battery(args.percent)
    with anime.AnimeMatrix.open() as matrix:
        matrix.start(args.brightness)
        matrix.draw(frame)
        print(f"Drawing for {args.seconds:g} s...")
        time.sleep(args.seconds)
        matrix.clear()
    print("Done. Plug/unplug (or change G-Helper's matrix setting) to bring back your usual display.")


if __name__ == "__main__":
    main()
