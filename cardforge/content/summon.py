"""召唤条件 —— 额外卡组 / 仪式的**素材行 + 召唤限制**。

为什么单独成模块
----------------
素材与召唤限制既是**卡文的第一段**，也是 **Lua 召唤流程的参数**。
两边必须读同一份 :class:`~cardforge.core.models.SummonSpec`，否则又会回到
「卡文写「龙族怪兽」，脚本允许任意怪兽」的老问题。本模块只做**规范化 +
文本投影**；Lua 投影在 :mod:`cardforge.content.lua.fragments`。

文本覆盖
--------
``SummonSpec.text_i18n[lang]`` 有值时整段直接使用作者原文（用于确实无法
用结构化字段表达的怪条件）。结构化字段仍然会进 Lua；生成器会在 notes 里
提示「文本是手写覆盖，脚本只认结构化字段」。

旧版兼容
--------
2.0 之前素材只存在于 ``effects[].params['materials']``。``normalize()`` 会把
它读成 :class:`MaterialPart`，所以旧卡不会因为升级而丢失素材条件。
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..core.models import (
    MATERIAL_KINDS, MATERIAL_LOCKS, MATERIAL_ROLES, SUMMON_LIMITS,
    CardSpec, MaterialPart, SummonSpec,
)
from .psct import lexicon as L
from .psct import rules

__all__ = [
    "normalize", "applies", "frame_kind", "material_line", "condition_lines",
    "block", "compose_meta", "resolve_setcode", "material_name",
    "MATERIAL_TYPE_KEYS", "MATERIAL_TYPE_LABELS", "synchro_roles", "type_key",
    "split_conds", "method_lines", "is_summon_line", "split_leading_block",
    "MATERIAL_KINDS", "MATERIAL_ROLES", "SUMMON_LIMITS", "MATERIAL_LOCKS",
]

#: 「卡种」素材的键 → 术语表里的 card_type 词条
MATERIAL_TYPE_KEYS = {
    "effect": "card_effect_monster",
    "normal": "card_normal_monster",
    "ritual": "card_ritual_monster",
    "fusion": "card_fusion_monster",
    "synchro": "card_synchro_monster",
    "xyz": "card_xyz_monster",
    "link": "card_link_monster",
    "token": "card_token",
    "spirit": "card_spirit",
    "union": "card_union",
    "gemini": "card_gemini",
    "flip": "card_flip",
    "toon": "card_toon",
}
MATERIAL_TYPE_LABELS = {
    "effect": "效果怪兽", "normal": "通常怪兽", "ritual": "仪式怪兽",
    "fusion": "融合怪兽", "synchro": "同步怪兽", "xyz": "超量怪兽",
    "link": "连接怪兽", "token": "衍生物", "spirit": "灵魂怪兽",
    "union": "联合怪兽", "gemini": "二重怪兽", "flip": "反转怪兽",
    "toon": "卡通怪兽",
}
_TYPE_ALIASES = {
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


def type_key(value: Any) -> str:
    """「卡种」素材值 → 规范键（effect/normal/…）；认不出返回空串。"""
    raw = str(value or "").strip()
    return raw if raw in MATERIAL_TYPE_KEYS else _TYPE_ALIASES.get(raw, "")


_type_key = type_key

#: 英文过去分词
_EN_PP = {
    "fusion": "Fusion Summoned", "synchro": "Synchro Summoned",
    "xyz": "Xyz Summoned", "link": "Link Summoned", "ritual": "Ritual Summoned",
}

_FULLWIDTH = str.maketrans("0123456789", "０１２３４５６７８９")


def _num(value: Any, lang: str) -> str:
    s = str(value)
    return s.translate(_FULLWIDTH) if lang == "ja" else s


def _quote(name: Any, lang: str) -> str:
    return L.quote(str(name or "").strip(), lang)


def applies(spec: CardSpec) -> bool:
    """这张卡是否该有召唤条件段（额外卡组或仪式怪兽）。"""
    fd = spec.frame_def
    return bool(fd.extra_deck or fd.base == "ritual")


def frame_kind(spec: CardSpec) -> str:
    return str(spec.frame_def.base or "")


# ══════════════════════════════════════════════════════════════════════
#  规范化（含旧版 params['materials'] 迁移）
# ══════════════════════════════════════════════════════════════════════
def _legacy_parts(spec: CardSpec) -> list[MaterialPart]:
    """把旧版 ``effects[].params['materials']`` 读成 MaterialPart。"""
    for eff in spec.effect_specs():
        if not str(eff.kind or "").endswith("_summon"):
            continue
        raw = (eff.params or {}).get("materials")
        if not raw:
            continue
        parts: list[MaterialPart] = []
        for item in raw:
            if isinstance(item, str):
                parts.append(MaterialPart(kind="archetype", value=item))
            elif isinstance(item, dict):
                fk = str(item.get("filter_kind") or "any")
                fv = item.get("filter_value")
                kind = {"field": "archetype"}.get(fk, fk)
                if kind not in MATERIAL_KINDS:
                    kind = "any"
                parts.append(MaterialPart(kind=kind, value=fv))
        if not parts:
            continue
        base = frame_kind(spec)
        # 旧版 Xyz 的 params['count'] 是素材数量；Fusion/Synchro 没有这个语义。
        if base == "xyz" and len(parts) == 1:
            try:
                parts[0].count = max(1, int((eff.params or {}).get("count") or 2))
            except Exception:
                parts[0].count = 2
        # 旧版 Synchro 的单个过滤器是「协调」过滤器。
        if base == "synchro" and len(parts) == 1:
            parts[0].tuner = "tuner"
            parts.append(MaterialPart(kind="any", tuner="non_tuner",
                                      count=1, count_max=99))
        return parts
    return []


def normalize(spec: CardSpec) -> SummonSpec:
    """取规范化的 SummonSpec（不修改 ``spec``；旧版素材会迁移进来）。"""
    raw = getattr(spec, "summon", None)
    if isinstance(raw, SummonSpec):
        s = SummonSpec.from_dict(raw.to_dict())
    else:
        s = SummonSpec.from_dict(raw or {})
    if not s.parts():
        s.materials = _legacy_parts(spec)
    return s


def resolve_setcode(spec: CardSpec, part: MaterialPart) -> str:
    """素材字段 → Lua 可用的 setcode 字面量（解析失败返回空串）。

    规则：
    * 显式 ``part.setcode`` 优先；
    * 素材字段名与卡自己的字段同名 → 用 ``spec.setcode``；
    * 素材值本身写成 ``0x1234`` → 直接用。
    """
    raw = str(part.setcode or "").strip()
    if not raw and str(part.value or "").strip() == str(spec.archetype or "").strip():
        raw = str(spec.setcode or "").strip()
    if not raw and str(part.value or "").strip().lower().startswith("0x"):
        raw = str(part.value).strip()
    if not raw or raw in ("0", "0x0", "0X0"):
        return ""
    import re
    tok = re.search(r"0[xX][0-9a-fA-F]+|\d+", raw)
    if not tok:
        return ""
    try:
        v = int(tok.group(0), 16) if tok.group(0).lower().startswith("0x") \
            else int(tok.group(0))
    except Exception:
        return ""
    return hex(v) if v > 0 else ""


def material_name(part: MaterialPart, lang: str) -> str:
    """素材名（卡名/字段名）的该语言写法；缺译名时回落原文。"""
    name = str(part.value or "").strip()
    table = part.name_i18n or {}
    return str(table.get(lang) or table.get("zh_cn") or name)


# ══════════════════════════════════════════════════════════════════════
#  文本上下文
# ══════════════════════════════════════════════════════════════════════
class _Ctx:
    def __init__(self, spec: CardSpec, lang: str):
        self.spec = spec
        self.request_lang = lang or "zh_cn"
        self.used_lang, self.reason = L.generation_lang(self.request_lang)
        self.notes: list[str] = []
        if self.reason:
            self.notes.append(self.reason)

    @property
    def lang(self) -> str:
        return self.used_lang

    def note(self, msg: str) -> None:
        if msg and msg not in self.notes:
            self.notes.append(msg)


# ══════════════════════════════════════════════════════════════════════
#  素材短语（中文）
# ══════════════════════════════════════════════════════════════════════
def _zh_type(key: str) -> str:
    k = _type_key(key)
    term = L.card_type_term(MATERIAL_TYPE_KEYS.get(k, ""), "zh_cn")
    return term or MATERIAL_TYPE_LABELS.get(k, "怪兽")


# ── 一段素材的多条件拆分（官方写法：一段里可以叠多个筛选）──────────────
#: 官方例：「包含「六武众」怪兽的战士族怪兽2只」（六武众的军大将）、
#: 「包含魔法师族·4星怪兽的怪兽2只」（圣月之魔导士 恩底弥翁）。
#: 也就是说**卡名/字段 + 种族/属性/卡种/等级**是**同一段**素材的条件，
#: 不是两段各 N 只 —— 拆成两段会把数量翻倍（脚本会要 6 只）。
_NAMED_KINDS = ("name", "archetype")


def split_conds(part: MaterialPart) -> tuple[list, list]:
    """素材段 → ``(具名条件, 其它筛选条件)``。"""
    named: list[MaterialPart] = []
    quals: list[MaterialPart] = []
    for c in part.conditions():
        kind = str(c.kind or "any")
        if kind in _NAMED_KINDS:
            named.append(c)
        elif kind == "any":
            continue
        else:
            quals.append(c)
    return named, quals


def _is_multi(part: MaterialPart) -> bool:
    """这一段是否叠了 2 个以上筛选条件（决定要不要走「包含…的…」句式）。"""
    named, quals = split_conds(part)
    return bool(named) and bool(quals)


def _zh_qual_word(c: MaterialPart) -> str:
    """单个非具名条件的中文修饰词（不带中心词「怪兽」）。"""
    kind, value = str(c.kind or ""), c.value
    if kind == "race":
        vals = value if isinstance(value, (list, tuple)) else [value]
        names = [L.race_term(str(v), "zh_cn") for v in vals if str(v or "").strip()]
        return "·".join([n for n in names if n])
    if kind == "attribute":
        vals = value if isinstance(value, (list, tuple)) else [value]
        names = [L.attribute_term(str(v), "zh_cn") for v in vals if str(v or "").strip()]
        return "·".join([n for n in names if n])
    if kind == "type":
        word = _zh_type(str(value or ""))
        return word[:-2] if word.endswith("怪兽") else word
    if kind == "level":
        return f"{_num(value, 'zh_cn')}星"
    if kind == "rank":
        return f"{_num(value, 'zh_cn')}阶"
    return ""


def _zh_named_word(c: MaterialPart, ctx: _Ctx) -> str:
    """具名条件（卡名/字段）的中文写法；字段带「怪兽」，单卡名不带。"""
    q = _quote(material_name(c, "zh_cn"), "zh_cn")
    return q if str(c.kind or "") == "name" else f"{q}怪兽"


def _zh_core(part: MaterialPart, ctx: _Ctx) -> str:
    named, quals = split_conds(part)
    words = [w for w in (_zh_qual_word(c) for c in quals) if w]
    head = ("·".join(words) if words else "") + "怪兽"
    if named and words:
        inner = " ".join(_zh_named_word(c, ctx) for c in named)
        return f"包含{inner}的{head}"
    if named:
        if len(named) == 1 and str(named[0].kind or "") == "name":
            return _quote(material_name(named[0], "zh_cn"), "zh_cn")
        return "".join(_zh_named_word(c, ctx) for c in named)
    if words:
        return head
    return "怪兽"


def _zh_filter(part: MaterialPart, ctx: _Ctx) -> str:
    core = _zh_core(part, ctx)
    is_name = str(part.kind or "") == "name" and not _is_multi(part)
    role = str(part.tuner or "")
    if role == "tuner" and not is_name:
        if str(part.kind or "") == "type":
            core = core + "的协调"
        else:
            core = core[:-2] + "协调" if core.endswith("怪兽") else core + "协调"
    elif role == "non_tuner" and not is_name:
        core = "协调以外的" + core
    if part.exclude_token:
        core = "衍生物以外的" + core
    if part.include_link:
        core = "包含连接怪兽的" + core
    if part.exclude_link:
        core = "连接怪兽以外的" + core
    return core


def _count_zh(part: MaterialPart, base: str, *, style: str) -> str:
    """把数量后缀接到中文素材短语上。style: fusion/xyz/link/synchro。"""
    lo, hi = part.count_lo, part.count_hi
    is_name = str(part.kind or "") == "name"
    if style in ("xyz",):
        if hi and hi >= 99:
            return f"{base}×{_num(lo, 'zh_cn')}只以上"
        if hi:
            return f"{base}×{_num(lo, 'zh_cn')}～{_num(hi, 'zh_cn')}只"
        return f"{base}×{_num(lo, 'zh_cn')}"
    if style == "link":
        # 连接素材的上限由连接值决定；卡文统一写「N 只以上」，
        # 只有「恰好 N 只」才省略「以上」。
        if is_name:
            if hi:
                return f"{base}{_num(lo, 'zh_cn')}只以上"
            return f"{base}×{_num(lo, 'zh_cn')}"
        if hi:
            return f"{base}{_num(lo, 'zh_cn')}只以上"
        return f"{base}{_num(lo, 'zh_cn')}只"
    if style == "synchro":
        if is_name and lo == 1 and not hi:
            return base
        if hi and hi >= 99:
            return f"{base}{_num(lo, 'zh_cn')}只以上"
        if hi:
            return f"{base}{_num(lo, 'zh_cn')}～{_num(hi, 'zh_cn')}只"
        if lo == 1:
            return base
        return f"{base}{_num(lo, 'zh_cn')}只"
    # fusion 的单个素材段
    if is_name:
        if hi and hi >= 99:
            return f"{base}{_num(lo, 'zh_cn')}只以上"
        if hi:
            return f"{base}{_num(lo, 'zh_cn')}～{_num(hi, 'zh_cn')}只"
        return f"{base}×{_num(lo, 'zh_cn')}" if lo > 1 else base
    if hi and hi >= 99:
        return f"{base}{_num(lo, 'zh_cn')}只以上"
    if hi:
        return f"{base}{_num(lo, 'zh_cn')}～{_num(hi, 'zh_cn')}只"
    if lo > 1:
        return f"{base}×{_num(lo, 'zh_cn')}"
    return base


# ══════════════════════════════════════════════════════════════════════
#  素材短语（日文）
# ══════════════════════════════════════════════════════════════════════
def _ja_type(key: str) -> str:
    k = _type_key(key)
    return L.card_type_term(MATERIAL_TYPE_KEYS.get(k, ""), "ja") or "モンスター"


def _ja_qual_word(c: MaterialPart) -> str:
    kind, value = str(c.kind or ""), c.value
    if kind == "race":
        vals = value if isinstance(value, (list, tuple)) else [value]
        names = [L.race_term(str(v), "ja") for v in vals if str(v or "").strip()]
        return "・".join([n for n in names if n])
    if kind == "attribute":
        vals = value if isinstance(value, (list, tuple)) else [value]
        names = [L.attribute_term(str(v), "ja") for v in vals if str(v or "").strip()]
        return ("・".join([n for n in names if n]) + "属性") if names else ""
    if kind == "type":
        word = _ja_type(str(value or ""))
        return word[:-len("モンスター")] if word.endswith("モンスター") else word
    if kind == "level":
        return f"レベル{_num(value, 'ja')}"
    if kind == "rank":
        return f"ランク{_num(value, 'ja')}"
    return ""


def _ja_named_word(c: MaterialPart) -> str:
    q = _quote(material_name(c, "ja"), "ja")
    return q if str(c.kind or "") == "name" else f"{q}モンスター"


def _ja_core(part: MaterialPart) -> str:
    named, quals = split_conds(part)
    words = [w for w in (_ja_qual_word(c) for c in quals) if w]
    head = ("・".join(words) if words else "") + "モンスター"
    if named and words:
        # 官方：「「六武衆」モンスターを含む戦士族モンスター」
        inner = " ".join(_ja_named_word(c) for c in named)
        return f"{inner}を含む{head}"
    if named:
        if len(named) == 1 and str(named[0].kind or "") == "name":
            return _quote(material_name(named[0], "ja"), "ja")
        return "".join(_ja_named_word(c) for c in named)
    if words:
        return head
    return "モンスター"


def _ja_filter(part: MaterialPart) -> str:
    core = _ja_core(part)
    is_name = str(part.kind or "") == "name" and not _is_multi(part)
    role = str(part.tuner or "")
    if role == "tuner" and not is_name:
        if str(part.kind or "") == "type":
            core = core + "のチューナー"
        elif core.endswith("モンスター"):
            core = core[:-len("モンスター")] + "チューナー"
        else:
            core = core + "チューナー"
    elif role == "non_tuner" and not is_name:
        core = "チューナー以外の" + core
    if part.exclude_token:
        core = "トークン以外の" + core
    if part.include_link:
        core = "リンクモンスターを含む" + core
    if part.exclude_link:
        core = "リンクモンスター以外の" + core
    return core


def _count_ja(part: MaterialPart, base: str, *, style: str) -> str:
    lo, hi = part.count_lo, part.count_hi
    is_name = str(part.kind or "") == "name"
    unit = "体"
    if style == "xyz":
        if hi and hi >= 99:
            return f"{base}×{_num(lo, 'ja')}以上"
        if hi:
            return f"{base}×{_num(lo, 'ja')}～{_num(hi, 'ja')}"
        return f"{base}×{_num(lo, 'ja')}"
    if style == "link":
        if is_name:
            if hi:
                return f"{base}{_num(lo, 'ja')}{unit}以上"
            return f"{base}×{_num(lo, 'ja')}"
        if hi:
            return f"{base}{_num(lo, 'ja')}{unit}以上"
        return f"{base}{_num(lo, 'ja')}{unit}"
    if style == "synchro":
        if is_name and lo == 1 and not hi:
            return base
        if hi and hi >= 99:
            return f"{base}{_num(lo, 'ja')}{unit}以上"
        if hi:
            return f"{base}{_num(lo, 'ja')}～{_num(hi, 'ja')}{unit}"
        if lo == 1:
            return base
        return f"{base}{_num(lo, 'ja')}{unit}"
    # fusion
    if is_name:
        if hi and hi >= 99:
            return f"{base}{_num(lo, 'ja')}{unit}以上"
        if hi:
            return f"{base}{_num(lo, 'ja')}～{_num(hi, 'ja')}{unit}"
        return f"{base}×{_num(lo, 'ja')}" if lo > 1 else base
    if hi and hi >= 99:
        return f"{base}{_num(lo, 'ja')}{unit}以上"
    if hi:
        return f"{base}{_num(lo, 'ja')}～{_num(hi, 'ja')}{unit}"
    if lo > 1:
        return f"{base}×{_num(lo, 'ja')}"
    return base


# ══════════════════════════════════════════════════════════════════════
#  素材短语（英文）
# ══════════════════════════════════════════════════════════════════════
def _plural_en(word: str, plural: bool) -> str:
    if not plural or not word:
        return word
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if word.endswith("Monster"):
        return word[:-len("Monster")] + "Monsters"
    if word.endswith("monster"):
        return word[:-len("monster")] + "monsters"
    return word + "s"


def _en_type(key: str, plural: bool) -> str:
    k = _type_key(key)
    term = L.card_type_term(MATERIAL_TYPE_KEYS.get(k, ""), "en") or "Monster"
    return _plural_en(term, plural)


def _en_qual_word(c: MaterialPart, plural: bool) -> str:
    kind, value = str(c.kind or ""), c.value
    if kind == "race":
        vals = value if isinstance(value, (list, tuple)) else [value]
        names = [L.race_term(str(v), "en") for v in vals if str(v or "").strip()]
        return "/".join([n for n in names if n])
    if kind == "attribute":
        vals = value if isinstance(value, (list, tuple)) else [value]
        names = [L.attribute_term(str(v), "en") for v in vals if str(v or "").strip()]
        return "/".join([n for n in names if n])
    if kind == "type":
        word = _en_type(str(value or ""), plural)
        for tail in (" Monsters", " monsters", " Monster", " monster"):
            if word.endswith(tail):
                return word[:-len(tail)]
        return word
    if kind == "level":
        return f"Level {value}"
    if kind == "rank":
        return f"Rank {value}"
    return ""


_EN_QUAL_ORDER = ("level", "rank", "attribute", "race", "type")


def _en_named_word(c: MaterialPart) -> str:
    q = _quote(material_name(c, "en"), "en")
    return q if str(c.kind or "") == "name" else f"{q} monster"


def _en_including_phrase(named: list) -> str:
    """官方英文「2 monsters including a \"Six Samurai\" monster」那半句。"""
    parts = []
    for c in named:
        q = _quote(material_name(c, "en"), "en")
        parts.append(q if str(c.kind or "") == "name" else f'a {q} monster')
    return " and ".join(parts)


