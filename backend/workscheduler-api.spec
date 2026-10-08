from pathlib import Path

import ortools
from PyInstaller.building.build_main import Analysis, EXE, PYZ


ortools_lib = Path(ortools.__file__).resolve().parent / ".libs"
ortools_binaries = [(str(path), ".") for path in ortools_lib.glob("*.dll")]

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=ortools_binaries,
    datas=[],
    hiddenimports=["ortools.sat.python.cp_model", "ortools.sat.python.cp_model_helper"],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="workscheduler-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
