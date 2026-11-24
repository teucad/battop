"""The Battop icon (a battery with a bolt), drawn with Pillow so it can be tinted."""

from __future__ import annotations

from PIL import Image, ImageDraw

GREEN = "#16a34a"
_SUPERSAMPLE = 4  # Draw large, then shrink, for smooth edges.


def draw_icon(size: int = 64, color: str = GREEN) -> Image.Image:
    n = size * _SUPERSAMPLE
    scale = n / 64
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return [x0 * scale, y0 * scale, x1 * scale, y1 * scale]

    draw.rounded_rectangle(box(3, 15, 53, 49), radius=9 * scale, outline=color, width=max(1, round(5 * scale)))
    draw.rounded_rectangle(box(54, 26, 61, 38), radius=2 * scale, fill=color)
    bolt = [(34, 21), (24, 35), (31, 35), (28, 44), (41, 28), (34, 28), (37, 21)]
    draw.polygon([(x * scale, y * scale) for x, y in bolt], fill=color)
    return img.resize((size, size), Image.LANCZOS)
