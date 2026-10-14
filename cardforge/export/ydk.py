"""``.ydk`` 卡组文件读写 —— EDOPro / YGOPro 的卡组交换格式。

格式（实测约定）::

    #created by CardForge 2.0
    #main
    210000000
    210000000
    210000011
    #extra
    210000020
    !side
    89631139

* ``#main`` / ``#extra`` / ``!side`` 是**段标记**；段标记之前/之中出现的其它 ``#``/``!``
  行都是注释（``#created by …`` 就是典型例子）。
* 每张卡的重复张数 = 卡号出现次数（不写数量字段）。
* 段落顺序固定 main → extra → side；side 用 ``!`` 前缀是官方格式的历史遗留，照抄。
* UTF-8 无 BOM，换行 ``\\n``。

``validate()`` 里的 ``Issue.gate`` 统一标 ``"G5"``：ydk 是导出层产物，归属导出自检。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..core.models import DeckEntry, DeckSpec, Issue

__all__ = [
    "HEADER", "SECTIONS", "DEFAULT_ID_START", "to_text", "from_text",
    "write", "read", "validate", "sizes", "expand",
]

HEADER = "#created by CardForge 2.0"

#: 段名 → ``DeckSpec`` 字段名
SECTIONS: dict[str, str] = {"main": "main", "extra": "extra", "side": "side"}

#: 自造卡卡号起点；``>=`` 此值的卡号才会被 ``pool_ids`` 做存在性校验。
DEFAULT_ID_START = 210000000

#: 规则上限：main 40–60 / extra ≤15 / side ≤15 / 同名 ≤3
LIMITS = {"main_min": 40, "main_max": 60, "extra_max": 15, "side_max": 15,
          "copies": 3}

_SECTION_MARKS = {"#main": "main", "#extra": "extra"}


# ══════════════════════════════════════════════════════════════════════
#  小工具
# ══════════════════════════════════════════════════════════════════════
def _entries(part: Any) -> list[DeckEntry]:
    """把 ``DeckEntry`` / dict / 裸 int 统一成 ``list[DeckEntry]``。"""
    out: list[DeckEntry] = []
    for e in (part or []):
        if isinstance(e, DeckEntry):
            out.append(e)
        elif isinstance(e, Mapping):
            out.append(DeckEntry(
                card_id=int(e.get("card_id") or 0),
                count=int(e.get("count") or 1),
                role=str(e.get("role") or ""),
                name=str(e.get("name") or ""),
            ))
        elif isinstance(e, int):
            out.append(DeckEntry(card_id=int(e), count=1))
        elif isinstance(e, (list, tuple)) and e:
            out.append(DeckEntry(card_id=int(e[0]),
                                 count=int(e[1]) if len(e) > 1 else 1))
    return out


def sizes(deck: DeckSpec) -> dict:
    """各段张数（按 ``count`` 累加），额外附带按卡号去重后的种类数。"""
    out = {}
    for key in ("main", "extra", "side"):
        es = [e for e in _entries(getattr(deck, key, None)) if int(e.card_id or 0)]
        out[key] = sum(max(0, int(e.count or 0)) for e in es)
        out[f"{key}_kinds"] = len({int(e.card_id) for e in es})
    out["total"] = out["main"] + out["extra"] + out["side"]
    return out


def expand(deck: DeckSpec) -> dict[str, list[int]]:
    """展开成三段卡号列表（重复张数 → 重复卡号）。"""
    out: dict[str, list[int]] = {}
    for key in ("main", "extra", "side"):
        ids: list[int] = []
        for e in _entries(getattr(deck, key, None)):
            cid = int(e.card_id or 0)
            if not cid:
                continue
            ids.extend([cid] * max(0, int(e.count or 0)))
        out[key] = ids
    return out


# ══════════════════════════════════════════════════════════════════════
#  序列化
# ══════════════════════════════════════════════════════════════════════
def to_text(deck: DeckSpec, *, header: str = HEADER) -> str:
    """``DeckSpec`` → ``.ydk`` 全文。"""
    ids = expand(deck)
    lines: list[str] = []
    if header:
        lines.append(header if header.lstrip().startswith("#") else f"#created by {header}")
    lines.append("#main")
    lines.extend(str(i) for i in ids["main"])
    lines.append("#extra")
    lines.extend(str(i) for i in ids["extra"])
    lines.append("!side")
    lines.extend(str(i) for i in ids["side"])
    return "\n".join(lines) + "\n"


def write(deck: DeckSpec, path: str | os.PathLike[str]) -> str:
    """写 ``.ydk``（UTF-8 无 BOM，``\\n``）。返回路径字符串。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_text(deck), encoding="utf-8", newline="\n")
    return str(p)


def from_text(text: str, name: str = "", *, archetype: str = "") -> DeckSpec:
    """``.ydk`` 全文 → ``DeckSpec``（同一卡号合并成一条 ``DeckEntry``，保留首见顺序）。"""
    deck = DeckSpec(name=name, archetype=archetype)
    cur = "main"
    notes: list[str] = []
    buckets: dict[str, list[int]] = {"main": [], "extra": [], "side": []}
    for raw in str(text or "").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        low = line.lower()
        if low in _SECTION_MARKS:
            cur = _SECTION_MARKS[low]
            continue
        if low in ("!side", "#side"):
            cur = "side"
            continue
        if line.startswith("#") or line.startswith("!"):
            notes.append(line)           # #created by … 之类的注释
            continue
        try:
            cid = int(line)
        except ValueError:
            notes.append(line)
            continue
        if cid > 0:
            buckets[cur].append(cid)

    for key, ids in buckets.items():
        seen: dict[int, int] = {}
        order: list[int] = []
        for cid in ids:
            if cid not in seen:
                seen[cid] = 0
                order.append(cid)
            seen[cid] += 1
        setattr(deck, key, [DeckEntry(card_id=cid, count=seen[cid]) for cid in order])
    deck.notes = "\n".join(notes)
    return deck


