# -*- coding: utf-8 -*-
"""诊断：用**引擎自己的融合 API** 判断「这张额外卡组卡到底能不能融合召唤」。

为什么不看 IDLE 的 spsummon 列表：实测四类正规召唤在预摆局面下从未出现在
该列表里，**手写官方风格脚本同样如此** —— 那个列表在本驱动下测不出正规召唤
（见 `_probe/extra_four_kinds.py`）。

改用的判据与真卡「融合」魔法完全一致（每张融合魔法都这么写）::

    c:IsCanBeSpecialSummoned(e, SUMMON_TYPE_FUSION, tp, false, false)
    c:CheckFusionMaterial(mg, nil, tp)

探针卡是一张自制魔法（脚本手写），效果 = 满足上述条件时融合召唤目标卡。
可观测结果两条：
1. 探针魔法出现在 IDLE 的 ``activate`` 列表 → 条件成立（引擎认为可融合召唤）；
2. 目标卡从额外卡组移动到怪兽区 → 引擎真的执行了 SUMMON_TYPE_FUSION。

用法::

    PYTHONIOENCODING=utf-8 py -3 _probe/fusion_api_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "_probe"))

from cardforge.content.lua import emit                      # noqa: E402
from cardforge.core.models import (CardSpec, MaterialPart,  # noqa: E402
                                   SummonSpec)
from cardforge.duel import bot, ocgcore as oc               # noqa: E402

MAT, FUS, SPELL = 210000041, 210000061, 210000071
MZONE, EXTRA = oc.LOCATION_MZONE, oc.LOCATION_EXTRA
VANILLA = "local s,id=GetID()\nfunction s.initial_effect(c)\nend\n"

#: 探针魔法：与官方「融合」同一条判定链
PROBE_SPELL = """local s,id=GetID()
function s.initial_effect(c)
	local e1=Effect.CreateEffect(c)
	e1:SetCategory(CATEGORY_SPECIAL_SUMMON)
	e1:SetType(EFFECT_TYPE_ACTIVATE)
	e1:SetCode(EVENT_FREE_CHAIN)
	e1:SetTarget(s.tg)
	e1:SetOperation(s.op)
	c:RegisterEffect(e1)
end
function s.filter(c,e,tp,mg)
	return c:IsCode(%(fus)d)
		and c:IsCanBeSpecialSummoned(e,SUMMON_TYPE_FUSION,tp,false,false)
		and c:CheckFusionMaterial(mg,nil,tp)
end
function s.tg(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then
		local mg=Duel.GetFusionMaterial(tp)
		return Duel.IsExistingMatchingCard(s.filter,tp,LOCATION_EXTRA,0,1,nil,e,tp,mg)
	end
	Duel.SetOperationInfo(0,CATEGORY_SPECIAL_SUMMON,nil,1,tp,LOCATION_EXTRA)
end
function s.op(e,tp,eg,ep,ev,re,r,rp)
	local mg=Duel.GetFusionMaterial(tp)
	local g=Duel.SelectMatchingCard(tp,s.filter,tp,LOCATION_EXTRA,0,1,1,nil,e,tp,mg)
	if #g==0 then return end
	local tc=g:GetFirst()
	local mat=Duel.SelectFusionMaterial(tp,tc,mg,nil,tp)
	if not mat or #mat==0 then return end
	tc:SetMaterial(mat)
	Duel.SendtoGrave(mat,REASON_EFFECT+REASON_MATERIAL+REASON_FUSION)
	Duel.BreakEffect()
	Duel.SpecialSummon(tc,SUMMON_TYPE_FUSION,tp,tp,false,false,POS_FACEUP)
	tc:CompleteProcedure()
end
"""

CAPTURE: list[dict] = []
_orig_idle = bot.SimpleBot._idlecmd


def _spy(self, msg, state):
    out = _orig_idle(self, msg, state)
    CAPTURE.append({"turn": state.get("turns"),
                    "activate": [int(x.get("code") or 0) for x in (msg.get("activate") or [])]})
    return out


bot.SimpleBot._idlecmd = _spy


def material() -> CardSpec:
    return CardSpec(id=MAT, name="测试素材", frame="effect", attribute="光",
                    race="战士族", level=4, atk=1600, dfd=1200,
                    archetype="测试", setcode="0x1000", effects=[], lua=VANILLA)


def fusion(*, with_materials: bool = True) -> CardSpec:
    spec = CardSpec(id=FUS, name="测试融合", frame="fusion", attribute="光",
                    race="战士族", level=8, atk=3000, dfd=2500,
                    archetype="测试", setcode="0x1000",
                    effects=[{"kind": "piercing", "trigger": "CONTINUOUS"}])
    if with_materials:
        spec.summon = SummonSpec(materials=[MaterialPart(
            kind="archetype", value="测试",
            also=[MaterialPart(kind="race", value="战士族")], count=3)])
    return spec


def spell() -> CardSpec:
    spec = CardSpec(id=SPELL, name="探针融合", frame="spell", spell_kind="normal",
                    attribute="光", race="战士族", level=0, atk=0, dfd=0)
    spec.lua = PROBE_SPELL % {"fus": FUS}
    return spec


def run(tag: str, fus: CardSpec, *, field_mats: int = 3) -> str:
    CAPTURE.clear()
    fus.lua = emit.emit_script(fus, tier=1)
    mat = material()
    sp = spell()
    deck_a = [FUS] * 3 + [MAT] * 3 + [SPELL] * 3
    res = bot.run_duel(deck_a, [89631139, 45467446, 73176492, 77098843],
                       seed=7, max_steps=600,
                       cards={FUS: fus, MAT: mat, SPELL: sp},
                       scenario={"hand": [{"code": SPELL, "team": 0}],
                                 "field": [{"code": MAT, "team": 0, "seq": i, "pos": 1}
                                           for i in range(field_mats)],
                                 "action": {}})
    offered = sum(1 for c in CAPTURE if SPELL in c["activate"])
    moves = [e for e in (res.get("log") or [])
             if int(e.get("id") or 0) == 50 and int(e.get("code") or 0) == FUS]
    landed = [e for e in moves if int(e.get("to_location") or 0) & MZONE]
    return (f"{tag:<26} 探针可发动={offered}/{len(CAPTURE)}  "
            f"融合卡移动={len(moves)} 上场={len(landed)}  "
            f"err={len(res.get('errors') or [])}")


def main() -> int:
    out = [
        run("有素材条件的融合卡", fusion()),
        run("素材条件为空（空壳）", fusion(with_materials=False)),
    ]
    text = "\n".join(out) + "\n"
    (ROOT / "_probe" / "fusion_api_probe.txt").write_text(text, encoding="utf-8")
    print(text.encode("utf-8", "ignore").decode("utf-8", "ignore"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
