# -*- coding: utf-8 -*-
"""探针 3：对渲染结果做像素级体检。
- 插画窗与官方框白窗的对齐（彩色像素越界了多少）
- 白条残留（灵摆）
- 暗环向外扩张量
- 连接箭头位置/颜色
- 文字包围盒是否越界
"""
import os, sys, json
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image
from forge import template as T
from forge import compositor as C

OUT = r"D:\游戏王DIY设计\_probe"
CAN = T.CANVAS


def load(n):
    return Image.open(os.path.join(OUT, n + ".png")).convert("RGB")


def frame_layer(frame="effect", pend=False):
    rel = T.frame_asset(frame, pend, "effect")
    im = Image.open(T.asset_path(rel)).convert("RGB")
    return np.asarray(im.resize(CAN, Image.LANCZOS)).astype(np.int16)


def box_of_white(a, thr=246):
    m = (a[:, :, 0] > thr) & (a[:, :, 1] > thr) & (a[:, :, 2] > thr)
    ys, xs = np.where(m)
    if not len(ys):
        return None
    return xs.min(), ys.min(), xs.max(), ys.max()


print("=" * 104)
print("① 标准框：插画窗 vs 卡框白窗 —— 未覆盖的白像素 / 越界的彩色像素")
print("=" * 104)
fa = frame_layer("effect")
fb = box_of_white(fa)
print(f"卡框(1140系) 白窗 bbox = x{fb[0]}-{fb[2]} y{fb[1]}-{fb[3]}  "
      f"w={fb[2]-fb[0]+1} h={fb[3]-fb[1]+1}")
rl = T.region("artwork")
print(f"GEO['artwork'] 画布矩形 = x{rl[0]:.0f}-{rl[0]+rl[2]:.0f} "
      f"y{rl[1]:.0f}-{rl[1]+rl[3]:.0f}  w={rl[2]:.0f} h={rl[3]:.0f}")
print()

for nm in ["c02_effect", "c01_normal", "c05_spell", "c06_trap", "c07_xyz",
           "c04_link", "c08_synchro", "c09_fusion", "c10_ritual", "x14_token",
           "x01_noart_effect"]:
    a = np.asarray(load(nm)).astype(np.int16)
    m = (a[:, :, 0] > 246) & (a[:, :, 1] > 246) & (a[:, :, 2] > 246)
    # 只看上半部（插画窗/文本面板以外）
    top = m[:int(CAN[1] * 0.62), :]
    ys, xs = np.where(top)
    wl = int(rl[0]); wt = int(rl[1]); ww = int(rl[2]); wh = int(rl[3])
    # 画窗矩形内的白像素（说明插画没盖满）
    inner = m[wt:wt + wh, wl:wl + ww]
    # 画窗矩形外的白像素（框自带的，属正常）
    outside = m.copy(); outside[wt:wt + wh, wl:wl + ww] = False
    oy, ox = np.where(outside[:int(CAN[1] * 0.62), :])
    print(f"{nm:<18} 画窗内白像素 {inner.sum():>7d}   画窗外(上半)白像素 {len(oy):>7d}"
          f"   最下白点 y={oy.max() if len(oy) else -1}")

print()
print("=" * 104)
print("② 灵摆框：白条残留")
print("=" * 104)
pa = frame_layer("pendulum", True)
print(f"卡框(effect-pendulum,1140系) 白窗 bbox = {box_of_white(pa)}")
g = T.region("pendulum_art_box")
print(f"GEO['pendulum_art_box']  = x{g[0]:.0f}-{g[0]+g[2]:.0f} y{g[1]:.0f}-{g[1]+g[3]:.0f}  "
      f"w={g[2]:.0f} h={g[3]:.0f}")