def _en_core(part: MaterialPart, plural: bool) -> str:
    named, quals = split_conds(part)
    ordered = sorted(quals, key=lambda c: _EN_QUAL_ORDER.index(str(c.kind or ""))
                     if str(c.kind or "") in _EN_QUAL_ORDER else 99)
    words = [w for w in (_en_qual_word(c, plural) for c in ordered) if w]
    head = " ".join(words + [_plural_en("monster", plural)])
    if named and words:
        return f"{head} including {_en_including_phrase(named)}"
    if named:
        if len(named) == 1 and str(named[0].kind or "") == "name":
            return _quote(material_name(named[0], "en"), "en")
        return " ".join(_en_named_word(c) for c in named)
    if words:
        return head
    return _plural_en("monster", plural)


def _en_filter(part: MaterialPart, plural: bool) -> str:
    core = _en_core(part, plural)
    is_name = str(part.kind or "") == "name" and not _is_multi(part)
    role = str(part.tuner or "")
    if role == "tuner" and not is_name:
        if str(part.kind or "") == "type":
            core = core.replace("Monster", "Tuner monster") if "Monster" in core \
                else "Tuner " + core
        elif core.endswith("Monsters"):
            core = core[:-len("Monsters")] + "Tuners"
        elif core.endswith("monsters"):
            core = core[:-len("monsters")] + "Tuners"
        elif core.endswith("Monster"):
            core = core[:-len("Monster")] + "Tuner"
        elif core.endswith("monster"):
            core = core[:-len("monster")] + "Tuner"
        else:
            core = core + " Tuner"
    elif role == "non_tuner" and not is_name:
        core = "non-Tuner " + core
    if part.exclude_token:
        core = "non-Token " + core
    if part.exclude_link:
        core = "non-Link " + core
    return core


