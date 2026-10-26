"""PSCT 规则表 —— **生成器与校验器共用的唯一规则来源**。

为什么要单独一个文件
--------------------
``gen.py``（结构化 IR → 卡文）与 ``lint.py``（卡文 → 问题清单）必须共用同一套
规则，否则"生成器写出来的东西被自己的校验器判错"是必然的。本模块只放**数据与
结构**，不放算法：

* 语言风格（标点／是否用分号／全角数字／引号）——从 ``core.enums.LANGS`` 派生，
  不另立一套。
* 标点三段式、连接词四象限、HOPT 六种写法、编号符号——来自
  ``data/lexicons/psct_patterns.json``（本文件是它的**结构化镜像 + 兜底**，
  运行时以 JSON 为准，见 ``lexicon.patterns()``）。
* 效果句式模板（IR 的 ``kind`` → 多语言句子）。
* 校验规则清单 ``LINT_RULES``（code / level / message / hint）。

规则来源（逐条可回溯）
----------------------
* ``research/PSCT与制卡方法论调研报告.md`` A1（标点语义）、A2（连接词四象限）、
  A3.2（时 vs 场合）、A5（取对象）、A6（HOPT 三写法）、A7.1（旧术语）、
  A8.1（错误清单 E01–E28）、A9.1（字段引用）、E1–E4（可编码清单）。
* ``data/lexicons/psct_patterns.json``（标点／连接词／HOPT／编号的机器可读版）。
* Konami PSCT Part 3 / Part 7 原文与 Yugipedia 汇总（经上述调研报告转述）。

已知不确定项（**不要当成官方定论**）
------------------------------------
1. 中文/日文官方卡文**不使用「；」**，这一点由 ``LANGS[*].uses_semicolon=False``
   与调研报告 B1.2 支持；但"日文是否绝对不用分号"调研报告标注为**未找到明文规定**
   （F1 第 12 项），属推论。
2. 中文/日文的编号后置冒号（``①：``）是 OCG 版式惯例；调研报告 A1.1 把冒号定义为
   "条件与后续之间的分隔"（英文 PSCT 语义）。两者在排版上并不完全等价，
   故本模块提供 :data:`CJK_COLON_MODE` 开关，默认 ``"after_number"``（照 OCG 版式）。
3. 日文连接词的**活用形**：官方把 ``and`` 写作「〜し、」、``and if you do`` 写作
   「〜し、その場合、」，都要求前件用连用形。本模块的 ja 模板用 ``|`` 分隔
   "辞書形|連用形"，能取到连用形时才用句内连接，取不到时退化为句首连接词。
4. 卡文长度容量是**渲染版面估算**，不是官方规定（见 :data:`TEXT_BOX`）。
"""
from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

from ...core.enums import LANGS

# ══════════════════════════════════════════════════════════════════════
#  0. 语言分组与全局开关
# ══════════════════════════════════════════════════════════════════════

#: 中日韩文字系统（用「：」「。」不加空格，断行按字）
CJK_LANGS: tuple[str, ...] = ("zh_cn", "zh_tw", "ja")
#: 生成器**原生模板**覆盖的语言（其余语言降级，见 ``degraded_reason``）
NATIVE_GEN_LANGS: tuple[str, ...] = ("zh_cn", "ja", "en")
#: 降级候选：术语表覆盖率低到不足以拼出可信句子 —— 一律回落到 en 并在返回值留痕
LOW_COVERAGE_LANGS: tuple[str, ...] = ("ko",)
#: 术语覆盖率低于该值即视为"不能硬造"，生成时降级
COVERAGE_FLOOR = 0.90

#: 中日文编号后置冒号的两种版式：``after_number`` = ``①：条件…``（OCG 版式，默认）；
#: ``after_conditions`` = ``条件：发动…``（照调研报告 A1.1 的字面读法）。
CJK_COLON_MODE = "after_number"

#: 编号符号（①–⑳）。``psct_patterns.numbering.symbols`` 只给到 ⑩。
NUMBER_SYMBOLS: str = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
#: 扩展编号（㉑–㉟，U+3251–U+325F）。官方卡文不会用到，但 DIY 可能写出来 ——
#: 识别它们才能让「编号超过 ⑳」这条 ERROR 真正可触发。
NUMBER_EXTENDED: str = "㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟"
#: 供 linter 复用的字符类（含扩展编号）
RE_NUMBER_CHARS: str = f"[{NUMBER_SYMBOLS}{NUMBER_EXTENDED}]"
#: 数据文件明确列出的编号上限（超过只报 WARN，不报 ERROR）
NUMBER_DOCUMENTED_MAX = 10
#: 硬上限（超过报 ERROR）
NUMBER_MAX = len(NUMBER_SYMBOLS)
#: 括号编号别名（``(1)`` / ``（1）``）
ASCII_NUMBER_ALIASES: tuple[str, ...] = ("(1)", "(2)", "(3)", "(4)", "(5)")


def number_value(ch: str) -> int:
    """``①`` → 1、``㉑`` → 21；无法识别返回 0。"""
    for table in (NUMBER_SYMBOLS, NUMBER_EXTENDED):
        i = table.find(ch)
        if i >= 0:
            return i + 1 + (20 if table is NUMBER_EXTENDED else 0)
    return 0


def number_symbol(index: int) -> str:
    """1 → ``①``。21–35 用扩展编号；越界时返回 ``(n)`` 形式，**不抛异常**。"""
    try:
        i = int(index)
    except Exception:
        return str(index)
    if 1 <= i <= len(NUMBER_SYMBOLS):
        return NUMBER_SYMBOLS[i - 1]
    if len(NUMBER_SYMBOLS) < i <= len(NUMBER_SYMBOLS) + len(NUMBER_EXTENDED):
        return NUMBER_EXTENDED[i - len(NUMBER_SYMBOLS) - 1]
    return f"({i})"


def number_symbols(indices: Iterable[int]) -> str:
    """``[1, 2]`` → ``①②``（用于「这个卡名的①②效果…」的引用串）。"""
    return "".join(number_symbol(i) for i in indices)


# ══════════════════════════════════════════════════════════════════════
#  1. 语言风格（标点 / 数字 / 引号）
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class LangStyle:
    """一种语言在卡文里的排版风格。``uses_semicolon`` 直接取自 ``core.enums``。"""

    lang: str
    cjk: bool
    uses_semicolon: bool
    colon: str = "："
    semi: str = "；"
    period: str = "。"
    comma: str = "，"
    enum_comma: str = "、"
    quote_open: str = "「"
    quote_close: str = "」"
    full_width_numeral: bool = True
    accent: str = ""            # 需要保留音调的西文（本引擎不处理，留字段）

    @property
    def joiner(self) -> str:
        """句中并列成分的连接符（中文/日文用「，」，英文用 ", "）。"""
        return self.comma if self.cjk else ", "

    @property
    def enum_joiner(self) -> str:
        return self.enum_comma if self.cjk else ", "


def _style(lang: str) -> LangStyle:
    spec = LANGS.get(lang)
    cjk = bool(spec and spec.wrap == "cjk")
    if cjk:
        return LangStyle(lang=lang, cjk=True,
                         uses_semicolon=bool(spec.uses_semicolon) if spec else False)
    return LangStyle(lang=lang, cjk=False,
                     uses_semicolon=bool(spec.uses_semicolon) if spec else True,
                     colon=":", semi=";", period=".", comma=", ",
                     enum_comma=", ", quote_open='"', quote_close='"',
                     full_width_numeral=False)


LANG_STYLE: dict[str, LangStyle] = {k: _style(k) for k in LANGS}


def style(lang: str) -> LangStyle:
    """取语言风格；未知语言按英文处理（**不抛异常**）。"""
    return LANG_STYLE.get(lang) or _style(lang)


def is_cjk(lang: str) -> bool:
    return style(lang).cjk


# ══════════════════════════════════════════════════════════════════════
#  2. 三段式结构（CONDITIONS ： ACTIVATION ； RESOLUTION）
# ══════════════════════════════════════════════════════════════════════
STRUCTURE_TEMPLATE = "CONDITIONS : ACTIVATION ; RESOLUTION"

SEGMENTS = (
    {"role": "conditions", "separator": ":", "zh_cn": "发动条件",
     "ja": "発動条件", "en": "conditions",
     "contains": ("when / if timing", "once per turn", "activation requirement",
                  "optional 'you can'")},
    {"role": "activation", "separator": ";", "zh_cn": "发动时要做的事",
     "ja": "発動時にすること", "en": "activation",
     "contains": ("cost", "target")},
    {"role": "resolution", "separator": ".", "zh_cn": "效果处理",
     "ja": "効果の処理", "en": "resolution", "contains": ("what actually happens",)},
)

#: 标点角色 → 各语言符号（与 psct_patterns.json 的 punctuation 同构）
PUNCT_ROLES = (
    "condition_separator", "activation_separator", "sentence_terminator",
    "parenthesis", "bulleted_effect", "effect_number",
)


def punctuation_of(lang: str) -> dict[str, str]:
    """该语言的角色 → 符号表（数据文件缺失时的内置版）。"""
    st = style(lang)
    return {
        "condition_separator": st.colon,
        "activation_separator": st.semi,
        "sentence_terminator": st.period,
        "parenthesis": "（）" if st.cjk else "()",
        "bulleted_effect": "●",
        "effect_number": "①",
    }


# ══════════════════════════════════════════════════════════════════════
#  3. 连接词四象限（PSCT Part 7；``also, after that`` 为 2014 年实装）
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Conjunction:
    key: str
    en: str
    ja: str
    zh_cn: str
    resolution_order: str        # sequential | simultaneous
    both_required: bool
    requires_a_for_b: bool
    aborts_b_if_a_fails: bool
    note: str = ""

    def text(self, lang: str) -> str:
        if lang == "ja":
            return self.ja
        if lang in ("zh_cn", "zh_tw"):
            return self.zh_cn
        return self.en


CONJUNCTIONS: dict[str, Conjunction] = {c.key: c for c in (
    Conjunction("and", "and", "し", "并且", "simultaneous", True, False, False,
                "同时处理且两者都必需（全有或全无）。官方指其罕见。"),
    Conjunction("then", "then", "その後", "那之后", "sequential", False, True, True,
                "B 在 A 之后；A 是 B 的前提，反之不然。会挡住 WHEN 触发。"),
    Conjunction("also", "also", "また", "此外", "simultaneous", False, False, False,
                "视为同时处理，互不为前提，能做到多少做多少。"),
    Conjunction("and_if_you_do", "and if you do", "その場合", "那个场合",
                "simultaneous", True, True, True,
                "时间轴上等同 and，因果上等同 then（A 是 B 的前提）。"),
    Conjunction("also_after_that", "also, after that", "また、その後",
                "此外，那之后", "sequential", False, False, False,
                "依次处理，互不为前提（2014 年引入，PSCT 原文未讨论）。"),
)}
CONJUNCTION_KEYS: tuple[str, ...] = tuple(CONJUNCTIONS)

