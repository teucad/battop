"""Double-click launcher (runs without a console window via pythonw)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from battop.app import main

main()
