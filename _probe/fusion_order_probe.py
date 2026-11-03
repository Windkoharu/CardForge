# -*- coding: utf-8 -*-
"""诊断：融合召唤不被提供，是不是「EnableReviveLimit 与 Fusion.AddProcMix 的先后」造成的。

官方脚本的写法一律是::

    c:EnableReviveLimit()
    Fusion.AddProcMix(...)

而 CardForge 生成的是反过来的（先 AddProcMix，后 EnableReviveLimit）。
这里把三种写法各跑一局，只看 IDLE(cmd51) 的 ``spsummon`` 列表里有没有被测卡。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "_probe"))

from cardforge.content.lua import emit                      # noqa: E402
from cardforge.core.models import (CardSpec, MaterialPart,  # noqa: E402
                                   SummonSpec)
from cardforge.duel import bot                              # noqa: E402

CAPTURE: list[list[int]] = []
_orig_idle = bot.SimpleBot._idlecmd


def _spy(self, msg, state):
    out = _orig_idle(self, msg, state)
    CAPTURE.append([int(x.get("code") or 0) for x in (msg.get("spsummon") or [])])
    return out


bot.SimpleBot._idlecmd = _spy

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
                    archetype="测试", setcode="0x1000",
                    effects=[{"kind": "pierce", "trigger": "CONTINUOUS"}])
    spec.summon = SummonSpec(materials=[MaterialPart(
        kind="archetype", value="测试",
        also=[MaterialPart(kind="race", value="战士族")], count=3)])
    return spec


def variant(lua: str, mode: str) -> str:
    if mode == "official_order":                 # 先 EnableReviveLimit
        body = lua.replace("\tc:EnableReviveLimit()\n", "")
        body = body.replace("\t--融合素材条件\n",
                            "\tc:EnableReviveLimit()\n\t--融合素材条件\n")
        return body
    if mode == "no_revive_limit":
        return lua.replace("\tc:EnableReviveLimit()\n", "")
    return lua


def run(tag: str, mode: str) -> str:
    CAPTURE.clear()
    spec = fusion()
    spec.lua = variant(emit.emit_script(spec, tier=1), mode)
    mat = material()
    res = bot.run_duel([FUS_ID] * 3 + [MAT_ID] * 3,
                       [89631139, 45467446, 73176492, 77098843],
                       seed=7, max_steps=400, cards={FUS_ID: spec, MAT_ID: mat},
                       scenario={"field": [{"code": MAT_ID, "team": 0, "seq": i,
                                            "pos": 1} for i in range(3)],
                                 "action": {"summon_code": FUS_ID}})
    hits = sum(1 for lst in CAPTURE if FUS_ID in lst)
    moves = [e for e in (res.get("log") or [])
             if int(e.get("id") or 0) == 50 and int(e.get("code") or 0) == FUS_ID]
    head = [ln.strip() for ln in spec.lua.splitlines()
            if "AddProc" in ln or "EnableReviveLimit" in ln]
    return (f"{tag:<22} 可选次数={hits}/{len(CAPTURE)}  "
            f"上场={len(moves)}  errors={len(res.get('errors') or [])}\n"
            f"    {head}\n")


def main() -> int:
    out = [
        run("A 现状(Proc→Revive)", "current"),
        run("B 官方顺序(Revive→Proc)", "official_order"),
        run("C 不写 EnableReviveLimit", "no_revive_limit"),
    ]
    text = "".join(out)
    (ROOT / "_probe" / "fusion_order_probe.txt").write_text(text, encoding="utf-8")
    print(text.encode("utf-8", "ignore").decode("utf-8", "ignore"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
