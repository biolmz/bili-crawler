# -*- mode: python ; coding: utf-8 -*-
"""
BiliCrawler — Linux 打包配置（PyInstaller onedir）

产出：dist/BiliCrawler/（内含可执行文件与 _internal/）
必须在 Linux 上执行；构建命令见 packaging/linux/build_linux.sh。
"""
import os
import re

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
SRC = os.path.join(ROOT, "src")
ASSETS = os.path.join(ROOT, "assets")

with open(os.path.join(SRC, "bili_core.py"), encoding="utf-8") as _f:
    APP_VERSION = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _f.read()).group(1)

datas, binaries, hiddenimports = [], [], []
_d, _b, _h = collect_all("yt_dlp")
datas += _d
binaries += _b
hiddenimports += _h

# 可选：内置静态 ffmpeg（放到 packaging/linux/vendor/ffmpeg 即可）
_vendor_ff = os.path.join(SPECPATH, "vendor", "ffmpeg")
if os.path.isfile(_vendor_ff):
    binaries.append((_vendor_ff, "ffmpeg/bin"))

a = Analysis(
    [os.path.join(SRC, "app.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BiliCrawler",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BiliCrawler",
)
