"""知识库切块与检索 —— 艾莉娅「参谋」职责的唯一数据源。

约束（硬性）
------------
1. **纯 Python、零网络、零向量库。** 打分只用关键词命中 + 中文字符 bigram 覆盖 +
   标题加权，结果可复现（同样的查询永远给同样的分与同样的顺序）。
2. **数据源是 ``data/knowledge/*.md``**（:func:`load` 自动切块）。方法论没覆盖的
   引擎侧事实（灵摆刻度区间、连接标记八个方向、门编号……）另给一组
   :data:`BUILTIN_ENTRIES` 内置速查，``source`` 字段**如实标注**为内置，
   不冒充方法论原文。
3. **检索不是裁决。** 命中的是「设计规律原文」，卡到底平不平衡仍然由
   ``content/design.py`` + ``pipeline/gates.py`` 说了算。

查询侧做了两件提高召回的事：
* **同义词扩展**（:data:`_SYNONYMS`）—— 用户说「打点」「箭头」「禁限卡」，
  文档里写的是「攻击力」「连接标记」「禁卡」。
* **中文按字符 bigram** —— 中文没有空格，整词切分不可靠，bigram 覆盖足够稳。
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Optional

from ..core import paths

__all__ = ["load", "search", "excerpt", "sections", "reload", "corpus_stats",
           "BUILTIN_ENTRIES", "DOC_LANG"]

DOC_LANG = "zh_cn"

#: 单块目标长度（字符）；超过就按段落再切
MAX_CHUNK = 900

_STATE: dict[str, Any] = {"docs": None}
_LOCK = threading.RLock()

_RE_HEADING = re.compile(r"^(#{1,4})\s+(.*)$", re.M)
_RE_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)
_WS = re.compile(r"\s+")

#: ASCII / 数字词（HOPT、ATK、setcode、40、0x100F …）
_RE_ASCII = re.compile(r"[A-Za-z0-9_.+/#-]{2,}")
#: CJK 连续串
_RE_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{1,}")

#: 查询同义词扩展：口语 → 文档用词（只加权重词，不改查询原意）
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "打点": ("攻击力", "ATK", "数值"),
    "atk": ("攻击力", "ATK"),
    "箭头": ("连接标记", "连接", "LINK"),
    "连接箭头": ("连接标记", "连接", "LINK"),
    "刻度": ("灵摆", "刻度"),
    "灵摆": ("灵摆", "刻度"),
    "禁限卡": ("禁卡", "禁止", "限制", "过强"),
    "禁限": ("禁卡", "禁止", "限制", "过强"),
    " banned": ("禁卡",),
    "初动率": ("初动", "上手", "概率"),
    "初动": ("初动", "启动", "Starter"),
    "上手率": ("初动", "上手", "概率"),
    "卡手": ("brick", "连贯", "不连贯"),
    "红旗": ("红旗", "雷区", "泛用", "素材条件", "无限"),
    "素材": ("素材条件", "额外卡组", "融合", "同调", "超量", "连接"),
    "字段": ("archetype", "卡名子串", "setcode", "查重"),
    "查重": ("查重", "命名", "误伤", "冲突"),
    "卡文": ("PSCT", "句式", "文本"),
    "术语": ("PSCT", "句式"),
    "平衡": ("平衡", "铁律", "代价", "限制"),
    "强度": ("过强", "平衡", "铁律"),
    "卡组": ("构筑", "配比", "卡位"),
    "终端": ("王牌", "trumps", "软终端"),
    "手坑": ("手坑", "Hand Trap", "干扰"),
    "副卡组": ("Side Deck", "银弹"),
    "号码": ("卡号", "id", "占用"),
    "锚点": ("三个设计锚点", "胜利方式", "王牌", "属性"),
    "三锚点": ("三个设计锚点", "胜利方式", "王牌", "属性绑定"),
    "阈值": ("上限", "标尺", "不应", "区间"),
    "句式": ("主题效果", "方言", "重复出现"),
    "代价": ("限制", "自肃", "平衡三角"),
}

#: 内置速查：引擎侧 / 质量门侧的稳定事实（``source`` 如实标注，不冒充方法论）
BUILTIN_ENTRIES: list[dict] = [
    {
        "section": "内置速查 · 灵摆刻度（Pendulum Scale）",
        "text": "灵摆刻度合法区间为 1–13（灵摆效果框的「●刻度 n」）。CardForge 的质量门规则："
                "灵摆卡没有设置刻度 → G1_PENDULUM_NO_SCALE（ERROR）；刻度不在 1–13 → "
                "G1_PENDULUM_SCALE_RANGE（WARN）；灵摆卡没有灵摆效果文本 → "
                "G1_PENDULUM_NO_EFFECT（INFO）。设计惯例：本家刻度通常收在 1–4 或 8–12，"
                "让「刻度相加 = 灵摆召唤等级」容易凑；把两个极端刻度（1 与 12 一类）放进同一"
                "系列会明显拉低上手一致性。",
        "source": "cardforge/content/design.py 的 G1 规则 + 官方规则（内置速查，非方法论原文）",
    },
    {
        "section": "内置速查 · 连接标记（连接箭头）",
        "text": "连接怪兽的八个方向标记：上、下、左、右、左上、左下、右上、右下；"
                "引擎里以位掩码存储，连接数值 = 标记数量（1–6）。质量门规则："
                "完全没有连接标记 → G1_LINK_NO_MARKER（ERROR）；标记数与所填数值不一致 → "
                "G1_LINK_RATING（WARN）。设计惯例：箭头指向「自己能做出素材的格子」，"
                "同系列下级的箭头要能互相接住，否则展开路径会断。",
        "source": "cardforge/core/constants.py LINK_MARKER_MAP + content/design.py G1 规则",
    },
    {
        "section": "内置速查 · 禁限卡表（Banlist）",
        "text": "本知识库**不收录官方禁限卡表原文**，CardForge 也不做在线同步（零网络是硬约束）。"
                "因此「会不会被禁」不在质量门的判定范围内，门只按设计规律报警。"
                "与方法论一致的判据（见 §1.4 泛用卡雷区、§1.2 七条铁律）："
                "素材条件过泛、一张卡毁掉整个系列、无代价 +1、无法被应对的封锁 —— "
                "历史上被禁的卡（Isolde / Baronne de Fleur / Union Carrier / Crystron Halqifibrax）"
                "共同点都是**素材条件太宽**，被无数无关卡组滥用。",
        "source": "data/knowledge/游戏王设计方法论.md §1.2/§1.4 的归纳（内置速查说明）",
    },
    {
        "section": "内置速查 · 三次「一回合一次」写法（HOPT）",
        "text": "三种写法语义不同，绝不合并：①「1回合1次」限制这张卡，离场/翻里侧重置；"
                "②「这个卡名的①②效果1回合各能使用1次」= 卡名硬限制（HOPT），限制的是玩家 + "
                "原本卡名，用 use；③「这个卡名的效果1回合只能发动1次」用 activate，被无效后还能再发。"
                "现代卡默认 ②。质量门规则：检索/特召类效果没有任何回合限制 → G1_HOPT_MISSING（ERROR）。",
        "source": "cardforge/core/models.py EFFECT_LIMITS + content/design.py G1 规则",
    },
    {
        "section": "内置速查 · 初动率计算（超几何分布）",
        "text": "「起手至少抽到 1 张初动点」的概率 = 1 − C(D−N, H) / C(D, H)，"
                "D=主卡组张数、N=初动点总张数、H=起手张数（默认 40 / 5）。"
                "方法论给的参考值（40 张、起手 5）：8 张 69.4%、12 张 85.0%、13 张 87.7%、"
                "15 张 91.9%。建议初动 12–15 张。CardForge 里由 "
                "content.design.opening_probability() 计算，卡组层由 analyze_deck() 汇总。",
        "source": "data/knowledge/游戏王设计方法论.md §3.2 + cardforge/content/design.py",
    },
    {
        "section": "内置速查 · 质量门 G1–G5 与状态语义",
        "text": "五道门全部是确定性代码：G1 平衡审计、G2 脚本静态检查、G3 实跑验证、"
                "G4 系列一致性、G5 导出自检。状态取值 pass / warn / fail / waived / "
                "pending / skipped，语义必须分清：skipped = **整道门没跑**（结论不可用，"
                "原因写在 degraded），warn/fail = 门真跑了；degraded 只表示部分子检查没跑成，"
                "门结论仍有效。历史缺陷 #12 就是 G3 谎报「通过」，修法是没真跑过一律返回 skipped。",
        "source": "cardforge/pipeline/gates.py + docs/03-实现状态.md §四",
    },
    {
        "section": "内置速查 · 效果条数与代价（平衡三角）",
        "text": "效果强度、代价、限制三项构成平衡三角：效果强 + 代价低 + 无限制 = 禁卡；"
                "效果弱 + 代价高 + 限制严 = 废卡。条数阈值：单卡效果 ≥3 条即告警、更多则拦截，"
                "≥4 条按红旗 RF17 处理（拆成两张卡或把一条移到魔陷）。",
        "source": "data/knowledge/游戏王设计方法论.md §1.1/§1.2 + content/design.py RED_FLAGS",
    },
]


# ══════════════════════════════════════════════════════════════════════
#  切块
# ══════════════════════════════════════════════════════════════════════
def _mk_chunk(doc_id: str, section: str, text: str, source: str) -> dict:
    clean = _WS.sub(" ", text).strip()
    return {
        "doc_id": doc_id,
        "section": _WS.sub(" ", section).strip(),
        "title": _WS.sub(" ", section.split("·")[-1]).strip(),
        "text": clean,
        "source": source,
    }


def _split_long(chunk: dict) -> list[dict]:
    """长块按段落窗口再切，保证每块都能塞进提示词。"""
    text = chunk.get("text") or ""
    if len(text) <= MAX_CHUNK:
        return [chunk]
    paras = [p for p in re.split(r"\n{2,}", text) if p.strip()] or [text]
    parts: list[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + len(p) > MAX_CHUNK:
            parts.append(buf)
            buf = p
        else:
            buf = f"{buf}\n{p}".strip()
    if buf:
        parts.append(buf)
    out: list[dict] = []
    for i, part in enumerate(parts):
        d = dict(chunk)
        d["section"] = chunk["section"] if len(parts) == 1 else f"{chunk['section']}（{i + 1}）"
        d["text"] = part
        out.append(d)
    return out


def _chunk_markdown(path: Path) -> list[dict]:
    """按标题切块：``##`` / ``###`` 为块边界，标题进 ``section`` 并随行保留在正文里。"""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except Exception:
        return []
    doc_id = path.stem
    matches = list(_RE_HEADING.finditer(raw))
    chunks: list[dict] = []
    if not matches:
        return _split_long(_mk_chunk(doc_id, path.name, raw, path.name))
    # 前言（第一个标题之前的内容）
    head = raw[:matches[0].start()].strip()
    if len(head) > 40:
        chunks.append(_mk_chunk(doc_id, f"{path.name} · 前言", head, path.name))
    for idx, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        if level == 1:
            continue                      # 文件主标题不作为独立块
        # 块尾 = 下一个任意级别标题（父标题只留自己的引言，不吞子块）
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        body = raw[m.start():end].strip()
        if not body:
            continue
        parent = ""
        for prev in matches[:idx][::-1]:
            if len(prev.group(1)) < level:
                parent = prev.group(2).strip()
                break
        section = f"{parent} · {title}" if parent and level >= 3 else title
        chunks.append(_mk_chunk(doc_id, section, body, path.name))
    out: list[dict] = []
    for c in chunks:
        out.extend(_split_long(c))
    return out


