# -*- coding: utf-8 -*-
"""诊断：四类「正规召唤」在引擎眼里到底成不成立 —— 用真卡（融合魔法 / 同调魔法 /
升阶 / 连接魔法）的同一套 API 来判，不看 IDLE 的可选列表。

为什么不信 IDLE 列表：预摆素材时融合/同步/超量/连接从未出现在
``spsummon`` 里，**手写官方风格脚本同样如此**（`_probe/extra_four_kinds.py`），
那是驱动的观测盲区，不是卡的问题。

判据分两层：
1. **谓词层**（引擎认不认「这张卡可以这样召唤」）：
   ``IsCanBeSpecialSummoned(…,SUMMON_TYPE_*)/CheckFusionMaterial/IsSynchroSummonable/
   IsLinkSummonable`` —— 探针魔法只有谓词成立时才可发动，所以「探针出现在
   IDLE 的 activate 列表」就是谓词成立的证据；
2. **执行层**：探针真的把额外卡组那张卡拉上场（``Duel.SynchroSummon`` /
   ``Duel.SpecialSummon(…,SUMMON_TYPE_*)`` + ``CompleteProcedure``）。

用法::

    PYTHONIOENCODING=utf-8 py -3 _probe/summon_api_probe.py
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

MAT, TUNER, FUS, SYN, XYZ, LNK = (210000041, 210000042, 210000061,
                                  210000062, 210000063, 210000064)
SPELL = 210000071
MZONE = oc.LOCATION_MZONE
VANILLA = "local s,id=GetID()\nfunction s.initial_effect(c)\nend\n"

#: 四类探针：``%(pred)s`` = 谓词，``%(exec)s`` = 执行语句
SPELL_TMPL = """local s,id=GetID()
function s.initial_effect(c)
	local e1=Effect.CreateEffect(c)
	e1:SetCategory(CATEGORY_SPECIAL_SUMMON)
	e1:SetType(EFFECT_TYPE_ACTIVATE)
	e1:SetCode(EVENT_FREE_CHAIN)
	e1:SetTarget(s.tg)
	e1:SetOperation(s.op)
	c:RegisterEffect(e1)
end
function s.filter(c,e,tp)
	return c:IsCode(%(target)d) and %(pred)s
