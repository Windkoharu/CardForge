"""ocgcore Lua API 白名单 —— G2「API 存在性」检查的依据。

数据来源
--------
``data/lua_api.json``，由 ``tools/extract_lua_api.py`` 从官方脚本库
（``ProjectIgnis/CardScripts`` 的 ``constant.lua`` / ``utility.lua`` 等核心文件
+ 400 张真实卡脚本）**实测抽取**。这是目前最可靠的存在性依据 ——
ocgcore 的 Lua API 没有公开发布的权威文档（调研结论）。

设计要点
--------
* 文件缺失时用一份**内置快照**兜底（保证离线可用、也保证测试可复现）。
* ``is_known()`` 只回答"这个名字在官方脚本里出现过吗"，**不保证语义正确**。
  因此 lint 把它当作 ``WARN`` 而不是 ``ERROR``（存在即合理，不存在才可疑）。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Optional

from ...core.paths import DATA

API_JSON = DATA / "lua_api.json"

#: 内置兜底快照（只收最常用的，保证没有 data 文件时也能工作）
_BUILTIN_FUNCS = frozenset({
    "Duel.Hint", "Duel.HintSelection", "Duel.SelectMatchingCard", "Duel.SelectTarget",
    "Duel.IsExistingMatchingCard", "Duel.IsExistingTarget", "Duel.GetLocationCount",
    "Duel.GetMatchingGroup", "Duel.GetFieldGroup", "Duel.SendtoHand", "Duel.SendtoGrave",
    "Duel.Remove", "Duel.Destroy", "Duel.SpecialSummon", "Duel.SpecialSummonStep",
    "Duel.SpecialSummonComplete", "Duel.ConfirmCards", "Duel.ShuffleHand", "Duel.Draw",
    "Duel.SetOperationInfo", "Duel.GetOperatedGroup", "Duel.SelectOption",
    "Duel.SelectYesNo", "Duel.SelectEffectYesNo", "Duel.AnnounceCard", "Duel.AnnounceNumber",
    "Duel.AnnounceAttribute", "Duel.AnnounceRace", "Duel.AnnounceType", "Duel.AnnounceLevel",
    "Duel.CheckLPCost", "Duel.PayLPCost", "Duel.SetLP", "Duel.Damage", "Duel.Recover",
    "Duel.GetLP", "Duel.GetTurnPlayer", "Duel.GetCurrentPhase", "Duel.GetChainInfo",
    "Duel.NegateEffect", "Duel.NegateActivation", "Duel.NegateSummon", "Duel.NegateAttack",
    "Duel.ChangePosition", "Duel.ChangeAttackTarget", "Duel.Equip", "Duel.GetControl",
    "Duel.GetMZoneCount", "Duel.GetSZoneCount", "Duel.CheckReleaseGroup",
    "Duel.Release", "Duel.DiscardHand", "Duel.SendtoDeck", "Duel.MoveToField",
    "Duel.CreateToken", "Duel.RegisterEffect", "Duel.RaiseEvent", "Duel.RaiseSingleEvent",
    "Duel.ShuffleDeck", "Duel.SortDecktop", "Duel.MoveSequence", "Duel.GetFirstMatchingCard",
    "Duel.IsPlayerCanSpecialSummonCount", "Duel.IsPlayerCanSpecialSummon",
    "Duel.IsPlayerCanDraw", "Duel.IsPlayerCanDiscardDeck", "Duel.IsPlayerAffectedByEffect",
    "Duel.IsExistingMatchingCard", "Duel.GetFlagEffect", "Duel.RegisterFlagEffect",
    "Duel.ResetFlagEffect", "Duel.GetChainMaterial", "Duel.SetChainLimit",
    "Duel.SetChainLimitTillChainEnd", "Duel.BreakEffect", "Duel.AdjustInstantly",
    "Duel.GetOverlayGroup", "Duel.CheckXyzMaterial", "Duel.Overlay",
    "Duel.IsSummonCancelable", "Duel.SetSummonCancelable", "Duel.CheckEvent",
    "Effect.CreateEffect", "Effect.CreateEffect", "aux.Stringid", "aux.TRUE", "aux.FALSE",
    "aux.Next", "aux.TargetBoolFunction", "aux.FilterBoolFunction", "aux.FilterEqualFunction",
    "aux.MonsterVariant", "aux.MonsterFilter", "aux.SpElimFilter", "aux.NecroValleyFilter",
    "aux.StatChangeDamageStep", "aux.Damage", "aux.Pierce", "aux.SelectEffect",
    "aux.SelectUnselectGroup", "aux.SelectUnselectTarget", "aux.SelectUnselectCards",
    "aux.SelectUnselectAttach", "aux.AddSynchroProcedure", "aux.AddXyzProcedure",
    "aux.AddLinkProcedure", "aux.AddFusionProcFunRep", "aux.AddRitualProcGreater",
    "aux.AddPendulumProcedure", "aux.EnablePendulumAttribute", "aux.EnableUnionAttribute",
    "aux.EnableGeminiAttribute", "aux.EnableDualAttribute", "aux.AddEquipProcedure",
    "aux.GivePriorityTo", "aux.delay_hint", "aux.RegisterClientHint",
})

_BUILTIN_CONSTS = frozenset({
    "EFFECT_TYPE_SINGLE", "EFFECT_TYPE_FIELD", "EFFECT_TYPE_ACTIVATE",
    "EFFECT_TYPE_IGNITION", "EFFECT_TYPE_TRIGGER_O", "EFFECT_TYPE_TRIGGER_F",
    "EFFECT_TYPE_QUICK_O", "EFFECT_TYPE_QUICK_F", "EFFECT_TYPE_CONTINUOUS",
    "EFFECT_TYPE_EQUIP", "EFFECT_TYPE_ABILITY", "EFFECT_TYPE_XMATERIAL",
    "EFFECT_TYPE_GRANT", "EFFECT_TYPE_DISABLE", "EFFECT_TYPE_FLIP",
    "EFFECT_FLAG_DELAY", "EFFECT_FLAG_DAMAGE_STEP", "EFFECT_FLAG_DAMAGE_CAL",
    "EFFECT_FLAG_CARD_TARGET", "EFFECT_FLAG_SET_AVAILABLE", "EFFECT_FLAG_NO_TURN_RESET",
    "EFFECT_FLAG_IGNORE_IMMUNE", "EFFECT_FLAG_PLAYER_TARGET", "EFFECT_FLAG_SINGLE_RANGE",
    "EFFECT_FLAG_CANNOT_DISABLE", "EFFECT_FLAG_UNCOPYABLE", "EFFECT_FLAG_AVAILABLE_BD",
    "CATEGORY_TOHAND", "CATEGORY_SEARCH", "CATEGORY_DRAW", "CATEGORY_DESTROY",
    "CATEGORY_REMOVE", "CATEGORY_SPECIAL_SUMMON", "CATEGORY_DAMAGE", "CATEGORY_RECOVER",
    "CATEGORY_NEGATE", "CATEGORY_DISABLE", "CATEGORY_ATKCHANGE", "CATEGORY_DEFCHANGE",
    "CATEGORY_POSITION", "CATEGORY_CONTROL", "CATEGORY_COUNTER", "CATEGORY_DECKDES",
    "CATEGORY_GRAVE_ACTION", "CATEGORY_GRAVE_SPSUMMON", "CATEGORY_SUMMON", "CATEGORY_SET",
    "CATEGORY_RELEASE", "CATEGORY_DISCARD", "CATEGORY_TODECK", "CATEGORY_LEAVE_GRAVE",
    "LOCATION_DECK", "LOCATION_HAND", "LOCATION_MZONE", "LOCATION_SZONE",
    "LOCATION_GRAVE", "LOCATION_REMOVED", "LOCATION_EXTRA", "LOCATION_FZONE",
    "LOCATION_PZONE", "LOCATION_EMZONE", "LOCATION_ONFIELD", "LOCATION_ALL",
    "REASON_EFFECT", "REASON_COST", "REASON_DESTROY", "REASON_BATTLE",
    "REASON_RELEASE", "REASON_DISCARD", "REASON_RULE", "REASON_SPSUMMON",
    "HINT_SELECTMSG", "HINTMSG_ATOHAND", "HINTMSG_TOGRAVE", "HINTMSG_DESTROY",
    "HINTMSG_REMOVE", "HINTMSG_FACEUP", "HINTMSG_FACEDOWN", "HINTMSG_TARGET",
    "HINTMSG_RELEASE", "HINTMSG_DISCARD", "HINTMSG_NEGATE",
    "POS_FACEUP_ATTACK", "POS_FACEUP_DEFENSE", "POS_FACEDOWN_DEFENSE", "POS_FACEUP",
    "PHASE_MAIN1", "PHASE_MAIN2", "PHASE_BATTLE", "PHASE_END", "PHASE_DRAW",
    "PHASE_STANDBY", "PHASE_BATTLE_START", "PHASE_DAMAGE", "PHASE_DAMAGE_CAL",
    "PLAYER_ALL", "PLAYER_NONE", "PLAYER_SELF", "PLAYER_OPPONENT",
    "EVENT_SUMMON_SUCCESS", "EVENT_SPSUMMON_SUCCESS", "EVENT_FLIP_SUMMON_SUCCESS",
    "EVENT_TO_GRAVE", "EVENT_REMOVE", "EVENT_DESTROYED", "EVENT_BATTLE_DESTROYED",
    "EVENT_LEAVE_FIELD", "EVENT_CHAINING", "EVENT_CHAIN_SOLVED", "EVENT_FREE_CHAIN",
    "EVENT_PHASE", "EVENT_PHASE_START", "EVENT_ATTACK_ANNOUNCE", "EVENT_BE_BATTLE_TARGET",
    "EVENT_DAMAGE_STEP_START", "EVENT_DAMAGE_STEP_END", "EVENT_TO_HAND",
    "EVENT_ADD_COUNTER", "EVENT_REMOVE_COUNTER", "EVENT_SET", "EVENT_MSET",
    "ATTRIBUTE_EARTH", "ATTRIBUTE_WATER", "ATTRIBUTE_FIRE", "ATTRIBUTE_WIND",
    "ATTRIBUTE_LIGHT", "ATTRIBUTE_DARK", "ATTRIBUTE_DIVINE",
    "RACE_WARRIOR", "RACE_SPELLCASTER", "RACE_DRAGON", "RACE_FIEND", "RACE_MACHINE",
    "TYPE_MONSTER", "TYPE_SPELL", "TYPE_TRAP", "TYPE_EFFECT", "TYPE_FUSION",
    "TYPE_SYNCHRO", "TYPE_XYZ", "TYPE_LINK", "TYPE_PENDULUM", "TYPE_RITUAL",
})

#: 卡对象方法（``c:XXX()``）兜底
_BUILTIN_METHODS = frozenset({
    "IsMonster", "IsSpell", "IsTrap", "IsType", "IsRace", "IsAttribute", "IsSetCard",
    "IsCode", "IsLevelBelow", "IsLevelAbove", "IsRank", "IsLink", "IsFusion",
    "IsSynchro", "IsXyz", "IsLink", "IsRitual", "IsPendulum", "IsFaceup",
    "IsFacedown", "IsPosition", "IsLocation", "IsControler", "IsPreviousLocation",
    "IsReason", "IsReasonCard", "IsRelateToEffect", "IsRelateToChain",
    "IsCanBeSpecialSummoned", "IsAbleToHand", "IsAbleToGrave", "IsAbleToRemove",
    "IsAbleToDeck", "IsAbleToChangeControler", "IsNotTuner", "IsTuner", "IsHasEffect",
    "IsImmuneToEffect", "IsDisabled", "IsDestructable", "IsSummonableCard",
    "GetControler", "GetOwner", "GetLocation", "GetPreviousLocation", "GetPosition",
    "GetPreviousPosition", "GetLevel", "GetRank", "GetLink", "GetOriginalLevel",
    "GetOriginalAttribute", "GetAttribute", "GetRace", "GetType", "GetCode",
    "GetOriginalCode", "GetSetCard", "GetAttack", "GetBaseAttack", "GetDefense",
    "GetBaseDefense", "GetTextAttack", "GetTextDefense", "GetOverlayCount",
    "GetOverlayGroup", "GetEquipGroup", "GetEquipTarget", "GetCardTarget",
    "GetColumn", "GetSequence", "GetFieldID", "GetRealFieldID", "GetCounter",
    "GetReason", "GetReasonCard", "GetReasonEffect", "GetReasonPlayer",
    "RegisterEffect", "RegisterFlagEffect", "ResetFlagEffect", "RegisterSummonEffect",
    "SetStatus", "GetStatus", "IsStatus", "SetCardTarget", "CancelCardTarget",
    "CreateRelation", "CreateEffectRelation", "ReleaseRelation", "GetFirstCardTarget",
    "AddCounter", "RemoveCounter", "EnableCounterPermit", "SetHint", "CompleteProcedure",
    "CheckFusionMaterial", "CheckFusionSubstitute", "CheckRemoveOverlayCard",
    "CheckUniqueOnField", "CheckWithSumEqual", "CheckWithSumGreater", "CheckWithSumGT",
    "CheckWithSumLT", "CheckXyzMaterial", "AssumeProperty", "CopyEffect", "Clone",
    "IsHasEffect", "Equals", "IsCode", "IsSummoned", "IsSpecialSummoned",
})


@lru_cache(maxsize=1)
def _load() -> dict:
    """加载 API 快照（文件缺失则用内置兜底）。"""
    data = {"source": "builtin", "functions": sorted(_BUILTIN_FUNCS),
            "constants": sorted(_BUILTIN_CONSTS), "card_methods": sorted(_BUILTIN_METHODS),
            "aux_functions": sorted(f for f in _BUILTIN_FUNCS if f.startswith("aux.")),
            "groups": {}}
    try:
        if API_JSON.exists():
            raw = json.loads(API_JSON.read_text(encoding="utf-8"))
            data.update({
                "source": str(API_JSON.name),
                "generated": raw.get("generated", ""),
                "functions": raw.get("functions") or data["functions"],
                "aux_functions": raw.get("aux_functions") or data["aux_functions"],
                "constants": raw.get("constants") or data["constants"],
                "card_methods": raw.get("card_methods") or data["card_methods"],
                "groups": raw.get("groups") or {},
                "counts": raw.get("counts") or {},
            })
    except Exception as e:
        data["error"] = str(e)[:200]
    return data


def reload() -> None:
    _load.cache_clear()


def api_functions() -> set:
    return set(_load()["functions"])


def aux_functions() -> set:
    return set(_load()["aux_functions"])


def categories() -> set:
    return set(_load()["groups"].get("CATEGORY_", [])) or \
        {c for c in _load()["constants"] if c.startswith("CATEGORY_")}


def effect_codes() -> set:
    return set(_load()["groups"].get("EFFECT_", [])) or \
        {c for c in _load()["constants"] if c.startswith("EFFECT_")}


def hints() -> set:
    return set(_load()["groups"].get("HINT", [])) or \
        {c for c in _load()["constants"] if c.startswith("HINT")}


def locations() -> set:
    return set(_load()["groups"].get("LOCATION_", [])) or \
        {c for c in _load()["constants"] if c.startswith("LOCATION_")}


def reasons() -> set:
    return set(_load()["groups"].get("REASON_", [])) or \
        {c for c in _load()["constants"] if c.startswith("REASON_")}


def card_methods() -> set:
    return set(_load()["card_methods"])


def constants() -> set:
    return set(_load()["constants"])


def is_known(name: str) -> bool:
    """``Duel.X`` / ``aux.X`` / ``Effect.X`` / ``EFFECT_X`` 是否在快照里出现过。"""
    name = (name or "").strip()
    if not name:
        return True
    d = _load()
    if "." in name:
        return name in set(d["functions"]) or name in set(d["aux_functions"])
    return name in set(d["constants"])


def is_known_method(name: str) -> bool:
    """``c:XXX()`` 的 XXX 是否是已知的卡对象方法。"""
    return (name or "").strip() in card_methods()


def groups() -> dict:
    return dict(_load().get("groups") or {})


def info() -> dict:
    d = _load()
    return {
        "source": d.get("source"), "generated": d.get("generated", ""),
        "error": d.get("error", ""),
        "n_functions": len(d["functions"]), "n_aux": len(d["aux_functions"]),
        "n_constants": len(d["constants"]), "n_methods": len(d["card_methods"]),
        "groups": {k: len(v) for k, v in (d.get("groups") or {}).items()},
        "path": str(API_JSON),
    }


# ══════════════════════════════════════════════════════════════════════
#  代码里出现的 API 引用抽取
# ══════════════════════════════════════════════════════════════════════
RE_CALL = re.compile(r"\b(Duel\.[A-Za-z_]\w*|aux\.[A-Za-z_]\w*|Effect\.[A-Za-z_]\w*)")
RE_METHOD = re.compile(r":([A-Za-z_]\w*)\s*\(")
RE_CONST_USE = re.compile(r"\b(EFFECT_[A-Z0-9_]+|CATEGORY_[A-Z0-9_]+|HINT[A-Z0-9_]*|"
                          r"LOCATION_[A-Z0-9_]+|REASON_[A-Z0-9_]+|ATTRIBUTE_[A-Z0-9_]+|"
                          r"RACE_[A-Z0-9_]+|TYPE_[A-Z0-9_]+|EVENT_[A-Z0-9_]+|"
                          r"PHASE_[A-Z0-9_]+|PLAYER_[A-Z0-9_]+|POS_[A-Z0-9_]+)\b")


def referenced(lua: str) -> dict:
    """从脚本里抽出所有 API / 常量 / 方法引用。"""
    body = _strip_lua_comments(lua or "")
    return {
        "calls": sorted(set(RE_CALL.findall(body))),
        "methods": sorted(set(RE_METHOD.findall(body))),
        "consts": sorted(set(RE_CONST_USE.findall(body))),
    }


def _strip_lua_comments(lua: str) -> str:
    """去掉 Lua 注释与字符串字面量（避免把注释里的名字当成真引用）。"""
    out: list[str] = []
    i, n = 0, len(lua)
    while i < n:
        ch = lua[i]
        # 长注释 --[[ ... ]] / --[==[ ... ]==]
        if lua.startswith("--", i):
            m = re.match(r"--\[(=*)\[", lua[i:])
            if m:
                close = "]" + m.group(1) + "]"
                j = lua.find(close, i)
                i = n if j < 0 else j + len(close)
                continue
            j = lua.find("\n", i)
            i = n if j < 0 else j
            continue
        # 长字符串 [[ ... ]]
        m = re.match(r"\[(=*)\[", lua[i:])
        if m:
            close = "]" + m.group(1) + "]"
            j = lua.find(close, i)
            i = n if j < 0 else j + len(close)
            continue
        if ch in "\"'":
            q = ch
            i += 1
            while i < n:
                if lua[i] == "\\":
                    i += 2
                    continue
                if lua[i] == q:
                    i += 1
                    break
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def unknown(lua: str) -> dict:
    """返回脚本里"不在快照中"的引用（可疑项，供 lint 报 WARN）。"""
    refs = referenced(lua)
    return {
        "calls": [c for c in refs["calls"] if not is_known(c)],
        "methods": [m for m in refs["methods"] if not is_known_method(m)],
        "consts": [c for c in refs["consts"] if not is_known(c)],
    }
