# -*- mode: python ; coding: utf-8 -*-
# Build (from the project root, with `pip install pyinstaller`):
#   pyinstaller --clean ecstudio.spec
# Produces dist/ecstudio/ with the `ecstudio` executable next to README.

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # validator data files (Material / Particle enum names)
        ("ecstudio/data", "ecstudio/data"),
    ],
    hiddenimports=["tkinter"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ecstudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed app on Windows/macOS
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ecstudio",
)
