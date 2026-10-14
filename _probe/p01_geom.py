# -*- coding: utf-8 -*-
"""探针 1：把官方卡框素材的真实白窗范围 / 亮边 / 与 GEO 的偏差量出来。"""
import os, sys, json
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image
from forge import template as T

CAN = T.CANVAS


def white_box(path, name):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    W, H = im.size
    # 「插画占位区」= 近乎纯白且大片连通
    m = (a[:, :, 0] > 246) & (a[:, :, 1] > 246) & (a[:, :, 2] > 246)
    print(f"    白像素总数 {m.sum()}  阈值 246 占比 {m.mean():.4f}")
    print(f"    参考素材声明插画窗 x171-1222 y376-1427 均值 = "
          f"{a[380:1420:200, 175:1218:200].reshape(-1,3).mean(axis=0).round(1)}")
    print(f"    该区纯白占比 = {m[380:1420, 175:1218].mean():.4f}")
    cols = m.sum(axis=0)
    rows = m.sum(axis=1)
    # 找出连续且宽度 > 60% 画宽的行带
    thr_c = W * 0.6
    ys = np.where(rows > thr_c)[0]
    thr_r = H * 0.6
    xs = np.where(cols > thr_r)[0]
    if len(ys) == 0 or len(xs) == 0:
        print(f"    !! 未找到大片白窗 (rows>{thr_c:.0f}: {len(ys)}, cols>{thr_r:.0f}: {len(xs)})")
        print(f"       rows 最大 {rows.max()}  cols 最大 {cols.max()}")
        return im, (0, 0, W - 1, H - 1), (CAN[0] / W, CAN[1] / H)
    y0, y1 = (ys.min(), ys.max()) if len(ys) else (None, None)
    x0, x1 = (xs.min(), xs.max()) if len(xs) else (None, None)
    fx = CAN[0] / W
    fy = CAN[1] / H
    refx = T.REF[0] / W
    refy = T.REF[1] / H
    print(f"--- {name}  native={W}x{H}  whitefrac={m.mean():.4f}")
    print(f"    原图像素白窗   x{x0}-{x1} y{y0}-{y1}   (w={x1-x0+1} h={y1-y0+1})")
    print(f"    → 1140 系     x{ x0*fx:.1f}-{(x1+1)*fx:.1f} y{y0*fy:.1f}-{(y1+1)*fy:.1f}")
    print(f"    → 813 系       x{ x0*refx:.1f}-{(x1+1)*refx:.1f} y{y0*refy:.1f}-{(y1+1)*refy:.1f}")
    return im, (x0, y0, x1, y1), (fx, fy)


def report_geo(name, box, fx, fy):
    x0, y0, x1, y1 = box
    got = (x0 * fx, y0 * fy, (x1 + 1 - x0) * fx, (y1 + 1 - y0) * fy)
    want = T.region(name)
    print(f"    渲染器用 GEO['{name}'] = ({want[0]:.1f}, {want[1]:.1f}, {want[2]:.1f}, {want[3]:.1f})")
    print(f"    素材实际白窗           = ({got[0]:.1f}, {got[1]:.1f}, {got[2]:.1f}, {got[3]:.1f})")
    print(f"    偏差 (l,t,w,h)         = ({got[0]-want[0]:+.1f}, {got[1]-want[1]:+.1f}, "
          f"{got[2]-want[2]:+.1f}, {got[3]-want[3]:+.1f})")


def edge_profile(im, box, fx, fy, label):
    """量插画窗四周的外圈亮度：看有没有白边/暗环。"""
    a = np.asarray(im.convert("L")).astype(np.float32)
    x0, y0, x1, y1 = box
    print(f"    [{label}] 窗外侧亮度剖面 (每 4px 一行/列均值)：")
    out = []
    for d in range(0, 49, 4):
        top = a[max(0, y0 - d - 1):y0 - d or None, x0:x1 + 1].mean() if y0 - d - 1 >= 0 else float("nan")
        bot = a[y1 + 1 + d:y1 + 2 + d, x0:x1 + 1].mean()
        lef = a[y0:y1 + 1, max(0, x0 - d - 1):x0 - d or None].mean() if x0 - d - 1 >= 0 else float("nan")
        rig = a[y0:y1 + 1, x1 + 1 + d:x1 + 2 + d].mean()
        out.append(f"d={d:>2} 上{top:6.1f} 下{bot:6.1f} 左{lef:6.1f} 右{rig:6.1f}")
    for i in range(0, len(out), 3):
        print("      " + " | ".join(out[i:i + 3]))


frames = {
    "effect": "frame/effect.png",
    "normal": "frame/normal.png",
    "spell": "frame/spell.png",
    "trap": "frame/trap.png",
    "xyz": "frame/xyz.png",
    "link": "frame/link.png",
    "synchro": "frame/synchro.png",
    "fusion": "frame/fusion.png",
    "ritual": "frame/ritual.png",
    "token": "frame/token.png",
    "effect-pendulum": "frame/effect-pendulum.png",
}

for k, rel in frames.items():
    p = T.asset_path(rel)
    if not p:
        print("MISSING", rel); continue
    im, box, (fx, fy) = white_box(p, k)
    geo = "pendulum_art_box" if "pendulum" in k else "artwork"
    report_geo(geo, box, fx, fy)
    edge_profile(im, box, fx, fy, k)
    print()