def _en_count(part: MaterialPart, base: str, *, style: str) -> str:
    lo, hi = part.count_lo, part.count_hi
    is_name = str(part.kind or "") == "name"
    plural = lo > 1 or bool(hi)
    if style == "xyz":
        if hi and hi >= 99:
            return f"{lo}+ {base}"
        if hi:
            return f"{lo} to {hi} {base}"
        return f"{lo} {base}"
    if style == "link":
        if is_name:
            return f"{lo}+ {base}" if hi else (f"{lo} {base}" if lo > 1 else base)
        return f"{lo}+ {base}" if hi else f"{lo} {base}"
    if style == "synchro":
        if is_name and lo == 1 and not hi:
            return base
        if hi and hi >= 99:
            return f"{lo}+ {base}"
        if hi:
            return f"{lo} to {hi} {base}"
        return f"{lo} {base}"
    # fusion
    if is_name:
        if hi and hi >= 99:
            return f"{lo}+ {base}"
        if hi:
            return f"{lo} to {hi} {base}"
        return " + ".join([base] * lo) if lo > 1 else base
    if hi and hi >= 99:
        return f"{lo}+ {base}"
    if hi:
        return f"{lo} to {hi} {base}"
    return f"{lo} {base}" if lo > 1 else base


# ══════════════════════════════════════════════════════════════════════
#  素材行
# ══════════════════════════════════════════════════════════════════════
def synchro_roles(parts: list[MaterialPart], ctx: Optional[_Ctx] = None) -> tuple:
    tuners = [p for p in parts if str(p.tuner or "") == "tuner"]
    nontuners = [p for p in parts if str(p.tuner or "") == "non_tuner"]
    if not tuners and not nontuners:
        # 没标角色：按官方惯性把第一段当协调、第二段当协调以外
        tuners = [parts[0]] if parts else []
        nontuners = parts[1:2]
        if parts and ctx is not None:
            ctx.note("同调素材没有标记协调/协调以外，已按「第一段=协调、第二段=协调以外」生成")
    elif not tuners and nontuners:
        if ctx is not None:
            ctx.note("同调素材没有协调段，素材行会用通用的「协调」补位")
    elif not nontuners and len(parts) >= 2:
        nontuners = [parts[1]]
        if ctx is not None:
            ctx.note("同调素材没有「协调以外」段，已把第二段当作非协调")
    return (tuners[0] if tuners else None,
            nontuners[0] if nontuners else None)