def load(*, refresh: bool = False) -> list[dict]:
    """``data/knowledge/*.md`` 切块 + 内置速查，返回 ``list[dict]``（惰性缓存）。"""
    with _LOCK:
        if _STATE["docs"] is not None and not refresh:
            return list(_STATE["docs"])
        docs: list[dict] = []
        base = Path(paths.KNOWLEDGE)
        files: list[Path] = []
        try:
            if base.is_dir():
                files = sorted(p for p in base.glob("*.md") if p.is_file())
        except Exception:
            files = []
        for f in files:
            docs.extend(_chunk_markdown(f))
        for e in BUILTIN_ENTRIES:
            docs.append(_mk_chunk("内置速查", str(e.get("section") or ""),
                                  str(e.get("text") or ""), str(e.get("source") or "")))
        _STATE["docs"] = docs
        return list(docs)


def reload() -> list[dict]:
    """强制重读（改完知识库立刻生效，测试用）。"""
    return load(refresh=True)


def sections() -> list[str]:
    """全部块标题（给 UI 目录 / help）。"""
    return [d["section"] for d in load()]


def corpus_stats() -> dict:
    docs = load()
    return {"chunks": len(docs),
            "docs": sorted({d["doc_id"] for d in docs}),
            "chars": sum(len(d["text"]) for d in docs)}


