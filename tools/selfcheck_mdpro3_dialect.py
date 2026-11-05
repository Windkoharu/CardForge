# -*- coding: utf-8 -*-
"""MDPro3 旧方言投影的回归自检（缺陷 #48）。

跑法：``python -X utf8 tools/selfcheck_mdpro3_dialect.py``（0 = 全绿）。

三层：
1. **合成夹具**：对每种「新方言行」写死输入 → 断言译文的精确形态，
   包括翻译不了的行必须被注释降级（绝不留下会中止 initial_effect 的死调用）；
2. **负面用例**：原样 EDOPro 脚本必须被 ``lint`` 判 ERROR —— 这正是
   SA人类 的包当年通过旧自检的盲区；
3. **工作区黄金**：本机每张有脚本的卡过一遍 translate+lint，断言无 ERROR，
   并对额外卡组五件套断言译出了对应旧方言流程调用。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cardforge.content.lua import mdpro3dialect as MD  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'√' if cond else '✗'} {name}" + ("" if cond else f" —— {detail}"))
    if not cond:
        FAILS.append(name)


def tr(line: str) -> tuple[str, list]:
    out, notes = MD.translate(line)
    return out, notes


# ══════════════════════════════════════════════════════════════════════
print("── 1. 合成夹具：逐行翻译 ──")
cases = [
    # (输入行, 期望译文, 期望至少一条 note?)
    ("\tFusion.AddProcMix(c,true,true,s.mat0_0,1357)",
     "\taux.AddFusionProcMix(c,false,true,s.mat0_0,1357)", False),
    ("\tFusion.AddProcMixRep(c,true,true,s.f,2,4,s.a,s.b)",
     "\taux.AddFusionProcMixRep(c,false,true,s.f,2,4,s.a,s.b)", False),
    ("\tSynchro.AddProcedure(c,s.f1,1,1,Synchro.NonTuner(s.f2),1,3)",
     "\taux.AddSynchroProcedure(c,s.f1,aux.NonTuner(s.f2),1,3)", False),
    ("\tSynchro.AddProcedure(c,s.f1,2,2,Synchro.NonTuner(s.f2),1,3)",
     "\taux.AddSynchroMixProcedure(c,aux.Tuner(s.f1),aux.Tuner(s.f1),nil,"
     "aux.NonTuner(s.f2),1,3)", False),
    ("\tSynchro.AddProcedure(c,s.f1,3,3,Synchro.NonTuner(s.f2),0,2)",
     "\taux.AddSynchroMixProcedure(c,aux.Tuner(s.f1),aux.Tuner(s.f1),aux.Tuner(s.f1),"
     "aux.NonTuner(s.f2),0,2)", False),
    ("\tRitual.AddProcGreater(c,aux.TRUE,4)",
     "\taux.AddRitualProcGreater2(c,aux.TRUE)", True),
    ("\tRitual.AddProcEqual(c,s.rf,4)",
     "\taux.AddRitualProcEqual2(c,s.rf)", True),
    ("\tXyz.AddProcedure(c,s.f,8,2,nil,nil,Xyz.InfiniteMats)",
     "\taux.AddXyzProcedure(c,s.f,8,2,nil,nil,99)", False),
    ("\tLink.AddProcedure(c,s.f,2,3,s.lchk1)",
     "\taux.AddLinkProcedure(c,s.f,2,3,s.lchk1)", False),
    ("\tPendulum.AddProcedure(c)",
     "\taux.EnablePendulumAttribute(c)", False),
    ("\taux.AddEquipProcedure(c,0,s.eqfil1)",
     "\taux.AddEquipSpellEffect(c,true,true,s.eqfil1)  "
     "-- [CardForge#48] 装备限制数按旧接口默认 1", False),
    ("\te1:SetCountLimit(1,{id,3},EFFECT_COUNT_CODE_OATH)",
     "\te1:SetCountLimit(1,id+3)", True),
    ("\te1:SetValue(aux.lnklimit)", "\te1:SetValue(aux.linklimit)", False),
    ("\treturn ep~=tp and re:IsMonsterEffect()",
     "\treturn ep~=tp and re:IsHasType(TYPE_MONSTER)", False),
]
for src, want, want_note in cases:
    out, notes = tr(src)
    check(f"翻译 {src.strip()[:52]!r}", out == want and bool(notes) == want_note,
          f"得 {out!r} notes={len(notes)}")

# 多行效果块
out, _ = tr("\tCard.AddCannotBeNormalSummoned(c)")
check("AddCannotBeNormalSummoned → CANNOT_SUMMON+CANNOT_MSET 块",
      "EFFECT_CANNOT_SUMMON" in out and "EFFECT_CANNOT_MSET" in out
      and out.count("c:RegisterEffect") == 2)
out, _ = tr("\tCard.AddMustFirstBeLinkSummoned(c)")
check("AddMustFirstBeLinkSummoned → SPSUMMON_CONDITION+aux.linklimit",
      "EFFECT_SPSUMMON_CONDITION" in out and "aux.linklimit" in out)
out, _ = tr("\tCard.AddSetcodesRule(c,0,0x1057)")
check("AddSetcodesRule → EFFECT_ADD_SETCODE 块",
      "EFFECT_ADD_SETCODE" in out and "SetValue(0x1057)" in out)

# 接触融合：组函数体 → 卡片级过滤 + 区域对
SRC = ("function s.initial_effect(c)\n"
       "\tFusion.AddContactProc(c,s.cgrp0_0,s.ctop0_0,nil,nil,SUMMON_TYPE_FUSION)\n"
       "end\n"
       "function s.cgrp0_0(tp)\n"
       "\treturn Duel.GetMatchingGroup(s.cfil0_0,tp,LOCATION_MZONE,LOCATION_SZONE,nil)\n"
       "end\n")
out, notes = MD.translate(SRC)
check("接触融合还原为 aux.AddContactFusionProcedure(c,过滤,区1,区2,操作)",
      "aux.AddContactFusionProcedure(c,s.cfil0_0,LOCATION_MZONE,LOCATION_SZONE,"
      "s.ctop0_0)" in out and not any(n.level == "ERROR" for n in notes),
      out)

# 降级：必须注释掉 + 硬 ERROR note
for src, why in [
    ("\tFusion.AddProcMixRepUnfix(c,true,true,{s.f,2,4})", "多段可变数量"),
    ("\tSynchro.AddProcedure(c,s.f1,1,2,Synchro.NonTuner(s.f2),1,3)", "协调数量浮动"),
    ("\tRitual.AddProc(c,s.f,4)", "旧接口名单里没有"),
]:
    out, notes = tr(src)
    check(f"降级 {src.strip()[:44]!r}",
          out.lstrip().startswith("-- [CardForge#48]")
          and any(n.level == "ERROR" for n in notes))

# ══════════════════════════════════════════════════════════════════════
print("── 2. 负面用例：原样 EDOPro 必须被 lint 判 ERROR ──")
RAW = """local s,id=GetID()
function s.initial_effect(c)
\tFusion.AddProcMix(c,true,true,s.mat0_0)
\tc:EnableReviveLimit()
\tlocal e1=Effect.CreateEffect(c)
\te1:SetCountLimit(1,{id,1},EFFECT_COUNT_CODE_OATH)
\taux.AddEquipProcedure(c,0,s.eqfil1)
\tc:RegisterEffect(e1)
end
function s.mat0_0(c)
\treturn c:IsCode(1357)
end
"""
errs = [n for n in MD.lint(RAW) if n.level == "ERROR"]
check("EDOPro 原文 lint 报 ERROR（当年自检的盲区）",
      any("Fusion.AddProcMix" in n.msg for n in errs)
      and any("{id," in n.msg for n in errs)
      and any("aux.AddEquipProcedure" in n.msg for n in errs),
      "\n".join(n.msg for n in errs))
GOOD = """local s,id=GetID()
function s.initial_effect(c)
\taux.AddFusionProcMix(c,false,true,s.mat0_0)
\tc:EnableReviveLimit()
\tlocal e1=Effect.CreateEffect(c)
\te1:SetCountLimit(1,id+1)
\tc:RegisterEffect(e1)
end
function s.mat0_0(c)
\treturn c:IsCode(1357)
end
"""
check("旧方言干净脚本 lint 零问题", not MD.lint(GOOD),
      "\n".join(f"{n.level}:{n.msg}" for n in MD.lint(GOOD)))
out2, _ = MD.translate(GOOD)
check("翻译幂等（再翻一次不变）", out2 == GOOD)

# ══════════════════════════════════════════════════════════════════════
print("── 3. 工作区黄金：每张有脚本的卡 ──")
import json  # noqa: E402
from cardforge.core.models import CardSpec  # noqa: E402

WS = ROOT / "workspace" / "cards"
GOLDEN = {
    "210000000": "aux.AddFusionProcMix(",
    "210000021": "aux.AddFusionProcMix(",
    "210100110": "aux.AddContactFusionProcedure(",
    "210100111": "aux.AddSynchroProcedure(",
    "210100112": "aux.AddXyzProcedure(",
    "210100113": "aux.AddLinkProcedure(",
}
BANNED = ("Fusion.", "Synchro.AddProcedure", "Xyz.", "Link.AddProcedure",
          "Ritual.AddProc", "Pendulum.AddProcedure", "aux.AddEquipProcedure",
          "IsMonsterEffect", "aux.lnklimit")
n_cards = 0
if WS.is_dir():
    for p in sorted(WS.rglob("spec.json")):
        spec = CardSpec.from_dict(json.loads(p.read_text(encoding="utf-8-sig")))
        lua = str(getattr(spec, "lua", "") or "")
        if not lua.strip():
            continue
        n_cards += 1
        out, notes = MD.translate(lua)
        errs = [n for n in notes + MD.lint(out) if n.level == "ERROR"]
        check(f"卡 {spec.id}「{spec.name}」译文无 ERROR", not errs,
              "\n".join(f"  {n.msg}" for n in errs))
        code_only = "\n".join(
            ln for ln in out.splitlines() if not ln.lstrip().startswith("--"))
        if str(spec.id) in GOLDEN:
            check(f"卡 {spec.id} 译出 {GOLDEN[str(spec.id)]}",
                  GOLDEN[str(spec.id)] in code_only)
        if "{id," in lua:
            check(f"卡 {spec.id} SetCountLimit 表标签已展开",
                  "{id," not in code_only and "id+" in code_only)
        # 注释里出现新方言词是允许的（降级说明），可执行行里绝不许留
        hit = [b for b in BANNED if b in code_only]
        check(f"卡 {spec.id} 可执行行无新方言残留", not hit, str(hit))
else:
    print(f"  （跳过：没有 {WS}）")
print(f"  共 {n_cards} 张")

# ══════════════════════════════════════════════════════════════════════
print()
if FAILS:
    print(f"红 {len(FAILS)} 条：")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("全部通过：MDPro3 方言投影行为符合预期。")
