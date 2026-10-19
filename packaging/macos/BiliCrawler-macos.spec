# -*- mode: python ; coding: utf-8 -*-
"""
BiliCrawler — macOS 打包配置（PyInstaller）

产出：dist/BiliCrawler.app
必须在 macOS 上执行（PyInstaller 不支持交叉编译）：
    pyinstaller --clean --noconfirm packaging/macos/BiliCrawler-macos.spec
或直接用 packaging/macos/build_macos.sh。

若把静态 ffmpeg 放到 packaging/macos/vendor/ffmpeg，
会被一起打进 .app（Contents/Frameworks/ffmpeg/bin/ffmpeg）。
"""
import os
import re

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
SRC = os.path.join(ROOT, "src")
ASSETS = os.path.join(ROOT, "assets")
ICNS = os.path.join(ASSETS, "app.icns")

# 版本号直接取源码里的 APP_VERSION，避免两处不一致
with open(os.path.join(SRC, "bili_core.py"), encoding="utf-8") as _f:
    APP_VERSION = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', _f.read()).group(1)

datas, binaries, hiddenimports = [], [], []
_d, _b, _h = collect_all("yt_dlp")
datas += _d
binaries += _b
hiddenimports += _h

# 可选：内置 ffmpeg（静态单文件）
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
    upx=False,                 # UPX 不支持 macOS arm64
    console=False,             # GUI 程序：不弹终端
    disable_windowed_traceback=False,
    target_arch=None,          # 跟随构建机架构（arm64 / x86_64）
    codesign_identity=None,    # 构建脚本里统一做 ad-hoc 签名
    entitlements_file=None,
    icon=ICNS,
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

app = BUNDLE(
    coll,
    name="BiliCrawler.app",
    icon=ICNS,
    bundle_identifier="cn.biolmz.bilicrawler",
    version=APP_VERSION,
    info_plist={
        "CFBundleName": "BiliCrawler",
        "CFBundleDisplayName": "BiliCrawler",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundleDevelopmentRegion": "zh_CN",
        "NSHumanReadableCopyright": "仅用于采集 B 站公开数据与下载公开投稿视频，"
                                    "请遵守著作权法与 B 站用户协议。",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "LSMultipleInstancesProhibited": True,
    },
)