def read(path: str | os.PathLike[str]) -> DeckSpec:
    """读 ``.ydk``。文件不存在/读取失败时返回空 ``DeckSpec``（不抛异常）。"""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return DeckSpec(name=p.stem)
    deck = from_text(text, name=p.stem)
    return deck


# ══════════════════════════════════════════════════════════════════════
#  校验
# ══════════════════════════════════════════════════════════════════════
def _issue(code: str, level: str, message: str, hint: str = "", field: str = "") -> Issue:
    return Issue(gate="G5", code=code, level=level, message=message, hint=hint, field=field)


def validate(
    deck: DeckSpec,
    pool_ids: Iterable[int] | None = None,
    *,
    diy_min: int = DEFAULT_ID_START,
    main_min: int = LIMITS["main_min"],
    main_max: int = LIMITS["main_max"],
    extra_max: int = LIMITS["extra_max"],
    side_max: int = LIMITS["side_max"],
    max_copies: int = LIMITS["copies"],
) -> list[Issue]:
    """卡组合法性校验（返回 ``list[Issue]``，**不抛异常**）。

    检查项：

    * ``YDK_MAIN_SIZE`` 主卡组不在 40–60 → **ERROR**
    * ``YDK_EXTRA_SIZE`` 额外卡组 > 15 → **ERROR**
    * ``YDK_SIDE_SIZE`` 副卡组 > 15 → **ERROR**
    * ``YDK_COPY_LIMIT`` 同名卡 > 3 → **ERROR**（``DeckEntry.name`` 为空时按卡号判同名）
    * ``YDK_CARD_UNKNOWN`` 卡号不在 ``pool_ids`` 里 → **ERROR**
    * ``YDK_EMPTY`` / ``YDK_NAME_EMPTY`` → INFO/WARN

    :param pool_ids: 可用卡号全集。``None`` = 跳过存在性校验。
        只有 ``>= diy_min`` 的卡号才会被校验 —— 官方卡号不在 DIY 卡池里，属正常情况。
        （自造卡固定从 2.1 亿起编号，官方池实测最大 id 为 99995595，不会撞。）
    """
    issues: list[Issue] = []
    s = sizes(deck)

    if s["main"] < int(main_min) or s["main"] > int(main_max):
        issues.append(_issue(
            "YDK_MAIN_SIZE", "ERROR",
            f"主卡组 {s['main']} 张，必须 {main_min}–{main_max} 张",
            hint=f"主卡组还差 {max(0, main_min - s['main'])} 张就合规。"
                 if s["main"] < main_min else
                 f"主卡组超了 {s['main'] - main_max} 张，需要移出。",
            field="main"))
    if s["extra"] > int(extra_max):
        issues.append(_issue(
            "YDK_EXTRA_SIZE", "ERROR",
            f"额外卡组 {s['extra']} 张，上限 {extra_max} 张",
            hint=f"移出 {s['extra'] - extra_max} 张额外卡组。", field="extra"))
    if s["side"] > int(side_max):
        issues.append(_issue(
            "YDK_SIDE_SIZE", "ERROR",
            f"副卡组 {s['side']} 张，上限 {side_max} 张",
            hint=f"移出 {s['side'] - side_max} 张副卡组。", field="side"))

    # 同名 ≤3：名字优先，没名字就用卡号（同卡号必然同名）
    copies: dict[str, int] = {}
    label: dict[str, str] = {}
    for key in ("main", "extra", "side"):
        for e in _entries(getattr(deck, key, None)):
            cid = int(e.card_id or 0)
            if not cid:
                continue
            tag = str(e.name or "").strip() or f"#{cid}"
            copies[tag] = copies.get(tag, 0) + max(0, int(e.count or 0))
            label.setdefault(tag, str(e.name or f"卡号 {cid}"))
    for tag, n in copies.items():
        if n > int(max_copies):
            issues.append(_issue(
                "YDK_COPY_LIMIT", "ERROR",
                f"「{label[tag]}」放了 {n} 张，同名卡上限 {max_copies} 张",
                hint="把多出来的张数换成别的卡，或移进副卡组（副卡组同样受同名限制）。",
                field="copies"))

    if pool_ids is not None:
        pool = {int(i) for i in pool_ids}
        missing = []
        for key in ("main", "extra", "side"):
            for e in _entries(getattr(deck, key, None)):
                cid = int(e.card_id or 0)
                if cid >= int(diy_min) and cid not in pool:
                    missing.append(cid)
        for cid in sorted(set(missing)):
            issues.append(_issue(
                "YDK_CARD_UNKNOWN", "ERROR",
                f"DIY 卡号 {cid} 不在给定卡池里",
                hint="先把它加进导出包并写进卡池，或改用已存在的卡号。",
                field="card_id"))

    if s["total"] == 0:
        issues.append(_issue(
            "YDK_EMPTY", "WARN", "卡组是空的",
            hint="先调用 pipeline.deck.build_deck() 或手动填 main。"))
    if not str(deck.name or "").strip():
        issues.append(_issue(
            "YDK_NAME_EMPTY", "INFO", "卡组没有名字",
            hint="给 DeckSpec.name 赋值，保存与导出时会更好找。"))
    return issues
