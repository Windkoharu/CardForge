# -*- coding: utf-8 -*-
"""按用户给的「圣痕龙骑士 露米艾尔」原文构造 CardSpec，投影卡文 + Lua。

用法::

    py -3 _probe/build_lumiel.py            # 打印卡文 / Lua / G1
    py -3 _probe/build_lumiel.py --json     # 输出 spec.json（可直接落进 workspace）
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardforge.core.models import CardSpec, MaterialPart, SummonMethod, SummonSpec  # noqa: E502
from cardforge.content import summon as S  # noqa: E502
from cardforge.content.psct import gen  # noqa: E502
from cardforge.content import design  # noqa: E502

ID = 210000021

EXPECTED = {
    "zh_cn": """包含「圣痕」怪兽的战士族怪兽×3
这张卡不能作为融合素材。
这张卡用融合召唤以及以下方法才能特殊召唤。
●把自己场上的上记的卡除外的场合可以从额外卡组特殊召唤。
①：1回合1次，以对方场上1张表侧表示的卡为对象才能发动。那张卡的效果直到回合结束时无效。这个效果在对方回合也能发动。
②：1回合1次，对方把怪兽的效果发动时，从卡组把1只战士族怪兽送去墓地才能发动。那个发动无效并破坏。
③：这张卡被战斗·效果破坏的场合才能发动。从自己的墓地选1只「圣痕龙骑士 露米艾尔」以外的战士族怪兽特殊召唤。""",
}


def build() -> CardSpec:
    spec = CardSpec(
        id=ID, name="圣痕龙骑士 露米艾尔", frame="fusion",
        attribute="光", race="战士族", level=8, atk=3000, dfd=2500,
        archetype="圣痕", setcode="0x1000",
        effects=[
            {
                "kind": "negate_card", "trigger": "QUICK", "limit": "once_per_turn",
                "params": {"until_end_turn": True},
                "target": {"from_zone": "FIELD", "controller": "opponent",
                           "count": 1, "face_up": True},
            },
            {
                "kind": "negate", "trigger": "OPPONENT_ACTIVATE_MONSTER",
                "limit": "once_per_turn",
                "cost": {"kind": "send_grave", "zone": "DECK", "count": 1,
                         "filter_kind": "race", "filter_value": "战士族"},
            },
            {
                "kind": "ssummon_grave", "trigger": "WHEN_DESTROYED",
                "limit": "no_limit",
                "params": {"destroyed_by": "battle_effect", "timing": "if",
                           "select": True},
                "target": {"from_zone": "GRAVE", "controller": "self",
                           "card_type": "", "count": 1, "exclude_self": True,
                           "filter_kind": "race", "filter_value": "战士族"},
            },
        ],
    )
    spec.summon = SummonSpec(
        materials=[MaterialPart(
            kind="archetype", value="圣痕",
            also=[MaterialPart(kind="race", value="战士族")], count=3)],
        methods=[SummonMethod(action="banish", zone="mz", use_materials=True)],
        limit="must_be",
        cannot_be_material=["fusion"],
    )
    return spec


def main() -> int:
    spec = build()
    spec.validate() if hasattr(spec, "validate") else None
    buf = io.StringIO()
    buf.write("=== 素材行（zh / ja / en）===\n")
    for lang in ("zh_cn", "ja", "en"):
        buf.write(f"[{lang}] {S.material_line(spec, lang)}\n")
    buf.write("\n=== 召唤条件段 ===\n")
    for lang in ("zh_cn", "ja", "en"):
        buf.write(f"[{lang}]\n{S.block(spec, lang)}\n\n")
    buf.write("=== 完整卡文 zh_cn ===\n")
    text = gen.compose(spec, "zh_cn")
    buf.write(text + "\n")
    buf.write("\n=== 与期望逐行比对 ===\n")
    want = EXPECTED["zh_cn"].splitlines()
    got = text.splitlines()
    for i, w in enumerate(want):
        g = got[i] if i < len(got) else "(缺)"
        mark = "OK " if g.strip() == w.strip() else "差异"
        buf.write(f"[{mark}] 期望: {w}\n        实得: {g}\n")
    buf.write("\n=== G1 ===\n")
    report = design.audit_card(spec)
    for issue in getattr(report, "issues", report):
        buf.write(f"  [{getattr(issue, 'level', '?')}] "
                  f"{getattr(issue, 'code', '')}: {getattr(issue, 'message', '')}\n")
    buf.write("\n=== Lua ===\n")
    from cardforge.content.lua import emit as LE
    lua = LE.emit_script(spec)
    buf.write(lua + "\n")
    out = buf.getvalue()
    if "--json" in sys.argv:
        print(json.dumps(spec.to_json_dict(), ensure_ascii=False, indent=2))
        return 0
    Path(ROOT / "_probe" / "lumiel_out.txt").write_text(out, encoding="utf-8")
    print(out.encode("utf-8", "replace").decode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
