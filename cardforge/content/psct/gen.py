"""结构化效果 IR → **多语言 PSCT 卡文**。

设计原则
--------
1. **不是逐词直译。** 每种语言有自己的模板与语序（见 :mod:`rules`）：
   英文靠 ``CONDITIONS: ACTIVATION; RESOLUTION`` 三段标点，中文/日文靠
   **语序**（cost 写在「发动／発動」之前）且**不使用分号**。
2. **编号即段落。** ① 是段落起始标记，每条效果独占一段，段间用 ``\\n``
   分隔（下游渲染器按 ``\\n`` 分段排版）；卡名级 HOPT 声明另起一句放在段末。
3. **说不出来的就不硬造。** 没有原生模板的语言（ko / zh_tw / de / fr / it /
   pt / es）一律降级到 en，并在 :func:`compose_with_meta` 的返回值里标注
   ``used_lang`` / ``degraded`` / ``reason``。
4. **生成器与校验器共用 :mod:`rules`**，不各自维护一份规则。

对外主接口（接口契约 §3.2）::

    effect_to_text(eff, spec, lang="zh_cn", index=1) -> str
    compose(spec, lang="zh_cn") -> str
    compose_all(spec, langs) -> dict[str, str]
    type_line(spec, lang="zh_cn") -> str
    st_label(spec, lang="zh_cn") -> str
    flavor(spec, lang="zh_cn") -> str

灵摆卡有**两个独立文本框**，故另有 :func:`compose_pendulum` /
:func:`fill_spec`（把结果分别写回 ``text_i18n`` 与 ``pendulum_text_i18n``）。

排版约定（照 OCG 版式）
----------------------
* 中日文：``①：<次数限制>，<其他条件>，<代价／取对象>才能发动。<效果处理>。``
  —— 编号后的「：」是**编号标记**（官方连续效果也这么写），
  代价与取对象靠语序落在「发动／発動」之前。
* 英文：``① <conditions>: You can <cost>, then <target>; <resolution>.``
  —— 条件后才是「：」，cost/target 与处理之间是「;」。
* 永续效果（不入连锁）：中日文仍带 ``①：``；英文**不加冒号也不加分号**。
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from ...core.enums import DEFAULT_LANG, FRAMES, MONSTER_TAGS, SPELL_KINDS, TRAP_KINDS
from ...core.models import CardSpec, EffectSpec, EffectTarget
from .. import summon as S
from . import lexicon as L
from . import rules

__all__ = [
    "effect_to_text", "compose", "compose_all", "compose_pendulum",
    "compose_all_pendulum", "compose_with_meta", "compose_all_meta",
    "fill_spec", "type_line", "st_label", "flavor", "effect_count_lines",
    "BOX_MONSTER", "BOX_PENDULUM",
]

#: 文本框标识
BOX_MONSTER = "monster"
BOX_PENDULUM = "pendulum"

_FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")


# ══════════════════════════════════════════════════════════════════════
#  小工具
# ══════════════════════════════════════════════════════════════════════
def _num(value: Any, lang: str) -> str:
    """数字本地化：日文用全角，中文/英文用半角。"""
    try:
        s = str(int(value))
    except Exception:
        s = str(value)
    return s.translate(_FULLWIDTH_DIGITS) if lang == "ja" else s


def _safe(value: Any) -> str:
    """把用户文本里的花括号换掉，避免 ``str.format`` 被卡名破坏。"""
    return str(value if value is not None else "").replace("{", "（").replace("}", "）")


class _SafeDict(dict):
    """缺键时保留 ``{key}`` 原文 —— 模板缺占位符时在输出里**看得见**。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _fmt(template: str, ctx: dict) -> str:
    try:
        return template.format_map(_SafeDict(ctx))
    except Exception:
        return template


def _cap(text: str) -> str:
    """英文句首大写（只动第一个 ASCII 字母）。"""
    for i, ch in enumerate(text or ""):
        if ch.isascii() and ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
    return text


def _bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


# ══════════════════════════════════════════════════════════════════════
#  生成上下文
# ══════════════════════════════════════════════════════════════════════
class _Gen:
    """一次生成过程的上下文（语言解析 + 降级留痕）。"""

    def __init__(self, spec: CardSpec, lang: str):
        self.spec = spec
        self.request_lang = lang or DEFAULT_LANG
        self.used_lang, self.reason = L.generation_lang(self.request_lang)
        self.notes: list[str] = []
        if self.reason:
            self.notes.append(self.reason)

    @property
    def lang(self) -> str:
        return self.used_lang

    @property
    def st(self) -> rules.LangStyle:
        return rules.style(self.used_lang)

    @property
    def degraded(self) -> bool:
        return bool(self.reason)

    def note(self, msg: str) -> None:
        if msg not in self.notes:
            self.notes.append(msg)

    def quote(self, name: str) -> str:
        return L.quote(name, self.used_lang)

    def name(self, lang: str = "") -> str:
        return self.spec.name_in(lang or self.used_lang) or self.spec.name


# ══════════════════════════════════════════════════════════════════════
#  宾语短语
# ══════════════════════════════════════════════════════════════════════
def _arch_name(gen: _Gen, params: Optional[dict] = None) -> str:
    """字段名（优先取 ``params['archetype_i18n']`` 的目标语言译名）。"""
    p = params or {}
    i18n = p.get("archetype_i18n")
    if isinstance(i18n, dict):
        v = i18n.get(gen.lang) or i18n.get("zh_cn") or i18n.get("en")
        if not i18n.get(gen.lang) and gen.lang != "zh_cn":
            gen.note(f"字段名「{v}」缺 {gen.lang} 译名，已用中文原名")
        if v:
            return str(v)
    arc = str(p.get("archetype") or gen.spec.archetype or "")
    if arc and gen.lang != "zh_cn":
        gen.note(f"字段名「{arc}」没有 {gen.lang} 译名（Archetype.name_i18n 可补）")
    return arc


