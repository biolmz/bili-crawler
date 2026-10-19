#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# BiliCrawler — macOS 构建脚本
#
#   ./packaging/macos/build_macos.sh              # 只构建 .app
#   ./packaging/macos/build_macos.sh --dmg        # 构建 .app + .dmg 安装包
#
# 前置：macOS 10.15+，Python 3.10~3.13（必须能 import tkinter）
# 说明：PyInstaller 不能交叉编译，macOS 包只能在 macOS 上产出。
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

MAKE_DMG=0
for arg in "$@"; do
  case "$arg" in
    --dmg) MAKE_DMG=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

# --- 环境检查 ---------------------------------------------------------------
if [ "$(uname -s)" != "Darwin" ]; then
  echo "✗ 当前系统不是 macOS，PyInstaller 无法交叉编译。" >&2
  echo "  请在 Mac 上运行，或使用 .github/workflows/build-macos.yml 让 GitHub Actions 构建。" >&2
  exit 1
fi

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "✗ 找不到 $PY，请先安装 Python 3（brew install python@3.12 python-tk@3.12）" >&2
  exit 1
fi

ARCH="$(uname -m)"                      # arm64 / x86_64
VERSION="$("$PY" - <<'EOF'
import re, io
s = io.open('src/bili_core.py', encoding='utf-8').read()
print(re.search(r'APP_VERSION\s*=\s*"([^"]+)"', s).group(1))
EOF
)"

echo "== BiliCrawler $VERSION / macOS $ARCH =="

# --- 依赖环境：默认建独立 venv ----------------------------------------------
# Homebrew 的 Python 是 externally-managed，直接 pip install 会被拒绝；
# 用 venv 隔离，同时 venv 会继承基础解释器的 tkinter。
if [ "${USE_SYSTEM_PY:-0}" = "1" ]; then
  RUNDIR_PY="$PY"
else
  VENV="$ROOT/build/venv-macos-$ARCH"
  if [ ! -x "$VENV/bin/python" ]; then
    echo "创建虚拟环境：$VENV"
    rm -rf "$VENV"
    "$PY" -m venv "$VENV"
  fi
  RUNDIR_PY="$VENV/bin/python"
fi

if ! "$RUNDIR_PY" -c "import tkinter" >/dev/null 2>&1; then
  echo "✗ 运行环境缺少 tkinter，GUI 打不出来。" >&2
  echo "  Homebrew：brew install python@3.12 python-tk@3.12" >&2
  echo "  官网安装包（python.org）：自带 Tcl/Tk，可直接用。" >&2
  exit 1
fi

echo "Python：$RUNDIR_PY"
"$RUNDIR_PY" -c "import sys, tkinter; print(' ', sys.version.split()[0], '| Tk', tkinter.TkVersion)"

# --- 依赖 -------------------------------------------------------------------
"$RUNDIR_PY" - <<'EOF'
import importlib.util, subprocess, sys
need = [m for m in ("requests", "yt_dlp", "PyInstaller") if importlib.util.find_spec(m) is None]
if need:
    print("安装依赖：", ", ".join(need))
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "-q",
                           "pip", "requests", "yt-dlp", "pyinstaller"])
EOF

PY="$RUNDIR_PY"

# --- 图标 -------------------------------------------------------------------
if [ ! -f assets/app.icns ]; then
  echo "生成 assets/app.icns …"
  "$PY" gen_icon.py
fi

# --- 内置 FFmpeg -------------------------------------------------------------
# 从 Finder 启动的 .app 不继承终端 PATH，Homebrew 的 ffmpeg 经常检测不到；
# 直接把静态 ffmpeg 打进包里，用户装完就能用。想省体积：NO_BUNDLED_FFMPEG=1。
FFMPEG_VER="b6.1.1"
VENDOR="$HERE/vendor"
mkdir -p "$VENDOR"
if [ "${NO_BUNDLED_FFMPEG:-0}" = "1" ]; then
  echo "按 NO_BUNDLED_FFMPEG=1 跳过内置 FFmpeg"
