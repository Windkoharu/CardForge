# -*- coding: utf-8 -*-
"""探针 5：文字版式的精确像素测量（隔离文本面板，避开测试插画的干扰）。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from forge import template as T
from forge import compositor as C

OUT = r"D:\游戏王DIY设计\_probe"
CAN = T.CANVAS

print("=" * 104)
print("① 字体对象报告的字号 vs 实际字形高度")
print("=" * 104)
f = C.font("text", 42)
print(f"  C.font('text',42) -> .size={f.size}  .path={getattr(f,'path','?')}")
print(f"  getmetrics() = {f.getmetrics()}")
print(f"  getlength('测') = {f.getlength('测'):.1f}   getlength('A') = {f.getlength('A'):.1f}")
print(f"  getbbox('测') = {f.getbbox('测')}")
tmp = Image.new("L", (200, 120), 0)
ImageDraw.Draw(tmp).text((10, 20), "测", font=f, fill=255)
a = np.asarray(tmp)
ys, xs = np.where(a > 60)
print(f"  实绘「测」bbox : x{xs.min()}-{xs.max()} (w={xs.max()-xs.min()+1}) "
      f"y{ys.min()}-{ys.max()} (h={ys.max()-ys.min()+1})")
print(f"  → 视觉字号 / .size = {(ys.max()-ys.min()+1)/42:.3f}")

f2 = C.font("text", 30)
tmp = Image.new("L", (200, 120), 0)
ImageDraw.Draw(tmp).text((10, 20), "测", font=f2, fill=255)
a = np.asarray(tmp)
ys, xs = np.where(a > 60)
print(f"  C.font('text',30) 实绘「测」高 = {ys.max()-ys.min()+1}px  (.size={f2.size})")

print()
print("=" * 104)
print("② fit_text_block：为什么「官方长度」的卡文也被横压？")
print("=" * 104)
d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
tl, tt, pw, ph = T.region("text_panel")
inner_w = pw - T.sx(8) * 2
bxh = T.region("text_box")[3]
print(f"  text_panel w={pw:.1f}  inner_w={inner_w:.1f}  text_box h={bxh:.1f}")
print(f"  FIT_PROFILES['description'] = {T.FIT_PROFILES['description']}")
print()
txt = ("①：这张卡召唤成功时才能发动。从卡组把1张「测试」卡加入手卡。"
       "②：1回合1次，以自己场上1只怪兽为对象才能发动。那只怪兽的攻击力直到回合结束时上升1000。"
       "这个效果在对方回合也能发动。③：这张卡被送去墓地的场合才能发动。自己从卡组抽1张。")
for prof in T.FIT_PROFILES["description"]:
    size = max(8, int(round(prof["fontSize"] * T.SY)))
    lh = max(size, int(round(prof["lineHeight"] * T.SY)))
    ff = C.font("text", size)
    q = T.COMPRESS["autoScaleXQuantifier"]
    steps = [round(1.0 - i * q, 4) for i in range(int(round(T.COMPRESS["maxAutoCompressionX"] / q)) + 1)]
    ok = None
    for cx in steps:
        lines = C.wrap_text(txt, ff, int(inner_w / cx), d)
        if len(lines) <= prof["maxLines"] and len(lines) * lh <= bxh:
            ok = (cx, lines, lh)
            break
    if ok:
        cx, lines, lh = ok
        print(f"  档 {prof['id']:<12} size={size:>3} lh={lh:>5.1f} maxLines={prof['maxLines']}")
        print(f"      → 命中 横压={cx:.2f}  行数={len(lines)}  占高={len(lines)*lh:.0f}/{bxh:.0f}")
        for i, ln in enumerate(lines):
            print(f"         L{i+1} w={d.textlength(ln, font=ff):6.1f}/{inner_w:.0f} "
                  f"({d.textlength(ln, font=ff)/inner_w*100:5.1f}%)  {ln[:26]}")
        break
print()
print("  ★ 若允许 横压=1.00 会怎样：")
size = max(8, int(round(T.FIT_PROFILES['description'][0]['fontSize'] * T.SY)))
ff = C.font("text", size)
lines = C.wrap_text(txt, ff, int(inner_w), d)
print(f"     size={size} 行数={len(lines)}  maxLines=5  "
      f"{'可以放下！' if len(lines)<=5 else '放不下'}")
for i, ln in enumerate(lines):
    print(f"       L{i+1} w={d.textlength(ln, font=ff):6.1f}/{inner_w:.0f} "
          f"({d.textlength(ln, font=ff)/inner_w*100:5.1f}%)  {ln[:26]}")

print()
print("=" * 104)
print("③ 渲染图文本面板实测：行高 / 行数 / 左右边界")
print("=" * 104)
pl, pt, pw, ph = T.region("text_panel")
for nm in ("c02_effect", "c07_xyz", "c04_link", "x07_jpmix"):
    img = Image.open(os.path.join(OUT, nm + ".png")).convert("RGB")
    a = np.asarray(img).astype(np.int16)
    # 只在 text_panel 内取「文字墨」= 比面板底色暗很多的像素
    x0, x1 = int(pl) + 4, int(pl + pw) - 4
    y0, y1 = int(pt) + 4, int(pt + ph) - 4
    sub = a[y0:y1, x0:x1]
    bg = np.median(sub.reshape(-1, 3), axis=0)
    dark = (np.abs(sub - bg).sum(axis=2) > 90)
    rows = dark.sum(axis=1)
    # 找文字行
    lines = []
    inrun = False
    for i, v in enumerate(rows):
        if v > 3 and not inrun:
            st = i; inrun = True
        elif v <= 3 and inrun:
            lines.append((y0 + st, y0 + i - 1)); inrun = False
    if inrun:
        lines.append((y0 + st, y0 + len(rows) - 1))
    cols = np.where(dark.any(axis=0))[0]
    print(f"  {nm:<12} 面板 x{x0}-{x1} y{y0}-{y1}  底色 {bg}")
    if len(cols):
        print(f"      墨迹横向 x{x0+cols.min()}-{x0+cols.max()}  "
              f"(面板内边距 左{x0+cols.min()-x0}px 右{x1-(x0+cols.max())}px)")
    print(f"      行段 {len(lines)} 段：", end="")
    for (s, e) in lines[:8]:
        print(f"[y{s}-{e} h{e-s+1}] ", end="")
    print()
    if len(lines) > 1:
        gaps = [lines[i + 1][0] - lines[i][0] for i in range(len(lines) - 1)]
        print(f"      行距 = {gaps}")

print()
print("=" * 104)
print("④ 卡名条：卡名是否超出 / 是否居中")
print("=" * 104)
tb = T.region("title_bevel")
print(f"  GEO['title_bevel'] = x{tb[0]:.0f}-{tb[0]+tb[2]:.0f} y{tb[1]:.0f}-{tb[1]+tb[3]:.0f}")
print(f"  代码用 nx=T.sx(62)={T.sx(62):.0f}  name_max_w=T.sx(608)={T.sx(608):.0f} "
      f"→ 右端 {T.sx(62)+T.sx(608):.0f} (卡名条右端 {tb[0]+tb[2]:.0f})")
for nm in ("c02_effect", "x12_longname", "c01_normal", "x07_jpmix"):
    img = Image.open(os.path.join(OUT, nm + ".png")).convert("RGB")
    a = np.asarray(img).astype(np.int16)
    y0, y1 = int(tb[1]), int(tb[1] + tb[3])
    sub = a[y0:y1, :]
    bg = np.median(sub.reshape(-1, 3), axis=0)
    dark = (np.abs(sub - bg).sum(axis=2) > 120)
    # 排除右上角属性圆标（x > 950）
    dark[:, 940:] = False
    cols = np.where(dark.sum(axis=0) > 1)[0]
    rows = np.where(dark.sum(axis=1) > 1)[0]
    if len(cols):
        print(f"  {nm:<14} 卡名墨迹 x{cols.min()}-{cols.max()} "
              f"y{y0+rows.min()}-{y0+rows.max()} 高{rows.max()-rows.min()+1}px  "
              f"左留白{cols.min()-int(tb[0])}px 右留白{int(tb[0]+tb[2])-cols.max()}px  "
              f"{'⚠ 越过 name_max_w' if cols.max() > T.sx(62)+T.sx(608) else ''}")

print()
print("=" * 104)
print("⑤ ATK/DEF 落点（只在数值行条带里找墨迹）")
print("=" * 104)
for nm in ("c02_effect", "c07_xyz", "c04_link", "c01_normal", "x08_question"):
    img = Image.open(os.path.join(OUT, nm + ".png")).convert("RGB")
    a = np.asarray(img).astype(np.int16)
    y0 = int(T.sy(1085))
    y1 = int(T.sy(1140))
    sub = a[y0:y1, 60:1120]
    bg = np.median(sub.reshape(-1, 3), axis=0)
    dark = (np.abs(sub - bg).sum(axis=2) > 110)
    cols = np.where(dark.sum(axis=0) > 1)[0]
    rows = np.where(dark.sum(axis=1) > 1)[0]
    if len(cols):
        print(f"  {nm:<14} 墨迹 x{60+cols.min()}-{60+cols.max()} "
              f"y{y0+rows.min()}-{y0+rows.max()} 高{rows.max()-rows.min()+1}px  "
              f"| 官方 atk右端{T.sx(583):.0f} def右端{T.sx(748):.0f} "
              f"link右端{T.sx(747):.0f}")