end
function s.tg(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return Duel.IsExistingMatchingCard(s.filter,tp,LOCATION_EXTRA,0,1,nil,e,tp) end
	Duel.SetOperationInfo(0,CATEGORY_SPECIAL_SUMMON,nil,1,tp,LOCATION_EXTRA)
end
function s.op(e,tp,eg,ep,ev,re,r,rp)
	local g=Duel.SelectMatchingCard(tp,s.filter,tp,LOCATION_EXTRA,0,1,1,nil,e,tp)
	if #g==0 then return end
	local tc=g:GetFirst()
	local mg=Duel.GetMatchingGroup(nil,tp,LOCATION_MZONE,0,nil)
	%(exec)s
end
"""

PROBES = {
    "融合": dict(
        target=FUS,
        pred="c:IsCanBeSpecialSummoned(e,SUMMON_TYPE_FUSION,tp,false,false) "
             "and c:CheckFusionMaterial(Duel.GetFusionMaterial(tp),nil,tp)",
        exec="local fmg=Duel.SelectFusionMaterial(tp,tc,Duel.GetFusionMaterial(tp),nil,tp)\n"
             "\tif not fmg or #fmg==0 then return end\n"
             "\ttc:SetMaterial(fmg)\n"
             "\tDuel.SendtoGrave(fmg,REASON_EFFECT+REASON_MATERIAL+REASON_FUSION)\n"
             "\tDuel.BreakEffect()\n"
             "\tDuel.SpecialSummon(tc,SUMMON_TYPE_FUSION,tp,tp,false,false,POS_FACEUP)\n"
             "\ttc:CompleteProcedure()"),
    "同步": dict(
        target=SYN,
        pred="c:IsCanBeSpecialSummoned(e,SUMMON_TYPE_SYNCHRO,tp,false,false) "
             "and c:IsSynchroSummonable(nil)",
        exec="if #mg==0 then return end\n"
             "\ttc:SetMaterial(mg)\n"
             "\tDuel.SynchroSummon(tp,tc,mg)\n"
             "\ttc:CompleteProcedure()"),
    "超量": dict(
        target=XYZ,
        pred="c:IsCanBeSpecialSummoned(e,SUMMON_TYPE_XYZ,tp,false,false)",
        exec="if #mg<2 then return end\n"
             "\ttc:SetMaterial(mg)\n"
             "\tDuel.SpecialSummon(tc,SUMMON_TYPE_XYZ,tp,tp,false,false,POS_FACEUP)\n"
             "\ttc:CompleteProcedure()"),
    "连接": dict(
        target=LNK,
        pred="c:IsCanBeSpecialSummoned(e,SUMMON_TYPE_LINK,tp,false,false) "
             "and c:IsLinkSummonable(nil)",
        exec="if #mg<2 then return end\n"
             "\ttc:SetMaterial(mg)\n"
             "\tDuel.LinkSummon(tp,tc,mg)\n"
             "\ttc:CompleteProcedure()"),
}

CAPTURE: list[dict] = []
_orig_idle = bot.SimpleBot._idlecmd


def _spy(self, msg, state):
    out = _orig_idle(self, msg, state)
    CAPTURE.append({"activate": [int(x.get("code") or 0) for x in (msg.get("activate") or [])]})
    return out


bot.SimpleBot._idlecmd = _spy


def mat(code: int, tags=None) -> CardSpec:
    return CardSpec(id=code, name=f"素材{code}", frame="effect", attribute="光",
                    race="战士族", level=4, atk=1600, dfd=1200,
                    archetype="测试", setcode="0x1000", tags=tags or [],
                    effects=[], lua=VANILLA)


def extra(code: int, frame: str, level: int, parts: list, **kw) -> CardSpec:
    base = dict(attribute="光", race="战士族", level=level, atk=3000, dfd=2500,
                archetype="测试", setcode="0x1000",
                effects=[{"kind": "piercing", "trigger": "CONTINUOUS"}])
    base.update(kw)
    spec = CardSpec(id=code, name=f"额外{code}", frame=frame, **base)
    spec.summon = SummonSpec(materials=parts)
    return spec


def spell(code: int, body: str) -> CardSpec:
    spec = CardSpec(id=code, name="探针", frame="spell", spell_kind="normal",
                    attribute="光", race="战士族", level=0, atk=0, dfd=0)
    spec.lua = body
    return spec


def run(tag: str, target: CardSpec, mats: list, probe: dict) -> str:
    CAPTURE.clear()
    target.lua = emit.emit_script(target, tier=1)
    sp = spell(SPELL, SPELL_TMPL % probe)
    cards = {target.id: target, SPELL: sp}
    for m in mats:
        cards[m.id] = m
    deck_a = [target.id] * 3 + [m.id for m in mats] + [SPELL] * 3
    res = bot.run_duel(deck_a, [89631139, 45467446, 73176492, 77098843],
                       seed=7, max_steps=700, cards=cards,
                       scenario={"hand": [{"code": SPELL, "team": 0,
                                           "loc": oc.LOCATION_HAND, "pos": oc.POS_FACEUP_ATTACK}],
                                 "field": [{"code": m.id, "team": 0, "seq": i, "pos": 1}
                                           for i, m in enumerate(mats)],
                                 "action": {}})
    offered = sum(1 for c in CAPTURE if SPELL in c["activate"])
    moves = [e for e in (res.get("log") or [])
             if int(e.get("id") or 0) == 50 and int(e.get("code") or 0) == target.id]
    landed = [e for e in moves if int(e.get("to_location") or 0) & MZONE]
    return (f"{tag:<10} 谓词成立={offered}/{len(CAPTURE)}  额外卡移动={len(moves)}  "
            f"上场={len(landed)}  报错={len(res.get('errors') or [])}"
            + (f"  {str(res.get('errors')[0])[:60]}" if res.get("errors") else ""))


def main() -> int:
    m, t = mat(MAT), mat(TUNER, ["tuner"])
    out = [
        run("融合", extra(FUS, "fusion", 8, [MaterialPart(
            kind="archetype", value="测试",
            also=[MaterialPart(kind="race", value="战士族")], count=3)]),
            [m, mat(210000043), mat(210000044)], PROBES["融合"]),
        run("同步", extra(SYN, "synchro", 8, [
            MaterialPart(kind="any", value="", tuner="tuner", count=1),
            MaterialPart(kind="any", value="", tuner="non_tuner", count=2)]),
            [t, mat(210000043), mat(210000044)], PROBES["同步"]),
        run("超量", extra(XYZ, "xyz", 4, [
            MaterialPart(kind="level", value=4, count=2)]),
            [m, mat(210000043)], PROBES["超量"]),
        run("连接", extra(LNK, "link", 2, [MaterialPart(kind="any", value="", count=2)],
                          link_markers=["左下", "下"], dfd=0),
            [m, mat(210000043)], PROBES["连接"]),
    ]
    text = "\n".join(out) + "\n"
    (ROOT / "_probe" / "summon_api_probe.txt").write_text(text, encoding="utf-8")
    print(text.encode("utf-8", "ignore").decode("utf-8", "ignore"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
