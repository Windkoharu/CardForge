"""效果 IR → **Lua 片段库**（每种效果一个函数，供 :mod:`cardforge.content.lua.emit` 调用）。

写法来源
--------
* 结构照 ``vendor/scripts/samples/c*.lua``（真实卡脚本）：
  ``local s,id=GetID()`` → ``function s.initial_effect(c)`` → 每条效果
  ``local eN=Effect.CreateEffect(c)`` + ``SetDescription(aux.Stringid(id,n))``
  + ``SetCategory/SetType/SetProperty/SetRange/SetCode/SetCountLimit``
  + ``SetCost/SetCondition/SetTarget/SetOperation`` → ``c:RegisterEffect(eN)``；
  辅助函数统一命名 ``s.<语义><槽位><角色>``（``fil`` 过滤 / ``con`` 条件 /
  ``cost`` 代价 / ``tg`` 取对象 / ``op`` 处理）。
* 额外卡组的召唤流程照 ``vendor/scripts/proc_*.lua`` 的**全局入口**：
  ``Fusion.AddProcMix`` / ``Xyz.AddProcedure`` / ``Link.AddProcedure`` /
  ``Synchro.AddProcedure`` / ``Ritual.AddProcGreater`` / ``Pendulum.AddProcedure``
  / ``aux.AddEquipProcedure``，以及 ``utility.lua`` 的
  ``Card.AddCannotBeSpecialSummoned`` 等规则文本工具。
  ``apicatalog.RE_CALL`` 只扫描 ``Duel.*``/``aux.*``/``Effect.*``，所以这些
  前缀不会进 ``unknown()``；它们仍由 :func:`procedure_calls` 收集，
  自测脚本逐个回 ``vendor/scripts`` 里 grep 验证确实定义过。

片段函数约定
------------
``fragment(kind)(eff, spec, ctx) -> str``：

* **返回值**是写进 ``s.initial_effect(c)`` 里的**注册块**（自带制表符缩进）；
  返回空串表示这条效果不需要注册 ``Effect``（规则文本类由
  :func:`frag_rule_text` 输出 utility 调用，降级类只输出注释）。
* 辅助函数通过 :meth:`LuaCtx.add_fn` 登记，由 emit 拼到 ``initial_effect`` 之后。
* 只使用 ``apicatalog`` 白名单里的 API；拿不准的一律 :func:`degrade`
  成 ``-- [CardForge] ...`` 注释，**绝不产出会崩的假代码**。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ...core import constants as C
from ...core.models import CardSpec, EffectSpec, EffectTarget, MaterialPart, SummonSpec
from .. import summon as S
from ..effects import EFFECT_KINDS, kind as effect_kind
from . import apicatalog as API

__all__ = [
    "FRAGMENTS", "fragment", "LuaCtx", "degrade", "procedure_calls",
    "PROVIDED_PROCEDURES", "TRIGGER_LUA", "ZONE_LOCATION",
    "setcode_literals", "summon_procedure_lines", "equip_filter_fn",
    "link_marker_lines", "NO_DESCRIPTION_FRAGMENTS",
]

TAB = "\t"

# ══════════════════════════════════════════════════════════════════════
#  映射表
# ══════════════════════════════════════════════════════════════════════
#: IR 区域键 → Lua ``LOCATION_*``
ZONE_LOCATION: dict[str, str] = {
    "DECK": "LOCATION_DECK", "DECKTOP": "LOCATION_DECK",
    "EXTRA": "LOCATION_EXTRA", "HAND": "LOCATION_HAND",
    "GRAVE": "LOCATION_GRAVE", "REMOVED": "LOCATION_REMOVED",
    "FIELD": "LOCATION_ONFIELD", "MZONE": "LOCATION_MZONE",
    "SZONE": "LOCATION_SZONE", "PZONE": "LOCATION_PZONE",
    "FZONE": "LOCATION_FZONE", "OVERLAY": "LOCATION_OVERLAY",
    "": "LOCATION_ONFIELD",
}
#: 时点键 → ``(EFFECT_TYPE 表达式, SetCode 的 EVENT 表达式, 默认 PROPERTY)``
TRIGGER_LUA: dict[str, tuple[str, str, str]] = {
    "IGNITION": ("EFFECT_TYPE_IGNITION", "", ""),
    "QUICK": ("EFFECT_TYPE_QUICK_O", "EVENT_FREE_CHAIN", ""),
    # 「对方把怪兽的效果发动时…才能发动」= 可选诱发（不是必须发动的反击类）
    "OPPONENT_ACTIVATE_MONSTER": ("EFFECT_TYPE_FIELD+EFFECT_TYPE_TRIGGER_O",
                                  "EVENT_CHAINING", "EFFECT_FLAG_DELAY"),
    "NORMAL_SUMMON_SUCCESS": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                              "EVENT_SUMMON_SUCCESS", "EFFECT_FLAG_DELAY"),
    "SPECIAL_SUMMON_SUCCESS": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                               "EVENT_SPSUMMON_SUCCESS", "EFFECT_FLAG_DELAY"),
    "SUMMON_ANY_SUCCESS": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                           "EVENT_SUMMON_SUCCESS", "EFFECT_FLAG_DELAY"),
    "FLIP_SUMMON": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                    "EVENT_FLIP_SUMMON_SUCCESS", "EFFECT_FLAG_DELAY"),
    "WHEN_DESTROYED": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                       "EVENT_DESTROYED", "EFFECT_FLAG_DELAY"),
    "WHEN_SENT_GRAVE": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                        "EVENT_TO_GRAVE", "EFFECT_FLAG_DELAY"),
    "WHEN_BANISHED": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                      "EVENT_REMOVE", "EFFECT_FLAG_DELAY"),
    "WHEN_TO_HAND": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                     "EVENT_TO_HAND", "EFFECT_FLAG_DELAY"),
    "BATTLE_DESTROY_SELF": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                            "EVENT_BATTLE_DESTROYING", "EFFECT_FLAG_DELAY"),
    "BATTLE_DESTROYED_SELF": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                              "EVENT_BATTLE_DESTROYED", "EFFECT_FLAG_DELAY"),
    "ATTACK_DECLARE": ("EFFECT_TYPE_FIELD+EFFECT_TYPE_TRIGGER_O",
                       "EVENT_ATTACK_ANNOUNCE", ""),
    "OPPONENT_ACTIVATE": ("EFFECT_TYPE_QUICK_F", "EVENT_CHAINING", ""),
    "ON_ACTIVATE": ("EFFECT_TYPE_QUICK_F", "EVENT_CHAINING", ""),
    "DAMAGE_STEP_START": ("EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O",
                          "EVENT_BATTLE_START", "EFFECT_FLAG_DAMAGE_STEP"),
    "END_PHASE": ("EFFECT_TYPE_FIELD+EFFECT_TYPE_TRIGGER_O", "EVENT_PHASE+PHASE_END", ""),
    "STANDBY_PHASE": ("EFFECT_TYPE_FIELD+EFFECT_TYPE_TRIGGER_O",
                      "EVENT_PHASE+PHASE_STANDBY", ""),
    "CONTINUOUS": ("EFFECT_TYPE_SINGLE", "", ""),
    "EQUIP_RELATED": ("EFFECT_TYPE_EQUIP", "", ""),
}
#: 时点键 → 「发动时这张卡自己在哪个区域」（``SetRange`` 的取值）
TRIGGER_SELF_RANGE: dict[str, str] = {
    "WHEN_SENT_GRAVE": "LOCATION_GRAVE",
    "WHEN_BANISHED": "LOCATION_REMOVED",
    "WHEN_TO_HAND": "LOCATION_HAND",
    "BATTLE_DESTROYED_SELF": "LOCATION_GRAVE",
}
#: ``filter_kind`` / ``params['card_type']`` 取值 → ``TYPE_*`` 表达式
TYPE_WORDS: dict[str, str] = {
    "monster": "TYPE_MONSTER", "spell": "TYPE_SPELL", "trap": "TYPE_TRAP",
    "spelltrap": "TYPE_SPELL+TYPE_TRAP", "spell/trap": "TYPE_SPELL+TYPE_TRAP",
    "normal": "TYPE_NORMAL", "effect": "TYPE_EFFECT", "fusion": "TYPE_FUSION",
    "synchro": "TYPE_SYNCHRO", "xyz": "TYPE_XYZ", "link": "TYPE_LINK",
    "ritual": "TYPE_RITUAL", "pendulum": "TYPE_PENDULUM", "tuner": "TYPE_TUNER",
    "token": "TYPE_TOKEN", "flip": "TYPE_FLIP",
}
_ATTR_BIT_NAME: dict[int, str] = {
    1: "ATTRIBUTE_EARTH", 2: "ATTRIBUTE_WATER", 4: "ATTRIBUTE_FIRE",
    8: "ATTRIBUTE_WIND", 16: "ATTRIBUTE_LIGHT", 32: "ATTRIBUTE_DARK",
    64: "ATTRIBUTE_DIVINE",
}
#: 位值 → ``RACE_*`` 常量名（直接从 constants 反查，避免把中文种族名当常量）
_RACE_BIT_NAME: dict[int, str] = {
    int(v): k for k, v in vars(C).items()
    if k.startswith("RACE_") and isinstance(v, int)
}
#: 位值 → ``LINK_MARKER_*`` 名（值与 ``vendor/scripts/constant.lua`` 一致）
BIT_MARKER: dict[int, str] = {
    1: "LINK_MARKER_BOTTOM_LEFT", 2: "LINK_MARKER_BOTTOM",
    4: "LINK_MARKER_BOTTOM_RIGHT", 8: "LINK_MARKER_LEFT",
    32: "LINK_MARKER_RIGHT", 64: "LINK_MARKER_TOP_LEFT",
    128: "LINK_MARKER_TOP", 256: "LINK_MARKER_TOP_RIGHT",
}
#: ``proc_*.lua`` / ``utility.lua`` 里真实定义的召唤流程与规则文本入口
PROVIDED_PROCEDURES: tuple[str, ...] = (
    "Fusion.AddProcMix", "Fusion.AddProcMixRep", "Fusion.AddProcMixRepUnfix",
    "Fusion.AddContactProc",
    "Xyz.AddProcedure", "Xyz.InfiniteMats", "Link.AddProcedure",
    "Synchro.AddProcedure", "Synchro.NonTuner", "Ritual.AddProcGreater",
    "Pendulum.AddProcedure", "aux.AddEquipProcedure",
    "Card.AddCannotBeSpecialSummoned", "Card.AddCannotBeNormalSummoned",
    "Card.AddMustFirstBeFusionSummoned", "Card.AddMustFirstBeSynchroSummoned",
    "Card.AddMustFirstBeXyzSummoned", "Card.AddMustFirstBeLinkSummoned",
    "Card.AddMustFirstBeRitualSummoned", "Card.AddSetcodesRule",
    "aux.fuslimit", "aux.synlimit", "aux.xyzlimit", "aux.lnklimit",
    "aux.ritlimit",
)
_used_procedures: set = set()


def procedure_calls() -> set:
    """本模块实际用过的召唤流程/工具入口（自测：回 vendor 脚本验证存在）。"""
    return set(_used_procedures)


def _use(proc: str) -> None:
    _used_procedures.add(proc)


# ══════════════════════════════════════════════════════════════════════
#  小工具
# ══════════════════════════════════════════════════════════════════════
def setcode_literals(spec: CardSpec) -> tuple:
    """``spec.setcode`` → Lua 十六进制字面量元组。

    支持 ``"0x1001"`` / ``"0x1001+0x2"`` / ``"0x1001, 0xe2"`` / ``"4129"``；
    解析失败返回 ``()``（可降级，不抛异常）。
    """
    raw = str(getattr(spec, "setcode", "") or "").strip()
    if not raw:
        return ()
    out: list[str] = []
    for tok in re.findall(r"0[xX][0-9a-fA-F]+|\d+", raw):
        try:
            v = int(tok, 16) if tok.lower().startswith("0x") else int(tok)
        except Exception:
            continue
        if v:
            lit = hex(v)
            if lit not in out:
                out.append(lit)
    return tuple(out)


def _zone_of(eff: EffectSpec, which: str = "from") -> str:
    t = eff.target
    z = str(getattr(t, f"{which}_zone", "") or "").upper() if t is not None else ""
    if not z:
        z = str((eff.params or {}).get(f"{which}_zone") or "").upper()
    return z


def _controller(eff: EffectSpec, default: str = "self") -> str:
    t = eff.target
    return str(getattr(t, "controller", default) or default) if t is not None else default


def _count(eff: EffectSpec, default: int = 1) -> tuple:
    """返回 ``(min, max)`` 选取数量。"""
    t, p = eff.target, eff.params or {}
    n = default
    if t is not None:
        try:
            n = int(t.count or 0) or default
        except Exception:
            n = default
    elif p.get("count") or p.get("n"):
        try:
            n = int(p.get("count") or p.get("n"))
        except Exception:
            n = default
    mx = n
    raw_max = t.count_max if t is not None else p.get("count_max")
    try:
        if raw_max:
            mx = max(int(raw_max), n)
    except Exception:
        mx = n
    return max(1, n), max(1, mx)


def _value(eff: EffectSpec, *keys: str, default: int = 0) -> int:
    p = eff.params or {}
    for k in (keys or ("value",)):
        if p.get(k) not in (None, ""):
            try:
                return int(p[k])
            except Exception:
                continue
    if eff.target is not None:
        try:
            return int(eff.target.count or default)
        except Exception:
            return default
    return default


def _param(eff: EffectSpec, key: str, default: Any = None) -> Any:
    return (eff.params or {}).get(key, default)


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def _race_lua(race: Any) -> str:
    """种族 → ``RACE_*`` 常量；白名单没命中就用十六进制位值。"""
    bit = C.RACE_MAP.get(str(race or ""))
    if not bit:
        return ""
    name = _RACE_BIT_NAME.get(int(bit), "")
    return name if name and API.is_known(name) else hex(int(bit))


def _attr_lua(attr: Any) -> str:
    bit = C.ATTRIBUTE_MAP.get(str(attr or ""))
    if not bit:
        return ""
    name = _ATTR_BIT_NAME.get(int(bit), "")
    return name if name and API.is_known(name) else hex(int(bit))


def _type_lua(value: Any) -> str:
    expr = TYPE_WORDS.get(str(value or "").strip().lower(), "")
    if not expr:
        return ""
    parts = expr.split("+")
    return "+".join(parts) if all(API.is_known(x) for x in parts) else ""


def _location(zone: str) -> str:
    return ZONE_LOCATION.get(str(zone or "").upper(), "LOCATION_ONFIELD")


# ══════════════════════════════════════════════════════════════════════
#  LuaCtx
# ══════════════════════════════════════════════════════════════════════
@dataclass
class LuaCtx:
    """一次脚本组装的共享状态（槽位分配 / Stringid 索引 / 辅助函数池 / 降级说明）。

    ``slot`` 是当前效果的**注册槽位**（决定 ``e1`` 变量名与函数名后缀），
    ``str_index`` 是下一个可用的 ``aux.Stringid(id, n)`` 索引 ——
    两者由 :mod:`emit` 统一推进，保证卡文框的 ①②③、cdb 的 ``str1..str16``
    与脚本引用三者严格同步（历史缺陷 #9 就是它们错位）。
    """

    spec: CardSpec
    lang: str = "zh_cn"
    box: str = "monster"                       # monster | pendulum
    slot: int = 0
    str_index: int = 0
    current_string: int = -1                   # 本效果该用的 Stringid 索引（emit 分配）
    strings: list = field(default_factory=list)
    funcs: list = field(default_factory=list)  # [(name, lua_source)]
    notes: list = field(default_factory=list)
    setcodes: tuple = ()
    #: 已占用的 ``SetCountLimit`` 计数桶（0 = 裸 ``id``，N≥1 = ``{id,N}``）
    limit_slots: set = field(default_factory=set)
    #: 本条效果是否需要在「特殊召唤成功」时点再注册一份（``SUMMON_ANY_SUCCESS``）
    clone_spsummon: bool = False

    # ── 取名 / 登记 ─────────────────────────────────────────────────
    def alloc_limit_slot(self, prefer_named: bool = False) -> int:
        """分配一个**不与同卡其它效果撞车**的 ``SetCountLimit`` 计数桶。

        官方写法：一张卡的第 1 条限制写 ``SetCountLimit(1,id)``（等价于桶 0），
        后面每条各用 ``SetCountLimit(1,{id,N})``，``N`` 依次为 1、2、3……
        两个效果共用同一个桶会让「用掉①」把「②」也一起限死，所以桶号必须独占。

        :param prefer_named: True 时跳过桶 0（卡名 once-per-turn 这类要求写 ``{id,N}``）。
        """
        n = 1 if prefer_named else 0
        while n in self.limit_slots:
            n += 1
        self.limit_slots.add(n)
        return n

    def name(self, role: str) -> str:
        """当前效果的第 ``role`` 号辅助函数名，如 ``s.fil1`` / ``s.op1``。"""
        return f"s.{role}{self.slot}"

    def add_fn(self, fname: str, params: str, *body: str) -> None:
        """登记一个顶层 Lua 函数（``body`` 里不用手写缩进）。"""
        lines = [f"function {fname}({params})"]
        for ln in body:
            for sub in str(ln).splitlines() or [""]:
                lines.append(TAB + sub if sub.strip() else "")
        lines.append("end")
        self.funcs.append((fname, "\n".join(lines)))

    def alloc_string(self, text: str) -> int:
        """分配一个 ``aux.Stringid`` 索引；超过 16 槽返回 ``-1``（调用方降级）。"""
        if self.str_index >= 16:
            self.note("效果描述超过 str1–str16 上限，后续效果不再引用 Stringid")
            return -1
        idx = self.str_index
        self.strings.append(str(text or "").strip())
        self.str_index += 1
        return idx

    def note(self, msg: str) -> None:
        if msg and msg not in self.notes:
            self.notes.append(msg)

    # ── 卡片侧事实 ──────────────────────────────────────────────────
    @property
    def is_spelltrap(self) -> bool:
        return self.spec.frame in ("spell", "trap")


# ══════════════════════════════════════════════════════════════════════
#  过滤函数
# ══════════════════════════════════════════════════════════════════════
def _filter_expr(ctx: LuaCtx, tgt: Optional[EffectTarget], *,
                 able: str = "", card_type: str = "",
                 faceup: bool = False, monster_only: bool = False) -> list:
    """过滤条件表达式列表（``and`` 连接）。"""
    parts: list[str] = []
    if tgt is not None:
        fk = str(tgt.filter_kind or "any")
        val = tgt.filter_value
        if fk == "archetype":
            code = ctx.setcodes[0] if ctx.setcodes else ""
            if code:
                parts.append(f"c:IsSetCard({code})")
            else:
                ctx.note("字段引用没有对应 setcode，过滤条件已放宽成「任何卡」")
        elif fk == "name":
            ctx.note(f"卡名「{val}」→ 卡号需要全局卡号表，这里按本卡卡名登记，请人工核对")
            parts.append("c:IsCode(id)")
        elif fk == "race":
            r = _race_lua(val)
            if r:
                parts.append(f"c:IsRace({r})")
        elif fk == "attribute":
            a = _attr_lua(val)
            if a:
                parts.append(f"c:IsAttribute({a})")
        elif fk == "level":
            try:
                parts.append(f"c:IsLevelAbove({int(val)})")
            except Exception:
                pass
        elif fk == "type":
            t = _type_lua(val if val not in (None, "") else card_type)
            if t:
                parts.append(f"c:IsType({t})")
        elif fk == "monster":
            parts.append("c:IsMonster()")
    if card_type and (tgt is None or str(tgt.filter_kind) != "type"):
        t = _type_lua(card_type)
        if t:
            parts.append(f"c:IsType({t})")
        elif not parts:
            parts.append("c:IsMonster()")
    if monster_only and not parts:
        parts.append("c:IsMonster()")
    if tgt is not None and getattr(tgt, "face_up", False) and "c:IsFaceup()" not in parts:
        # 卡文写「以…1张表侧表示的卡为对象」→ 脚本必须过滤里侧（历史缺口）
        parts.append("c:IsFaceup()")
    if faceup and "c:IsFaceup()" not in parts:
        parts.append("c:IsFaceup()")
    if able:
        parts.append(able)
    return parts


def _make_filter(ctx: LuaCtx, eff: EffectSpec, *, able: str = "",
                 card_type: str = "", faceup: bool = False,
                 monster_only: bool = False,
                 needs_ep: bool = False) -> tuple:
    """登记过滤函数，返回 ``(函数名, 调用时的实参尾巴)``。

    ``needs_ep=True`` 时过滤函数签名是 ``function s.filN(c,e,tp)``
    （``c:IsCanBeSpecialSummoned(e,0,tp,...)`` 这类判定要拿到效果和玩家），
    调用处必须跟着补 ``,e,tp`` —— 返回的第二个值就是这个尾巴。
    """
    fname = ctx.name("fil")
    parts = _filter_expr(ctx, eff.target, able=able, card_type=card_type,
                         faceup=faceup, monster_only=monster_only)
    expr = " and ".join(parts) if parts else "true"
    tail = ",e,tp" if needs_ep else ""
    ctx.add_fn(fname, f"c{tail}", f"return {expr}")
    return fname, tail


# ══════════════════════════════════════════════════════════════════════
#  注册块骨架
# ══════════════════════════════════════════════════════════════════════
def _activation_type(ctx: LuaCtx, eff: EffectSpec) -> tuple:
    """返回 ``(EFFECT_TYPE, SetCode, 默认 PROPERTY)``。"""
    trig = str(eff.trigger or "IGNITION").upper()
    if (eff.params or {}).get("continuous") or trig == "CONTINUOUS":
        return TRIGGER_LUA["CONTINUOUS"]
    type_expr, code, prop = TRIGGER_LUA.get(trig, TRIGGER_LUA["IGNITION"])
    if ctx.is_spelltrap and trig in ("IGNITION", "QUICK", ""):
        # 魔法·陷阱没有"起动效果"，靠卡种发动（速攻/反击的 2 速由卡种提供）
        return ("EFFECT_TYPE_ACTIVATE", code or "EVENT_FREE_CHAIN", prop)
    return (type_expr, code, prop)


def _range_loc(ctx: LuaCtx, eff: EffectSpec) -> str:
    """这条效果注册时该写的 ``SetRange`` —— 也就是**发动这张卡时它自己所在的区域**。

    官方口径（参照 ``c18716735`` / ``c10966439`` 等真实卡）：

    * 墓地里的诱发效果 → ``LOCATION_GRAVE``，被除外时 → ``LOCATION_REMOVED``；
      写成 ``LOCATION_MZONE`` 会让效果在对局里**永远不触发**；
    * 灵摆框效果 → ``LOCATION_PZONE``；
    * 魔法·陷阱的「发动」本身 → 不写 ``SetRange``（发动区域由卡种决定，
      多写一行是冗余）；
    * ``params['self_zone']`` 可显式覆盖（例如「从手卡特殊召唤这张卡」）。
    """
    p = eff.params or {}
    if p.get("self_zone"):
        return _location(str(p["self_zone"]))
    if ctx.box == "pendulum":
        return "LOCATION_PZONE"
    trig = str(eff.trigger or "").upper()
    if ctx.spec.is_monster and trig in TRIGGER_SELF_RANGE:
        return TRIGGER_SELF_RANGE[trig]
    typ = _activation_type(ctx, eff)[0]
    if "EFFECT_TYPE_ACTIVATE" in typ:
        return ""
    if ctx.spec.frame in ("spell", "trap"):
        return "LOCATION_SZONE"
    if ctx.spec.is_monster:
        return "LOCATION_MZONE"
    return "LOCATION_ONFIELD"


def _is_targeting(eff: EffectSpec) -> bool:
    """这条效果是否**取对象**（与 PSCT 卡文侧同一判定）。"""
    p = eff.params or {}
    if "targeting" in p:
        return _truthy(p.get("targeting"))
    if eff.target is None:
        return False
    k = effect_kind(eff.kind)
    if k is None:
        return True
    return k.takes_target


def _property(eff: EffectSpec, base: str, *, targeting: Optional[bool] = None) -> str:
    """拼装 PROPERTY 表达式。

    ``targeting`` 由片段显式传入：注册表里的「取对象」归属是按**卡文句式**判定的
    （``psct.rules.NON_TARGETING_KINDS``），而脚本里到底是 ``SelectTarget`` 还是
    ``SelectMatchingCard`` 是另一回事 —— 两者不一致时以**脚本实际写法**为准，
    否则会生成「标了取对象标记却没有取对象」的自相矛盾效果。
    """
    parts = [base] if base else []
    flag = _is_targeting(eff) if targeting is None else targeting
    if flag:
        parts.append("EFFECT_FLAG_CARD_TARGET")
    return "+".join(x for x in parts if x)


def _limit_lines(ctx: LuaCtx, eff: EffectSpec, v: str) -> list:
    """``limit`` → ``SetCountLimit``。

    与官方写法一一对应（``vendor/scripts/samples/c11161666.lua`` /
    ``c1122030.lua`` 实测）：

    =======================================  ==========================================
    ``limit``                                生成
    =======================================  ==========================================
    ``once_per_turn``                        ``SetCountLimit(1,id)``
    ``hopt_name`` / ``hopt_name_use``        ``SetCountLimit(1,{id,N})``
    ``hopt_name_activate``                   ``SetCountLimit(1,{id,N},EFFECT_COUNT_CODE_OATH)``
    ``once_duel``                            ``SetCountLimit(1,{id,N},EFFECT_COUNT_CODE_DUEL)``
    ``once_while_faceup``                    ``SetCountLimit(1,id)`` + 降级说明
    =======================================  ==========================================

    ``N`` 由 :meth:`LuaCtx.alloc_limit_slot` 顺序分配，**保证同一张卡的不同效果
    不会共用计数桶**（共用会让①把②一起限死）。``EFFECT_FLAG_NO_TURN_RESET``
    **不能**当第三个参数用 —— 那是 ``SetProperty`` 的旗标，跨回合限制要用
    ``EFFECT_COUNT_CODE_DUEL``（本 build 的 ``constant.lua`` 里有）。
    """
    lim = str(eff.limit or "none")
    if lim in ("", "none"):
        return []
    named = lim in ("hopt_name", "hopt_name_use", "hopt_name_activate", "once_duel")
    n = ctx.alloc_limit_slot(prefer_named=named)
    ref = "id" if n == 0 else f"{{id,{n}}}"
    if lim == "hopt_name_activate":
        return [f"{v}:SetCountLimit(1,{ref},EFFECT_COUNT_CODE_OATH)"]
    if lim in ("once_duel", "hopt_name_apply"):
        return [f"{v}:SetCountLimit(1,{ref},EFFECT_COUNT_CODE_DUEL)"]
    if lim == "once_while_faceup":
        ctx.note("once_while_faceup（表侧表示期间 1 次）用 SetCountLimit 近似，"
                 "离场即重置；要严格「只在表侧期间计数」需人工补 SetReset 逻辑")
    return [f"{v}:SetCountLimit(1,{ref})"]


def _description(ctx: LuaCtx, eff: EffectSpec) -> str:
    """cdb ``str*`` 文本：作者原文优先，其次按卡文模板生成再剥掉段首编号。"""
    p = eff.params or {}
    if p.get("desc"):
        return str(p["desc"])
    if eff.raw_text:
        return _strip_number(str(eff.raw_text))
    try:
        from ..psct import gen
        return _strip_number(gen.effect_to_text(eff, ctx.spec, ctx.lang,
                                                index=ctx.slot + 1))
    except Exception:
        return str(eff.kind or "")


def _strip_number(text: str) -> str:
    """剥掉段首编号（①②…）与其后的「：」，cdb str 里不重复卡文编号。"""
    from ..psct import rules as PR
    t = (text or "").strip()
    marks = set(PR.number_symbols(list(range(1, 21))))
    while t and t[0] in marks:
        t = t[1:].lstrip("：:、 。.")
    return t.strip()


def _begin(ctx: LuaCtx, eff: EffectSpec, *, category: str = "",
           use_stringid: bool = True,
           targeting: Optional[bool] = None) -> tuple:
    """注册块的开头若干行；返回 ``(效果变量名, 行列表)``。

    ``aux.Stringid(id, n)`` 的 ``n`` **不在这里分配**，而是取 emit 按
    :func:`cardforge.content.lua.emit.plan` 预先算好的 ``ctx.current_string``
    —— 这样脚本引用与 cdb ``str1..str16``、卡文框编号永远同源。
    """
    v = f"e{ctx.slot}"
    typ, code, prop = _activation_type(ctx, eff)
    # 「召唤·特殊召唤成功时」= 同一份效果在两个时点各注册一次（官方写法）
    ctx.clone_spsummon = str(eff.trigger or "").upper() == "SUMMON_ANY_SUCCESS"
    if not category:
        k = effect_kind(eff.kind)
        bits = getattr(k, "category_bits", 0) if k else 0
        # 注册表里存的是 Lua 表达式字符串（如 "CATEGORY_TOHAND+CATEGORY_SEARCH"）
        category = bits if isinstance(bits, str) else ""
    lines = [f"local {v}=Effect.CreateEffect(c)"]
    if use_stringid and ctx.current_string >= 0:
        lines.append(f"{v}:SetDescription(aux.Stringid(id,{ctx.current_string}))")
    if category:
        lines.append(f"{v}:SetCategory({category})")
    lines.append(f"{v}:SetType({typ})")
    full_prop = _property(eff, prop, targeting=targeting)
    if full_prop:
        lines.append(f"{v}:SetProperty({full_prop})")
    rng = _range_loc(ctx, eff)
    if rng:
        lines.append(f"{v}:SetRange({rng})")
    if code:
        lines.append(f"{v}:SetCode({code})")
    lines += _limit_lines(ctx, eff, v)
    return v, lines


def _hook_lines(ctx: LuaCtx, v: str, eff: EffectSpec) -> list:
    """需要但尚未接线的 ``SetCost`` / ``SetCondition`` 行（供片段自行决定位置）。"""
    out: list[str] = []
    cost = _cost_fn(ctx, eff)
    if cost:
        out.append(f"{v}:SetCost({cost})")
    con = _add_condition(ctx, eff)
    if con:
        out.append(f"{v}:SetCondition({con})")
    return out


# ══════════════════════════════════════════════════════════════════════
#  代价
# ══════════════════════════════════════════════════════════════════════
def _cost_fn(ctx: LuaCtx, eff: EffectSpec) -> str:
    """登记代价函数并返回名字；没有代价返回 ``""``。"""
    cost = eff.cost
    if cost is None or str(cost.kind or "none") in ("", "none"):
        return ""
    k = str(cost.kind)
    n = max(1, int(cost.count or 1))
    zone = str(cost.zone or "").upper()
    loc = _location(zone or "MZONE")
    fname = ctx.name("cfil")
    role = ctx.name("cost")
    if k == "tribute_self":
        ctx.add_fn(role, "e,tp,eg,ep,ev,re,r,rp,chk",
                   "if chk==0 then return e:GetHandler():IsReleasable() end",
                   "Duel.Release(e:GetHandler(),REASON_COST)")
        return role
    if k == "discard_self":
        ctx.add_fn(role, "e,tp,eg,ep,ev,re,r,rp,chk",
                   "if chk==0 then return Duel.GetFieldGroupCount(tp,LOCATION_HAND,0)>0 end",
                   "Duel.DiscardHand(tp,aux.TRUE,1,1,REASON_COST+REASON_DISCARD)")
        return role
    if k == "pay_lp":
        lp = int(cost.lp or _value(eff, "lp", "value", default=0) or 1000)
        ctx.add_fn(role, "e,tp,eg,ep,ev,re,r,rp,chk",
                   f"if chk==0 then return Duel.CheckLPCost(tp,{lp}) end",
                   f"Duel.PayLPCost(tp,{lp})")
        return role
    if k == "detach":
        ctx.add_fn(role, "e,tp,eg,ep,ev,re,r,rp,chk",
                   "local sc=e:GetHandler()",
                   f"if chk==0 then return sc:CheckRemoveOverlayCard(tp,{n},REASON_COST) end",
                   f"sc:RemoveOverlayCard(tp,{n},{n},REASON_COST)")
        return role
    if k in ("discard", "discard_opponent"):
        ctx.add_fn(role, "e,tp,eg,ep,ev,re,r,rp,chk",
                   f"if chk==0 then return Duel.GetFieldGroupCount(tp,LOCATION_HAND,0)>={n} end",
                   f"Duel.DiscardHand(tp,aux.TRUE,{n},{n},REASON_COST+REASON_DISCARD)")
        return role
    # release / send_grave / banish：从指定区域选 n 张
    tgt = EffectTarget(from_zone=zone or "MZONE",
                       filter_kind=cost.filter_kind or "any",
                       filter_value=cost.filter_value, count=n)
    able = {"release": "c:IsReleasable()",
            "send_grave": "c:IsAbleToGraveAsCost()",
            "banish": "c:IsAbleToRemoveAsCost()"}.get(k, "true")
    parts = _filter_expr(ctx, tgt, able=able)
    ctx.add_fn(fname, "c", "return " + (" and ".join(parts) if parts else "true"))
    if k == "release":
        ctx.add_fn(role, "e,tp,eg,ep,ev,re,r,rp,chk",
                   f"if chk==0 then return Duel.CheckReleaseGroup(tp,{fname},{n},nil) end",
                   f"local g=Duel.SelectReleaseGroup(tp,{fname},{n},{n},nil)",
                   "Duel.Release(g,REASON_COST)")
    elif k == "banish":
        ctx.add_fn(role, "e,tp,eg,ep,ev,re,r,rp,chk",
                   f"if chk==0 then return Duel.IsExistingMatchingCard({fname},tp,{loc},0,{n},nil) end",
                   "Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_REMOVE)",
                   f"local g=Duel.SelectMatchingCard(tp,{fname},tp,{loc},0,{n},{n},nil)",
                   "Duel.Remove(g,POS_FACEUP,REASON_COST)")
    else:
        ctx.add_fn(role, "e,tp,eg,ep,ev,re,r,rp,chk",
                   f"if chk==0 then return Duel.IsExistingMatchingCard({fname},tp,{loc},0,{n},nil) end",
                   "Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TOGRAVE)",
                   f"local g=Duel.SelectMatchingCard(tp,{fname},tp,{loc},0,{n},{n},nil)",
                   "Duel.SendtoGrave(g,REASON_COST)")
    return role


# ══════════════════════════════════════════════════════════════════════
#  触发条件
# ══════════════════════════════════════════════════════════════════════
def _condition_lines(eff: EffectSpec) -> list:
    """诱发效果的条件函数体（照官方写法：只问原因/控制者/是否在场）。"""
    trig = str(eff.trigger or "").upper()
    if trig == "WHEN_DESTROYED":
        return ["local c=e:GetHandler()",
                "return c:IsReason(REASON_DESTROY) and c:IsPreviousLocation(LOCATION_ONFIELD)"]
    if trig == "WHEN_SENT_GRAVE":
        return ["local c=e:GetHandler()",
                "return c:IsPreviousLocation(LOCATION_ONFIELD) and c:IsLocation(LOCATION_GRAVE)"]
    if trig == "WHEN_BANISHED":
        return ["local c=e:GetHandler()",
                "return c:IsPreviousLocation(LOCATION_ONFIELD) "
                "and c:IsLocation(LOCATION_REMOVED)"]
    if trig == "BATTLE_DESTROYED_SELF":
        return ["return e:GetHandler():IsReason(REASON_BATTLE)"]
    if trig == "BATTLE_DESTROY_SELF":
        return ["return true"]
    if trig in ("OPPONENT_ACTIVATE", "ON_ACTIVATE"):
        return ["return ep~=tp"]
    if trig == "OPPONENT_ACTIVATE_MONSTER":
        return ["return ep~=tp and re:IsMonsterEffect()"]
    if trig == "ATTACK_DECLARE":
        return ["return Duel.GetCurrentChain()==0"]
    if trig in ("END_PHASE", "STANDBY_PHASE"):
        return ["return Duel.IsTurnPlayer(tp)"]
    if trig == "DAMAGE_STEP_START":
        # 官方没有「伤害步骤开始时」这个 EVENT 常量，这里用战斗开始时 +
        # EFFECT_FLAG_DAMAGE_STEP 近似；需要严格卡在伤害步骤请人工改写
        return ["return Duel.GetCurrentPhase()==PHASE_DAMAGE"]
    return []


def _add_condition(ctx: LuaCtx, eff: EffectSpec) -> str:
    """有条件时登记 ``SetCondition`` 函数并返回名字，否则 ``""``。"""
    body = _condition_lines(eff)
    if not body:
        return ""
    fname = ctx.name("con")
    ctx.add_fn(fname, "e,tp,eg,ep,ev,re,r,rp", *body)
    return fname


def _finish(ctx: LuaCtx, v: str, *, cost: str = "", con: str = "",
            target: str = "", operation: str = "") -> list:
    """补 ``SetCost/SetCondition/SetTarget/SetOperation`` 与 ``RegisterEffect``。

    ``SUMMON_ANY_SUCCESS``（「召唤·特殊召唤成功时」）按官方写法注册**两份**：
    一份挂在 ``EVENT_SUMMON_SUCCESS`` 上，另一份 ``Clone()`` 后改挂
    ``EVENT_SPSUMMON_SUCCESS``（参照 ``vendor/scripts/samples/c10966439.lua``
    的 ``e2a`` / ``e2b``）。克隆体沿用同一个 ``SetCountLimit`` 计数桶，
    所以「1回合1次」不会被绕开。
    """
    out: list[str] = []
    if cost:
        out.append(f"{v}:SetCost({cost})")
    if con:
        out.append(f"{v}:SetCondition({con})")
    if target:
        out.append(f"{v}:SetTarget({target})")
    if operation:
        out.append(f"{v}:SetOperation({operation})")
    out.append(f"c:RegisterEffect({v})")
    if ctx.clone_spsummon:
        b = f"{v}b"
        out.append(f"local {b}={v}:Clone()")
        out.append(f"{b}:SetCode(EVENT_SPSUMMON_SUCCESS)")
        out.append(f"c:RegisterEffect({b})")
        ctx.clone_spsummon = False
    return out


def _block(ctx: LuaCtx, lines: list, eff: EffectSpec, label: str = "") -> str:
    """注册块（带一行中文注释头，方便作者接手手改）。"""
    k = effect_kind(eff.kind)
    head = label or _clean_label(eff, k)
    return (f"{TAB}--{ctx.slot}. {head}\n"
            + "\n".join(TAB + ln for ln in lines))


def _clean_label(eff: EffectSpec, k: Any) -> str:
    """注释头用的效果摘要：原文优先，模板里的 ``{obj}/{n}`` 占位符不参与展示。"""
    raw = " ".join((eff.raw_text or "").split())
    if raw:
        return raw[:40]
    zh = (k.zh if k is not None else "") or str(eff.kind or "效果")
    return re.sub(r"\{[^{}]*\}", "…", zh)


def degrade(eff: EffectSpec, ctx: LuaCtx, reason: str) -> str:
    """不生成代码，只写注释 —— 保证脚本不会因为假 API 而崩。"""
    ctx.note(f"效果 kind={eff.kind} 已降级：{reason}")
    raw = (eff.raw_text or "").strip().replace("\n", " ")[:80]
    return (f"{TAB}-- [CardForge] 效果 kind={eff.kind} 暂无脚本片段，需人工补写：{reason}\n"
            + (f"{TAB}-- 原卡文：{raw}" if raw else "").rstrip("\n"))


# ══════════════════════════════════════════════════════════════════════
#  片段：不取对象的「选卡 → 移动」类
# ══════════════════════════════════════════════════════════════════════
def frag_to_hand(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """检索 / 回收：从卡组·墓地·除外区把卡加入手卡（官方写法不取对象）。"""
    zone = _zone_of(eff) or "DECK"
    mn, mx = _count(eff)
    loc = _location(zone)
    fil, ftail = _make_filter(ctx, eff, able="c:IsAbleToHand()",
                             card_type=str(_param(eff, "card_type", "")))
    v, lines = _begin(ctx, eff, category="CATEGORY_TOHAND+CATEGORY_SEARCH",
                       targeting=False)
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk",
               f"if chk==0 then return Duel.IsExistingMatchingCard({fil},tp,{loc},0,{mn},nil) end",
               f"Duel.SetOperationInfo(0,CATEGORY_TOHAND,nil,{mn},tp,{loc})")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               "Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_ATOHAND)",
               f"local g=Duel.SelectMatchingCard(tp,{fil},tp,{loc},0,{mn},{mx},nil)",
               "if #g>0 then",
               f"{TAB}Duel.SendtoHand(g,nil,REASON_EFFECT)",
               f"{TAB}Duel.ConfirmCards(1-tp,g)",
               "end")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    return _block(ctx, lines, eff)


def frag_special_summon(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """特殊召唤（不取对象）：从某区域选卡后 ``Duel.SpecialSummon``。"""
    zone = _zone_of(eff) or "HAND"
    mn, mx = _count(eff)
    loc = _location(zone)
    card_type = str(_param(eff, "card_type", ""))
    ex = _ex_arg(eff)
    fil, ftail = _make_filter(ctx, eff,
                              able="c:IsCanBeSpecialSummoned(e,0,tp,false,false)",
                              card_type=card_type or "monster", needs_ep=True)
    v, lines = _begin(ctx, eff, category="CATEGORY_SPECIAL_SUMMON",
                       targeting=False)
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk",
               f"if chk==0 then return Duel.GetLocationCount(tp,LOCATION_MZONE)>0 "
               f"and Duel.IsExistingMatchingCard({fil},tp,{loc},0,{mn},{ex}{ftail}) end",
               f"Duel.SetOperationInfo(0,CATEGORY_SPECIAL_SUMMON,nil,{mn},tp,{loc})")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               "if Duel.GetLocationCount(tp,LOCATION_MZONE)<=0 then return end",
               "Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_SPSUMMON)",
               f"local g=Duel.SelectMatchingCard(tp,{fil},tp,{loc},0,{mn},{mx},{ex}{ftail})",
               "if #g>0 then",
               f"{TAB}Duel.SpecialSummon(g,0,tp,tp,false,false,POS_FACEUP)",
               "end")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    return _block(ctx, lines, eff)


def frag_special_summon_token(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """在自己场上生成并特殊召唤衍生物。"""
    token = str(_param(eff, "token", "") or "").strip()
    if not token:
        return degrade(eff, ctx, "衍生物卡名（params['token']）缺失")
    mn, mx = _count(eff)
    n = int(_param(eff, "count", 0) or mn)
    atk = int(_param(eff, "atk", 0) or 0)
    dfd = int(_param(eff, "def", _param(eff, "dfd", 0)) or 0)
    lv = int(_param(eff, "level", 1) or 1)
    race = _race_lua(_param(eff, "race", "") or spec.race) or "RACE_WARRIOR"
    attr = _attr_lua(_param(eff, "attribute", "") or spec.attribute) or "ATTRIBUTE_DARK"
    types = "TYPE_MONSTER+TYPE_NORMAL+TYPE_TOKEN"
    if not (API.is_known("TYPE_MONSTER") and API.is_known("TYPE_TOKEN")):
        return degrade(eff, ctx, "TYPE_TOKEN 不在 API 白名单里")
    v, lines = _begin(ctx, eff, category="CATEGORY_SPECIAL_SUMMON+CATEGORY_TOKEN",
                       targeting=False)
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk",
               f"if chk==0 then return Duel.GetLocationCount(tp,LOCATION_MZONE)>={n} "
               f"and Duel.IsPlayerCanSpecialSummonMonster(tp,id+1,0,{types},{atk},{dfd},"
               f"{lv},{race},{attr}) end",
               f"Duel.SetOperationInfo(0,CATEGORY_TOKEN,nil,{n},tp,0)",
               f"Duel.SetOperationInfo(0,CATEGORY_SPECIAL_SUMMON,nil,{n},tp,0)")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               f"if Duel.GetLocationCount(tp,LOCATION_MZONE)<{n} then return end",
               f"for i=1,{n} do",
               f"{TAB}local t=Duel.CreateToken(tp,id+1)",
               f"{TAB}Duel.SpecialSummonStep(t,0,tp,tp,false,false,POS_FACEUP)",
               "end",
               "Duel.SpecialSummonComplete()")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    ctx.note(f"衍生物「{token}」用卡号 id+1，需要一并导出该衍生物卡与它的 cdb 行")
    return _block(ctx, lines, eff)


def frag_destroy_all(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """场上的…全部破坏（不取对象，处理时才选）。"""
    zone = _zone_of(eff) or "MZONE"
    loc = _location(zone)
    ctrl = _controller(eff, "both")
    loc_self, loc_opp = (loc, "0") if ctrl == "self" else \
        ("0", loc) if ctrl == "opponent" else (loc, loc)
    fil, ftail = _make_filter(ctx, eff, able="c:IsDestructable()",
                              card_type=str(_param(eff, "card_type", "")))
    v, lines = _begin(ctx, eff, category="CATEGORY_DESTROY", targeting=False)
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk",
               f"if chk==0 then return Duel.IsExistingMatchingCard({fil},tp,"
               f"{loc_self},{loc_opp},1,nil) end",
               f"Duel.SetOperationInfo(0,CATEGORY_DESTROY,nil,0,PLAYER_ALL,{loc})")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               f"local g=Duel.GetMatchingGroup({fil},tp,{loc_self},{loc_opp},nil)",
               "if #g>0 then",
               f"{TAB}Duel.Destroy(g,REASON_EFFECT)",
               "end")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    ctx.note("destroy_all 不取对象，处理时选「场上的全部」；"
             "若卡文写的是「那张卡」请改用 destroy")
    return _block(ctx, lines, eff)


def frag_draw(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """自己抽 n 张。"""
    n = _count(eff)[0]
    v, lines = _begin(ctx, eff, category="CATEGORY_DRAW", targeting=False)
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk",
               f"if chk==0 then return Duel.IsPlayerCanDraw(tp,{n}) end",
               "Duel.SetTargetPlayer(tp)",
               f"Duel.SetTargetParam({n})",
               f"Duel.SetOperationInfo(0,CATEGORY_DRAW,nil,0,tp,{n})")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               "local p=Duel.GetChainInfo(0,CHAININFO_TARGET_PLAYER)",
               f"Duel.Draw(p,{n},REASON_EFFECT)")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    return _block(ctx, lines, eff)


def frag_mill(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """卡组顶 n 张送去墓地。"""
    n = _count(eff)[0]
    v, lines = _begin(ctx, eff, category="CATEGORY_DECKDES", targeting=False)
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk",
               f"if chk==0 then return Duel.IsPlayerCanDiscardDeck(tp,{n}) end",
               f"Duel.SetOperationInfo(0,CATEGORY_DECKDES,nil,0,tp,{n})")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp", f"Duel.DiscardDeck(tp,{n},REASON_EFFECT)")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    return _block(ctx, lines, eff)


def frag_excavate(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """确认卡组顶 n 张（翻开拓掘；后续处置需要人工补写）。"""
    n = _count(eff)[0]
    v, lines = _begin(ctx, eff, category="", targeting=False)
    op = ctx.name("op")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp", f"Duel.ConfirmDecktop(tp,{n})")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     operation=op)
    ctx.note("excavate 只生成「确认卡组顶 n 张」，翻出卡之后的处置需人工补写")
    return _block(ctx, lines, eff)


def frag_discard_opponent(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """对方丢弃 n 张手卡。"""
    n = _count(eff)[0]
    v, lines = _begin(ctx, eff, category="CATEGORY_HANDES", targeting=False)
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk",
               "if chk==0 then return Duel.GetFieldGroupCount(1-tp,LOCATION_HAND,0)>0 end",
               f"Duel.SetOperationInfo(0,CATEGORY_HANDES,nil,0,1-tp,{n})")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               f"Duel.DiscardHand(1-tp,aux.TRUE,{n},{n},REASON_EFFECT+REASON_DISCARD)")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    ctx.note("discard_opponent 生成的是「对方随机丢弃」；若卡文要求对方自选请手改")
    return _block(ctx, lines, eff)


def frag_set(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """从卡组把魔法·陷阱卡放置（不取对象）。"""
    zone = _zone_of(eff) or "DECK"
    mn, mx = _count(eff)
    loc = _location(zone)
    card_type = str(_param(eff, "card_type", "spelltrap") or "spelltrap")
    fil, ftail = _make_filter(ctx, eff, card_type=card_type)
    v, lines = _begin(ctx, eff, category="CATEGORY_SET", targeting=False)
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk",
               f"if chk==0 then return Duel.GetLocationCount(tp,LOCATION_SZONE)>0 "
               f"and Duel.IsExistingMatchingCard({fil},tp,{loc},0,{mn},nil) end",
               f"Duel.SetOperationInfo(0,CATEGORY_SET,nil,{mn},tp,{loc})")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               "if Duel.GetLocationCount(tp,LOCATION_SZONE)<=0 then return end",
               "Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_SET)",
               f"local g=Duel.SelectMatchingCard(tp,{fil},tp,{loc},0,{mn},{mx},nil)",
               "if #g>0 then",
               f"{TAB}Duel.SSet(tp,g)",
               "end")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    return _block(ctx, lines, eff)


# ══════════════════════════════════════════════════════════════════════
#  片段：取对象的「对目标做一件事」
# ══════════════════════════════════════════════════════════════════════
_ACTIONS: dict[str, dict] = {
    "destroy": dict(cat="CATEGORY_DESTROY", hint="HINTMSG_DESTROY",
                    able="c:IsDestructable()", one="Duel.Destroy(tc,REASON_EFFECT)"),
    "banish": dict(cat="CATEGORY_REMOVE", hint="HINTMSG_REMOVE",
                   able="c:IsAbleToRemove()",
                   one="Duel.Remove(tc,POS_FACEUP,REASON_EFFECT)"),
    "banish_face_down": dict(cat="CATEGORY_REMOVE", hint="HINTMSG_REMOVE",
                             able="c:IsAbleToRemove()",
                             one="Duel.Remove(tc,POS_FACEDOWN,REASON_EFFECT)"),
    "send_grave": dict(cat="CATEGORY_TOGRAVE", hint="HINTMSG_TOGRAVE",
                       able="c:IsAbleToGrave()",
                       one="Duel.SendtoGrave(tc,REASON_EFFECT)"),
    "return_hand": dict(cat="CATEGORY_TOHAND", hint="HINTMSG_ATOHAND",
                        able="c:IsAbleToHand()",
                        one="Duel.SendtoHand(tc,nil,REASON_EFFECT)"),
    "return_deck": dict(cat="CATEGORY_TODECK", hint="HINTMSG_TODECK",
                        able="c:IsAbleToDeck()",
                        one="Duel.SendtoDeck(tc,nil,SEQ_DECKSHUFFLE,REASON_EFFECT)"),
    "shuffle_deck": dict(cat="CATEGORY_TODECK", hint="HINTMSG_TODECK",
                         able="c:IsAbleToDeck()",
                         one="Duel.SendtoDeck(tc,nil,SEQ_DECKSHUFFLE,REASON_EFFECT)"),
}


def _zone_mask(loc_self: str, loc_opp: str) -> str:
    """``(自身区域, 对方区域)`` → ``IsLocation`` 用的掩码表达式。

    ``chkc`` 那一行要的是「这张效果能在哪些区域找到目标」，是一个**并集**；
    而 ``Duel.IsExistingTarget`` / ``SelectTarget`` 用的是（自己, 对方）**两个参数**。
    直接拼 ``{loc_self}|{loc_opp}`` 会产出 ``LOCATION_MZONE|0`` 这种官方绝不写的噪声，
    所以这里做三种归约：一边是 0 → 取另一边；两边相同 → 只写一次；否则才用 ``|``。
    """
    a, b = str(loc_self or "0"), str(loc_opp or "0")
    if a == b:
        return a if a != "0" else "LOCATION_ONFIELD"
    if b == "0":
        return a
    if a == "0":
        return b
    return f"{a}|{b}"


def _target_zones(eff: EffectSpec) -> tuple:
    """返回 ``(过滤函数, 自身区域, 对方区域)``（取对象类效果的搜索范围）。"""
    zone = _zone_of(eff) or "MZONE"
    loc = _location(zone)
    ctrl = _controller(eff, "self")
    if ctrl == "opponent":
        return loc, "0", loc
    if ctrl == "both":
        return loc, loc, loc
    return loc, loc, "0"


def _ex_arg(eff: EffectSpec) -> str:
    """``IsExistingMatchingCard`` / ``SelectMatchingCard`` 的排除对象参数。

    卡文写「「卡名」以外的…」（IR 里是 ``target.exclude_self``）时将排除对象
    作为 ``ex`` 传入，脚本层就不会把这张卡自己选进去。
    """
    tgt = eff.target
    if tgt is not None and getattr(tgt, "exclude_self", False):
        return "e:GetHandler()"
    return "nil"


def _targeted(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx, *, action: str,
              category: str = "", extra_target: str = "",
              operation_extra: tuple = (), faceup: bool = False,
              label: str = "") -> str:
    """「以…为对象才能发动 → 处理时对那个对象做一件事」的通用骨架。"""
    conf = _ACTIONS.get(action, {})
    cat = category or str(conf.get("cat") or "")
    hint = str(conf.get("hint") or "HINTMSG_TARGET")
    able = str(conf.get("able") or "")
    one = str(conf.get("one") or "")
    if API.is_known_method("IsFaceup") and faceup:
        able = f" and ".join(x for x in (able, "c:IsFaceup()") if x)
    loc_self, loc_opp = _target_zones(eff)[1], _target_zones(eff)[2]
    card_type = str(_param(eff, "card_type", ""))
    fil, ftail = _make_filter(ctx, eff, able=able, card_type=card_type, faceup=faceup)
    v, lines = _begin(ctx, eff, category=cat, targeting=True)
    tg, op = ctx.name("tg"), ctx.name("op")
    ex = "e:GetHandler()" if (eff.target is not None and eff.target.exclude_self) else "nil"
    chkc = (f"if chkc then return chkc:IsLocation({_zone_mask(loc_self, loc_opp)}) "
            f"and {fil}(chkc) end")
    body = [chkc,
            f"if chk==0 then return Duel.IsExistingTarget({fil},tp,{loc_self},{loc_opp},"
            f"1,{ex}) end",
            f"Duel.Hint(HINT_SELECTMSG,tp,{hint})",
            f"local g=Duel.SelectTarget(tp,{fil},tp,{loc_self},{loc_opp},"
            f"{_count(eff)[0]},{_count(eff)[1]},{ex})",
            f"Duel.SetOperationInfo(0,{cat or 'CATEGORY_DESTROY'},g,#g,0,0)"]
    if extra_target:
        body.append(extra_target)
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk,chkc", *body)
    op_body = ["local tc=Duel.GetFirstTarget()",
               "if tc and tc:IsRelateToEffect(e) then",
               f"{TAB}{one}"]
    for ln in operation_extra:
        op_body.append(f"{TAB}{ln}")
    op_body.append("end")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp", *op_body)
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    return _block(ctx, lines, eff, label)


def frag_destroy(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    return _targeted(eff, spec, ctx, action="destroy")


def frag_banish(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    action = "banish_face_down" if str(eff.kind) == "banish_face_down" else "banish"
    return _targeted(eff, spec, ctx, action=action)


def frag_send_grave(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    return _targeted(eff, spec, ctx, action="send_grave")


def frag_return_hand(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    return _targeted(eff, spec, ctx, action="return_hand")


def frag_return_deck(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    action = "shuffle_deck" if str(eff.kind) == "shuffle_deck" else "return_deck"
    return _targeted(eff, spec, ctx, action=action)


# ══════════════════════════════════════════════════════════════════════
#  片段：无效化
# ══════════════════════════════════════════════════════════════════════
def frag_negate(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """「那个发动无效并破坏」／「那个效果无效化」（连锁时点）。

    官方分两族，卡文差别在「才能发动」四个字：

    * **反击陷阱** / 「…时，那个发动无效并破坏」（没有「才能发动」）
      → ``EFFECT_TYPE_QUICK_F``（必须发动）；
    * 「…时，…才能发动。那个发动无效并破坏」→ 带代价的**可选诱发**
      ``EFFECT_TYPE_FIELD+EFFECT_TYPE_TRIGGER_O`` + ``EFFECT_FLAG_DELAY``。

    一律写成 QUICK_F 会让「才能发动」的效果变成强制发动（历史缺陷）。
    """
    full = str(eff.kind) == "negate"
    cat = "CATEGORY_NEGATE+CATEGORY_DESTROY" if full else "CATEGORY_NEGATE"
    v, lines = _begin(ctx, eff, category=cat, targeting=False)
    forced = _truthy(_param(eff, "quick_f", False), default=False)
    counter_trap = (str(spec.frame) == "trap"
                    and str(spec.trap_kind) == "counter")
    if forced or counter_trap:
        lines = [ln for ln in lines
                 if not ln.endswith(":SetRange(" + _range_loc(ctx, eff) + ")")]
        for i, ln in enumerate(lines):
            if ln.startswith(f"{v}:SetType("):
                lines[i] = f"{v}:SetType(EFFECT_TYPE_QUICK_F)"
        if not any(ln.startswith(f"{v}:SetProperty(") for ln in lines):
            lines.append(f"{v}:SetProperty(EFFECT_FLAG_DAMAGE_STEP"
                         f"+EFFECT_FLAG_DAMAGE_CAL)")
        else:
            for i, ln in enumerate(lines):
                if ln.startswith(f"{v}:SetProperty(") \
                        and "EFFECT_FLAG_DAMAGE_STEP" not in ln:
                    lines[i] = ln[:-1] + "+EFFECT_FLAG_DAMAGE_STEP" \
                        + "+EFFECT_FLAG_DAMAGE_CAL)"
    if not any(ln.startswith(f"{v}:SetCode(") for ln in lines):
        lines.append(f"{v}:SetCode(EVENT_CHAINING)")
    con, op = ctx.name("con"), ctx.name("op")
    body = _condition_lines(eff) or ["return ep~=tp"]
    ctx.add_fn(con, "e,tp,eg,ep,ev,re,r,rp", *body)
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               *(["if Duel.NegateActivation(ev) and re:GetHandler():IsRelateToEffect(re) then",
                  f"{TAB}Duel.Destroy(eg,REASON_EFFECT)",
                  "end"] if full else ["Duel.NegateEffect(ev)"]))
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=con, operation=op)
    ctx.note("negate 的条件函数只判断「发动的不是自己」（怪兽效果类时点会额外认 "
             "re:IsMonsterEffect()）；属性/字段/卡种那类限定请人工补写")
    return _block(ctx, lines, eff)


def frag_negate_card(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """「那张卡的效果直到回合结束时无效」—— 给场上的对象挂无效化效果。

    官方写法是给对象注册 ``EFFECT_DISABLE`` + ``EFFECT_DISABLE_EFFECT``
    （前者管它自己激活的效果，后者管它在场上已生效的效果），并按卡文时限
    ``SetReset``；与 :func:`frag_negate`（无效连锁上的一次发动）是两回事。
    """
    v, lines = _begin(ctx, eff, category="CATEGORY_NEGATE", targeting=True)
    _loc, loc_self, loc_opp = _target_zones(eff)
    mask = _zone_mask(loc_self, loc_opp)
    fil, _tail = _make_filter(ctx, eff, card_type="", faceup=True)
    lo, hi = _count(eff, 1)
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk,chkc",
               f"if chkc then return chkc:IsOnField() and chkc:IsFaceup() end",
               f"if chk==0 then return Duel.IsExistingTarget({fil},tp,"
               f"{loc_self},{loc_opp},1,nil) end",
               "Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_FACEUP)",
               f"local g=Duel.SelectTarget(tp,{fil},tp,{loc_self},{loc_opp},"
               f"{lo},{hi},nil)",
               "Duel.SetOperationInfo(0,CATEGORY_NEGATE,g,1,0,0)")
    until = _truthy(_param(eff, "until_end_turn", True), default=True)
    reset = ("RESET_EVENT+RESETS_STANDARD+RESET_PHASE+PHASE_END" if until
             else "RESET_EVENT+RESETS_STANDARD")
    body = ["local tc=Duel.GetFirstTarget()",
            "if tc and tc:IsFaceup() and tc:IsRelateToEffect(e) then"]
    for name, code in (("e1", "EFFECT_DISABLE"), ("e2", "EFFECT_DISABLE_EFFECT")):
        body += [
            f"{TAB}local {name}=Effect.CreateEffect(e:GetHandler())",
            f"{TAB}{TAB}{name}:SetType(EFFECT_TYPE_SINGLE)",
            f"{TAB}{TAB}{name}:SetCode({code})",
            f"{TAB}{TAB}{name}:SetReset({reset})",
            f"{TAB}{TAB}tc:RegisterEffect({name})",
        ]
    body.append("end")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp", *body)
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    if not until:
        ctx.note("negate_card 未声明时限，已按「离场即失效」生成"
                 "（卡文写「直到回合结束时无效」请设 params['until_end_turn']=True）")
    ctx.note(f"negate_card 的作用区域按对象取 {mask}；"
             f"若只想无效怪兽效果请改挂 EFFECT_DISABLE+MONSTER 限定")
    return _block(ctx, lines, eff)


# ══════════════════════════════════════════════════════════════════════
#  片段：数值 / 表示形式 / 控制权 / 指示物 / LP
# ══════════════════════════════════════════════════════════════════════
_STAT_CODE: dict[str, tuple] = {
    "gain_atk": ("EFFECT_UPDATE_ATTACK", 1, "CATEGORY_ATKCHANGE"),
    "lose_atk": ("EFFECT_UPDATE_ATTACK", -1, "CATEGORY_ATKCHANGE"),
    "gain_def": ("EFFECT_UPDATE_DEFENSE", 1, "CATEGORY_DEFCHANGE"),
    "lose_def": ("EFFECT_UPDATE_DEFENSE", -1, "CATEGORY_DEFCHANGE"),
    "set_atk": ("EFFECT_SET_ATTACK", 0, "CATEGORY_ATKCHANGE"),
    "set_def": ("EFFECT_SET_DEFENSE", 0, "CATEGORY_DEFCHANGE"),
}


def frag_stat_change(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """改变对象怪兽的攻/守（一次性效果，通常到回合结束失效）。"""
    conf = _STAT_CODE.get(str(eff.kind))
    if conf is None:
        return degrade(eff, ctx, f"未知的数值种类 {eff.kind}")
    code, sign, cat = conf
    raw = _value(eff, "value", "atk", "def", "n", default=0)
    v = abs(int(raw)) * (sign if sign else 1)
    value_expr = str(v)
    until = _truthy(_param(eff, "until_end_turn", False), default=False)
    # 时限：写了「直到回合结束为止」→ 只按回合结束复位；否则离场 + 回合结束双保险
    reset = ("RESET_PHASE+PHASE_END" if until
             else "RESET_EVENT+RESET_PHASE+PHASE_END")
    v_, lines = _begin(ctx, eff, category=cat, targeting=True)
    fil, ftail = _make_filter(ctx, eff, able="c:IsFaceup()",
                              card_type=str(_param(eff, "card_type", "")) or "monster",
                              faceup=False)
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk,chkc",
               "if chkc then return chkc:IsLocation(LOCATION_MZONE) and chkc:IsFaceup() end",
               f"if chk==0 then return Duel.IsExistingTarget({fil},tp,"
               f"LOCATION_MZONE,LOCATION_MZONE,1,nil) end",
               "Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TARGET)",
               f"local g=Duel.SelectTarget(tp,{fil},tp,LOCATION_MZONE,LOCATION_MZONE,"
               f"{_count(eff)[0]},{_count(eff)[1]},nil)",
               f"Duel.SetOperationInfo(0,{cat},g,#g,0,0)")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               "local tc=Duel.GetFirstTarget()",
               "if tc and tc:IsFaceup() and tc:IsRelateToEffect(e) then",
               f"{TAB}local e1=Effect.CreateEffect(e:GetHandler())",
               f"{TAB}{TAB}e1:SetType(EFFECT_TYPE_SINGLE)",
               f"{TAB}{TAB}e1:SetCode({code})",
               f"{TAB}{TAB}e1:SetValue({value_expr})",
               f"{TAB}{TAB}e1:SetReset({reset})",
               f"{TAB}{TAB}tc:RegisterEffect(e1)",
               "end")
    lines += _finish(ctx, v_, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    if not until:
        ctx.note("stat_change 没有时限信息，默认给「离场 + 回合结束」双重失效"
                 "（卡文若写「直到回合结束为止」请设 params['until_end_turn']=True）")
    return _block(ctx, lines, eff)


def frag_change_position(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """表示形式变更（默认改成表侧攻击表示）。"""
    pos = str(_param(eff, "position", "") or "")
    pos_lua = {"defense": "POS_FACEUP_DEFENSE", "attack": "POS_FACEUP_ATTACK",
               "face_down": "POS_FACEDOWN_DEFENSE"}.get(pos, "POS_FACEUP_ATTACK")
    v, lines = _begin(ctx, eff, category="CATEGORY_POSITION", targeting=True)
    loc_self, loc_opp = _target_zones(eff)[1], _target_zones(eff)[2]
    fil = ctx.name("fil")
    ctx.add_fn(fil, "c", "return c:IsFaceup()")
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk,chkc",
               f"if chkc then return chkc:IsLocation({_zone_mask(loc_self, loc_opp)}) and {fil}(chkc) end",
               f"if chk==0 then return Duel.IsExistingTarget({fil},tp,{loc_self},{loc_opp},"
               f"1,nil) end",
               "Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_FACEUP)",
               f"local g=Duel.SelectTarget(tp,{fil},tp,{loc_self},{loc_opp},"
               f"{_count(eff)[0]},{_count(eff)[1]},nil)",
               "Duel.SetOperationInfo(0,CATEGORY_POSITION,g,#g,0,0)")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               "local tc=Duel.GetFirstTarget()",
               "if tc and tc:IsRelateToEffect(e) then",
               f"{TAB}Duel.ChangePosition(tc,{pos_lua})",
               "end")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    ctx.note("change_position 按卡文模板生成「改成表侧攻击表示」，"
             "要守备/里侧请设 params['position']")
    return _block(ctx, lines, eff)


def frag_take_control(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """得到对象怪兽的控制权。"""
    until = _truthy(_param(eff, "until_end_turn", True), default=True)
    v, lines = _begin(ctx, eff, category="CATEGORY_CONTROL", targeting=True)
    fil = ctx.name("fil")
    ctx.add_fn(fil, "c", "return c:IsControler(1-Duel.GetTurnPlayer()) "
                         "and c:IsFaceup() and c:IsAbleToChangeControler()")
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk,chkc",
               f"if chkc then return chkc:IsLocation(LOCATION_MZONE) and {fil}(chkc) end",
               f"if chk==0 then return Duel.IsExistingTarget({fil},tp,LOCATION_MZONE,"
               f"LOCATION_MZONE,1,nil) end",
               "Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TARGET)",
               f"local g=Duel.SelectTarget(tp,{fil},tp,LOCATION_MZONE,LOCATION_MZONE,"
               f"{_count(eff)[0]},{_count(eff)[1]},nil)",
               "Duel.SetOperationInfo(0,CATEGORY_CONTROL,g,#g,0,0)")
    reason = "REASON_EFFECT+REASON_TEMPORARY" if until else "REASON_EFFECT"
    op_body = ["local tc=Duel.GetFirstTarget()",
               "if tc and tc:IsRelateToEffect(e) then",
               f"{TAB}Duel.GetControl(tc,tp,{reason},0)"]
    op_body.append("end")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp", *op_body)
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    ctx.note("take_control 生成最小实现：临时得到控制权用 REASON_TEMPORARY；"
             "「回合结束时归还」的自动复位官方多为手写，请人工复核")
    return _block(ctx, lines, eff)


def frag_counter(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """放置指示物。"""
    ctr = str(_param(eff, "counter", "") or "").strip()
    if not ctr:
        return degrade(eff, ctx, "指示物种类（params['counter']）缺失")
    if API.is_known(ctr):
        ctr_lua = ctr
    elif re.fullmatch(r"0[xX][0-9a-fA-F]+", ctr):
        ctr_lua = hex(int(ctr, 16))
    else:
        return degrade(eff, ctx, f"指示物「{ctr}」既不是已知常量也不是十六进制字面量")
    n = int(_param(eff, "count", 0) or _count(eff)[0] or 1)
    v, lines = _begin(ctx, eff, category="CATEGORY_COUNTER", targeting=True)
    fil = ctx.name("fil")
    ctx.add_fn(fil, "c", f"return c:IsFaceup() and c:IsCanAddCounter({ctr_lua},{n})")
    tg, op = ctx.name("tg"), ctx.name("op")
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk,chkc",
               f"if chkc then return chkc:IsLocation(LOCATION_MZONE) and {fil}(chkc) end",
               f"if chk==0 then return Duel.IsExistingTarget({fil},tp,LOCATION_MZONE,"
               f"LOCATION_MZONE,1,nil) end",
               "Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TARGET)",
               f"local g=Duel.SelectTarget(tp,{fil},tp,LOCATION_MZONE,LOCATION_MZONE,"
               f"{_count(eff)[0]},{_count(eff)[1]},nil)",
               f"Duel.SetOperationInfo(0,CATEGORY_COUNTER,g,#g,0,0)")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               "local tc=Duel.GetFirstTarget()",
               "if tc and tc:IsRelateToEffect(e) and tc:IsFaceup() then",
               f"{TAB}tc:AddCounter({ctr_lua},{n})",
               "end")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    ctx.note(f"指示物 {ctr_lua} 需要在 strings.conf 里补 !counter 行才能显示名字")
    return _block(ctx, lines, eff)


def frag_lp(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """给与对方伤害 / 自己回复 LP。"""
    damage = str(eff.kind) == "lp_damage"
    v0 = abs(int(_value(eff, "value", "damage", "recover", "n", default=0)))
    cat = "CATEGORY_DAMAGE" if damage else "CATEGORY_RECOVER"
    if not v0:
        return degrade(eff, ctx, "伤害/回复数值（params['value']）缺失")
    v, lines = _begin(ctx, eff, category=cat, targeting=False)
    tg, op = ctx.name("tg"), ctx.name("op")
    who = "1-tp" if damage else "tp"
    ctx.add_fn(tg, "e,tp,eg,ep,ev,re,r,rp,chk",
               "if chk==0 then return true end",
               f"Duel.SetOperationInfo(0,{cat},{v0},0,{who})")
    ctx.add_fn(op, "e,tp,eg,ep,ev,re,r,rp",
               f"Duel.{'Damage' if damage else 'Recover'}({who},{v0},REASON_EFFECT)")
    lines += _finish(ctx, v, cost=_cost_fn(ctx, eff), con=_add_condition(ctx, eff),
                     target=tg, operation=op)
    return _block(ctx, lines, eff)


# ══════════════════════════════════════════════════════════════════════
#  片段：永续 / 抗性（不入连锁）
# ══════════════════════════════════════════════════════════════════════
#: kind → ``(EFFECT_CODE, SetValue, 是否只作用于本卡)``
_STATIC_TABLE: dict[str, tuple] = {
    "direct_attack": ("EFFECT_DIRECT_ATTACK", "1", True),
    "piercing": ("EFFECT_PIERCE", "1", True),
    "cannot_attack": ("EFFECT_CANNOT_ATTACK", "1", True),
    "cannot_be_destroyed": ("EFFECT_INDESTRUCTABLE_EFFECT", "1", True),
    "cannot_be_targeted": ("EFFECT_CANNOT_BE_EFFECT_TARGET", "aux.TRUE", True),
    "unaffected": ("EFFECT_IMMUNE_EFFECT", "s.{n}efct", True),
    "cannot_activate": ("EFFECT_CANNOT_ACTIVATE", "aux.TRUE", False),
}


def frag_static(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """永续/抗性类：注册一个不进入连锁的静态效果。"""
    kind_key = str(eff.kind)
    v = f"e{ctx.slot}"
    lines: list[str] = []
    if kind_key == "continuous_gain_atk":
        num = int(_value(eff, "value", "atk", "n", default=0))
        if not num:
            return degrade(eff, ctx, "continuous_gain_atk 缺少数值 params['value']")
        loc_self, loc_opp = _target_zones(eff)[1], _target_zones(eff)[2]
        card_type = str(_param(eff, "card_type", "")) or "monster"
        lines = [f"local {v}=Effect.CreateEffect(c)",
                 f"{v}:SetType(EFFECT_TYPE_FIELD)",
                 f"{v}:SetCode(EFFECT_UPDATE_ATTACK)",
                 f"{v}:SetRange(LOCATION_MZONE)",
                 f"{v}:SetTargetRange({loc_self},{loc_opp})"]
        fil, ftail = _make_filter(ctx, eff, card_type=card_type,
                                  able="c:IsFaceup()", faceup=False)
        lines.append(f"{v}:SetValue({num})")
        lines.append(f"{v}:SetLabel(1)")
        cond = ctx.name("con")
        ctx.add_fn(cond, "e,tp", "return true")
        lines.append(f"{v}:SetCondition({cond})")
        ctx.note("continuous_gain_atk 的加成对象用 SetTargetRange 圈定区域，"
                 f"过滤条件见 {fil}；如需「只要这张卡在场」之外的条件请人工补写")
        lines.append(f"c:RegisterEffect({v})")
        return _block(ctx, lines, eff)
    conf = _STATIC_TABLE.get(kind_key)
    if conf is None:
        return degrade(eff, ctx, f"没有静态效果映射：{kind_key}")
    code, value, self_only = conf
    if "{n}" in value:
        fname = ctx.name("efct")
        ctx.add_fn(fname, "e,te",
                   "return te:GetHandler():IsControler(e:GetHandlerPlayer())")
        value = fname
    lines = [f"local {v}=Effect.CreateEffect(c)"]
    lines.append(f"{v}:SetType(EFFECT_TYPE_SINGLE)")
    lines.append(f"{v}:SetCode({code})")
    if self_only:
        lines.append(f"{v}:SetProperty(EFFECT_FLAG_SINGLE_RANGE)")
        lines.append(f"{v}:SetRange({_range_loc(ctx, eff)})")
    lines.append(f"{v}:SetValue({value})")
    con = _add_condition(ctx, eff)
    if con:
        lines.append(f"{v}:SetCondition({con})")
    lines.append(f"c:RegisterEffect({v})")
    return _block(ctx, lines, eff)


def frag_rule_text(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """效果外文本 / 召唤手续：**不是效果**，不能注册成 ``Effect``。

    官方用 ``utility.lua`` 里的 ``Card.AddCannotBeSpecialSummoned`` 等函数给卡打状态
    （这些不是效果，因此不会被「无效化」）。
    """
    key = str(eff.kind)
    if key == "cannot_special_summon":
        _use("Card.AddCannotBeSpecialSummoned")
        return (f"{TAB}--规则文本（不是效果，不可被无效）：这张卡不能特殊召唤\n"
                f"{TAB}Card.AddCannotBeSpecialSummoned(c)")
    if key == "cannot_normal_summon":
        _use("Card.AddCannotBeNormalSummoned")
        return (f"{TAB}--规则文本：这张卡不能通常召唤\n"
                f"{TAB}Card.AddCannotBeNormalSummoned(c)")
    if key == "must_first_ssummon":
        procs = {"fusion": "Card.AddMustFirstBeFusionSummoned",
                 "synchro": "Card.AddMustFirstBeSynchroSummoned",
                 "xyz": "Card.AddMustFirstBeXyzSummoned",
                 "link": "Card.AddMustFirstBeLinkSummoned",
                 "ritual": "Card.AddMustFirstBeRitualSummoned"}
        fn = procs.get(str(spec.frame_def.base), "")
        if not fn:
            return degrade(eff, ctx, "无法从卡种判定「必须先怎样特殊召唤」")
        _use(fn)
        _use("c:EnableReviveLimit")
        return (f"{TAB}--规则文本：这张卡不能通常召唤，必须先以卡的效果特殊召唤\n"
                f"{TAB}c:EnableReviveLimit()\n{TAB}{fn}(c)")
    return degrade(eff, ctx, f"未登记的规则文本种类 {key}")


def frag_name_alias(eff: EffectSpec, spec: CardSpec, ctx: LuaCtx) -> str:
    """卡名当作 X 使用 / 也当作某字段卡使用。"""
    key = str(eff.kind)
    p = eff.params or {}
    if key == "copy_name":
        name = str(p.get("name") or "").strip()
        if not name:
            return degrade(eff, ctx, "copy_name 缺少 params['name']")
        ctx.note(f"卡名当作「{name}」需要该卡的卡号（DIY 卡没有全局卡号表），"
                 "已写入 listed_names 占位与注释，请人工补卡号")
        return (f"{TAB}--卡名当作「{name}」使用（EFFECT_ADD_CODE 的取值是卡号）\n"
                f"{TAB}s.listed_names={{id}}  -- TODO: 换成「{name}」的卡号\n"
                f"{TAB}local e{ctx.slot}=Effect.CreateEffect(c)\n"
                f"{TAB}e{ctx.slot}:SetType(EFFECT_TYPE_SINGLE)\n"
                f"{TAB}e{ctx.slot}:SetCode(EFFECT_CHANGE_CODE)\n"
                f"{TAB}e{ctx.slot}:SetValue(id)  -- TODO: 换成「{name}」的卡号\n"
                f"{TAB}c:RegisterEffect(e{ctx.slot})")
    arch = str(p.get("archetype") or spec.archetype or "").strip()
    if not arch or not ctx.setcodes:
        return degrade(eff, ctx, "treat_as_card 需要目标字段名与本卡的 setcode")
    _use("Card.AddSetcodesRule")
    return (f"{TAB}--也当作「{arch}」卡使用（把本卡 setcode 追加到字段）\n"
            f"{TAB}Card.AddSetcodesRule(c,0,{ctx.setcodes[0]})")


# ══════════════════════════════════════════════════════════════════════
#  片段注册表（键 = effects.EffectKind.lua_fragment）
# ══════════════════════════════════════════════════════════════════════
FRAGMENTS: dict[str, Callable] = {
    "frag_to_hand": frag_to_hand,
    "frag_special_summon": frag_special_summon,
    "frag_special_summon_token": frag_special_summon_token,
    "frag_destroy": frag_destroy,
    "frag_destroy_all": frag_destroy_all,
    "frag_banish": frag_banish,
    "frag_send_grave": frag_send_grave,
    "frag_return_hand": frag_return_hand,
    "frag_return_deck": frag_return_deck,
    "frag_set": frag_set,
    "frag_draw": frag_draw,
    "frag_mill": frag_mill,
    "frag_excavate": frag_excavate,
    "frag_discard_opponent": frag_discard_opponent,
    "frag_negate": frag_negate,
    "frag_negate_card": frag_negate_card,
    "frag_stat_change": frag_stat_change,
    "frag_change_position": frag_change_position,
    "frag_take_control": frag_take_control,
    "frag_counter": frag_counter,
    "frag_lp": frag_lp,
    "frag_static": frag_static,
    "frag_rule_text": frag_rule_text,
    "frag_name_alias": frag_name_alias,
}


def fragment(kind_key: str) -> Optional[Callable]:
    """按 ``EffectKind.lua_fragment`` 取片段函数；没有则 ``None``（由 emit 降级）。"""
    k = effect_kind(kind_key)
    if k is None or not k.lua_fragment:
        return None
    return FRAGMENTS.get(k.lua_fragment)


#: 这些片段注册的是**不入连锁的静态效果**（攻守提升、穿防、不能被无效…），
#: 官方不给它们 cdb ``str`` 描述槽 —— 占槽会让 ``spec.strings`` 比脚本里实际引用的
#: ``aux.Stringid`` 多出一条条没人用的文字（emit 的槽位分配必须知道这件事）。
#: 注意：``copy_name`` / ``treat_as_card`` 也是静态的（卡名当作 / 也当作字段卡使用）。
NO_DESCRIPTION_FRAGMENTS: frozenset = frozenset({
    "frag_static", "frag_name_alias", "frag_rule_text",
})


# ══════════════════════════════════════════════════════════════════════
#  召唤流程 / 卡种骨架（由 emit 调用，不属于单条效果）
# ══════════════════════════════════════════════════════════════════════
#: 「卡种」素材的旧写法 → ``_type_lua`` 的键
_TYPE_PART_ALIASES = {
    "效果": "effect", "效果怪兽": "effect",
    "通常": "normal", "通常怪兽": "normal",
    "仪式": "ritual", "仪式怪兽": "ritual",
    "融合": "fusion", "融合怪兽": "fusion",
    "同步": "synchro", "同步怪兽": "synchro", "同调怪兽": "synchro",
    "超量": "xyz", "超量怪兽": "xyz",
    "连接": "link", "连接怪兽": "link",
    "衍生物": "token", "灵魂": "spirit", "联合": "union",
    "二重": "gemini", "反转": "flip", "卡通": "toon",
}


def _cond_predicate(spec: CardSpec, part: MaterialPart) -> tuple[str, str]:
    """**单个**筛选条件 → Lua 谓词；解析不了返回 ``("", 原因)``。"""
    kind = str(part.kind or "any")
    value = part.value
    if kind == "any":
        return "", ""
    if kind == "name":
        try:
            code = int(part.code or 0)
        except Exception:
            code = 0
        if not code:
            return "", "缺少卡号（kind=name 需填 code）"
        return f"c:IsCode({code})", ""
    if kind == "archetype":
        code = S.resolve_setcode(spec, part)
        if not code:
            return "", "缺少字段码（可填本卡 setcode，或为素材字段指定 setcode）"
        return f"c:IsSetCard({code})", ""
    if kind == "race":
        vals = value if isinstance(value, (list, tuple)) else [value]
        exprs = [f"c:IsRace({_race_lua(v)})" for v in vals if _race_lua(v)]
        if not exprs:
            return "", "种族无效"
        return ("(" + " or ".join(exprs) + ")") if len(exprs) > 1 else exprs[0], ""
    if kind == "attribute":
        vals = value if isinstance(value, (list, tuple)) else [value]
        exprs = [f"c:IsAttribute({_attr_lua(v)})" for v in vals if _attr_lua(v)]
        if not exprs:
            return "", "属性无效"
        return ("(" + " or ".join(exprs) + ")") if len(exprs) > 1 else exprs[0], ""
    if kind == "type":
        key = str(value or "").strip().lower()
        key = _TYPE_PART_ALIASES.get(key, key)
        t = _type_lua(key)
        if not t:
            return "", "卡种无效"
        return f"c:IsType({t})", ""
    if kind == "level":
        try:
            return f"c:IsLevel({int(value)})", ""
        except Exception:
            return "", "等级无效"
    if kind == "rank":
        try:
            return f"c:IsRank({int(value)})", ""
        except Exception:
            return "", "阶级无效"
    return "", f"未知素材种类「{kind}」"


def _material_predicates(spec: CardSpec, part: MaterialPart) -> tuple[list, str]:
    """素材段 → Lua 谓词列表；解析不了时返回 ``([], 原因)``。

    一段里的多个筛选（字段＋种族那类）在**同一个谓词**里 ``and`` 起来 ——
    官方语义是「同时满足的 1 只怪兽」，拆成两个过滤函数会让素材数量翻倍。
    """
    preds: list[str] = []
    for c in part.conditions():
        expr, err = _cond_predicate(spec, c)
        if err:
            return [], f"「{c.value or c.kind}」{err}"
        if expr:
            preds.append(expr)
    if str(part.tuner or "") == "tuner":
        preds.append("c:IsType(TYPE_TUNER)")
    elif str(part.tuner or "") == "non_tuner":
        preds.append("not c:IsType(TYPE_TUNER)")
    if part.exclude_token:
        preds.append("not c:IsType(TYPE_TOKEN)")
    if part.exclude_link:
        preds.append("not c:IsType(TYPE_LINK)")
    if part.include_link:
        # 「包含连接怪兽的…」是**整组素材**的要求，交给 specialchk（见
        # _link_procedure），单个素材谓词里不加，否则每张都必须是连接怪兽。
        pass
    return preds, ""



def _material_filter(ctx: LuaCtx, spec: CardSpec, part: MaterialPart,
                     idx: int) -> tuple[Optional[str], str]:
    """返回 ``(过滤函数名, 错误原因)``。

    过滤函数名 ``None`` 表示「无附加条件」（任意怪兽）；错误原因非空表示
    该素材无法确定性映射，调用方必须降级成注释而不是放行任意素材。
    """
    preds, err = _material_predicates(spec, part)
    if err:
        return None, err
    if not preds:
        return None, ""
    fname = f"s.mat{ctx.slot}_{idx}"
    ctx.add_fn(fname, "c", "return " + " and ".join(preds))
    return fname, ""


def _part_counts(part: MaterialPart) -> tuple[int, int]:
    """``(最小, 最大)``；最大 0 = 恰好等于最小。"""
    lo = part.count_lo
    hi = part.count_hi
    return lo, hi


def _fusion_procedure(ctx: LuaCtx, spec: CardSpec, s: SummonSpec) -> list:
    out: list[str] = []
    parts = s.parts()
    out.append(f"{TAB}--融合素材条件")
    if not parts:
        out.append(f"{TAB}-- [CardForge] 融合素材条件为空：请在「召唤条件」里填写素材，"
                   f"未生成 Fusion.AddProcMix")
        ctx.note("融合素材为空，未生成 Fusion.AddProcMix")
        return out
    exprs: list[tuple[MaterialPart, str]] = []
    for i, p in enumerate(parts):
        name, err = _material_filter(ctx, spec, p, i)
        if err:
            out.append(f"{TAB}-- [CardForge] 素材「{p.value or p.kind}」{err}，"
                       f"未生成 Fusion.AddProcMix；需人工补写")
            ctx.note(f"融合素材「{p.value or p.kind}」{err}，脚本未生成素材过滤")
            return out
        exprs.append((p, name or "aux.TRUE"))
    ranged = [(p, e) for p, e in exprs if p.count_hi]
    _use("Fusion.AddProcMix")
    if len(ranged) == 1:
        p, expr = ranged[0]
        lo, hi = _part_counts(p)
        others = [e for q, e in exprs if q is not p]
        tail = ("," + ",".join(others)) if others else ""
        out.append(f"{TAB}Fusion.AddProcMixRep(c,true,true,{expr},{lo},{hi}{tail})")
    elif len(ranged) > 1:
        _use("Fusion.AddProcMixRepUnfix")
        entries = []
        for p, e in exprs:
            lo, hi = _part_counts(p)
            # Unfix 的每个参数都必须是 {filter/code, min, max} 表；
            # 固定数量也写成 min=max，不能混入裸函数（f[1] 会报 index 错误）。
            entries.append("{" + f"{e},{lo},{hi or lo}" + "}")
        out.append(f"{TAB}Fusion.AddProcMixRepUnfix(c,true,true,{','.join(entries)})")
    else:
        flat: list[str] = []
        for p, e in exprs:
            lo, _hi = _part_counts(p)
            flat.extend([e] * max(1, lo))
        out.append(f"{TAB}Fusion.AddProcMix(c,true,true,{','.join(flat)})")
    out.append(f"{TAB}c:EnableReviveLimit()")
    return out


def _synchro_procedure(ctx: LuaCtx, spec: CardSpec, s: SummonSpec) -> list:
    out: list[str] = []
    parts = s.parts()
    out.append(f"{TAB}--同步素材条件：协调段 + 协调以外段")
    if not parts:
        out.append(f"{TAB}-- [CardForge] 同步素材条件为空：请在「召唤条件」里填写素材，"
                   f"未生成 Synchro.AddProcedure")
        ctx.note("同步素材为空，未生成 Synchro.AddProcedure")
        return out
    tuner, non = S.synchro_roles(parts)
    if tuner is None or non is None:
        out.append(f"{TAB}-- [CardForge] 同步素材需要「协调」与「协调以外」两段，"
                   f"当前不足，未生成 Synchro.AddProcedure")
        ctx.note("同步素材角色不完整，脚本未生成召唤流程")
        return out
    f1, err1 = _material_filter(ctx, spec, tuner, 0)
    f2, err2 = _material_filter(ctx, spec, non, 1)
    if err1 or err2:
        why = err1 or err2
        out.append(f"{TAB}-- [CardForge] 同步素材{why}，未生成 Synchro.AddProcedure；"
                   f"需人工补写")
        ctx.note(f"同步素材{why}，脚本未生成召唤流程")
        return out
    lo1, hi1 = _part_counts(tuner)
    lo2, hi2 = _part_counts(non)
    max1 = hi1 or lo1
    max2 = hi2 or lo2
    f2expr = f"Synchro.NonTuner({f2})" if f2 else "Synchro.NonTuner(nil)"
    _use("Synchro.AddProcedure")
    _use("Synchro.NonTuner")
    out.append(f"{TAB}Synchro.AddProcedure(c,{f1 or 'nil'},{lo1},{max1},"
               f"{f2expr},{lo2},{max2})")
    out.append(f"{TAB}c:EnableReviveLimit()")
    return out


def _xyz_procedure(ctx: LuaCtx, spec: CardSpec, s: SummonSpec) -> list:
    out: list[str] = []
    parts = s.parts()
    out.append(f"{TAB}--超量素材条件")
    if not parts:
        out.append(f"{TAB}-- [CardForge] 超量素材条件为空：请在「召唤条件」里填写素材，"
                   f"未生成 Xyz.AddProcedure")
        ctx.note("超量素材为空，未生成 Xyz.AddProcedure")
        return out
    if len(parts) > 1:
        out.append(f"{TAB}-- [CardForge] 超量素材只支持一组筛选条件；当前有 "
                   f"{len(parts)} 段，未生成 Xyz.AddProcedure")
        ctx.note("超量素材有多段，脚本未生成召唤流程（请合并筛选条件）")
        return out
    p = parts[0]
    f, err = _material_filter(ctx, spec, p, 0)
    if err:
        out.append(f"{TAB}-- [CardForge] 超量素材{err}，未生成 Xyz.AddProcedure；"
                   f"需人工补写")
        ctx.note(f"超量素材{err}，脚本未生成召唤流程")
        return out
    lo, hi = _part_counts(p)
    lv = spec.effective_level
    if str(p.kind or "") == "level":
        lv = int(p.value or lv)
    elif str(p.kind or "") in ("rank", "name"):
        lv = None
    maxct = "Xyz.InfiniteMats" if hi >= 99 else (hi or None)
    _use("Xyz.AddProcedure")
    if lv is None:
        lv_expr = "nil"
    else:
        lv_expr = str(int(lv or 0)) if lv else "nil"
    if maxct:
        if maxct == "Xyz.InfiniteMats":
            _use("Xyz.InfiniteMats")
        call = f"Xyz.AddProcedure(c,{f or 'nil'},{lv_expr},{lo},nil,nil,{maxct})"
    else:
        call = f"Xyz.AddProcedure(c,{f or 'nil'},{lv_expr},{lo})"
    out.append(f"{TAB}{call}")
    out.append(f"{TAB}c:EnableReviveLimit()")
    return out


def _link_procedure(ctx: LuaCtx, spec: CardSpec, s: SummonSpec) -> list:
    out: list[str] = []
    parts = s.parts()
    out.append(f"{TAB}--连接素材条件")
    if not parts:
        out.append(f"{TAB}-- [CardForge] 连接素材条件为空：请在「召唤条件」里填写素材，"
                   f"未生成 Link.AddProcedure")
        ctx.note("连接素材为空，未生成 Link.AddProcedure")
        return out
    if len(parts) > 1:
        out.append(f"{TAB}-- [CardForge] 连接素材只支持一组筛选条件；当前有 "
                   f"{len(parts)} 段，未生成 Link.AddProcedure")
        ctx.note("连接素材有多段，脚本未生成召唤流程（请合并筛选条件）")
        return out
    p = parts[0]
    f, err = _material_filter(ctx, spec, p, 0)
    if err:
        out.append(f"{TAB}-- [CardForge] 连接素材{err}，未生成 Link.AddProcedure；"
                   f"需人工补写")
        ctx.note(f"连接素材{err}，脚本未生成召唤流程")
        return out
    lo, hi = _part_counts(p)
    rating = int(spec.effective_level or 0)
    maxc = hi or lo
    if hi >= 99:
        maxc = rating or lo
    if maxc < lo:
        maxc = lo
    special = ""
    if p.include_link:
        special = f"s.lchk{ctx.slot}"
        ctx.add_fn(special, "sg,lc",
                   "return sg:IsExists(Card.IsType,1,nil,TYPE_LINK)")
    _use("Link.AddProcedure")
    extra = f",{special}" if special else ""
    out.append(f"{TAB}Link.AddProcedure(c,{f or 'nil'},{lo},{maxc}{extra})")
    out.append(f"{TAB}c:EnableReviveLimit()")
    return out


#: 额外召唤方法：区域 → ``Duel.GetMatchingGroup`` 的两个区域参数
_METHOD_ZONE_LOC = {
    "mz": ("LOCATION_MZONE", "LOCATION_MZONE"),
    "field": ("LOCATION_ONFIELD", "LOCATION_ONFIELD"),
    "hand": ("LOCATION_HAND", "0"),
    "gy": ("LOCATION_GRAVE", "0"),
    "field_gy": ("LOCATION_ONFIELD|LOCATION_GRAVE", "0"),
    "hand_field": ("LOCATION_HAND|LOCATION_ONFIELD", "0"),
}
#: 额外召唤方法：处理动作 → ``(素材可用性谓词, 执行语句)``
_METHOD_ACTION_LUA = {
    "banish": ("c:IsAbleToRemoveAsCost()",
               "Duel.Remove(g,POS_FACEUP,REASON_COST|REASON_MATERIAL)"),
    "send_gy": ("c:IsAbleToGraveAsCost()",
                "Duel.SendtoGrave(g,REASON_COST|REASON_MATERIAL)"),
    "release": ("c:IsFaceup() and c:IsReleasable()",
                "Duel.Release(g,REASON_COST|REASON_MATERIAL)"),
    "return_deck": ("c:IsAbleToDeckOrExtraAsCost()",
                    "Duel.SendtoDeck(g,nil,SEQ_DECKSHUFFLE,"
                    "REASON_COST|REASON_MATERIAL)"),
    "return_hand": ("c:IsAbleToHand()",
                    "Duel.SendtoHand(g,nil,REASON_COST|REASON_MATERIAL)"),
}


def _contact_group_filter(ctx: LuaCtx, spec: CardSpec, s: SummonSpec,
                          m, idx: int) -> tuple[Optional[str], str]:
    """``Fusion.AddContactProc`` 的候选素材组过滤函数。

    条件 = 素材行里各段谓词的**或**（组只是候选集，最终由
    ``CheckFusionMaterial`` 校验所选子集确实满足召唤流程）＋ 能否作为代价处理。
    """
    parts = m.item_parts() if not m.use_materials else s.parts()
    if not parts:
        return None, "没有可用于接触召唤的素材条件（素材行为空）"
    exprs: list[str] = []
    for p in parts:
        preds, err = _material_predicates(spec, p)
        if err:
            return None, f"素材「{p.value or p.kind}」{err}"
        exprs.append("(" + " and ".join(preds) + ")" if preds else "true")
    act = _METHOD_ACTION_LUA.get(str(m.action or "banish"))
    if not act:
        return None, f"未登记的召唤方法处理动作「{m.action}」"
    group = "(" + " or ".join(exprs) + ")" if len(exprs) > 1 else exprs[0]
    body = group + " and " + act[0]
    if int(m.count_lo or 0) > 0:
        body += "   -- 数量要求（" + str(m.count_lo) + "只以上）在选择时限定"
    fname = f"s.cfil{ctx.slot}_{idx}"
    ctx.add_fn(fname, "c", "return " + body)
    return fname, ""


def _contact_lines(ctx: LuaCtx, spec: CardSpec, s: SummonSpec) -> list:
    """「以下方法」的脚本：融合卡走 ``Fusion.AddContactProc``。

    官方写法（例：青眼双爆裂龙、冰狱龙 三叉龙、E·HERO 新宇侠·接触融合）：
    ``Fusion.AddContactProc(c,组过滤,处理,sumcon,condition,SUMMON_TYPE_FUSION)``
    —— 第 6 个参数把召唤类型标成融合，这样卡文里的「用融合召唤以及以下方法」
    才能同时通过 ``aux.fuslimit`` 的检查。
    """
    out: list[str] = []
    methods = s.item_methods()
    if not methods:
        return out
    base = spec.frame_def.base
    zh = {"banish": "除外", "send_gy": "送去墓地", "release": "解放",
          "return_deck": "回到卡组", "return_hand": "回到手卡"}
    for i, m in enumerate(methods):
        label = f"{zh.get(str(m.action or 'banish'), m.action)}"
        if base != "fusion":
            out.append(f"{TAB}-- [CardForge] 额外召唤方法（{label}）"
                       f"目前只有融合卡能自动生成脚本；"
                       f"{'本卡种' if i == 0 else '第 ' + str(i + 1) + ' 条'}"
                       f"需人工补写 EFFECT_SPSUMMON_PROC")
            ctx.note(f"额外召唤方法（{label}）在 {base} 卡种上未生成脚本，"
                     f"卡文与脚本暂不一致，需人工补写")
            continue
        if (m.text_i18n or {}).get("zh_cn") and not m.use_materials \
                and not m.item_parts():
            out.append(f"{TAB}-- [CardForge] 额外召唤方法「{label}」只写了文本、"
                       f"没有结构化素材条件，未生成脚本")
            ctx.note("额外召唤方法只有文本，脚本未生成")
            continue
        fname, err = _contact_group_filter(ctx, spec, s, m, i)
        if err:
            out.append(f"{TAB}-- [CardForge] 额外召唤方法（{label}）{err}，"
                       f"未生成 Fusion.AddContactProc；需人工补写")
            ctx.note(f"额外召唤方法（{label}）{err}，脚本未生成")
            continue
        loc = _METHOD_ZONE_LOC.get(str(m.zone or "mz"), _METHOD_ZONE_LOC["mz"])
        gname = f"s.cgrp{ctx.slot}_{i}"
        opname = f"s.ctop{ctx.slot}_{i}"
        ctx.add_fn(gname, "tp",
                   f"return Duel.GetMatchingGroup({fname},tp,{loc[0]},{loc[1]},nil)")
        act = _METHOD_ACTION_LUA[str(m.action or "banish")][1]
        ctx.add_fn(opname, "g,tp,c", act)
        _use("Fusion.AddContactProc")
        out.append(f"{TAB}--额外召唤方法：把上记的卡{label}的接触召唤"
                   f"（{'不需要「融合」' if m.no_spelling else '仍按融合召唤类型结算'}）")
        out.append(f"{TAB}Fusion.AddContactProc(c,{gname},{opname},"
                   f"nil,nil,SUMMON_TYPE_FUSION)")
    return out


_LIMIT_FN = {
    "fusion": "aux.fuslimit", "synchro": "aux.synlimit", "xyz": "aux.xyzlimit",
    "link": "aux.lnklimit", "ritual": "aux.ritlimit",
}
_LOCK_CODE = {
    "fusion": "EFFECT_CANNOT_BE_FUSION_MATERIAL",
    "synchro": "EFFECT_CANNOT_BE_SYNCHRO_MATERIAL",
    "xyz": "EFFECT_CANNOT_BE_XYZ_MATERIAL",
    "link": "EFFECT_CANNOT_BE_LINK_MATERIAL",
}


def _restriction_lines(ctx: LuaCtx, spec: CardSpec, s: SummonSpec) -> list:
    """召唤限制 / 素材锁定的 Lua 注册块（与卡文一一对应）。"""
    out: list[str] = []
    if s.cannot_normal_summon:
        _use("Card.AddCannotBeNormalSummoned")
        out.append(f"{TAB}--不能通常召唤")
        out.append(f"{TAB}Card.AddCannotBeNormalSummoned(c)")
    lock_zh = {"fusion": "融合", "synchro": "同步", "xyz": "超量", "link": "连接"}
    for lock in s.cannot_be_material or []:
        code = _LOCK_CODE.get(str(lock))
        if not code:
            continue
        v = f"e_lock_{lock}"
        out += [
            f"{TAB}--不能作为{lock_zh.get(str(lock), str(lock))}素材",
            f"{TAB}local {v}=Effect.CreateEffect(c)",
            f"{TAB}{v}:SetType(EFFECT_TYPE_SINGLE)",
            f"{TAB}{v}:SetProperty(EFFECT_FLAG_CANNOT_DISABLE+EFFECT_FLAG_UNCOPYABLE)",
            f"{TAB}{v}:SetCode({code})",
            f"{TAB}{v}:SetValue(1)",
            f"{TAB}c:RegisterEffect({v})",
        ]
    if s.limit == "cannot_spsummon":
        _use("Card.AddCannotBeSpecialSummoned")
        out.append(f"{TAB}--不能特殊召唤")
        out.append(f"{TAB}Card.AddCannotBeSpecialSummoned(c)")
    elif s.limit in ("must_be", "must_be_with_materials"):
        fn = _LIMIT_FN.get(spec.frame_def.base)
        if fn:
            out += [
                f"{TAB}--召唤条件：只能用本卡种的召唤方式特殊召唤",
                f"{TAB}local e_sp=Effect.CreateEffect(c)",
                f"{TAB}e_sp:SetType(EFFECT_TYPE_SINGLE)",
                f"{TAB}e_sp:SetProperty(EFFECT_FLAG_CANNOT_DISABLE+EFFECT_FLAG_UNCOPYABLE)",
                f"{TAB}e_sp:SetCode(EFFECT_SPSUMMON_CONDITION)",
                f"{TAB}e_sp:SetValue({fn})",
                f"{TAB}c:RegisterEffect(e_sp)",
            ]
            if fn.startswith("aux.") and API.is_known(fn):
                _use(fn)
    return out


def summon_procedure_lines(ctx: LuaCtx, spec: CardSpec) -> list:
    """灵摆 / 额外卡组 / 仪式的召唤流程（**含素材条件与召唤限制**）。

    数据源是 ``spec.summon``（旧版 ``params['materials']`` 会被
    :func:`cardforge.content.summon.normalize` 迁移）。信息不足时返回
    **注释行**而不是「任意怪兽」的假流程。
    """
    out: list[str] = []
    base = spec.frame_def.base
    frame = spec.frame
    s = S.normalize(spec)
    if spec.is_pendulum:
        _use("Pendulum.AddProcedure")
        out.append(f"{TAB}--灵摆召唤流程（左右刻度编码在 cdb 的 level 字段里，脚本不用写）")
        out.append(f"{TAB}Pendulum.AddProcedure(c)")
    if frame in ("token", "skill"):
        return out
    if frame == "spell" and spec.spell_kind == "equip":
        _use("aux.AddEquipProcedure")
        out.append(f"{TAB}--装备魔法：按规则装备（装备目标条件见下面的过滤函数）")
        out.append(f"{TAB}aux.AddEquipProcedure(c,0,s.eqfil{ctx.slot})")
        return out
    if base not in ("fusion", "synchro", "xyz", "link", "ritual"):
        return out
    if s.limit == "cannot_spsummon":
        out.append(f"{TAB}-- [CardForge] 这张卡声明「不能特殊召唤」，"
                   f"本卡种的召唤流程不会生成")
        ctx.note("召唤条件声明「不能特殊召唤」，未生成召唤流程")
        out.extend(_restriction_lines(ctx, spec, s))
        return out
    if base == "fusion":
        out.extend(_fusion_procedure(ctx, spec, s))
    elif base == "synchro":
        out.extend(_synchro_procedure(ctx, spec, s))
    elif base == "xyz":
        out.extend(_xyz_procedure(ctx, spec, s))
    elif base == "link":
        out.extend(_link_procedure(ctx, spec, s))
    elif base == "ritual":
        _use("Ritual.AddProcGreater")
        out.append(f"{TAB}--仪式召唤流程：祭品等级合计不小于 {spec.effective_level}"
                   f"（签名 c,filter,lv,desc —— desc 不传，传 0 会让 Lua 当成真值"
                   f"去 SetDescription(0)）")
        out.append(f"{TAB}Ritual.AddProcGreater(c,aux.TRUE,{spec.effective_level})")
        out.append(f"{TAB}c:EnableReviveLimit()")
    out.extend(_contact_lines(ctx, spec, s))
    out.extend(_restriction_lines(ctx, spec, s))
    return out


def equip_filter_fn(ctx: LuaCtx, spec: CardSpec, eff: Optional[EffectSpec]) -> list:
    """装备魔法的装备目标过滤函数（被 :func:`summon_procedure_lines` 引用）。"""
    if spec.frame != "spell" or spec.spell_kind != "equip":
        return []
    fname = f"s.eqfil{ctx.slot}"
    parts = _filter_expr(ctx, eff.target if eff else None,
                         card_type=str(_param(eff, "card_type", "") if eff else "")
                         or "monster")
    expr = " and ".join(parts) if parts else "true"
    ctx.add_fn(fname, "c", f"return c:IsFaceup() and ({expr})")
    return []


def link_marker_lines(spec: CardSpec) -> list:
    """连接箭头 → ``LINK_MARKER_*`` 常量（引擎从 cdb 的 ``def`` 字段读箭头，
    这里额外给出常量掩码，供「被这张卡指向 / 相邻」类效果引用）。"""
    if spec.frame != "link":
        return []
    bits = int(spec.link_bits or 0)
    if not bits:
        return [f"{TAB}-- [CardForge] 连接怪兽没有连接箭头，请检查 link_markers"]
    names = [BIT_MARKER[b] for b in sorted(BIT_MARKER) if bits & b and API.is_known(BIT_MARKER[b])]
    if not names:
        return [f"{TAB}-- [CardForge] 连接箭头常量不在 API 白名单里，已跳过"]
    return [f"{TAB}--连接箭头：{'、'.join(str(m) for m in spec.link_markers)}"
            f"（供「被指向/相邻」类效果引用）",
            f"{TAB}s.link_marker_mask={'+'.join(names)}"]


def skill_skeleton_lines(ctx: LuaCtx, spec: CardSpec) -> list:
    """技能卡骨架（``proc_skill.lua`` 提供 ``Auxiliary.CanActivateSkill`` 等工具）。"""
    return [f"{TAB}--技能卡：主阶段・无连锁时才能发动（判定见 Auxiliary.CanActivateSkill）",
            f"{TAB}local e{ctx.slot}=Effect.CreateEffect(c)",
            f"{TAB}e{ctx.slot}:SetType(EFFECT_TYPE_ACTIVATE)",
            f"{TAB}e{ctx.slot}:SetCode(EVENT_FREE_CHAIN)",
            f"{TAB}e{ctx.slot}:SetProperty(EFFECT_FLAG_CANNOT_DISABLE)",
            f"{TAB}e{ctx.slot}:SetOperation(s.skill{ctx.slot}op)",
            f"{TAB}c:RegisterEffect(e{ctx.slot})",
            f"{TAB}-- [CardForge] 技能卡的对局规则改动需人工补写（参考 proc_skill.lua）"]