def _filter_words_bare(target: Optional[EffectTarget], gen: _Gen,
                       params: Optional[dict] = None) -> tuple[str, str]:
    """返回 ``(不带数量的宾语短语, 单位键)``（不含「表侧表示」限定）。"""
    p = dict(params or {})
    lang = gen.lang
    tgt = target or EffectTarget()
    kind = str(tgt.filter_kind or p.get("filter_kind") or "any")
    value = tgt.filter_value if tgt.filter_value is not None else p.get("filter_value")

    if kind in ("name", "card_name") and value:
        return gen.quote(str(value)), "card"
    if kind in ("archetype", "field"):
        arc = value or _arch_name(gen, p)
        if not arc:
            gen.note("字段引用没有给出字段名，已退化为「卡」")
            return ("カード" if lang == "ja" else "card" if lang == "en"
                    else "卡"), "card"
        q = gen.quote(str(arc))
        # 字段引用后面跟的是「怪兽」还是「卡」，取决于这条效果限制的卡类型 ——
        # 官方简中实测：「X」怪兽 3791 张 、「X」卡 1184 张，两者都合法但语义不同。
        # 以前一律写「X」卡，于是「1只「圣痕」怪兽」被投影成「1张「圣痕」卡」，
        # 量词与名词一起走样（整理器按「数值+卡名保真」守卫拦下，等于永远不敢重写）。
        ct = str(p.get("card_type") or "").strip().lower()
        if lang == "ja":
            if ct == "monster":
                return f"{q}モンスター", "monster"
            if ct in ("spell", "trap", "spelltrap"):
                w = {"spell": "魔法カード", "trap": "罠カード",
                     "spelltrap": "魔法・罠カード"}[ct]
                return f"{q}{w}", "card"
            return f"{q}カード", "card"
        if lang != "en":
            if ct == "monster":
                return f"{q}怪兽", "monster"
            if ct == "spell":
                return f"{q}魔法卡", "card"
            if ct == "trap":
                return f"{q}陷阱卡", "card"
            if ct == "spelltrap":
                return f"{q}魔法·陷阱卡", "card"
            return f"{q}卡", "card"
        if ct == "monster":
            return f"{q} monster", "monster"
        if ct == "spell":
            return f"{q} Spell card", "card"
        if ct == "trap":
            return f"{q} Trap card", "card"
        if ct == "spelltrap":
            return f"{q} Spell/Trap card", "card"
        return f"{q} card", "card"
    if kind == "race" and value:
        race = L.race_term(str(value), lang)
        if lang == "ja":
            return f"{race}モンスター", "monster"
        if lang != "en":
            return f"{race}怪兽", "monster"
        return f"{race} monster", "monster"
    if kind == "attribute" and value:
        attr = L.attribute_term(str(value), lang)
        if lang == "ja":
            return f"{attr}属性モンスター", "monster"
        if lang != "en":
            return f"{attr}怪兽", "monster"
        return f"{attr} monster", "monster"
    if kind == "level" and value is not None:
        n = _num(value, lang)
        if lang == "ja":
            return f"レベル{n}モンスター", "monster"
        if lang != "en":
            return f"{n}星怪兽", "monster"
        return f"Level {n} monster", "monster"
    if kind in ("type", "card_type") and value:
        ct = L.card_type_term(str(value), lang)
        if lang == "ja":
            return f"{ct}モンスター", "monster"
        if lang != "en":
            return f"{ct}怪兽", "monster"
        return f"{ct} monster", "monster"
    if kind == "token":
        return ("トークン" if lang == "ja" else "Token" if lang == "en"
                else "衍生物"), "token"
    if kind == "monster":
        return ("モンスター" if lang == "ja" else "monster" if lang == "en"
                else "怪兽"), "monster"
    return ("カード" if lang == "ja" else "card" if lang == "en" else "卡"), "card"


def _filter_words(target: Optional[EffectTarget], gen: _Gen,
                  params: Optional[dict] = None) -> tuple[str, str]:
    """宾语短语 + 单位；补上官方卡文里挂在宾语身上的两类限定。

    * ``face_up`` → 「表侧表示的」前缀（「以对方场上1张表侧表示的卡为对象」）。
    * ``select`` + ``exclude_self`` → 「「卡名」以外的」前缀：不取对象的"选"
      句式里官方用卡名排除（旧式「（这张卡除外）」只出现在取对象的老卡上，
      那边仍由 :func:`_target_phrase` 收尾，两种写法不叠加）。
    """
    core, unit = _filter_words_bare(target, gen, params)
    tgt = target or EffectTarget()
    p = dict(params or {})
    lang = gen.lang
    face_up = _bool(getattr(tgt, "face_up", False), False) or \
        _bool(p.get("face_up"), False)
    prefix = rules.FACEUP_WORDS.get(lang, "")
    if face_up and prefix and core:
        core = f"{prefix} {core}" if lang == "en" else f"{prefix}{core}"
    if _bool(p.get("select"), False) and getattr(tgt, "exclude_self", False) and core:
        nm = gen.quote(gen.name())
        if lang == "en":
            core = f"{core} other than {nm}"
        elif lang == "ja":
            core = f"{nm}を除く{core}"
        else:
            core = f"{nm}以外的{core}"
    return core, unit


def _count_of(target: Optional[EffectTarget], params: Optional[dict] = None) -> tuple[int, int]:
    p = dict(params or {})
    tgt = target or EffectTarget()
    try:
        count = int(tgt.count or p.get("count") or p.get("n") or 1)
    except Exception:
        count = 1
    try:
        cmax = int(tgt.count_max or p.get("count_max") or 0)
    except Exception:
        cmax = 0
    return max(0, count), max(0, cmax)


def _obj_with_count(core: str, unit: str, count: int, cmax: int, gen: _Gen) -> str:
    """把「不带数量的宾语」变成带数量的短语（语序按语言）。"""
    lang = gen.lang
    num = _num(count, lang)
    unit_w = rules.COUNT_UNITS.get(unit, rules.COUNT_UNITS["card"])
    up_to = cmax > count > 0
    if lang == "ja":
        base = f"{core}{num}{unit_w.get('ja', '枚')}"
        return f"{base}まで" if up_to else base
    if lang != "en":
        base = f"{num}{unit_w.get('zh_cn', '张')}{core}"
        return f"{base}以下" if up_to else base
    return f"up to {num} {core}" if up_to else f"{num} {core}"


def _obj_phrase(eff: EffectSpec, gen: _Gen, *,
                target: Optional[EffectTarget] = None,
                params: Optional[dict] = None) -> str:
    """带数量的宾语短语（``1只龙族怪兽`` / ``ドラゴン族モンスター１体`` / ``1 Dragon monster``）。"""
    tgt = target if target is not None else eff.target
    core, unit = _filter_words(tgt, gen, params)
    count, cmax = _count_of(tgt, params)
    return _obj_with_count(core, unit, count or 1, cmax, gen)


