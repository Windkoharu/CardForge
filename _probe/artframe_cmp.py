# -*- coding: utf-8 -*-
"""把「参考图（真卡里的卡图窗口）」和「我们现在的渲染」并排放大对比。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cardforge.render import geometry as G  # noqa: E402

OURS = Path("D:/游戏王DIY设计/_probe/artframe_cmp/210000011_native.png")
REF = Path(r"C:\Users\Administrator\Desktop\卡图.png")
OUT = Path("D:/游戏王DIY设计/_probe/artframe_cmp/side_by_side.png")

ours = Image.open(OURS).convert("RGB")
print("我们的成图:", ours.size)
f = G.make_frame(ours.size[0], ours.size[1])
ax, ay, aw, ah = f.rect(G.STANDARD_ART_KEY)
print(f"我们的卡图窗口 rect = ({ax:.1f},{ay:.1f}) {aw:.1f}x{ah:.1f}  "
      f"宽高比 {aw/ah:.4f}")

Z = 5
CUT = 90


def corner(img, x, y):
    box = (int(x - CUT * 0.35), int(y - CUT * 0.35), int(x + CUT * 0.65), int(y + CUT * 0.65))
    return img.crop(box).resize((CUT * Z, CUT * Z), Image.NEAREST)


# 参考图：内框左上角按上一轮量到的 (14, 17) 取
a = corner(Image.open(REF).convert("RGB"), 14, 17)
b = corner(ours, ax, ay)

pad = 14
sheet = Image.new("RGB", (a.width * 2 + pad * 3, a.height + pad * 2), (24, 21, 17))
sheet.paste(a, (pad, pad))
sheet.paste(b, (a.width + pad * 2, pad))
sheet.save(OUT)
print(f"左=参考(真卡)  右=我们现在  各 {CUT}x{CUT} 区域放大 {Z}x  →  {OUT}")

# 顺带把参考图的框带剖面按「亮度」重新量一次（避开饱和度判据的噪声）
im = Image.open(REF).convert("RGB")
px = im.load()
W, H = im.size
for label, y in [("上边 x=287", None)]:
    pass
print("\n参考图：沿中线从上往下 0..40 的 RGB（找框带与画面的真实交界）")
for y in range(0, 40):
    c = px[W // 2, y]
    print(f"  y={y:<3} rgb({c[0]:>3},{c[1]:>3},{c[2]:>3})")
