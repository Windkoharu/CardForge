"""零 AI 的卡文**整理 + 校验** —— 把你手写的一段效果文本，收拾成标准 PSCT 描述。

为什么要有这一层
----------------
内核一直有两条腿：``effects.infer_from_text``（卡文 → IR）与
``psct.gen``（IR → 标准卡文）。但它们各自只服务一个按钮：「从卡文推断」把文本
拆成 IR（**会动你的效果列表**），「生成卡文」把 IR 投影回文本（**会覆盖你写的文本**）。
中间缺的正是用户最想要的那一步：**我只想把这段文字整理干净，别碰我的卡。**

本模块提供第三条路，四条硬规定：

1. **绝不静默改语义。** 分两层做：
   * **L1 表层**（:func:`surface`）：标点、引号、段号、空白、全角数字 ——
     纯字符级归一，不动词、不动结构、不动数值；
   * **L2 结构**（:func:`tidy`）：只有当这一段**被内核完整识别**
     （认得出 ``kind``，且重写后再反解回来的 IR 与原 IR **逐字段相等**）时，
     才用 :func:`cardforge.content.psct.gen.effect_to_text` 重写整段。
     对不上就退回 L1，并在结果里写明「为什么没敢重写」。
2. **认不出来的句子原样保留。** 召唤手续段（素材行 / 「…才能特殊召唤。」 / 「●…」）
   是 ``spec.summon`` 的产物，这里**一个字都不改**，只提示去哪改。
3. **术语只报不改。** 「同步→同调」这类裁决来自官方简中卡文库实测，
   但替换会连卡名一起伤（「XYZ-神龙炮」「喷气同调士」），所以只出建议清单。
4. **一键替换有门槛。** 只有「每一段都被识别 + 数值与卡名逐字保真 +
   整理后 lint 的 ERROR 不比整理前多」三件事同时成立，
   ``safe_to_apply`` 才为真；否则界面只允许逐段采纳。

报告形态见 :func:`tidy` 的返回值；界面拿它渲染「左原文 / 右整理后 / 改了什么」。
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ...core.enums import LANGS
from ...core.models import CardSpec
from . import gen, rules

__all__ = ["Edit", "Para", "surface", "tidy", "TERM_SUGGESTIONS"]


def _lang_label(lang: str) -> str:
    spec = LANGS.get(lang)
    return getattr(spec, "zh_cn", None) or lang


# ══════════════════════════════════════════════════════════════════════
#  数据结构
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Edit:
    """一处改动：稳定规则号 + 改前改后 + 一句人话理由。"""

    code: str
    from_text: str
    to_text: str
    why: str

    def to_dict(self) -> dict:
        return {"code": self.code, "from": self.from_text,
                "to": self.to_text, "why": self.why}


@dataclass
class Para:
    """一个段落的整理结果。"""

    index: int                       # 框内编号（1 起）；0 = 召唤手续段
    kind: str                        # summon_block | effect | declaration | plain
    src: str
    out: str
    status: str                      # rewritten | surface | kept
    recognized: bool = False
    reason: str = ""                 # 为什么重写 / 为什么没敢重写
    edits: list[Edit] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.out != self.src

    def to_dict(self) -> dict:
        return {"index": self.index, "kind": self.kind, "src": self.src,
                "out": self.out, "status": self.status, "changed": self.changed,
                "recognized": self.recognized, "reason": self.reason,
                "edits": [e.to_dict() for e in self.edits],
                "rules": sorted({e.code for e in self.edits})}


# ══════════════════════════════════════════════════════════════════════
#  1. L1 表层归一（纯字符级，永远安全）
# ══════════════════════════════════════════════════════════════════════
#: 全角数字 → 半角（官方简中卡文实测用半角：「1回合1次」而不是「１回合１次」）
_FW_NUM = str.maketrans("０１２３４５６７８９", "0123456789")
#: 弯引号直接映射；**直引号必须按出现次序配对** ——
#: 以前把 ``"`` 一律换成 ``「``，于是 ``"星尘龙"`` 变成 ``「星尘龙「``，
#: 整理器自己造出一句更不对的文本（自检抓到才修的）。
_QUOTE_MAP = {"“": "「", "”": "」", "‘": "「", "’": "」"}


def _convert_quotes(s: str) -> str:
    out: list[str] = []
    open_next = True                       # 下一个直引号该是开还是闭
    for ch in s:
        if ch in _QUOTE_MAP:
            out.append(_QUOTE_MAP[ch])
            open_next = ch in ("“", "‘")   # 弯引号会重新设定配对方向
        elif ch == '"':
            out.append("「" if open_next else "」")
            open_next = not open_next
        elif ch == "'":
            out.append("「" if open_next else "」")
            open_next = not open_next
        else:
            out.append(ch)
    return "".join(out)
#: 段号别名：``1.`` ``1、`` ``（1）`` ``(1)`` ``[1]`` → ①
#: （``(?!\d)`` 保证 ``1.5`` 这种小数不被当成段号；只认行首）
_NUM_HEAD = re.compile(
    r"^[\s　]*(?:[（(\[](\d{1,2})[)）\]][\.、．:：]?|(\d{1,2})[\.、．:：](?!\d))[\s　]*")
#: 重复标点
_DUP_PUNCT = re.compile(r"([。，、；：！？])\1+")


def surface(text: str, lang: str = "zh_cn") -> tuple[str, list[Edit]]:
    """字符级归一，返回 ``(新文本, 改动清单)``。

    只做**不会改变任何词义**的事：空白、全角数字、段号、引号形状、
    标点角色、重复标点。动词、句式、数值一律不碰。

    **顺序是有讲究的**：段号必须赶在「. → 。」之前归一 ——
    反过来的话 ``1. 把自己场上…`` 会先被句号规则改成 ``1。把自己场上…``，
    既难看又再也认不出那是段号（实测踩过）。
    """
    st = rules.style(lang)
    edits: list[Edit] = []
    src = str(text or "")
    s = src

    # ── 空白 ──
    s2 = re.sub(r"[ \t　]+\n", "\n", s)
    s2 = re.sub(r"\n{3,}", "\n\n", s2)
    s2 = "\n".join(ln.strip() for ln in s2.split("\n"))
    if s2 != s:
        edits.append(Edit("TIDY_WHITESPACE", s, s2, "去掉行尾空白与多余空行"))
    s = s2

    if st.cjk:
        # ── 全角数字 → 半角 ──
        s2 = s.translate(_FW_NUM)
        if s2 != s:
            edits.append(Edit("TIDY_FULLWIDTH_DIGIT", "１２３", "123",
                              "官方简中卡文用半角数字（「1回合1次」）"))
        s = s2

        # ── 段号归一：``1.`` ``1、`` ``（1）`` ``(1)`` ``[1]`` → ① ─
        s2 = _renumber(s)
        if s2 != s:
            edits.append(Edit("TIDY_PARA_MARK", "1. / （1） / (1)", "① ② ③",
                              "段号统一用官方简中的带圈数字，"
                              "内核据此分配卡文编号与脚本 Stringid 槽位"))
        s = s2

        # ── 引号 → 「」 ──
        if any(c in s for c in '"“‘’”'):
            s2 = _convert_quotes(s)
            if s2 != s:
                edits.append(Edit("TIDY_QUOTES", "“”/\"\"", st.quote_open + "…" + st.quote_close,
                                  f"{_lang_label(lang)}的卡名引用统一用「」，并按出现次序配对"))
            s = s2

        # ── 标点角色：半角 : ; 与句末 . → 全角（数字后面那个点不是句号）──
        s2 = re.sub(r"(?<![0-9A-Za-z]):(?![0-9A-Za-z])", st.colon, s)
        s2 = re.sub(r";", st.semi, s2)
        s2 = re.sub(r"(?<![0-9])\.(?=\s|$|「|”)", st.period, s2)
        if s2 != s:
            edits.append(Edit("TIDY_PUNCT_ROLE", ": ; .", f"{st.colon} {st.semi} {st.period}",
                              "条件分隔 / 发动分隔 / 句号按" + _lang_label(lang) + "的排版角色归一"))
        s = s2

    # ── 重复标点 ──
    s2 = _DUP_PUNCT.sub(r"\1", s)
    if s2 != s:
        edits.append(Edit("TIDY_DUP_PUNCT", "。。／，，", "。／，", "重复标点合并"))
    s = s2
    # 「，。」这种句末悬挂逗号
    s2 = re.sub(r"[，,](?=。)", "", s)
    if s2 != s:
        edits.append(Edit("TIDY_TRAILING_COMMA", "…，。", "…。", "句号前的逗号是笔误"))
    s = s2
    return s, edits


def _renumber(text: str) -> str:
    """把行首的 ``1.`` / ``1、`` / ``（1）`` / ``[1]`` 换成官方带圈数字 ``①``。

    三道护栏，防止把正文里的数字当段号：
    ① 只认**行首**；② 只认 1–20（卡文一段最多 20 条，与 ``NUMBER_MAX`` 一致）；
    ③ 数字后面紧跟的不能又是数字（``1.5`` 这种小数不动）。
    """
    out: list[str] = []
    n = 0
    for line in str(text or "").split("\n"):
        m = _NUM_HEAD.match(line)
        if m:
            raw = next((g for g in m.groups() if g), None)
            try:
                val = int(raw)
            except (TypeError, ValueError):
                val = 0
            if 1 <= val <= 20:
                n = val
                tail = line[m.end():].lstrip()
                line = rules.number_symbol(val) + ("：" + tail if tail and not
                                                   tail.startswith(("：", ":")) else tail)
        out.append(line)
    return "\n".join(out)


def normalize_numbers(text: str) -> str:
    """把全角数字折成半角，用于**保真比对**（比对时不该因字形不同而判失败）。"""
    return str(text or "").translate(_FW_NUM)


# ══════════════════════════════════════════════════════════════════════
#  2. 保真守卫
# ══════════════════════════════════════════════════════════════════════
_NAME_IN_QUOTES = re.compile(r"「([^」]+)」")
_DIGITS = re.compile(r"\d+")


def _digits_of(text: str) -> list[str]:
    return _DIGITS.findall(normalize_numbers(text))


def _names_of(text: str) -> list[str]:
    return sorted(_NAME_IN_QUOTES.findall(text or ""))


def _ir_sig(eff: Any) -> tuple:
    """一条效果 IR 的**语义指纹**：只取决定规则含义的字段。

    重写前后指纹必须逐字相等 —— 这是「整理不许改语义」的机器判据。
    ``raw_text`` / ``note`` / ``params['_index']`` 这类追溯字段不参与。
    """
    if eff is None:
        return ()
    t = eff.target.to_dict() if getattr(eff, "target", None) else None
    c = eff.cost.to_dict() if getattr(eff, "cost", None) else None
    params = {k: v for k, v in (getattr(eff, "params", {}) or {}).items()
              if not str(k).startswith("_")}
    return (str(eff.kind or ""), str(eff.trigger or ""), str(eff.limit or ""),
            repr(t), repr(c), repr(sorted(params.items())))


def _infer_one(text: str, name: str = "") -> list:
    """卡文 → IR（延迟导入避免成环：effects ↔ psct ↔ summon）。"""
    from .. import effects as E
    try:
        return list(E.infer_from_text(text, name) or [])
    except Exception:                                    # noqa: BLE001
        return []


# ══════════════════════════════════════════════════════════════════════
#  3. 术语建议（只报不改）
# ══════════════════════════════════════════════════════════════════════
def term_suggestions(text: str, lang: str) -> list[dict]:
    """命中的民间/繁中术语 —— **只出建议，绝不自动替换**。

    为什么不自动替换：这些词会出现在卡名里（「XYZ-神龙炮」「喷气同调士」
    「真红眼·同步」…），字符串替换会连名字一起改掉。
    """
    out: list[dict] = []
    stripped = _strip_quoted(text)
    for term in rules.FOLK_TERMS:
        if lang not in term.langs:
            continue
        if term.bad in stripped:
            out.append({"bad": term.bad, "good": term.good,
                        "why": term.why, "level": term.level})
    if lang == "en":
        for old, new in rules.OLD_TERMS_EN:
            if re.search(rf"(?<![A-Za-z]){re.escape(old)}(?![A-Za-z])", stripped, re.I):
                out.append({"bad": old, "good": new,
                            "why": "PSCT 变更前的旧英文术语", "level": "WARN"})
    return out


def _strip_quoted(text: str) -> str:
    """把「…」里的内容挖空（卡名不参与术语判定）。"""
    return _NAME_IN_QUOTES.sub("〔〕", str(text or ""))


TERM_SUGGESTIONS = term_suggestions


# ══════════════════════════════════════════════════════════════════════
#  4. 主入口
# ══════════════════════════════════════════════════════════════════════
def _lint(spec: Optional[CardSpec], text: str, lang: str) -> dict:
    """对「这段文本」跑一次 PSCT 校验（在 spec 的**副本**上，绝不写脏真 spec）。"""
    from . import lint as L
    base = spec if spec is not None else CardSpec(id=0, name="", frame="effect")
    s = copy.deepcopy(base)
    s.text_i18n = dict(s.text_i18n or {})
    s.text_i18n[lang] = text
    try:
        issues = list(L.lint(s, lang) or [])
    except Exception as e:                               # noqa: BLE001
        return {"errors": 0, "warns": 0, "issues": [],
                "error": f"校验执行失败：{type(e).__name__}: {e}"}
    return {"errors": sum(1 for i in issues if i.level == "ERROR"),
            "warns": sum(1 for i in issues if i.level in ("WARN", "INFO")),
            "issues": [{"code": i.code, "level": i.level, "message": i.message,
                        "hint": i.hint, "field": i.field} for i in issues]}


def _is_declaration(para: str) -> bool:
    """卡名级使用次数声明（「这个卡名的①的效果1回合只能使用1次。」）。

    它是 :func:`gen.compose` 按 IR 的 ``limit`` 收集后**另起一句**的产物，
    不是一条效果 —— 反解它会得到空 ``kind``，所以这里单独归类并原样保留。
    """
    s = str(para or "").strip()
    if not s:
        return False
    return bool(re.search(r"这个卡名的.{0,8}(效果|卡).{0,12}(只能|仅).{0,8}(发动|使用)", s)) \
        or bool(re.search(r"^「.+」\s*1回合", s))


_DECL_RE = re.compile(r"(?=(?:这个卡名的|「[^」]+」\s*1回合))")


def _peel_declaration(para: str) -> tuple[str, str]:
    """把粘在效果段尾巴上的**卡名级使用次数声明**剥出来 → ``(效果段, 声明句)``。

    官方卡面里这句是独立一句（由每条效果的「使用次数限制」汇总生成），
    但 ``_split_paragraphs`` 只按 ①②③ 切，于是「②…上升300点。
    这个卡名的①的效果1回合只能使用1次。」会被当成同一段 ——
    整段既不是效果也不是声明，重写与保留都判不对（实测就是这个坑）。
    """
    s = str(para or "").strip()
    parts = _DECL_RE.split(s)
    if len(parts) < 2:
        return s, ""
    main = parts[0].strip()
    decl = "\n".join(p.strip() for p in parts[1:] if p.strip())
    return main, decl


def _paragraphs(text: str) -> list[tuple[int, str]]:
    """切段。**先按 ①②③ 切，切不出来再按行切**。

    ``effects._split_paragraphs`` 只认带圈段号（那是官方卡面的形状），
    但用户手写经常是「一行一条、没有编号」—— 那种文本必须也能逐段处理，
    否则整块会被当成一段而永远识别不出来（实测就是这个坑）。
    """
    from .. import effects as E
    src = str(text or "").strip()
    if not src:
        return []
    paras = list(E._split_paragraphs(src) or [])
    if len(paras) > 1:
        return paras
    lines = [ln.strip() for ln in src.split("\n") if ln.strip()]
    if len(lines) > 1:
        return [(i + 1, ln) for i, ln in enumerate(lines)]
    return paras or [(1, src)]


def tidy(text: str, spec: Optional[CardSpec] = None,
         lang: str = "zh_cn", *, name: str = "", rewrite: bool = True) -> dict:
    """把手写卡文整理成标准描述，返回**逐段可追溯**的结果。

    :param text: 用户写的效果文本（一个文本框的全部内容）。
    :param spec: 卡牌规格。用于投影标准句式与跑校验；``None`` 时只做 L1 表层整理。
    :param lang: 语言（``zh_cn`` / ``ja`` / ``en`` …）。
    :param name: 卡名。默认取 ``spec.name``；反解「「卡名」以外的」需要它。
    :param rewrite: ``False`` 时**完全不做 L2 结构重写**，只交表层整理
        （给「我就想把标点弄干净」这种用法）。
    :return: ``{"ok", "lang", "text", "changed", "paragraphs": [...],
        "surface_edits": [...], "terms": [...], "lint_before", "lint_after",
        "recognized", "total", "confidence", "safe_to_apply", "blockers",
        "fidelity", "notes"}``

    ``safe_to_apply`` 为真的三个条件（缺一不可）：

    1. 每一段效果都被内核**完整识别**（认不出就不许整段替换）；
    2. 数值与卡名**逐字保真**（整理前后数字串多重集合相等、「」里的名字相等）；
    3. 整理后 lint 的 **ERROR 数不比整理前多**。
    """
    src = str(text or "")
    st = rules.style(lang)
    card_name = str(name or getattr(spec, "name", "") or
                    (spec.name_in(lang) if spec is not None else "") or "").strip()
    notes: list[str] = []

    # ── 1. 召唤手续段先摘出来（它是 spec.summon 的产物，一个字都不改）──
    from .. import summon as S
    block, rest = S.split_leading_block(src)
    block_out, block_edits = (surface(block, lang) if block else ("", []))

    # ── 2. 先按**原文**切段，再逐段表层归一 ──
    # 顺序很重要：先整体归一再切段的话，``Para.src`` 拿到的已经是归一后的文本，
    # 界面上「1. → ①：」这类改动就看不见了 —— 而那正是用户最想核对的一处。
    work: list[tuple[int, str, str]] = []               # (编号, 原文, 归一后)
    tail_decls: list[tuple[str, str]] = []              # (声明原句, 声明归一后)
    surf_edits: list[Edit] = list(block_edits)
    for idx0, raw in _paragraphs(rest):
        norm0, es = surface(raw, lang)
        for e in es:
            if not any(e.code == x.code and e.from_text == x.from_text
                       and e.to_text == x.to_text for x in surf_edits):
                surf_edits.append(e)
        main_src, decl_src = _peel_declaration(raw)
        main_norm, decl_norm = _peel_declaration(norm0)
        if main_src.strip() or main_norm.strip():
            work.append((idx0, main_src.strip(), main_norm.strip()))
        if decl_src.strip() or decl_norm.strip():
            tail_decls.append((decl_src.strip() or decl_norm.strip(),
                               decl_norm.strip()))

    out_paras: list[Para] = []
    if block_out.strip():
        out_paras.append(Para(
            index=0, kind="summon_block", src=block, out=block_out,
            status="surface" if block_edits else "kept", recognized=True,
            reason="召唤手续段（素材行 / 「…才能特殊召唤。」 / 「●…」）是「规格 → 召唤条件」"
                   "的投影产物，这里不重写 —— 要改词去规格页改召唤条件。",
            edits=block_edits))

    rewritten = 0
    for idx, p_src, para in work:
        if _is_declaration(para):
            out_paras.append(Para(idx, "declaration", p_src, para, "kept", True,
                                  "卡名级使用次数声明由每条效果的「使用次数限制」汇总生成，"
                                  "不在这里重写。"))
            continue
        effs = _infer_one(para, card_name)
        eff = effs[0] if len(effs) == 1 else None
        recognized = bool(eff is not None and (eff.kind or ""))
        if not recognized:
            why = ("这段内核认不出效果种类" if not effs else
                   f"这段被拆成了 {len(effs)} 条效果，无法确定重写边界" if len(effs) > 1 else
                   "认出了时点/代价但没有处理动作 —— 多半是漏写了「才能发动。」或处理句")
            out_paras.append(Para(idx, "effect", p_src, para, "kept", False,
                                  why + "。已**原样保留**，只做标点归一。"
                                        "去规格页手工补这条效果，或把句子写成"
                                        "「…才能发动。…」的完整形状。"))
            continue
        # ── L2：整段重写，但要过三道保真守卫 ──
        if not rewrite or spec is None:
            out_paras.append(Para(idx, "effect", p_src, para, "surface", True,
                                  "已识别（" + str(eff.kind) + "）；"
                                  + ("未提供卡规格，只做表层整理。" if spec is None
                                     else "按请求关闭了结构重写。")))
            continue
        try:
            new = gen.effect_to_text(eff, spec, lang, index=idx)
        except Exception as e:                           # noqa: BLE001
            out_paras.append(Para(idx, "effect", p_src, para, "surface", True,
                                  f"重写失败（{type(e).__name__}: {e}），退回表层整理。"))
            continue
        if not new or new.strip() == para.strip():
            out_paras.append(Para(idx, "effect", p_src, new or para, "kept", True,
                                  "已经是标准写法，无需改动。"))
            continue
        # 守卫 A：再反解一次，IR 指纹必须逐字相等
        back = _infer_one(new, card_name)
        sig_before = _ir_sig(eff)
        sig_after = _ir_sig(back[0]) if len(back) == 1 else ("(拆成多条)",)
        # 守卫 B：数值与卡名逐字保真
        digits_ok = _digits_of(para) == _digits_of(new)
        names_ok = _names_of(para) == _names_of(new)
        if not (sig_before == sig_after and digits_ok and names_ok):
            miss = []
            if sig_before != sig_after:
                miss.append("重写后再反解回来的 IR 与原 IR 不一致（语义可能被动过）")
            if not digits_ok:
                miss.append(f"数值变了：{_digits_of(para)} → {_digits_of(new)}")
            if not names_ok:
                miss.append(f"卡名引用变了：{_names_of(para)} → {_names_of(new)}")
            out_paras.append(Para(idx, "effect", p_src, para, "surface", True,
                                  "识别成功但**没敢重写**：" + "；".join(miss) +
                                  "。已退回只做标点归一。"))
            continue
        rewritten += 1
        out_paras.append(Para(idx, "effect", p_src, new, "rewritten", True,
                              f"整段按内核句式重写（种类 {eff.kind} / 时点 {eff.trigger} / "
                              f"限制 {eff.limit}），并已通过「再反解 IR 等价 + 数值与卡名保真」两道守卫。",
                              [Edit("TIDY_REWRITE", para, new,
                                    f"识别为 {eff.kind}，按官方句式重写整段")]))

    # 剥下来的卡名级声明：原样保留（它由每条效果的「使用次数限制」汇总生成）
    for decl_src, decl_norm in tail_decls:
        out_paras.append(Para(0, "declaration", decl_src, decl_norm or decl_src,
                              "kept", True,
                              "卡名级使用次数声明由每条效果的「使用次数限制」汇总生成，"
                              "不在这里重写 —— 要改次数去规格页改那条效果的限制。"))

    # ── 4. 汇总文本 ──
    pieces: list[str] = []
    if block_out.strip():
        pieces.append(block_out.strip())
    effect_part = "\n".join(p.out.strip() for p in out_paras if p.kind != "summon_block")
    if effect_part.strip():
        pieces.append(effect_part.strip())
    final = "\n".join(pieces)

    # ── 5. 校验前后对比 ──
    lb = _lint(spec, src, lang)
    la = _lint(spec, final, lang)

    # ── 6. 一键替换的三道门槛 ──
    blockers: list[str] = []
    unrecognized = [p.index for p in out_paras if p.kind == "effect" and not p.recognized]
    if unrecognized:
        blockers.append(f"第 {'、'.join(str(i) for i in unrecognized)} 段内核认不出来，"
                        "原样保留中 —— 整段替换会把它们照原样带回去，"
                        "所以这里只允许逐段采纳。")
    # 保真基线是**表层归一之后**的文本，不是用户原始输入 ——
    # L1 本来就会把 “” 变成「」（「」里的名字因此「变多」），
    # 拿原文当基线会把这种正当改动误报成「卡名丢了」。
    base_norm = "\n".join(x for x in [block_out] + [w[2] for w in work]
                          + [d[1] for d in tail_decls] if x.strip())
    digits_ok = _digits_of(base_norm) == _digits_of(final)
    names_ok = _names_of(base_norm) == _names_of(final)
    if not digits_ok:
        blockers.append(f"数值对不上：{list(_digits_of(base_norm))} → {list(_digits_of(final))}")
    if not names_ok:
        blockers.append("卡名引用对不上，检查是不是把「」里的内容弄丢了")
    if la.get("errors", 0) > lb.get("errors", 0):
        blockers.append(f"整理后校验的 ERROR 反而变多（{lb.get('errors', 0)} → "
                        f"{la.get('errors', 0)}），不要采纳")
    if la.get("error") or lb.get("error"):
        blockers.append("校验器本身没跑成，无法判断整理是否安全")

    total_effect = sum(1 for p in out_paras if p.kind == "effect")
    recognized_n = sum(1 for p in out_paras if p.kind == "effect" and p.recognized)
    confidence = round(recognized_n / total_effect, 3) if total_effect else 1.0
    if not src.strip():
        blockers.append("文本是空的")

    if rewritten:
        notes.append(f"{rewritten} 段按官方句式整段重写；其余只做表层归一。")
    if not total_effect and block_out.strip():
        notes.append("这段只有召唤手续文本，没有效果段 —— 要改它去规格页的「召唤条件」。")
    if term_suggestions(final, lang):
        notes.append("术语建议见 terms 列表（**只报不改**：这些词会出现在卡名里，"
                     "自动替换会连名字一起改掉）。")

    return {
        "ok": True,
        "lang": lang,
        "lang_label": _lang_label(lang),
        "text": final,
        "changed": final != src,
        "paragraphs": [p.to_dict() for p in out_paras],
        "surface_edits": [e.to_dict() for e in surf_edits],
        "terms": term_suggestions(final, lang),
        "lint_before": lb,
        "lint_after": la,
        "recognized": recognized_n,
        "total": total_effect,
        "rewritten": rewritten,
        "confidence": confidence,
        "safe_to_apply": (not blockers) and (final != src),
        "blockers": blockers,
        "fidelity": {
            "numbers_ok": digits_ok,
            "names_ok": names_ok,
            "all_recognized": bool(total_effect) and recognized_n == total_effect,
        },
        "notes": notes,
    }
