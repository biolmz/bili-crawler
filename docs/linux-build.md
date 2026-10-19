# Linux 打包说明

## 结论先行

PyInstaller 打出来的包内含 **Python 解释器、Tcl/Tk 运行时、yt-dlp 内核**，都是分平台、
分架构的二进制。Windows 或 macOS 上都没法给 Linux 出包——不存在交叉编译。Linux 包必须在
Linux 环境下生成。

| 途径 | 适合 | 耗时 |
|---|---|---|
| 本地 Linux 跑脚本 | 手上有 Linux 机器 / 虚拟机 / WSL2 | 3~6 分钟 |
| GitHub Actions | 没有 Linux，推代码自动出包 | 8~12 分钟 |

---

## 一、本地构建

```bash
# Debian / Ubuntu
sudo apt install python3 python3-venv python3-tk ffmpeg
# Fedora： sudo dnf install python3 python3-tkinter ffmpeg
# Arch：   sudo pacman -S python tk ffmpeg

git clone https://github.com/biolmz/bili-crawler.git
cd bili-crawler
bash packaging/linux/build_linux.sh          # 同时出 tar.gz 和 deb
```

可选参数：

```bash
bash packaging/linux/build_linux.sh --deb    # 只出 deb
bash packaging/linux/build_linux.sh --tar    # 只出免安装包
```

脚本流程：校验系统与 tkinter → 建 `build/venv-linux-<arch>/` → 装依赖 → 校验 PNG 图标
→ PyInstaller 按 `packaging/linux/BiliCrawler-linux.spec` 打成 onedir → 组 tar.gz → 组 deb。

产物：

```
dist/BiliCrawler/                                  # 可直接运行的目录
dist/BiliCrawler-1.1.0-linux-x86_64.tar.gz         # 免安装
dist/bilicrawler_1.1.0_amd64.deb                   # Debian / Ubuntu
```

---

## 二、GitHub Actions 构建

`.github/workflows/build-linux.yml` 已配好，推 `main` 或手动触发：

- **x86_64**：`ubuntu-22.04`，系统 Python 3.10 + `python3-tk`
- **aarch64**：`ubuntu-22.04-arm`，同样配方

产物在 **Actions → build-linux → Artifacts**（需登录）。打 `v*` tag 时自动附到 Release。

```bash
gh workflow run build-linux
```

---

## 三、包的结构

### deb

```
/opt/bilicrawler/                        程序本体（onedir，约 46 MB）
/usr/bin/bilicrawler   -> /opt/bilicrawler/BiliCrawler
/usr/share/applications/bilicrawler.desktop
/usr/share/icons/hicolor/512x512/apps/bilicrawler.png
```

`postinst` 里刷新 desktop database 与图标缓存，装完菜单和图标立即生效。

deb 的 `Depends` 只声明 Tk 运行时真正需要的系统库：`libc6 libx11-6 libxext6
libxrender1 libxft2 libfontconfig1 libfreetype6 libxss1`。Python 与 Tcl/Tk 本身已打进包里，
不需要系统再装 Python。

### tar.gz

```
BiliCrawler-1.1.0-linux-x86_64/
├─ BiliCrawler/          程序本体
├─ bilicrawler           启动脚本（sh，exec 到本体）
└─ 安装说明.txt
```

---

## 四、glibc 兼容性（重要）

CI 用 Ubuntu 22.04 构建，产物依赖 **glibc ≥ 2.35**：

| 系统 | 能否直接跑 |
|---|---|
| Ubuntu 22.04 / 24.04 | ✅ |
| Debian 12 / 13 | ✅ |
| Fedora 36+ / RHEL 9+ | ✅ |
| Ubuntu 20.04（glibc 2.31） | ❌ 需在该系统上自行编译 |
| Debian 11（glibc 2.31） | ❌ 同上 |
| CentOS 7（glibc 2.17） | ❌ 同上 |

要给老系统出包，最简单是在那台机器（或对应容器）里跑 `build_linux.sh`。
想一次兼容更老的发行版，需要把 PyInstaller 放进 manylinux2014/centos7 容器里构建。

---

## 五、FFmpeg

默认不内置。两种方式：

- 系统安装：`sudo apt install ffmpeg`，程序会自动在 PATH 里找到
- 界面内点「未检测到 FFmpeg」：自动下载 johnvansickle 的静态构建（amd64 / arm64 / armhf 自动匹配）
  到 `~/.local/share/BiliCrawler/ffmpeg/bin/ffmpeg`

想预置静态 ffmpeg：

```bash
mkdir -p packaging/linux/vendor
cp /path/to/static/ffmpeg packaging/linux/vendor/ffmpeg
chmod +x packaging/linux/vendor/ffmpeg
bash packaging/linux/build_linux.sh
```

注意架构必须与目标包一致（x86_64 包里放 x86_64 版）。

---

## 六、常见问题

**`ModuleNotFoundError: No module named '_tkinter'`**
没装 Tk 绑定。Debian/Ubuntu `sudo apt install python3-tk`；Fedora `python3-tkinter`；Arch `tk`。

**`error: externally-managed-environment`（PEP 668）**
系统 Python 禁止直接装包。脚本默认建 venv 就是为了绕开；手动操作也先 `python3 -m venv .venv`。

**Wayland 下界面字体发虚 / 缩放不对**
Tk 走 XWayland，缩放由 Tk 自己决定。可尝试 `GDK_SCALE=2 ./bilicrawler`（程序会跟随该变量调整尺寸）。

**中文字体变成方块**
系统缺中文字体：`sudo apt install fonts-noto-cjk`。程序启动时会自动在
`Noto Sans CJK SC / Source Han Sans SC / WenQuanYi Micro Hei` 之间挑一个可用的。

**双击 tar.gz 里的可执行文件没反应**
部分文件管理器默认不执行文本文件。用 `./bilicrawler` 启动，或在文件管理器偏好里允许执行。

**deb 装完菜单里没有图标**
`sudo update-desktop-database` / 注销重登。图标缓存由 `postinst` 刷新，个别桌面环境需重新登录。
