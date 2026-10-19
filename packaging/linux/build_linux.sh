#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# BiliCrawler — Linux 构建脚本
#
#   ./packaging/linux/build_linux.sh            # tar.gz + deb
#   ./packaging/linux/build_linux.sh --tar      # 只要免安装包
#   ./packaging/linux/build_linux.sh --deb      # 只要 deb
#
# 前置：Linux（x86_64 / arm64），Python 3.10~3.13 且能 import tkinter
#       Debian/Ubuntu：sudo apt install python3 python3-venv python3-tk
# 说明：PyInstaller 不能交叉编译，Linux 包只能在 Linux 上产出。
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

DO_TAR=0
DO_DEB=0
for arg in "$@"; do
  case "$arg" in
    --tar) DO_TAR=1 ;;
    --deb) DO_DEB=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done
[ "$DO_TAR$DO_DEB" = "00" ] && { DO_TAR=1; DO_DEB=1; } || true

TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

# --- 环境检查 ---------------------------------------------------------------
if [ "$(uname -s)" != "Linux" ]; then
  echo "✗ 当前系统不是 Linux，PyInstaller 无法交叉编译。" >&2
  echo "  请在 Linux 上运行，或用 .github/workflows/build-linux.yml 让 GitHub Actions 构建。" >&2
  exit 1
fi

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "✗ 找不到 $PY" >&2; exit 1; }

ARCH_RAW="$(uname -m)"
case "$ARCH_RAW" in
  x86_64|amd64)  DEB_ARCH=amd64; PKG_ARCH=x86_64 ;;
  aarch64|arm64) DEB_ARCH=arm64; PKG_ARCH=aarch64 ;;
  armv7l)        DEB_ARCH=armhf; PKG_ARCH=armv7l ;;
  *)             DEB_ARCH="$ARCH_RAW"; PKG_ARCH="$ARCH_RAW" ;;
esac

VERSION="$("$PY" - <<'EOF'
import re, io
s = io.open('src/bili_core.py', encoding='utf-8').read()
print(re.search(r'APP_VERSION\s*=\s*"([^"]+)"', s).group(1))
EOF
)"

echo "== BiliCrawler $VERSION / Linux $PKG_ARCH =="

# --- 依赖环境：独立 venv（避开 PEP 668 的 externally-managed 限制） ----------
if [ "${USE_SYSTEM_PY:-0}" = "1" ]; then
  RUNDIR_PY="$PY"
else
  VENV="$ROOT/build/venv-linux-$PKG_ARCH"
  if [ ! -x "$VENV/bin/python" ]; then
    echo "创建虚拟环境：$VENV"
    rm -rf "$VENV"
    "$PY" -m venv "$VENV" || {
      echo "✗ 创建 venv 失败，Debian/Ubuntu 请先：sudo apt install python3-venv" >&2
      exit 1
    }
  fi
  RUNDIR_PY="$VENV/bin/python"
fi

if ! "$RUNDIR_PY" -c "import tkinter" >/dev/null 2>&1; then
  echo "✗ 缺少 tkinter，GUI 打不出来。" >&2
  echo "  Debian/Ubuntu：sudo apt install python3-tk" >&2
  echo "  Fedora：sudo dnf install python3-tkinter" >&2
  echo "  Arch：sudo pacman -S tk" >&2
  exit 1
fi

echo "Python：$RUNDIR_PY"
"$RUNDIR_PY" -c "import sys, tkinter; print(' ', sys.version.split()[0], '| Tk', tkinter.TkVersion)"

"$RUNDIR_PY" - <<'EOF'
import importlib.util, subprocess, sys
need = [m for m in ("requests", "yt_dlp", "PyInstaller") if importlib.util.find_spec(m) is None]
if need:
    print("安装依赖：", ", ".join(need))
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "-q",
                           "pip", "requests", "yt-dlp", "pyinstaller"])
EOF

# --- 图标 -------------------------------------------------------------------
[ -f assets/app.png ] || { echo "生成 assets/app.png …"; "$RUNDIR_PY" gen_icon.py; }

# --- 构建 -------------------------------------------------------------------
rm -rf build/linux dist/BiliCrawler
echo "运行 PyInstaller …"
"$RUNDIR_PY" -m PyInstaller --clean --noconfirm \
      --distpath dist --workpath build/linux \
      packaging/linux/BiliCrawler-linux.spec

APP_DIR="dist/BiliCrawler"
[ -x "$APP_DIR/BiliCrawler" ] || { echo "✗ 未生成 $APP_DIR/BiliCrawler" >&2; exit 1; }