def _target_phrase(eff: EffectSpec, gen: _Gen) -> str:
    """**取对象**用的短语（含控制者与区域）。

    ``params`` 必须一起传进来：字段 + 卡类型（``card_type``）是分开存的，
    漏传就会让「以…为对象」那半句写成「1张「X」卡」，
    而处理段是「那只怪兽」—— 同一句话里量词和名词自相矛盾。
    """
    tgt = eff.target
    lang = gen.lang
    core, unit = _filter_words(tgt, gen, eff.params)
    count, cmax = _count_of(tgt, eff.params)
    objn = _obj_with_count(core, unit, count or 1, cmax, gen)
    if tgt is None:
        return objn
    ctrl = str(tgt.controller or "self")
    zone = str(tgt.from_zone or "").upper()
    cw = rules.CONTROLLER_WORDS.get(ctrl, rules.CONTROLLER_WORDS["self"])
    if lang == "en":
        who = "you" if ctrl == "self" else (
            "your opponent" if ctrl == "opponent" else "either player")
        if zone in ("", "FIELD"):
            if ctrl == "both":
                out = f"{objn} either player controls"
            elif ctrl == "opponent":
                out = f"{objn} your opponent controls"
            else:
                out = f"{objn} you control"
        else:
            zw = rules.ZONE_WORDS.get(zone, {}).get("en", zone.lower())
            poss = "your" if ctrl == "self" else "your opponent's"
            out = f"{objn} in {poss} {zw}"
        if tgt.exclude_self:
            out += " (except this card)"
        return out
    if lang == "ja":
        c = cw.get("ja", "自分")
        if zone in ("", "FIELD"):
            out = f"{c}フィールドの{objn}"
        else:
            zw = rules.ZONE_WORDS.get(zone, {}).get("ja", zone)
            out = f"{c}の{zw}の{objn}"
        if tgt.exclude_self:
            out += "（このカードを除く）"
        return out
    c = cw.get("zh_cn", "自己")
    # 官方简中取对象段是「以自己场上1只…／以自己墓地1只…」，区域和数量之间
    # **不加「的」**（实测：「以自己场上1只」761 例，「以自己场上的1只」0 例）。
    if zone in ("", "FIELD"):
        out = f"{c}场上{objn}"
    else:
        zw = rules.ZONE_WORDS.get(zone, {}).get("zh_cn", zone)
        out = f"{c}{zw}{objn}"
    if tgt.exclude_self:
        out += "（这张卡除外）"
    return out


# ══════════════════════════════════════════════════════════════════════
#  代价（发动段）
# ══════════════════════════════════════════════════════════════════════
def _cost_object(eff: EffectSpec, gen: _Gen) -> str:
    """代价的宾语短语（会带上区域信息，如「自己手卡的1张卡」/「自分フィールドのモンスター１体」）。

    ⚠ 历史缺陷（docs/03 §三-c）：``EffectCost(kind="discard")`` 不写 zone 时，
    ``""`` 被当成「场上」，于是卡文写成「把自己场上的怪兽丢弃」——
    **丢弃的默认区域是手卡**，这里必须显式兜住。
    ``detach`` 同理：去除的是「超量素材」而不是「怪兽」。
    """
    cost = eff.cost
    assert cost is not None
    lang = gen.lang
    kind_cost = str(cost.kind or "").strip().lower()
    zone = str(cost.zone or "").upper()
    # discard：不写 zone → 手卡（官方写法「把手卡…丢弃」，绝不落到场上）
    if kind_cost == "discard" and not zone:
        zone = "HAND"
    kind = str(cost.filter_kind or "any")

    # detach：宾语是「超量素材」短语，独立构造（模板只需接动词）
    if kind_cost == "detach":
        n = max(1, int(cost.count or 1))
        num = _num(n, lang)
        on_other = zone in ("MZONE", "FIELD", "MONSTER")
        if lang == "ja":
            return (f"自分フィールドのモンスターのＸ素材を{num}つ" if on_other
                    else f"このカードのＸ素材を{num}つ")
        if lang != "en":
            return (f"自己场上的怪兽{num}个超量素材" if on_other
                    else f"这张卡{num}个超量素材")
        unit_w = "material" if n == 1 else "materials"
        return (f"{n} {unit_w} from a monster you control" if on_other
                else f"{n} {unit_w} from this card")

    tgt = EffectTarget(from_zone=zone, filter_kind=kind,
                       filter_value=cost.filter_value, count=cost.count or 1)
    core, unit = _filter_words(tgt, gen)
    on_field = zone in ("MZONE", "FIELD", "MONSTER", "")
    if kind == "any":
        if on_field:   # 注意：HAND 不算 on_field —— 区域词由下面的前缀给出
            core = {"zh_cn": "怪兽", "ja": "モンスター"}.get(lang, "monster")
            unit = "monster"
    count, cmax = _count_of(tgt)
    obj = _obj_with_count(core, unit, count or 1, cmax, gen)
    if lang == "en":
        if zone == "HAND":
            return f"{obj} from your hand"
        if on_field:
            return f"{obj} you control"
        zw = rules.ZONE_WORDS.get(zone, {}).get("en", "") if zone else ""
        return f"{obj} in your {zw}" if zw else obj
    if lang == "ja":
        if zone == "HAND":
            return f"自分の手札の{obj}"
        if on_field:
            return f"自分フィールドの{obj}"
        zw = rules.ZONE_WORDS.get(zone, {}).get("ja", zone) if zone else ""
        return f"自分の{zw}の{obj}" if zw else obj
    if zone == "HAND":
        return obj
    if on_field:
        return f"自己场上{obj}"
    return obj


#: 中文代价的来源区域前缀（官方实测：「从卡组把1只…」1022 例、
#: 「从手卡把1只」506 例、「从自己墓地把1只」208 例、「从额外卡组把」242 例；
#: 而「把自己卡组的1只」0 例 —— 代价的区域用「从…」引导，不用「的」字定语）。
_COST_FROM_ZH: dict[str, str] = {
    "DECK": "从卡组", "DECKTOP": "从卡组顶", "HAND": "从手卡",
    "GRAVE": "从自己墓地", "EXTRA": "从额外卡组", "REMOVED": "从除外区",
    "FIELD": "", "MZONE": "", "SZONE": "", "PZONE": "", "FZONE": "", "": "",
}


def _cost_from(eff: EffectSpec, gen: _Gen) -> str:
    """代价的「从…」来源前缀（只有中文有这个句式；日英靠宾语自带介词）。"""
    if gen.lang != "zh_cn":
        return ""
    cost = eff.cost
    if cost is None:
        return ""
    kind_cost = str(cost.kind or "").strip().lower()
    if kind_cost in ("tribute_self", "discard_self", "pay_lp", "detach", "none", ""):
        return ""
    zone = str(cost.zone or "").upper()
    if kind_cost == "discard" and not zone:
        zone = "HAND"
    if zone in ("", "FIELD", "MZONE", "SZONE", "PZONE", "FZONE", "MONSTER"):
        return ""
    return _COST_FROM_ZH.get(zone, "")


