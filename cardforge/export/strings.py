"""``strings.conf`` 的渲染与解析 —— EDOPro 自定义系列名 / 计数器名的显示来源。

语法（ProjectIgnis / EDOPro 约定，与旧工程产物
``workspace/out/expansions/strings.conf`` 实测一致）::

    # 注释行，整行忽略
    !setname 0x1001 星奏
    !counter 0x1 星奏指示物
    !counter_alias 0x1 星奏计数器

* 指令 = ``!`` + 名字 + 空格 + 十六进制键 + 空格 + **余下整行都是名字**（名字里可以有空格）。
* ``#`` 开头是注释；空行保留位置；**未知指令原样保留**（不丢用户手写的内容）。
* 输出 UTF-8 无 BOM，换行 ``\\n``，指令按十六进制值升序 —— 同输入必然同输出，便于 diff。

本模块是 ``strings.conf`` 的**规范实现**；``pool/cdb.py::write_strings_conf`` 也转调它
（函数内延迟 import，不构成模块级反向依赖）。两个入口的输出逐字节一致。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "DIRECTIVES", "DEFAULT_HEADER", "hexkey", "render", "parse", "merge",
    "write", "read",
]

#: 指令名 → ``parse()`` 结果里的键。
DIRECTIVES: dict[str, str] = {
    "setname": "setnames",
    "counter": "counters",
    "counter_alias": "counters_alias",
}

#: 反向映射（键 → 指令名），保持 ``!setname`` 在最前。
_KEYS: tuple[tuple[str, str], ...] = (
    ("setnames", "setname"),
    ("counters", "counter"),
    ("counters_alias", "counter_alias"),
)

DEFAULT_HEADER = "CardForge 自动生成 —— DIY 系列名 / 计数器名"

_MARK_BEGIN = "# >>> CardForge"
_MARK_END = "# <<< CardForge"


# ══════════════════════════════════════════════════════════════════════
#  键格式化
# ══════════════════════════════════════════════════════════════════════
def hexkey(value: Any) -> str:
    """统一成 ``0x`` + 大写十六进制。

    * ``int`` → 十进制原值转十六进制（``4097`` → ``0x1001``）
    * ``"0x1001"`` / ``"1001"`` → 按**十六进制**解析（setcode 的书写惯例就是 0x）
    * 解析不了的字符串原样返回（用户自有写法，不替他改）
    """
    if isinstance(value, bool):
        return f"0x{int(value):X}"
    if isinstance(value, int):
        return f"0x{value:X}"
    s = str(value).strip()
    if not s:
        return "0x0"
    body = s[2:] if s.lower().startswith("0x") else s
    try:
        return f"0x{int(body, 16):X}"
    except ValueError:
        return s


def _sort_key(item: tuple[Any, Any]) -> tuple[int, Any]:
    """按十六进制数值排序；解析不了的排最后，按字符串排。"""
    key = item[0]
    body = str(key).strip()
    if body.lower().startswith("0x"):
        body = body[2:]
    try:
        return (0, int(body, 16))
    except (ValueError, TypeError):
        return (1, str(key))


def _norm_map(table: Mapping[Any, Any] | Iterable[tuple[Any, Any]] | None
             ) -> dict[str, str]:
    """归一化成 ``{"0x1001": "星奏"}``，键去重（后者覆盖前者）、值去首尾空白。"""
    out: dict[str, str] = {}
    if not table:
        return out
    items = table.items() if isinstance(table, Mapping) else table
    for k, v in items:
        if v is None:
            continue
        out[hexkey(k)] = str(v).strip()
    return out


# ══════════════════════════════════════════════════════════════════════
#  渲染
# ══════════════════════════════════════════════════════════════════════
def render(
    setnames: Mapping[Any, Any] | None = None,
    counters: Mapping[Any, Any] | None = None,
    counters_alias: Mapping[Any, Any] | None = None,
    *,
    unknown: Sequence[str] | None = None,
    comments: Sequence[str] | None = None,
    header: str = DEFAULT_HEADER,
) -> str:
    """渲染 ``strings.conf`` 全文。

    :param unknown: 未知指令的原始行（``parse()["unknown"]`` 的回灌，逐行原样输出）。
    :param comments: 注释行（可带或不带 ``#``）。
    :param header: 首行注释；传空串则不写首行。
    """
    lines: list[str] = []
    if header:
        lines.append(f"# {header.lstrip('# ').rstrip()}")
    for c in (comments or []):
        c = str(c).rstrip("\r\n")
        lines.append(c if c.lstrip().startswith("#") else f"# {c}".rstrip())
    for key, directive in _KEYS:
        table = {"setnames": setnames, "counters": counters,
                 "counters_alias": counters_alias}[key]
        for hk, name in sorted(_norm_map(table).items(), key=_sort_key):
            lines.append(f"!{directive} {hk} {name}".rstrip())
    for line in (unknown or []):
        line = str(line).rstrip("\r\n")
        if line.strip():
            lines.append(line)
    # 全空输入返回空串而不是孤零零一个换行 —— 写盘时才会是真的空文件
    return ("\n".join(lines) + "\n") if lines else ""


# ══════════════════════════════════════════════════════════════════════
#  解析
# ══════════════════════════════════════════════════════════════════════
def parse(text: str) -> dict:
    """解析 ``strings.conf`` 全文。

    :returns: ``{"setnames":{},"counters":{},"counters_alias":{},
        "unknown":[...],"comments":[...],"lines":[...]}``

    ``unknown`` 与 ``comments`` 都是**原始行**（已去行尾换行），可直接回灌 :func:`render`
    实现无损往返。
    """
    out: dict[str, Any] = {k: {} for k, _directive in _KEYS}
    out["unknown"] = []
    out["comments"] = []
    out["lines"] = []
    for raw in str(text or "").splitlines():
        line = raw.rstrip("\r\n")
        out["lines"].append(line)
        stripped = line.strip()
        if not stripped:
            out["comments"].append(line)
            continue
        if stripped.startswith("#"):
            out["comments"].append(line)
            continue
        if not stripped.startswith("!"):
            out["unknown"].append(line)
            continue
        parts = stripped.split(None, 2)
        name = parts[0][1:].lower()
        key = DIRECTIVES.get(name)
        if key is None or len(parts) < 2:
            out["unknown"].append(line)
            continue
        hk = hexkey(parts[1])
        value = parts[2].strip() if len(parts) > 2 else ""
        out[key][hk] = value
    return out


def read(path: str | os.PathLike[str]) -> dict:
    """读文件并解析；文件不存在返回空结构（不抛异常）。"""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return parse("")
    return parse(text)


# ══════════════════════════════════════════════════════════════════════
#  合并 / 写入
# ══════════════════════════════════════════════════════════════════════
def merge(existing: str, *, tag: str = "CardForge", **kw: Any) -> str:
    """把新指令合并进一份**已有**的 strings.conf 文本，返回合并后的全文。

    用 ``# >>> CardForge <tag>`` / ``# <<< CardForge <tag>`` 围出一个受管区块：
    重复调用只会替换区块，不会无限追加，也**不动用户的其它内容**。

    ``**kw`` 全部按关键字转给 :func:`render`（``setnames`` / ``counters`` /
    ``counters_alias`` / ``unknown`` / ``comments``）。
    """
    begin = f"{_MARK_BEGIN} {tag} >>>"
    end = f"{_MARK_END} {tag} <<<"
    body = render(setnames=kw.get("setnames"), counters=kw.get("counters"),
                  counters_alias=kw.get("counters_alias"), header="",
                  unknown=kw.get("unknown"), comments=kw.get("comments")).rstrip("\n")
    block = [begin, *body.split("\n")] if body else [begin]
    block.append(end)

    lines = str(existing or "").splitlines()
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        if lines[i].strip() == begin:
            out.extend(block)
            replaced = True
            i += 1
            while i < len(lines) and lines[i].strip() != end:
                i += 1
            i += 1                      # 跳过 end 行
            continue
        out.append(lines[i])
        i += 1
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.extend(block)
    return "\n".join(out) + "\n"


def write(path: str | os.PathLike[str], **kw: Any) -> str:
    """渲染并写盘（UTF-8 无 BOM，``\\n`` 换行）。返回路径字符串。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(**kw), encoding="utf-8", newline="\n")
    return str(p)
