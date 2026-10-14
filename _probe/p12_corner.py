# -*- coding: utf-8 -*-
"""探针 12：焰刃系列成品的插画窗角落放大，确认圆角与白线到底来自哪里。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
from PIL import Image, ImageDraw
import numpy as np
from forge import template as T

SRC = r"D:\workbuddy workspace\2026-10-12-12-38-13\CardForge-造卡产物-焰刃系列.png"
OUT = r"D:\游戏王DIY设计\_probe"
im = Image.open(SRC).convert("RGB")
print("焰刃系列总览图:", im.size)
# 5 张卡横排；找第一张卡的插画窗左上角
a = np.asarray(im).astype(np.int16)
print("尺寸:", im.size)
# 裁第一张卡（左侧 ~1/5）
w5 = im.width // 5
card = im.crop((60, 250, 60 + w5 - 40, 250 + 800))
card = card.resize((card.width * 3, card.height * 3), Image.NEAREST)
card.save(os.path.join(OUT, "z_yanren_card1.png"))
print("saved z_yanren_card1.png", card.size)

# 直接对比：procedural vs official 的插画窗左上角
sys.path.insert(0, OUT)
from p02_render import art_demo, S  # noqa
from forge import compositor as C
art = art_demo(1400, 1400, 1)
spec = S("角部对比", "effect", level=4, attribute="炎", race="战士族",
         atk=1700, **{"def": 1000}, text="①：角部对比。")
g = T.region("artwork")
x0, y0 = int(g[0]), int(g[1])
tiles = []
for mode in ("official", "procedural"):
    img = C.render_card(dict(spec), art, C.CANVAS, frame_mode=mode).convert("RGB")
    c = img.crop((x0 - 14, y0 - 14, x0 + 90, y0 + 90))
    c = c.resize((c.width * 5, c.height * 5), Image.NEAREST)
    d = ImageDraw.Draw(c)
    # 标出 GEO 角点
    d.line([(14 * 5, 0), (14 * 5, c.height)], fill=(255, 0, 255), width=2)
    d.line([(0, 14 * 5), (c.width, 14 * 5)], fill=(255, 0, 255), width=2)
    d.text((6, 6), mode, fill=(255, 0, 255))
    tiles.append(c)
sheet = Image.new("RGB", (sum(t.width for t in tiles) + 20, tiles[0].height), (30, 30, 30))
xx = 0
for t in tiles:
    sheet.paste(t, (xx, 0)); xx += t.width + 20
sheet.save(os.path.join(OUT, "z_corner_cmp.png"))
print("saved z_corner_cmp.png", sheet.size)

print()
print("=== 量化：GEO 角点 (140,307) 处两种基座的像素 ===")
for mode in ("official", "procedural"):
    img = C.render_card(dict(spec), art, C.CANVAS, frame_mode=mode).convert("RGB")
    a2 = np.asarray(img).astype(np.int16)
    print(f"  {mode:<11} 角点(140,307)={tuple(a2[307,140])}  "
          f"(139,306)={tuple(a2[306,139])}  (141,308)={tuple(a2[308,141])}")
print()
print("  解释：official 基座在 (140,307) 仍是框的斜面色（插画从 (141,308) 才开始），")
print("        所以插画窗左上角有 **1px 的框色/亮色三角**，视觉上像一个小圆角。")
print("        procedural 基座用 _rounded_mask 真正做圆角（arad=sx(30)≈42px）。")
