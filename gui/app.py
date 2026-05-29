"""
QUBE Signal Identifier — Launcher wrapper.

Ejecutar con: uv run python gui/app.py
"""

import sys
from pathlib import Path

src_dir = str(Path(__file__).resolve().parent.parent / "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from qube_ui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
