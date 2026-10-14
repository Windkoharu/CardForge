# -*- coding: utf-8 -*-
"""斜切框验收（结构自动判读版）。

官方目标（换算到 1394 画布）：框侧暗部渐变 ≈25–35px、暗线 ≈3px、
钢带 ≈15–16px、亮发丝 ≈3px；顶/左亮、底/右暗。
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cardforge.core.models import CardSpec  # noqa: E402
from cardforge.render import compositor as C, geometry as G, bezel as BZ  # noqa: E402

OUT = ROOT / "_probe" / "bezel"
OUT.mkdir(parents=True, exist_ok=True)
ART = ROOT / "workspace/pics/art/星奏/210000011/v5.png"

spec = CardSpec.from_dict(json.loads(
    (ROOT / "workspace/cards/星奏/210000011/spec.json").read_text(encoding="utf-8")))
spec.render.rarity = "common"          # 先避开闪膜，单看框本体结构
art = Image.open(ART)

res = {}
for tag, strength in (("off", 0.0), ("on", 1.0)):
    spec.render.bezel = strength
    img, rep = C.render_card(spec, art, size="native", return_report=True)
    img.convert("RGB").save(OUT / f"card_{tag}.png")
    res[tag] = img.convert("RGB")
    print(f"bezel={tag:<4} 带宽={rep.bezel}px  warnings={rep.warnings}")


def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def sat(c):
    mx, mn = max(c), min(c)
    return (mx - mn) / (mx + 1)


f = G.make_frame(1394, 2031)
wx, wy, ww, wh = [int(round(v)) for v in f.rect(G.STANDARD_ART_KEY)]
img = res["on"]
px = img.load()
col = [(dy, px[wx + ww // 2, wy + dy]) for dy in range(-70, 41)]

print("\n沿上沿中列的结构判读（dy=0 是窗沿）：")
# 1) 框侧暗部渐变：从远处往里，找到亮度开始持续下降的起点
far = [lum(c) for dy, c in col if -70 <= dy <= -55]
base = sorted(far)[len(far) // 2]
start = next((d for d, L in [(dd, lum(c)) for dd, c in col if -70 <= dd <= -1]
              if L < base - 3), None)
lo = min([(dd, lum(c)) for dd, c in col if -70 <= dd <= -1], key=lambda t: t[1])
print(f"  框侧暗部渐变：dy={start} 起压暗，到 dy={lo[0]} 最低（L {base:.0f} → {lo[1]:.0f}）"
      f"  宽度≈{abs(lo[0]-start)}px  目标 25–35px")
# 2) 钢带：dy>=0 起，低饱和（S<0.20）连续段
band = 0
for dy in range(0, 40):
    c = px[wx + ww // 2, wy + dy]
    if sat(c) < 0.20:
        band += 1
    else:
        break
print(f"  钢色带：dy=0..{band-1} 宽 {band}px  目标 15–16px")
# 3) 发丝：带末端的亮环
hair = 0
for dy in range(band, band + 10):
    c = px[wx + ww // 2, wy + dy]
    if lum(c) > lum(px[wx + ww // 2, wy + band - 1]) - 4 and sat(c) < 0.25:
        hair += 1
    else:
        break
print(f"  亮发丝：带末端续 {hair}px  目标 3px")
print(f"  带中点色 {px[wx + ww // 2, wy + band // 2]}  发丝色 {px[wx + ww // 2, wy + band + 1]}"
      f"  画面色 {px[wx + ww // 2, wy + band + hair + 8]}")

mid = BZ.bezel_metrics(f)["band"] / 2
pts = {"顶": (wx + ww // 2, wy + int(mid)), "底": (wx + ww // 2, wy + wh - int(mid)),
       "左": (wx + int(mid), wy + wh // 2), "右": (wx + ww - int(mid), wy + wh // 2)}
L = {k: lum(px[x, y]) for k, (x, y) in pts.items()}
print("\n四边斜切面亮度：", " ".join(f"{k}={v:.0f}" for k, v in L.items()),
      f"→ 顶-底差 {L['顶']-L['底']:+.0f} · 左-右差 {L['左']-L['右']:+.0f}（都应为正）")

print("\n窗沿逐行（dy=-26..+26）：")
for dd in range(-26, 27):
    c = px[wx + ww // 2, wy + dd]
    mark = "← 窗沿" if dd == 0 else ("← 带内缘" if dd == band else "")
    print(f"  {dd:+3d} rgb({c[0]:>3},{c[1]:>3},{c[2]:>3}) L={lum(c):6.1f} S={sat(c):.2f} {mark}")

# 关掉时的对照：同一列在窗沿处应是硬边
pxo = res["off"].load()
print("\n关掉斜切框时窗沿剖面（应是硬跳变）：",
      " ".join(f"{lum(pxo[wx + ww // 2, wy + dy]):.0f}" for dy in range(-4, 5)))

ref = Image.open(r"C:\Users\Administrator\Desktop\卡图.png").convert("RGB")


def corner(im, x, y, cut=96, z=6):
    return im.crop((int(x - cut / 3), int(y - cut / 3), int(x + cut * 2 / 3),
                    int(y + cut * 2 / 3))).resize((cut * z, cut * z), Image.NEAREST)


a, b, c2 = corner(ref, 14, 20), corner(res["off"], wx, wy), corner(res["on"], wx, wy)
pad = 16
sheet = Image.new("RGB", (a.width * 3 + pad * 4, a.height + pad * 2), (26, 23, 20))
for i, im in enumerate((a, b, c2)):
    sheet.paste(im, (pad * (i + 1) + im.width * i, pad))
sheet.save(OUT / "corner_cmp.png")
print(f"\n对照图（左=官方参考 / 中=关 / 右=开）：{OUT/'corner_cmp.png'}")