# ══════════════════════════════════════════════════════════════════════
#  打分
# ══════════════════════════════════════════════════════════════════════
def _bigrams(s: str) -> list[str]:
    return [s[i:i + 2] for i in range(len(s) - 1)] if len(s) >= 2 else ([s] if s else [])


def _terms(query: str) -> tuple[list[str], list[str], list[str]]:
    """→ (整串/词组关键词, ASCII 词, CJK bigram)。含同义词扩展。"""
    q = str(query or "").strip()
    low = q.lower()
    ascii_terms = sorted({t.lower() for t in _RE_ASCII.findall(q)})
    runs = _RE_CJK_RUN.findall(q)
    keys: list[str] = []
    if len(q) >= 2 and q not in runs:
        keys.append(q)
    for r in runs:
        if len(r) >= 2:
            keys.append(r)
    # 同义词扩展：查询词与词条**互为子串**（长度≥2）时，把文档用词补进关键词
    extra: list[str] = []
    probe = [key.lower() for key in keys] + list(ascii_terms)
    for k in probe:
        if len(k) < 2:
            continue
        for syn, words in _SYNONYMS.items():
            sl = syn.strip().lower()
            if k == sl or k in sl or sl in k:
                extra.extend(w for w in words if w not in keys)
    for w in extra:
        if w not in keys:
            keys.append(w)
    grams: list[str] = []
    for r in runs:
        grams.extend(g for g in _bigrams(r))
    seen: set[str] = set()
    keys = [key for key in keys if not (key in seen or seen.add(key))]  # type: ignore[arg-type]
    grams = [g for g in grams if not (g in seen or seen.add(g))]        # type: ignore[arg-type]
    return keys, ascii_terms, grams


