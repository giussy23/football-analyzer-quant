# -*- mode: python ; coding: utf-8 -*-
# football_analyzer.spec — empaquetado de AlphaBet (one-folder)
#
# Uso:
#   pyinstaller football_analyzer.spec
# Salida:
#   dist/AlphaBet/AlphaBet.exe

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT   = Path(SPECPATH)          # D:\football_analyzer  (el paquete football_analyzer)
PARENT = ROOT.parent             # D:\  → para que 'football_analyzer' sea importable

# Que collect_submodules('football_analyzer') encuentre el paquete
sys.path.insert(0, str(PARENT))

# ── Datos a empaquetar ──────────────────────────────────────────────────────────
datas  = collect_data_files('customtkinter')                 # temas/fuentes de CTk
datas += [(str(ROOT / 'assets'), 'football_analyzer/assets')]  # logo + icono + svg

# ── Imports que PyInstaller podría no detectar solo ─────────────────────────────
hiddenimports  = collect_submodules('football_analyzer')     # todos los submódulos
hiddenimports += ['sklearn', 'scipy', 'scipy.special.cython_special',
                  'pandas', 'numpy', 'PIL', 'requests']

a = Analysis(
    ['main.py'],
    pathex=[str(PARENT), str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'shap', 'pytest', 'IPython', 'jupyter', 'notebook'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AlphaBet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # sin UPX: build más fiable, menos falsos positivos AV
    console=False,             # app de ventana, sin consola negra
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'assets' / 'app_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AlphaBet',
)