def _notify_missing_names(s: SummonSpec, ctx: _Ctx) -> None:
    if ctx.lang == "zh_cn":
        return
    for p in s.parts():
        if str(p.kind or "") not in ("name", "archetype"):
            continue
        if (p.name_i18n or {}).get(ctx.lang):
            continue
        ctx.note(f"素材「{p.value}」缺 {ctx.lang} 译名，已用中文原名")


def _xyz_base_zh(spec: CardSpec, p: MaterialPart, ctx: _Ctx) -> str:
    rank = spec.effective_level
    if str(p.kind or "") in ("level", "rank"):
        return _zh_filter(p, ctx)
    if str(p.kind or "") == "name":
        core = f"{_num(rank, 'zh_cn')}星{_quote(material_name(p, 'zh_cn'), 'zh_cn')}"
    else:
        core = _zh_core(p, ctx)
        if str(p.kind or "") == "type":
            core = f"{_num(rank, 'zh_cn')}星{core}"
        elif core.endswith("怪兽"):
            core = core[:-2] + f"{_num(rank, 'zh_cn')}星怪兽"
        else:
            core = f"{_num(rank, 'zh_cn')}星{core}"
    if p.exclude_token:
        core = "衍生物以外的" + core
    if p.include_link:
        core = "包含连接怪兽的" + core
    if p.exclude_link:
        core = "连接怪兽以外的" + core
    return core


