# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ZYTONA APP (Windows .exe)."""

import os

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
root = os.path.dirname(os.path.abspath(SPEC))

hidden = collect_submodules("hon_net_guard")
hidden += [
    "psutil",
    "tkinter",
    "_tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
]

a = Analysis(
    [os.path.join(root, "main.py")],
    pathex=[root],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ZYTONA_APP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=None,
)
