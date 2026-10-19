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

if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo "✗ 当前 Python 缺少 tkinter，GUI 打不出来。" >&2
  echo "  Homebrew：brew install python-tk@3.12" >&2
  echo "  官网安装包（python.org）：自带 Tcl/Tk，可直接用。" >&2
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

# --- 依赖 -------------------------------------------------------------------
"$PY" - <<'EOF'
import importlib, subprocess, sys
need = [m for m in ("requests", "yt_dlp", "PyInstaller") if importlib.util.find_spec(m) is None]
if need:
    print("安装依赖：", ", ".join(need))
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade",
                           "pip", "requests", "yt-dlp", "pyinstaller"])
EOF

# --- 图标 -------------------------------------------------------------------
if [ ! -f assets/app.icns ]; then
  echo "生成 assets/app.icns …"
  "$PY" gen_icon.py
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
if not os.path.isfile(os.path.join(macos_dir, "BiliCrawler")):
    sys.exit("✗ Contents/MacOS/BiliCrawler 缺失")
EOF

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
