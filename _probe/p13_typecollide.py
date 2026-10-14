# -*- coding: utf-8 -*-
"""探针 13：类型行是否被「插画窗」下沿切掉 —— 比文本框顶边更严重的碰撞。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image, ImageDraw
from forge import template as T
from forge import compositor as C

OUT = r"D:\游戏王DIY设计\_probe"
CAN = T.CANVAS
ar = T.region("artwork")
art_bottom = ar[1] + ar[3]
tll = T.region("type_line")
print(f"插画窗底边 y{art_bottom:.0f}")
print(f"类型行基线 y{tll[1]:.0f}  可用宽 {tll[2]:.0f}")
print(f"→ 类型行基线在插画窗底边【下方】{tll[1]-art_bottom:.0f}px")
print()

print("=== 各卡种：类型行墨迹的上下边界 vs 插画窗底边 ===")
for nm in ("c01_normal", "c02_effect", "c04_link", "c07_xyz", "c08_synchro",
           "c09_fusion", "c10_ritual", "c05_spell", "x15_procedural"):
    a = np.asarray(Image.open(os.path.join(OUT, nm + ".png")).convert("RGB")).astype(np.int16)
    y0, y1 = int(art_bottom) - 6, int(tll[1]) + 30
    band = a[y0:y1, int(T.sx(63)) + 4:int(T.sx(63)) + int(T.sx(500))]
    dark = band.mean(axis=2) < 130
    rows = np.where(dark.sum(axis=1) > 4)[0]
    if not len(rows):
        print(f"  {nm:<16} 无墨迹"); continue
    top, bot = y0 + rows.min(), y0 + rows.max()
    clipped = max(0, int(round(art_bottom)) - top)
    print(f"  {nm:<16} 类型行墨迹 y{top}-{bot}  "
          f"插画窗底 y{art_bottom:.0f}  → 被插画窗覆盖 {clipped}px "
          f"({'⚠ 切字' if clipped else 'OK'})  "
          f"文本框顶 y{T.region('text_panel')[1]:.0f} → 越出 {max(0, int(T.region('text_panel')[1])-top)}px")

print()
print("=== 官方卡框自带的类型行在哪？（在裸卡框上找它的位置）===")
fr = Image.open(T.asset_path("frame/effect.png")).convert("RGB").resize(CAN, Image.LANCZOS)
fa = np.asarray(fr).astype(np.int16)
# 官方框文本面板是纯白占位，类型行是画在框上的墨迹 → 在 y1240-1320 找非白深色
band = fa[1230:1340, 90:1050]
dark = band.mean(axis=2) < 200
rows = np.where(dark.sum(axis=1) > 4)[0]
if len(rows):
    print(f"  裸卡框 y1230-1340 里的深色墨迹: y{1230+rows.min()}-{1230+rows.max()}")
    cols = np.where(dark.sum(axis=0) > 1)[0]
    print(f"    横向 x{90+cols.min()}-{90+cols.max()}")
else:
    print("  未找到（该区域是纯白占位，说明官方框【没有】画类型行）")
print()
print("  结论核对：官方卡框图在此区域", "有" if len(rows) else "没有", "自带类型行")
print("  →", "渲染器必须自己画，但要画在正确位置" if len(rows) else
      "官方框留了空白给类型行，渲染器必须自己画 —— 位置必须完全按真卡标定")

print()
print("=== 修复方案试算：把类型行下移到完全不切字 ===")
print(f"  当前基线 y{tll[1]:.0f}，字形高约 55px → 墨迹顶 = {tll[1]-55:.0f}")
print(f"  插画窗底 y{art_bottom:.0f} → 基线至少要 ≥ {art_bottom+55:.0f}")
print(f"  对应 813 系 y = {(art_bottom+55)/T.SY:.1f}  （当前 GEO 值 918）")
print(f"  文本框顶 y{T.region('text_panel')[1]:.0f} → 基线 ≥ {T.region('text_panel')[1]+55:.0f}")
print(f"  对应 813 系 y = {(T.region('text_panel')[1]+55)/T.SY:.1f}")
print(f"  → 取 max = {(max(art_bottom, T.region('text_panel')[1])+55)/T.SY:.1f}，"
      f"即 GEO['type_line'] 的 y 建议从 918 改到 ~942")
print(f"  但文本框底只有 y{T.region('text_panel')[1]+T.region('text_panel')[3]:.0f}"
      f"（813系 1111），类型行下移会压缩正文空间")
