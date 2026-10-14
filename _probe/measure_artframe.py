# -*- coding: utf-8 -*-
"""量参考图：卡图窗口的边框厚度 / 颜色剖面 / 内侧过渡（暗角）。

参考图 = 真实卡牌里卡图附近的样子（574×572 RGBA）。
输出全部按「占卡图窗口宽度的比例」给，方便映射到任意分辨率。
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image, ImageEnhance  # noqa: E402

REF = Path(r"C:\Users\Administrator\Desktop\卡图.png")
PURE = Path(r"C:\Users\Administrator\Downloads\15105.png")

im = Image.open(REF).convert("RGBA")
W, H = im.size
px = im.load()
print(f"参考图 {REF.name}: {W}x{H} mode={im.mode}")
print(f"纯卡图 {PURE.name}: {Image.open(PURE).size}")


def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def profile(axis, fixed, lo=0, hi=None, step=1):
    """沿 axis 方向的一条扫描线，返回 [(位置, r,g,b, a, 亮度)]。"""
    hi = hi if hi is not None else (W if axis == "x" else H)
    out = []
    for t in range(lo, hi, step):
        c = px[t, fixed] if axis == "x" else px[fixed, t]
        out.append((t, c[0], c[1], c[2], c[3], round(lum(c), 1)))
    return out


def edge_band(name, line, forward=True):
    """从图边缘往里找「暗框 → 亮画」的转折点。"""
    ls = line if forward else line[::-1]
    base = [x[5] for x in ls[:6]]
    med = sorted(base)[len(base) // 2]
    for i, s in enumerate(ls):
        if s[5] > med + 40:
            print(f"  {name:<10} 边框厚 ≈ {i:>3}px  (第 {i} 个像素亮度 {med:.0f} → {s[5]:.0f})"
                  f"  框色 rgb{ls[0][1:5]}  转折处 rgb{ls[i][1:5]}")
            return i
    print(f"  {name:<10} 没找到明显转折（前 6px 亮度 {[round(b) for b in base]}）")
    return 0


print("\n[1] 四边的暗框厚度（中线扫描）")
top = edge_band("上", profile("y", W // 2, 0, 80))
bot = edge_band("下", profile("y", W // 2, H - 80, H), forward=False)
lft = edge_band("左", profile("x", H // 2, 0, 80))
rgt = edge_band("右", profile("x", H // 2, W - 80, W), forward=False)

print("\n[2] 上边 0..30px 的逐像素剖面（看是硬边还是有渐变）")
for row in profile("y", W // 2, 0, 30):
    print("   y=%-3d rgb(%3d,%3d,%3d) a=%3d L=%6.1f" % row)

print("\n[3] 内侧暗角：从转折处往里 0..40px 的亮度变化")
inner = profile("y", W // 2, top, top + 40)
print("   " + " ".join(f"{r[5]:.0f}" for r in inner))
mid_lum = sorted(r[5] for r in profile("y", W // 2, H // 2 - 20, H // 2 + 20))
print(f"   画面中心亮度带 {mid_lum[0]:.0f}..{mid_lum[-1]:.0f}")

print("\n[4] 四角 vs 四边中点的框色（看框是否单色 / 有无斜切）")
for name, (x, y) in {"左上角": (3, 3), "右上角": (W - 4, 3), "左下角": (3, H - 4),
                     "右下角": (W - 4, H - 4), "上中": (W // 2, 3), "下中": (W // 2, H - 4),
                     "左中": (3, H // 2), "右中": (W - 4, H // 2)}.items():
    print(f"   {name:<5} rgb{px[x, y][:3]} a={px[x, y][3]}")

print("\n[5] alpha 通道：外圈是不是透明裁过形状")
al = [px[x, y][3] for x, y in [(W // 2, 0), (W // 2, 2), (0, H // 2), (2, H // 2),
                               (W - 1, H // 2), (W - 3, H // 2), (W // 2, H - 1), (W // 2, H - 3)]]
print("   边缘 alpha:", al)

print("\n[6] 画面内容与纯卡图的对应关系（缩放/裁切）")
pure = Image.open(PURE).convert("RGB")
art = im.convert("RGB").crop((lft, top, W - rgt, H - bot))
print(f"   参考图去掉边框后的画面区: {art.size}  宽高比 {art.size[0] / art.size[1]:.4f}")
print(f"   纯卡图宽高比: {pure.size[0] / pure.size[1]:.4f}")
for k in ("L", "C"):
    e = ImageEnhance.Contrast(art) if k == "C" else ImageEnhance.Brightness(art)
    print(f"   {k}: 参考画面均值 {tuple(round(sum(p[i] for p in art.getdata())/len(art.getdata()),1) for i in range(3))}")

# 存一张放大 4 倍的左上角，肉眼看框的结构
corner = im.crop((0, 0, 120, 120)).convert("RGB").resize((480, 480), Image.NEAREST)
out = Path("D:/游戏王DIY设计/_probe/artframe_corner4x.png")
corner.save(out)
print(f"\n放大图已存：{out}")