def _cost_parts(eff: EffectSpec, gen: _Gen) -> dict:
    """返回 ``{"plain": 中日文/英文用, "ja_stem": 连用形, "ja_te": て形}``。

    中日文靠语序表达 cost（写在「发动／発動」之前），英文靠 ``;``。
    """
    cost = eff.cost
    if cost is None or str(cost.kind or "none") in ("", "none"):
        return {"plain": "", "ja_stem": "", "ja_te": ""}
    key = str(cost.kind)
    spec = rules.COST_PHRASES.get(key)
    if spec is None:
        gen.note(f"未注册的代价种类「{key}」，已忽略该代价")
        return {"plain": "", "ja_stem": "", "ja_te": ""}
    obj = _cost_object(eff, gen)
    ctx = {
        "obj": obj,
        "lp": _num(cost.lp or eff.params.get("lp") or 0, gen.lang),
        "n": _num(cost.count or 1, gen.lang),
    }
    return {
        "plain": _cost_from(eff, gen)
        + _fmt(spec.en if gen.lang == "en" else spec.zh_cn, ctx),
        "ja_stem": _fmt(spec.ja or spec.zh_cn, ctx),
        "ja_te": _fmt(spec.ja_te or spec.ja or spec.zh_cn, ctx),
    }


def _has_target(eff: EffectSpec) -> bool:
    """该效果是否**取对象**。

    IR 里给了 ``target`` 不代表一定取对象：

    * 检索/堆墓/从卡组特召这类效果按官方写法是"处理时才选"，不写「以…为对象」；
    * 永续效果不入连锁，根本没有"发动时取对象"这一步。

    此时 ``target`` 只作为范围描述使用（``params['targeting']=True`` 可强制取对象，
    ``params['select']=True`` 则强制走"处理时选"的「从自己墓地选…」句式）。
    """
    if eff.target is None:
        return False
    p = eff.params or {}
    if _bool(p.get("select"), False):
        return False
    if _bool(p.get("targeting"), False):
        return True
    if _is_continuous(eff):
        return False
    return str(eff.kind or "") not in rules.NON_TARGETING_KINDS


# ══════════════════════════════════════════════════════════════════════
#  发动条件
# ══════════════════════════════════════════════════════════════════════
def _quick(eff: EffectSpec, gen: _Gen) -> bool:
    """是否诱发即时效果（官方收尾句「这个效果在对方回合也能发动。」）。

    ``params['quick']`` 显式指定优先；时点填 ``QUICK`` 的怪兽效果默认就是它。
    魔法/陷阱没有这个说法（靠卡种拿 2 速），所以只对怪兽成立。
    """
    p = dict(eff.params or {})
    if "quick" in p:
        return _bool(p.get("quick"), True) and gen.spec.is_monster
    return str(eff.trigger or "").upper() == "QUICK" and gen.spec.is_monster


def _conditions(eff: EffectSpec, gen: _Gen) -> list[str]:
    """发动条件段的成分（官方语序：次数限制 → 其它条件 → 时点）。"""
    out: list[str] = []
    p = dict(eff.params or {})

    key = rules.hopt_key(eff.limit)
    if key in rules.INLINE_HOPT_KEYS:
        text = L.hopt(key, gen.lang, gen.name(), numbers="①")
        out.append(text.rstrip("，,：:、 ").strip())

    extra = p.get("condition")
    if isinstance(extra, dict):
        if not extra.get(gen.lang) and gen.lang != "zh_cn" and extra:
            gen.note("附加发动条件缺该语言文本，已回落到中文原文")
        extra = extra.get(gen.lang) or extra.get("zh_cn") or extra.get("en")
    elif extra and gen.lang != "zh_cn":
        gen.note("附加发动条件是纯字符串（非多语言 dict），"
                 "在非中文卡文里会原样出现")
    if extra:
        out.append(str(extra))

    trigger = str(eff.trigger or "").upper()
    destroyed_by = str(p.get("destroyed_by") or "").strip()
    item = rules.TRIGGER_PHRASES.get(trigger)
    if trigger == "WHEN_DESTROYED" and destroyed_by \
            and rules.DESTROYED_BY_PHRASES.get(destroyed_by):
        # 「这张卡被战斗·效果破坏的场合」—— 破坏方式是官方卡文的一部分，
        # 只写「被破坏时」会把「不会被战斗破坏」那类抗性读成可利用的漏洞。
        timing = str(p.get("timing")
                     or rules.TRIGGER_TIMING_DEFAULT.get(trigger, "when"))
        pair = rules.DESTROYED_BY_PHRASES[destroyed_by]
        phrase = pair.get(gen.lang) or pair.get("zh_cn")
        if phrase:
            out.append(phrase[1] if timing == "if" else phrase[0])
            return [s for s in out if s]
    if trigger == "QUICK" and _quick(eff, gen):
        # 官方简中不写「对方主要阶段」，用收尾句「这个效果在对方回合也能发动。」
        pass
    elif item is None:
        if trigger and trigger not in ("CONTINUOUS",):
            gen.note(f"未注册的时点「{trigger}」，条件段留空（需人工补写时点）")
    elif trigger == "QUICK" and not gen.spec.is_monster:
        # 只有怪兽有诱发即时效果；速攻魔法/陷阱靠卡种本身获得 2 速（报告 A3.3）
        gen.note("魔法/陷阱没有「诱发即时效果」这一说法，已省略 (Quick Effect) "
                 "类时点措辞（速攻魔法/陷阱靠卡种获得 2 速）")
    else:
        phrase = item.get(gen.lang) or ""
        timing = str(p.get("timing")
                     or rules.TRIGGER_TIMING_DEFAULT.get(trigger, "when"))
        if phrase:
            out.append(rules.retime(phrase, gen.lang, timing))
    return [s for s in out if s]