#: 生成器默认连接词（一条效果被拆成两段处理时的缺省语义）
DEFAULT_CONJUNCTION = "then"

#: 连接词四象限网格（与 psct_patterns.json 的 conjunction_quadrants 同构）
CONJUNCTION_QUADRANTS = (
    {"resolution_order": "sequential", "neither_required": "also_after_that",
     "a_required_for_b": "then", "both_required": None},
    {"resolution_order": "simultaneous", "neither_required": "also",
     "a_required_for_b": "and_if_you_do", "both_required": "and"},
)

#: 日文连接词的句内连接形态（需要前件连用形）
JA_INLINE_CONJ = {"and": "、", "and_if_you_do": "、その場合、"}
#: 日文连接词的句首连接形态（前件用辞书形即可）
JA_SENTENCE_CONJ = {"then": "その後、", "also": "また、",
                    "also_after_that": "また、その後、"}
#: 中文连接词的句中写法
ZH_CONJ_WRAP = {"and": "并且", "then": "那之后", "also": "此外",
                "and_if_you_do": "那个场合", "also_after_that": "此外，那之后"}

#: 英文连接词（用于扫描）
EN_CONJUNCTIONS: tuple[str, ...] = ("and if you do", "also, after that", "then",
                                    "also", "and")


# ══════════════════════════════════════════════════════════════════════
#  4. HOPT 三种写法（必须区分，绝不合并）
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class HoptSpec:
    key: str
    zh_cn: str
    ja: str
    en: str
    scope: str
    strictness: str              # apply < activate < use
    placement: str               # activation_condition | separate_sentence
    reset_on_leave: bool
    note: str = ""
    number_slot: bool = False    # 句子里的 ①② 需要按实际编号替换
    name_slot: bool = False      # 句子里的 X 需要按实际卡名替换

    def text(self, lang: str) -> str:
        if lang == "ja":
            return self.ja
        if lang in ("zh_cn", "zh_tw"):
            return self.zh_cn
        return self.en


HOPT_SPECS: dict[str, HoptSpec] = {h.key: h for h in (
    HoptSpec("once_per_turn", "1回合1次，", "１ターンに１度、", "Once per turn:",
             "this_card", "activate", "activation_condition", True,
             "限制这一张卡本身；离场或翻里侧后重置。写在冒号之前的发动条件里。"),
    HoptSpec("hopt_name_use", "这个卡名的①②的效果1回合各能使用1次。",
             "このカード名の①②の効果はそれぞれ１ターンに１度しか使用できない。",
             'You can only use each effect of "X" once per turn.',
             "player_and_original_name", "use", "separate_sentence", False,
             "限制玩家 + 原本卡名；离场/翻里侧都不重置。最严格的一档。",
             number_slot=True, name_slot=True),
    HoptSpec("hopt_name_activate", "「X」1回合只能发动1张。",
             "「X」は１ターンに１枚しか発動できない。",
             'You can only activate 1 "X" per turn.',
             "player_and_original_name", "activate", "separate_sentence", False,
             "同名卡合计 1 次发动；本次发动被无效则本回合仍可再发动另一张。",
             name_slot=True),
    HoptSpec("hopt_name_activate_monster", "这个卡名的效果1回合只能发动1次。",
             "このカード名の効果は１ターンに１度しか発動できない。",
             'You can only activate this effect of "X" once per turn.',
             "player_and_original_name", "activate", "separate_sentence", False,
             "怪兽卡用「这个卡名的效果1回合只能发动1次」；"
             "魔法/陷阱卡用「「X」1回合只能发动1张」（data/lexicons 的官方句式）。",
             name_slot=True),
    HoptSpec("hopt_name_apply", "这个卡名的效果1场决斗中只能适用1次。",
             "このカード名の効果はデュエル中に１度しか適用できない。",
             'You can only apply this effect of "X" once per Duel.',
             "player_and_original_name", "apply", "separate_sentence", False,
             "最宽松的一档：效果被改写或无效后仍可再次尝试。", name_slot=True),
    HoptSpec("hopt_gain_effect_once", "（这个效果1回合只能获得1次。）",
             "（この効果は１ターンに１度しか得られない。）",
             "(You can only gain this effect once per turn.)",
             "player", "gain", "separate_sentence", False,
             "限制玩家，与卡名无关（如追加通常召唤类效果）。"),
    HoptSpec("hopt_once_while_face_up", "这张卡在怪兽区域表侧表示存在的场合，1次",
             "このカードがモンスターゾーンに表側表示で存在する場合に１度",
             "Once while face-up on the field:",
             "this_card", "use", "activation_condition", True,
             "旧句式「This effect can only be used once while face-up…」的现行写法。"),
)}

#: ``EffectSpec.limit`` → HOPT 规格键（IR 里 ``hopt_name`` 是 ``hopt_name_use`` 的别名）
LIMIT_ALIASES: dict[str, str] = {
    "hopt_name": "hopt_name_use",
    "hopt_name_each": "hopt_name_use",
    "once_per_turn": "once_per_turn",
    "hopt_name_activate": "hopt_name_activate",
    "hopt_name_apply": "hopt_name_apply",
    "hopt_gain_effect_once": "hopt_gain_effect_once",
    "once_while_faceup": "hopt_once_while_face_up",
    "once_duel": "hopt_name_apply",
}
#: 写在"独立句子"里的 HOPT（段末声明），与写在发动条件里的相对
TRAILING_HOPT_KEYS: tuple[str, ...] = ("hopt_name_use", "hopt_name_activate",
                                       "hopt_name_apply", "hopt_gain_effect_once")
#: 写在"发动条件"里的 HOPT
INLINE_HOPT_KEYS: tuple[str, ...] = ("once_per_turn", "hopt_once_while_face_up")


def hopt_key(limit: str) -> str:
    """把 ``EffectSpec.limit`` 归一化成 HOPT 规格键；``none``/空 → ``""``。"""
    key = (limit or "").strip()
    if not key or key == "none":
        return ""
    return LIMIT_ALIASES.get(key, key if key in HOPT_SPECS else "")


# ══════════════════════════════════════════════════════════════════════
#  5. 时点关键词（时 vs 场合 / When vs If）
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class TimingWord:
    key: str            # when | if
    zh_cn: str
    ja: str
    en: str
    strictness: str
    note: str = ""


TIMING_WORDS: dict[str, TimingWord] = {t.key: t for t in (
    TimingWord("when", "时", "時", "When", "strict",
               "只在该事件是「最后发生的事」时才能发动（会错过时点）。"),
    TimingWord("if", "的场合", "場合", "If", "loose",
               "只问「是否发生过」，不会错过时点。"),
)}

#: 触发条件 → 时点档（默认严格档 when；``params['timing']='if'`` 可覆盖）
TRIGGER_TIMING_DEFAULT: dict[str, str] = {
    "WHEN_DESTROYED": "when",
    "WHEN_SENT_GRAVE": "when",
    "WHEN_BANISHED": "when",
    "WHEN_TO_HAND": "when",
    "NORMAL_SUMMON_SUCCESS": "when",
    "SPECIAL_SUMMON_SUCCESS": "when",
    "SUMMON_ANY_SUCCESS": "when",
    "FLIP_SUMMON": "when",
    "ON_ACTIVATE": "when",
    "BATTLE_DESTROY_SELF": "when",
    "BATTLE_DESTROYED_SELF": "when",
    "ATTACK_DECLARE": "when",
    "OPPONENT_ACTIVATE": "when",
    "DAMAGE_STEP_START": "when",
    "END_PHASE": "phase",
    "STANDBY_PHASE": "phase",
    "EQUIP_RELATED": "when",
}


