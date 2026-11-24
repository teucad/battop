"""Regenerate battop/assets/battop.ico and battop.png from battop/icon.py."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from battop.icon import draw_icon  # noqa: E402

assets = root / "battop" / "assets"
assets.mkdir(exist_ok=True)
draw_icon(256).save(assets / "battop.png")
draw_icon(256).save(assets / "battop.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
print("wrote", assets / "battop.ico", "and", assets / "battop.png")
