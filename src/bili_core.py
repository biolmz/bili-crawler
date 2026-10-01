# -*- coding: utf-8 -*-
"""
bili_core.py
============
B站（bilibili）公开数据采集 与 视频下载 核心模块。

设计边界
--------
1. 只访问 B 站 web 端**公开接口**，只处理**公开可访问的普通投稿视频**；
   不涉及付费课程、大会员专享、番剧版权内容 —— 这类内容本模块不会绕过。
2. 数据采集：视频信息 / 分P列表 / UP主投稿 / 评论 / 弹幕。
   部分接口需要 wbi 签名，本模块已完整实现。
3. 视频下载：走 yt-dlp（长期维护的下载内核），支持清晰度选择、批量、进度回调。

本模块不依赖任何 GUI 库，可单独当库调用；GUI 只负责包装它。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import zlib
from dataclasses import dataclass, field, asdict
from typing import Callable, Iterable, Optional

import requests

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

APP_NAME = "BiliCrawler"
APP_VERSION = "1.1.0"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

API = "https://api.bilibili.com"

# wbi 签名用的字符重排表（B 站前端硬编码，固定不变）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

# 正则
RE_BV = re.compile(r"BV[0-9A-Za-z]{10}")
RE_AV = re.compile(r"av(\d+)", re.IGNORECASE)
RE_B23 = re.compile(r"https?://b23\.tv/[0-9A-Za-z]+", re.IGNORECASE)
RE_PAGE = re.compile(r"[?&]p=(\d+)")
RE_SPACE = re.compile(r"space\.bilibili\.com/(\d+)")
RE_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


class BiliError(Exception):
    """业务异常，消息可直接展示给用户。"""


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------

def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def human_time(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def ts_to_str(ts: int) -> str:
    if not ts:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except Exception:
        return ""


def sanitize(name: str, maxlen: int = 90) -> str:
    """把标题清洗成合法文件名。"""
    name = RE_ILLEGAL.sub("_", name or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return name[:maxlen] or "untitled"


def app_dir() -> str:
    """程序所在目录（打包后为 exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def data_dir() -> str:
    """程序数据目录（cookie、ffmpeg 等）。优先 D 盘。"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def default_download_dir() -> str:
    """默认下载目录：D 盘优先。"""
    for drive in ("D:\\", "E:\\"):
        if os.path.isdir(drive):
            p = os.path.join(drive, "BiliDownloads")
            try:
                os.makedirs(p, exist_ok=True)
                return p
            except OSError:
                pass
    p = os.path.join(os.path.expanduser("~"), "BiliDownloads")
    os.makedirs(p, exist_ok=True)
    return p


# --------------------------------------------------------------------------
# FFmpeg 检测
# --------------------------------------------------------------------------

def is_ffmpeg(path: str) -> bool:
    if not path:
        return False
    exe = path if path.lower().endswith(".exe") else os.path.join(path, "ffmpeg.exe")
    return os.path.isfile(exe)


def find_ffmpeg() -> str:
    """
    依次查找 ffmpeg：
      0. 环境变量 BILICRAWLER_FFMPEG 指定的路径
      1. 程序目录 / 程序目录\\ffmpeg\\bin（安装后的位置）
      2. 项目 assets 目录（源码运行）
      3. 数据目录
      4. 系统 PATH
      5. 常见安装位置
    返回 ffmpeg.exe 的完整路径，找不到返回 ""。
    """
    env_ff = os.environ.get("BILICRAWLER_FFMPEG", "").strip()
    if env_ff and os.path.isfile(env_ff):
        return env_ff

    meipass = getattr(sys, "_MEIPASS", "")
    candidates = [
        os.path.join(app_dir(), "ffmpeg.exe"),
        os.path.join(app_dir(), "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(app_dir(), "bin", "ffmpeg.exe"),
        # 源码运行时：<项目根>/assets/ffmpeg/bin/ffmpeg.exe
        os.path.join(os.path.dirname(app_dir()), "assets", "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(data_dir(), "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(data_dir(), "ffmpeg.exe"),
    ]
    if meipass:
        candidates += [
            os.path.join(meipass, "ffmpeg.exe"),
            os.path.join(meipass, "ffmpeg", "bin", "ffmpeg.exe"),
        ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    which = shutil.which("ffmpeg")
    if which:
        return which

    for p in (
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"D:\ffmpeg\bin\ffmpeg.exe",
        os.path.expanduser(r"~\scoop\shims\ffmpeg.exe"),
    ):
        if os.path.isfile(p):
            return p
    return ""


# --------------------------------------------------------------------------
# 会话（含 wbi 签名）
# --------------------------------------------------------------------------

class BiliSession:
    """带 wbi 签名能力的 HTTP 会话。"""

    def __init__(self, cookie: str = "", timeout: int = 20):
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update(
            {
                "User-Agent": UA,
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        self._wbi_mixin: str = ""
        self._wbi_ts: float = 0.0
        if cookie:
            self.set_cookie(cookie)

    # -- cookie ----------------------------------------------------------
    def set_cookie(self, cookie: str) -> None:
        """接受整串 cookie 或仅 SESSDATA。"""
        cookie = (cookie or "").strip()
        if not cookie:
            return
        if "=" not in cookie:  # 只给了 SESSDATA 的值
            cookie = f"SESSDATA={cookie}"
        for item in cookie.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            self.s.cookies.set(k.strip(), v.strip(), domain=".bilibili.com")

    def has_login(self) -> bool:
        return any(c.name == "SESSDATA" for c in self.s.cookies)

    # -- 基础请求 --------------------------------------------------------
    def get_json(self, url: str, params: Optional[dict] = None) -> dict:
        try:
            r = self.s.get(url, params=params or {}, timeout=self.timeout)
        except requests.RequestException as e:
            raise BiliError(f"网络请求失败：{e}") from e
        if r.status_code != 200:
            raise BiliError(f"HTTP {r.status_code}：{url}")
        try:
            return r.json()
        except ValueError as e:
            raise BiliError("接口返回的不是 JSON，可能被风控拦截") from e

    def get_raw(self, url: str, params: Optional[dict] = None) -> bytes:
        try:
            r = self.s.get(url, params=params or {}, timeout=self.timeout)
        except requests.RequestException as e:
            raise BiliError(f"网络请求失败：{e}") from e
        return r.content

    # -- wbi 签名 --------------------------------------------------------
    def _wbi_key(self) -> str:
        """从 nav 接口取 img_key/sub_key 并做重排，得到 mixin key（缓存 1 小时）。"""
        if self._wbi_mixin and time.time() - self._wbi_ts < 3600:
            return self._wbi_mixin
        try:
            data = self.get_json(f"{API}/x/web-interface/nav")
            wbi = data["data"]["wbi_img"]
            img_key = wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
            sub_key = wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
        except (KeyError, TypeError) as e:
            raise BiliError("获取 wbi 签名密钥失败（nave 接口异常）") from e
        raw = img_key + sub_key
        self._wbi_mixin = "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]
        self._wbi_ts = time.time()
        return self._wbi_mixin

    def wbi_sign(self, params: dict) -> dict:
        """对参数做 wbi 签名，返回带 wts / w_rid 的新字典。"""
        key = self._wbi_key()
        p = dict(params)
        p["wts"] = int(time.time())
        items = sorted(p.items())
        # 值里的 !'()* 必须剔除，否则签名不匹配
        cleaned = [
            (k, "".join(ch for ch in str(v) if ch not in "!'()*")) for k, v in items
        ]
        query = urllib.parse.urlencode(cleaned)
        p["w_rid"] = hashlib.md5((query + key).encode("utf-8")).hexdigest()
        return p

    def get_wbi_json(self, url: str, params: dict) -> dict:
        return self.get_json(url, self.wbi_sign(params))


# --------------------------------------------------------------------------
# 输入解析
# --------------------------------------------------------------------------

@dataclass
class VideoRef:
    """用户输入解析出的视频引用。"""
    bvid: str = ""
    aid: int = 0
    page: int = 1          # 分P序号，从 1 开始
    raw: str = ""

    @property
    def key(self) -> str:
        return self.bvid or (f"av{self.aid}" if self.aid else "")


def parse_one(text: str, session: Optional[BiliSession] = None) -> Optional[VideoRef]:
    """
    解析单行输入，支持：
        BV1xx411c7mD
        av170001
        https://www.bilibili.com/video/BV1xx411c7mD?p=2
        https://b23.tv/xxxxx      （短链，需要联网跳转）
    解析不出返回 None。
    """
    text = (text or "").strip()
    if not text:
        return None
    ref = VideoRef(raw=text)

    m = RE_PAGE.search(text)
    if m:
        ref.page = max(1, int(m.group(1)))

    m = RE_BV.search(text)
    if m:
        ref.bvid = m.group(0)
        return ref

    m = RE_AV.search(text)
    if m:
        ref.aid = int(m.group(1))
        return ref

    # 短链跳转
    m = RE_B23.search(text)
    if m:
        s = session or BiliSession()
        try:
            r = s.s.head(m.group(0), allow_redirects=True, timeout=15)
            final = r.url
        except requests.RequestException:
            try:
                r = s.s.get(m.group(0), allow_redirects=True, timeout=15)
                final = r.url
            except requests.RequestException:
                return None
        return parse_one(final, session)

    return None


def parse_input(text: str, session: Optional[BiliSession] = None,
                log: Optional[Callable[[str], None]] = None) -> list[VideoRef]:
    """解析多行输入，去重（按 key+page）。"""
    out: list[VideoRef] = []
    seen = set()
    for line in re.split(r"[\s,;，；]+", text or ""):
        line = line.strip()
        if not line:
            continue
        ref = parse_one(line, session)
        if ref is None:
            if log:
                log(f"  ! 无法识别：{line[:60]}")
            continue
        sig = (ref.key, ref.page)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(ref)
    return out


# --------------------------------------------------------------------------
# 数据采集
# --------------------------------------------------------------------------

@dataclass
class VideoInfo:
    bvid: str = ""
    aid: int = 0
    cid: int = 0
    title: str = ""
    desc: str = ""
    pic: str = ""
    tname: str = ""
    duration: int = 0
    pubdate: int = 0
    owner_mid: int = 0
    owner_name: str = ""
    view: int = 0
    danmaku: int = 0
    reply: int = 0
    like: int = 0
    coin: int = 0
    favorite: int = 0
    share: int = 0
    pages: list = field(default_factory=list)   # [{cid, page, part, duration}]

    def summary_line(self) -> str:
        return (f"{self.title} | UP主:{self.owner_name} | "
                f"时长:{human_time(self.duration)} | 播放:{self.view}")


class BiliClient:
    """采集 + 下载的门面类。"""

    def __init__(self, cookie: str = "", log: Optional[Callable[[str], None]] = None):
        self.log = log or (lambda m: None)
        self.session = BiliSession(cookie)
        self._info_cache: dict[str, VideoInfo] = {}
        self.stop_event = threading.Event()

    # ---------------- 输入展开 ----------------
    def resolve_input(self, text: str, up_limit: int = 60,
                      log: Optional[Callable[[str], None]] = None) -> list[VideoRef]:
        """
        把多行用户输入展开成「视频级」引用列表：

          * 普通 BV 号 / av 号 / 链接 / b23.tv 短链  → 直接解析成一条
          * UP 主空间链接 (space.bilibili.com/<mid>)  → 拉取其最近投稿，展开成多条

        返回去重后的 VideoRef 列表（此时还未取每个视频的详细信息）。
        """
        logger = log or (lambda m: None)
        refs: list[VideoRef] = []
        seen: set[tuple] = set()

        def push(r: VideoRef) -> None:
            sig = (r.key, r.page)
            if r.key and sig not in seen:
                seen.add(sig)
                refs.append(r)

        for token in re.split(r"[\s,;，；]+", text or ""):
            token = token.strip()
            if not token:
                continue

            m = RE_SPACE.search(token)
            if m:
                mid = int(m.group(1))
                logger(f"识别到 UP 主空间 mid={mid}，拉取投稿列表…")
                try:
                    vids = self.user_videos(mid, limit=up_limit)
                except BiliError as e:
                    logger(f"  投稿列表获取失败：{e}")
                    continue
                logger(f"  取得 {len(vids)} 个投稿")
                for v in vids:
                    push(VideoRef(bvid=v.get("bvid", ""), aid=v.get("aid", 0),
                                  raw=token))
                continue

            for r in parse_input(token, self.session, logger):
                push(r)
                if r and not r.bvid and not r.aid:
                    continue

        return refs

    # ---------------- 视频信息 ----------------
    def video_info(self, ref: VideoRef) -> VideoInfo:
        params = {"bvid": ref.bvid} if ref.bvid else {"aid": ref.aid}
        data = self.session.get_json(f"{API}/x/web-interface/view", params)
        if data.get("code") != 0:
            code = data.get("code")
            msg = data.get("message", "")
            hint = {
                -404: "视频不存在或已被删除",
                -403: "无权限访问（可能是付费/会员专享内容）",
                -352: "触发风控，请稍后重试或填入 Cookie",
            }.get(code, msg)
            raise BiliError(f"获取视频信息失败（code={code}）：{hint}")

        d = data["data"]
        st = d.get("stat", {}) or {}
        ow = d.get("owner", {}) or {}
        pages = [
            {
                "cid": p.get("cid", 0),
                "page": p.get("page", 1),
                "part": p.get("part", ""),
                "duration": p.get("duration", 0),
            }
            for p in (d.get("pages") or [])
        ]
        info = VideoInfo(
            bvid=d.get("bvid", ""),
            aid=d.get("aid", 0),
            cid=d.get("cid", 0),
            title=d.get("title", ""),
            desc=(d.get("desc") or "").strip(),
            pic=d.get("pic", ""),
            tname=d.get("tname", ""),
            duration=d.get("duration", 0),
            pubdate=d.get("pubdate", 0),
            owner_mid=ow.get("mid", 0),
            owner_name=ow.get("name", ""),
            view=st.get("view", 0),
            danmaku=st.get("danmaku", 0),
            reply=st.get("reply", 0),
            like=st.get("like", 0),
            coin=st.get("coin", 0),
            favorite=st.get("favorite", 0),
            share=st.get("share", 0),
            pages=pages,
        )
        self._info_cache[info.bvid or f"av{info.aid}"] = info
        return info

    def cid_of_page(self, info: VideoInfo, page: int) -> int:
        """取指定分P的 cid；page 从 1 开始，越界则回退到第 1P。"""
        if not info.pages:
            return info.cid
        idx = page - 1
        if idx < 0 or idx >= len(info.pages):
            idx = 0
        return info.pages[idx].get("cid") or info.cid

    # ---------------- UP主投稿列表 ----------------
    def user_videos(self, mid: int, limit: int = 30) -> list[dict]:
        """拉取 UP 主最近投稿（需要 wbi 签名）。limit 为最大条数。"""
        out: list[dict] = []
        pn = 1
        ps = 30
        while len(out) < limit:
            params = {"mid": mid, "ps": ps, "pn": pn, "order": "pubdate",
                      "platform": "web", "web_location": 1550101}
            data = self.session.get_wbi_json(f"{API}/x/space/wbi/arc/search", params)
            if data.get("code") != 0:
                raise BiliError(
                    f"获取 UP 主投稿失败（code={data.get('code')}）："
                    f"{data.get('message')}；如为 -352 请填入 Cookie 后重试"
                )
            vlist = (((data.get("data") or {}).get("list") or {}).get("vlist")) or []
            if not vlist:
                break
            for v in vlist:
                out.append({
                    "bvid": v.get("bvid", ""),
                    "aid": v.get("aid", 0),
                    "title": v.get("title", ""),
                    "created": v.get("created", 0),
                    "length": v.get("length", ""),
                    "play": v.get("play", 0),
                    "comment": v.get("comment", 0),
                })
            if len(vlist) < ps:
                break
            pn += 1
            time.sleep(0.6)   # 温和限速，规避风控
        return out[:limit]

    # ---------------- 评论 ----------------
    def comments(self, aid: int, max_count: int = 100) -> list[dict]:
        """采集主评论区（不含楼中楼），按热度。返回 [{user, uid, content, like, ctime, rpid}]"""
        out: list[dict] = []
        next_page = 0
        while len(out) < max_count:
            params = {"oid": aid, "type": 1, "mode": 3, "next": next_page, "ps": 20,
                      "web_location": 1315875}
            data = self.session.get_wbi_json(f"{API}/x/v2/reply/wbi/main", params)
            if data.get("code") != 0:
                raise BiliError(
                    f"获取评论失败（code={data.get('code')}）：{data.get('message')}"
                )
            d = data.get("data") or {}
            replies = d.get("replies") or []
            if not replies:
                break
            for r in replies:
                member = (r.get("member") or {})
                content = ((r.get("content") or {}).get("message") or "").strip()
                out.append({
                    "rpid": r.get("rpid"),
                    "user": member.get("uname", ""),
                    "uid": member.get("mid", 0),
                    "content": content,
                    "like": r.get("like", 0),
                    "ctime": ts_to_str(r.get("ctime", 0)),
                    "sub_count": (r.get("rcount", 0)),
                })
                if len(out) >= max_count:
                    break
            cursor = d.get("cursor") or {}
            if cursor.get("is_end"):
                break
            next_page = cursor.get("next", 0)
            time.sleep(0.5)
        return out

    # ---------------- 弹幕 ----------------
    def danmaku(self, cid: int) -> list[dict]:
        """采集全量弹幕。B 站返回 deflate 压缩的 XML，这里手动解压。"""
        url = f"{API}/x/v1/dm/list.so"
        raw = self.session.get_raw(url, {"oid": cid})

        text = ""
        # 先试裸 deflate（无 zlib 头），再试标准 zlib，最后当明文
        for wbits in (-zlib.MAX_WBITS, zlib.MAX_WBITS):
            try:
                text = zlib.decompress(raw, wbits).decode("utf-8", "ignore")
                break
            except zlib.error:
                continue
        if not text:
            text = raw.decode("utf-8", "ignore")

        out: list[dict] = []
        for m in re.finditer(r'<d p="([^"]+)"[^>]*>([^<]*)</d>', text):
            attrs = m.group(1).split(",")
            if len(attrs) < 8:
                continue
            try:
                t = float(attrs[0])
            except ValueError:
                t = 0.0
            out.append({
                "time": round(t, 2),
                "time_str": human_time(t),
                "mode": attrs[1],
                "fontsize": attrs[2],
                "color": attrs[3],
                "timestamp": attrs[4],
                "pool": attrs[5],
                "uid": attrs[6],
                "text": m.group(2),
            })
        return out

    # ---------------- 下载 ----------------
    def download(self, ref: VideoRef, outdir: str, quality: str = "best",
                 audio_only: bool = False,
                 progress: Optional[Callable[[dict], None]] = None,
                 ffmpeg: str = "") -> str:
        """
        用 yt-dlp 下载。返回最终文件路径（取不到则返回 ""）。
        quality: best / 1080p / 720p / 480p / 360p
        """
        import yt_dlp

        os.makedirs(outdir, exist_ok=True)
        info = self.video_info(ref)
        cid = self.cid_of_page(info, ref.page)

        # 分P标题并入文件名，避免同名覆盖
        if len(info.pages) > 1:
            part = next((p["part"] for p in info.pages if p["cid"] == cid), "")
            title_part = f"{info.title} - P{ref.page} {sanitize(part, 40)}"
        else:
            title_part = info.title

        bvid = info.bvid or ref.key
        url = f"https://www.bilibili.com/video/{bvid}"
        if ref.page > 1:
            url += f"?p={ref.page}"

        ydl_opts = {
            "outtmpl": os.path.join(outdir, f"{sanitize(title_part)} [{bvid}].%(ext)s"),
            "format": self.build_format(quality, bool(ffmpeg), audio_only),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "windowsfilenames": True,
            "retries": 5,
            "fragment_retries": 5,
            "socket_timeout": 30,
            "concurrent_fragment_downloads": 4,
            # 优先 H.264，其次分辨率/码率；避免默认挑到 AV1 导致播放器不兼容
            "format_sort": ["vcodec:h264", "res", "br", "size"],
            "http_headers": {
                "User-Agent": UA,
                "Referer": "https://www.bilibili.com/",
            },
        }
        if ffmpeg:
            ydl_opts["ffmpeg_location"] = ffmpeg
        if not audio_only:
            ydl_opts["merge_output_format"] = "mp4"
        if self.session.has_login():
            cj = os.path.join(data_dir(), "cookies.txt")
            try:
                with open(cj, "w", encoding="utf-8") as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    for c in self.session.s.cookies:
                        if "bilibili" not in (c.domain or ""):
                            continue
                        dom = c.domain if c.domain.startswith(".") else "." + c.domain
                        f.write("\t".join([
                            dom, "TRUE", c.path or "/", "FALSE",
                            str(int(c.expires or 0)), c.name, c.value or "",
                        ]) + "\n")
                ydl_opts["cookiefile"] = cj
            except OSError:
                pass

        result = {"path": ""}

        def hook(d):
            if self.stop_event.is_set():
                raise yt_dlp.utils.DownloadError("用户已停止")
            if progress:
                progress(d)
            if d.get("status") == "finished":
                result["path"] = d.get("filename", "")

        ydl_opts["progress_hooks"] = [hook]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                if result["path"]:
                    final = ydl.prepare_filename(info_dict)
                    if os.path.isfile(final):
                        return final
                    if os.path.isfile(result["path"]):
                        return result["path"]
        except Exception as e:
            msg = str(e)
            if self.stop_event.is_set():
                raise BiliError("已停止") from e
            if "ffmpeg" in msg.lower():
                raise BiliError(
                    "该清晰度需要 FFmpeg 合并音视频，当前未检测到 FFmpeg。"
                    "请在界面点击『获取 FFmpeg』或改选『仅单文件』画质。"
                ) from e
            raise BiliError(f"下载失败：{msg[:300]}") from e
        return result["path"]

    @staticmethod
    def build_format(quality: str, has_ffmpeg: bool, audio_only: bool = False) -> str:
        """
        生成 yt-dlp format 表达式。

        注意：B 站同一分辨率会同时提供 avc1(H.264) / hev1(HEVC) / av01(AV1) 三种编码，
        yt-dlp 默认可能挑到 AV1 —— 体积小但老播放器放不了。
        这里显式优先 avc1，兼容性最好；没有 avc1 时再降级。
        """
        if audio_only:
            return "bestaudio/best"
        heights = {"1080p": 1080, "720p": 720, "480p": 480, "360p": 360}
        if quality in heights:
            h = heights[quality]
            if has_ffmpeg:
                return (
                    f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[ext=m4a]/"
                    f"bestvideo[height<={h}]+bestaudio/best[height<={h}]"
                )
            return (
                f"best[height<={h}][ext=mp4]/best[height<={h}]/best[ext=mp4]/best"
            )
        if has_ffmpeg:
            return (
                "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/"
                "bestvideo+bestaudio/best"
            )
        return "best[ext=mp4]/best"
