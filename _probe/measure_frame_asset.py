# -*- coding: utf-8 -*-
"""量「官方卡框素材」在插画窗边界处的真实剖面（这才是"真卡上卡图附近"的权威依据）。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image  # noqa: E402

FA = Path("D:/游戏王DIY设计/data/assets/frame")
X, Y, W, H = 171, 375, 1051, 1052          # 素材里的插画窗（实测）
D = 22

for name in ("effect.png", "fusion.png", "link.png", "spell.png"):
    p = FA / name
    if not p.exists():
        continue
    im = Image.open(p).convert("RGBA")
    px = im.load()
    cx, cy = X + W // 2, Y + H // 2
    print(f"\n── {name}  插画窗 ({X},{Y}) {W}x{H}")
    print("   上边界（- 窗外 / + 窗内）：")
    for d in range(-D, D):
        c = px[cx, Y + d]
        print(f"     {d:+3d} rgba({c[0]:>3},{c[1]:>3},{c[2]:>3},{c[3]:>3})")
    print("   左边界（- 窗外 / + 窗内）：")
    line = []
    for d in range(-D, D):
        c = px[X + d, cy]
        line.append(f"{d:+d}:({c[0]},{c[1]},{c[2]},a{c[3]})")
    print("     " + "  ".join(line[:12]))
    print("     " + "  ".join(line[12:]))
    # 窗内是不是透明（决定"过渡"该由谁画）
    inner = [px[X + 30, Y + 3], px[X + 3, Y + 30], px[X + W // 2, Y + H // 2]]
    print("   窗内三点 alpha:", [c[3] for c in inner])
