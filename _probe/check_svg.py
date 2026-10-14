# -*- coding: utf-8 -*-
"""矢量预览（render_svg）全卡种回归：验证 compositor 的 L.palette 崩溃修复。"""
import copy
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardforge.core.models import CardSpec          # noqa: E402
from cardforge.render import compositor as C        # noqa: E402

base = CardSpec.from_dict(json.loads(
    (ROOT / "workspace/cards/星奏/210000011/spec.json").read_text(encoding="utf-8")))

FRAMES = ["normal", "effect", "ritual", "fusion", "synchro", "xyz", "link",
          "pendulum", "normal_pendulum", "ritual_pendulum", "fusion_pendulum",
          "synchro_pendulum", "xyz_pendulum", "spell", "trap", "token", "skill"]

bad = []
for fr in FRAMES:
    sp = copy.deepcopy(base)
    sp.frame = fr
    sp.name = f"矢量测试 {fr}"
    if fr == "link":
        sp.link_markers = ["左下", "下", "右下"]
    if fr == "spell":
        sp.spell_kind = "quick"
    if fr == "trap":
        sp.trap_kind = "counter"
    try:
        svg = C.render_svg(sp, width=813)
        ok = svg.startswith("<svg") and svg.rstrip().endswith("</svg>") and "<text" in svg
        print(f"  {'OK ' if ok else 'BAD'} {fr:<18} {len(svg):>7}B")
        if not ok:
            bad.append(fr)
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL {fr:<18} {type(e).__name__}: {e}")
        bad.append(fr)

# 罕贵 × 矢量：确认卡名白字规则对 xyz/link/spell/trap 生效
for fr in ["xyz", "link", "spell", "trap", "effect"]:
    sp = copy.deepcopy(base)
    sp.frame = fr
    svg = C.render_svg(sp, width=400)
    head = svg[svg.find("<text"):svg.find("<text") + 260]
    print(f"  卡名色 {fr:<8} {'白' if '#FFFFFF' in head else '黑'}")

print(f"\n矢量预览：{len(FRAMES)} 卡种 · 失败 {len(bad)}" + (f" → {bad}" if bad else ""))
sys.exit(1 if bad else 0)
