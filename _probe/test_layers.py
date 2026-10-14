# -*- coding: utf-8 -*-
"""合成层几何验证（不花 GPU）：用一张现成卡图造出「背景层 + 带 alpha 的主体层」，
检查 subject_bleed 档是否做到：背景不出窗、主体压出窗沿、卡名条回贴。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cardforge.core.models import CardSpec  # noqa: E402
from cardforge.render import compositor as C  # noqa: E402

SRC = Path(r"C:/Users/Administrator/Downloads/15105.png")
OUT = ROOT / "_probe" / "layers"
OUT.mkdir(parents=True, exist_ok=True)

art = Image.open(SRC).convert("RGB").resize((1024, 1024), Image.LANCZOS)

# 背景层：整体压暗 + 模糊（模拟"环境"，主体不该出现在里面）
bg = art.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.55))
# 主体层：原图 + 椭圆 alpha（中心留实、边缘羽化透明）
sub = art.convert("RGBA")
m = Image.new("L", sub.size, 0)
d = ImageDraw.Draw(m)
d.ellipse([212, 120, 812, 1024], fill=255)
m = m.filter(ImageFilter.GaussianBlur(28))
sub.putalpha(m)
bg.save(OUT / "synth_bg.png")
sub.save(OUT / "synth_subject.png")

spec = CardSpec.from_dict(json.loads(
    (ROOT / "workspace/cards/星奏/210000011/spec.json").read_text(encoding="utf-8")))

for mode in ("none", "subject_bleed"):
    spec.render.fullart.mode = mode
    spec.render.rarity = "rare"
    img = C.render_card(spec, art if mode == "none" else None, size="share",
                        layers={"background": bg.convert("RGBA"), "subject": sub})
    p = OUT / f"card_{mode}.png"
    img.save(p)
    print(f"  {mode:<14} → {p.name} {img.size}")

# 并排：左=标准整图，右=主体出框
a = Image.open(OUT / "card_none.png")
b = Image.open(OUT / "card_subject_bleed.png")
sheet = Image.new("RGB", (a.width * 2 + 36, a.height + 24), (26, 23, 20))
sheet.paste(a, (12, 12))
sheet.paste(b, (a.width + 24, 12))
sheet.save(OUT / "compare.png")
print(f"\n对照图：{OUT/'compare.png'}（左 标准 / 右 主体出框）")