def _xyz_base_ja(spec: CardSpec, p: MaterialPart) -> str:
    rank = spec.effective_level
    if str(p.kind or "") in ("level", "rank"):
        return _ja_filter(p)
    word = f"レベル{_num(rank, 'ja')}"
    if str(p.kind or "") == "name":
        core = f"{word}{_quote(material_name(p, 'ja'), 'ja')}"
    else:
        core = _ja_core(p)
        if str(p.kind or "") == "type":
            core = f"{word}{core}"
        elif core.endswith("モンスター"):
            core = core[:-len("モンスター")] + f"{word}モンスター"
        else:
            core = f"{word}{core}"
    if p.exclude_token:
        core = "トークン以外の" + core
    if p.include_link:
        core = "リンクモンスターを含む" + core
    if p.exclude_link:
        core = "リンクモンスター以外の" + core
    return core


def _xyz_base_en(spec: CardSpec, p: MaterialPart, plural: bool) -> str:
    rank = spec.effective_level
    if str(p.kind or "") in ("level", "rank"):
        return _en_filter(p, plural)
    word = f"Level {rank}"
    if str(p.kind or "") == "name":
        core = f"{word} {_quote(material_name(p, 'en'), 'en')}"
    else:
        tail = _en_core(p, plural)
        core = f"{word} {tail}"
    if p.exclude_token:
        core = "non-Token " + core
    if p.include_link:
        core = core + ", including a Link Monster"
    if p.exclude_link:
        core = "non-Link " + core
    return core


def _material_line_zh(spec: CardSpec, s: SummonSpec, ctx: _Ctx) -> str:
    base = frame_kind(spec)
    parts = s.parts()
    _notify_missing_names(s, ctx)
    if base == "ritual":
        return _ritual_line(s, ctx)
    if not parts:
        return ""
    if base == "fusion":
        return "＋".join(_count_zh(p, _zh_filter(p, ctx), style="fusion") for p in parts)
    if base == "synchro":
        tuner, non = synchro_roles(parts, ctx)
        out = []
        if tuner:
            out.append(_count_zh(tuner, _zh_filter(tuner, ctx), style="synchro"))
        else:
            out.append("协调")
        if non:
            out.append(_count_zh(non, _zh_filter(non, ctx), style="synchro"))
        else:
            out.append("协调以外的怪兽1只以上")
        return "＋".join(out)
    if base == "xyz":
        p = parts[0]
        return _count_zh(p, _xyz_base_zh(spec, p, ctx), style="xyz")
    if base == "link":
        p = parts[0]
        if p.count_hi >= 99 and spec.effective_level and spec.effective_level <= p.count_lo:
            p.count_max = 0
        return _count_zh(p, _zh_filter(p, ctx), style="link")
    return ""


def _material_line_ja(spec: CardSpec, s: SummonSpec, ctx: _Ctx) -> str:
    base = frame_kind(spec)
    parts = s.parts()
    _notify_missing_names(s, ctx)
    if base == "ritual":
        return _ritual_line(s, ctx)
    if not parts:
        return ""
    if base == "fusion":
        return "＋".join(_count_ja(p, _ja_filter(p), style="fusion") for p in parts)
    if base == "synchro":
        tuner, non = synchro_roles(parts, ctx)
        out = []
        if tuner:
            out.append(_count_ja(tuner, _ja_filter(tuner), style="synchro"))
        else:
            out.append("チューナー")
        if non:
            out.append(_count_ja(non, _ja_filter(non), style="synchro"))
        else:
            out.append("チューナー以外のモンスター１体以上")
        return "＋".join(out)
    if base == "xyz":
        p = parts[0]
        return _count_ja(p, _xyz_base_ja(spec, p), style="xyz")
    if base == "link":
        p = parts[0]
        if p.count_hi >= 99 and spec.effective_level and spec.effective_level <= p.count_lo:
            p.count_max = 0
        return _count_ja(p, _ja_filter(p), style="link")
    return ""


