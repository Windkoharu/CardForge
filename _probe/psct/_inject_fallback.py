"""把 _gen_fallback.py 生成的兜底表注入 lexicon.py（幂等，可重复跑）。

用法::

    python _probe/psct/_gen_fallback.py
    python _probe/psct/_inject_fallback.py

这是**开发期一次性脚本**：注入后 lexicon.py 就是自包含的
（不再依赖 data/lexicons/）。首次注入走标记位，之后走"整块替换"。
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGET = ROOT / "cardforge" / "content" / "psct" / "lexicon.py"

MARK_TERMS = "# @@FALLBACK_TERMS_HERE@@"
MARK_PATTERNS = "# @@FALLBACK_PATTERNS_HERE@@"
HEAD_TERMS = "_FALLBACK_TERMS: dict[str, dict[str, str]] = {"
HEAD_PATTERNS = "_FALLBACK_PATTERNS: dict = {"


def _block_end(lines: list[str], start: int) -> int:
    """从 ``start``（形如 ``xxx = {``）找到配对的收尾 ``}`` 行号（含）。"""
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth <= 0 and i > start:
            return i
    raise ValueError("找不到配对的花括号")


def _replace_block(lines: list[str], head: str, block: str) -> list[str]:
    idx = next((i for i, ln in enumerate(lines) if ln.startswith(head)), None)
    if idx is None:
        raise ValueError(f"找不到块起始行：{head}")
    end = _block_end(lines, idx)
    return lines[:idx] + block.splitlines() + lines[end + 1:]


def main() -> int:
    frag = (HERE / "_fallback_fragment.py.txt").read_text(encoding="utf-8")
    terms_start = frag.index("# @@FALLBACK_TERMS@@")
    pats_start = frag.index("# @@FALLBACK_PATTERNS@@")
    terms_block = frag[terms_start:pats_start].rstrip("\n")
    pats_block = frag[pats_start:].rstrip("\n")

    lines = TARGET.read_text(encoding="utf-8").splitlines()
    if MARK_TERMS in lines:
        lines = [terms_block if ln == MARK_TERMS else ln for ln in lines]
    else:
        lines = _replace_block(lines, HEAD_TERMS, terms_block)
    if MARK_PATTERNS in lines:
        lines = [pats_block if ln == MARK_PATTERNS else ln for ln in lines]
    else:
        lines = _replace_block(lines, HEAD_PATTERNS, pats_block)

    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"injected: {TARGET}  ({TARGET.stat().st_size} bytes, {len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
