"""PSCT 卡文**确定性**校验器（G-text 门）。

为什么不用 AI 判定
------------------
PSCT 是形式化程度很高的规范：标点语义、编号、HOPT 三种写法、时/场合、
cost 位置、取对象都是**可枚举的文本特征**。用模型判定会引入不可复现的错误率
（调研报告 F3 第 1 条：「Deterministic parser + 0 LLM interpretation」）。
本模块只做正则/位置/计数判断，任何一条结论都能复现。

规则清单见 :data:`cardforge.content.psct.rules.LINT_RULES`
（本模块的 :data:`RULES` 就是它，避免规则散落两处）。

两个入口
--------
``lint(spec, lang=None)``
    按卡牌规格校验（可指定语言；不指定则校验所有已填语言），
    并额外做**跨语言一致性**（中文「以…为对象」↔ 英文 target）与
    结构检查（灵摆框、效果条数）。
``lint_text(text, lang, spec=None)``
    只校验一段文本。给了 ``spec`` 就能做跨语言与 IR↔文本对照。

分段模型（照调研报告 E1 的分层器）
----------------------------------
``① → 条件段(cond) → 发动段(act) → 处理段(res)``
中日文用**语序**切分（「才能发动／発動できる」为界），英文用 ``:`` 与 ``;``。
卡名 HOPT 声明句在分析前**单独摘出**（它含 ①② 但不是效果段落）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Optional, Sequence

from ...core.models import CardSpec, Issue
from . import gen as _gen
from . import lexicon as L
from . import rules

__all__ = ["lint", "lint_text", "RULES", "analyze"]

#: 规则清单（= rules.LINT_RULES，唯一来源）
RULES: list[dict] = rules.LINT_RULES
GATE = "G-text"


# ══════════════════════════════════════════════════════════════════════
#  正则
# ══════════════════════════════════════════════════════════════════════
_RE_NUM = re.compile(rules.RE_NUMBER_CHARS)
_RE_HEAD_CJK = re.compile(rf"^\s*({rules.RE_NUMBER_CHARS}+)\s*[：:]?")
_RE_HEAD_EN = re.compile(rf"^\s*({rules.RE_NUMBER_CHARS}+)[\s.、:：]*")
_RE_QUOTED_CJK = re.compile(r"「[^「」\n]{1,60}」")
_RE_QUOTED_EN = re.compile(r'"[^"\n]{1,60}"')
_RE_QUOTED_FIELD_CJK = re.compile(r"「([^「」\n]{1,30})」卡")

#: HOPT 声明句（分析前摘出；它含 ①② 引用但不是效果段落）
_NC = rules.RE_NUMBER_CHARS
_DECL_RES: dict[str, tuple[str, ...]] = {
    "zh_cn": (rf"这个卡名的{_NC}+的?效果[^。]*。",
              r"「[^」]{1,40}」[^。]{0,20}1回合只能发动[^。]*。",
              r"（这个效果1回合只能获得1次。）"),
    "zh_tw": (rf"這個卡名的{_NC}+的?效果[^。]*。",
              r"（這個效果1回合只能獲得1次。）"),
    "ja": (rf"このカード名の{_NC}+の?効果[^。]*。",
           r"「[^」]{1,40}」[^。]{0,20}１ターンに１枚しか発動できない[^。]*。",
           r"（この効果は１ターンに１度しか得られない。）"),
    "en": (r"You can only (?:use|activate|apply)[^.]*\.",
           r"\(You can only gain this effect[^)]*\)"),
    "ko": (r"이 카드명[^.]*\.",),
}
#: 强发动标记（不含裸「发动」，避免把「那个发动无效」误当发动段边界）
_STRONG_ACT_ZH = ("才能发动", "可以发动", "才能發動")
_STRONG_ACT_JA = ("発動できる", "発動する", "発動した")
#: 英文 cost/target 特征（用于"缺分号"判断，只取无歧义的词）
_EN_TARGET_RE = re.compile(r"\btarget", re.I)
_EN_COST_RE = re.compile(r"\b(Tribute|Release|discard|pay|detach)\b", re.I)


# ══════════════════════════════════════════════════════════════════════
#  分层器
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Para:
    """一个段落的分层结果。"""

    raw: str = ""
    core: str = ""              # 摘掉 HOPT 声明句之后的正文
    declared: str = ""          # 被摘出的声明句
    num: int = 0                # 段落起始编号（0 = 无）
    numbers: list = dc_field(default_factory=list)   # 段内出现的全部编号
    mid_numbers: list = dc_field(default_factory=list)  # 不在段首的编号
    cond: str = ""              # 条件段（含次数限制）
    act: str = ""               # 发动段（cost + 取对象）
    res: str = ""               # 处理段
    activation_pos: int = -1    # 「才能发动/発動できる」在 core 中的位置

    @property
    def is_only_declaration(self) -> bool:
        return bool(self.declared) and not self.core.strip()

    @property
    def is_effect(self) -> bool:
        return self.num > 0

    @property
    def has_colon(self) -> bool:
        return ("：" in self.core) or (":" in self.core)

    @property
    def has_semi(self) -> bool:
        return ("；" in self.core) or (";" in self.core)


def _strip_declarations(text: str, lang: str) -> tuple[str, str]:
    """返回 ``(正文, 摘出的声明句)``。"""
    decl = ""
    core = text
    for pat in _DECL_RES.get(lang, ()):
        found = re.findall(pat, core)
        if found:
            decl = (decl + "".join(found))
            core = re.sub(pat, "", core)
    return core.strip(), decl.strip()


def _split_segments(core: str, lang: str) -> tuple[str, str, str, int]:
    """切 ``(cond, act, res, activation_pos)``。"""
    if lang == "en":
        if ":" in core:
            cond, rest = core.split(":", 1)
            if ";" in rest:
                act, res = rest.split(";", 1)
            else:
                act, res = rest, ""
            return cond.strip(), act.strip(), res.strip(), core.index(":")
        if ";" in core:
            act, res = core.split(";", 1)
            return "", act.strip(), res.strip(), -1
        return "", "", core.strip(), -1
    markers = _STRONG_ACT_JA if lang == "ja" else _STRONG_ACT_ZH
    pos, marker = -1, ""
    for m in markers:
        p = core.find(m)
        if p >= 0 and (pos < 0 or p < pos):
            pos, marker = p, m
    if pos >= 0:
        head = core[:pos]
        res = core[pos + len(marker):].lstrip("。，, ")
        return head.strip(), head.strip(), res.strip(), pos
    return core.strip(), "", "", -1


def analyze(text: str, lang: str) -> dict:
    """把卡文切成段落并分层。返回 ``{"paragraphs": [Para], "raw": str}``。"""
    paras: list[Para] = []
    for block in (text or "").split("\n"):
        if not block.strip():
            continue
        core, decl = _strip_declarations(block, lang)
        p = Para(raw=block.strip(), core=core, declared=decl)
        head = _RE_HEAD_EN if lang == "en" else _RE_HEAD_CJK
        m = head.match(core)
        if m:
            p.num = _num_value(m.group(1)[0])
        p.numbers = [_num_value(c) for c in _RE_NUM.findall(core)]
        p.mid_numbers = _mid_numbers(core, lang)
        p.cond, p.act, p.res, p.activation_pos = _split_segments(core, lang)
        paras.append(p)
    return {"paragraphs": paras, "raw": text or ""}


def _num_value(ch: str) -> int:
    return rules.number_value(ch)


def _mid_numbers(core: str, lang: str) -> list[int]:
    """段内**非段首**的编号（引用编号不算，如「这个卡名的②效果」）。"""
    head = _RE_HEAD_EN if lang == "en" else _RE_HEAD_CJK
    m = head.match(core)
    start = m.end() if m else 0
    out: list[int] = []
    for hit in _RE_NUM.finditer(core):
        if hit.start() < start:
            continue
        prev = core[hit.start() - 1] if hit.start() > 0 else ""
        if prev in ("的", "の"):        # 「这个卡名的②效果」= 引用，不是新段落
            continue
        out.append(_num_value(hit.group(0)))
    return out


def _strip_quotes(text: str) -> str:
    """去掉引号内容（卡名/字段名里的词不算文本错误）。"""
    t = _RE_QUOTED_CJK.sub("〔〕", text or "")
    return _RE_QUOTED_EN.sub("〔〕", t)


# ══════════════════════════════════════════════════════════════════════
#  问题构造
# ══════════════════════════════════════════════════════════════════════
def _issue(code: str, detail: str = "", field: str = "",
           level: str = "") -> Issue:
    meta = rules.rule(code) or {}
    msg = meta.get("message", code)
    if detail:
        msg = f"{msg} —— {detail}"
    return Issue(gate=GATE, code=code, level=level or meta.get("level", "WARN"),
                 message=msg, hint=meta.get("hint", ""), field=field)


def _risky_hits(text: str, lang: str) -> list[str]:
    """文本里命中的「检索/特召/抽卡」特征。"""
    out: list[str] = []
    for pat in rules.RISKY_TEXT_PATTERNS.get(lang, ()):
        for m in re.finditer(pat, text or ""):
            s = m.group(0)
            if s not in out:
                out.append(s)
    return out


def _has_limit(text: str, lang: str) -> bool:
    low = (text or "").lower()
    for marker in rules.LIMIT_MARKERS.get(lang, ()):
        if marker.lower() in low:
            return True
    # 日文/中文的「这个卡名的…1回合…」
    if lang in ("zh_cn", "zh_tw") and "这个卡名的" in (text or ""):
        return True
    if lang == "ja" and "このカード名の" in (text or ""):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════
#  单段文本的规则
# ══════════════════════════════════════════════════════════════════════
def _lint_one_text(text: str, lang: str, spec: Optional[CardSpec],
                   field: str, box: str) -> list[Issue]:
    out: list[Issue] = []
    if not (text or "").strip():
        return out
    cjk = rules.is_cjk(lang)
    an = analyze(text, lang)
    paras: list[Para] = an["paragraphs"]
    plain = _strip_quotes(text)

    # ── 1. 标点：中日文用分号 ──────────────────────────────────
    if cjk:
        for p in paras:
            if "；" in p.core or ";" in p.core:
                out.append(_issue("PSCT_PUNCT_CJK_SEMICOLON",
                                  f"第 {p.num or '?'} 段出现「；」", field))
                break

    # ── 2. 标点：英文缺分号 / 缺冒号 ───────────────────────────
    if lang == "en":
        for p in paras:
            if p.is_only_declaration:
                continue
            if ":" in p.core and ";" not in p.core and (
                    _EN_TARGET_RE.search(p.core) or _EN_COST_RE.search(p.core)):
                out.append(_issue("PSCT_PUNCT_EN_MISSING_SEMI",
                                  f"第 {p.num or '?'} 段："
                                  f"{p.core[:48]}…", field))
                break
    for p in paras:
        if p.is_only_declaration or p.has_colon:
            continue
        if lang == "en":
            if re.search(r"\b(When|If|Once per turn|During)\b", p.core):
                out.append(_issue("PSCT_MISSING_COLON", f"第 {p.num or '?'} 段", field))
                break
        elif re.search(r"(时|場合|场合|1回合1次|１ターンに１度)", p.core):
            out.append(_issue("PSCT_MISSING_COLON", f"第 {p.num or '?'} 段", field))
            break

    # ── 3. 编号 ────────────────────────────────────────────────
    nums = [p.num for p in paras if p.is_effect]
    if nums:
        expect = list(range(1, len(nums) + 1))
        if nums != expect:
            out.append(_issue("PSCT_NUM_SEQUENCE",
                              f"实际编号 {rules.number_symbols(nums) or '(无)'}"
                              f"，应为 {rules.number_symbols(expect)}", field))
        top = max(nums)
        if top > rules.NUMBER_MAX:
            out.append(_issue("PSCT_NUM_OVERFLOW", f"最大编号 {top}", field))
        elif top > rules.NUMBER_DOCUMENTED_MAX:
            out.append(_issue("PSCT_NUM_BEYOND_TABLE", f"最大编号 {top}", field))
        if len(nums) >= rules.EFFECT_COUNT_WARN:
            out.append(_issue("PSCT_EFFECT_COUNT", f"共 {len(nums)} 条编号效果", field))
    for p in paras:
        if p.mid_numbers:
            out.append(_issue("PSCT_NUM_MID_PARAGRAPH",
                              f"「{p.core[:40]}…」中的"
                              f"{rules.number_symbols(p.mid_numbers)}未在段首", field))
            break

    # ── 4. HOPT ───────────────────────────────────────────────
    hits = _risky_hits(text, lang)
    if hits and not _has_limit(text, lang):
        out.append(_issue("PSCT_HOPT_MISSING",
                          f"命中的效果：「{hits[0][:32]}」", field))
    for p in paras:
        if p.is_only_declaration:
            continue
        if lang == "en":
            if ":" in p.core:
                after = p.core.split(":", 1)[1].lower()
                if "once per turn" in after or "once per duel" in after:
                    out.append(_issue("PSCT_HOPT_POSITION",
                                      f"第 {p.num or '?'} 段：Once per turn 出现在冒号之后",
                                      field))
                    break
        else:
            marker = "才能发动" if lang != "ja" else "発動できる"
            pos = p.core.find(marker)
            hopt_word = "1回合1次" if lang != "ja" else "１ターンに１度"
            if pos >= 0 and p.core.find(hopt_word) > pos:
                out.append(_issue("PSCT_HOPT_POSITION",
                                  f"第 {p.num or '?'} 段：{hopt_word} 写在「{marker}」之后",
                                  field))
                break
    if len(nums) >= 2 and not _has_name_hopt(text, lang) and any(
            ("1回合1次" in text) or ("１ターンに１度" in text)
            or ("once per turn" in text.lower()) for _ in (0,)):
        out.append(_issue("PSCT_HOPT_NAME_HINT",
                          "检测到「1回合1次」但没有卡名级限制", field))

    # ── 5. 时点 ───────────────────────────────────────────────
    tre = rules.TIMING_RE.get(lang, {})
    for p in paras:
        if p.is_only_declaration:
            continue
        seg = p.cond or p.core
        if tre.get("when") and tre.get("if") and re.search(tre["when"], seg) \
                and re.search(tre["if"], seg):
            out.append(_issue("PSCT_TIMING_MIXED", f"第 {p.num or '?'} 段", field))
            break
    if lang == "en":
        for p in paras:
            if p.is_only_declaration or "When" not in p.core:
                continue
            if ":" not in p.core or p.core.rindex("When") > p.core.index(":"):
                out.append(_issue("PSCT_TIMING_EN_WHEN",
                                  f"第 {p.num or '?'} 段：{p.core[:40]}…", field))
                break
    # 注：文本层面的「触发效果缺时点」判定不可靠（起动/永续效果本来就没有时点词），
    # 只在有 IR 时用 :func:`_cross_ir` 做对照检查。

    # ── 6. 代价位置 ───────────────────────────────────────────
    cost_verbs = rules.COST_VERBS.get(lang, ())
    if lang == "en":
        for p in paras:
            if p.is_only_declaration or ";" not in p.core:
                continue
            tail = p.core.split(";", 1)[1]
            hit = next((v for v in cost_verbs if re.search(rf"\b{v}\b", tail, re.I)), "")
            if hit:
                out.append(_issue("PSCT_COST_AFTER_SEMI",
                                  f"第 {p.num or '?'} 段：分号之后出现「{hit}」", field))
                break
    elif cjk:
        strong = _STRONG_ACT_JA if lang == "ja" else _STRONG_ACT_ZH
        for p in paras:
            if p.is_only_declaration:
                continue
            if any(m in p.core for m in strong):
                continue
            pos = max(p.core.find("发动"), p.core.find("発動"))
            if pos < 0:
                continue
            tail = p.core[pos:]
            hit = next((v for v in cost_verbs if v in tail), "")
            if hit:
                out.append(_issue("PSCT_COST_POSITION_CJK",
                                  f"第 {p.num or '?'} 段：「{hit}」写在发动之后", field))
                break

    # ── 6.5 效果处理位置（报告 A8.1 E03）──────────────────────
    # 处理动词是「结果」，只能出现在分号之后（英文）/ 发动之后（中日文）。
    # 写在分号左侧 = 把结果塞进了发动条件，引擎会按「发动时就要已经发生」处理。
    res_verbs = rules.RESOLUTION_VERBS.get(lang, ())
    if lang == "en":
        for p in paras:
            if p.is_only_declaration or ";" not in p.core:
                continue
            head = p.core.split(";", 1)[0]
            # 冒号之前是纯条件，只查冒号与分号之间那一段（发动部分）
            if ":" in head:
                head = head.split(":", 1)[1]
            hit = next((v for v in res_verbs
                        if re.search(rf"\b{re.escape(v)}\b", head, re.I)), "")
            if hit:
                out.append(_issue("PSCT_RESOLUTION_BEFORE_SEMI",
                                  f"第 {p.num or '?'} 段：「{hit}」写在分号之前", field))
                break
    else:
        for p in paras:
            if p.is_only_declaration or not p.is_effect:
                continue
            pos = p.activation_pos          # 「发动／発動」的位置
            if pos <= 0:
                continue
            head = p.core[:pos]             # 发动之前 = 条件/代价/取对象
            hit = next((v for v in res_verbs if v in head), "")
            if hit:
                out.append(_issue("PSCT_RESOLUTION_BEFORE_SEMI",
                                  f"第 {p.num or '?'} 段：「{hit}」写在发动之前", field))
                break

    # ── 6.6 内置特殊召唤的来源括号（报告 A8.1 E28）────────────
    # 注：召唤手续**不是效果**，所以这里不能要求 is_effect ——
    # 「You can Special Summon this card.」这类段落恰恰没有编号也没有冒号。
    ss_markers = rules.BUILTIN_SS_MARKERS.get(lang, ())
    origin_parens = rules.SS_ORIGIN_PARENS.get(lang, ())
    if ss_markers and origin_parens:
        for p in paras:
            if p.is_only_declaration:
                continue
            if not any(m in p.core for m in ss_markers):
                continue
            if any(x in p.core for x in origin_parens):
                continue
            out.append(_issue("PSCT_BUILTIN_SS_NO_ORIGIN",
                              f"第 {p.num or '?'} 段：{p.core[:44]}…", field))
            break

    # ── 7. 取对象（同语言内的位置检查）────────────────────────
    tgt_re = re.compile(rules.TARGET_RE.get(lang, r"(?!x)x"),
                        re.I if lang == "en" else 0)
    for p in paras:
        if p.is_only_declaration or not p.is_effect:
            continue
        m = tgt_re.search(p.core)
        if not m:
            continue
        if lang == "en":
            semi = p.core.find(";")
            bad = semi >= 0 and m.start() > semi
        else:
            bad = p.activation_pos >= 0 and m.start() > p.activation_pos
        if bad:
            out.append(_issue("PSCT_TARGET_AFTER_ACTIVATION",
                              f"第 {p.num} 段：取对象出现在发动/处理段", field))
            break

    # ── 8. 引号与字段引用 ─────────────────────────────────────
    if cjk:
        if '"' in text:                 # 中日文里出现半角双引号 → 引号用错
            out.append(_issue("PSCT_QUOTE_STYLE",
                              "中文/日文里出现了半角双引号 \"…\"", field))
    else:
        if "「" in text or "」" in text:
            out.append(_issue("PSCT_QUOTE_STYLE", "英文里出现了「」", field))
    for name in _spec_names(spec, lang):
        if _unquoted_hit(plain, name, lang):
            out.append(_issue("PSCT_NAME_UNQUOTED", f"「{name}」", field))
            break
    if spec is not None and spec.archetype:
        for hit in _RE_QUOTED_FIELD_CJK.findall(text):
            if hit and hit != spec.archetype and hit != spec.name:
                out.append(_issue("PSCT_FIELD_VS_NAME",
                                  f"「{hit}」卡 与声明的字段「{spec.archetype}」不一致",
                                  field))
                break

    # ── 9. 连接词 ─────────────────────────────────────────────
    if cjk:
        for word in ("then", "also", "and", "and if you do", "also, after that"):
            if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", plain):
                out.append(_issue("PSCT_CONJ_FOREIGN_IN_CJK",
                                  f"出现了英文连接词「{word}」", field))
                break
    else:
        for p in paras:
            if p.is_only_declaration:
                continue
            if re.search(r"\bthen\b", p.res, re.I) and not (
                    tgt_re.search(p.core) or _EN_COST_RE.search(p.core)):
                out.append(_issue("PSCT_CONJ_THEN_INDEPENDENT",
                                  f"第 {p.num or '?'} 段：then 之后无前置依赖", field))
                break
    if not cjk:
        if re.search(r"\band\b", plain, re.I) and "and if you do" not in plain.lower():
            out.append(_issue("PSCT_CONJ_AND_RARE", "出现单独的 and", field))

    # ── 10. 术语 ──────────────────────────────────────────────
    if lang in ("zh_cn", "zh_tw"):
        for bad, good, why in rules.FOLK_TERMS:
            if _contains_token(plain, bad, lang):
                out.append(_issue("PSCT_FOLK_TERM",
                                  f"「{bad}」→ 官方写法「{good}」", field))
                break
    if lang == "en":
        for old, new in rules.OLD_TERMS_EN:
            pat = rf"(?<![A-Za-z]){re.escape(old)}(?![A-Za-z])"
            if re.search(pat, plain, re.I):
                out.append(_issue("PSCT_OLD_TERM_EN", f"「{old}」→「{new}」", field))
                break
        # HERO 字段大小写（报告 A9.2）：查**原文**而不是 plain ——
        # plain 用 _strip_quotes 把引号内容换成了 〔〕，而卡名恰恰在引号里。
        hero_text = text or ""
        for keep in rules.HERO_CASE_EXCEPTIONS:
            hero_text = hero_text.replace(keep, "\x00" * len(keep))
        for wrong, right in rules.HERO_CASE:
            if re.search(re.escape(wrong) + r"\b", hero_text):
                out.append(_issue("PSCT_HERO_CASE",
                                  f"「{wrong}」应为「{right}」", field))
                break

    # ── 10.5 结构类（● 语义 / 效果外文本 / 魔陷 2 速）─────────
    for p in paras:
        if p.core.count("●") >= 2:
            if not any(q in p.core for q in ("（按顺序）", "（同时）",
                                             "（順番に）", "（同時に）",
                                             "(in sequence)", "(simultaneously)")):
                out.append(_issue("PSCT_BULLET_AMBIGUOUS",
                                  f"第 {p.num or '?'} 段有 {p.core.count('●')} 个「●」",
                                  field))
                break
    for p in paras:
        if not p.is_effect:
            continue
        if any(m in p.core for m in rules.RULE_TEXT_MARKERS.get(lang, ())):
            out.append(_issue("PSCT_RULE_TEXT_NUMBERED",
                              f"第 {p.num} 段含效果外文本特征", field))
            break
    if spec is not None and not spec.is_monster:
        if any(m in text for m in rules.QUICK_EFFECT_MARKERS.get(lang, ())):
            out.append(_issue("PSCT_ST_QUICK_EFFECT",
                              "魔法/陷阱卡文本里出现诱发即时效果的措辞", field))

    # ── 11. 版式与数值 ────────────────────────────────────────
    lines = rules.estimate_lines(text, lang, box=box)
    cap = rules.max_lines(box)
    if lines > cap:
        out.append(_issue("PSCT_TEXT_TOO_LONG",
                          f"估算 {lines} 行，文本框约 {cap} 行"
                          f"（每行约 {rules.TEXT_BOX['cpl'].get(lang, 30)} 全角字当量）",
                          field))
    elif lines >= cap * rules.TEXT_BOX["warn_ratio"]:
        out.append(_issue("PSCT_TEXT_TOO_LONG",
                          f"估算 {lines} 行，已接近文本框容量 {cap} 行", field,
                          level="INFO"))
    stat = rules.STAT_WORDS.get(lang, {})
    latin = stat.get("latin_atk", "ATK")
    local_atk = stat.get("atk", "攻击力")
    has_latin = re.search(rf"\b{latin}\b", plain) is not None
    has_local = local_atk in plain and local_atk != latin
    foreign = "攻击力" if lang == "en" else latin
    if has_latin and has_local:
        out.append(_issue("PSCT_STAT_MIXED", f"同时出现 {latin} 与「{local_atk}」", field))
    elif lang == "en" and foreign in plain:
        out.append(_issue("PSCT_STAT_LANG", f"英文卡文里出现了「{foreign}」", field))
    elif cjk and has_latin:
        out.append(_issue("PSCT_STAT_LANG",
                          f"该语言习惯写法是「{local_atk}」，不是 {latin}", field))
    return out


def _contains_token(text: str, token: str, lang: str) -> bool:
    if re.fullmatch(r"[A-Za-z]+", token):
        return re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", text) is not None
    return token in text


def _spec_names(spec: Optional[CardSpec], lang: str) -> list[str]:
    """可能被引用却没加引号的卡名/字段名。"""
    if spec is None:
        return []
    out: list[str] = []
    for name in (spec.name_in(lang), spec.name, spec.archetype):
        name = str(name or "").strip()
        if not name:
            continue
        need = 3 if re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", name) else 5
        if len(name) >= need and name not in out:
            out.append(name)
    return out


def _unquoted_hit(text: str, name: str, lang: str) -> bool:
    """文本里出现该名字，但没被引号包住。"""
    if not name:
        return False
    opens = ("「", '"', "『")
    for m in re.finditer(re.escape(name), text or ""):
        prev = text[m.start() - 1] if m.start() > 0 else ""
        if prev in opens:
            continue
        if lang == "en":
            nxt = text[m.end():m.end() + 1]
            if prev.isalnum() or nxt.isalnum():
                continue
        return True
    return False


def _has_name_hopt(text: str, lang: str) -> bool:
    low = (text or "").lower()
    if lang in ("zh_cn", "zh_tw"):
        return "这个卡名的" in text
    if lang == "ja":
        return "このカード名の" in text
    return "you can only use" in low or "you can only activate" in low


# ══════════════════════════════════════════════════════════════════════
#  跨语言检查
# ══════════════════════════════════════════════════════════════════════
_TARGET_PAIRS = (("zh_cn", "en"), ("ja", "en"))


def _has_target_marker(text: str, lang: str) -> bool:
    if not text:
        return False
    return re.search(rules.TARGET_RE.get(lang, r"(?!x)x"),
                     text, re.I if lang == "en" else 0) is not None


def _cross_language(spec: CardSpec, out: list[Issue]) -> None:
    """中文/日文「以…为对象」 ↔ 英文 target 的一致性。"""
    boxes = [("text_i18n", spec.text_i18n or {})]
    if spec.is_pendulum:
        boxes.append(("pendulum_text_i18n", spec.pendulum_text_i18n or {}))
    for field, table in boxes:
        for a_lang, b_lang in _TARGET_PAIRS:
            a, b = table.get(a_lang) or "", table.get(b_lang) or ""
            if not a or not b:
                continue
            a_has, b_has = _has_target_marker(a, a_lang), _has_target_marker(b, b_lang)
            if a_has and not b_has:
                out.append(_issue("PSCT_TARGET_MISSING_EN",
                                  f"{a_lang} 写了取对象，{b_lang} 没有 target",
                                  f"{field}.{b_lang}"))
            elif b_has and not a_has:
                out.append(_issue("PSCT_TARGET_MISSING_ZH",
                                  f"{b_lang} 有 target，{a_lang} 没写「以…为对象」",
                                  f"{field}.{a_lang}"))


def _cross_ir(spec: CardSpec, table: dict, lang: str, field: str,
              out: list[Issue], box: str) -> None:
    """IR ↔ 文本对照：诱发类效果必须写出时点（E04）。"""
    if not table:
        return
    effects = _gen._box_effects(spec, box)
    if not effects:
        return
    an = analyze(table, lang)
    numbered = [p for p in an["paragraphs"] if p.is_effect]
    if len(numbered) != len(effects):
        return                      # 文本与 IR 不同步，不做对照（避免误报）
    tre = rules.TIMING_RE.get(lang, {})
    for p, eff in zip(numbered, effects):
        trig = str(eff.trigger or "").upper()
        if rules.TRIGGER_TIMING_DEFAULT.get(trig) != "when":
            continue
        if not tre.get("when"):
            continue
        # 时点写作 "时" 还是 "场合" 由 params['timing'] 决定，两者都算写了时点
        if not (re.search(tre["when"], p.core)
                or re.search(tre.get("if", r"(?!x)x"), p.core)):
            out.append(_issue("PSCT_TIMING_MISSING",
                              f"第 {p.num} 段（IR 时点 {trig}）没有时点词", field))


# ══════════════════════════════════════════════════════════════════════
#  对外入口
# ══════════════════════════════════════════════════════════════════════
def lint_text(text: str, lang: str, spec: Optional[CardSpec] = None) -> list[Issue]:
    """校验一段卡文。

    :param lang: ``zh_cn`` / ``ja`` / ``en`` / …
    :param spec: 可选的卡牌规格。给了它就能做跨语言对照（取对象、卡名引号）
        与 IR ↔ 文本对照（时点缺失）。
    """
    lang = lang or "zh_cn"
    field = "text" if spec is None else f"text_i18n.{lang}"
    out = _lint_one_text(text or "", lang, spec, field, "monster")
    if spec is not None:
        _cross_language(spec, out)
    return _dedup(out)


def lint(spec: CardSpec, lang: Optional[str] = None) -> list[Issue]:
    """按卡牌规格校验卡文（G-text）。

    ``lang=None`` 时校验所有已填语言；并额外做结构检查
    （效果条数、灵摆框、空卡文）。**不做**任何模型判断。
    """
    out: list[Issue] = []
    texts: dict[str, str] = dict(spec.text_i18n or {})
    pends: dict[str, str] = dict(spec.pendulum_text_i18n or {})

    langs = [lang] if lang else sorted(set(texts) | set(pends))
    for lg in langs:
        if lg in texts:
            out += _lint_one_text(texts[lg], lg, spec, f"text_i18n.{lg}", "monster")
        if lg in pends:
            out += _lint_one_text(pends[lg], lg, spec,
                                  f"pendulum_text_i18n.{lg}", "pendulum")
        if spec is not None:
            _cross_ir(spec, texts.get(lg, ""), lg, f"text_i18n.{lg}", out, "monster")
            if spec.is_pendulum:
                _cross_ir(spec, pends.get(lg, ""), lg,
                          f"pendulum_text_i18n.{lg}", out, "pendulum")

    # ── 结构检查 ──────────────────────────────────────────────
    effects = spec.effect_specs()
    if effects and not any(t.strip() for t in texts.values()) \
            and not any(t.strip() for t in pends.values()):
        out.append(_issue("PSCT_NO_TEXT", f"卡牌有 {len(effects)} 条效果但卡文为空",
                          "text_i18n"))
    if spec.is_monster and len(effects) >= rules.EFFECT_COUNT_WARN and not any(
            p.is_effect
            for t in list(texts.values()) + list(pends.values())
            for p in analyze(t, "zh_cn")["paragraphs"]):
        out.append(_issue("PSCT_EFFECT_COUNT",
                          f"IR 里有 {len(effects)} 条效果，卡文里没有编号", "effects"))
    if spec.is_pendulum and not any(t.strip() for t in pends.values()):
        if any(i in set(spec.pendulum_effect_indices or [])
               for i in range(len(effects))):
            out.append(_issue("PSCT_PENDULUM_NO_EFFECT", "灵摆效果框为空",
                              "pendulum_text_i18n"))
        else:
            out.append(_issue("PSCT_PENDULUM_NO_EFFECT", "灵摆效果框为空",
                              "pendulum_text_i18n", level="INFO"))

    _cross_language(spec, out)
    return _dedup(out)


def _dedup(issues: Sequence[Issue]) -> list[Issue]:
    """同一 (code, field, message) 只保留一条。"""
    seen = set()
    out: list[Issue] = []
    for i in issues:
        key = (i.code, i.field, i.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
    return out
