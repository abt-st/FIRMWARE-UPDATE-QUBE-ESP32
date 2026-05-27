"""
QUBE Signal Identifier — Launcher
Arquitectura: ESP32 + L298N + INA219

Uso:
    python gui/app.py

Este archivo es un wrapper delgado. La implementacion completa
se encuentra en src/qube_ui/app.py.

Requiere:
    uv sync (instala todas las dependencias)
"""

import sys
from pathlib import Path

# Agregar src/ al path para importar qube_ui
src_dir = str(Path(__file__).parent.parent / "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from qube_ui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
