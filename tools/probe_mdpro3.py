"""从 .NET 程序集里抽字符串，找 MDPro3 读 DIY 卡的路径与机制。

用途：给 CardForge 接 MDPro3 导出目标之前，先搞清楚**客户端实际读哪些文件**，
而不是照 EDOPro 的 expansions/ 布局硬套（两者差别很大：MDPro3 的脚本在
``Data/script.zip`` 里、卡图在 ``Picture/Art/``、卡池按语言分在
``Data/locales/<lang>/cards.cdb``）。

用法::

    python tools/probe_mdpro3.py <Assembly-CSharp.dll> [--grep 关键词,关键词]
"""
from __future__ import annotations

import re
import sys
import pathlib

ASCII_RE = re.compile(rb"[\x20-\x7e]{4,}")
UTF16_RE = re.compile(rb"(?:[\x20-\x7e][\x00-\xff]){3,}")


def _utf16_strings(blob: bytes) -> set[str]:
    out: set[str] = set()
    for m in UTF16_RE.finditer(blob):
        b = m.group()
        if len(b) % 2:
            b = b[:-1]
        if not b:
            continue
        try:
            s = b.decode("utf-16-le")
        except Exception:
            continue
        # 只留"看起来像人话"的：可打印 + 没有替换符
        if s and all(ch.isprintable() or ch in "\t\n" for ch in s):
            out.add(s)
    return out


def harvest(dll: pathlib.Path) -> list[str]:
    blob = dll.read_bytes()
    rows: set[str] = set()
    for m in ASCII_RE.finditer(blob):
        rows.add(m.group().decode("ascii", "ignore"))
    rows |= _utf16_strings(blob)
    return sorted(r for r in rows if 3 < len(r) < 140)


def main(argv: list[str]) -> int:
    dll = pathlib.Path(argv[0] if argv else
                       "MDPro3_Data/Managed/Assembly-CSharp.dll")
    kws = (argv[1].split(",") if len(argv) > 1 else
           ["cdb", "script", "Picture", "Data/", "DIY", "自制", "自定义",
            "ypk", "CardGenerated", "locales", "Deck", "ydk", "strings.conf",
            "lflist", "Windbot", "repo"])
    rows = harvest(dll)
    out = pathlib.Path("workspace/.cache/mdpro3_strings.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [f"程序集：{dll}  抽出字符串 {len(rows)} 条", ""]
    for k in kws:
        hits = [r for r in rows if k.lower() in r.lower()]
        lines.append(f"═══ 含「{k}」：{len(hits)} 条 ═══")
        lines.extend("   " + h.replace("\n", " ") for h in hits[:120])
        lines.append("")
    text = "\n".join(lines)
    out.write_text(text, encoding="utf-8")
    print(f"写出 {out}（{len(text)} 字符）")
    for k in kws:
        print(f"  {k:14s} {sum(1 for r in rows if k.lower() in r.lower())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
