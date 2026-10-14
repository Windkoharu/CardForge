# -*- coding: utf-8 -*-
"""探针 8：灵摆下半部结构图 + 星带/卡名条放大图，用于肉眼定案。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image, ImageDraw
from forge import template as T
from forge import compositor as C

OUT = r"D:\游戏王DIY设计\_probe"
CAN = T.CANVAS


def crop_scaled(src, box, scale, dst, grid=None):
    im = Image.open(os.path.join(OUT, src)).convert("RGB")
    c = im.crop(box)
    c = c.resize((int(c.width * scale), int(c.height * scale)), Image.NEAREST)
    d = ImageDraw.Draw(c)
    if grid:
        for (gx, gy, label, col) in grid:
            X = (gx - box[0]) * scale
            Y = (gy - box[1]) * scale
            d.line([(X, 0), (X, c.height)], fill=col, width=2)
            d.line([(0, Y), (c.width, Y)], fill=col, width=2)
            d.text((X + 3, Y + 3), label, fill=col)
    c.save(os.path.join(OUT, dst))
    print(f"  saved {dst} {c.size}")


print("灵摆下半部（含 GEO 参考线）")
g = T.region("pendulum_art_box")
pp = T.region("pendulum_panel")
mp = T.region("pendulum_monster_panel")
sl = T.region("pendulum_scale_l")
grid = [
    (0, int(g[1] + g[3]), "art_box bottom", (255, 0, 255)),
    (0, int(pp[1]), "pend_panel top", (0, 255, 255)),
    (0, int(pp[1] + pp[3]), "pend_panel bottom", (0, 255, 255)),
    (0, int(mp[1]), "mon_panel top", (255, 128, 0)),
    (0, int(mp[1] + mp[3]), "mon_panel bottom", (255, 128, 0)),
    (0, int(T.sy(1090)), "geo1090", (255, 255, 0)),
    (0, int(T.sy(1111)), "geo1111 text_panel slot", (128, 255, 128)),
    (0, CAN[1] - 1, "card bottom", (255, 255, 255)),
]
crop_scaled("c03_pendulum.png", (60, int(g[1] + g[3]) - 60, 1090, 1600), 1.15,
            "z_pend_lower.png", grid)

print("星带 + 卡名条")
tb = T.region("title_bevel")
ls = T.region("level_star")
crop_scaled("c02_effect.png", (60, int(tb[1]) - 20, 1090, 340), 1.5, "z_stars_effect.png",
            [(0, int(ls[1]), "level_star top", (255, 0, 255)),
             (0, int(ls[1] + ls[3]), "level_star bottom", (255, 0, 255)),
             (0, int(T.region("artwork")[1]), "art top", (0, 255, 255)),
             (int(T.sx(680)), 0, "star band right", (255, 255, 0))])
crop_scaled("c07_xyz.png", (60, int(tb[1]) - 20, 1090, 340), 1.5, "z_stars_xyz.png",
            [(int(T.sx(89.6)), 0, "rank left", (255, 255, 0)),
             (0, int(ls[1] + ls[3]), "level_star bottom", (255, 0, 255)),
             (0, int(T.region("artwork")[1]), "art top", (0, 255, 255))])

print("文本框顶部（类型行 + 首行效果文）")
tp = T.region("text_panel")
crop_scaled("c02_effect.png", (int(tp[0]) - 10, int(tp[1]) - 10, int(tp[0] + tp[2]) + 10,
                               int(tp[1]) + 200), 1.6, "z_text_top.png",
            [(0, int(T.region("type_line")[1]), "type_line baseline", (255, 0, 255)),
             (0, int(T.region("text_box")[1]), "text_box top", (0, 255, 255))])

print("ATK/DEF 行")
crop_scaled("c02_effect.png", (60, int(T.sy(1060)), 1120, 1662), 1.5, "z_stats.png",
            [(0, int(T.sy(1076)), "separator", (255, 0, 255)),
             (int(T.sx(583)), 0, "atk anchor", (0, 255, 255)),
             (int(T.sx(748)), 0, "def anchor", (255, 128, 0))])
crop_scaled("c04_link.png", (60, int(T.sy(1060)), 1120, 1662), 1.5, "z_stats_link.png",
            [(0, int(T.sy(1076)), "separator", (255, 0, 255)),
             (int(T.sx(747)), 0, "link anchor", (0, 255, 255))])
