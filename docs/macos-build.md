# macOS 打包说明

## 为什么不能直接"转换"

PyInstaller 打出来的包内含 **Python 解释器、Tcl/Tk 运行时、yt-dlp 内核**，三样都是按操作系统和
CPU 架构编译的二进制。Windows 上产出的 `.exe` 无法转换成 macOS 的 `.app`——没有交叉编译这条路。
所以 macOS 包必须在 macOS 环境下生成。

两条可行路径：

| 途径 | 适合 | 耗时 |
|---|---|---|
| 本地 Mac 跑脚本 | 手上有 Mac，想立刻出包 | 3~6 分钟 |
| GitHub Actions | 没有 Mac，推代码自动出包 | 8~12 分钟（含排队） |

---

## 一、本地 Mac 构建

```bash
brew install python@3.12 python-tk@3.12
git clone https://github.com/biolmz/bili-crawler.git
cd bili-crawler
bash packaging/macos/build_macos.sh --dmg
```

脚本做的事：

1. 检查系统是 macOS、Python 能 `import tkinter`
2. 在 `build/venv-macos-<arch>/` 建独立虚拟环境（规避 Homebrew Python 的 externally-managed 限制）
3. 缺依赖时装 `requests` / `yt-dlp` / `pyinstaller`
4. 没有 `assets/app.icns` 时用 `gen_icon.py` 现生成
5. PyInstaller 按 `packaging/macos/BiliCrawler-macos.spec` 打出 `dist/BiliCrawler.app`
6. 校验 `Contents/MacOS/BiliCrawler`、Tcl/Tk 资源、yt-dlp 是否齐全
7. ad-hoc 签名（`codesign --force --deep --sign -`）+ 清 quarantine 属性
8. `ditto` 打 zip；带 `--dmg` 时调 `make_dmg.sh` 用 `hdiutil` 出安装镜像

产物：

```
dist/BiliCrawler.app
dist/BiliCrawler-1.1.0-macos-arm64.dmg     # 或 x86_64
dist/BiliCrawler-1.1.0-macos-arm64.zip
```

只想要 `.app` 不要 dmg，去掉 `--dmg` 即可。

---

## 二、GitHub Actions 构建（无 Mac）

`.github/workflows/build-macos.yml` 已配好，推送到 `main` 或手动触发即跑：

- **arm64**：`macos-14` runner + Homebrew Python 3.12 + `python-tk@3.12`
- **x86_64**：`macos-15-intel` runner + python.org 官方 Python 3.12（自带 Tk framework）

产物在仓库 **Actions → build-macos → 对应 run → Artifacts** 下载（需登录 GitHub）。
打 `v*` tag 时会自动把 dmg 附到同名 Release。

手动触发：

```bash
# 网页：Actions → build-macos → Run workflow
# 或命令行（需 gh 已登录）
gh workflow run build-macos
```

---

## 三、内置 FFmpeg（默认开启）

macOS 上从 Finder 启动的 `.app` **不继承终端 PATH**，`brew install` 的 ffmpeg 经常检测不到；
内置一份静态 ffmpeg 最省事，装完就能合并高清视频。

构建脚本默认按架构下载 [ffmpeg-static](https://github.com/eugeneware/ffmpeg-static) b6.1.1：

| 架构 | 资源 | 解压后 |
|---|---|---|
| arm64 | `ffmpeg-darwin-arm64.gz` | 45.6 MB |
| x86_64 | `ffmpeg-darwin-x64.gz` | 79.5 MB |

产物落在 `Contents/Frameworks/ffmpeg/bin/ffmpeg`，`Contents/Resources/ffmpeg` 是指向它的符号链接。
包的体积因此增加约 45~80 MB（dmg 约 46 MB / 55 MB）。

不想内置（想省体积）：

```bash
NO_BUNDLED_FFMPEG=1 bash packaging/macos/build_macos.sh --dmg
```

此时程序按「环境变量 `BILICRAWLER_FFMPEG` → 程序目录 → 数据目录 → PATH → Homebrew/MacPorts
常见路径」的顺序查找，也可以在界面里点「未检测到 FFmpeg」自动下载。

自己塞指定版本：

```bash
mkdir -p packaging/macos/vendor
cp /path/to/static/ffmpeg packaging/macos/vendor/ffmpeg
chmod +x packaging/macos/vendor/ffmpeg
bash packaging/macos/build_macos.sh --dmg
```

架构必须与目标包一致（arm64 包要塞 arm64 版），否则运行即报 `Bad CPU type`。
ffmpeg-static 的二进制是 **GPL** 许可，分发时请保留 `packaging/macos/vendor/ffmpeg.LICENSE`。

---

## 四、常见问题

**`error: externally-managed-environment`**
Homebrew 的 Python 3.12 禁止直接往系统 site-packages 装包。脚本默认建 venv 就是为了绕开它；
手动装依赖时也请先 `python3 -m venv .venv && source .venv/bin/activate`。

**`ModuleNotFoundError: No module named '_tkinter'`**
用了不带 Tk 的 Python。`brew install python-tk@3.12`，或改用 python.org 官方安装包。

**`brew link` 报冲突导致安装返回非 0**
runner 上常预装了 `python@3.12`。`brew link --overwrite --force python@3.12` 即可；
包本身已解压到 Cellar，link 失败不影响 `brew --prefix` 取路径。

**`bad interpreter: /usr/bin/env bash^M`**
脚本被 CRLF 污染。仓库的 `.gitattributes` 已强制 `*.sh` 用 LF；本地改过就用
`dos2unix packaging/macos/*.sh` 修一下。

**用户双击提示"无法打开，Apple 无法验证"**
正常现象——包只做了 ad-hoc 签名。让用户右键 → 打开；或执行
`xattr -dr com.apple.quarantine /Applications/BiliCrawler.app`。

---

## 五、正式分发（去掉安全提示）

要让用户双击就能开，需要 Apple Developer 账号（$99/年）做两件事：

1. **Developer ID 签名**：把证书导成 `.p12` 放进 GitHub Secrets，构建时
   `codesign --force --deep --options runtime --sign "Developer ID Application: XXX (TEAMID)"`
2. **公证**：`xcrun notarytool submit BiliCrawler.dmg --apple-id ... --team-id ... --password ... --wait`
   通过后 `xcrun stapler staple BiliCrawler.dmg`

在这两步做之前，ad-hoc 签名版本只在"本机自用 / 右键打开"场景下可用。
