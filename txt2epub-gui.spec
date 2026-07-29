# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：txt2epub GUI 单文件（-F）exe。

主理人要求交付「一个 exe 文件」，故采用单文件模式：EXE 直接收
a.binaries / a.zipfiles / a.datas，**不带 COLLECT**，产出单个
`txt2epub-gui.exe`。GUI 代码与单文件/单目录无关，若改回单目录(-D)
只需把下方 EXE 换成 `exe = EXE(pyz, a.scripts, ...)` + `coll = COLLECT(...)`
即可，无需改动任何源码。

入口为 `src/gui/__main__.py`（即 `python -m src.gui`）。

注意：`langdetect` 的语种识别依赖其 `profiles` 数据目录，打包后若缺失会
报 "profiles not found"。这里通过 `datas` 显式收集该目录规避此常见坑。
"""

import os
from pathlib import Path

import langdetect

# 动态定位 langdetect 的 profiles 目录（避免硬编码路径）
_langdetect_profiles = Path(langdetect.__file__).parent / "profiles"
_datas = []
if _langdetect_profiles.is_dir():
    # (源目录, 打包内目标目录) —— 运行时在 _MEIPASS/langdetect/profiles 还原
    _datas.append((str(_langdetect_profiles), "langdetect/profiles"))


a = Analysis(
    ["src/gui/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        # Tkinter 各子模块（标准库，但 PyInstaller 不总自动收集）
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.simpledialog",
        # 内核与 GUI 子包（确保单文件下也能被收集）
        "src",
        "src.txt2epub",
        "src.utils",
        "src.gui",
        "src.gui.app",
        "src.gui.worker",
        "src.gui.models",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# 单文件模式：-F。不带 COLLECT，所有内容打进一个 exe。
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="txt2epub-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 窗口程序，不弹控制台
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 主理人若提供 .ico 填入此处即可
)
