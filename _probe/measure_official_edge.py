# -*- coding: utf-8 -*-
"""决定性证据：官方整卡图（MDPro3 OverFrame 704x1024）与我们的卡框素材，
在「插画窗边界」处的真实剖面 —— 看有没有斜切框 / 内暗线 / 过渡。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cardforge.render import geometry as G  # noqa: E402

# REF 系里的插画窗
REF_RECT = G.FRAME_ART_REF if hasattr(G, "FRAME_ART_REF") else (100, 219, 613, 613)
print("REF 系插画窗:", REF_RECT, "  REF 尺寸:", G.REF)


def rect_for(size):
    """把 REF 插画窗换算到任意整卡尺寸。"""
    sx = size[0] / G.REF[0]
    sy = size[1] / G.REF[1]
    x, y, w, h = REF_RECT
    return x * sx, y * sy, w * sx, h * sy


def scan(img, name, depth=26):
    px = img.convert("RGB").load()
    W, H = img.size
    x, y, w, h = rect_for((W, H))
    print(f"\n── {name}  尺寸 {W}x{H}  插画窗 ≈ ({x:.0f},{y:.0f}) {w:.0f}x{h:.0f}")
    cx = int(x + w / 2)
    print("   上边界（y 从窗外 depth 到窗内 depth）：")
    for yy in range(int(y) - depth, int(y) + depth):
        c = px[cx, max(0, min(H - 1, yy))]
        d = yy - int(y)
        print(f"     {d:+3d} rgb({c[0]:>3},{c[1]:>3},{c[2]:>3})")


of = sorted((Path("D:/MyCardLibrary/mdpro3/Picture/OverFrame")).glob("*.png"))
if of:
    scan(Image.open(of[0]), f"MDPro3 官方整卡 OverFrame/{of[0].name}")

# 我们用的卡框素材：插画窗边缘本来长什么样
fa = Path("D:/游戏王DIY设计/data/assets/frame")
cands = [p for p in fa.glob("*.png")][:3]
for p in cands:
    im = Image.open(p)
    print(f"\n   卡框素材 {p.name} {im.size} {im.mode}")

print("\n=== 参考图（用户给的真卡截图）换算到同一尺度 ===")
ref = Image.open(Path(r"C:\Users\Administrator\Desktop\卡图.png"))
print(f"   {ref.size}；若按 624x624 官方 Art 缩到 574 → 缩放 {574/624:.4f}")
print(f"   参考图框厚 20px ÷ {574/624:.4f} ≈ 官方 Art 系里的 {20/(574/624):.1f}px")
print(f"   换算到 REF 系（整卡 813 宽、窗 613 宽）：{20/(574/624)*(613/624):.1f} REF px")
