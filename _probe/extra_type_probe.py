# -*- coding: utf-8 -*-
"""诊断：额外卡组里的 DIY 卡，**引擎实际看到的 type** 是什么。

路径：手动驱动 OcgCore（不走 bot.run_duel），开局后直接 query
``LOCATION_EXTRA`` 的第 0 个槽位，把 ``type`` 打出来 ——
融合召唤是否被引擎提供，第一道门就是 ``data.type & TYPE_FUSION``。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "_probe"))

from cardforge.content.lua import emit                      # noqa: E402
from cardforge.core import paths                            # noqa: E402
from cardforge.core.models import (CardSpec, MaterialPart,  # noqa: E402
                                   SummonSpec)
from cardforge.duel import bot, ocgcore as oc               # noqa: E402
from cardforge.pool import cdb as pool_cdb                  # noqa: E402

MAT_ID = 210000041
FUS_ID = 210000061
VANILLA = "local s,id=GetID()\nfunction s.initial_effect(c)\nend\n"


def material() -> CardSpec:
    return CardSpec(id=MAT_ID, name="测试素材", frame="effect",
                    attribute="光", race="战士族", level=4, atk=1600, dfd=1200,
                    archetype="测试", setcode="0x1000", effects=[], lua=VANILLA)


def fusion() -> CardSpec:
    spec = CardSpec(id=FUS_ID, name="测试融合", frame="fusion",
                    attribute="光", race="战士族", level=8, atk=3000, dfd=2500,
                    archetype="测试", setcode="0x1000", effects=[])
    spec.summon = SummonSpec(materials=[MaterialPart(
        kind="archetype", value="测试",
        also=[MaterialPart(kind="race", value="战士族")], count=3)])
    return spec


def main() -> int:
    core = oc.OcgCore()
    cdb = paths.OFFICIAL_CDB / "cards_zh.cdb"
    if not cdb.exists():
        cdb = paths.OFFICIAL_CDB / "cards.cdb"
    core.register_cdb(cdb)
    print("cdb:", cdb, cdb.exists())

    specs = {FUS_ID: fusion(), MAT_ID: material()}
    for code, spec in specs.items():
        spec.lua = emit.emit_script(spec, tier=1)
        data = bot._spec_card_data(spec)
        core.register_card_data(code, data)
        core.register_card_script(code, spec.lua)
        row = pool_cdb.spec_to_rows(spec)[0]
        print(f"{code} 写盘 type=0x{int(row[4]):x} engine type=0x{int(data.get('type') or 0):x}")

    core.player_info = {"lp": 8000, "hand": 5, "draw": 1, "hand_limit": 6}
    assert core.create_duel(7) == 0
    print("runtime_missing:", core.runtime_missing)
    core.inject_deck([MAT_ID] * 3 + [89631139] * 37, [89631139] * 40,
                     [FUS_ID] * 3, [13529466] * 3)
    for i in range(3):
        core.place_field(0, oc.LOCATION_MZONE, i, MAT_ID)
    core.start_duel()
    core.process()
    core.messages()

    print("extra count team0:", core.query_count(0, oc.LOCATION_EXTRA))
    for seq in range(3):
        q = core.query_card(0, oc.LOCATION_EXTRA, seq)
        print(f"  extra[{seq}] code={q.get('code')} type=0x{int(q.get('type') or 0):x}"
              f" pos/pos={q.get('position')}")
    for seq in range(3):
        q = core.query_card(0, oc.LOCATION_MZONE, seq)
        print(f"  mzone[{seq}] code={q.get('code')} type=0x{int(q.get('type') or 0):x}")
    print("script_errors:", core.script_errors[:5])
    core.end_duel()
    return 0


if __name__ == "__main__":
    sys.exit(main())
