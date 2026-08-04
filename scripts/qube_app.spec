# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado de la app de escritorio con PyInstaller.

    uv run pyinstaller scripts/qube_app.spec --noconfirm
    dist/QubeApp/QubeApp.exe

**onedir, no onefile.** Un `--onefile` se descomprime entero en `%TEMP%` en cada
arranque: con Qt son varios segundos de espera antes de ver la ventana, cada vez. La
carpeta arranca en el acto y se copia igual a un pendrive.

**Con consola, a propósito.** No es una app de escritorio de consumo: imprime el estado
del enlace y `--selftest` reporta ahí la tasa efectiva y las muestras perdidas. Esconder
esa salida en una herramienta de medición sería esconder justo lo que hay que leer.

Las exclusiones no son cosméticas: el entorno del proyecto tiene torch, SB3, mlflow y
matplotlib instalados, y sin excluirlos PyInstaller los arrastra por análisis estático
aunque la app no los use — son GB de bundle.
"""

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis

a = Analysis(
    ["../src/qube_app/__main__.py"],
    pathex=["../src"],
    binaries=[],
    datas=[],
    hiddenimports=["qube_app.ui.main_window", "qube_app.fake"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Pesados del entorno de RL/análisis que la app no usa.
        "torch",
        "stable_baselines3",
        "gymnasium",
        "mlflow",
        "matplotlib",
        "scipy",
        "pandas",
        "sympy",
        "IPython",
        "tkinter",
        # Qt que pyqtgraph no necesita para trazas 2D.
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtQuick",
        "PySide6.QtQml",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QubeApp",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="QubeApp",
)