def _material_line_en(spec: CardSpec, s: SummonSpec, ctx: _Ctx) -> str:
    base = frame_kind(spec)
    parts = s.parts()
    _notify_missing_names(s, ctx)
    if base == "ritual":
        return _ritual_line(s, ctx)
    if not parts:
        return ""
    if base == "fusion":
        return " + ".join(_en_count(p, _en_filter(p, p.count_lo > 1 or bool(p.count_hi)),
                                    style="fusion") for p in parts)
    if base == "synchro":
        tuner, non = synchro_roles(parts, ctx)
        out = []
        if tuner:
            plural = tuner.count_lo > 1 or bool(tuner.count_hi)
            out.append(_en_count(tuner, _en_filter(tuner, plural), style="synchro"))
        else:
            out.append("1 Tuner")
        if non:
            plural = non.count_lo > 1 or bool(non.count_hi)
            out.append(_en_count(non, _en_filter(non, plural), style="synchro"))
        else:
            out.append("1+ non-Tuner monsters")
        return " + ".join(out)
    if base == "xyz":
        p = parts[0]
        plural = p.count_lo > 1 or bool(p.count_hi)
        return _en_count(p, _xyz_base_en(spec, p, plural), style="xyz")
    if base == "link":
        p = parts[0]
        if p.count_hi >= 99 and spec.effective_level and spec.effective_level <= p.count_lo:
            p.count_max = 0
        plural = p.count_lo > 1 or bool(p.count_hi)
        out = _en_count(p, _en_filter(p, plural), style="link")
        if p.include_link and "including a Link Monster" not in out:
            out += ", including a Link Monster"
        return out
    return ""


def _ritual_line(s: SummonSpec, ctx: _Ctx) -> str:
    name = str(s.ritual_spell or "").strip()
    if not name:
        ctx.note("仪式怪兽没有填写仪式魔法卡名，卡文第一行（降临条件）留空")
        return ""
    lang = ctx.lang
    q = _quote(name, lang)
    if s.ritual_spell_archetype:
        if lang == "ja":
            return f"{q}儀式魔法カードにより降臨"
        if lang == "en":
            return f"You can Ritual Summon this card with any {q} Ritual Spell."
        return f"{q}仪式魔法卡降临"
    if lang == "ja":
        return f"{q}により降臨"
    if lang == "en":
        return f"You can Ritual Summon this card with {q}."
    return f"{q}降临"


def material_line(spec: CardSpec, lang: str = "zh_cn") -> str:
    """素材行 / 仪式降临行（不含召唤限制）。"""
    s = normalize(spec)
    if not applies(spec):
        return ""
    ctx = _Ctx(spec, lang)
    override = s.text_i18n.get(ctx.request_lang) or s.text_i18n.get(ctx.used_lang)
    if override:
        first = str(override).strip().splitlines()
        return first[0].strip() if first else ""
    if ctx.lang == "ja":
        return _material_line_ja(spec, s, ctx)
    if ctx.lang == "en":
        return _material_line_en(spec, s, ctx)
    return _material_line_zh(spec, s, ctx)


# ══════════════════════════════════════════════════════════════════════
#  召唤限制行
# ══════════════════════════════════════════════════════════════════════
_LOCK_TEXT = {
    "zh_cn": {
        "fusion": "这张卡不能作为融合素材。",
        "synchro": "这张卡不能作为同步素材。",
        "xyz": "这张卡不能作为超量召唤的素材。",
        "link": "这张卡不能作为连接素材。",
    },
    "ja": {
        "fusion": "このカードは融合素材にできない。",
        "synchro": "このカードはシンクロ素材にできない。",
        "xyz": "このカードはエクシーズ召喚の素材にできない。",
        "link": "このカードはリンク素材にできない。",
    },
    "en": {
        "fusion": "Cannot be used as Fusion Material.",
        "synchro": "Cannot be used as Synchro Material.",
        "xyz": "Cannot be used as material for an Xyz Summon.",
        "link": "Cannot be used as Link Material.",
    },
}


#: 「以下方法」条目里，素材怎么处理
_ACTION_TEXT = {
    "zh_cn": {"banish": "除外", "send_gy": "送去墓地", "release": "解放",
              "return_deck": "回到卡组", "return_hand": "回到手卡"},
    "ja": {"banish": "除外した", "send_gy": "墓地へ送った", "release": "リリースした",
           "return_deck": "デッキに戻した", "return_hand": "手札に戻した"},
    "en": {"banish": "banishing", "send_gy": "sending to the GY",
           "release": "releasing", "return_deck": "returning to the Deck",
           "return_hand": "returning to the hand"},
}
#: 素材从哪个区域取
_ZONE_TEXT = {
    "zh_cn": {"mz": "自己场上", "field": "自己场上", "hand": "自己手卡",
              "gy": "自己墓地", "field_gy": "自己场上·墓地",
              "hand_field": "自己手卡·场上"},
    "ja": {"mz": "自分フィールド", "field": "自分フィールド", "hand": "自分手札",
           "gy": "自分墓地", "field_gy": "自分フィールド・墓地",
           "hand_field": "自分手札・フィールド"},
    "en": {"mz": "your field", "field": "your field", "hand": "your hand",
           "gy": "your GY", "field_gy": "your field or GY",
           "hand_field": "your hand or field"},
}
#: 「不需要「融合」」那类补注
_NO_SPELLING_TEXT = {
    "zh_cn": "（不需要「融合」）",
    "ja": "（「融合」は必要としない）",
    "en": ' (do not activate "Polymerization")',
}
_UNIT_TEXT = {"zh_cn": "只", "ja": "体", "en": ""}