def _coverage(grams: list[str], hay: str) -> float:
    if not grams:
        return 0.0
    hit = sum(1 for g in grams if g in hay)
    return hit / len(grams)


def _score_one(doc: dict, keys: list[str], ascii_terms: list[str],
               grams: list[str]) -> float:
    text = str(doc.get("text") or "")
    title = str(doc.get("section") or "") + " " + str(doc.get("title") or "")
    tl = text.lower()
    title_l = title.lower()
    s = 0.0
    for k in keys:
        kl = k.lower()
        if len(k) >= 2 and kl in title_l:
            s += 4.0                       # 标题命中权重最高（方法论按标题分类）
        if len(k) >= 2 and kl in tl:
            s += 2.5
    for a in ascii_terms:
        if a in title_l:
            s += 4.0
        if a in tl:
            s += 3.0                       # 英文/数字词是强判别信号
    s += 3.0 * _coverage(grams, tl)
    s += 2.0 * _coverage(grams, title_l)
    # 表格行里的数字（刻度区间/概率表）在正文里出现就给一点结构分
    if grams and _RE_TABLE_ROW.search(text) and _coverage(grams, tl) >= 0.5:
        s += 0.6
    return round(s, 4)


def search(query: str, k: int = 4) -> list[dict]:
    """关键词 + 字符 bigram + 标题加权的检索。**不依赖向量库、不依赖网络。**

    返回 ``[{"doc_id","section","score","text","source", ...}]``；
    一个都没命中时不返回空列表骗人，而是给出分块头名并标 ``"low_confidence": True``。
    """
    docs = load()
    if not docs:
        return []
    keys, ascii_terms, grams = _terms(query)
    if not (keys or ascii_terms or grams):
        d = dict(docs[0])
        d.update({"score": 0.0, "low_confidence": True,
                  "matched": [], "query": str(query or "")})
        return [d]
    scored = [(_score_one(d, keys, ascii_terms, grams), d) for d in docs]
    scored.sort(key=lambda t: (-t[0], t[1]["section"]))
    limit = max(1, int(k or 1))
    hits = [(sc, d) for sc, d in scored if sc > 0][:limit]
    out: list[dict] = []
    pool = hits or [(scored[0][0], scored[0][1])]
    for sc, d in pool:
        tl = str(d.get("text") or "").lower()
        title_l = (str(d.get("section") or "") + str(d.get("title") or "")).lower()
        matched = [t for t in keys + ascii_terms if len(t) >= 2 and (t in tl or t in title_l)]
        item = dict(d)
        item["score"] = float(sc)
        item["matched"] = matched
        item["query"] = str(query or "")
        item["low_confidence"] = bool(sc <= 0)
        out.append(item)
    return out


def excerpt(doc_id: str, section: str) -> str:
    """取某块原文。``doc_id`` / ``section`` 允许前缀与子串模糊匹配；找不到返回 ``""``。"""
    want_doc = str(doc_id or "").strip()
    want_sec = str(section or "").strip()
    if not want_sec and not want_doc:
        return ""
    best = ""
    for d in load():
        if want_doc and want_doc not in str(d.get("doc_id") or ""):
            continue
        sec = str(d.get("section") or "")
        if not want_sec:
            return str(d.get("text") or "")
        if sec == want_sec:
            return str(d.get("text") or "")
        if want_sec in sec or sec in want_sec:
            if not best:
                best = str(d.get("text") or "")
    return best
