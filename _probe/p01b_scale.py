# -*- coding: utf-8 -*-
"""探针 1b：精确量官方卡框的白窗 + 计算「素材坐标系 vs GEO 坐标系」的缩放矛盾。"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image
from forge import template as T

CAN = T.CANVAS


def box_of(im, xlo=0, xhi=None, ylo=0, yhi=None, thr=246):
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    H, W = a.shape[:2]
    xhi = xhi or W
    yhi = yhi or H
    sub = a[ylo:yhi, xlo:xhi]
    m = (sub[:, :, 0] > thr) & (sub[:, :, 1] > thr) & (sub[:, :, 2] > thr)
    rows = m.sum(axis=1)
    cols = m.sum(axis=0)
    ry = np.where(rows > 0.5 * m.shape[1])[0]
    rx = np.where(cols > 0.5 * m.shape[0])[0]
    if not len(ry) or not len(rx):
        return None
    return (xlo + rx.min(), ylo + ry.min(), xlo + rx.max(), ylo + ry.max())


print("=" * 100)
print("A. 每个官方卡框素材：真实白窗（原图像素） vs 声明值 171,375 -> 1222,1427")
print("=" * 100)
files = ["normal", "effect", "ritual", "fusion", "synchro", "xyz", "link",
         "spell", "trap", "token",
         "normal-pendulum", "effect-pendulum", "ritual-pendulum",
         "fusion-pendulum", "synchro-pendulum", "xyz-pendulum"]
for f in files:
    rel = f"frame/{f}.png"
    p = T.asset_path(rel)
    if not p:
        print(f"{f:<20} MISSING")
        continue
    im = Image.open(p).convert("RGB")
    W, H = im.size
    pend = "pendulum" in f
    # 灵摆框插画窗很大（93-1300 x 364-1912），标准框在上半部
    if pend:
        b = box_of(im, 0, W, 0, int(H * 0.92))
    else:
        b = box_of(im, 0, W, 0, int(H * 0.68))
    if b is None:
        print(f"{f:<20} native={W}x{H}  NO WHITE BOX")
        continue
    x0, y0, x1, y1 = b
    # 换算到 813 系（= GEO 坐标系）
    rx = T.REF[0] / W
    ry = T.REF[1] / H
    print(f"{f:<20} native={W}x{H}  白窗原图 x{x0}-{x1} y{y0}-{y1}  "
          f"| 813系 x{x0*rx:.1f}-{(x1+1)*rx:.1f} y{y0*ry:.1f}-{(y1+1)*ry:.1f} "
          f"(w={(x1+1-x0)*rx:.1f})")

print()
print("=" * 100)
print("B. 坐标系矛盾")
print("=" * 100)
W, H = T.FRAME_CANVAS
print(f"卡框素材原生            = {W}x{H}   (宽高比 {W/H:.5f})")
print(f"合成画布 CANVAS         = {CAN[0]}x{CAN[1]}  (宽高比 {CAN[0]/CAN[1]:.5f})")
print(f"素材→画布 缩放          = {CAN[0]/W:.6f} x {CAN[1]/H:.6f}   ← render_card 实际用的")
print(f"GEO 的 813→画布 缩放 SX = {T.SX:.6f}  SY = {T.SY:.6f}")
print()
im = Image.open(T.asset_path("frame/effect.png")).convert("RGB")
b = box_of(im, 0, im.width, 0, int(im.height * 0.68))
x0, y0, x1, y1 = b
k = CAN[0] / im.width
print(f"卡框素材白窗 (原图)     = ({x0}, {y0}, {x1+1-x0}, {y1+1-y0})")
print(f"按 render_card 缩放 {k:.4f} 后，白窗落在画布上：")
print(f"    实际   l={x0*k:.1f}  t={y0*k:.1f}  w={(x1+1-x0)*k:.1f}  h={(y1+1-y0)*k:.1f}")
print(f"渲染器贴插画用的 GEO['artwork']：")
w = T.region("artwork")
print(f"    GEO    l={w[0]:.1f}  t={w[1]:.1f}  w={w[2]:.1f}  h={w[3]:.1f}")
print()
print(f"    → 差异：左 {w[0]-x0*k:+.1f}px  上 {w[1]-y0*k:+.1f}px  "
      f"宽 {w[2]-(x1+1-x0)*k:+.1f}px  高 {w[3]-(y1+1-y0)*k:+.1f}px")
print()
print("=" * 100)
print("C. 若把卡框按 GEO 缩放（SX）后，白窗会落在哪里？")
print("=" * 100)
print(f"    白窗 l={x0*T.SX:.1f}  t={y0*T.SY:.1f}  w={(x1+1-x0)*T.SX:.1f}  h={(y1+1-y0)*T.SY:.1f}")
print(f"    GEO['artwork'] = {T.region('artwork')}")
print("    → 两者一致（这就是 template.py 里那句『实测占位区折算到 813 系恰好等于 GEO』的含义）")
print("    但 render_card 并没有按 SX 缩放卡框，而是按 画布/素材原生 缩放 —— 两者相差 "
      f"{T.SX/(CAN[0]/W):.4f} 倍")