# ══════════════════════════════════════════════════════════════════════
#  效果处理
# ══════════════════════════════════════════════════════════════════════
def _one_resolution(kind: str, params: dict, eff: EffectSpec,
                    gen: _Gen) -> tuple[str, str]:
    """返回 ``(辞書形, 連用形)``；未注册的种类退化为 ``(文本, "")``。"""
    kind = (kind or "").strip()
    tpl = rules.EFFECT_TEMPLATES.get(kind)
    lang = gen.lang
    # 「处理时才选」句式（官方：「从自己的墓地选1只…特殊召唤」）
    if _bool(dict(params or {}).get("select"), False) and kind in rules.SELECT_TEMPLATES:
        tpl = rules.SELECT_TEMPLATES[kind]
    if tpl:
        raw = str(tpl.get(lang) or tpl.get("en") or "")
        if "|" in raw:
            dict_form, stem = raw.split("|", 1)
        else:
            dict_form, stem = raw, ""
        ctx = _template_ctx(eff, gen, params, kind)
        return _fmt(dict_form, ctx), (_fmt(stem, ctx) if stem else "")
    raw_text = (eff.raw_text or "").strip().rstrip("。. ")
    if raw_text:
        gen.note(f"效果种类「{kind or '(空)'}」未注册，已直接使用 raw_text")
        return raw_text, ""
    gen.note(f"效果种类「{kind or '(空)'}」未注册且无 raw_text，已插入可见占位符")
    placeholder = {"zh_cn": f"（未注册的效果种类：{kind}）",
                   "ja": f"（未登録の効果種別：{kind}）",
                   "en": f"(unregistered effect kind: {kind})"}.get(lang, kind)
    return placeholder, ""


def _resolution_pieces(eff: EffectSpec, gen: _Gen) -> list[tuple[str, str]]:
    """效果处理的各段：``params['parts']`` 支持把一条效果拆成多段。"""
    p = dict(eff.params or {})
    raw = p.get("parts")
    pieces: list[tuple[str, str]] = []
    if isinstance(raw, (list, tuple)) and raw:
        for item in raw:
            if isinstance(item, str):
                pieces.append(_one_resolution(item, {}, eff, gen))
            elif isinstance(item, dict):
                merged = {**p, **item}
                pieces.append(_one_resolution(str(item.get("kind") or eff.kind),
                                              merged, eff, gen))
    else:
        pieces.append(_one_resolution(str(eff.kind or ""), p, eff, gen))
    return [(a, b) for a, b in pieces if a]


def _join_resolution(pieces: list[tuple[str, str]], conj_key: str,
                     gen: _Gen) -> str:
    """用**连接词表里的译法**把多段处理接起来（不做逐词直译）。"""
    if len(pieces) <= 1:
        return pieces[0][0] if pieces else ""
    conj = rules.CONJUNCTIONS.get(conj_key)
    if conj is None:
        gen.note(f"未注册的连接词「{conj_key}」，退化为 {rules.DEFAULT_CONJUNCTION}")
        conj_key = rules.DEFAULT_CONJUNCTION
    word = L.conjunction(conj_key, gen.lang)
    lang = gen.lang
    forms = [d for d, _ in pieces]

    if lang == "ja":
        inline = rules.JA_INLINE_CONJ.get(conj_key)
        if inline:
            stem = pieces[0][1]
            if stem:
                return stem + inline + "、".join(forms[1:])
            gen.note(f"日文连接词「{word}」需要前件连用形，模板未提供，"
                     f"已改用句首连接写法")
        return ("。" + word + "、").join(forms)
    if lang != "en":
        w = rules.ZH_CONJ_WRAP.get(conj_key, word)
        return ("，" + w + "，").join(forms)
    return (" " + word + " ").join(forms)


def _reference_obj(eff: EffectSpec, gen: _Gen, params: dict) -> str:
    """取对象之后，处理段该怎么指代它：``那只怪兽`` / ``那张卡`` / ``it``。

    代词要跟**宾语的类别**一致 —— 官方简中实测「那只怪兽」2756 张、
    「那张卡」1037 张、「那只卡」0 张：对象是怪兽就说「那只怪兽」，
    说「那张卡」会串到陷阱/魔法上去。
    """
    if eff.target is None or not _has_target(eff):
        return ""
    if not _bool(params.get("reference"), True):
        return ""
    if str(eff.kind or "") not in rules.TARGET_REF_KINDS:
        return ""
    key = str(params.get("reference_key") or "it")
    words = dict(rules.REFERENCE_PHRASES.get(key, rules.REFERENCE_PHRASES["it"]))
    if key == "it":
        _core, unit = _filter_words(eff.target, gen, params)
        if unit == "monster":
            words = {"zh_cn": "那只怪兽", "ja": "それ", "en": "it"}
        elif unit == "token":
            words = {"zh_cn": "那只衍生物", "ja": "それ", "en": "it"}
    return words.get(gen.lang) or words.get("en") or ""


def _zone_word(eff: EffectSpec, gen: _Gen) -> str:
    """「选」句式里的区域名（``{zone}`` 占位符）。

    优先用 IR 里写的 ``target.from_zone``，缺省时退回效果种类模板自带的
    ``zone`` 元数据（``ssummon_grave`` → GRAVE），避免「从墓地选」写成「从场上选」。
    """
    tgt = eff.target
    zone = str(getattr(tgt, "from_zone", "") or "").upper()
    if not zone:
        meta = rules.EFFECT_TEMPLATES.get(str(eff.kind or "")) or {}
        zone = str(meta.get("zone") or "").upper()
    table = rules.SELECT_ZONE_WORDS.get(zone) or rules.ZONE_WORDS.get(zone)
    if not table:
        return {"zh_cn": "场上", "ja": "フィールド", "en": "field"}[gen.lang]
    return table.get(gen.lang) or table.get("zh_cn") or ""