# ══════════════════════════════════════════════════════════════════════
#  6. 触发条件短语（发动条件段）
# ══════════════════════════════════════════════════════════════════════
#: ``EffectSpec.trigger`` → 三段式里的"条件"段。日文留 ``|`` 便于统一处理（此处不用）。
TRIGGER_PHRASES: dict[str, dict[str, str]] = {
    "IGNITION": {"zh_cn": "自己主要阶段", "ja": "自分メインフェイズに",
                 "en": "During your Main Phase"},
    "QUICK": {"zh_cn": "对方主要阶段", "ja": "相手メインフェイズに",
              "en": "During your opponent's Main Phase (Quick Effect)"},
    "CONTINUOUS": {"zh_cn": "", "ja": "", "en": ""},
    "NORMAL_SUMMON_SUCCESS": {"zh_cn": "这张卡召唤成功时",
                              "ja": "このカードが召喚に成功した時",
                              "en": "When this card is Normal Summoned"},
    "SPECIAL_SUMMON_SUCCESS": {"zh_cn": "这张卡特殊召唤成功时",
                               "ja": "このカードが特殊召喚に成功した時",
                               "en": "When this card is Special Summoned"},
    "SUMMON_ANY_SUCCESS": {"zh_cn": "这张卡召唤·特殊召唤成功时",
                           "ja": "このカードが召喚・特殊召喚に成功した時",
                           "en": "When this card is Normal or Special Summoned"},
    "FLIP_SUMMON": {"zh_cn": "这张卡反转召唤成功时",
                    "ja": "このカードが反転召喚に成功した時",
                    "en": "When this card is Flip Summoned"},
    "WHEN_DESTROYED": {"zh_cn": "这张卡被破坏时", "ja": "このカードが破壊された時",
                       "en": "When this card is destroyed"},
    "WHEN_SENT_GRAVE": {"zh_cn": "这张卡被送去墓地时",
                        "ja": "このカードが墓地へ送られた時",
                        "en": "When this card is sent to the GY"},
    "WHEN_BANISHED": {"zh_cn": "这张卡被除外时", "ja": "このカードが除外された時",
                      "en": "When this card is banished"},
    "WHEN_TO_HAND": {"zh_cn": "这张卡加入手卡时",
                     "ja": "このカードが手札に加わった時",
                     "en": "When this card is added to your hand"},
    "ON_ACTIVATE": {"zh_cn": "魔法·陷阱·怪兽的效果发动时",
                    "ja": "魔法・罠・モンスターの効果が発動した時",
                    "en": "When a Spell/Trap Card or effect is activated"},
    "DAMAGE_STEP_START": {"zh_cn": "伤害步骤开始时",
                          "ja": "ダメージステップ開始時に",
                          "en": "At the start of the Damage Step"},
    "BATTLE_DESTROY_SELF": {"zh_cn": "这张卡战斗破坏对方怪兽时",
                            "ja": "このカードが戦闘で相手モンスターを破壊した時",
                            "en": "When this card destroys an opponent's monster by battle"},
    "BATTLE_DESTROYED_SELF": {"zh_cn": "这张卡被战斗破坏时",
                              "ja": "このカードが戦闘で破壊された時",
                              "en": "When this card is destroyed by battle"},
    "ATTACK_DECLARE": {"zh_cn": "对方怪兽攻击宣言时",
                       "ja": "相手モンスターの攻撃宣言時",
                       "en": "When an opponent's monster declares an attack"},
    "OPPONENT_ACTIVATE": {"zh_cn": "对方发动效果时",
                          "ja": "相手が効果を発動した時",
                          "en": "When your opponent activates a card or effect"},
    "END_PHASE": {"zh_cn": "结束阶段", "ja": "エンドフェイズに", "en": "During the End Phase"},
    "STANDBY_PHASE": {"zh_cn": "准备阶段", "ja": "スタンバイフェイズに",
                      "en": "During the Standby Phase"},
    "EQUIP_RELATED": {"zh_cn": "这张卡被装备时", "ja": "このカードが装備された時",
                      "en": "When this card is equipped"},
    "OPPONENT_ACTIVATE_MONSTER": {"zh_cn": "对方把怪兽的效果发动时",
                                  "ja": "相手がモンスターの効果を発動した時",
                                  "en": "When your opponent activates a monster effect"},
}
#: 「表侧表示」限定（官方：「以对方场上1张表侧表示的卡为对象」）——
#: 作为**前缀**接在宾语短语前面（种族/属性等条件保留）。
FACEUP_WORDS: dict[str, str] = {
    "zh_cn": "表侧表示的", "ja": "表側表示の", "en": "face-up",
}
#: 诱发即时效果的收尾句（官方简中：「这个效果在对方回合也能发动。」）
QUICK_EFFECT_SENTENCE: dict[str, str] = {
    "zh_cn": "这个效果在对方回合也能发动",
    "ja": "この効果は相手ターンでも発動できる",
    "en": "This is a Quick Effect",
}
#: 「战斗·效果破坏」那类破坏方式限定（配合 ``params['destroyed_by']``）。
#: 每项 = ``(when 档, if 档)``；官方简中区分「…时」与「…的场合」。
DESTROYED_BY_PHRASES: dict[str, dict[str, tuple[str, str]]] = {
    "battle_effect": {
        "zh_cn": ("这张卡被战斗·效果破坏时", "这张卡被战斗·效果破坏的场合"),
        "ja": ("このカードが戦闘・効果で破壊された時",
               "このカードが戦闘・効果で破壊された場合"),
        "en": ("When this card is destroyed by battle or card effect",
               "If this card is destroyed by battle or card effect"),
    },
    "battle": {
        "zh_cn": ("这张卡被战斗破坏时", "这张卡被战斗破坏的场合"),
        "ja": ("このカードが戦闘で破壊された時", "このカードが戦闘で破壊された場合"),
        "en": ("When this card is destroyed by battle",
               "If this card is destroyed by battle"),
    },
    "effect": {
        "zh_cn": ("这张卡被效果破坏时", "这张卡被效果破坏的场合"),
        "ja": ("このカードがカードの効果で破壊された時",
               "このカードがカードの効果で破壊された場合"),
        "en": ("When this card is destroyed by card effect",
               "If this card is destroyed by card effect"),
    },
}
#: 触发时点缺失时（E04）用于判断"该写时点却没写"
TRIGGER_MARKERS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("时", "场合", "阶段"),
    "ja": ("時", "場合", "フェイズ"),
    "en": ("When", "If", "During", "Phase", "Step"),
}

#: 时点档 when → if 的机械改写规则（zh/ja/en）
TIMING_REWRITE: dict[str, tuple[tuple[str, str], ...]] = {
    "zh_cn": (("成功时", "成功的场合"), ("时", "的场合")),
    "ja": (("時", "場合"),),
    "en": (("When ", "If "),),
}


def retime(phrase: str, lang: str, timing: str) -> str:
    """把条件短语从 when 档改写成 if 档（``timing='if'``）。"""
    if timing != "if" or not phrase:
        return phrase
    out = phrase
    for old, new in TIMING_REWRITE.get(lang, ()):
        if old in out:
            out = out.replace(old, new, 1)
            break
    return out


# ══════════════════════════════════════════════════════════════════════
#  7. 代价短语（发动段；中文/日文靠语序，写在「发动/発動」之前）
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class CostPhrase:
    key: str
    zh_cn: str
    en: str
    ja: str = ""          # 连用形（〜し / 〜て 的前件）
    ja_te: str = ""       # 「〜して」形（后面没有别的成分时用）
    note: str = ""


COST_PHRASES: dict[str, CostPhrase] = {c.key: c for c in (
    CostPhrase("none", "", "", "", ""),
    CostPhrase("release", "把{obj}解放", "Tribute {obj}",
               "{obj}をリリースし", "{obj}をリリースして"),
    CostPhrase("tribute_self", "把这张卡解放", "Tribute this card",
               "このカードをリリースし", "このカードをリリースして"),
    CostPhrase("discard", "把{obj}丢弃", "discard {obj}",
               "{obj}を捨て", "{obj}を捨てて"),
    CostPhrase("discard_self", "把这张卡丢弃", "discard this card",
               "このカードを捨て", "このカードを捨てて"),
    CostPhrase("send_grave", "把{obj}送去墓地", "send {obj} to the GY",
               "{obj}を墓地へ送り", "{obj}を墓地へ送って"),
    CostPhrase("pay_lp", "支付{lp}点LP", "pay {lp} LP",
               "{lp}ＬＰを払い", "{lp}ＬＰを払って"),
    CostPhrase("banish", "把{obj}除外", "banish {obj}",
               "{obj}を除外し", "{obj}を除外して"),
    # ⚠ detach 的宾语自带「素材 + 数量 + 格助词」（gen._cost_object 构造），
    #   日文模板不能再补 を，否则「…を１つを取り除き」双助词。
    CostPhrase("detach", "把{obj}去除", "detach {obj}",
               "{obj}取り除き", "{obj}取り除いて"),
)}

#: 无歧义的"代价动词"（用于 linter 的 cost 位置判断）。
#: 故意**不含** 送去墓地 / 除外 / send / banish —— 它们在效果处理段里同样常见，
#: 纳入会误报（见最终报告"规则取舍"）。
COST_VERBS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("解放", "丢弃", "舍弃", "支付", "去除"),
    "ja": ("リリース", "捨て", "払っ", "取り除"),
    "en": ("Tribute", "Release", "discard", "pay", "detach"),
    "ko": ("릴리스", "버리고", "지불"),
}
#: 「发动 / 発動 / activate」标记
ACTIVATION_MARKERS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("才能发动", "发动", "才能發動"),
    "ja": ("発動できる", "発動する", "発動"),
    "en": ("You can", "activate", "activated", "activation"),
}
#: 选发（可选）效果的标记；没有它 → 必发效果
OPTIONAL_MARKERS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("才能发动", "可以发动"),
    "ja": ("発動できる", "できる"),
    "en": ("You can",),
}


# ══════════════════════════════════════════════════════════════════════
#  8. 取对象 / 指代
# ══════════════════════════════════════════════════════════════════════
TARGET_PHRASE: dict[str, str] = {
    "zh_cn": "以{obj}为对象",
    "ja": "{obj}を対象として",
    "en": "target {obj}",
}
#: 「以…为对象」的识别正则（取对象判定）
TARGET_RE: dict[str, str] = {
    "zh_cn": r"以[^。；;]{1,40}为对象",
    "ja": r"[^。]{1,40}を対象として",
    "en": r"\btarget(?:s|ed|ing)?\b",
}
#: 「that target / it」指代写法（处理时是否仍要求满足取对象条件）
REFERENCE_PHRASES: dict[str, dict[str, str]] = {
    "that_target": {"zh_cn": "那个对象", "ja": "その対象", "en": "that target"},
    "it": {"zh_cn": "那张卡", "ja": "それ", "en": "it"},
}
#: 场所键 → 卡文用词（IC 用 DECK/HAND/... ，与 models.EffectTarget.from_zone 对齐）
ZONE_WORDS: dict[str, dict[str, str]] = {
    "DECK": {"zh_cn": "卡组", "ja": "デッキ", "en": "Deck"},
    "EXTRA": {"zh_cn": "额外卡组", "ja": "ＥＸデッキ", "en": "Extra Deck"},
    "HAND": {"zh_cn": "手卡", "ja": "手札", "en": "hand"},
    "GRAVE": {"zh_cn": "墓地", "ja": "墓地", "en": "GY"},
    "REMOVED": {"zh_cn": "除外状态", "ja": "除外状態", "en": "banished"},
    "FIELD": {"zh_cn": "场上", "ja": "フィールド", "en": "field"},
    "MZONE": {"zh_cn": "怪兽区域", "ja": "モンスターゾーン", "en": "Monster Zone"},
    "SZONE": {"zh_cn": "魔法与陷阱区域", "ja": "魔法＆罠ゾーン",
              "en": "Spell & Trap Zone"},
    "PZONE": {"zh_cn": "灵摆区域", "ja": "Ｐゾーン", "en": "Pendulum Zone"},
    "FZONE": {"zh_cn": "场地区域", "ja": "フィールドゾーン", "en": "Field Zone"},
    "DECKTOP": {"zh_cn": "卡组顶", "ja": "デッキの上", "en": "top of the Deck"},
}
#: 控制者 → 所属短语
CONTROLLER_WORDS: dict[str, dict[str, str]] = {
    "self": {"zh_cn": "自己", "ja": "自分", "en": "you"},
    "opponent": {"zh_cn": "对方", "ja": "相手", "en": "opponent"},
    "both": {"zh_cn": "双方", "ja": "お互い", "en": "both players"},
}
#: 计数单位：怪兽 / 卡 / 指示物
COUNT_UNITS: dict[str, dict[str, str]] = {
    "monster": {"zh_cn": "只", "ja": "体", "en": ""},
    "card": {"zh_cn": "张", "ja": "枚", "en": ""},
    "counter": {"zh_cn": "个", "ja": "個", "en": ""},
    "token": {"zh_cn": "只", "ja": "体", "en": ""},
}


