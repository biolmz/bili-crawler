# -*- coding: utf-8 -*-
"""核心模块自测：解析 / 视频信息 / 弹幕 / 评论 / 下载格式表达式"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from bili_core import BiliClient, parse_input, BiliError, find_ffmpeg  # noqa

BV = "BV1GJ411x7h7"

print("=" * 60)
print("[1] FFmpeg:", find_ffmpeg() or "(未找到)")

print("=" * 60)
print("[2] 输入解析")
for s in ["BV1GJ411x7h7",
          "av80433022",
          "https://www.bilibili.com/video/BV1GJ411x7h7?p=2",
          "https://space.bilibili.com/1234/video",
          "乱七八糟的东西"]:
    r = parse_input(s)
    print(f"  {s[:46]:48s} -> {[(x.key, x.page) for x in r]}")

cli = BiliClient(log=lambda m: print("   log:", m))

print("=" * 60)
print("[3] 视频信息")
refs = parse_input(BV)
info = cli.video_info(refs[0])
print("  标题:", info.title)
print("  UP主:", info.owner_name, "| mid:", info.owner_mid)
print("  BV:", info.bvid, "| aid:", info.aid, "| cid:", info.cid)
print("  时长:", info.duration, "s | 分P数:", len(info.pages))
print("  播放:", info.view, "| 弹幕:", info.danmaku, "| 评论:", info.reply,
      "| 点赞:", info.like)

print("=" * 60)
print("[4] 弹幕采集")
try:
    dm = cli.danmaku(info.cid)
    print(f"  共 {len(dm)} 条")
    for d in dm[:3]:
        print("   ", d["time_str"], d["uid"], d["text"][:30])
except BiliError as e:
    print("  失败:", e)

print("=" * 60)
print("[5] 评论采集")
try:
    cm = cli.comments(info.aid, 20)
    print(f"  共 {len(cm)} 条")
    for c in cm[:3]:
        print(f"    {c['user']} (赞{c['like']}): {c['content'][:36]}")
except BiliError as e:
    print("  失败(可能需要 Cookie):", e)

print("=" * 60)
print("[6] format 表达式")
for q in ("best", "1080p", "720p", "480p"):
    print(f"  有ffmpeg {q:6s} -> {BiliClient.build_format(q, True)}")
    print(f"  无ffmpeg {q:6s} -> {BiliClient.build_format(q, False)}")
print("  audio=True  ->", BiliClient.build_format("best", True, True))
print("=" * 60)
print("OK")