def _method_target(m, lang: str, spec: CardSpec, ctx: _Ctx) -> str:
    """``●`` 条目里的素材短语（「上记的卡」或自定义筛选）。"""
    fallback = {"zh_cn": "上记的卡", "ja": "上記のカード",
                "en": "the above cards"}.get(lang, "上记的卡")
    if m.use_materials:
        return fallback
    parts = m.item_parts()
    if not parts:
        return fallback
    if lang == "ja":
        return "と".join(_ja_filter(p) for p in parts)
    if lang == "en":
        return " and ".join(_en_filter(p, p.count_lo > 1) for p in parts)
    return "和".join(_zh_filter(p, ctx) for p in parts)


def method_lines(spec: CardSpec, s: SummonSpec, lang: str,
                 ctx: Optional[_Ctx] = None) -> list[str]:
    """「以下方法」的 ``●`` 条目（官方把它们单列一行，接在召唤限制后面）。"""
    ctx = ctx or _Ctx(spec, lang)
    lang = ctx.lang
    out: list[str] = []
    for i, m in enumerate(s.item_methods()):
        override = (m.text_i18n or {}).get(ctx.request_lang) or \
            (m.text_i18n or {}).get(lang)
        if override:
            line = str(override).strip()
            out.append(line if line.startswith("●") else "●" + line)
            continue
        action = _ACTION_TEXT.get(lang, {}).get(str(m.action or "banish"), "")
        zone = _ZONE_TEXT.get(lang, {}).get(str(m.zone or "mz"), "")
        if not action or not zone:
            ctx.note(f"额外召唤方法用了未登记的处理/区域"
                     f"（action={m.action} zone={m.zone}），第 {i + 1} 条已跳过")
            continue
        target = _method_target(m, lang, spec, ctx)
        unit = _UNIT_TEXT.get(lang, "")
        cnt = (f"{_num(m.count_lo, lang)}{unit}" if m.count_lo else "")
        if lang == "en":
            line = (f"● Special Summon this card from your Extra Deck by "
                    f"{action} {cnt}{target} from {zone}")
            out.append(line + (_NO_SPELLING_TEXT["en"] if m.no_spelling else "") + ".")
            continue
        if lang == "ja":
            tail = "特殊召喚できる"
            line = f"●{zone}の{cnt}{target}を{action}場合、エクストラデッキから{tail}"
            out.append(line + (_NO_SPELLING_TEXT["ja"] if m.no_spelling else "") + "。")
            continue
        line = f"●把{zone}的{cnt}{target}{action}的场合可以从额外卡组特殊召唤"
        out.append(line + (_NO_SPELLING_TEXT["zh_cn"] if m.no_spelling else "") + "。")
    return out


def _limit_lines(spec: CardSpec, s: SummonSpec, lang: str) -> list[str]:
    base = frame_kind(spec)
    out: list[str] = []
    if s.cannot_normal_summon:
        out.append({"zh_cn": "这张卡不能通常召唤。",
                    "ja": "このカードは通常召喚できない。",
                    "en": "Cannot be Normal Summoned/Set."}.get(lang, ""))
    for lock in s.cannot_be_material or []:
        txt = _LOCK_TEXT.get(lang, {}).get(str(lock), "")
        if txt:
            out.append(txt)
    methods = bool(s.item_methods())
    if s.limit == "cannot_spsummon":
        out.append({"zh_cn": "这张卡不能特殊召唤。",
                    "ja": "このカードは特殊召喚できない。",
                    "en": "Cannot be Special Summoned."}.get(lang, ""))
    elif s.limit in ("must_be", "must_be_with_materials"):
        with_mats = s.limit == "must_be_with_materials" and bool(s.parts())
        if lang == "ja":
            word = {
                "fusion": ("融合召喚", "融合素材"),
                "synchro": ("シンクロ召喚", "シンクロ素材"),
                "xyz": ("エクシーズ召喚", "エクシーズ素材"),
                "link": ("リンク召喚", "リンク素材"),
                "ritual": ("儀式召喚", "儀式素材"),
            }.get(base)
            if word:
                if methods:
                    head = (f"上記のカードを{word[1]}にした{word[0]}"
                            if with_mats else word[0])
                    out.append(f"このカードは{head}、"
                               f"または以下の方法でのみ特殊召喚できる。")
                elif with_mats:
                    out.append(f"このカードは上記のカードを{word[1]}にした"
                               f"{word[0]}でしか特殊召喚できない。")
                else:
                    out.append(f"このカードは{word[0]}でしか特殊召喚できない。")
        elif lang == "en":
            pp = _EN_PP.get(base, "")
            mats = {
                "fusion": "Fusion Materials", "synchro": "Synchro Materials",
                "xyz": "Xyz Materials", "link": "Link Materials",
                "ritual": "Ritual Materials",
            }.get(base, "Materials")
            if pp:
                if methods:
                    head = f"with the above {mats} " if with_mats else ""
                    line = (f"Must be {pp} {head}or Special Summoned "
                            f"by the following method.")
                    out.append(" ".join(line.split()))
                elif with_mats:
                    out.append(f"Must be {pp} with the above {mats} and cannot "
                               f"be Special Summoned by other ways.")
                else:
                    out.append(f"Must be {pp} and cannot be Special Summoned "
                               f"by other ways.")
        else:
            word = {
                "fusion": ("融合召唤", "融合素材"),
                "synchro": ("同步召唤", "同步素材"),
                "xyz": ("超量召唤", "超量素材"),
                "link": ("连接召唤", "连接素材"),
                "ritual": ("仪式召唤", "仪式素材"),
            }.get(base)
            if word:
                if methods:
                    head = (f"用以上记的卡为{word[1]}的{word[0]}"
                            if with_mats else word[0])
                    out.append(f"这张卡用{head}以及以下方法才能特殊召唤。")
                elif with_mats:
                    out.append(f"这张卡用以上记的卡为{word[1]}的{word[0]}"
                               f"才能特殊召唤。")
                else:
                    out.append(f"这张卡不用{word[0]}不能特殊召唤。")
    return [x for x in out if x]


def condition_lines(spec: CardSpec, lang: str = "zh_cn") -> list[str]:
    """召唤限制行 + 「以下方法」条目（官方顺序：不能通常召唤 → 素材锁定 →
    召唤方式限制 → ``●`` 各条）。"""
    s = normalize(spec)
    if not applies(spec):
        return []
    ctx = _Ctx(spec, lang)
    if s.text_i18n.get(ctx.request_lang) or s.text_i18n.get(ctx.used_lang):
        return []
    out = _limit_lines(spec, s, ctx.used_lang)
    out += method_lines(spec, s, ctx.used_lang, ctx)
    return out