echo "  体积：$(du -sh "$APP_DIR" | cut -f1)"
echo "  Tcl/Tk：$(find "$APP_DIR/_internal" -maxdepth 1 -iname '*tcl*' -o -maxdepth 1 -iname '*tk*' | wc -l) 项"
echo "  yt-dlp：$(du -sh "$APP_DIR/_internal/yt_dlp" 2>/dev/null | cut -f1)"

mkdir -p dist

# --- 免安装 tar.gz -----------------------------------------------------------
if [ "$DO_TAR" = "1" ]; then
  PKG="BiliCrawler-${VERSION}-linux-${PKG_ARCH}"
  STAGE="$TMPROOT/tar"
  mkdir -p "$STAGE/$PKG"
  cp -a "$APP_DIR" "$STAGE/$PKG/BiliCrawler"

  cat > "$STAGE/$PKG/bilicrawler" <<'SH'
#!/bin/sh
# BiliCrawler 启动器：定位到脚本所在目录再执行
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/BiliCrawler/BiliCrawler" "$@"
SH
  chmod +x "$STAGE/$PKG/bilicrawler"

  cat > "$STAGE/$PKG/安装说明.txt" <<'TXT'
BiliCrawler — Linux 免安装版
============================

解压后直接运行：
   ./bilicrawler

也可以双击目录里的 BiliCrawler/BiliCrawler（部分文件管理器需先在
「首选项 → 行为」里允许运行可执行文本文件）。

关于 FFmpeg
-----------
合并高清晰度视频需要 FFmpeg。二选一：
   · 系统包管理器安装（推荐）
       Debian/Ubuntu：sudo apt install ffmpeg
       Fedora：sudo dnf install ffmpeg
   · 打开程序后点顶部「未检测到 FFmpeg」，按提示自动下载静态版

数据与配置位置
--------------
配置/Cookie：~/.local/share/BiliCrawler
默认下载目录：~/Downloads/BiliDownloads
（若设置了 XDG_DATA_HOME，配置会落在 $XDG_DATA_HOME/BiliCrawler）

仅用于采集 B 站公开数据、下载公开投稿视频用于个人学习备份。
请遵守著作权法与 B 站用户协议。
TXT

  tar -czf "dist/${PKG}.tar.gz" -C "$STAGE" "$PKG"
  echo "✓ dist/${PKG}.tar.gz ($(du -h "dist/${PKG}.tar.gz" | cut -f1))"
fi

# --- deb 安装包 --------------------------------------------------------------
if [ "$DO_DEB" = "1" ]; then
  if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "⚠ 未找到 dpkg-deb，跳过 deb（Debian/Ubuntu：已默认自带；其它发行版用 tar.gz 即可）" >&2
  else
    PKG_NAME="bilicrawler"
    DSTAGE="$TMPROOT/deb"
    mkdir -p "$DSTAGE/DEBIAN" \
             "$DSTAGE/opt/bilicrawler" \
             "$DSTAGE/usr/bin" \
             "$DSTAGE/usr/share/applications" \
             "$DSTAGE/usr/share/icons/hicolor/512x512/apps"

    cp -a "$APP_DIR/." "$DSTAGE/opt/bilicrawler/"
    ln -sf /opt/bilicrawler/BiliCrawler "$DSTAGE/usr/bin/bilicrawler"
    sed -e "s/^Version=.*/Version=${VERSION}/" packaging/linux/bilicrawler.desktop \
        > "$DSTAGE/usr/share/applications/bilicrawler.desktop"
    cp assets/app.png "$DSTAGE/usr/share/icons/hicolor/512x512/apps/bilicrawler.png"

    SIZE_KB="$(du -sk "$DSTAGE/opt" | cut -f1)"
    cat > "$DSTAGE/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: video
Priority: optional
Architecture: ${DEB_ARCH}
Installed-Size: ${SIZE_KB}
Depends: libc6, libx11-6, libxext6, libxrender1, libxft2, libfontconfig1, libfreetype6, libxss1
Maintainer: biolmz <biolmz@users.noreply.github.com>
Homepage: https://github.com/biolmz/bili-crawler
Description: Bilibili video collector and downloader
 采集 B 站公开数据（视频信息/分P/评论/弹幕）并下载公开投稿视频。
 基于 yt-dlp，支持清晰度选择、批量下载与进度显示。
EOF

    cat > "$DSTAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi
exit 0
EOF
    chmod 755 "$DSTAGE/DEBIAN/postinst"

    DEB_OUT="dist/${PKG_NAME}_${VERSION}_${DEB_ARCH}.deb"
    dpkg-deb --root-owner-group --build "$DSTAGE" "$DEB_OUT" >/dev/null
    echo "✓ $DEB_OUT ($(du -h "$DEB_OUT" | cut -f1))"
    echo "  安装：sudo dpkg -i $DEB_OUT   或   sudo apt install ./$DEB_OUT"
  fi
fi

echo "完成。产物在 dist/"
