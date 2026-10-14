# -*- coding: utf-8 -*-
"""端到端集成探针：用兄弟模块 compositor.py + layers.py 真渲一张卡，检查 text.py 接得上。

跑法::

    python _probe\\p_text_integration.py

产出 ``_probe/text/it_card_*.png``。**只读**其它模块，不改任何既有文件。
"""
from __future__ import annotations

import io
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OUT_DIR = ROOT / "_probe" / "text"
OUT_DIR.mkdir(parents=True, exist_ok=True)
buf = io.StringIO()


def out(*a) -> None:
    print(*a)
    print(*a, file=buf)


FAILS: list[str] = []


def check(cond: bool, msg: str) -> bool:
    out(("  [PASS] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)
    return cond


out("=" * 96)
out("text.py × compositor.py 端到端集成")
out("=" * 96)

from cardforge.core.models import CardSpec, RenderOptions  # noqa: E402

CASES = [
    ("effect", {"name": "青眼の白龍－测试型", "text": "", "level": 8,
                "race": "龙族", "attribute": "光", "atk": 3000, "dfd": 2500}, "it_card_effect"),
    ("effect", {"name": "长文测试龙", "level": 4, "race": "龙族", "attribute": "暗",
                "atk": 1800, "dfd": 1200}, "it_card_longtext"),
    ("spell", {"name": "融合", "spell_kind": "normal", "frame": "spell"}, "it_card_spell"),
    ("pendulum", {"name": "灵摆测试", "level": 4, "race": "魔法师族", "attribute": "光",
                  "atk": 1500, "dfd": 1000, "pendulum_scale": 3}, "it_card_pendulum"),
]

LONG = (
    "①：1回合1次，以自己场上1只「青眼」怪兽为对象才能发动。那只怪兽的攻击力"
    "直到回合结束时上升1000，这个效果在对方回合也能发动。"
    "②：这张卡被送去墓地的场合才能发动。从卡组把1只光属性·龙族怪兽加入手卡，"
    "那之后自己从卡组抽1张。这个效果发动后，直到回合结束时自己不能把怪兽特殊召唤。"
    "③：这张卡在墓地存在的场合，把这张卡除外才能发动。从自己墓地把1张「融合」"
    "加入手卡，那之后把1只融合怪兽融合召唤。这个效果在这张卡送去墓地的回合不能发动。"
)
NORMAL = (
    "「青眼の白龍」を対象として発動できる。そのモンスターの攻撃力は"
    "ターン終了時まで1000アップする。②：このカードが墓地へ送られた場合に"
    "発動できる。デッキから「青眼の白龍」1体を手札に加える。"
)

try:
    from cardforge.render import compositor as CO
except Exception:
    out("  compositor 不可用：\n" + traceback.format_exc())
    sys.exit(2)

out(f"  capabilities = { {k: v for k, v in CO.capabilities().items() if k in ('pillow', 'text_engine', 'fonts', 'official_frames')} }")

for frame_key, fields, tag in CASES:
    spec = CardSpec(id=1, frame=frame_key)
    for k, v in fields.items():
        setattr(spec, k, v)
    spec.text_i18n = {"zh_cn": LONG if tag == "it_card_longtext" else NORMAL}
    spec.render = RenderOptions(lang_text="zh_cn", output_size="share",
                                psct_bold=True, rarity="common")
    try:
        res = CO.render_card(spec, size="share")
        img = res.image if hasattr(res, "image") else res
        path = OUT_DIR / f"{tag}.png"
        img.save(path)
        rep = getattr(res, "report", None)
        info = ""
        if rep is not None:
            info = (f" lines={getattr(rep, 'text_lines', '?')}"
                    f" size={getattr(rep, 'text_size', '?')}"
                    f" overflow={getattr(rep, 'text_overflow', '?')}"
                    f" warnings={getattr(rep, 'warnings', [])[:2]}")
        out(f"  [OK]   {tag}: {img.size}{info} -> {path.name}")
        check(img.size[0] > 100, f"{tag} 渲染出图")
    except Exception:
        out(f"  [ERR]  {tag} 渲染失败：\n{traceback.format_exc()}")
        check(False, f"{tag} 渲染失败")

out("")
out(f"失败 {len(FAILS)} 条")
REPORT = ROOT / "_probe" / "_text_integration.txt"
REPORT.write_text(buf.getvalue(), encoding="utf-8")
print("报告写入", REPORT)
sys.exit(1 if FAILS else 0)
