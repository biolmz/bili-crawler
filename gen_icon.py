# -*- coding: utf-8 -*-
"""生成程序图标 app.ico（粉色圆角方块 + 白色播放三角），纯标准库手写 ICO。"""
import os
import struct

PINK = (0xFB, 0x72, 0x99)   # R,G,B
WHITE = (0xFF, 0xFF, 0xFF)


def render(size: int, ss: int = 3):
    """超采样抗锯齿渲染，返回 BGRA 字节（bottom-up 由调用方拼）。"""
    N = size * ss
    pad = N * 0.045           # 外留白
    r = N * 0.30              # 圆角半径
    x0, y0 = pad, pad
    x1, y1 = N - pad, N - pad

    # 播放三角（指向右）
    t = [(N * 0.36, N * 0.28), (N * 0.36, N * 0.72), (N * 0.72, N * 0.50)]

    def in_round_rect(px, py):
        cx = min(max(px, x0 + r), x1 - r)
        cy = min(max(py, y0 + r), y1 - r)
        if x0 <= px <= x1 and y0 <= py <= y1:
            dx, dy = px - cx, py - cy
            return dx * dx + dy * dy <= r * r or (x0 + r <= px <= x1 - r) or (y0 + r <= py <= y1 - r)
        return False

    def sign(ax, ay, bx, by, px, py):
        return (px - bx) * (ay - by) - (ax - bx) * (py - by)

    def in_tri(px, py):
        d1 = sign(t[0][0], t[0][1], t[1][0], t[1][1], px, py)
        d2 = sign(t[1][0], t[1][1], t[2][0], t[2][1], px, py)
        d3 = sign(t[2][0], t[2][1], t[0][0], t[0][1], px, py)
        neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
        pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
        return not (neg and pos)

    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            bg_hit = fg_hit = 0
            for sy in range(ss):
                for sx in range(ss):
                    px = x * ss + sx + 0.5
                    py = y * ss + sy + 0.5
                    inside = in_round_rect(px, py)
                    if inside:
                        if in_tri(px, py):
                            fg_hit += 1
                        else:
                            bg_hit += 1
            tot = ss * ss
            cov_bg = bg_hit / tot
            cov_fg = fg_hit / tot
            if cov_bg + cov_fg <= 0:
                row.append((0, 0, 0, 0))
            else:
                a = int(round(255 * (cov_bg + cov_fg)))
                # 混合颜色
                rr = (PINK[0] * cov_bg + WHITE[0] * cov_fg) / (cov_bg + cov_fg)
                gg = (PINK[1] * cov_bg + WHITE[1] * cov_fg) / (cov_bg + cov_fg)
                bb = (PINK[2] * cov_bg + WHITE[2] * cov_fg) / (cov_bg + cov_fg)
                row.append((int(rr), int(gg), int(bb), a))
        rows.append(row)
    return rows


def to_image_bytes(size: int, rows) -> bytes:
    """BITMAPINFOHEADER + XOR(BGRA, bottom-up) + AND mask。"""
    hdr = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    xor = bytearray()
    for y in range(size - 1, -1, -1):          # bottom-up
        for x in range(size):
            r, g, b, a = rows[y][x]
            xor += bytes((b, g, r, a))         # BGRA
    rowbytes = ((size + 31) // 32) * 4          # 1bpp 行按 4 字节对齐
    andmask = bytes(rowbytes * size)            # 全 0：交给 alpha 通道
    return hdr + bytes(xor) + andmask


def build(path: str, sizes=(16, 32, 48, 64, 128, 256)):
    imgs = []
    for s in sizes:
        imgs.append((s, to_image_bytes(s, render(s))))
    n = len(imgs)
    header = struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    entries, blobs = b"", b""
    for s, data in imgs:
        w = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)
    print(f"icon written: {os.path.abspath(path)}  ({os.path.getsize(path)} bytes, {n} sizes)")


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "assets", "app.ico")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    build(out)