b = np.asarray(load("c03_pendulum")).astype(np.int16)
m = (b[:, :, 0] > 246) & (b[:, :, 1] > 246) & (b[:, :, 2] > 246)
x0 = int(g[0]); y0 = int(g[1]); x1 = int(g[0] + g[2]); y1 = int(g[1] + g[3])
print(f"\n渲染图里，GEO 画窗下方 (y{y1} 起) 的白像素：")
sub = m[y1:, :]
rows = sub.sum(axis=1)
runs = []
inrun = False
for i, v in enumerate(rows):
    if v > 100 and not inrun:
        st = i; inrun = True
    elif v <= 100 and inrun:
        runs.append((y1 + st, y1 + i - 1)); inrun = False
if inrun:
    runs.append((y1 + st, y1 + len(rows) - 1))
for r in runs:
    seg = m[r[0]:r[1] + 1, :]
    xs2 = np.where(seg.any(axis=0))[0]
    print(f"  白条 y{r[0]}-{r[1]} (高 {r[1]-r[0]+1}px)  x{xs2.min()}-{xs2.max()} (宽 {xs2.max()-xs2.min()+1}px)")
if not runs:
    print("  无")
print()

print("=" * 104)
print("③ 暗环向外扩张量（渲染图 vs 裸卡框，沿画窗左右中线的亮度差）")
print("=" * 104)
a = np.asarray(load("c02_effect")).astype(np.int16)
cy = int(rl[1] + rl[3] / 2)
print("  距画窗左边 x 偏移 d（负=窗外）:  渲染L  -  卡框L  =  差值")
for d in range(-45, 4, 3):
    x = int(rl[0]) + d
    if x < 0:
        continue
    print(f"    d={d:+4d}  x={x:4d}   渲染 {a[cy, x].mean():6.1f}   卡框 {fa[cy, x].mean():6.1f}"
          f"   差 {a[cy, x].mean() - fa[cy, x].mean():+6.1f}")
print()
print("  距画窗右边（正=窗外）:")
rx = int(rl[0] + rl[2]) - 1
for d in range(-4, 46, 3):
    x = rx + d
    if x >= CAN[0]:
        continue
    print(f"    d={d:+4d}  x={x:4d}   渲染 {a[cy, x].mean():6.1f}   卡框 {fa[cy, x].mean():6.1f}"
          f"   差 {a[cy, x].mean() - fa[cy, x].mean():+6.1f}")
print()
print("  距画窗上边（负=窗外）:")
cx = int(rl[0] + rl[2] / 2)
for d in range(-45, 4, 3):
    y = int(rl[1]) + d
    if y < 0:
        continue
    print(f"    d={d:+4d}  y={y:4d}   渲染 {a[y, cx].mean():6.1f}   卡框 {fa[y, cx].mean():6.1f}"
          f"   差 {a[y, cx].mean() - fa[y, cx].mean():+6.1f}")
print()
print("=" * 104)
print("④ 连接箭头：贴片位置与素材颜色的实际落点")
print("=" * 104)
la = np.asarray(load("c04_link")).astype(np.int16)
size = int(round(T.sx(56)))
ax, ay, aw, ah = T.region("artwork")
print(f"箭头素材目标尺寸 size={size}px (=813系{T.sx(56)/T.SX:.1f}px)")
rel = {"左上": (0.055, 0.055), "上": (0.5, 0.018), "右上": (0.945, 0.055),
       "左": (0.018, 0.5), "右": (0.982, 0.5),
       "左下": (0.055, 0.945), "下": (0.5, 0.982), "右下": (0.945, 0.945)}
for cn, (fx, fy) in rel.items():
    cx, cy = ax + aw * fx, ay + ah * fy
    on = cn in ("上", "左下", "右下")
    print(f"  {cn:<3} 中心 ({cx:6.1f},{cy:6.1f})  {'ON ' if on else 'off'}  "
          f"画窗内? x{ax:.0f}-{ax+aw:.0f} y{ay:.0f}-{ay+ah:.0f}  "
          f"{'内' if ax <= cx <= ax+aw and ay <= cy <= ay+ah else '!! 出界'}")