def _template_ctx(eff: EffectSpec, gen: _Gen, params: dict, kind: str) -> dict:
    """模板占位符上下文（缺键时保留 ``{key}`` 原文，便于发现模板 bug）。"""
    lang = gen.lang
    p = dict(eff.params or {})
    p.update(params or {})
    n = p.get("count") or p.get("n") or p.get("value") or 1
    name = str(p.get("name") or p.get("copy_name") or gen.name())
    arch = _arch_name(gen, p)
    ctx = {
        "obj": _obj_phrase(eff, gen, params=p),
        "objc": _filter_words(eff.target, gen, p)[0],
        "n": _num(n, lang),
        "num": _num(n, lang),
        "value": _num(p.get("value") or n, lang),
        "atk": _num(p.get("atk") or 0, lang),
        "lp": _num(p.get("lp") or 0, lang),
        "name": gen.quote(name) if name else gen.quote(gen.name()),
        "arch": gen.quote(arch) if arch else gen.quote(gen.name()),
        "token": _safe(p.get("token") or "衍生物"),
        "ctr": _safe(p.get("counter") or "指示物"),
        "zone": _zone_word(eff, gen),
    }
    # 历史缺陷（docs/03 §三-c）：特召的对象**永远是怪兽**，filter 缺省时
    # 量词不能沿用「张/枚」。从额外卡组特召会写成「把1张卡特殊召唤」→ 这里正名。
    # 字段/具名宾语同理：`从手卡把1张「星奏」卡特殊召唤` 应为「1只「星奏」怪兽」。
    if kind in rules.SUMMON_KINDS:
        core, unit = _filter_words(eff.target, gen, p)
        if unit == "card":
            if core in ("卡", "card", "カード"):
                core = {"zh_cn": "怪兽", "ja": "モンスター"}.get(lang, "monster")
            elif lang == "ja" and core.endswith("カード"):
                core = core[:-3] + "モンスター"
            elif lang == "en" and core.endswith(" card"):
                core = core[:-5] + " monster"
            elif core.endswith("卡"):
                core = core[:-1] + "怪兽"
            count, cmax = _count_of(eff.target, p)
            ctx["obj"] = _obj_with_count(core, "monster", count or 1, cmax, gen)
    ref = _reference_obj(eff, gen, p)
    if ref and kind == str(eff.kind or ""):
        ctx["obj"] = ref
    # **作用于自己**的效果（「这张卡的攻击力上升300。」）：宾语就是本卡。
    # 官方简中实测 568 张写「这张卡的攻击力上升…」，写「1张卡的攻击力上升…」的有 0 张 ——
    # 而 target 缺省时兜底出来的恰恰是后者，等于凭空造一个不存在的官方句式。
    if _bool(p.get("self_obj"), False) and getattr(eff, "target", None) is None:
        ctx["obj"] = {"ja": "このカード", "en": "this card"}.get(lang, "这张卡")
    return ctx


# ══════════════════════════════════════════════════════════════════════
#  单条效果 → 段落
# ══════════════════════════════════════════════════════════════════════
def _is_continuous(eff: EffectSpec) -> bool:
    p = dict(eff.params or {})
    if _bool(p.get("continuous"), False):
        return True
    if str(eff.trigger or "").upper() == "CONTINUOUS":
        return True
    return str(eff.kind or "") in rules.CONTINUOUS_KINDS


def _optional(eff: EffectSpec) -> bool:
    p = dict(eff.params or {})
    if "optional" in p:
        return _bool(p.get("optional"), True)
    return str(eff.kind or "") not in rules.RULE_TEXT_KINDS


def _paragraph(gen: _Gen, eff: EffectSpec, index: int) -> str:
    lang = gen.lang
    num = rules.number_symbol(index)
    cond = _conditions(eff, gen)
    cost = _cost_parts(eff, gen)
    targeting = _has_target(eff)
    target = _target_phrase(eff, gen) if targeting else ""
    if eff.target is not None and not targeting:
        why = ("永续效果不入连锁，没有「发动时取对象」这一步"
               if _is_continuous(eff) else
               f"效果种类「{eff.kind}」按官方写法在处理时才选卡，不写「以…为对象」")
        gen.note(f"{why}；target 已用作范围描述"
                 f"（如需强制取对象请设 params['targeting']=True）")
    optional = _optional(eff)
    continuous = _is_continuous(eff)
    res = _join_resolution(_resolution_pieces(eff, gen),
                           str((eff.params or {}).get("conjunction")
                               or rules.DEFAULT_CONJUNCTION), gen)

    if lang == "en":
        act: list[str] = []
        if cost["plain"]:
            act.append(cost["plain"])
        if target:
            t = _fmt(rules.TARGET_PHRASE["en"], {"obj": target})
            act.append(t if not act else "then " + t)
        act_text = ", ".join(act)
        head = num + " "
        if continuous and not cond and not act_text:
            return head + ((_cap(res) + ".") if res else "")
        body = ""
        if cond:
            body += _join_conditions_en(cond) + ": "
        if act_text:
            body += ("You can " if optional else "") + act_text + "; "
        elif optional and not continuous:
            body += "You can "
        body += res
        body = body.rstrip()
        if body and not body.endswith("."):
            body += "."
        if _quick(eff, gen) and rules.QUICK_EFFECT_SENTENCE.get("en"):
            body += " " + rules.QUICK_EFFECT_SENTENCE["en"] + "."
        return head + body

    verb = ("発動できる" if optional else "発動する") if lang == "ja" else \
           ("才能发动" if optional else "发动")
    lead = ("、" if lang == "ja" else "，").join(cond)
    head_body = ""
    if lang == "ja":
        if cost["ja_stem"] and target:
            head_body = cost["ja_stem"] + "、" + _fmt(
                rules.TARGET_PHRASE["ja"], {"obj": target}) + verb
        elif cost["ja_te"]:
            head_body = cost["ja_te"] + verb
        elif target:
            head_body = _fmt(rules.TARGET_PHRASE["ja"], {"obj": target}) + verb
    else:
        if cost["plain"] and target:
            head_body = cost["plain"] + "，" + _fmt(
                rules.TARGET_PHRASE[lang], {"obj": target}) + verb
        elif cost["plain"]:
            head_body = cost["plain"] + verb
        elif target:
            head_body = _fmt(rules.TARGET_PHRASE[lang], {"obj": target}) + verb

    segs: list[str] = []
    if lead and head_body:
        segs.append(lead + ("、" if lang == "ja" else "，") + head_body)
    elif head_body:
        segs.append(head_body)
    elif lead and not continuous:
        # 日文：时点词后接「に発動できる」；中文：时点词直接接「才能发动」
        if lang == "ja":
            joiner = "に" if lead.endswith(("時", "場合")) else (
                "" if lead.endswith("に") else "、")
        else:
            joiner = ""
        segs.append(lead + joiner + verb)
    elif lead:
        segs.append(lead)
    if res:
        segs.append(res)
    if _quick(eff, gen) and rules.QUICK_EFFECT_SENTENCE.get(lang):
        # 官方简中收尾句：「这个效果在对方回合也能发动。」
        segs.append(rules.QUICK_EFFECT_SENTENCE[lang])
    prefix = num + "：" if rules.CJK_COLON_MODE == "after_number" else num
    return prefix + "。".join(s for s in segs if s) + "。"


def _join_conditions_en(parts: list[str]) -> str:
    """英文条件段：首项保持原样（首字母大写），其余降为小写接在后面。"""
    out = [parts[0]]
    for p in parts[1:]:
        out.append(_lower_first(p))
    return ", ".join(out)


