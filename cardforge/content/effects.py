"""效果 DSL 注册表 —— 效果 IR（:class:`~cardforge.core.models.EffectSpec`）的**唯一词表**。

设计原则
--------
1. **``kind`` 键与 :data:`cardforge.content.psct.rules.EFFECT_TEMPLATES` 完全同名。**
   卡文（PSCT）和脚本（Lua）是同一份 IR 的两个投影；一旦键名不一致，
   「卡文写的是检索、脚本生成的是破坏」这类错配就无法被发现。
2. **句式不复制第二份。** ``text_templates`` 直接引用 ``psct.rules`` 的模板字典。
3. **注册表只描述"能不能"，不描述"怎么写 Lua"。** 具体脚本片段在
   :mod:`cardforge.content.lua.fragments`，本模块只用 ``lua_fragment`` 指向函数名；
   空字符串表示**目前没有片段**（生成器会降级成注释，绝不瞎编代码）。
4. 校验与推断都是**纯规则**的，不依赖任何模型（可降级的能力失败返回空集合）。

对外主接口（接口契约 §3.4）::

    EffectKind                      # 一条效果种类的完整描述
    EFFECT_KINDS                    # kind → EffectKind（键与 PSCT 模板同名）
    kind(key)                       # 查表，未知返回 None
    describe_all()                  # 给 UI 下拉用的精简列表
    validate_effect(eff)            # IR 自检 → list[Issue]
    infer_from_text(text)           # 卡文 → list[EffectSpec]（规则/关键词推断）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from ..core.models import (
    EFFECT_LIMITS, TRIGGERS, EffectCost, EffectSpec, EffectTarget, Issue,
)
from .psct import rules as PR

__all__ = [
    "EffectKind", "EFFECT_KINDS", "kind", "describe_all",
    "validate_effect", "infer_from_text", "PARAM_TYPES", "ZONE_KEYS",
    "FILTER_KINDS", "CONTROLLER_KEYS", "COST_KINDS",
]

#: 模板里真正属于"句式"的语言键（``rules`` 的字典还混了 risky/continuous 等元数据）
_LANG_KEYS: tuple[str, ...] = ("zh_cn", "ja", "en")

# ══════════════════════════════════════════════════════════════════════
#  取值域
# ══════════════════════════════════════════════════════════════════════
#: 参数类型（UI 据此决定输入控件；校验据此判断类型是否匹配）
PARAM_TYPES: tuple[str, ...] = ("int", "str", "bool", "list", "dict")

#: ``EffectTarget.from_zone/to_zone`` 允许的键（与 ``psct.rules.ZONE_WORDS`` 对齐）
ZONE_KEYS: tuple[str, ...] = (
    "", "DECK", "DECKTOP", "EXTRA", "HAND", "GRAVE", "REMOVED",
    "FIELD", "MZONE", "SZONE", "PZONE", "FZONE", "OVERLAY",
)

#: ``EffectTarget.filter_kind`` 允许的键
FILTER_KINDS: tuple[str, ...] = (
    "any", "archetype", "race", "attribute", "type", "level",
    "name", "monster", "card", "token", "counter_target", "linked",
)

#: ``EffectTarget.controller`` 允许的键
CONTROLLER_KEYS: tuple[str, ...] = ("self", "opponent", "both", "")

#: ``EffectCost.kind`` 允许的键（与 ``psct.rules.COST_PHRASES`` 对齐）
COST_KINDS: tuple[str, ...] = tuple(PR.COST_PHRASES.keys())

# 所有 kind 都可以出现的**通用**参数（不需要在注册表里逐个声明）。
#
# IR 契约补充说明 —— ``continuous`` 键
# -----------------------------------
# ``params["continuous"] = True`` 表示这条效果**不入连锁**（永续效果 / 装备效果 /
# 规则文本）。它是 IR 里唯一能表达「不入连锁」的字段，两个投影都读它：
#
# * 卡文侧（``psct.gen.compose``）：判定 ``①：`` 之后要不要写「才能发动」——
#   永续句式没有发动段，直接「条件 + 处理」。
# * 脚本侧（``lua.emit`` / ``lua.fragments``）：决定 Lua 的 ``SetType`` 走
#   ``EFFECT_TYPE_SINGLE`` / ``EFFECT_TYPE_FIELD`` / ``EFFECT_TYPE_EQUIP``，
#   而不是 ``EFFECT_TYPE_IGNITION`` / ``EFFECT_TYPE_TRIGGER_O``。
#   规则文本（``psct.rules.RULE_TEXT_KINDS``）更进一步：根本不生成 ``Effect``，
#   因为它不是效果，写成效果会让它变成可被「无效化」的对象。
#
# 由 :func:`infer_from_text` 从「只要…」「…为止」「不能…」这类措辞推断；
# 手写的 IR 也可以显式设置。``until_end_turn`` 同理，表达「直到…为止」的时限。
COMMON_PARAMS: tuple[str, ...] = (
    "_index",          # gen/emit 用来标记效果序号（CardSpec.effect_specs 自动写入）
    "timing",          # when | if（时点严格度）
    "targeting",       # 强制是否取对象
    "continuous",      # 不入连锁（永续/装备/规则文本）—— 见上面的 IR 契约补充说明
    "parts",           # 多段处理
    "conjunction",     # 多段处理的连接词
    "reference",       # 处理段是否用「那张卡」指代
    "reference_key",   # 指代词键
    "condition",       # 额外发动条件（dict 或 str）
    "optional",        # 「才能发动」vs「发动」
    "archetype",       # 字段名（覆盖 CardSpec.archetype）
    "archetype_i18n",  # 字段名多语言
    "desc",            # 人工指定 cdb str 文本
    "materials",       # 额外卡组召唤素材描述
    "filter_kind",     # 无 target 时的过滤类型
    "filter_value",    # 无 target 时的过滤取值
    "until_end_turn",    # 时限：直到回合结束/对方回合结束（脚本侧 → SetReset）
    "card_type",         # 卡类型限制：monster | spell | trap | spelltrap

    "count", "count_max", "n", "value",
)


# ══════════════════════════════════════════════════════════════════════
#  EffectKind
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class EffectKind:
    """一种效果种类的完整描述（卡文模板 + 脚本片段 + 参数契约）。"""

    key: str
    zh: str
    en: str
    triggers: tuple[str, ...]              # 允许的时点键（core.models.TRIGGERS）
    params: dict[str, dict]                # 参数名 → {type,required,choices,default,zh}
    target_required: bool
    cost_allowed: bool
    lua_fragment: str                      # fragments.FRAGMENTS 里的函数名
    text_templates: dict[str, str]         # lang → 句式（取自 psct.rules.EFFECT_TEMPLATES）
    #: Lua 的 CATEGORY_* 表达式字符串（``"CATEGORY_DESTROY"``）；0 = 无类别
    category_bits: "int | str" = 0

    @property
    def has_fragment(self) -> bool:
        """是否已有 Lua 片段（False 时生成器必须降级成注释）。"""
        return bool(self.lua_fragment)

    @property
    def is_continuous(self) -> bool:
        return self.key in PR.CONTINUOUS_KINDS

    @property
    def is_rule_text(self) -> bool:
        return self.key in PR.RULE_TEXT_KINDS

    @property
    def takes_target(self) -> bool:
        """按官方写法是否**取对象**（见 ``psct.rules.NON_TARGETING_KINDS``）。"""
        return (self.key not in PR.NON_TARGETING_KINDS
                and not self.is_continuous and not self.is_rule_text)

    def template(self, lang: str = "zh_cn") -> str:
        return self.text_templates.get(lang) or self.text_templates.get("zh_cn") or ""

    def allowed_params(self) -> tuple[str, ...]:
        return tuple(self.params.keys()) + COMMON_PARAMS


def _p(t: str, zh: str, *, required: bool = False,
       choices: tuple[str, ...] = (), default: Any = None) -> dict:
    """构造一个参数描述字典（契约 §3.4 的 ``params`` 值形状）。"""
    return {"type": t, "required": required, "choices": choices,
            "default": default, "zh": zh}


#: 可以作为"发动"类时点的键（起动 / 诱发 / 诱发即时）
_ACT: tuple[str, ...] = tuple(
    k for k in TRIGGERS if k not in ("CONTINUOUS", "QUICK")) + ("QUICK",)
#: 反击类（连锁时点）
_NEG: tuple[str, ...] = ("OPPONENT_ACTIVATE", "ON_ACTIVATE", "QUICK")
#: 永续/规则文本类（不入连锁，没有时点）
_CONT: tuple[str, ...] = ("CONTINUOUS", "EQUIP_RELATED")
#: 只有永续时点
_CONT_ONLY: tuple[str, ...] = ("CONTINUOUS",)

_NO_PARAMS: dict[str, dict] = {}


def _mk_int(zh: str, *, required: bool = False, default: Any = None) -> dict[str, dict]:
    return {"value": _p("int", zh, required=required, default=default)}


def _mk_count(zh: str = "数量", *, required: bool = False) -> dict[str, dict]:
    return {"count": _p("int", zh, required=required, default=1)}


# ══════════════════════════════════════════════════════════════════════
#  注册表（键必须与 psct.rules.EFFECT_TEMPLATES 同名）
# ══════════════════════════════════════════════════════════════════════
#: 每个 kind 的 (triggers, params, target_required, cost_allowed, fragment, category)
_TABLE: dict[str, tuple] = {
    # ── 检索 / 回收（官方写法不取对象）──────────────────────────────
    "search": (_ACT, _NO_PARAMS, True, True, "frag_to_hand", "CATEGORY_TOHAND+CATEGORY_SEARCH"),
    "search_grave": (_ACT, _NO_PARAMS, True, True, "frag_to_hand", "CATEGORY_TOHAND+CATEGORY_SEARCH"),
    "recover": (_ACT, _NO_PARAMS, True, True, "frag_to_hand", "CATEGORY_TOHAND+CATEGORY_SEARCH"),
    "search_banished": (_ACT, _NO_PARAMS, True, True, "frag_to_hand", "CATEGORY_TOHAND+CATEGORY_SEARCH"),
    # ── 特殊召唤 ────────────────────────────────────────────────────
    "ssummon": (_ACT, _NO_PARAMS, True, True, "frag_special_summon", "CATEGORY_SPECIAL_SUMMON"),
    "ssummon_deck": (_ACT, _NO_PARAMS, True, True, "frag_special_summon", "CATEGORY_SPECIAL_SUMMON"),
    "ssummon_hand": (_ACT, _NO_PARAMS, True, True, "frag_special_summon", "CATEGORY_SPECIAL_SUMMON"),
    "ssummon_grave": (_ACT, _NO_PARAMS, True, True, "frag_special_summon", "CATEGORY_SPECIAL_SUMMON"),
    "ssummon_extra": (_ACT, _mk_int("额外卡组怪兽的连接值/等级限制"), True, True,
                      "frag_special_summon", "CATEGORY_SPECIAL_SUMMON"),
    "ssummon_token": (_ACT, {"token": _p("str", "衍生物卡名", required=True),
                             "count": _p("int", "衍生物数量", default=1),
                             "atk": _p("int", "衍生物攻击力", default=0),
                             "def": _p("int", "衍生物守备力", default=0),
                             "level": _p("int", "衍生物等级", default=1),
                             "race": _p("str", "衍生物种族", default="战士族"),
                             "attribute": _p("str", "衍生物属性", default="暗")},
                      False, True, "frag_special_summon_token",
                      "CATEGORY_SPECIAL_SUMMON+CATEGORY_TOKEN"),
    "ssummon_banished": (_ACT, _NO_PARAMS, True, True, "frag_special_summon", "CATEGORY_SPECIAL_SUMMON"),
    # ── 抽卡 / 堆墓 / 翻卡 ──────────────────────────────────────────
    "draw": (_ACT, _mk_count(), False, True, "frag_draw", "CATEGORY_DRAW"),
    "mill": (_ACT, _mk_count(), False, True, "frag_mill", "CATEGORY_DECKDES"),
    "excavate": (_ACT, _mk_count(), False, True, "frag_excavate", 0),
    "discard_opponent": (_ACT, _mk_count(), False, True, "frag_discard_opponent", "CATEGORY_HANDES"),
    # ── 除去 / 移动 ─────────────────────────────────────────────────
    "destroy": (_ACT, _NO_PARAMS, True, True, "frag_destroy", "CATEGORY_DESTROY"),
    "destroy_all": (_ACT, _NO_PARAMS, False, True, "frag_destroy_all", "CATEGORY_DESTROY"),
    "banish": (_ACT, _NO_PARAMS, True, True, "frag_banish", "CATEGORY_REMOVE"),
    "banish_face_down": (_ACT, _NO_PARAMS, True, True, "frag_banish", "CATEGORY_REMOVE"),
    "send_grave": (_ACT, _NO_PARAMS, True, True, "frag_send_grave", "CATEGORY_TOGRAVE"),
    "return_hand": (_ACT, _NO_PARAMS, True, True, "frag_return_hand", "CATEGORY_TOHAND"),
    "return_deck": (_ACT, _NO_PARAMS, True, True, "frag_return_deck", "CATEGORY_TODECK"),
    "shuffle_deck": (_ACT, _NO_PARAMS, True, True, "frag_return_deck", "CATEGORY_TODECK"),
    "set_from_deck": (_ACT, _NO_PARAMS, True, True, "frag_set", "CATEGORY_SET"),
    # ── 无效化 ──────────────────────────────────────────────────────
    "negate": (_NEG, _NO_PARAMS, False, False, "frag_negate", "CATEGORY_NEGATE+CATEGORY_DESTROY"),
    "negate_effect": (_NEG, _NO_PARAMS, False, False, "frag_negate", "CATEGORY_NEGATE"),
    "cannot_activate": (_CONT_ONLY, _NO_PARAMS, False, False, "frag_static", 0),
    # ── 数值 / 表示形式 / 控制权 ────────────────────────────────────
    "gain_atk": (_ACT, _mk_int("攻击力上升数值", required=True), True, True,
                 "frag_stat_change", "CATEGORY_ATKCHANGE"),
    "lose_atk": (_ACT, _mk_int("攻击力下降数值", required=True), True, True,
                 "frag_stat_change", "CATEGORY_ATKCHANGE"),
    "set_atk": (_ACT, _mk_int("攻击力目标数值", required=True), True, True,
                "frag_stat_change", "CATEGORY_ATKCHANGE"),
    "gain_def": (_ACT, _mk_int("守备力上升数值", required=True), True, True,
                 "frag_stat_change", "CATEGORY_DEFCHANGE"),
    "set_def": (_ACT, _mk_int("守备力目标数值", required=True), True, True,
                "frag_stat_change", "CATEGORY_DEFCHANGE"),
    "change_position": (_ACT, _NO_PARAMS, True, True, "frag_change_position", "CATEGORY_POSITION"),
    "take_control": (_ACT, {"until_end_turn": _p("bool", "仅到回合结束", default=True)},
                     True, True, "frag_take_control", "CATEGORY_CONTROL"),
    "place_counter": (_ACT, {"counter": _p("str", "指示物种类（常量名或十六进制）", required=True),
                             "count": _p("int", "放置个数", default=1)},
                      True, True, "frag_counter", "CATEGORY_COUNTER"),
    # ── 伤害 / LP ───────────────────────────────────────────────────
    "lp_damage": (_ACT, _mk_int("伤害数值", required=True), False, True,
                  "frag_lp", "CATEGORY_DAMAGE"),
    "lp_gain": (_ACT, _mk_int("回复数值", required=True), False, True,
                "frag_lp", "CATEGORY_RECOVER"),
    "direct_attack": (_CONT_ONLY, _NO_PARAMS, False, False, "frag_static", 0),
    "piercing": (_CONT_ONLY, _NO_PARAMS, False, False, "frag_static", 0),
    # ── 限制 / 抗性（多为永续）──────────────────────────────────────
    "cannot_attack": (_CONT_ONLY, _NO_PARAMS, False, False, "frag_static", 0),
    "cannot_be_destroyed": (_CONT_ONLY, _NO_PARAMS, False, False, "frag_static", 0),
    "unaffected": (_CONT_ONLY, _NO_PARAMS, False, False, "frag_static", 0),
    "cannot_be_targeted": (_CONT_ONLY, _NO_PARAMS, False, False, "frag_static", 0),
    "continuous_gain_atk": (_CONT_ONLY, _mk_int("攻击力上升数值", required=True),
                            False, False, "frag_static", 0),
    # ── 召唤 / 规则文本 ────────────────────────────────────────────
    "fusion_summon": (_ACT, _NO_PARAMS, True, True, "", "CATEGORY_SPECIAL_SUMMON+CATEGORY_FUSION_SUMMON"),
    "synchro_summon": (_ACT, _NO_PARAMS, True, True, "", "CATEGORY_SPECIAL_SUMMON"),
    "xyz_summon": (_ACT, _NO_PARAMS, True, True, "", "CATEGORY_SPECIAL_SUMMON"),
    "link_summon": (_ACT, _NO_PARAMS, True, True, "", "CATEGORY_SPECIAL_SUMMON"),
    "ritual_summon": (_ACT, _NO_PARAMS, True, True, "", "CATEGORY_SPECIAL_SUMMON"),
    "pendulum_summon": (_ACT, _NO_PARAMS, False, False, "", "CATEGORY_SPECIAL_SUMMON"),
    "extra_normal_summon": (_ACT, _mk_count("额外召唤次数"), False, True, "", "CATEGORY_SUMMON"),
    "copy_name": (_CONT, {"name": _p("str", "当作使用的卡名", required=True)},
                  False, False, "frag_name_alias", 0),
    "treat_as_card": (_CONT, {"archetype": _p("str", "当作使用的字段名", required=False)},
                      False, False, "frag_name_alias", 0),
    "cannot_special_summon": (_CONT_ONLY, _NO_PARAMS, False, False, "frag_rule_text", 0),
    "cannot_normal_summon": (_CONT_ONLY, _NO_PARAMS, False, False, "frag_rule_text", 0),
    "must_first_ssummon": (_CONT_ONLY, _NO_PARAMS, False, False, "frag_rule_text", 0),
}


def _build() -> dict[str, EffectKind]:
    """由 ``psct.rules.EFFECT_TEMPLATES`` + 上面的表构造注册表。

    模板里有而表里没有的 kind → 仍然注册（保证键完整），但没有 Lua 片段；
    表里有而模板里没有的 kind → 直接丢弃（防止两边漂移）。
    """
    out: dict[str, EffectKind] = {}
    for key, tpl in PR.EFFECT_TEMPLATES.items():
        texts = {lg: str(tpl[lg]) for lg in _LANG_KEYS if tpl.get(lg)}
        row = _TABLE.get(key)
        if row is None:
            triggers, params, treq, cost_ok, frag, cat = (_ACT, _NO_PARAMS, False, True, "", 0)
        else:
            triggers, params, treq, cost_ok, frag, cat = row
        out[key] = EffectKind(
            key=key,
            zh=str(tpl.get("zh_cn") or ""),
            en=str(tpl.get("en") or ""),
            triggers=tuple(triggers),
            params=dict(params),
            target_required=bool(treq),
            cost_allowed=bool(cost_ok),
            lua_fragment=str(frag or ""),
            text_templates=texts,
            category_bits=cat,
        )
    return out


EFFECT_KINDS: dict[str, EffectKind] = _build()


def kind(key: str) -> Optional[EffectKind]:
    """查表；``key`` 未注册时返回 ``None``（可降级，不抛异常）。"""
    if not key:
        return None
    return EFFECT_KINDS.get(str(key).strip())


def describe_all() -> list[dict]:
    """给 UI 下拉用的效果种类列表（契约 §3.4）。"""
    out: list[dict] = []
    for k in EFFECT_KINDS.values():
        out.append({
            "key": k.key, "zh": k.zh, "en": k.en,
            "triggers": list(k.triggers),
            "params": {name: dict(spec) for name, spec in k.params.items()},
            "target_required": k.target_required,
            "cost_allowed": k.cost_allowed,
            "continuous": k.is_continuous,
            "rule_text": k.is_rule_text,
            "takes_target": k.takes_target,
            "has_fragment": k.has_fragment,
            "lua_fragment": k.lua_fragment,
            "category_bits": k.category_bits,
        })
    return out


# ══════════════════════════════════════════════════════════════════════
#  IR 校验
# ══════════════════════════════════════════════════════════════════════
def _issue(code: str, level: str, msg: str, hint: str = "",
           fld: str = "effects") -> Issue:
    return Issue(gate="G1", code=code, level=level, message=msg, hint=hint, field=fld)


def _as_effect(eff: Any) -> Optional[EffectSpec]:
    """容错：dict → EffectSpec；拿不出合法对象就返回 ``None``（可降级）。"""
    if isinstance(eff, EffectSpec):
        return eff
    if isinstance(eff, dict):
        try:
            return EffectSpec.from_dict(eff)
        except Exception:
            return None
    return None


def _coerce(value: Any, want: str) -> tuple[bool, Any]:
    """参数类型检查：返回 ``(是否合法, 规整后的值)``。"""
    if value is None:
        return True, None
    if want == "int":
        if isinstance(value, bool):
            return False, None
        if isinstance(value, int):
            return True, value
        try:
            return True, int(str(value).strip())
        except Exception:
            return False, None
    if want == "bool":
        if isinstance(value, bool):
            return True, value
        if isinstance(value, str):
            return True, value.strip().lower() not in ("", "0", "false", "no", "off")
        return True, bool(value)
    if want == "str":
        return True, str(value)
    if want in ("list", "dict"):
        return isinstance(value, (list, tuple) if want == "list" else dict), value
    return True, value


def validate_effect(eff: EffectSpec) -> list[Issue]:
    """校验**一条**效果 IR，返回问题列表（合法时为空列表）。

    覆盖契约 §3.4 要求的检查项：kind 是否注册、时点是否被该 kind 允许、
    必填参数是否缺失、该 kind 是否允许代价、是否要求 target、
    limit / filter_kind / zone / controller 取值域、参数类型是否可规整。
    """
    out: list[Issue] = []
    e = _as_effect(eff)
    if e is None:
        return [_issue("EFFECT_MALFORMED", "ERROR",
                       "效果条目不是 EffectSpec/dict，无法校验",
                       "用 content.effects.infer_from_text 生成，或手写成 EffectSpec")]

    idx = e.index
    tag = f"第 {idx + 1} 条效果"
    k = kind(e.kind)
    if not str(e.kind or "").strip():
        out.append(_issue("EFFECT_KIND_MISSING", "ERROR", f"{tag}缺少 kind",
                          "kind 是卡文与脚本共同的锚点，不能为空"))
        return out
    if k is None:
        out.append(_issue("EFFECT_KIND_UNKNOWN", "ERROR",
                          f"{tag}的 kind「{e.kind}」不在注册表里",
                          "可选键见 content.effects.describe_all()（与 PSCT 模板同名）",
                          fld="effects.kind"))
        return out

    # ── 时点 ──
    trig = str(e.trigger or "").strip().upper()
    if trig and trig not in TRIGGERS:
        out.append(_issue("EFFECT_TRIGGER_UNKNOWN", "ERROR",
                          f"{tag}的时点「{e.trigger}」不是已登记的时点键",
                          "时点键取自 core.models.TRIGGERS", fld="effects.trigger"))
    elif trig and k.triggers and trig not in k.triggers:
        allowed = "、".join(k.triggers) or "（该种类无时点）"
        out.append(_issue("EFFECT_TRIGGER_NOT_ALLOWED", "ERROR",
                          f"{tag}「{k.zh}」不允许时点「{e.trigger}」",
                          f"该种类可用的时点：{allowed}", fld="effects.trigger"))
    elif not trig:
        out.append(_issue("EFFECT_TRIGGER_EMPTY", "WARN", f"{tag}没有填时点",
                          "永续效果填 CONTINUOUS，起动效果填 IGNITION",
                          fld="effects.trigger"))

    # ── 参数 ──
    params = dict(e.params or {})
    for name, spec in k.params.items():
        if spec.get("required") and params.get(name) in (None, ""):
            out.append(_issue("EFFECT_PARAM_MISSING", "ERROR",
                              f"{tag}「{k.zh}」缺少必填参数 {name}（{spec.get('zh')}）",
                              f"在 params 里补 {name}", fld="effects.params"))
    for name, val in params.items():
        if name in k.params:
            want = str(k.params[name].get("type") or "")
            ok, _ = _coerce(val, want)
            if not ok:
                out.append(_issue("EFFECT_PARAM_TYPE", "ERROR",
                                  f"{tag}的参数 {name} 应为 {want}，收到 {type(val).__name__}",
                                  "改成可转换的值（数字串可以）", fld="effects.params"))
            choices = k.params[name].get("choices") or ()
            if choices and str(val) not in {str(c) for c in choices}:
                out.append(_issue("EFFECT_PARAM_CHOICE", "WARN",
                                  f"{tag}的参数 {name}={val!r} 不在候选值里",
                                  "候选：" + "、".join(str(c) for c in choices),
                                  fld="effects.params"))
        elif name not in COMMON_PARAMS:
            out.append(_issue("EFFECT_PARAM_UNKNOWN", "INFO",
                              f"{tag}有注册表之外的参数「{name}」",
                              "会被卡文/脚本忽略；确需自定义请加进 COMMON_PARAMS",
                              fld="effects.params"))

    # ── target ──
    if k.target_required and e.target is None:
        out.append(_issue("EFFECT_TARGET_REQUIRED", "ERROR",
                          f"{tag}「{k.zh}」必须描述作用对象（target）",
                          "补 EffectTarget(from_zone/filter_kind/count/controller)",
                          fld="effects.target"))
    if e.target is not None:
        t = e.target
        if str(t.from_zone or "").upper() not in ZONE_KEYS:
            out.append(_issue("EFFECT_TARGET_ZONE_UNKNOWN", "ERROR",
                              f"{tag}的作用区域「{t.from_zone}」不在取值域里",
                              "取值：" + "、".join(z for z in ZONE_KEYS if z),
                              fld="effects.target.from_zone"))
        if str(t.to_zone or "").upper() not in ZONE_KEYS:
            out.append(_issue("EFFECT_TARGET_ZONE_UNKNOWN", "ERROR",
                              f"{tag}的目标区域「{t.to_zone}」不在取值域里",
                              "取值：" + "、".join(z for z in ZONE_KEYS if z),
                              fld="effects.target.to_zone"))
        if str(t.filter_kind or "any") not in FILTER_KINDS:
            out.append(_issue("EFFECT_TARGET_FILTER_UNKNOWN", "ERROR",
                              f"{tag}的过滤类型「{t.filter_kind}」不在取值域里",
                              "取值：" + "、".join(FILTER_KINDS),
                              fld="effects.target.filter_kind"))
        if str(t.controller or "self") not in CONTROLLER_KEYS:
            out.append(_issue("EFFECT_TARGET_CONTROLLER_UNKNOWN", "ERROR",
                              f"{tag}的控制者「{t.controller}」不在取值域里",
                              "取值：self、opponent、both",
                              fld="effects.target.controller"))
        try:
            if int(t.count or 1) <= 0:
                out.append(_issue("EFFECT_TARGET_COUNT", "ERROR",
                                  f"{tag}的数量必须大于 0", "count=0 会让卡文与脚本同时失配",
                                  fld="effects.target.count"))
        except Exception:
            out.append(_issue("EFFECT_TARGET_COUNT", "ERROR",
                              f"{tag}的数量不是数字：{t.count!r}", "改成整数",
                              fld="effects.target.count"))
        if str(t.filter_kind or "") in ("archetype", "name", "race", "attribute",
                                        "level", "type") and t.filter_value in (None, ""):
            out.append(_issue("EFFECT_TARGET_FILTER_VALUE", "ERROR",
                              f"{tag}的过滤类型是 {t.filter_kind} 但没有 filter_value",
                              "脚本无法据此生成过滤函数", fld="effects.target.filter_value"))

    # ── cost ──
    c = e.cost
    if c is not None and str(c.kind or "none") not in ("", "none"):
        if not k.cost_allowed:
            out.append(_issue("EFFECT_COST_NOT_ALLOWED", "ERROR",
                              f"{tag}「{k.zh}」是{'规则文本' if k.is_rule_text else '不入连锁的效果'}，"
                              f"不能有代价（cost={c.kind}）",
                              "去掉 cost，或把效果改成入连锁的种类", fld="effects.cost"))
        if str(c.kind) not in COST_KINDS:
            out.append(_issue("EFFECT_COST_KIND_UNKNOWN", "ERROR",
                              f"{tag}的代价种类「{c.kind}」不在取值域里",
                              "取值：" + "、".join(COST_KINDS), fld="effects.cost.kind"))
        if str(c.zone or "").upper() not in ZONE_KEYS:
            out.append(_issue("EFFECT_COST_ZONE_UNKNOWN", "ERROR",
                              f"{tag}代价的区域「{c.zone}」不在取值域里",
                              "取值：" + "、".join(z for z in ZONE_KEYS if z),
                              fld="effects.cost.zone"))
        if c.kind == "pay_lp" and not (int(c.lp or 0) or int(params.get("value") or 0)):
            out.append(_issue("EFFECT_COST_LP_MISSING", "ERROR",
                              f"{tag}代价是支付 LP 但没有填数值", "补 cost.lp",
                              fld="effects.cost.lp"))

    # ── limit ──
    lim = str(e.limit or "none")
    if lim not in EFFECT_LIMITS:
        out.append(_issue("EFFECT_LIMIT_UNKNOWN", "ERROR",
                          f"{tag}的发动次数限制「{e.limit}」不在取值域里",
                          "取值：" + "、".join(EFFECT_LIMITS.keys()), fld="effects.limit"))

    return out


def validate_effects(spec: Any) -> list[Issue]:
    """校验整张卡的所有效果（便捷入口，供 G1/G2 复用）。"""
    out: list[Issue] = []
    for e in getattr(spec, "effect_specs", lambda: [])():
        out.extend(validate_effect(e))
    return out


# ══════════════════════════════════════════════════════════════════════
#  卡文 → IR（纯规则推断，**不依赖 LLM**）
# ══════════════════════════════════════════════════════════════════════
#: 段首编号（①..⑳ 与「1:」两种常见写法）
#: 段落编号标记：①–⑳（U+2460..U+2473）、㉑–㉟（U+3251..U+325F）、㊱–㊿（U+32B1..U+32BF）
#: —— 整段连续取值，保证 ``⑪`` 以后也按同一条规则识别，而不是只到 ``⑩``。
_NUM_VALUES: str = (
    "".join(chr(c) for c in range(0x2460, 0x2474))
    + "".join(chr(c) for c in range(0x3251, 0x3260))
    + "".join(chr(c) for c in range(0x32B1, 0x32C0))
)
_NUM_MARK_RE = re.compile("[" + re.escape(_NUM_VALUES) + "]")

#: 时点识别（按**长度倒序**匹配，避免「特殊召唤成功时」被「召唤成功时」抢走）
_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("这张卡特殊召唤成功时", "SPECIAL_SUMMON_SUCCESS"),
    ("特殊召唤成功的场合", "SPECIAL_SUMMON_SUCCESS"),
    ("这张卡召唤·特殊召唤成功时", "SUMMON_ANY_SUCCESS"),
    ("这张卡反转召唤成功时", "FLIP_SUMMON"),
    ("这张卡召唤成功时", "NORMAL_SUMMON_SUCCESS"),
    ("召唤成功时", "NORMAL_SUMMON_SUCCESS"),
    ("这张卡被破坏时", "WHEN_DESTROYED"),
    ("这张卡被破坏的场合", "WHEN_DESTROYED"),
    ("这张卡被破坏送去墓地时", "WHEN_SENT_GRAVE"),
    ("这张卡被送去墓地时", "WHEN_SENT_GRAVE"),
    ("同调召唤成功时", "SPECIAL_SUMMON_SUCCESS"),
    ("同步召唤成功时", "SPECIAL_SUMMON_SUCCESS"),
    ("融合召唤成功时", "SPECIAL_SUMMON_SUCCESS"),
    ("超量召唤成功时", "SPECIAL_SUMMON_SUCCESS"),
    ("多维召唤成功时", "SPECIAL_SUMMON_SUCCESS"),
    ("连接召唤成功时", "SPECIAL_SUMMON_SUCCESS"),
    ("链接召唤成功时", "SPECIAL_SUMMON_SUCCESS"),
    ("仪式召唤成功时", "SPECIAL_SUMMON_SUCCESS"),
    ("灵摆召唤成功时", "SPECIAL_SUMMON_SUCCESS"),
    ("这张卡被除外时", "WHEN_BANISHED"),
    ("这张卡加入手卡时", "WHEN_TO_HAND"),
    ("被战斗破坏时", "BATTLE_DESTROYED_SELF"),
    ("战斗破坏对方怪兽时", "BATTLE_DESTROY_SELF"),
    ("攻击宣言时", "ATTACK_DECLARE"),
    ("对方怪兽的攻击宣言时", "ATTACK_DECLARE"),
    ("对方发动", "OPPONENT_ACTIVATE"),
    ("效果发动时", "ON_ACTIVATE"),
    ("伤害步骤开始时", "DAMAGE_STEP_START"),
    ("结束阶段", "END_PHASE"),
    ("准备阶段", "STANDBY_PHASE"),
    ("自己主要阶段", "IGNITION"),
    ("主要阶段", "IGNITION"),
    ("这张卡装备时", "EQUIP_RELATED"),
    # 日文
    ("このカードが特殊召喚に成功した時", "SPECIAL_SUMMON_SUCCESS"),
    ("このカードが召喚に成功した時", "NORMAL_SUMMON_SUCCESS"),
    ("このカードが破壊された時", "WHEN_DESTROYED"),
    ("このカードが墓地へ送られた時", "WHEN_SENT_GRAVE"),
    ("自分メインフェイズに", "IGNITION"),
    ("エンドフェイズに", "END_PHASE"),
    ("スタンバイフェイズに", "STANDBY_PHASE"),
    ("相手が効果を発動した時", "OPPONENT_ACTIVATE"),
    # 英文
    ("When this card is Normal or Special Summoned", "SUMMON_ANY_SUCCESS"),
    ("When this card is Normal Summoned", "NORMAL_SUMMON_SUCCESS"),
    ("When this card is Special Summoned", "SPECIAL_SUMMON_SUCCESS"),
    ("When this card is destroyed", "WHEN_DESTROYED"),
    ("When this card is sent to the GY", "WHEN_SENT_GRAVE"),
    ("When your opponent activates", "OPPONENT_ACTIVATE"),
    ("During your Main Phase", "IGNITION"),
    ("During the End Phase", "END_PHASE"),
    ("During the Standby Phase", "STANDBY_PHASE"),
)
_TRIGGER_PATTERNS = tuple(sorted(_TRIGGER_PATTERNS, key=lambda x: -len(x[0])))

#: 代价识别（写在「发动」之前；中文靠语序、英文靠分号）
_COST_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # (正则, cost kind, 备注：需要解析的对象组名)
    (r"把这张卡解放", "tribute_self", ""),
    (r"このカードをリリース", "tribute_self", ""),
    (r"Tribute this card", "tribute_self", ""),
    (r"将这张卡从手卡丢弃", "discard_self", ""),
    (r"把这张卡从手卡丢弃", "discard_self", ""),
    (r"このカードを手札から捨て", "discard_self", ""),
    (r"discard this card", "discard_self", ""),
    (r"支付(?P<lp>\d+)点\s*LP", "pay_lp", "lp"),
    (r"(?P<lp>\d+)点的\s*LP(?:的生命分)?支付", "pay_lp", "lp"),
    (r"支付(?P<lp>\d+)点生命", "pay_lp", "lp"),
    (r"去除(?P<n>\d+)(?:个|只)(?:超量)?素材", "detach", "n"),
    (r"取り除いた(?P<n>\d+)個", "detach", "n"),
    (r"detach (?P<n>\d+) material", "detach", "n"),
    (r"把(?P<n>\d+)(?P<u>[只张])(?P<obj>[^。；;]*?)(?:从手卡)?丢弃", "discard", "obj"),
    (r"手札を(?P<n>\d+)枚捨てる", "discard", "n"),
    (r"discard (?P<n>\d+) card", "discard", "n"),
    (r"把(?P<n>\d+)(?P<u>[只张])(?P<obj>[^。；;]*?)除外", "banish", "obj"),
    (r"把(?P<n>\d+)(?P<u>[只张])(?P<obj>[^。；;]*?)送去墓地", "send_grave", "obj"),
    (r"把(?P<n>\d+)(?P<u>[只张])(?P<obj>[^。；;]*?)解放", "release", "obj"),
    (r"墓地へ送る", "send_grave", ""),
    (r"リリースする", "release", ""),
)

#: 处理段 → (动作键, 附加捕获)
#: **列表顺序即优先级**：更具体/更长的写法必须排在前面，否则会被泛化模式抢走
#: （例：「那个发动无效并破坏」里同时有「无效」和「破坏」，必须优先读成 negate）。
_ACTION_PATTERNS: tuple[tuple[str, str], ...] = (
    # ── 无效化（先于「破坏」）──────────────────────────────────────
    ("发动无效并破坏", "negate"),
    ("无效并破坏", "negate"),
    ("発動を無効にし破壊", "negate"),
    ("negate the activation", "negate"),
    ("效果无效", "negate_effect"),
    ("効果を無効", "negate_effect"),
    ("negate its effects", "negate_effect"),
    ("无效化", "negate_effect"),
    # ── 召唤手续（规则文本，先于「特殊召唤」）──────────────────────
    ("不能通常召唤", "cannot_normal_summon"),
    ("不能特殊召唤", "cannot_special_summon"),
    ("才能特殊召唤", "must_first_ssummon"),
    ("でのみ特殊召喚", "must_first_ssummon"),
    ("cannot be Normal Summoned", "cannot_normal_summon"),
    ("cannot be Special Summoned", "cannot_special_summon"),
    ("must first be Special Summoned", "must_first_ssummon"),
    # ── 特殊召唤类 ─────────────────────────────────────────────────
    ("融合召唤", "fusion_summon"),
    ("同步召唤", "synchro_summon"),
    ("超量召唤", "xyz_summon"),
    ("连接召唤", "link_summon"),
    ("仪式召唤", "ritual_summon"),
    ("灵摆召唤", "pendulum_summon"),
    ("特殊召唤", "special_summon"),
    # ── 抗性 / 限制（先于泛化的「破坏」「攻击」）────────────────────
    ("不会被效果破坏", "cannot_be_destroyed"),
    ("効果では破壊され", "cannot_be_destroyed"),
    ("cannot be destroyed by", "cannot_be_destroyed"),
    ("不受其他卡的效果影响", "unaffected"),
    ("効果を受けない", "unaffected"),
    ("unaffected by", "unaffected"),
    ("不能成为效果的对象", "cannot_be_targeted"),
    ("対象にならない", "cannot_be_targeted"),
    ("cannot be targeted", "cannot_be_targeted"),
    ("不能攻击", "cannot_attack"),
    ("攻撃できない", "cannot_attack"),
    ("cannot attack", "cannot_attack"),
    ("战斗伤害", "piercing"),
    ("戦闘ダメージ", "piercing"),
    ("piercing battle damage", "piercing"),
    ("直接攻击", "direct_attack"),
    ("直接攻撃", "direct_attack"),
    ("attack directly", "direct_attack"),
    # ── 移动 / 除去 ────────────────────────────────────────────────
    ("加入手卡", "to_hand"),
    ("手牌加", "to_hand"),
    ("手札に加える", "to_hand"),
    ("add .* to your hand", "to_hand"),
    ("回到手卡", "return_hand"),
    ("return .* to the hand", "return_hand"),
    ("送去墓地", "send_grave"),
    ("墓地へ送る", "send_grave"),
    ("send .* to the GY", "send_grave"),
    ("回到卡组", "return_deck"),
    ("洗回卡组", "shuffle_deck"),
    ("デッキに戻", "return_deck"),
    ("除外する", "banish"),
    ("除外", "banish"),
    ("banish", "banish"),
    ("破壊する", "destroy"),
    ("destroy ", "destroy"),
    ("破坏", "destroy"),
    # ── 数值 / LP / 卡库 ───────────────────────────────────────────
    (r"攻击力[^。；;]{0,24}?(?:上升|アップ)(?P<v>\d+)", "gain_atk"),
    (r"守备力[^。；;]{0,24}?(?:上升|アップ)(?P<v>\d+)", "gain_def"),
    (r"攻击力[^。；;]{0,24}?(?:下降|ダウン)(?P<v>\d+)", "lose_atk"),
    (r"攻击力[^。；;]{0,24}?(?:变成|变为)(?P<v>\d+)", "set_atk"),
    (r"守备力[^。；;]{0,24}?(?:变成|变为)(?P<v>\d+)", "set_def"),
    ("攻击力上升", "gain_atk"),
    (r"攻撃力は(?P<v>\d+)アップ", "gain_atk"),
    (r"gains (?P<v>\d+) ATK", "gain_atk"),
    ("攻击力下降", "lose_atk"),
    ("攻击力变成", "set_atk"),
    ("守备力上升", "gain_def"),
    ("守备力变成", "set_def"),
    ("表示形式变更", "change_position"),
    ("表示形式を変更", "change_position"),
    ("控制权", "take_control"),
    ("コントロールを得", "take_control"),
    ("take control", "take_control"),
    (r"放置(?P<n>\d+)(?:个|只)", "place_counter"),
    ("指示物", "place_counter"),
    (r"Counter\(s\)", "place_counter"),
    (r"回复(?P<n>\d+)点\s*LP", "lp_gain"),
    ("回復する", "lp_gain"),
    (r"gain (?P<n>\d+) LP", "lp_gain"),
    (r"(?P<v>\d+)点伤害", "lp_damage"),
    ("ダメージを与える", "lp_damage"),
    (r"inflict (?P<v>\d+) damage", "lp_damage"),
    (r"抽\s*(?P<n>\d+)\s*张", "draw"),
    ("ドローする", "draw"),
    (r"draw (?P<n>\d+) card", "draw"),
    ("通常召喚に加えて", "extra_normal_summon"),
    ("additional time", "extra_normal_summon"),
    ("丢弃", "discard_opponent"),
    ("捨てる", "discard_opponent"),
    ("discards", "discard_opponent"),
    # ── 卡名 / 字段当作使用（规则文本）─────────────────────────────
    ("卡名当作", "copy_name"),
    ("カード名は.*として扱う", "copy_name"),
    ("name becomes", "copy_name"),
    ("当作.{1,10}卡使用", "treat_as_card"),
    ("としても扱う", "treat_as_card"),
    ("treated as a", "treat_as_card"),
    ("特殊召喚する", "special_summon"),
)

#: (动作, 来源区域) → kind
_KIND_MATRIX: dict[tuple[str, str], str] = {
    ("to_hand", "DECK"): "search",
    ("to_hand", "GRAVE"): "search_grave",
    ("to_hand", "REMOVED"): "search_banished",
    ("to_hand", "EXTRA"): "search_banished",
    ("to_hand", ""): "search_banished",
    ("special_summon", "DECK"): "ssummon_deck",
    ("special_summon", "HAND"): "ssummon_hand",
    ("special_summon", "GRAVE"): "ssummon_grave",
    ("special_summon", "EXTRA"): "ssummon_extra",
    ("special_summon", "REMOVED"): "ssummon_banished",
    ("special_summon", "FIELD"): "ssummon",
    ("special_summon", ""): "ssummon",
    ("return_hand", ""): "return_hand",
    ("return_deck", ""): "return_deck",
    ("shuffle_deck", ""): "shuffle_deck",
    ("send_grave", ""): "send_grave",
    ("banish", ""): "banish",
    ("destroy", ""): "destroy",
}

#: 动作 → kind（不依赖来源区域的那一类）
_ACTION_KIND: dict[str, str] = {
    "fusion_summon": "fusion_summon", "synchro_summon": "synchro_summon",
    "xyz_summon": "xyz_summon", "link_summon": "link_summon",
    "ritual_summon": "ritual_summon", "pendulum_summon": "pendulum_summon",
    "return_hand": "return_hand", "return_deck": "return_deck",
    "shuffle_deck": "shuffle_deck", "send_grave": "send_grave",
    "banish": "banish", "destroy": "destroy", "draw": "draw",
    "gain_atk": "gain_atk", "lose_atk": "lose_atk", "set_atk": "set_atk",
    "gain_def": "gain_def", "set_def": "set_def",
    "change_position": "change_position", "take_control": "take_control",
    "place_counter": "place_counter", "lp_damage": "lp_damage",
    "lp_gain": "lp_gain", "direct_attack": "direct_attack",
    "piercing": "piercing", "cannot_be_destroyed": "cannot_be_destroyed",
    "unaffected": "unaffected", "cannot_be_targeted": "cannot_be_targeted",
    "cannot_attack": "cannot_attack", "extra_normal_summon": "extra_normal_summon",
    "discard_opponent": "discard_opponent",
    "negate": "negate", "negate_effect": "negate_effect",
    "cannot_normal_summon": "cannot_normal_summon",
    "cannot_special_summon": "cannot_special_summon",
    "must_first_ssummon": "must_first_ssummon",
    "copy_name": "copy_name", "treat_as_card": "treat_as_card",
}

#: 区域关键词 → zone
_ZONE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("从额外卡组", "EXTRA"), ("ＥＸデッキから", "EXTRA"), ("from your Extra Deck", "EXTRA"),
    ("从卡组顶", "DECKTOP"), ("卡组的上から", "DECKTOP"), ("top of the Deck", "DECKTOP"),
    ("从卡组", "DECK"), ("デッキから", "DECK"), ("from your Deck", "DECK"),
    ("从手卡", "HAND"), ("从手牌", "HAND"), ("手札から", "HAND"), ("from your hand", "HAND"),
    ("从自己墓地", "GRAVE"), ("从对方墓地", "GRAVE"), ("从墓地把", "GRAVE"),
    ("从墓地", "GRAVE"), ("自己墓地", "GRAVE"), ("对方墓地", "GRAVE"),
    ("墓地から", "GRAVE"), ("from your GY", "GRAVE"),
    ("除外的", "REMOVED"), ("除外状态", "REMOVED"), ("banished", "REMOVED"),
    ("自己场上", "MZONE"), ("对方场上", "MZONE"), ("场上的", "MZONE"),
    ("自分フィールドの", "MZONE"), ("相手フィールドの", "MZONE"),
)

#: 魔法·陷阱放置类（不取对象的 Set）
_SET_RE = re.compile(r"从卡组把[^。；;]*?(?:魔法|陷阱)[^。；;]*?(?:卡)?(?:以表侧表示)?放置|"
                     r"セットする|Set .* from your Deck")
_TOKEN_RE = re.compile(r"(?P<token>「[^」]{1,20}」)[^。]*?(?P<n>\d+)?只?衍生物|"
                       r"衍生物[^。]*?「(?P<token2>[^」]{1,20})」|"
                       r"Token\(s\)\s*(?:to|on)")
#: 「「X」怪兽／「X」卡／「X」魔法·陷阱」——引号里是字段名而不是卡名
_ARCH_ADJ_RE = re.compile(r"「([^」]{1,20})」\s*(?:怪兽|モンスター|卡|カード|魔法|陷阱)")
_ALL_RE = re.compile(r"全部|所有|全て|all\b", re.I)
_TARGETED_RE = re.compile(r"以[^。；;]{1,40}为对象|を対象として|target(?:s|ing)?\b", re.I)
#: 处理段指代词（官方写法用代词而不是重抄对象短语，见 rules.REFERENCE_PHRASES）。
#: 「那个／那只／那张」→ ``it``；「那个对象」→ ``that_target``；
#: 「那些」是复数，官方模板没有对应简中代词 → 记进 EffectSpec.note 提示人工复核。
_REFERENCE_RE = re.compile(r"那个对象|その対象|that target|那些|それら|那个|那只|那张|それ")
_SELF_EXCLUDE_RE = re.compile(r"（?这张卡除外）?|（このカードを除く）|except this card")
#: 「不入连锁」的措辞（永续效果 / 装备效果 / 规则文本）——
#: 官方卡文里这类句子**没有「才能发动」**，Lua 侧也不能登记成 IGNITION/TRIGGER。
#: 「不入连锁」的措辞（永续效果 / 装备效果 / 规则文本）——
#: 官方卡文里这类句子**没有「才能发动」**，Lua 侧也不能登记成 IGNITION/TRIGGER。
#: 注意：时限措辞「直到…为止／直到…时」**不属于**永续（它是入连锁效果的持续时长），
#: 所以这里不收「until／直到」，否则「攻击力直到回合结束时上升1000」会被误判成永续。
_CONTINUOUS_RE = re.compile(
    r"只要|限り|存在する(?:場合|限り)|while this card|is unaffected"
    r"|cannot be|不能|不受|不会被|当作|作为[^。；;]{1,12}存在", re.I)
#: 「直到…为止」的时限措辞（脚本侧要写 SetReset(RESET_PHASE+PHASE_END)）
#: 「直到…为止／直到…时」的时限措辞（脚本侧要写 SetReset(RESET_PHASE+PHASE_END)）
UNTIL_RE = re.compile(
    r"直到[^。；;]{0,16}?(?:为止|时)|回合结束为止|until the end of the turn|まで", re.I)

_HOPT_NAME_RE = re.compile(r"这个卡名的|このカード名の|You can only (?:use|activate) "
                           r"(?:each|1|this)? ?(?:effect|.*per turn)", re.I)
_OOPPT_RE = re.compile(
    r"1回合1次|１ターンに１度|Once per turn"
    r"|这个效果1回合只能(?:使用|发动)1次|この効果は１ターンに１度しか(?:使用|発動)できない", re.I)
_ACTIVATE_ONCE_RE = re.compile(r"1回合只能发动1张|しか発動できない|only activate 1", re.I)
_DUEL_ONCE_RE = re.compile(r"1场决斗中|デュエル中に|per Duel", re.I)
_NUM_RE = re.compile(r"(?P<n>\d+)\s*(?P<u>[只张个体枚])")
_VALUE_RE = re.compile(r"(?P<v>\d+)\s*(?:点|パ| damage| LP)", re.I)
_RACE_RE = re.compile(r"(?P<race>[\u4e00-\u9fa5]{1,6}族)")
_ATTR_RE = re.compile(r"(?P<attr>[地水炎风光暗神])属性")
_LEVEL_RE = re.compile(r"(?P<lv>\d+)\s*(?:星|等級|レベル)|Level (?P<lv2>\d+)", re.I)
_NAME_RE = re.compile(r"「([^」]{1,24})」")
_TYPE_WORD_RE = re.compile(r"(?P<t>通常召唤|效果怪兽|怪兽|魔法|陷阱|卡)")


def _is_num_para_mark(src: str, pos: int) -> bool:
    """``src[pos]`` 的圈数字是**段落起始标记**，还是「这个卡名的①②的效果」这种行内引用。

    两条判据，任一成立即算段起始：

    1. 紧跟冒号 —— 官方 PSCT 的编号段落恒为 ``①：正文``；
    2. 位于行首 —— 整篇开头，或前面只有空白。

    少了这道判据，``这个卡名的①②的效果1回合各能使用1次。`` 会被切成
    「①」「②的效果…」两条幽灵效果，而真正的限制语句反而粘在上一条上。
    """
    j = pos + 1
    while j < len(src) and src[j] in " \t\u3000":
        j += 1
    if j < len(src) and src[j] in "：:":
        return True
    k = pos
    while k > 0 and src[k - 1] in " \t\u3000":
        k -= 1
    return k == 0 or src[k - 1] == "\n"


def _split_paragraphs(text: str) -> list[tuple[int, str]]:
    """按 ①② 编号 / 换行 / 段落切段，返回 ``(框内编号, 段落原文)``。

    ``编号`` 是效果**所属文本框内的序号**（1 起）：卡文侧
    :func:`cardforge.content.psct.gen.compose` 就是按这个序号打 ①②③，
    脚本侧则据此分配 ``aux.Stringid(id, n)`` 槽位 —— 两边必须用同一个编号，
    否则「卡文写的②」和「脚本里的第二段描述」会错位（历史缺陷 #9）。

    * 有 ①②③ 标记：编号直接取标记在 ``①..⑳`` 里的位置（**按标记取值，
      不靠段落顺序猜**，因此「只给第②段」也切得对）；
    * 只有换行（``
