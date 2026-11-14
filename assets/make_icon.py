#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成小程序头像：深色渐变底 + 纳指100 成立以来走势（背景）+ 数字「100」（主体）。

层级关系（按你的要求）：
  1. 底部渐变（最远）
  2. 走势线（背景，压低对比度，底部浓、向上渐隐）
  3. 数字 100（主体，亮色实心，压在最上）

数字用超粗无衬线字体、收紧字距、垂直渐变填充，4 倍超采样后缩小，
保证 40px 下依然清晰。输出 1024（母版）、512、144（微信头像规格）。
"""
import json
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "scripts", "out", "index_history_monthly.json")

BG_TOP = (18, 30, 44)       # #121e2c
BG_BOTTOM = (21, 58, 56)    # #153a38
TEXT_TOP = (167, 243, 208)  # #a7f3d0 顶部浅薄荷
TEXT_BOTTOM = (34, 197, 94)  # #22c55e 底部深绿

TREND_LINE = (94, 190, 148)  # 走势线颜色，刻意比数字暗
TREND_ALPHA_BOTTOM = 0.22    # 贴底处的透明度
TREND_ALPHA_TOP = 0.0        # 向上完全渐隐
TREND_HEIGHT_RATIO = 0.58    # 走势区占画布高度比例，底部对齐

CANVAS = 1024
SS = 4
S = CANVAS * SS

TEXT = "100"
TARGET_WIDTH = 0.66         # 数字宽度占画布比例
TRACKING = -0.012            # 字距（相对字号，负数收紧）

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\seguibl.ttf",   # Segoe UI Black
    r"C:\Windows\Fonts\ariblk.ttf",    # Arial Black
    r"C:\Windows\Fonts\arialbd.ttf",   # Arial Bold
    r"/System/Library/Fonts/Supplemental/Arial Black.ttf",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise SystemExit("找不到可用字体")


def gradient_bg(size):
    img = Image.new("RGB", (1, size), BG_TOP)
    px = img.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px[0, y] = tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
    return img.resize((size, size), Image.BILINEAR)


def text_width(font, text, tracking):
    w = 0
    for ch in text:
        w += font.getlength(ch)
    return w + tracking * (len(text) - 1)


def draw_text_mask(size):
    """返回已居中、收紧字距的文字蒙版（L 模式）"""
    target = size * TARGET_WIDTH
    lo, hi = 10, size
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if text_width(load_font(mid), TEXT, TRACKING * mid) <= target:
            lo = mid
        else:
            hi = mid

    font = load_font(lo)
    tracking = TRACKING * lo

    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)

    widths = [font.getlength(ch) for ch in TEXT]
    total = sum(widths) + tracking * (len(TEXT) - 1)
    bbox = font.getbbox(TEXT)
    text_h = bbox[3] - bbox[1]

    x = (size - total) / 2
    y = (size - text_h) / 2 - bbox[1]
    for ch, w in zip(TEXT, widths):
        d.text((x, y), ch, font=font, fill=255)
        x += w + tracking

    return mask


def load_trend_values():
    with open(DATA, encoding="utf-8") as f:
        rows = json.load(f)["rows"]
    return [float(r["close"]) for r in rows]


def trend_layer(size):
    """把成立以来的月线画成底部背景层。

    用对数刻度：125 → 28,289 相差 226 倍，线性刻度会把前 30 年压成一条平线。
    """
    values = load_trend_values()
    logs = [math.log(v) for v in values]
    lo, hi = min(logs), max(logs)
    span = hi - lo or 1.0

    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    top = size * (1 - TREND_HEIGHT_RATIO)
    bottom = size * 1.0
    usable = bottom - top
    pad_x = size * 0.03

    n = len(values)
    pts = []
    for i, lg in enumerate(logs):
        x = pad_x + (size - 2 * pad_x) * i / (n - 1)
        y = bottom - ((lg - lo) / span) * usable
        pts.append((x, y))

    # 面积填充
    draw.polygon(pts + [(size, pts[-1][1]), (size, size), (0, size), (0, pts[0][1])],
                 fill=TREND_LINE + (255,))

    # 顶部渐隐到全透明，让走势线只在底部「浮」出来
    vgrad = Image.new("L", (1, size))
    px = vgrad.load()
    for y in range(size):
        if y < top:
            px[0, y] = 0
        else:
            t = (y - top) / max(1, size - top - 1)
            px[0, y] = round(255 * (TREND_ALPHA_TOP + (TREND_ALPHA_BOTTOM - TREND_ALPHA_TOP) * t**0.7))
    vgrad = vgrad.resize((size, size), Image.BILINEAR)
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), vgrad))

    # 折线叠一道，让走势更清晰
    line = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    width = max(2, round(size / 210))
    for i in range(n - 1):
        ld.line([pts[i], pts[i + 1]], fill=TREND_LINE + (255,), width=width, joint="curve")
    line = line.filter(ImageFilter.GaussianBlur(size / 1400))
    line.putalpha(ImageChops.multiply(line.getchannel("A"), vgrad))

    return Image.alpha_composite(layer, line)


def main():
    bg = gradient_bg(S).convert("RGBA")

    # 第二层：走势线背景（在数字之下）
    bg = Image.alpha_composite(bg, trend_layer(S))

    # 第三层：数字 100（主体）
    mask = draw_text_mask(S)
    grad = Image.new("RGB", (1, S))
    px = grad.load()
    for y in range(S):
        t = y / max(1, S - 1)
        px[0, y] = tuple(round(TEXT_TOP[i] + (TEXT_BOTTOM[i] - TEXT_TOP[i]) * t) for i in range(3))
    grad = grad.resize((S, S), Image.BILINEAR)

    icon = bg.copy()
    icon.paste(grad, (0, 0), mask)
    icon = icon.convert("RGB").resize((CANVAS, CANVAS), Image.LANCZOS)

    for size in (1024, 512, 144):
        out = icon if size == 1024 else icon.resize((size, size), Image.LANCZOS)
        name = "icon-%d.png" % size
        out.save(os.path.join(HERE, name), "PNG", optimize=True)
        print("saved", name)


if __name__ == "__main__":
    main()