def _lower_first(text: str) -> str:
    for i, ch in enumerate(text or ""):
        if ch.isascii() and ch.isalpha():
            return text[:i] + ch.lower() + text[i + 1:]
    return text


def effect_to_text(eff: EffectSpec, spec: CardSpec, lang: str = "zh_cn",
                   index: int = 1, *, standalone: bool = False) -> str:
    """把一条效果渲染成一个段落（段首带 ① 编号）。

    :param standalone: True 时把该效果自己的卡名级 HOPT 声明也附在段末。
        ``compose`` 会统一收集声明，故默认 False（避免重复）。
    """
    gen = _Gen(spec, lang)
    text = _paragraph(gen, eff, index)
    if standalone:
        key = rules.hopt_key(eff.limit)
        if key in rules.TRAILING_HOPT_KEYS:
            decl = _declaration(gen, key, [index], total=1)
            if decl:
                text = text + "\n" + decl
    return text


# ══════════════════════════════════════════════════════════════════════
#  HOPT 声明（段末另起一句）
# ══════════════════════════════════════════════════════════════════════
def _declaration(gen: _Gen, key: str, indices: Sequence[int], total: int) -> str:
    """生成一条卡名级 HOPT 声明。``indices`` 是**框内编号**（1 起）。"""
    lang = gen.lang
    name = gen.name()
    idx = sorted({int(i) for i in indices if int(i) > 0})
    if not idx:
        return ""
    numbers = rules.number_symbols(idx)
    all_covered = (len(idx) == total and total > 1
                   and idx == list(range(1, total + 1)))
    if key == "hopt_name_activate" and gen.spec.is_monster:
        # 怪兽用「这个卡名的效果1回合只能发动1次」，魔陷用「「X」1回合只能发动1张」
        text = L.hopt("hopt_name_activate_monster", lang, name, numbers=numbers)
    elif key == "hopt_name_use" and (len(idx) == 1 or not all_covered):
        # 只限制一个效果（或只限制其中一部分）→ 官方用「这个卡名的①的效果…」句式
        text = L.hopt_single(lang, name, numbers)
    else:
        text = L.hopt(key, lang, name, numbers=numbers)
    return _fmt(text, {"n": numbers, "name": gen.quote(name)})


def _declarations(gen: _Gen, effects: Sequence[EffectSpec]) -> list[str]:
    """收集该文本框里所有「独立句 HOPT」声明（固定顺序 + 去重）。"""
    total = len(effects)
    by_key: dict[str, list[int]] = {}
    for i, eff in enumerate(effects, start=1):
        key = rules.hopt_key(eff.limit)
        if key in rules.TRAILING_HOPT_KEYS:
            by_key.setdefault(key, []).append(i)
    out: list[str] = []
    for key in rules.TRAILING_HOPT_KEYS:
        if key in by_key:
            text = _declaration(gen, key, by_key[key], total)
            if text:
                out.append(text)
    return out


# ══════════════════════════════════════════════════════════════════════
#  组装
# ══════════════════════════════════════════════════════════════════════
def _is_pure_normal(spec: CardSpec) -> bool:
    """通常怪兽（文本框里放的是说明文，不是效果文）。"""
    fd = spec.frame_def
    return (fd.is_monster and fd.base == "normal" and not (spec.effects or [])
            and not spec.is_pendulum)


def _box_effects(spec: CardSpec, box: str) -> list[EffectSpec]:
    """该文本框里的效果（灵摆效果按 ``pendulum_effect_indices`` 分流）。"""
    effects = spec.effect_specs()
    pend = {int(i) for i in (spec.pendulum_effect_indices or [])}
    return [eff for i, eff in enumerate(effects) if (i in pend) == (box == BOX_PENDULUM)]


def _pack(gen: _Gen, text: str, box: str, source: str) -> dict:
    # 灵摆卡的「怪兽效果框」比标准怪兽框矮，容量另算
    cap_box = ("pendulum_monster"
               if box == BOX_MONSTER and gen.spec.is_pendulum else box)
    return {
        "text": text,
        "lang": gen.request_lang,
        "used_lang": gen.used_lang,
        "degraded": gen.degraded,
        "reason": gen.reason,
        "notes": list(gen.notes),
        "lines": rules.estimate_lines(text, gen.used_lang, box=cap_box),
        "max_lines": rules.max_lines(cap_box),
        "box": box,
        "source": source,
        "chars": len(text),
    }


def compose_with_meta(spec: CardSpec, lang: str = "zh_cn", *,
                      box: str = BOX_MONSTER) -> dict:
    """生成卡文 + 降级/缺口标注。

    返回 ``{"text","lang","used_lang","degraded","reason","notes","lines",
    "max_lines","box","source","chars"}``。
    """
    gen = _Gen(spec, lang)
    effects = _box_effects(spec, box)
    # 召唤条件（素材行 + 召唤限制）只进「怪兽效果框」；灵摆效果框不重复。
    summon_text = "" if box == BOX_PENDULUM else S.block(spec, lang, ctx=gen)
    if not effects:
        if box == BOX_PENDULUM:
            text = (spec.pendulum_text_in(gen.used_lang)
                    or spec.pendulum_text_in(DEFAULT_LANG))
            if text:
                gen.note("灵摆效果框没有对应的效果 IR，回退到既有文本")
                return _pack(gen, text, box, "existing")
            return _pack(gen, "", box, "ir")
        if _is_pure_normal(spec):
            text = flavor(spec, gen.used_lang) or flavor(spec, DEFAULT_LANG)
            gen.note("通常怪兽的文本框内容是说明文（渲染器用 draw_flavor 绘制，"
                     "不会读 text_i18n）")
            return _pack(gen, text, box, "flavor")
        if summon_text:
            return _pack(gen, summon_text, box, "summon")
        existing = spec.text_in(gen.used_lang) or spec.text_in(DEFAULT_LANG)
        if existing:
            gen.note("没有效果 IR，回退到既有卡文")
            return _pack(gen, existing, box, "existing")
        return _pack(gen, "", box, "ir")

    paras = [_paragraph(gen, eff, i) for i, eff in enumerate(effects, start=1)]
    paras += _declarations(gen, effects)
    body = "\n".join(p for p in paras if p.strip())
    text = (summon_text + "\n" + body) if summon_text else body
    return _pack(gen, text, box, "summon+ir" if summon_text else "ir")


def compose(spec: CardSpec, lang: str = "zh_cn") -> str:
    """汇总所有效果 + HOPT 声明（**怪兽效果框**）。

    灵摆卡的灵摆效果框请用 :func:`compose_pendulum`。
    通常怪兽返回说明文（官方版式里它的文本框就是 flavor）。
    """
    return compose_with_meta(spec, lang, box=BOX_MONSTER)["text"]