# ══════════════════════════════════════════════════════════════════════
#  9. 效果句模板（IR ``kind`` → 多语言句子）
# ══════════════════════════════════════════════════════════════════════
# 占位符：
#   {obj}   带数量的对象短语（1只龙族怪兽 / ドラゴン族モンスター１体 / 1 Dragon monster）
#   {objc}  不带数量的对象短语（龙族怪兽 / ドラゴン族モンスター / Dragon monster）
#   {n}     数量（本地化数字）
#   {name}  卡名（已按语言加引号）
#   {arch}  字段名（已按语言加引号）
#   {token} 衍生物名
#   {ctr}   指示物名
# 日文值可用 ``|`` 分隔「辞書形|連用形」——连接词 ``and`` / ``and if you do`` 需要连用形。

def _t(zh_cn: str, ja: str, en: str, **meta: Any) -> dict[str, Any]:
    return {"zh_cn": zh_cn, "ja": ja, "en": en, **meta}


EFFECT_TEMPLATES: dict[str, dict[str, Any]] = {
    # ── 检索 / 回收 ──────────────────────────────────────────────
    "search": _t("从卡组把{obj}加入手卡",
                 "デッキから{obj}を手札に加える|加え",
                 "add {obj} from your Deck to your hand",
                 zone="DECK", risky=True),
    "search_grave": _t("从墓地把{obj}加入手卡",
                       "墓地から{obj}を手札に加える|加え",
                       "add {obj} from your GY to your hand",
                       zone="GRAVE", risky=True),
    "recover": _t("从墓地把{obj}加入手卡",
                  "墓地から{obj}を手札に加える|加え",
                  "add {obj} from your GY to your hand",
                  zone="GRAVE", risky=True),
    "search_banished": _t("把{obj}加入手卡",
                          "{obj}を手札に加える|加え",
                          "add {obj} to your hand", risky=True),
    # ── 特殊召唤 ────────────────────────────────────────────────
    "ssummon": _t("把{obj}特殊召唤", "{obj}を特殊召喚する|特殊召喚し",
                  "Special Summon {obj}", risky=True),
    "ssummon_deck": _t("从卡组把{obj}特殊召唤",
                       "デッキから{obj}を特殊召喚する|特殊召喚し",
                       "Special Summon {obj} from your Deck",
                       zone="DECK", risky=True),
    "ssummon_hand": _t("从手卡把{obj}特殊召唤",
                       "手札から{obj}を特殊召喚する|特殊召喚し",
                       "Special Summon {obj} from your hand",
                       zone="HAND", risky=True),
    "ssummon_grave": _t("从墓地把{obj}特殊召唤",
                        "墓地から{obj}を特殊召喚する|特殊召喚し",
                        "Special Summon {obj} from your GY",
                        zone="GRAVE", risky=True),
    "ssummon_extra": _t("从额外卡组把{obj}特殊召唤",
                        "ＥＸデッキから{obj}を特殊召喚する|特殊召喚し",
                        "Special Summon {obj} from your Extra Deck",
                        zone="EXTRA", risky=True),
    "ssummon_token": _t("在自己场上把{n}只「{token}」特殊召唤",
                        "自分フィールドに「{token}」{n}体を特殊召喚する|特殊召喚し",
                        "Special Summon {n} \"{token}\" Token(s) to your field",
                        risky=True),
    "ssummon_banished": _t("把{obj}特殊召唤", "{obj}を特殊召喚する|特殊召喚し",
                           "Special Summon {obj}", zone="REMOVED", risky=True),
    # ── 抽卡 / 堆墓 / 翻卡 ──────────────────────────────────────
    "draw": _t("自己从卡组抽{n}张卡", "自分はデッキから{n}枚ドローする|ドローし",
               "draw {n} card(s)", risky=True),
    "mill": _t("从卡组顶把{n}张卡送去墓地",
               "デッキの上から{n}枚を墓地へ送る|墓地へ送り",
               "send the top {n} card(s) of your Deck to the GY", risky=True),
    "excavate": _t("把卡组顶{n}张卡翻开", "デッキの上から{n}枚をめくる|めくり",
                   "excavate the top {n} card(s) of your Deck"),
    "discard_opponent": _t("对方丢弃{n}张手卡", "相手は手札を{n}枚捨てる|捨て",
                           "your opponent discards {n} card(s)", risky=True),
    # ── 除去 / 移动 ─────────────────────────────────────────────
    "destroy": _t("把{obj}破坏", "{obj}を破壊する|破壊し", "destroy {obj}"),
    "destroy_all": _t("场上的{objc}全部破坏", "フィールドの{objc}を全て破壊する|全て破壊し",
                      "destroy all {objc}"),
    "banish": _t("把{obj}除外", "{obj}を除外する|除外し", "banish {obj}"),
    "banish_face_down": _t("把{obj}里侧表示除外", "{obj}を裏側表示で除外する|裏側表示で除外し",
                           "banish {obj} face-down"),
    "send_grave": _t("把{obj}送去墓地", "{obj}を墓地へ送る|墓地へ送り",
                     "send {obj} to the GY"),
    "return_hand": _t("把{obj}回到手卡", "{obj}を手札に戻す|手札に戻し",
                      "return {obj} to the hand"),
    "return_deck": _t("把{obj}回到卡组", "{obj}をデッキに戻す|デッキに戻し",
                      "return {obj} to the Deck"),
    "shuffle_deck": _t("把{obj}洗牌", "{obj}をシャッフルする|シャッフルし",
                       "shuffle {obj} into the Deck"),
    "set_from_deck": _t("从卡组把{obj}放置", "デッキから{obj}をセットする|セットし",
                        "Set {obj} from your Deck", zone="DECK"),
    # ── 无效化 ──────────────────────────────────────────────────
    "negate": _t("那个发动无效并破坏", "その発動を無効にし破壊する|無効にし破壊し",
                 "negate the activation, and if you do, destroy it"),
    "negate_effect": _t("那个效果无效化", "その効果を無効にする|無効にし",
                        "negate its effects"),
    # 无效**场上某张卡**的效果（对象是卡本身，不是连锁上的发动）
    "negate_card": _t("{obj}的效果直到回合结束时无效",
                      "{obj}の効果はターン終了時まで無効になる|効果はターン終了時まで無効になり",
                      "negate the effects of {obj} until the end of the turn"),
    "cannot_activate": _t("不能发动", "発動できない", "cannot be activated"),
    # ── 数值 / 表示形式 / 控制权 ────────────────────────────────
    "gain_atk": _t("{obj}的攻击力上升{n}", "{obj}の攻撃力を{n}アップする|アップし",
                   "{obj} gains {n} ATK"),
    "lose_atk": _t("{obj}的攻击力下降{n}", "{obj}の攻撃力を{n}ダウンする|ダウンし",
                   "{obj} loses {n} ATK"),
    "set_atk": _t("{obj}的攻击力变成{n}", "{obj}の攻撃力を{n}にする|{n}にし",
                  "{obj}'s ATK becomes {n}"),
    "gain_def": _t("{obj}的守备力上升{n}", "{obj}の守備力を{n}アップする|アップし",
                   "{obj} gains {n} DEF"),
    "set_def": _t("{obj}的守备力变成{n}", "{obj}の守備力を{n}にする|{n}にし",
                  "{obj}'s DEF becomes {n}"),
    "change_position": _t("把{obj}的表示形式变更", "{obj}の表示形式を変更する|変更し",
                          "change {obj} to face-up Defense Position"),
    "take_control": _t("得到{obj}的控制权", "{obj}のコントロールを得る|コントロールを得",
                       "take control of {obj}"),
    "place_counter": _t("在{obj}上放置{n}个{ctr}指示物",
                        "{obj}に{ctr}カウンターを{n}個置く|{ctr}カウンターを{n}個置き",
                        "place {n} {ctr} Counter(s) on {obj}"),
    # ── 伤害 / LP ───────────────────────────────────────────────
    "lp_damage": _t("给与对方{n}点伤害", "相手に{n}のダメージを与える|ダメージを与え",
                    "inflict {n} damage to your opponent"),
    "lp_gain": _t("自己回复{n}点LP", "自分のＬＰを{n}回復する|回復し",
                  "gain {n} LP"),
    "direct_attack": _t("{objc}可以直接攻击", "{objc}は直接攻撃できる|直接攻撃でき",
                        "{objc} can attack directly"),
    "piercing": _t("{objc}向守备表示怪兽攻击的场合，给与对方那个攻击力超过守备力数值的战斗伤害",
                   "{objc}が守備表示モンスターを攻撃した場合、その守備力を攻撃力が超えた分だけ"
                   "相手に戦闘ダメージを与える|戦闘ダメージを与え",
                   "if {objc} attacks a Defense Position monster, inflict piercing "
                   "battle damage"),
    # ── 限制 / 抗性（多为永续）──────────────────────────────────
    "cannot_attack": _t("{objc}不能攻击", "{objc}は攻撃できない|攻撃できず",
                        "{objc} cannot attack", continuous=True),
    "cannot_be_destroyed": _t("{objc}不会被效果破坏", "{objc}は効果では破壊されない|破壊されず",
                              "{objc} cannot be destroyed by card effects",
                              continuous=True),
    "unaffected": _t("{objc}不受其他卡的效果影响", "{objc}は他のカードの効果を受けない|受けず",
                     "{objc} is unaffected by other cards' effects", continuous=True),
    "cannot_be_targeted": _t("{objc}不能成为效果的对象", "{objc}は効果の対象にならない|ならず",
                             "{objc} cannot be targeted by card effects",
                             continuous=True),
    "continuous_gain_atk": _t(
        "只要这张卡在怪兽区域存在，自己场上的怪兽的攻击力上升{n}",
        "このカードがモンスターゾーンに存在する限り、自分フィールドのモンスターの攻撃力は"
        "{n}アップする|{n}アップし",
        "while this card is face-up on the field, monsters you control gain {n} ATK",
        continuous=True),
    # ── 召唤 / 规则文本 ────────────────────────────────────────
    "fusion_summon": _t("把{obj}融合召唤", "{obj}を融合召喚する|融合召喚し",
                        "Fusion Summon {obj}", risky=True),
    "synchro_summon": _t("把{obj}同步召唤", "{obj}をＳ召喚する|Ｓ召喚し",
                         "Synchro Summon {obj}", risky=True),
    "xyz_summon": _t("把{obj}超量召唤", "{obj}をＸ召喚する|Ｘ召喚し",
                     "Xyz Summon {obj}", risky=True),
    "link_summon": _t("把{obj}连接召唤", "{obj}をＬ召喚する|Ｌ召喚し",
                      "Link Summon {obj}", risky=True),
    "ritual_summon": _t("把{obj}仪式召唤", "{obj}を儀式召喚する|儀式召喚し",
                        "Ritual Summon {obj}", risky=True),
    "pendulum_summon": _t("把{obj}灵摆召唤", "{obj}をＰ召喚する|Ｐ召喚し",
                          "Pendulum Summon {obj}", risky=True),
    "extra_normal_summon": _t(
        "这个回合，自己在通常召唤外加上只有{n}次可以把{objc}召唤",
        "このターン、自分は通常召喚に加えて{n}度だけ{objc}を召喚できる|召喚でき",
        "you can Normal Summon {objc} {n} additional time(s) this turn", risky=True),
    "copy_name": _t("这张卡的卡名当作{name}使用", "このカードのカード名は{name}として扱う|扱い",
                    "this card's name becomes {name}"),
    "treat_as_card": _t("这张卡也当作{arch}卡使用", "このカードは{arch}カードとしても扱う|扱い",
                        "this card is also always treated as a {arch} card"),
    "cannot_special_summon": _t("这张卡不能特殊召唤", "このカードは特殊召喚できない|特殊召喚できず",
                                "cannot be Special Summoned", rule_text=True),
    "cannot_normal_summon": _t("这张卡不能通常召唤", "このカードは通常召喚できない|通常召喚できず",
                               "cannot be Normal Summoned/Set", rule_text=True),
    "must_first_ssummon": _t("这张卡不能通常召唤，用{objc}的效果才能特殊召唤",
                             "このカードは通常召喚できず、{objc}の効果でのみ特殊召喚できる|"
                             "特殊召喚でき",
                             "must first be Special Summoned (from your hand) by {objc}",
                             rule_text=True),
}