elif [ -x "$VENDOR/ffmpeg" ]; then
  echo "复用已下载的 $VENDOR/ffmpeg"
else
  case "$ARCH" in
    arm64) ASSET="ffmpeg-darwin-arm64" ;;
    *)     ASSET="ffmpeg-darwin-x64" ;;
  esac
  BASE="https://github.com/eugeneware/ffmpeg-static/releases/download/${FFMPEG_VER}"
  echo "下载 FFmpeg：$ASSET"
  curl -fL --retry 3 --connect-timeout 20 -o "$VENDOR/ffmpeg.gz" "$BASE/${ASSET}.gz"
  gunzip -c "$VENDOR/ffmpeg.gz" > "$VENDOR/ffmpeg"
  rm -f "$VENDOR/ffmpeg.gz"
  chmod +x "$VENDOR/ffmpeg"
  curl -fsL -o "$VENDOR/ffmpeg.LICENSE" "$BASE/${ASSET}.LICENSE" 2>/dev/null || true
fi

if [ -x "$VENDOR/ffmpeg" ]; then
  echo "  $("$VENDOR/ffmpeg" -version 2>&1 | head -1)"
else
  echo "⚠ 未内置 FFmpeg：程序首次运行时需自行获取（brew install ffmpeg 或界面内下载）"
fi

# --- 构建 -------------------------------------------------------------------
rm -rf build/macos dist/BiliCrawler.app dist/BiliCrawler
echo "运行 PyInstaller …"
"$PY" -m PyInstaller --clean --noconfirm \
      --distpath dist --workpath build/macos \
      packaging/macos/BiliCrawler-macos.spec

APP="dist/BiliCrawler.app"
[ -d "$APP" ] || { echo "✗ 未生成 $APP" >&2; exit 1; }

# --- 校验关键运行时 ---------------------------------------------------------
"$PY" - "$APP" <<'EOF'
import os, sys
app = sys.argv[1]
macos_dir = os.path.join(app, "Contents", "MacOS")
bundled = []
for dirpath, _, files in os.walk(app):
    for f in files:
        bundled.append(os.path.join(dirpath, f).lower())
def has(frag):
    return any(frag in p for p in bundled)
print("  可执行文件：", os.path.join("Contents", "MacOS", "BiliCrawler"))
print("  Tcl/Tk 资源：", "已包含" if has("tcl") or has("tk") else "⚠ 未检测到")
print("  yt-dlp 内核：", "已包含" if has("yt_dlp") else "⚠ 未检测到")
ff = [p for p in bundled if os.path.basename(p) == "ffmpeg"]
print("  内置 FFmpeg：", ff[0] if ff else "⚠ 未包含（用户需自行安装）")
if not os.path.isfile(os.path.join(macos_dir, "BiliCrawler")):
    sys.exit("✗ Contents/MacOS/BiliCrawler 缺失")
EOF

# ffmpeg 必须真能执行（架构不匹配时这里就会暴露）
FF_BIN="$(find "$APP" -type f -name ffmpeg -perm -111 2>/dev/null | head -1)"
if [ -n "$FF_BIN" ]; then
  echo "  验证内置 ffmpeg：$("$FF_BIN" -version 2>&1 | head -1)"
fi

# --- ad-hoc 签名（未做 Apple 公证，分发后首次打开需右键→打开） ---------------
echo "ad-hoc 签名 …"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP" && echo "  签名校验通过"
xattr -cr "$APP" 2>/dev/null || true

# --- 产物 -------------------------------------------------------------------
ZIP="dist/BiliCrawler-${VERSION}-macos-${ARCH}.zip"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
echo "✓ $APP"
echo "✓ $ZIP ($(du -h "$ZIP" | cut -f1))"

if [ "$MAKE_DMG" = "1" ]; then
  bash "$HERE/make_dmg.sh" "$APP" "$VERSION" "$ARCH"
fi
