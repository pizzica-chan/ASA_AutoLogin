# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller ビルド定義（python build.py で実行）"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
root = Path(SPECPATH)

datas = [
    (str(root / "assets"), "assets"),
    (str(root / "docs" / "setup_samples"), "docs/setup_samples"),
    (str(root / "config.example.yaml"), "."),
]
binaries = []
hiddenimports = [
    "cv2",
    "numpy",
    "mss",
    "mss.windows",
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "yaml",
    "pydirectinput",
    "vgamepad",
    "vgamepad.win",
    "vgamepad.win.virtual_gamepad",
    "win32gui",
    "win32con",
    "win32api",
    "win32process",
    "pywintypes",
]

for package in ("cv2", "mss", "vgamepad"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(root / "gui.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="ASA_Login",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ASA_Login",
)