#: 名字里就带"检索/特召"语义的 kind（生成器用；linter 一律走文本层）
RISKY_KINDS: tuple[str, ...] = tuple(
    k for k, v in EFFECT_TEMPLATES.items() if v.get("risky"))
#: 不入连锁的 kind（没有冒号的分号）
CONTINUOUS_KINDS: tuple[str, ...] = tuple(
    k for k, v in EFFECT_TEMPLATES.items() if v.get("continuous"))
#: 效果外文本 / 召唤手续（不是效果，不可被无效）
RULE_TEXT_KINDS: tuple[str, ...] = tuple(
    k for k, v in EFFECT_TEMPLATES.items() if v.get("rule_text"))
#: 特召类 kind 的显式清单 —— 生成器用它把宾语量词强制为「只/体」
#: （历史缺陷：从额外卡组特召写成「把1张卡特殊召唤」，docs/03 §三-c）
SUMMON_KINDS: frozenset[str] = frozenset({
    "ssummon", "ssummon_deck", "ssummon_hand", "ssummon_grave",
    "ssummon_extra", "ssummon_banished", "ssummon_token",
})
#: **不取对象**的效果种类：按官方写法，这些效果在处理时才选卡，
#: 卡文里不写「以…为对象」。若 IR 给了 target，则把它当作"范围描述"使用。
NON_TARGETING_KINDS: tuple[str, ...] = (
    "search", "search_grave", "search_banished", "recover", "draw", "mill",
    "excavate", "discard_opponent", "ssummon_deck", "ssummon_extra",
    "ssummon_token", "destroy_all", "extra_normal_summon", "shuffle_deck",
)
#: 官方 K 语言里"按顺序/同时"的补充括号（多个 ● 时必写，见报告 A1.5）
BULLET_QUALIFIERS: dict[str, dict[str, str]] = {
    "in_sequence": {"zh_cn": "（按顺序）", "ja": "（順番に）", "en": "(in sequence)"},
    "simultaneously": {"zh_cn": "（同时）", "ja": "（同時に）", "en": "(simultaneously)"},
}
#: 处理段直接作用于"刚取的对象"的效果种类 —— 官方写作「那张卡／それ／it」，
#: 而不是把取对象短语再抄一遍（A5.2 的指代写法）。
TARGET_REF_KINDS: tuple[str, ...] = (
    "destroy", "banish", "banish_face_down", "send_grave", "return_hand",
    "return_deck", "gain_atk", "lose_atk", "set_atk", "gain_def", "set_def",
    "change_position", "take_control", "place_counter", "negate_effect",
    "negate_card",
    "shuffle_deck", "cannot_attack", "cannot_be_destroyed", "unaffected",
    "cannot_be_targeted", "direct_attack",
    # 检索/回收/特召这类「先取对象、处理段用代词」的句式：官方写
    # 「…为对象才能发动。**那只怪兽**加入手卡。」而不是把宾语短语重抄一遍
    # （简中库「那只怪兽」2756 张）。以前漏了这几个种类，处理段会重述宾语，
    # 于是「1只「X」怪兽」在整句里出现两次，读起来就不是官方味道。
    "search", "search_grave", "search_banished", "recover",
    "ssummon_grave", "ssummon_hand", "to_hand", "special_summon",
)

#: **不取对象**、在处理时才「选」卡的效果句式（官方简中用「选」而不是「把」）。
#: 配合 ``params['select']=True`` 使用（此时 ``target`` 只描述范围）。
SELECT_TEMPLATES: dict[str, dict[str, Any]] = {
    "ssummon_grave": _t("从自己{zone}选{obj}特殊召唤",
                        "自分{zone}から{obj}を選んで特殊召喚する",
                        "Special Summon {obj} from your {zone}"),
    "ssummon_deck": _t("从自己{zone}选{obj}特殊召唤",
                       "自分{zone}から{obj}を選んで特殊召喚する",
                       "Special Summon {obj} from your {zone}"),
    "ssummon_hand": _t("从自己{zone}选{obj}特殊召唤",
                       "自分{zone}から{obj}を選んで特殊召喚する",
                       "Special Summon {obj} from your {zone}"),
    "ssummon_banished": _t("从自己{zone}选{obj}特殊召唤",
                           "自分{zone}から{obj}を選んで特殊召喚する",
                           "Special Summon {obj} from your {zone}"),
    "search": _t("从自己{zone}选{obj}加入手卡",
                 "自分{zone}から{obj}を選んで手札に加える",
                 "Add {obj} from your {zone} to your hand"),
    "search_grave": _t("从自己{zone}选{obj}加入手卡",
                       "自分{zone}から{obj}を選んで手札に加える",
                       "Add {obj} from your {zone} to your hand"),
    "recover": _t("从自己{zone}选{obj}加入手卡",
                  "自分{zone}から{obj}を選んで手札に加える",
                  "Add {obj} from your {zone} to your hand"),
    "destroy": _t("把{obj}破坏", "{obj}を破壊する", "destroy {obj}"),
    "banish": _t("把{obj}除外", "{obj}を除外する", "banish {obj}"),
}
#: 各种族/区域名（「选」句式里区域词的多语言）
SELECT_ZONE_WORDS: dict[str, dict[str, str]] = {
    "GRAVE": {"zh_cn": "墓地", "ja": "墓地", "en": "GY"},
    "DECK": {"zh_cn": "卡组", "ja": "デッキ", "en": "Deck"},
    "HAND": {"zh_cn": "手卡", "ja": "手札", "en": "hand"},
    "REMOVED": {"zh_cn": "除外区", "ja": "除外ゾーン", "en": "banishment"},
    "EXTRA": {"zh_cn": "额外卡组", "ja": "ＥＸデッキ", "en": "Extra Deck"},
    "FIELD": {"zh_cn": "场上", "ja": "フィールド", "en": "field"},
    "MZONE": {"zh_cn": "怪兽区域", "ja": "モンスターゾーン", "en": "monster zone"},
    "SZONE": {"zh_cn": "魔法与陷阱区域", "ja": "魔法・罠ゾーン",
              "en": "Spell & Trap Zone"},
}

#: 目标从句的收尾（英文 ``target`` 之后不加东西）
TARGET_TAIL: dict[str, str] = {"zh_cn": "", "ja": "", "en": ""}


# ══════════════════════════════════════════════════════════════════════
#  10. 词表（linter 用）
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class FolkTerm:
    """一条「民间/繁中写法 → 官方简中写法」的裁决。

    :param langs: **这条裁决只对哪些语言成立**。术语方向是跟着代理版本走的：
        简中官方写「同调／调整」，繁中官方写「同步／协调」，
        同一对词在两种语言里方向正好相反 —— 所以不能像以前那样
        把 zh_cn 与 zh_tw 混在一行里判。
    :param level: ``WARN`` 是现行官方不这么写；``INFO`` 是
        **旧卡原文里合法**（官方库里就有），只是新卡建议按现行写法。
    """

    bad: str
    good: str
    why: str
    langs: tuple[str, ...] = ("zh_cn",)
    level: str = "WARN"


