"""修 Python 源文件里「字符串字面量被写成真实换行」的缺陷。

并行 agent 通过工具写文件时，把 ``"\\n"`` 写成了**真实换行**，
Python 直接 ``SyntaxError: unterminated string literal``。

策略：反复 ``compile()``，拿到报错行号后判断该行是不是「以未闭合的
``"`` 结尾、且下一行以 ``"`` 开头」—— 是就把换行折回 ``\\n`` 转义。
只动这一种形态，不做激进改写；修不动就打印出来交给人。

用法::

    python tools/fix_string_newlines.py <文件> [--apply]
"""
from __future__ import annotations

import pathlib
import sys


def _unterminated(line: str) -> str | None:
    """返回本行**未闭合**的引号字符；闭合则返回 None。"""
    i, n, open_q = 0, len(line), None
    in_str = False
    while i < n:
        ch = line[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = False
                open_q = None
            i += 1
            continue
        if ch in "\"'":
            # 三引号？
            if line[i:i + 3] in ('"""', "'''"):
                return None                     # 文档字符串交给编译器判断
            in_str = True
            open_q = ch
        i += 1
    return open_q if in_str else None


def fix(path: str, *, apply: bool = False) -> int:
    p = pathlib.Path(path)
    total = 0
    for attempt in range(200):
        src = p.read_text(encoding="utf-8")
        try:
            compile(src, path, "exec")
            print(f"{path}: 语法 OK（共修 {total} 处）")
            return total
        except SyntaxError as e:
            if "unterminated string literal" not in str(e) or not e.lineno:
                print(f"{path}: 停在非断行错误 → 第 {e.lineno} 行：{e.msg}")
                return total
            lines = src.split("\n")
            idx = e.lineno - 1
            cur = lines[idx]
            nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
            q = _unterminated(cur)
            if q != '"':
                print(f"{path}:{e.lineno}: 断的不是双引号（{q!r}），跳过：{cur!r}")
                return total
            tail = nxt.lstrip()
            if not tail.startswith('"'):
                print(f"{path}:{e.lineno}: 下一行不以引号开头，需人工：{nxt!r}")
                return total
            body = tail[1:]
            cut = body.find('"')
            after = body[cut + 1:] if cut >= 0 else ""
            lines[idx] = cur + "\\n" + after
            del lines[idx + 1]
            total += 1
            print(f"  修 {path}:{e.lineno}  换行 → \\n")
            if apply:
                p.write_text("\n".join(lines), encoding="utf-8")
            else:
                print("  （dry-run，加 --apply 才写盘）")
                return total
    print(f"{path}: 达到重试上限")
    return total


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv[1:]
    for f in args or ["cardforge/content/lua/fragments.py"]:
        fix(f, apply=apply)