# ══════════════════════════════════════════════════════════════════════
#  反向：从卡文里认出召唤条件段
# ══════════════════════════════════════════════════════════════════════
#: 素材行 / 降临行的形状（官方：素材行永远是卡文第一段，且不带句号）
_MATERIAL_LINE_RES: tuple[re.Pattern, ...] = (
    re.compile(r"^「.{1,24}」\s*[＋+]"),                  # 「A」＋「B」
    re.compile(r"[＋+].{0,30}(?:怪兽|モンスター|monsters)", re.I),
    re.compile(r"怪兽\s*[×x]\s*[０-９\d]"),                # 怪兽×3
    re.compile(r"(?:怪兽|モンスター)\s*[０-９\d]*\s*(?:只|体|枚)?以上"),
    re.compile(r"^包含「.{1,20}」"),                      # 包含「X」怪兽的Y怪兽
    re.compile(r"^(?:[０-９\d]+(?:星|阶级|等级|レベル|Rank|Level)).{0,24}"
               r"(?:怪兽|モンスター|monsters)", re.I),      # 8星怪兽×2 / 10星怪兽×3
    re.compile(r"(降临|降臨)\s*。?$|Ritual Summon"),        # 「「XX」降临」
    re.compile(r"モンスター\s*[×x]\s*[０-９\d]"),
    re.compile(r"^[０-９\d].{0,40}monsters", re.I),
)
#: 召唤限制 / 素材锁定 / ● 条目
_LIMIT_LINE_RES: tuple[re.Pattern, ...] = (
    re.compile(r"这张卡不能通常召唤|このカードは通常召喚できない|"
               r"Cannot be Normal Summoned"),
    re.compile(r"这张卡不能特殊召唤|このカードは特殊召喚できない"),
    re.compile(r"不能作为.{0,8}素材|素材にできない|Cannot be used as"),
    re.compile(r"(才能|才可以)特殊召唤|でしか特殊召喚できない|でのみ特殊召喚できる|"
               r"または以下の方法|Must be (Fusion|Synchro|Xyz|Link|Ritual) Summoned"),
    re.compile(r"^●"),
)
_PARA_HEAD_RE = re.compile(r"^\s*[①②③④⑤⑦⑧⑨]")


def is_summon_line(line: str) -> bool:
    """这一行是召唤条件段（素材行 / 限制行 / ● 条目）吗。"""
    s = str(line or "").strip()
    if not s:
        return False
    return any(r.search(s) for r in _MATERIAL_LINE_RES) or \
        any(r.search(s) for r in _LIMIT_LINE_RES)


def split_leading_block(text: str) -> tuple[str, str]:
    """把卡文开头的召唤条件段切出来 → ``(召唤条件段, 剩下的效果文本)``。

    为什么需要它：卡文第一段是 :func:`block` 从 ``spec.summon`` 投影出来的
    **产物**，不是一条效果。以前把它交给 ``effects.infer_from_text`` 反解，
    「…才能特殊召唤。」会被读成 ① ``must_first_ssummon``，于是用户把官方卡文
    贴回来重新生成，卡面凭空多出一条没人写的效果（实测就是这张卡踩的坑）。
    """
    lines = (text or "").splitlines()
    head: list[str] = []
    i = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            if head:
                continue
            break
        if _PARA_HEAD_RE.match(s) or not is_summon_line(s):
            break
        head.append(s)
    else:
        i = len(lines)
    if not head:
        return "", text or ""
    consumed = len(head)
    # 空行不算内容，但要一并吃掉，避免剩下的文本以空行开头
    rest_lines = lines[consumed:]
    while rest_lines and not rest_lines[0].strip():
        rest_lines.pop(0)
    return "\n".join(head), "\n".join(rest_lines)


# ══════════════════════════════════════════════════════════════════════
#  整段
# ══════════════════════════════════════════════════════════════════════
def block(spec: CardSpec, lang: str = "zh_cn", *, ctx: Optional[_Ctx] = None) -> str:
    """卡文最前面的召唤条件段（素材行 + 限制行，行间用 ``\\n``）。"""
    s = normalize(spec)
    if not applies(spec):
        return ""
    ctx = ctx or _Ctx(spec, lang)
    override = s.text_i18n.get(ctx.request_lang) or s.text_i18n.get(ctx.used_lang)
    if override:
        if hasattr(ctx, "note"):
            ctx.note("召唤条件使用手写覆盖；Lua 只认结构化字段，请核对两边一致")
        return str(override).strip()
    material = ""
    if ctx.lang == "ja":
        material = _material_line_ja(spec, s, ctx)
    elif ctx.lang == "en":
        material = _material_line_en(spec, s, ctx)
    else:
        material = _material_line_zh(spec, s, ctx)
    lines = ([material] if material else []) + _limit_lines(spec, s, ctx.lang)
    lines += method_lines(spec, s, ctx.lang, ctx)
    return "\n".join(x for x in lines if x.strip())


def compose_meta(spec: CardSpec, lang: str = "zh_cn") -> dict:
    """给生成器/预览接口用的结构化结果（与 ``psct.gen`` 的 meta 同形）。"""
    ctx = _Ctx(spec, lang)
    s = normalize(spec)
    if s.text_i18n.get(ctx.request_lang) or s.text_i18n.get(ctx.used_lang):
        ctx.note("召唤条件是手写覆盖；Lua 只认结构化字段，请核对两边一致")
        ctx.used_lang = ctx.request_lang
        ctx.reason = ""
    text = block(spec, lang, ctx=ctx)
    return {
        "text": text,
        "lang": ctx.request_lang,
        "used_lang": ctx.used_lang,
        "degraded": bool(ctx.reason),
        "reason": ctx.reason,
        "notes": list(ctx.notes),
        "lines": rules.estimate_lines(text, ctx.used_lang),
        "chars": len(text),
    }