#: 民间/繁中误译 → 官方简中。**方向以 ``vendor/data/cards_zh.cdb``
#: （15019 张官方简中卡文）实测为准**，不是以民间习惯或繁中为准：
#:
#: ==========================  ======  ======  =====================================
#: 词                          简中库   繁中库   结论
#: ==========================  ======  ======  =====================================
#: 同调 / 同步                  991 / 0   —      简中官方是**同调**
#: 调整 / 协调                  807 / 0   —      简中官方是**调整**
#: 连接 / 链接                  819 / 0   —      简中官方是连接
#: 超量 / XYZ                1256 / 4(卡名)  —   XYZ 只出现在卡名里
#: 反转 / 翻转                592 / 1     —      「翻转」那 1 张是普通用语（见下）
#: 卡组 / 牌组               5895 / 0     —      卡文统一写卡组
#: ==========================  ======  ======  =====================================
#:
#: 历史缺陷：本表原先把「同调→同步」「调整→协调」两条**方向写反**，
#: 于是把用户写对的简中卡文报成"民间误译"，还会在整理时把「同调」改成「同步」。
FOLK_TERMS: tuple[FolkTerm, ...] = (
    FolkTerm("同步", "同调",
             "「同步」是繁中/民间译名，**官方简中为「同调」**"
             "（简中卡文库 991 张用「同调」、「同步」0 张）。"),
    FolkTerm("协调", "调整",
             "「协调」是繁中/民间译名，**官方简中为「调整」**"
             "（简中卡文库 807 张用「调整」、「协调」0 张）。"),
    FolkTerm("XYZ", "超量",
             "「XYZ」是民间写法，官方简中为「超量」（Xyz→超量召唤/阶级）。"
             "注意卡名里的 XYZ 是名字的一部分，校验器已先剥掉引号内容再判。"),
    FolkTerm("xyz", "超量", "「xyz」是民间写法，官方简中为「超量」。"),
    FolkTerm("链接", "连接", "「链接」是民间译名，官方简中为「连接」（Link→连接召唤）。"),
    FolkTerm("同盟", "联合", "「同盟」是民间译名，官方简中为「联合」（Union→联合）。"),
    FolkTerm("双面", "二重", "「双面」是民间译名，官方简中为「二重」（Gemini→二重）。"),
    FolkTerm("多维", "超量", "「多维」是民间译名，官方简中为「超量」。"),
    FolkTerm("牌组", "卡组",
             "官方界面叫「牌组」，但规则书与卡文统一写「卡组」——"
             "卡文里出现「牌组」应归一为「卡组」（简中库 5895 / 0）。"),
    FolkTerm("祭品召唤", "上级召唤", "官方简中为「上级召唤」（Tribute Summon）。"),
    FolkTerm("祭品", "解放",
             "现行官方简中写「解放」；但**旧卡原文确实写「作为祭品」**"
             "（简中库 114 张），所以这条只是建议，不算错。",
             level="INFO"),
    # 「翻转」不能整词判：官方库里那 1 张是「把卡组上下翻转过来」——普通用语，
    # 不是 Flip 效果。所以只在**反转效果的上下文**里提示。
    FolkTerm("这张卡翻转", "这张卡反转",
             "Flip 效果的官方简中是「反转」；「这张卡翻转的场合」是旧译写法。"),
    FolkTerm("翻转的场合", "反转的场合",
             "Flip 效果的官方简中是「反转」。"),
    FolkTerm("翻转效果", "反转效果",
             "Flip 效果的官方简中是「反转」。"),
)

#: 旧术语残留（PSCT 变更史，A7.1）：出现即提示归一化
OLD_TERMS_EN: tuple[tuple[str, str], ...] = (
    ("remove from play", "banish"),
    ("removed from play", "banished"),
    ("removed from the field", "leaves the field"),
    ("select", "target"),
    ("pick up", "excavate"),
    ("Life Points", "LP"),
    ("Graveyard", "GY"),
    ("Xyz Material", "material"),
    ("-Type", "（删去种族后缀）"),
    ("This card's name is treated as", "This card's name becomes"),
    ("cannot be Normal Summoned or Set", "cannot be Normal Summoned/Set"),
    ("can only be", "must first be"),
)

#: 检索 / 特召 / 抽卡的文本特征（HOPT 缺失检查，E09）
RISKY_TEXT_PATTERNS: dict[str, tuple[str, ...]] = {
    "zh_cn": (r"从卡组[^。]{0,16}加入手卡", r"从卡组[^。]{0,16}特殊召唤",
              r"从墓地把[^。]{0,16}加入手卡", r"从卡组抽\d+张卡",
              r"从卡组顶[^。]{0,12}送去墓地"),
    "zh_tw": (r"從牌組[^。]{0,16}加入手牌", r"從牌組[^。]{0,16}特殊召喚",
              r"從墓地將[^。]{0,16}加入手牌", r"從牌組抽\d+張卡"),
    "ja": (r"デッキから[^。]{0,20}手札に加え", r"デッキから[^。]{0,20}特殊召喚",
           r"デッキから\d*枚?ドロー", r"デッキの上から[^。]{0,16}墓地へ送"),
    "en": (r"from your Deck to your hand", r"Special Summon [^.]{0,40}from your Deck",
           r"draw \d+ card", r"top \d+ cards? of your Deck to the GY"),
    "ko": (r"덱에서[^.]{0,20}패에 넣", r"덱에서[^.]{0,20}특수 소환"),
}
#: 「任何回合限制」的文本标记（HOPT 缺失检查的反面）
LIMIT_MARKERS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("1回合1次", "1回合只能", "1回合各能使用1次", "1场决斗", "回合1次"),
    "zh_tw": ("1回合1次", "1回合只能", "1回合各能使用1次", "1場決鬥"),
    "ja": ("１ターンに１度", "１ターンに１度しか", "１デュエルに１度"),
    "en": ("once per turn", "once per duel", "only use", "only activate",
           "once while face-up"),
    "ko": ("1턴에 1번", "1턴에 한 번"),
}
#: 时点词识别（时 vs 场合）
TIMING_RE: dict[str, dict[str, str]] = {
    "zh_cn": {"when": r"(?:成功|破坏|发动|召唤|送去墓地|除外|加入|离开|攻击|特殊召唤|被战斗破坏|放置|反转|抽|存在|成为|结束)[^。，,]{0,4}时",
              "if": r"场合"},
    "zh_tw": {"when": r"(?:成功|破壞|發動|召喚|送去墓地|除外|加入|離開|攻擊|特殊召喚|放置|反轉)[^。，,]{0,4}時",
              "if": r"場合"},
    "ja": {"when": r"(?:成功|破壊|発動|召喚|墓地へ送|除外|加わ|離れ|攻撃|特殊召喚|なっ)[^。、,]{0,6}時",
           "if": r"場合"},
    "en": {"when": r"\bWhen\b", "if": r"\bIf\b"},
}

#: 引号风格（字段引用／卡名引用）
QUOTE_PAIRS: dict[str, tuple[str, str]] = {
    "zh_cn": ("「", "」"), "zh_tw": ("「", "」"), "ja": ("「", "」"),
    "ko": ("「", "」"), "en": ('"', '"'),
}

#: 效果外文本 / 召唤手续的特征句（不该被编号、不该入连锁）
RULE_TEXT_MARKERS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("这张卡不能通常召唤", "这张卡不能特殊召唤", "这个卡名在规则上",
              "这张卡也当作"),
    "ja": ("このカードは通常召喚できない", "このカードは特殊召喚できない",
           "このカード名はルール上"),
    "en": ("cannot be Normal Summoned/Set", "cannot be Special Summoned",
           "This card's name is always treated as", "is also always treated as"),
}
#: 「诱发即时效果」写法（魔法/陷阱不该出现）
QUICK_EFFECT_MARKERS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("（这个效果在对方回合也能发动）", "这个效果在对方回合也能发动",
              "对方回合也能发动"),
    "ja": ("（この効果は相手ターンでも発動できる）", "相手ターンでも発動できる"),
    "en": ("(Quick Effect)", "during either player's turn"),
}

#: 代价句式（用于「处理动词位置」检查前先把代价摘掉）。
#: 中日文没有分号，代价与处理动词共用同一批词（送去墓地／除外／解放…），
#: 只有「它出现在『才能发动』之前并且构成把…送去墓地这类代价」才能区分。
COST_SHAPE_RE: dict[str, str] = {
    "zh_cn": r"(?:从|把)[^。；;]{0,28}?(?:送去墓地|除外|解放|丢弃|舍弃|回到卡组|"
             r"回到手卡|回到额外卡组)|支付\s*[０-９\d]+\s*点[^。；;]{0,6}",
    "ja": r"(?:自分|相手)?[^。；;]{0,28}?(?:墓地へ送り|墓地へ送って|除外し|除外して|"
          r"リリースし|リリースして|捨て|捨てて|デッキに戻し|手札に戻し)|"
          r"[０-９\d]+\s*[ＬP]*P?を払い",
}
#: 被动触发条件（「这张卡被战斗·效果破坏的场合」）—— 处理动词出现在这里
#: 是**时点**，不是把结果写进了发动条件；中日文靠「被／で破壊され」分辨。
CONDITION_SHAPE_RE: dict[str, str] = {
    "zh_cn": r"被[^。；;]{0,16}?(?:破坏|除外|送去墓地|回到卡组|回到手卡)",
    "ja": r"[^。；;]{0,16}?(?:で破壊され|で除去され|で除外され|墓地へ送られ"
          r"|手札に戻され|デッキに戻られ)",
}

#: 效果**处理**动词（报告 A8.1 E03）—— 这些是「结果」，只能出现在分号之后
#: （英文）/ 发动之后（中日文，靠语序）。写在分号之前 = 把处理塞进了发动条件。
RESOLUTION_VERBS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("加入手卡", "特殊召唤", "抽", "破坏", "送去墓地", "除外",
              "回到", "返回", "变成", "放置", "回复", "无效"),
    "ja": ("手札に加え", "特殊召喚", "ドロー", "破壊", "墓地へ送", "除外",
           "戻", "になる", "置", "回復", "無効"),
    "en": ("add", "Special Summon", "draw", "destroy", "send", "banish",
           "return", "negate", "gain", "inflict", "recover"),
}
#: 内置特殊召唤（召唤手续）的标记（报告 A8.1 E28）——
#: 必须带「（从〜）」来源括号，否则无法判断能否被「无效召唤」类卡片无效。
BUILTIN_SS_MARKERS: dict[str, tuple[str, ...]] = {
    # 「特殊召唤。」单独作为标记会把「不能特殊召唤。」「才能特殊召唤。」
    # 这类召唤限制/条件也当成内置特召（历史误报）。只保留明确的主动写法。
    "zh_cn": ("可以把自己", "可以把自己场上", "可以特殊召唤。"),
    "ja": ("自分フィールド", "特殊召喚する。"),
    "en": ("You can Special Summon this card", "Special Summon this card"),
}
#: 内置特召的来源括号写法（有任一个即视为已标注来源）
SS_ORIGIN_PARENS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("（从手卡）", "（从墓地）", "（从卡组）", "（从额外卡组）", "（从除外）"),
    "ja": ("（手札から）", "（墓地から）", "（デッキから）", "（ＥＸデッキから）",
           "（除外から）"),
    "en": ("(from your hand)", "(from your GY)", "(from your Deck)",
           "(from your Extra Deck)", "(from your banishment)"),
}
#: HERO 字段大小写（报告 A9.2，历史遗留特例，官方 PSCT Part 2 规定）
HERO_CASE: tuple[tuple[str, str], ...] = (
    (r"Elemental Hero", "Elemental HERO"),
    (r"Destiny Hero", "Destiny HERO"),
    (r"Evil Hero", "Evil HERO"),
    (r"Vision Hero", "Vision HERO"),
    (r"Masked Hero", "Masked HERO"),
    (r"Xtra Hero", "Xtra HERO"),
    (r"Contrast Hero", "Contrast HERO"),
)
#: HERO 大小写的例外（保持原样，不纠正）
HERO_CASE_EXCEPTIONS: tuple[str, ...] = (
    "Hero Kid", "HERO Flash", "Hero's Bond", "HERO'S Bond", "Hero Signal",
)

