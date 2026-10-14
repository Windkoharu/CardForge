"""极简 JS 括号平衡检查器（找语法错误的定位工具，不是解析器）。

处理：单引号 / 双引号 / 模板字符串（含 ${} 插值）/ 行注释 / 块注释。
用途：浏览器只报 "Unexpected token"，不给行号；这个脚本能指到第一个
不配对的括号上。
"""
from __future__ import annotations

import pathlib
import sys

PAIRS = {"(": ")", "[": "]", "{": "}"}
CLOSING = {v: k for k, v in PAIRS.items()}


def check(path: str) -> str:
    s = pathlib.Path(path).read_text(encoding="utf-8")
    i, n, line = 0, len(s), 1
    stack: list[tuple[str, int]] = []
    while i < n:
        c = s[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "/":
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "*":
            j = s.find("*/", i + 2)
            line += s.count("\n", i, j if j > 0 else n)
            i = n if j < 0 else j + 2
            continue
        if c in "'\"`":
            q = c
            j = i + 1
            while j < n:
                ch = s[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == q:
                    break
                if ch == "\n":
                    line += 1
                    if q != "`":
                        break          # 普通字符串里出现换行 = 引号没闭合
                if q == "`" and ch == "$" and j + 1 < n and s[j + 1] == "{":
                    d = 1
                    j += 2
                    while j < n and d:
                        if s[j] == "{":
                            d += 1
                        elif s[j] == "}":
                            d -= 1
                        elif s[j] == "\n":
                            line += 1
                        j += 1
                    continue
                j += 1
            i = j + 1
            continue
        if c in PAIRS:
            stack.append((c, line))
            i += 1
            continue
        if c in CLOSING:
            if not stack:
                return f"{path}:{line}: 多余的 '{c}'，没有对应的开括号"
            o, ol = stack.pop()
            if PAIRS[o] != c:
                return f"{path}:{line}: '{c}' 与第 {ol} 行的 '{o}' 不匹配"
            i += 1
            continue
        i += 1
    if stack:
        o, ol = stack[-1]
        return f"{path}: 文件末尾仍有第 {ol} 行的 '{o}' 未闭合"
    return f"{path}: 括号平衡 OK"


if __name__ == "__main__":
    files = sys.argv[1:] or [f"web/js/{n}.js" for n in
                             ("spec", "art", "app", "text", "pack",
                              "gates", "assistant", "state", "ui", "api")]
    for p in files:
        print(check(p))
