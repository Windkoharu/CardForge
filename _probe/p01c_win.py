# -*- coding: utf-8 -*-
"""探针 1c：用素材声明的精确窗口量白窗边界，并输出卡框真彩放大图供肉眼比对。"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image
from forge import template as T

OUT = r"D:\游戏王DIY设计\_probe"
CAN = T.CANVAS


def measure(rel, decl, name):
    im = Image.open(T.asset_path(rel)).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    H, W = a.shape[:2]
    dx0, dy0, dx1, dy1 = decl
    # 以声明窗为起点，向四边扩张直到不再是纯白
    thr = 246
    white = (a[:, :, 0] > thr) & (a[:, :, 1] > thr) & (a[:, :, 2] > thr)
    cy = (dy0 + dy1) // 2
    cx = (dx0 + dx1) // 2
    x0 = dx0
    while x0 > 0 and white[cy, x0 - 1]:
        x0 -= 1
    x1 = dx1
    while x1 < W - 1 and white[cy, x1 + 1]:
        x1 += 1
    y0 = dy0
    while y0 > 0 and white[y0 - 1, cx]:
        y0 -= 1
    y1 = dy1
    while y1 < H - 1 and white[y1 + 1, cx]:
        y1 += 1
    rx, ry = T.REF[0] / W, T.REF[1] / H
    print(f"--- {name} ({rel})  native {W}x{H}")
    print(f"    声明窗  原图 x{dx0}-{dx1} y{dy0}-{dy1}  (w={dx1-dx0+1} h={dy1-dy0+1})")
    print(f"    实测窗  原图 x{x0}-{x1} y{y0}-{y1}  (w={x1-x0+1} h={y1-y0+1})")
    print(f"    实测→813系 x{x0*rx:.1f}-{(x1+1)*rx:.1f} y{y0*ry:.1f}-{(y1+1)*ry:.1f} "
          f"(w={(x1+1-x0)*rx:.1f} h={(y1+1-y0)*ry:.1f})")
    print(f"    声明→813系 x{dx0*rx:.1f}-{(dx1+1)*rx:.1f} y{dy0*ry:.1f}-{(dy1+1)*ry:.1f} "
          f"(w={(dx1+1-dx0)*rx:.1f} h={(dy1+1-dy0)*ry:.1f})")
    kx, ky = CAN[0] / W, CAN[1] / H
    print(f"    实测窗按0.8178缩放落画布 l={x0*kx:.1f} t={y0*ky:.1f} "
          f"w={(x1+1-x0)*kx:.1f} h={(y1+1-y0)*ky:.1f}")
    g = T.region("artwork" if "pendulum" not in rel else "pendulum_art_box")
    print(f"    渲染器 GEO           l={g[0]:.1f} t={g[1]:.1f} w={g[2]:.1f} h={g[3]:.1f}")
    print(f"    ==> 越界：下缘多出 {g[1]+g[3] - (y0*ky + (y1+1-y0)*ky):+.1f}px  "
          f"右缘 {g[0]+g[2] - (x0*kx + (x1+1-x0)*kx):+.1f}px")
    # 越界区里到底是什么？
    ov_t = int(round(g[1] + g[3]))
    yy = min(H - 1, int(ov_t / ky))
    print(f"    插画窗底边落在原图 y={yy}；该行原图像素均值 {a[yy, x0:x1+1].mean(axis=0).round(1)}")
    for probe in range(yy - 12, min(H, yy + 24), 6):
        print(f"      y={probe:5d}  均值 {a[probe, x0:x1+1].mean(axis=0).round(1)}  "
              f"最小 {a[probe, x0:x1+1].min(axis=0)}")
    print()
    return im, (x0, y0, x1, y1)


print("=" * 100)
print("① 标准怪兽框 effect：素材声明 171,375 -> 1222,1427")
print("=" * 100)
im, b = measure("frame/effect.png", (171, 375, 1222, 1427), "effect")

# 出真彩放大图：白窗下缘一带
x0, y0, x1, y1 = b
crop = im.crop((x0 - 60, y1 - 40, x1 + 61, min(im.height, y1 + 200)))
crop = crop.resize((crop.width * 2, crop.height * 2), Image.NEAREST)
crop.save(os.path.join(OUT, "frame_effect_window_bottom.png"))
print(f"已存 {OUT}\\frame_effect_window_bottom.png  size={crop.size}")

print()
print("=" * 100)
print("② 灵摆框 effect-pendulum：素材声明 93,364 -> 1300,1912")
print("=" * 100)
imp, bp = measure("frame/effect-pendulum.png", (93, 364, 1300, 1912), "effect-pendulum")
x0, y0, x1, y1 = bp
crop2 = imp.crop((0, max(0, y1 - 900), imp.width, min(imp.height, y1 + 130)))
crop2 = crop2.resize((crop2.width // 2, crop2.height // 2), Image.LANCZOS)
crop2.save(os.path.join(OUT, "frame_pend_lower.png"))
print(f"已存 {OUT}\\frame_pend_lower.png  size={crop2.size}")

# 全框总览
sheet = Image.new("RGB", (5 * 300, 2 * 437), (40, 40, 40))
for i, f in enumerate(["normal", "effect", "fusion", "synchro", "ritual",
                       "xyz", "link", "spell", "trap", "effect-pendulum"]):
    t = Image.open(T.asset_path(f"frame/{f}.png")).convert("RGB")
    t.thumbnail((300, 437), Image.LANCZOS)
    sheet.paste(t, ((i % 5) * 300, (i // 5) * 437))
sheet.save(os.path.join(OUT, "frames_sheet.png"))
print(f"已存 {OUT}\\frames_sheet.png")
