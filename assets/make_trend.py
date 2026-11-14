#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成纳指100 成立以来的走势背景图（月线，对数刻度）。

用途：铺在小程序概览卡底部作为氛围背景，以及头像里的底纹。
因为是「背景」，所以刻意压低对比度，不与前景的主数字争视觉。

为什么用对数刻度：1985 年基准 125 点，如今 28,289 点，相差 226 倍。
线性刻度会把 1985-2015 这三十年压成贴底的一条平线，看不出任何形态。
对数刻度下每一倍的涨幅占同样的高度，42 年的起伏才都能看见。

数据源：scripts/out/index_history_monthly.json（由 fetch_index_history.py 产出）
"""
import json
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "scripts", "out", "index_history_monthly.json")

# 输出画布（2 倍图，足够 750rpx 宽卡片使用，体积仍然很小）
W, H = 900, 196
SS = 3  # 超采样倍数，缩小后边缘更平滑
SW, SH = W * SS, H * SS

LINE_FROM = (62, 132, 104)    # 左端：偏暗的薄荷绿
LINE_TO = (108, 203, 158)     # 右端：柔化的薄荷绿
FILL_TOP_ALPHA = 0.26
FILL_BOTTOM_ALPHA = 0.02

# 上下留白，避免线贴边被切
PAD_TOP = 0.14
PAD_BOTTOM = 0.08
PAD_X = 0.014  # 左右各留一点，首尾点不贴边


def load_series():
    with open(DATA, encoding="utf-8") as f:
        rows = json.load(f)["rows"]
    return [(r["date"], float(r["close"])) for r in rows]


def project(values):
    """对数刻度投影到画布坐标。"""
    logs = [math.log(v) for v in values]
    lo, hi = min(logs), max(logs)
    span = hi - lo or 1.0
    top = SH * PAD_TOP
    bottom = SH * (1 - PAD_BOTTOM)
    usable = bottom - top

    n = len(values)
    left = SW * PAD_X
    right = SW * (1 - PAD_X)
    usable_w = right - left
    pts = []
    for i, lg in enumerate(logs):
        x = left + usable_w * i / (n - 1)
        t = (lg - lo) / span
        y = bottom - t * usable
        pts.append((x, y))
    return pts


def vertical_alpha(size, top_alpha, bottom_alpha):
    """自上而下的透明度渐变（L 模式蒙版）。"""
    grad = Image.new("L", (1, size))
    px = grad.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px[0, y] = round(255 * (top_alpha + (bottom_alpha - top_alpha) * t))
    return grad.resize((SW, SH), Image.BILINEAR)


def horizontal_fade(size):
    """水平方向淡化：左端稍淡，右端实，形成「走到今天」的方向感。"""
    grad = Image.new("L", (size, 1))
    px = grad.load()
    for x in range(size):
        t = x / max(1, size - 1)
        px[x, 0] = round(255 * (0.45 + 0.55 * t))
    return grad.resize((SW, SH), Image.BILINEAR)


def build_trend():
    series = load_series()
    values = [v for _, v in series]
    pts = project(values)

    layer = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # ---- 面积填充 ----
    poly = pts + [(SW, pts[-1][1]), (SW, SH), (0, SH), (0, pts[0][1])]
    draw.polygon(poly, fill=(LINE_TO[0], LINE_TO[1], LINE_TO[2], 255))

    # 垂直渐变 × 水平渐变 = 最终透明度
    alpha = ImageChops.multiply(
        vertical_alpha(SH, FILL_TOP_ALPHA, FILL_BOTTOM_ALPHA),
        horizontal_fade(SW),
    )
    layer.putalpha(alpha)

    # ---- 折线（逐段插值颜色，形成左右渐变） ----
    line = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    width = max(2, round(SW / 300))
    n = len(pts)
    for i in range(n - 1):
        t = i / max(1, n - 2)
        color = tuple(round(LINE_FROM[c] + (LINE_TO[c] - LINE_FROM[c]) * t) for c in range(3))
        ld.line([pts[i], pts[i + 1]], fill=color + (255,), width=width, joint="curve")
    # 顶端小圆点，强调当前位置
    r = max(3, round(SW / 260))
    cx, cy = pts[-1]
    ld.ellipse([cx - r, cy - r, cx + r, cy + r], fill=LINE_TO + (255,))

    line = line.filter(ImageFilter.GaussianBlur(SS * 0.35))

    out = Image.alpha_composite(layer, line)
    return out.resize((W, H), Image.LANCZOS)


def main():
    trend = build_trend()
    path = os.path.join(HERE, "trend-42y.png")
    trend.save(path, "PNG", optimize=True)
    size = os.path.getsize(path)
    print("saved %s  %dx%d  %.1f KB" % (os.path.basename(path), W, H, size / 1024))


if __name__ == "__main__":
    main()
