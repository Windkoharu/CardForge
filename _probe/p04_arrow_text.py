# -*- coding: utf-8 -*-
"""探针 4：连接箭头素材几何 + 渲染落点；星级/阶级星落点；文字包围盒。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image, ImageDraw
from forge import template as T
from forge import compositor as C

OUT = r"D:\游戏王DIY设计\_probe"
CAN = T.CANVAS

print("=" * 104)
print("① 连接箭头素材：原生尺寸 / alpha bbox / 非透明像素重心")
print("=" * 104)
for d, suf in T.ARROW_DIRS.items():
    for st in ("on", "off"):
        rel = f"arrow/{suf}-{st}.png"
        im = Image.open(T.asset_path(rel)).convert("RGBA")
        a = np.asarray(im)
        al = a[:, :, 3]
        ys, xs = np.where(al > 8)
        if not len(ys):
            print(f"  {rel:<26} {im.size}  EMPTY"); continue
        bx0, bx1, by0, by1 = xs.min(), xs.max(), ys.min(), ys.max()
        cx = (bx0 + bx1) / 2 / im.width
        cy = (by0 + by1) / 2 / im.height
        print(f"  {rel:<26} 原生 {im.size[0]:>4}x{im.size[1]:<4} "
              f"alpha bbox {bx1-bx0+1:>4}x{by1-by0+1:<4} "
              f"重心相对 ({cx:.3f},{cy:.3f})  缩放后可视尺寸 "
              f"{round((bx1-bx0+1)*79/max(im.size))}x{round((by1-by0+1)*79/max(im.size))}")

print()
print("=" * 104)
print("② 渲染图 c04_link 里每个方位的实际彩色像素范围（判定箭头落点）")
print("=" * 104)
a = np.asarray(Image.open(os.path.join(OUT, "c04_link.png")).convert("RGB")).astype(np.int16)
ax, ay, aw, ah = T.region("artwork")
size = int(round(T.sx(56)))
rel = {"左上": (0.055, 0.055), "上": (0.5, 0.018), "右上": (0.945, 0.055),
       "左": (0.018, 0.5), "右": (0.982, 0.5),
       "左下": (0.055, 0.945), "下": (0.5, 0.982), "右下": (0.945, 0.945)}
for cn, (fx, fy) in rel.items():
    cx, cy = ax + aw * fx, ay + ah * fy
    x0, x1 = int(cx - size), int(cx + size)
    y0, y1 = int(cy - size), int(cy + size)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(CAN[0], x1), min(CAN[1], y1)
    sub = a[y0:y1, x0:x1]
    # 「红」像素 = 有效箭头
    red = (sub[:, :, 0] > 140) & (sub[:, :, 0] - sub[:, :, 1] > 50) & (sub[:, :, 0] - sub[:, :, 2] > 50)
    white = (sub[:, :, 0] > 200) & (sub[:, :, 1] > 200) & (sub[:, :, 2] > 200)
    print(f"  {cn:<3} 理论中心 ({cx:6.1f},{cy:6.1f})  采样窗 x{x0}-{x1} y{y0}-{y1}"
          f"  红像素 {red.sum():>5d}  白像素 {white.sum():>5d}"
          f"  {'← 应为 ON 但没红' if cn in ('上','左下','右下') and red.sum() < 20 else ''}")

print()
print("=" * 104)
print("③ 星级 / 阶级星 落点 vs GEO")
print("=" * 104)
gx, gy, gw, gh = T.region("level_star")
print(f"  GEO['level_star'] = x{gx:.0f}-{gx+gw:.0f} y{gy:.0f}-{gy+gh:.0f}  (h={gh:.0f})")
gx2, gy2, gw2, gh2 = T.region("rank_star")
print(f"  GEO['rank_star']  = x{gx2:.0f}-{gx2+gw2:.0f} y{gy2:.0f}-{gy2+gh2:.0f}")
ar = T.region("artwork")
print(f"  GEO['artwork']    = y{ar[1]:.0f} 起  → 星级底边 y{gy+gh:.0f}，"
      f"距插画窗 {ar[1]-(gy+gh):+.0f}px")
for nm, n in (("c02_effect", 4), ("c07_xyz", 4), ("x10_13star", 13)):
    img = np.asarray(Image.open(os.path.join(OUT, nm + ".png")).convert("RGB")).astype(np.int16)
    band = img[int(gy) - 30:int(gy + gh) + 20, :]
    bright = (band[:, :, 0] > 200) & (band[:, :, 1] > 150) & (band[:, :, 2] < 140)
    cols = np.where(bright.any(axis=0))[0]
    rows = np.where(bright.any(axis=1))[0]
    if len(cols):
        print(f"  {nm:<12} 星横向 x{cols.min()}-{cols.max()}  "
              f"纵向 y{int(gy)-30+rows.min()}-{int(gy)-30+rows.max()}")
        print(f"               → 单星宽约 {(cols.max()-cols.min()+1)/n:.1f}px  "
              f"(GEO 期望 {gw:.1f})  星带底 y{int(gy)-30+rows.max()} "
              f"vs 插画窗顶 y{ar[1]:.0f} 重叠 "
              f"{max(0, int(gy)-30+rows.max()-int(ar[1])+1)}px")
    else:
        print(f"  {nm:<12} 未找到星")

print()
print("=" * 104)
print("④ ATK/DEF 与类型行：文字包围盒 vs 官方实测锚点")
print("=" * 104)
for nm in ("c02_effect", "c07_xyz", "c04_link", "c01_normal"):
    img = Image.open(os.path.join(OUT, nm + ".png")).convert("RGB")
    a = np.asarray(img).astype(np.int16)
    y0 = int(T.sy(1076))
    band = a[y0:y0 + int(T.sy(120)), :]
    dark = band.mean(axis=2) < 110
    cols = np.where(dark.sum(axis=0) > 2)[0]
    rows = np.where(dark.sum(axis=1) > 2)[0]
    if len(cols):
        print(f"  {nm:<12} 深色文字/线 x{cols.min()}-{cols.max()} "
              f"y{y0+rows.min()}-{y0+rows.max()}")
    print(f"              官方锚点 atk右端 x{T.sx(583):.0f} def右端 x{T.sx(748):.0f} "
          f"link右端 x{T.sx(747):.0f}")

print()
print("=" * 104)
print("⑤ fit_text_block 的失效模式：什么时候会截断 / 横压")
print("=" * 104)
probe = Image.new("RGBA", (10, 10))
d = ImageDraw.Draw(probe)
cases = {
    "官方风 3 段": "①：这张卡召唤成功时才能发动。从卡组把1张「测试」卡加入手卡。"
                   "②：1回合1次，以自己场上1只怪兽为对象才能发动。那只怪兽的攻击力直到回合结束时上升1000。"
                   "这个效果在对方回合也能发动。③：这张卡被送去墓地的场合才能发动。自己从卡组抽1张。",
    "×4 超长": "①：这张卡召唤成功时才能发动。从卡组把1张「测试」卡加入手卡。"
               "②：1回合1次，以自己场上1只怪兽为对象才能发动。那只怪兽的攻击力直到回合结束时上升1000。"
               "这个效果在对方回合也能发动。③：这张卡被送去墓地的场合才能发动。自己从卡组抽1张。" * 4,
    "×8 极端": "①：这张卡召唤成功时才能发动。从卡组把1张「测试」卡加入手卡。" * 30,
}
inner_w = (T.region("text_panel")[2] - T.sx(8) * 2)
for k, txt in cases.items():
    f, cx, lines, lh = C.fit_text_block(txt, inner_w, T.region("text_box")[3],
                                        "description", d, "text")
    total = len(lines) * lh
    cap = T.region("text_box")[3]
    print(f"  {k:<12} 字数{len(txt):>5}  字号{f.size:>3}  横压{cx:.2f}  "
          f"行数{len(lines):>3}  行距{lh:.1f}  占高{total:.0f}/{cap:.0f}"
          f"  {'⚠ 截断' if lines and lines[-1].endswith('…') else ''}"
          f"  {'⚠ 溢出' if total > cap else ''}")