#: 数值写法（ATK/守备力）
STAT_WORDS: dict[str, dict[str, str]] = {
    "zh_cn": {"atk": "攻击力", "def": "守备力", "lp": "LP", "latin_atk": "ATK"},
    "ja": {"atk": "攻撃力", "def": "守備力", "lp": "ＬＰ", "latin_atk": "ATK"},
    "en": {"atk": "ATK", "def": "DEF", "lp": "LP", "latin_atk": "ATK"},
}

#: 文本框容量估算（**版面估算，不是官方规定**）
#: 标定依据：render/geometry.py 的 ``pendulum_monster_text`` 宽 686 REF px、
#: ``FIT_PROFILES['description']`` 的 small/extra-small 档（字号 21/17）。
#: 取「小档字号 21px → 约 30 个全角字/行」为估算基准，英文按半角 0.5em 折算。
TEXT_BOX: dict[str, Any] = {
    #: 每行可容纳的"全角字符当量"
    "cpl": {"zh_cn": 30, "zh_tw": 30, "ja": 30, "ko": 30,
            "en": 56, "de": 56, "fr": 56, "it": 56, "pt": 56, "es": 56},
    #: 各文本框相对"标准怪兽框"的宽度系数（灵摆效果框更窄）
    "cpl_scale": {"monster": 1.0, "pendulum_monster": 1.0, "st": 1.0,
                  "pendulum": 0.9},
    #: 文本框可容纳行数（超出即提示精简；灵摆框两栏高度不同）
    "max_lines": {"monster": 8, "pendulum_monster": 6, "pendulum": 5, "st": 9},
    "default_cpl": 30,
    "warn_ratio": 0.85,
}

#: 效果条数提示线（与 design.py 的 G1 呼应）
EFFECT_COUNT_WARN = 3
EFFECT_COUNT_ERROR = 4


# ══════════════════════════════════════════════════════════════════════
#  11. 校验规则清单（lint.py 的 RULES 就取这里）
# ══════════════════════════════════════════════════════════════════════
def _plain(text: Any) -> str:
    """去掉 Markdown 强调星号。

    规则表里的 ``**取对象**`` 是给**读源码的人**看的；界面把 hint/message 当纯文本
    渲染，星号就原样漏到屏幕上（实测：「这类**结果**一律写分号右侧」）。
    反引号保留 —— 它在纯文本里正好当代码引号用。
    """
    s = str(text or "")
    return s.replace("**", "").replace("__", "")


def _rule(code: str, level: str, message: str, hint: str, **extra: Any) -> dict:
    d = {"code": code, "level": level,
         "message": _plain(message), "hint": _plain(hint)}
    d.update(extra)
    return d


LINT_RULES: list[dict] = [
    # ── 标点三段式 ──────────────────────────────────────────────
    _rule("PSCT_PUNCT_CJK_SEMICOLON", "ERROR",
          "中文/日文卡文出现「；」分号",
          "中日文官方卡文不使用分号：把「；」改写成「，」或「。」，"
          "并把代价/取对象移到「发动／発動」之前（靠语序表达）。",
          source="报告 B1.2 / LANGS[*].uses_semicolon=False"),
    _rule("PSCT_PUNCT_EN_MISSING_SEMI", "WARN",
          "英文出现代价或取对象，但没有「;」分隔效果处理",
          "PSCT 三段式：CONDITIONS: ACTIVATION; RESOLUTION。"
          "把 target / Tribute / discard 之后的处理部分用「;」隔开。",
          source="PSCT Part 3"),
    _rule("PSCT_MISSING_COLON", "WARN",
          "写了发动时机或次数限制，却没有「：」（会变成不入连锁的效果）",
          "效果文中出现「时/场合/1回合1次」这类条件时，条件之后必须补「：」。",
          source="报告 A8.1 E01（DIY 最高频错误）"),
    # ── 编号 ────────────────────────────────────────────────────
    _rule("PSCT_NUM_SEQUENCE", "ERROR",
          "效果编号不连续（跳号／未从①开始）",
          "编号只按顺序给「效果」编号：从①起、连续、无缺失。"
          "新增或删除效果后必须重排编号。",
          source="报告 A1.6 / A8.1 E06-E07"),
    _rule("PSCT_NUM_MID_PARAGRAPH", "ERROR",
          "效果编号没有出现在段落起始",
          "①②③ 是**段落起始标记**：每条效果独占一段，编号写在段首。"
          "正文中引用编号请写「这个卡名的②效果」而不是另起一个编号。",
          source="报告 A1.6"),
    _rule("PSCT_NUM_OVERFLOW", "ERROR",
          "效果编号超过 ⑳",
          f"单卡效果条数远超常规（编号上限 {NUMBER_MAX}）；"
          "超过 3 条就该考虑拆卡（见 design.LIMITS）。",
          source="报告 C3.3 / A8.1 E23"),
    _rule("PSCT_NUM_BEYOND_TABLE", "WARN",
          "效果编号超过 ⑩（词表只收录到 ⑩）",
          "官方词表 numbering.symbols 只列到 ⑩；⑪ 以上属罕见写法，请确认排版字体支持。",
          source="psct_patterns.numbering.symbols"),
    # ── HOPT ────────────────────────────────────────────────────
    _rule("PSCT_HOPT_MISSING", "ERROR",
          "检索／特殊召唤／抽卡类效果，全文没有任何回合限制",
          "补「1回合1次，」写进发动条件，或在段末加"
          "「这个卡名的①②效果1回合各能使用1次。」"
          "（与 design.py 的 G1_HOPT_MISSING 呼应，这里是文本层面的检查）。",
          source="报告 A8.1 E09 / E2 清单"),
    _rule("PSCT_HOPT_POSITION", "WARN",
          "「1回合1次」写在发动条件之后（位置不对）",
          "英文写在冒号之前（Once per turn: You can …）；"
          "中日文写在「才能发动／発動できる」之前。写在处理段里等于没限制。",
          source="报告 A6.1 / psct_patterns.hopt.placement"),
    _rule("PSCT_HOPT_NAME_HINT", "INFO",
          "多效果卡只用了「1回合1次」（可被离场重置）",
          "多效果卡建议升级为卡名 HOPT（这个卡名的①②效果1回合各能使用1次），"
          "离场/翻里侧都不会重置。",
          source="报告 A6.2 / C2.4"),
    # ── 时点 ────────────────────────────────────────────────────
    _rule("PSCT_TIMING_MIXED", "WARN",
          "同一段里「时」与「场合」混用（时点语义冲突）",
          "「时」= 严格时点（会错过）；「场合」= 宽松（不会错过）。"
          "同一触发只能用一种；日文的「時」还额外表示「直接连锁」。",
          source="报告 A3.2"),
    _rule("PSCT_TIMING_EN_WHEN", "WARN",
          "英文 When 出现在非触发位置",
          "When 只能引导触发条件（冒号之前）。处理段里描述时点请改用"
          "「if」「while」「during」。",
          source="报告 A3.2 / E1 分层器"),
    _rule("PSCT_TIMING_MISSING", "WARN",
          "触发类效果没有写时点（时/場合/When/If）",
          "诱发效果必须写明时点：中文「〜时／〜的场合」、"
          "日文「〜時／〜場合」、英文 When/If。",
          source="报告 A8.1 E04"),
    # ── 代价位置 ────────────────────────────────────────────────
    _rule("PSCT_COST_AFTER_SEMI", "ERROR",
          "代价（cost）写在分号之后",
          "分号之前写发动时要做的 cost 与取对象，分号之后写效果处理。"
          "把 Tribute/discard/pay LP 移到「;」左侧。",
          source="报告 A1.2 / A8.1 E02"),
    _rule("PSCT_RESOLUTION_BEFORE_SEMI", "ERROR",
          "效果处理写在分号之前（发动条件里塞了结果）",
          "分号左侧只能是发动条件／代价／取对象；"
          "「加入手卡／特殊召唤／破坏／抽卡」这类**结果**一律写分号右侧（英文），"
          "中日文则写在「发动／発動」之后。",
          source="报告 A8.1 E03"),
    _rule("PSCT_BUILTIN_SS_NO_ORIGIN", "WARN",
          "内置特殊召唤没有标注来源地括号",
          "召唤手续里的内置特召必须写来源，如「（从手卡）／（墓地から）／(from your GY)」，"
          "否则无法判断能否被「无效召唤」类效果无效。",
          source="报告 A8.1 E28"),
    _rule("PSCT_HERO_CASE", "WARN",
          "HERO 字段大小写不符合官方 PSCT",
          "Elemental HERO / Destiny HERO / Evil HERO 等字段中的 HERO 必须全大写"
          "（Hero Kid、Hero's Bond 等为官方特例，保持原样）。",
          source="报告 A9.2 / PSCT Part 2"),
    _rule("PSCT_COST_POSITION_CJK", "WARN",
          "中文/日文把代价写在「发动」之后，且没写「才能发动」",
          "中日文靠语序表达 cost：写成「把…解放才能发动。…」"
          "（cost 在「发动／発動」之前）。",
          source="报告 E4 跨语言生成规则"),
    # ── 取对象 ──────────────────────────────────────────────────
    _rule("PSCT_TARGET_MISSING_EN", "ERROR",
          "中文写了「以〜为对象」，英文却没有 target",
          "取对象必须在分号之前用「target」明示，否则引擎按不取对象处理，结算完全不同。",
          source="报告 A5.1"),
    _rule("PSCT_TARGET_MISSING_ZH", "WARN",
          "英文有 target，中文却没写「以〜为对象」",
          "中文第 9 期以后的写法是「以〜为对象才能发动」；漏写会被读成不取对象。",
          source="报告 A5.1"),
    _rule("PSCT_TARGET_AFTER_ACTIVATION", "WARN",
          "取对象写在效果处理段（分号／才能发动之后）",
          "取对象属于「发动时做的事」，必须写在分号之前／「才能发动」之前。",
          source="报告 A1.2"),
    # ── 字段与引号 ──────────────────────────────────────────────
    _rule("PSCT_QUOTE_STYLE", "WARN",
          "字段／卡名引号用法与该语言不符",
          "中文与日文用「」；英文用半角双引号 \"…\"。不要中日文里用 ASCII 引号，"
          "也不要在英文里用「」。",
          source="报告 A9.1"),
    _rule("PSCT_NAME_UNQUOTED", "WARN",
          "引用了卡名／字段名但没加引号",
          "卡名与字段名必须加引号：中文「青眼白龙」、英文 \"Blue-Eyes White Dragon\"。"
          "字段匹配写「「X」卡」，精确卡名匹配写「有「X」卡名记述的卡」。",
          source="报告 A9.1"),
    _rule("PSCT_FIELD_VS_NAME", "INFO",
          "字段引用与卡名引用可能混淆",
          "「「X」卡」= 字段（卡名含 X 的所有卡）；"
          "「有「X」卡名记述的卡」= 文本引用（效果文里真的出现该卡名）。"
          "两者不是一回事，请人工确认。",
          source="报告 A9.1 / A8.1 E24"),
    # ── 连接词 ──────────────────────────────────────────────────
    _rule("PSCT_CONJ_FOREIGN_IN_CJK", "ERROR",
          "中文/日文卡文里出现英文连接词",
          "中日文用「并且／那之后／此外／那个场合／此外，那之后」或"
          "「し／その後／また／その場合／また、その後」，不要直接写 then/also/and。",
          source="报告 E4 跨语言生成规则"),
    _rule("PSCT_CONJ_THEN_INDEPENDENT", "INFO",
          "用了 then（那之后），但两段处理看不出依赖关系",
          "then 表示「A 是 B 的前提」且**会挡住 WHEN 触发**；"
          "若两段互不依赖，应改用 also（此外）；若依次但互不依赖，用 also, after that。",
          source="报告 A2.3 / A2.4"),
    _rule("PSCT_CONJ_AND_RARE", "INFO",
          "单独使用 and（全有或全无）",
          "官方指出单独 and 很罕见，只用于「高度受限、不可分割」的效果；"
          "普通「同时 + 一个必需」应写 and if you do。",
          source="报告 A2.1 / A8.1 E20"),
    # ── 术语 ────────────────────────────────────────────────────
    _rule("PSCT_FOLK_TERM", "WARN",
          "官方简中卡文里出现民间误译",
          "见 message 里的官方写法；繁中与民间译名不要混进简中卡文。",
          source="data/lexicons/README.md §2 / 报告 B3.2"),
    _rule("PSCT_OLD_TERM_EN", "WARN",
          "英文出现 PSCT 变更前的旧术语",
          "按 A7.1 归一化：remove from play→banish、select→target、"
          "Life Points→LP、Graveyard→GY。",
          source="报告 A7.1"),
    # ── 版式与数值 ──────────────────────────────────────────────
    _rule("PSCT_TEXT_TOO_LONG", "WARN",
          "卡文长度超过文本框容量估算",
          "精简措辞或拆卡；文本框容量是版面估算（不是官方规定），"
          "以渲染实测为准。",
          source="报告 C3.3 / 本项目版面估算"),
    _rule("PSCT_STAT_MIXED", "WARN",
          "ATK／攻击力 的写法不统一",
          "中文/日文卡文统一写「攻击力／守备力」，英文统一写 ATK/DEF；"
          "同一张卡不要两种混用。",
          source="报告 B3.3（攻击力/守备力）"),
    _rule("PSCT_STAT_LANG", "INFO",
          "数值写法与该语言习惯不符",
          "中文写「攻击力」、英文写 ATK；LP 在中文里也写作 LP。",
          source="报告 B3.3"),
    # ── 结构 ────────────────────────────────────────────────────
    _rule("PSCT_EFFECT_COUNT", "WARN",
          "单卡效果条数偏多",
          "官方建议 ≤2 条；≥3 条属 Post-Modern 设计标志，请确认是有意为之。",
          source="报告 C3.3 / design.LIMITS"),
    _rule("PSCT_BULLET_AMBIGUOUS", "WARN",
          "同一段里有多个「●」但没有声明（按顺序）或（同时）",
          "`●A ●B` 两者都未写时会被解析为**各自另开连锁**；"
          "要顺序适用请写「（按顺序）」，要同时适用请写「（同时）」。",
          source="报告 A1.5 / A8.1 E21"),
    _rule("PSCT_ST_QUICK_EFFECT", "WARN",
          "魔法/陷阱卡写成了「诱发即时效果」",
          "官方规则里只有怪兽有诱发即时效果；魔法/陷阱靠卡种本身"
          "（速攻魔法、陷阱）获得咒文速度 2，不要写 (Quick Effect)。",
          source="报告 A3.3 / A8.1 E22"),
    _rule("PSCT_RULE_TEXT_NUMBERED", "WARN",
          "效果外文本/召唤手续被编了号（会被当成效果）",
          "「不能通常召唤」「不能特殊召唤」这类属**效果外文本**，"
          "不参与 ①② 编号，也不能被无效；请去掉编号或改写。",
          source="报告 A8.1 E26-E27"),
    _rule("PSCT_NO_TEXT", "WARN",
          "该语言的卡文为空",
          "调用 psct.compose() 生成，或手工补写。",
          source="接口契约 §3.2"),
    _rule("PSCT_SUMMON_LINE_MISSING", "WARN",
          "额外卡组/仪式卡文的第一行不是素材行或降临行",
          "官方版式要求素材行（「A」＋「B」/「X」怪兽×N）或仪式降临行写在"
          "编号效果之前。点「生成」重新投影，或手工补在第一行。",
          source="官方卡文版式：素材行先于 ①② 效果"),
    _rule("PSCT_PENDULUM_NO_EFFECT", "INFO",
          "灵摆卡的灵摆效果框为空",
          "灵摆卡通常有独立的灵摆效果文本；灵摆效果与怪兽效果的编号各自另起。",
          source="psct_patterns.numbering.rules"),
]


