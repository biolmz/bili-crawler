# -*- coding: utf-8 -*-
"""
app.py — B站视频采集下载器（图形界面）
=========================================
两段式流程：粘贴链接 → 解析出视频清单 → 勾选要的 → 开始下载 / 采集。

仅用于：采集 B 站公开数据、下载公开投稿视频用于个人学习备份。
不处理付费课程 / 大会员专享 / 番剧版权内容。
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import zipfile

# --- 无控制台环境下保护 stdout/stderr（PyInstaller --windowed） ---
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# --- Windows 高 DPI 适配 ---
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bili_core import (  # noqa: E402
    APP_NAME, APP_VERSION, BiliClient, BiliError, VideoInfo, VideoRef,
    data_dir, default_download_dir, find_ffmpeg, human_size, human_time,
    parse_input, sanitize,
)

# ======================================================================
# 主题
# ======================================================================
BG = "#f5f6f8"
CARD = "#ffffff"
BORDER = "#e8eaed"
BORDER_S = "#dfe2e6"
TEXT = "#1f2329"
SUB = "#8a9099"
PRIMARY = "#fb7299"
PRIMARY_D = "#ef5b86"
PRIMARY_L = "#ffe9f0"
OK = "#00b42a"
WARN = "#ff7d00"
ERR = "#d54941"
HOVER = "#f4f5f7"

FONT = "Microsoft YaHei UI"
MONO = "Consolas"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def _detect_scale() -> float:
    """检测系统 DPI 缩放倍率（96 DPI = 1.0）。高分屏上所有像素尺寸都要跟着放大。"""
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
        hdc = windll.user32.GetDC(0)
        dpi = windll.gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
        windll.user32.ReleaseDC(0, hdc)
        return max(1.0, min(dpi / 96.0, 3.0))
    except Exception:
        return 1.0


SCALE = _detect_scale()


def S(v):
    """把 96-DPI 设计值换算成当前屏幕的像素值。"""
    return int(round(v * SCALE))

MODE_MAP = {"下载视频": "download", "采集数据": "collect", "下载 + 采集": "both"}
QUALITY_MAP = {
    "最高画质": "best",
    "1080P": "1080p",
    "720P": "720p",
    "480P": "480p",
    "360P": "360p",
}


@dataclass
class Row:
    """解析结果里的一行。"""
    ref: VideoRef
    info: VideoInfo
    page: int
    title: str
    part: str
    duration: int
    checked: bool = True
    state: str = "待处理"
    iid: str = ""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"B站视频采集下载器  v{APP_VERSION}")
        self.geometry(f"{S(1120)}x{S(866)}")
        self.minsize(S(1000), S(620))
        self.configure(bg=BG)

        self.q: queue.Queue = queue.Queue()
        self.client: BiliClient | None = None
        self.thread: threading.Thread | None = None
        self.ffmpeg_path = find_ffmpeg()
        self.rows: list[Row] = []
        self.by_iid: dict[str, Row] = {}
        self._seq = 0
        self.busy = False
        self.log_lines: list[tuple[str, str]] = []   # (文本, tag)
        self._log_widgets: list[tk.Text] = []
        self.log_win: tk.Toplevel | None = None

        self._init_style()
        self._build_ui()
        self._refresh_ffmpeg_badge()
        self.after(80, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ================================================== 样式
    def _init_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, foreground=TEXT, font=(FONT, 10))
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=CARD)
        st.configure("TLabel", background=BG, foreground=TEXT, font=(FONT, 10))
        st.configure("Card.TLabel", background=CARD, foreground=TEXT, font=(FONT, 10))

        st.configure("TRadiobutton", background=CARD, foreground=TEXT, font=(FONT, 10))
        st.map("TRadiobutton", background=[("active", CARD)])
        st.configure("TCheckbutton", background=CARD, foreground=TEXT, font=(FONT, 10))
        st.map("TCheckbutton", background=[("active", CARD)])

        st.configure("TEntry", fieldbackground="#fbfbfc", bordercolor=BORDER_S,
                     lightcolor=BORDER_S, darkcolor=BORDER_S, insertcolor=TEXT,
                     foreground=TEXT, padding=S(4))
        st.configure("TCombobox", fieldbackground="#fbfbfc", background="#fbfbfc",
                     bordercolor=BORDER_S, arrowcolor=SUB, padding=S(3))
        st.map("TCombobox", fieldbackground=[("readonly", "#fbfbfc")],
               background=[("readonly", "#fbfbfc")])

        st.configure("TProgressbar", troughcolor="#eceef1", background=PRIMARY,
                     bordercolor="#eceef1", lightcolor=PRIMARY, darkcolor=PRIMARY,
                     thickness=S(11))

        st.configure("Treeview", background=CARD, fieldbackground=CARD,
                     foreground=TEXT, rowheight=S(28), font=(FONT, 10),
                     borderwidth=0, relief="flat")
        st.configure("Treeview.Heading", background="#fafbfc", foreground="#4e5969",
                     font=(FONT, 9, "bold"), relief="flat",
                     padding=(S(6), S(6)))
        st.map("Treeview.Heading", background=[("active", "#f2f3f5")])
        st.map("Treeview", background=[("selected", PRIMARY_L)],
               foreground=[("selected", TEXT)])
        self.option_add("*TCombobox*Listbox.font", (FONT, 10))

    def _btn(self, parent, text, cmd, kind="primary", small=False):
        if kind == "primary":
            bg, fg, abg = PRIMARY, "#ffffff", PRIMARY_D
        elif kind == "danger":
            bg, fg, abg = CARD, ERR, "#fdeceb"
        else:
            bg, fg, abg = CARD, TEXT, HOVER
        b = tk.Button(
            parent, text=text, command=cmd,
            font=(FONT, 9 if small else 10),
            bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=BORDER_S if kind != "primary" else PRIMARY,
            cursor="hand2",
            padx=S(12 if small else 18), pady=S(4 if small else 6),
        )
        return b

    def _card(self, parent, title="", right=None):
        wrap = tk.Frame(parent, bg=CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        if title:
            head = tk.Frame(wrap, bg=CARD)
            head.pack(fill="x", padx=S(16), pady=(S(12), S(10)))
            tk.Label(head, text=title, bg=CARD, fg=TEXT,
                     font=(FONT, 10, "bold")).pack(side="left")
            if right:
                right(head)
            tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x")
        body = tk.Frame(wrap, bg=CARD)
        body.pack(fill="both", expand=True, padx=S(16), pady=(S(8), S(14)))
        return wrap, body

    # ================================================== 界面
    def _build_ui(self):
        # 顶部品牌色细条，给整页一个视觉锚点
        tk.Frame(self, bg=PRIMARY, height=S(3)).pack(fill="x")

        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True, padx=S(18), pady=S(16))

        # ---------- 顶栏 ----------
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", pady=(S(0), S(12)))
        left = tk.Frame(head, bg=BG)
        left.pack(side="left")
        tk.Label(left, text="B站视频采集下载器", bg=BG, fg=TEXT,
                 font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(left, text="粘贴链接 · 解析清单 · 勾选下载 · 公开数据采集",
                 bg=BG, fg=SUB, font=(FONT, 9)).pack(anchor="w", pady=(S(2), S(0)))
        self.ff_badge = tk.Label(head, text="", bg=BG, fg=SUB, font=(FONT, 9),
                                 cursor="hand2")
        self.ff_badge.pack(side="right", pady=(S(10), S(0)))

        # ---------- ① 输入 ----------
        def input_right(p):
            self._btn(p, "粘贴", self._paste, "ghost", small=True).pack(side="right")
            self._btn(p, "清空", self._clear, "ghost", small=True).pack(
                side="right", padx=(S(0), S(8)))

        card1, c1 = self._card(root, "① 输入链接", input_right)
        card1.pack(fill="x")
        irow = tk.Frame(c1, bg=CARD)
        irow.pack(fill="x")
        self.txt_input = tk.Text(irow, height=3, font=(MONO, 10), bg="#fbfbfc",
                                 fg=TEXT, relief="flat", highlightthickness=1,
                                 highlightbackground=BORDER_S, insertbackground=TEXT,
                                 wrap="none", padx=S(10), pady=S(8))
        self.txt_input.pack(side="left", fill="both", expand=True)
        self.btn_parse = self._btn(irow, "解析链接", self._parse, "primary")
        self.btn_parse.pack(side="right", padx=(S(10), S(0)))
        tk.Label(c1, text="BV号 / av号 / 链接 / b23.tv 短链 / UP主空间，一行一个",
                 bg=CARD, fg=SUB, font=(FONT, 9)).pack(anchor="w", pady=(S(7), S(0)))

        # ---------- ② 解析结果 ----------
        def result_right(p):
            self.lbl_count = tk.Label(p, text="尚未解析", bg=CARD, fg=SUB,
                                      font=(FONT, 9))
            self.lbl_count.pack(side="right")
            for txt, cmd in (("反选", self._invert), ("全不选", self._none),
                             ("全选", self._all)):
                self._btn(p, txt, cmd, "ghost", small=True).pack(
                    side="right", padx=(S(0), S(8)))

        # 底部固定区容器：先占位，保证窗口变小时底部（按钮/进度）不会被裁掉
        bottom = tk.Frame(root, bg=BG)
        bottom.pack(side="bottom", fill="x")

        card2, c2 = self._card(root, "② 视频清单", result_right)
        card2.pack(fill="both", expand=True, pady=(S(12), S(0)))

        cols = ("sel", "title", "part", "up", "dur", "state")
        self.tree = ttk.Treeview(c2, columns=cols, show="headings",
                                 selectmode="browse", height=6)
        heads = {
            "sel": ("", S(46), "center"),
            "title": ("标题", S(330), "w"),
            "part": ("分P", S(250), "w"),
            "up": ("UP主", S(140), "w"),
            "dur": ("时长", S(76), "center"),
            "state": ("状态", S(84), "center"),
        }
        for k, (txt, w, anchor) in heads.items():
            self.tree.heading(k, text=txt)
            self.tree.column(k, width=w, anchor=anchor, minwidth=S(50),
                             stretch=(k == "title"))
        vsb = ttk.Scrollbar(c2, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#fcfcfd")
        self.tree.tag_configure("fail", foreground=ERR)
        self.tree.tag_configure("done", foreground=OK)
        self.tree.bind("<Button-1>", self._on_tree_click)

        # ---------- ③ 任务设置 ----------
        card3, c3 = self._card(bottom, "③ 任务设置")
        card3.pack(fill="x", pady=(S(12), S(0)))

        r1 = tk.Frame(c3, bg=CARD)
        r1.pack(fill="x")
        tk.Label(r1, text="模式", bg=CARD, fg=SUB, font=(FONT, 9),
                 width=6, anchor="w").pack(side="left")
        self.var_mode = tk.StringVar(value="下载 + 采集")
        for name in MODE_MAP:
            ttk.Radiobutton(r1, text=name, value=name, variable=self.var_mode,
                            command=self._sync_state).pack(side="left", padx=(S(0), S(14)))
        tk.Label(r1, text="画质", bg=CARD, fg=SUB, font=(FONT, 9)).pack(
            side="left", padx=(S(10), S(6)))
        self.var_quality = tk.StringVar(value="最高画质")
        self.cmb_quality = ttk.Combobox(r1, textvariable=self.var_quality, width=11,
                                        state="readonly", values=list(QUALITY_MAP),
                                        font=(FONT, 10))
        self.cmb_quality.pack(side="left")
        self.var_audio = tk.BooleanVar(value=False)
        self.chk_audio = ttk.Checkbutton(r1, text="仅音频", variable=self.var_audio)
        self.chk_audio.pack(side="left", padx=(S(12), S(0)))

        r2 = tk.Frame(c3, bg=CARD)
        r2.pack(fill="x", pady=(S(7), S(0)))
        tk.Label(r2, text="保存到", bg=CARD, fg=SUB, font=(FONT, 9),
                 width=6, anchor="w").pack(side="left")
        self.var_outdir = tk.StringVar(value=default_download_dir())
        tk.Entry(r2, textvariable=self.var_outdir, font=(FONT, 10), relief="flat",
                 bg="#fbfbfc", highlightthickness=1, highlightbackground=BORDER_S,
                 insertbackground=TEXT).pack(side="left", fill="x", expand=True,
                                             ipady=S(4))
        self._btn(r2, "浏览", self._pick_dir, "ghost", small=True).pack(
            side="left", padx=(S(8), S(0)))

        r3 = tk.Frame(c3, bg=CARD)
        r3.pack(fill="x", pady=(S(7), S(0)))
        tk.Label(r3, text="采集", bg=CARD, fg=SUB, font=(FONT, 9),
                 width=6, anchor="w").pack(side="left")
        self.var_info = tk.BooleanVar(value=True)
        self.var_cmt = tk.BooleanVar(value=True)
        self.var_dm = tk.BooleanVar(value=True)
        self.chk_info = ttk.Checkbutton(r3, text="视频信息", variable=self.var_info)
        self.chk_cmt = ttk.Checkbutton(r3, text="评论", variable=self.var_cmt)
        self.chk_dm = ttk.Checkbutton(r3, text="弹幕", variable=self.var_dm)
        for w in (self.chk_info, self.chk_cmt):
            w.pack(side="left", padx=(S(0), S(12)))
        tk.Label(r3, text="上限", bg=CARD, fg=SUB, font=(FONT, 9)).pack(
            side="left", padx=(S(0), S(4)))
        self.var_cmt_max = tk.StringVar(value="100")
        self.ent_cmt = tk.Entry(r3, textvariable=self.var_cmt_max, width=6,
                                font=(FONT, 10), relief="flat", bg="#fbfbfc",
                                highlightthickness=1, highlightbackground=BORDER_S,
                                justify="center", insertbackground=TEXT)
        self.ent_cmt.pack(side="left", ipady=S(3))
        self.chk_dm.pack(side="left", padx=(S(12), S(0)))
        self._btn(r3, "Cookie 设置", self._cookie_dialog, "ghost", small=True).pack(
            side="right")

        # ---------- 操作栏 ----------
        act = tk.Frame(bottom, bg=BG)
        act.pack(fill="x", pady=(S(10), S(0)))
        self.btn_start = self._btn(act, "开始任务", self._start, "primary")
        self.btn_start.pack(side="left")
        self.btn_stop = self._btn(act, "停止", self._stop, "danger")
        self.btn_stop.pack(side="left", padx=S(8))
        self.btn_stop.configure(state="disabled")
        self._btn(act, "打开输出目录", self._open_dir, "ghost").pack(side="left")
        self._btn(act, "运行日志", self._open_log_window, "ghost").pack(
            side="left", padx=S(8))

        # ---------- 进度 ----------
        pg = tk.Frame(bottom, bg=BG)
        pg.pack(fill="x", pady=(S(10), S(0)))
        self.pb = ttk.Progressbar(pg, mode="determinate", maximum=100)
        self.pb.pack(fill="x")
        self.lbl_status = tk.Label(pg, text="就绪", bg=BG, fg=SUB, font=(FONT, 9),
                                   anchor="w")
        self.lbl_status.pack(fill="x", pady=(S(5), S(0)))

        tk.Label(bottom,
                 text="仅用于采集公开数据与个人学习备份 · 不处理付费 / 会员专享内容 · 请勿商业传播",
                 bg=BG, fg=SUB, font=(FONT, 8)).pack(anchor="center", pady=(S(7), S(0)))

        self._sync_state()

    # ================================================== 状态联动
    def _sync_state(self):
        need_dl = MODE_MAP.get(self.var_mode.get(), "both") in ("download", "both")
        self.cmb_quality.configure(state="readonly" if need_dl else "disabled")
        self.chk_audio.configure(state="normal" if need_dl else "disabled")

    # ================================================== 输入区动作
    def _paste(self):
        try:
            data = self.clipboard_get()
        except tk.TclError:
            return
        cur = self.txt_input.get("1.0", "end").strip()
        self.txt_input.delete("1.0", "end")
        self.txt_input.insert("1.0", (cur + "\n" + data).strip())

    def _clear(self):
        self.txt_input.delete("1.0", "end")

    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.var_outdir.get() or "D:\\")
        if d:
            self.var_outdir.set(os.path.normpath(d))

    def _open_dir(self):
        d = self.var_outdir.get()
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)
        except Exception:
            subprocess.Popen(["explorer", d])

    def _toggle_log(self):
        """打开（或唤到前台）独立的日志窗口。"""
        if self.log_win is not None and self.log_win.winfo_exists():
            self.log_win.lift()
            self.log_win.focus_force()
            return
        win = tk.Toplevel(self)
        self.log_win = win
        win.title("运行日志")
        win.geometry(f"{S(860)}x{S(480)}")
        win.configure(bg=BG)
        wrap = tk.Frame(win, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(14), pady=S(14))
        txt = tk.Text(wrap, font=(MONO, 9), bg="#ffffff", fg=TEXT, relief="flat",
                      highlightthickness=1, highlightbackground=BORDER, wrap="word",
                      padx=S(12), pady=S(10))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        txt.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        for tag, color in (("err", ERR), ("ok", OK), ("warn", WARN), ("dim", SUB)):
            txt.tag_config(tag, foreground=color)
        for line, tag in self.log_lines:
            txt.insert("end", line + "\n", tag or ())
        txt.see("end")
        txt.configure(state="disabled")
        self._log_widgets.append(txt)

        def clear():
            self.log_lines.clear()
            self._log_widgets = [w for w in self._log_widgets if w.winfo_exists()]
            for w in self._log_widgets:
                w.configure(state="normal")
                w.delete("1.0", "end")
                w.configure(state="disabled")

        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=S(14), pady=(S(0), S(12)))
        self._btn(bar, "清空", clear, "ghost", small=True).pack(side="right")
        self._btn(bar, "关闭", win.destroy, "ghost", small=True).pack(
            side="right", padx=(S(0), S(8)))

    def _open_log_window(self):
        self._toggle_log()

    def _cookie_dialog(self):
        win = tk.Toplevel(self)
        win.title("Cookie 设置")
        win.configure(bg=CARD)
        win.geometry(f"{S(540)}x{S(290)}")
        win.transient(self)
        win.grab_set()
        tk.Label(win, text="填写 SESSDATA 可提升成功率", bg=CARD, fg=TEXT,
                 font=(FONT, 11, "bold")).pack(anchor="w", padx=S(20), pady=(S(18), S(6)))
        tk.Label(win,
                 text="不填也能用。填了之后评论采集、UP主投稿、高码率视频会更稳定。\n\n"
                      "获取方法：浏览器登录 B 站 → F12 → Application → Cookies →\n"
                      "www.bilibili.com → 复制 SESSDATA 的值，粘贴到下面。\n\n"
                      "只保存在本机，不会上传到任何地方。",
                 bg=CARD, fg=SUB, font=(FONT, 9), justify="left").pack(anchor="w",
                                                                      padx=S(20))
        e = tk.Entry(win, font=(MONO, 10), relief="flat", bg="#fbfbfc",
                     highlightthickness=1, highlightbackground=BORDER_S,
                     insertbackground=TEXT, width=64)
        e.pack(fill="x", padx=S(20), pady=S(12), ipady=S(5))
        p = os.path.join(data_dir(), "cookie.txt")
        if os.path.isfile(p):
            try:
                e.insert(0, open(p, encoding="utf-8").read().strip())
            except OSError:
                pass

        def save():
            val = e.get().strip()
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(val)
            except OSError as ex:
                messagebox.showerror("保存失败", str(ex))
                return
            if self.client:
                self.client.session.set_cookie(val)
            self._log("Cookie 已保存。" if val else "Cookie 已清空。", "ok")
            win.destroy()

        bar = tk.Frame(win, bg=CARD)
        bar.pack(fill="x", padx=S(20), pady=S(14))
        self._btn(bar, "保存", save, "primary").pack(side="right")
        self._btn(bar, "取消", win.destroy, "ghost").pack(side="right", padx=(S(0), S(8)))

    # ================================================== FFmpeg
    def _refresh_ffmpeg_badge(self):
        if self.ffmpeg_path:
            self.ff_badge.configure(text="● FFmpeg 已就绪", fg=OK)
        else:
            self.ff_badge.configure(text="● 未检测到 FFmpeg（点此获取）", fg=WARN)
        self.ff_badge.bind("<Button-1>", lambda e: self._get_ffmpeg())

    def _get_ffmpeg(self):
        if self.ffmpeg_path:
            messagebox.showinfo("FFmpeg", f"已检测到 FFmpeg：\n{self.ffmpeg_path}")
            return
        if not messagebox.askyesno(
                "获取 FFmpeg",
                "高清晰度视频的画面与音轨是分开的，需要 FFmpeg 合并。\n\n"
                f"将从公开源下载 FFmpeg（约 30MB）到：\n{data_dir()}\\ffmpeg\n\n是否继续？"):
            return

        def job():
            try:
                import requests
                self._log("开始下载 FFmpeg…")
                dst = os.path.join(data_dir(), "ffmpeg", "bin")
                os.makedirs(dst, exist_ok=True)
                tmp = os.path.join(data_dir(), "ffmpeg.zip")
                with requests.get(FFMPEG_URL, stream=True, timeout=60,
                                  headers={"User-Agent": "Mozilla/5.0"}) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length") or 0)
                    got = 0
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(262144):
                            f.write(chunk)
                            got += len(chunk)
                            if total:
                                self.q.put(("progress", (
                                    got * 100.0 / total,
                                    f"下载 FFmpeg {human_size(got)} / {human_size(total)}")))
                self._log("解压中…")
                with zipfile.ZipFile(tmp) as z:
                    hit = [n for n in z.namelist() if n.endswith("bin/ffmpeg.exe")]
                    if not hit:
                        raise RuntimeError("压缩包内未找到 ffmpeg.exe")
                    with z.open(hit[0]) as src, \
                            open(os.path.join(dst, "ffmpeg.exe"), "wb") as out:
                        while True:
                            b = src.read(1048576)
                            if not b:
                                break
                            out.write(b)
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                self.ffmpeg_path = find_ffmpeg()
                self.q.put(("ffmpeg", self.ffmpeg_path))
                self._log(f"FFmpeg 就绪：{self.ffmpeg_path}", "ok")
            except Exception as e:
                self._log(f"FFmpeg 获取失败：{e}", "err")

        threading.Thread(target=job, daemon=True).start()

    # ================================================== 解析
    def _parse(self):
        if self.busy:
            return
        raw = self.txt_input.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("提示", "请先粘贴视频链接")
            return
        self._set_busy(True)
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self.by_iid.clear()
        self.lbl_count.configure(text="解析中…")
        self._log("=" * 58, "dim")
        self._log("开始解析链接…")
        self.thread = threading.Thread(target=self._run_parse, args=(raw,),
                                       daemon=True)
        self.thread.start()

    def _run_parse(self, raw: str):
        try:
            cli = self.client or BiliClient(self._load_cookie(),
                                            log=lambda m: self._log(m))
            self.client = cli
            cli.stop_event.clear()

            refs = cli.resolve_input(raw, up_limit=60,
                                     log=lambda m: self._log(m, "dim"))
            if not refs:
                self._log("没有解析到有效地址。", "err")
                self.q.put(("parsed", []))
                return
            self._log(f"共识别到 {len(refs)} 个视频，正在获取详细信息…", "ok")

            rows: list[Row] = []
            for i, ref in enumerate(refs, 1):
                if cli.stop_event.is_set():
                    break
                self.q.put(("status", f"解析中 {i}/{len(refs)} …"))
                self.q.put(("progress", (i * 100.0 / len(refs), "")))
                try:
                    info = cli.video_info(ref)
                except BiliError as e:
                    self._log(f"  ✗ {ref.key}：{e}", "warn")
                    rows.append(Row(ref=ref, info=VideoInfo(), page=1,
                                    title=f"{ref.key}（解析失败）", part="—",
                                    duration=0, checked=False, state="失败"))
                    continue

                if len(info.pages) > 1:
                    for p in info.pages:
                        pref = VideoRef(bvid=ref.bvid, aid=ref.aid,
                                        page=p["page"], raw=ref.raw)
                        rows.append(Row(ref=pref, info=info, page=p["page"],
                                        title=info.title,
                                        part=f"P{p['page']} {p.get('part', '')}".strip(),
                                        duration=p.get("duration", 0)))
                else:
                    rows.append(Row(ref=ref, info=info, page=ref.page,
                                    title=info.title, part="—",
                                    duration=info.duration))
            self._log(f"解析完成：{len(rows)} 个条目。", "ok")
            self.q.put(("parsed", rows))
        except Exception:
            self._log("解析出错：\n" + traceback.format_exc(), "err")
            self.q.put(("parsed", []))
        finally:
            self.q.put(("idle", None))

    def _load_cookie(self) -> str:
        p = os.path.join(data_dir(), "cookie.txt")
        if os.path.isfile(p):
            try:
                return open(p, encoding="utf-8").read().strip()
            except OSError:
                pass
        return ""

    def _add_rows(self, rows: list[Row]):
        for idx, r in enumerate(rows):
            tag = "fail" if r.state == "失败" else ("odd" if idx % 2 else "")
            iid = self.tree.insert(
                "", "end",
                values=("☑" if r.checked else "☐", r.title, r.part,
                        r.info.owner_name or "—",
                        human_time(r.duration) if r.duration else "—", r.state),
                tags=(tag,) if tag else ())
            r.iid = iid
            self.by_iid[iid] = r
            self.rows.append(r)
        self._update_count()

    def _update_count(self):
        total = len(self.rows)
        if total == 0:
            self.lbl_count.configure(text="尚无结果")
            return
        sel = sum(1 for r in self.rows if r.checked)
        self.lbl_count.configure(text=f"已选 {sel} / 共 {total} 个")

    # ---- 勾选 ----
    def _on_tree_click(self, e):
        if self.tree.identify("region", e.x, e.y) != "cell":
            return
        if self.tree.identify_column(e.x) != "#1":
            return
        iid = self.tree.identify_row(e.y)
        if not iid:
            return
        r = self.by_iid.get(iid)
        if r is None or r.state == "失败":
            return
        r.checked = not r.checked
        self.tree.set(iid, "sel", "☑" if r.checked else "☐")
        self._update_count()

    def _set_all(self, value):
        for r in self.rows:
            if r.state == "失败":
                continue
            r.checked = value
            self.tree.set(r.iid, "sel", "☑" if value else "☐")
        self._update_count()

    def _all(self):
        self._set_all(True)

    def _none(self):
        self._set_all(False)

    def _invert(self):
        for r in self.rows:
            if r.state == "失败":
                continue
            r.checked = not r.checked
            self.tree.set(r.iid, "sel", "☑" if r.checked else "☐")
        self._update_count()

    # ================================================== 执行任务
    def _start(self):
        if self.busy:
            return
        picked = [r for r in self.rows if r.checked and r.state != "失败"]
        if not picked:
            if self.rows:
                messagebox.showwarning("提示", "请先勾选要处理的视频")
            else:
                messagebox.showwarning("提示", "请先点『解析链接』获取视频清单")
            return

        outdir = self.var_outdir.get().strip()
        if not outdir:
            messagebox.showwarning("提示", "请选择保存目录")
            return
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("目录不可用", str(e))
            return

        cfg = {
            "rows": picked,
            "mode": MODE_MAP.get(self.var_mode.get(), "both"),
            "quality": QUALITY_MAP.get(self.var_quality.get(), "best"),
            "audio_only": self.var_audio.get(),
            "want_cmt": self.var_cmt.get(),
            "want_dm": self.var_dm.get(),
            "cmt_max": max(0, int(re.sub(r"\D", "", self.var_cmt_max.get()) or "100")),
            "outdir": outdir,
            "ffmpeg": self.ffmpeg_path,
        }
        self._set_busy(True)
        self._log("=" * 58, "dim")
        self._log(f"开始处理 {len(picked)} 个条目 → {outdir}")
        self.thread = threading.Thread(target=self._run_task, args=(cfg,),
                                       daemon=True)
        self.thread.start()

    def _run_task(self, cfg: dict):
        try:
            cli = self.client or BiliClient(self._load_cookie(),
                                            log=lambda m: self._log(m))
            self.client = cli
            cli.stop_event.clear()

            rows: list[Row] = cfg["rows"]
            mode = cfg["mode"]
            do_dl = mode in ("download", "both")
            do_col = mode in ("collect", "both")
            outdir = cfg["outdir"]
            data_out = os.path.join(outdir, "_采集数据")
            total = len(rows)
            ok = fail = 0

            for i, r in enumerate(rows, 1):
                if cli.stop_event.is_set():
                    self._log("已停止。", "warn")
                    break
                tag = f"[{i}/{total}]"
                self._set_state(r, "处理中", "")
                head = r.title if r.part == "—" else f"{r.title} · {r.part}"
                self._log(f"{tag} {head}", "ok")
                base = i - 1

                if do_dl:
                    self.q.put(("status", f"{tag} 下载中：{r.title[:34]}"))
                    try:
                        path = cli.download(
                            r.ref, outdir, cfg["quality"], cfg["audio_only"],
                            progress=lambda d, bi=base, rr=r: self._on_dl(d, bi, total, rr),
                            ffmpeg=cfg["ffmpeg"])
                        self._log(f"      ✓ {os.path.basename(path) if path else '完成'}",
                                  "ok")
                    except BiliError as e:
                        self._log(f"      ✗ 下载失败：{e}", "err")
                        self._set_state(r, "失败", "fail")
                        fail += 1
                        continue

                if do_col and not cli.stop_event.is_set():
                    os.makedirs(data_out, exist_ok=True)
                    self.q.put(("status", f"{tag} 采集中：{r.title[:34]}"))
                    payload = {"video": r.info.__dict__}
                    if cfg["want_cmt"] and cfg["cmt_max"] > 0:
                        try:
                            payload["comments"] = cli.comments(r.info.aid,
                                                               cfg["cmt_max"])
                            self._log(f"      评论 {len(payload['comments'])} 条", "dim")
                        except BiliError as e:
                            payload["comments"] = []
                            self._log(f"      评论失败：{e}", "warn")
                    if cfg["want_dm"]:
                        try:
                            cid = cli.cid_of_page(r.info, r.page)
                            payload["danmaku"] = cli.danmaku(cid)
                            self._log(f"      弹幕 {len(payload['danmaku'])} 条", "dim")
                        except BiliError as e:
                            payload["danmaku"] = []
                            self._log(f"      弹幕失败：{e}", "warn")
                    suffix = f"_P{r.page}" if r.part != "—" else ""
                    fp = os.path.join(data_out,
                                      f"{r.info.bvid or r.ref.key}{suffix}.json")
                    try:
                        with open(fp, "w", encoding="utf-8") as f:
                            json.dump(payload, f, ensure_ascii=False, indent=2)
                    except OSError as e:
                        self._log(f"      写入失败：{e}", "err")

                self._set_state(r, "完成", "done")
                ok += 1
                self.q.put(("progress", (i * 100.0 / total, "")))

            self._log(f"全部结束：成功 {ok}，失败 {fail}。", "ok")
            self.q.put(("status", f"完成 · 成功 {ok} / 失败 {fail}"))
            self.q.put(("progress", (100.0, "")))
        except Exception:
            self._log("发生未预期错误：\n" + traceback.format_exc(), "err")
        finally:
            self.q.put(("idle", None))

    def _set_state(self, r: Row, text: str, tag: str):
        self.q.put(("state", (r.iid, text, tag)))

    def _on_dl(self, d: dict, base: int, total: int, r: Row):
        if d.get("status") != "downloading":
            return
        tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        got = d.get("downloaded_bytes") or 0
        if not tot:
            return
        pct = got * 100.0 / tot
        overall = (base + pct / 100.0) * 100.0 / total
        speed = d.get("speed") or 0
        eta = int(d.get("eta") or 0)
        head = r.title[:26] if r.part == "—" else f"{r.title[:18]} {r.part}"
        self.q.put(("progress", (
            overall,
            f"[{base + 1}/{total}] {head} · {pct:.0f}% · "
            f"{human_size(got)}/{human_size(tot)} · {human_size(speed)}/s · 剩余 {eta}s"
        )))

    def _stop(self):
        if self.client:
            self.client.stop_event.set()
            self._log("已发送停止信号，等待当前文件收尾…", "warn")
        self.btn_stop.configure(state="disabled")

    def _set_busy(self, busy: bool):
        self.busy = busy
        if busy:
            self.btn_start.configure(state="disabled", bg="#f9c8d7")
            self.btn_parse.configure(state="disabled")
            self.btn_stop.configure(state="normal")
        else:
            self.btn_start.configure(state="normal", bg=PRIMARY)
            self.btn_parse.configure(state="normal")
            self.btn_stop.configure(state="disabled")

    # ================================================== 队列泵
    def _log(self, msg: str, tag: str = ""):
        self.q.put(("log", (msg, tag)))

    def _pump(self):
        try:
            while True:
                try:
                    kind, payload = self.q.get_nowait()
                except queue.Empty:
                    break
                if kind == "log":
                    msg, tag = payload
                    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
                    self.log_lines.append((line, tag))
                    if len(self.log_lines) > 4000:
                        del self.log_lines[:1000]
                    alive = []
                    for w in self._log_widgets:
                        if not w.winfo_exists():
                            continue
                        alive.append(w)
                        w.configure(state="normal")
                        w.insert("end", line + "\n", tag or ())
                        w.see("end")
                        w.configure(state="disabled")
                    self._log_widgets = alive
                elif kind == "status":
                    self.lbl_status.configure(text=payload)
                elif kind == "progress":
                    pct, note = payload
                    self.pb.configure(value=max(0, min(100, pct)))
                    if note:
                        self.lbl_status.configure(text=note)
                elif kind == "state":
                    iid, text, tag = payload
                    if iid and self.tree.exists(iid):
                        self.tree.set(iid, "state", text)
                        if tag:
                            self.tree.item(iid, tags=(tag,))
                elif kind == "parsed":
                    self._add_rows(payload)
                    if payload:
                        self.lbl_status.configure(
                            text=f"解析完成，共 {len(payload)} 个条目")
                elif kind == "ffmpeg":
                    self.ffmpeg_path = payload
                    self._refresh_ffmpeg_badge()
                elif kind == "idle":
                    self._set_busy(False)
                    self._update_count()
        except Exception:
            pass
        self.after(80, self._pump)

    def _on_close(self):
        if self.busy:
            if not messagebox.askyesno("退出", "任务正在运行，确定要退出吗？"):
                return
            if self.client:
                self.client.stop_event.set()
        self.destroy()


# ======================================================================
# 命令行模式
# ======================================================================

def run_cli(argv) -> int:
    """
        BiliCrawler.exe --cli -o D:\\out -q 1080p -m both BV1xx411c7mD
    退出码：0 全部成功 / 1 有失败 / 2 地址无效
    """
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stderr = sys.stdout
    except Exception:
        pass

    import argparse
    ap = argparse.ArgumentParser(prog="BiliCrawler",
                                 description="B站视频采集下载器（命令行模式）")
    ap.add_argument("urls", nargs="+")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("-q", "--quality", default="best",
                    choices=["best", "1080p", "720p", "480p", "360p"])
    ap.add_argument("-m", "--mode", default="both",
                    choices=["download", "collect", "both"])
    ap.add_argument("--audio-only", action="store_true")
    ap.add_argument("--cookie", default="")
    ap.add_argument("--comments", type=int, default=100)
    ap.add_argument("--no-danmaku", action="store_true")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    def say(m):
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

    outdir = a.out or default_download_dir()
    os.makedirs(outdir, exist_ok=True)
    do_dl = a.mode in ("download", "both")
    do_col = a.mode in ("collect", "both")

    cookie = a.cookie
    cp = os.path.join(data_dir(), "cookie.txt")
    if not cookie and os.path.isfile(cp):
        try:
            cookie = open(cp, encoding="utf-8").read().strip()
        except OSError:
            pass

    cli = BiliClient(cookie, log=say)
    ff = find_ffmpeg()
    say(f"FFmpeg: {ff or '未找到'}")
    refs = cli.resolve_input(" ".join(a.urls), log=say)
    if not refs:
        say("没有解析到有效地址")
        return 2

    data_out = os.path.join(outdir, "_采集数据")
    ok = fail = 0
    for i, ref in enumerate(refs, 1):
        try:
            info = cli.video_info(ref)
        except BiliError as e:
            say(f"[{i}/{len(refs)}] {ref.key} 失败: {e}")
            fail += 1
            continue
        say(f"[{i}/{len(refs)}] {info.title}  ({info.owner_name})")
        if do_dl:
            try:
                p = cli.download(ref, outdir, a.quality, a.audio_only, ffmpeg=ff)
                say(f"    已保存: {os.path.basename(p) if p else '(完成)'}")
            except BiliError as e:
                say(f"    下载失败: {e}")
                fail += 1
                continue
        if do_col:
            os.makedirs(data_out, exist_ok=True)
            payload = {"video": info.__dict__}
            if a.comments > 0:
                try:
                    payload["comments"] = cli.comments(info.aid, a.comments)
                except BiliError as e:
                    payload["comments"] = []
                    say(f"    评论失败: {e}")
            if not a.no_danmaku:
                try:
                    payload["danmaku"] = cli.danmaku(cli.cid_of_page(info, ref.page))
                except BiliError as e:
                    payload["danmaku"] = []
                    say(f"    弹幕失败: {e}")
            fp = os.path.join(data_out, f"{info.bvid or ref.key}.json")
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except OSError as e:
                say(f"    写入失败: {e}")
        ok += 1

    say(f"完成：成功 {ok}，失败 {fail}")
    return 0 if fail == 0 else 1


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("--cli", "cli"):
        sys.exit(run_cli(argv[1:]))
    App().mainloop()


if __name__ == "__main__":
    main()