``）分段：顺序编号；
    * 什么都没有：整段当作一条（``idx=1``）。
    """
    src = (text or "").strip()
    if not src:
        return []
    out: list[tuple[int, str]] = []
    if _NUM_MARK_RE.search(src):
        cur_idx = 0
        cur = ""
        for pos, ch in enumerate(src):
            if _NUM_MARK_RE.match(ch) and _is_num_para_mark(src, pos):
                if cur.strip():
                    out.append((cur_idx or len(out) + 1, cur.strip()))
                cur_idx = _NUM_VALUES.index(ch) + 1
                cur = ch
            else:
                cur += ch
        if cur.strip():
            out.append((cur_idx or len(out) + 1, cur.strip()))
        return out
    parts = [x.strip() for x in re.split(r"\n+", src) if x.strip()]
    if not parts:
        parts = [src]
    return [(i, para) for i, para in enumerate(parts, start=1)]


def _detect_limit(head: str, whole: str) -> str:
    """代价/条件段里找发动次数限制。"""
    if _ACTIVATE_ONCE_RE.search(whole):
        return "hopt_name_activate"
    if _DUEL_ONCE_RE.search(whole):
        return "once_duel"
    if _HOPT_NAME_RE.search(whole):
        return "hopt_name"
    if _OOPPT_RE.search(head) or _OOPPT_RE.search(whole):
        return "once_per_turn"
    return "none"


def _detect_trigger(head: str) -> tuple[str, str]:
    """返回 ``(trigger, 命中的关键词)``。"""
    for word, key in _TRIGGER_PATTERNS:
        if word and word in head:
            return key, word
    return "", ""


def _detect_zone(text: str) -> str:
    for word, zone in _ZONE_PATTERNS:
        if word in text:
            return zone
    return ""


def _detect_cost(head: str, spec: EffectSpec) -> tuple[Optional[EffectCost], str]:
    """从发动段里剥出代价；返回 ``(cost 或 None, 剩下的条件文本)``。"""
    for pattern, key, _note in _COST_PATTERNS:
        m = re.search(pattern, head)
        if not m:
            continue
        cost = EffectCost(kind=key)
        gd = m.groupdict() if getattr(m, "groupdict", None) else {}
        n = gd.get("n")
        if n:
            try:
                cost.count = int(n)
            except Exception:
                cost.count = 1
        lp = gd.get("lp")
        if lp:
            try:
                cost.lp = int(lp)
            except Exception:
                cost.lp = 0
        if key == "pay_lp" and not cost.lp:
            mv = _VALUE_RE.search(m.group(0))
            cost.lp = int(mv.group("v")) if mv else 0
        obj = str(gd.get("obj") or "")
        if obj:
            tgt = _parse_object(m.group(0))
            if tgt is not None:
                cost.filter_kind = tgt.filter_kind
                cost.filter_value = tgt.filter_value
        if key in ("discard", "discard_self"):
            cost.zone = "HAND"
        elif key in ("release", "tribute_self", "send_grave", "banish"):
            cost.zone = "MZONE" if key in ("release", "banish", "send_grave") else ""
        elif key == "detach":
            cost.zone = "OVERLAY"
        head = head[:m.start()] + head[m.end():]
        return cost, head
    return None, head


def _parse_object(segment: str) -> Optional[EffectTarget]:
    """把「1张「星奏」卡」「1只龙族怪兽」解析成 EffectTarget。"""
    if not segment:
        return None
    t = EffectTarget()
    body = segment
    mn = _NUM_RE.search(body)
    if mn:
        try:
            t.count = max(1, int(mn.group("n")))
        except Exception:
            t.count = 1
        if re.search(r"\d+\s*(?:张|枚|枚まで)", body):
            pass
    names = _NAME_RE.findall(body)
    if re.search(r"族|属性|星|Level|レベル", body) and names:
        # 「星奏」是字段名而不是卡名
        t.filter_kind = "archetype"
        t.filter_value = names[0]
    elif re.search(r"卡|カード|card", body, re.I) and names:
        t.filter_kind = "archetype"
        t.filter_value = names[0]
    elif _ARCH_ADJ_RE.search(body):
        # 「星奏」怪兽 / 「焰刃」卡 —— 引号紧邻类型词，官方这是**字段**引用
        t.filter_kind = "archetype"
        t.filter_value = _ARCH_ADJ_RE.search(body).group(1)
    elif names:
        t.filter_kind = "name"
        t.filter_value = names[0]
    mr = _RACE_RE.search(body)
    if mr:
        t.filter_kind, t.filter_value = "race", mr.group("race")
    ma = _ATTR_RE.search(body)
    if ma:
        t.filter_kind, t.filter_value = "attribute", ma.group("attr")
    ml = _LEVEL_RE.search(body)
    if ml:
        t.filter_kind = "level"
        t.filter_value = int(ml.group("lv") or ml.group("lv2") or 0)
    has_st = bool(re.search(r"魔法|陷阱|Spell/Trap|魔法・罠", body, re.I))
    has_mon = bool(re.search(r"怪兽|モンスター|monster", body, re.I))
    if has_st and t.filter_kind in ("any", "monster"):
        # 只有「魔法·陷阱」没有字段/卡名时，类型本身就是过滤条件
        t.filter_kind, t.filter_value = "type", "spelltrap"
    elif has_mon and t.filter_kind == "any":
        t.filter_kind = "monster"
    if re.search(r"对方|相手|opponent", body, re.I):
        t.controller = "opponent"
    if _SELF_EXCLUDE_RE.search(body):
        t.exclude_self = True
    if t.filter_kind == "any" and not mn:
        return None
    return t


def _split_head_body(para: str) -> tuple[str, str]:
    """把「①：条件段才能发动。处理段。」切成 ``(条件段, 处理段)``。"""
    text = para.strip()
    m = _NUM_MARK_RE.match(text)
    if m:
        text = text[m.end():]
        text = text.lstrip("：:、 。.")
    for sep in ("才能发动。", "才能发动；", "才能发动:", "发动。", "可以发动。",
                "発動できる。", "発動し、", "You can ", "can be activated. "):
        i = text.find(sep)
        if i >= 0:
            return text[:i].strip(), text[i + len(sep):].strip()
    # 没有「发动」字样：永续/规则文本，整段都是处理段
    return "", text


def _detect_action(body: str) -> tuple[str, Optional[re.Match]]:
    for pattern, action in _ACTION_PATTERNS:
        m = re.search(pattern, body)
        if m:
            return action, m
    return "", None


def infer_from_text(text: str) -> list[EffectSpec]:
    """卡文 → 效果 IR（**纯规则/关键词推断，不依赖 LLM**）。

    能确定地还原：``kind``、``trigger``、``limit``、``cost``、``target``
    （区域 / 数量 / 过滤条件 / 控制者）、是否取对象、是否**不入连锁**
    （``params['continuous']``，见本模块开头的 IR 契约补充说明）、
    时限（``params['until_end_turn']``）与处理段的指代（``params['reference_key']``）。

    识别顺序上有两条硬规则（都是真实卡文踩过的坑）：

    1. **段落编号按 ``_split_paragraphs`` 给的 idx 走**，``_index = idx - 1``，
       与 :func:`cardforge.content.psct.gen.compose` 的 ①②③ 完全一致；
    2. **先在处理段（「才能发动。」之后）匹配 kind 关键词，处理段完全没命中
       才退回发动段** —— 发动段带代价或卡名时会被误读，例如
       「从墓地把怪兽特殊召唤」做代价时，若先扫发动段就会把整条读成 ssummon_grave；
       代价文本在匹配前已经由 :func:`_detect_cost` 剥离，但卡名里的词
       （「星奏的指挥」含「指挥」）仍可能撞上关键词，所以处理段优先。

    认不出来的段落保留 ``raw_text`` 并把 ``kind`` 留空，交给
    :func:`validate_effect` 精确报错、由人工补写 —— 不猜。
    """
    out: list[EffectSpec] = []
    for idx, para in _split_paragraphs(text):
        head, body = _split_head_body(para)
        eff = EffectSpec(trigger="", limit="none", raw_text=para, source="infer")
        eff.params = dict(eff.params or {})
        eff.params["_index"] = idx - 1

        # 1) 次数限制
        eff.limit = _detect_limit(head, para)

        # 2) 代价（先把代价从发动段剥掉，再做后续匹配）
        cost, head2 = _detect_cost(head, eff)
        eff.cost = cost

        # 3) kind：处理段优先，发动段兜底
        action, m = _detect_action(body)
        if not action:
            action, m = _detect_action(head2)

        # 4) 时点（不入连锁的判断在第 6 步，这里先按时点词给候选）
        trigger, tword = _detect_trigger(head2 or para)

        zone = _detect_zone(body) or _detect_zone(head2)
        kkey = ""
        if action:
            if action == "special_summon" and _TOKEN_RE.search(body):
                kkey = "ssummon_token"
            elif action == "destroy" and _ALL_RE.search(body):
                kkey = "destroy_all"
            elif action == "to_hand" and _SET_RE.search(body):
                kkey = "set_from_deck"
            else:
                kkey = _KIND_MATRIX.get((action, zone)) or _ACTION_KIND.get(action, "")
        if not kkey:
            # 认不出来：只留 raw_text，让 validate_effect 精确命中「kind 缺失/未注册」
            out.append(eff)
            continue
        eff.kind = kkey

        # 5) target
        targeted = bool(_TARGETED_RE.search(head2))
        obj_seg = ""
        if targeted:
            mt = re.search(r"以(?P<obj>[^。；;]{1,40})为对象", head2)
            if mt:
                obj_seg = mt.group("obj")
        cand_seg = obj_seg if obj_seg else body
        tgt = _parse_object(cand_seg) if cand_seg else None
        if tgt is not None:
            tgt.from_zone = tgt.from_zone or zone
            if not obj_seg and "对方" in cand_seg:
                tgt.controller = "opponent"
        eff.target = tgt
        # 「「星奏」魔法卡」= 字段 + 卡类型两条限制；filter_kind 只有一条槽位，
        # 类型限制另存进 params['card_type']（Lua 侧 → c:IsType(TYPE_SPELL+TYPE_TRAP)）
        if tgt is not None and tgt.filter_kind in ("archetype", "name"):
            if re.search(r"魔法|陷阱|Spell/Trap", cand_seg, re.I):
                eff.params["card_type"] = "spelltrap"
            elif re.search(r"怪兽|モンスター|monster", cand_seg, re.I):
                eff.params["card_type"] = "monster"

        # 6) 不入连锁（永续 / 装备 / 规则文本）—— IR 里用 params['continuous'] 表达
        k = kind(kkey)
        is_rule = kkey in PR.RULE_TEXT_KINDS
        is_cont_kind = kkey in PR.CONTINUOUS_KINDS
        if kkey == "gain_atk" and _CONTINUOUS_RE.search(para):
            # 「只要这张卡在场，攻击力上升」是永续句式，不是起动效果
            kkey, k = "continuous_gain_atk", kind("continuous_gain_atk")
        if is_rule or is_cont_kind or (not tword and _CONTINUOUS_RE.search(para)):
            eff.params["continuous"] = True
            eff.trigger = "CONTINUOUS"
        else:
            eff.trigger = trigger or "IGNITION"

        # 7) 时限「直到…为止」→ 脚本侧需要 SetReset
        if UNTIL_RE.search(para):
            eff.params["until_end_turn"] = True
            eff.note = (eff.note + "；" if eff.note else "") +                 "时限措辞「直到…为止」已记为 until_end_turn，具体截止时点请人工确认"

        # 8) 处理段的指代（「那个／那张／那些」→ 官方用代词而不是重抄对象短语）
        ref = _REFERENCE_RE.search(body)
        if ref is not None:
            eff.params["reference"] = True
            word = ref.group(0)
            if word in ("那个对象", "その対象", "that target"):
                eff.params["reference_key"] = "that_target"
            else:
                eff.params["reference_key"] = "it"
                if word in ("那些", "それら"):
                    eff.note = (eff.note + "；" if eff.note else "") +                         f"处理段用「{word}」复数指代，卡文模板是单数写法，需人工复核"

        # 9) 数值参数
        try:
            gd = (m.groupdict() if m is not None and getattr(m, "groupdict", None) else {}) or {}
        except Exception:
            gd = {}
        if kkey in ("gain_atk", "lose_atk", "set_atk", "gain_def", "set_def",
                    "lp_damage", "lp_gain", "continuous_gain_atk"):
            val = gd.get("v")
            if val is None:
                mv = _VALUE_RE.search(body)
                val = mv.group("v") if mv else None
            if val is not None:
                eff.params["value"] = int(val)
        if kkey in ("draw", "mill", "excavate", "discard_opponent", "place_counter",
                    "ssummon_token", "extra_normal_summon"):
            n = gd.get("n")
            if n is None and tgt is not None:
                n = str(tgt.count or 1)
            if n is not None:
                eff.params["count"] = int(n)
        if kkey == "ssummon_token":
            mt2 = _NAME_RE.search(body)
            eff.params["token"] = (mt2.group(1) if mt2 else "")
        if kkey == "place_counter":
            mc = re.search(r"(?P<ctr>[一-龥A-Za-z]{1,10})指示物", body)
            eff.params["counter"] = (mc.group("ctr") if mc else "")
        if kkey in ("copy_name", "treat_as_card"):
            mn2 = _NAME_RE.search(body)
            eff.params["name" if kkey == "copy_name" else "archetype"] =                 (mn2.group(1) if mn2 else "")
        if not eff.params.get("continuous"):
            if targeted:
                eff.params["targeting"] = True
            elif k is not None and not k.takes_target:
                eff.params["targeting"] = False
        out.append(eff)
    return out


def infer_spec(text: str, *, index: int = 0) -> Optional[EffectSpec]:
    """推断单条效果（便捷入口）。"""
    lst = infer_from_text(text)
    return lst[index] if 0 <= index < len(lst) else None