def rule_codes() -> tuple[str, ...]:
    return tuple(r["code"] for r in LINT_RULES)


def rule(code: str) -> dict | None:
    for r in LINT_RULES:
        if r["code"] == code:
            return r
    return None


# ══════════════════════════════════════════════════════════════════════
#  12. 版面长度估算（生成器与校验器共用）
# ══════════════════════════════════════════════════════════════════════
def display_width(text: str, lang: str) -> float:
    """把文本折算成"全角字符当量"宽度（半角算 0.5）。

    这是**版面估算**，用于判断卡文是否会溢出文本框；不是官方规定。
    """
    w = 0.0
    for ch in text or "":
        if ch in "\n":
            continue
        w += 0.5 if unicodedata.east_asian_width(ch) in ("Na", "H") else 1.0
    return w


def estimate_lines(text: str, lang: str, *, box: str = "monster") -> int:
    """按段落估算行数（下游渲染器按 ``\\n`` 分段排版）。"""
    base = TEXT_BOX["cpl"].get(lang, TEXT_BOX["default_cpl"])
    cpl = base * float(TEXT_BOX["cpl_scale"].get(box, 1.0))
    total = 0
    for para in (text or "").split("\n"):
        para = para.strip()
        if not para:
            continue
        total += max(1, int(math.ceil(display_width(para, lang) / float(cpl))))
    return total


def max_lines(box: str = "monster") -> int:
    return int(TEXT_BOX["max_lines"].get(box, TEXT_BOX["max_lines"]["monster"]))


__all__ = [
    "CJK_LANGS", "NATIVE_GEN_LANGS", "LOW_COVERAGE_LANGS", "COVERAGE_FLOOR",
    "CJK_COLON_MODE", "NUMBER_SYMBOLS", "NUMBER_EXTENDED", "RE_NUMBER_CHARS",
    "NUMBER_MAX", "NUMBER_DOCUMENTED_MAX", "number_symbol", "number_symbols",
    "number_value",
    "LangStyle", "LANG_STYLE", "style", "is_cjk",
    "STRUCTURE_TEMPLATE", "SEGMENTS", "PUNCT_ROLES", "punctuation_of",
    "Conjunction", "CONJUNCTIONS", "CONJUNCTION_KEYS", "DEFAULT_CONJUNCTION",
    "CONJUNCTION_QUADRANTS", "JA_INLINE_CONJ", "JA_SENTENCE_CONJ", "ZH_CONJ_WRAP",
    "EN_CONJUNCTIONS",
    "HoptSpec", "HOPT_SPECS", "LIMIT_ALIASES", "TRAILING_HOPT_KEYS",
    "INLINE_HOPT_KEYS", "hopt_key",
    "TimingWord", "TIMING_WORDS", "TRIGGER_TIMING_DEFAULT", "retime",
    "TRIGGER_PHRASES", "TRIGGER_MARKERS", "TIMING_REWRITE",
    "CostPhrase", "COST_PHRASES", "COST_VERBS", "ACTIVATION_MARKERS",
    "OPTIONAL_MARKERS",
    "TARGET_PHRASE", "TARGET_RE", "REFERENCE_PHRASES", "ZONE_WORDS",
    "CONTROLLER_WORDS", "COUNT_UNITS",
    "EFFECT_TEMPLATES", "RISKY_KINDS", "CONTINUOUS_KINDS", "RULE_TEXT_KINDS",
    "SUMMON_KINDS",
    "NON_TARGETING_KINDS", "BULLET_QUALIFIERS", "TARGET_REF_KINDS", "TARGET_TAIL",
    "SELECT_TEMPLATES", "SELECT_ZONE_WORDS", "FACEUP_WORDS",
    "QUICK_EFFECT_SENTENCE", "DESTROYED_BY_PHRASES",
    "FOLK_TERMS", "FolkTerm", "OLD_TERMS_EN", "RISKY_TEXT_PATTERNS", "LIMIT_MARKERS",
    "TIMING_RE", "QUOTE_PAIRS", "STAT_WORDS", "TEXT_BOX",
    "RULE_TEXT_MARKERS", "QUICK_EFFECT_MARKERS",
    "RESOLUTION_VERBS", "COST_SHAPE_RE", "CONDITION_SHAPE_RE", "BUILTIN_SS_MARKERS", "SS_ORIGIN_PARENS",
    "HERO_CASE", "HERO_CASE_EXCEPTIONS",
    "EFFECT_COUNT_WARN", "EFFECT_COUNT_ERROR",
    "LINT_RULES", "rule_codes", "rule",
    "display_width", "estimate_lines", "max_lines",
]