def compose_pendulum(spec: CardSpec, lang: str = "zh_cn") -> str:
    """灵摆效果框文本（非灵摆卡返回空串）。"""
    if not spec.is_pendulum:
        return ""
    return compose_with_meta(spec, lang, box=BOX_PENDULUM)["text"]


def compose_all(spec: CardSpec, langs: Iterable[str]) -> dict[str, str]:
    """多语言卡文（怪兽效果框）。

    没有原生模板的语言（ko / zh_tw / de / fr / it / pt / es）**降级到 en**；
    降级信息在 :func:`compose_all_meta` 的 ``used_lang`` / ``reason`` 里。
    """
    return {lg: compose(spec, lg) for lg in (langs or [])}


def compose_all_pendulum(spec: CardSpec, langs: Iterable[str]) -> dict[str, str]:
    """多语言灵摆效果框。"""
    return {lg: compose_pendulum(spec, lg) for lg in (langs or [])}


def compose_all_meta(spec: CardSpec, langs: Iterable[str], *,
                     box: str = BOX_MONSTER) -> dict[str, dict]:
    """多语言 + 每语言的结构化标注（``used_lang`` / ``degraded`` / ``reason``）。"""
    return {lg: compose_with_meta(spec, lg, box=box) for lg in (langs or [])}


def fill_spec(spec: CardSpec, langs: Iterable[str] = ("zh_cn", "ja", "en"),
              *, write_normal_flavor: bool = False) -> dict[str, dict]:
    """生成并**写回** ``spec.text_i18n`` / ``spec.pendulum_text_i18n``。

    通常怪兽默认不写 ``text_i18n``（渲染器对 ``frame=='normal'`` 走
    ``draw_flavor``，写进去只会得到两份一样的文本）。
    """
    out: dict[str, dict] = {}
    pure_normal = _is_pure_normal(spec)
    for lg in (langs or []):
        meta = compose_with_meta(spec, lg, box=BOX_MONSTER)
        out[lg] = dict(meta)
        if meta["text"] and (write_normal_flavor or not pure_normal):
            spec.text_i18n[lg] = meta["text"]
        if spec.is_pendulum:
            pmeta = compose_with_meta(spec, lg, box=BOX_PENDULUM)
            out[lg]["pendulum"] = pmeta
            if pmeta["text"]:
                spec.pendulum_text_i18n[lg] = pmeta["text"]
    return out


# ══════════════════════════════════════════════════════════════════════
#  类型行 / 魔陷标签 / 说明文
# ══════════════════════════════════════════════════════════════════════
def _bracket(text: str, lang: str) -> str:
    return f"【{text}】" if rules.is_cjk(lang) else f"[{text}]"


def _frame_label(key: str, lang: str) -> str:
    item = FRAMES.get(key)
    if item is None:
        return key
    return getattr(item, lang, "") or item.zh_cn


def type_line(spec: CardSpec, lang: str = "zh_cn") -> str:
    """怪兽类型行：``【龙族／效果】`` / ``【ドラゴン族／効果】`` / ``[Dragon / DARK / Effect]``。

    * 官方简中种族**一律带「族」后缀**（``龙族`` 而非 ``龙``）；
    * ``／`` 是全角斜杠（中日文），英文用 `` / ``；
    * 魔陷卡没有类型行，请用 :func:`st_label`。
    """
    fd = spec.frame_def
    if not fd.is_monster:
        return ""
    st = rules.style(lang)
    parts: list[str] = [L.race_term(spec.race, lang),
                        L.attribute_term(spec.attribute, lang)]
    if spec.is_pendulum:
        parts.append(_frame_label("pendulum", lang))
    base = fd.base
    if base not in ("normal", "effect", "token"):
        parts.append(_frame_label(base, lang))
    for tag in (spec.tags or []):
        meta = MONSTER_TAGS.get(str(tag))
        if meta:
            parts.append(meta.get(lang) or meta.get("zh_cn") or str(tag))
    has_effect = bool(spec.effects or []) or base == "effect" or bool(
        spec.is_pendulum and spec.pendulum_effect_indices)
    if base == "normal":
        parts.append(_frame_label("normal", lang))
    elif base == "token":
        parts.append(_frame_label("token", lang))
    elif base == "effect" or has_effect:
        parts.append(_frame_label("effect", lang))
    parts = [p for p in parts if p]
    sep = "／" if st.cjk else " / "
    return _bracket(sep.join(parts), lang)


def st_label(spec: CardSpec, lang: str = "zh_cn") -> str:
    """魔法/陷阱标签：``【速攻魔法】`` / ``[Quick-Play Spell]``；怪兽返回空串。

    非魔陷也非怪兽的卡种（技能卡等）退回类型行的卡种标签。
    """
    if spec.frame == "spell":
        meta = SPELL_KINDS.get(spec.spell_kind) or SPELL_KINDS["normal"]
    elif spec.frame == "trap":
        meta = TRAP_KINDS.get(spec.trap_kind) or TRAP_KINDS["normal"]
    else:
        if spec.is_monster:
            return ""
        label = _frame_label(spec.frame, lang)
        return _bracket(label, lang) if label else ""
    label = meta.get(lang) or meta.get("zh_cn") or ""
    return _bracket(label, lang) if label else ""


def flavor(spec: CardSpec, lang: str = "zh_cn") -> str:
    """说明文。回落链：``lang → zh_cn → 主字段 → ""``。

    **不生成、不臆造**说明文 —— 说明文是作者的创作内容，不是可推导的规则文本。
    """
    for lg in (lang, DEFAULT_LANG):
        v = (spec.flavor_i18n or {}).get(lg)
        if v:
            return str(v).strip()
    return str(spec.flavor or "").strip()


def effect_count_lines(spec: CardSpec, lang: str = "zh_cn") -> dict:
    """文本框占用估算（给 UI 用；估算规则见 :data:`rules.TEXT_BOX`）。"""
    meta = compose_with_meta(spec, lang)
    out = {"lines": meta["lines"], "max_lines": meta["max_lines"],
           "over": meta["lines"] > meta["max_lines"], "box": meta["box"]}
    if spec.is_pendulum:
        pmeta = compose_with_meta(spec, lang, box=BOX_PENDULUM)
        out.update({"pendulum_lines": pmeta["lines"],
                    "pendulum_max_lines": pmeta["max_lines"],
                    "pendulum_over": pmeta["lines"] > pmeta["max_lines"]})
    return out
