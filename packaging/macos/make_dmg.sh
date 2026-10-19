#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 把 BiliCrawler.app 打成 .dmg 安装镜像
#   ./make_dmg.sh dist/BiliCrawler.app 1.1.0 arm64
# 镜像内含 .app + Applications 快捷方式，拖进去即完成安装。
# ---------------------------------------------------------------------------
set -euo pipefail

APP="${1:?用法: make_dmg.sh <BiliCrawler.app> <版本> <架构>}"
VERSION="${2:-1.1.0}"
ARCH="${3:-$(uname -m)}"

[ "$(uname -s)" = "Darwin" ] || { echo "✗ 只能在 macOS 上生成 dmg" >&2; exit 1; }
[ -d "$APP" ] || { echo "✗ 找不到 $APP" >&2; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME="$(basename "$APP" .app)"
OUT="$ROOT/dist/${NAME}-${VERSION}-macos-${ARCH}.dmg"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

cat > "$STAGE/安装说明.txt" <<'TXT'
BiliCrawler — macOS 安装说明
============================

1. 把左边的 BiliCrawler 拖到右边的 Applications 文件夹。
2. 首次打开：在「应用程序」里右键 BiliCrawler →「打开」→ 再点「打开」。
   （应用未做 Apple 公证，直接双击会被 Gatekeeper 拦下，这是正常现象。）

如果提示「已损坏，无法打开」，在终端执行一次：
   xattr -dr com.apple.quarantine /Applications/BiliCrawler.app

关于 FFmpeg
-----------
合并高清晰度视频需要 FFmpeg。两种方式任选：
   · 已装 Homebrew：brew install ffmpeg （程序会自动识别）
   · 打开程序后点顶部「未检测到 FFmpeg」，按提示自动下载

数据与配置位置
--------------
~/Library/Application Support/BiliCrawler
默认下载目录：~/Downloads/BiliDownloads

仅用于采集 B 站公开数据、下载公开投稿视频用于个人学习备份。
请遵守著作权法与 B 站用户协议。
TXT

echo "生成 dmg …"
rm -f "$OUT"
hdiutil create \
  -volname "$NAME $VERSION" \
  -srcfolder "$STAGE" \
  -fs HFS+ \
  -format UDZO \
  -ov \
  "$OUT" >/dev/null

echo "✓ $OUT ($(du -h "$OUT" | cut -f1))"
