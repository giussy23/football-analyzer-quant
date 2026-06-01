# -*- mode: python ; coding: utf-8 -*-
# football_analyzer.spec
#
# Uso:
#   pip install pyinstaller
#   pyinstaller football_analyzer.spec
#
# El ejecutable queda en:  dist/FootballAnalyzer/FootballAnalyzer.exe

import sys
from pathlib import Path
import customtkinter

# Ruta raíz del proyecto
ROOT = Path(SPECPATH)

# Assets de CustomTkinter (necesarios para que los temas y fuentes funcionen)
CTK_PATH = Path(customtkinter.__file__).parent

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # CustomTkinter assets (temas, fuentes, imágenes)
        (str(CTK_PATH / 'assets'), 'customtkinter/assets'),
    ],
    hiddenimports=[
        # scikit-learn internals que PyInstaller no detecta solo
        'sklearn.utils._cython_blas',
        'sklearn.neighbors.typedefs',
        'sklearn.neighbors.quad_tree',
        'sklearn.tree._utils',
        'sklearn.utils._weight_vector',
        'sklearn.ensemble._gb_losses',
        'sklearn.utils.sparsetools',
        # joblib
        'joblib.externals.loky.backend.managers',
        # pandas / numpy
        'pandas._libs.tslibs.np_datetime',
        'pandas._libs.tslibs.nattype',
        'pandas._libs.tslibs.timezones',
        'numpy.core._dtype_ctypes',
        # tkinter
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        # app modules
        'football_analyzer.core.config',
        'football_analyzer.core.data',
        'football_analyzer.core.features',
        'football_analyzer.core.model',
        'football_analyzer.core.analyzer',
        'football_analyzer.core.storage',
        'football_analyzer.ui.widgets',
        'football_analyzer.ui.views.analysis',
        'football_analyzer.ui.views.portfolio',
        'football_analyzer.ui.views.settings',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'IPython', 'jupyter',
        'pytest', 'setuptools',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FootballAnalyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # Sin consola negra al arrancar
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,               # Pon aquí tu .ico si tienes: icon='icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FootballAnalyzer',
)
