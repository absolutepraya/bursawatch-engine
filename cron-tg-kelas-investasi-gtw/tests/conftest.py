from __future__ import annotations

import sys
from pathlib import Path


BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
sys.path.insert(0, str(BIN.parent.parent / "lib-swing-format" / "bin"))
