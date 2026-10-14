# -*- coding: utf-8 -*-
"""只处理「正则条目行」：以 `("` 或 `(r"` 开头的元组元素行，把含反斜杠的字面量改成 raw。"""
import pathlib
import re

p = pathlib.Path(r"D:\游戏王DIY设计\cardforge\content\effects.py")
lines = p.read_text(encoding="utf-8").splitlines()

STR = re.compile(r'(?<![r])"((?:[^"\\]|\\.)*)"')
ENTRY = re.compile(r'^\s*\(r?"')

changed = 0
for i, ln in enumerate(lines):
    if not ENTRY.match(ln):
        continue
    if "\\" not in ln:
        continue
    new = ln
    out = []
    pos = 0
    for m in STR.finditer(new):
        body = m.group(1)
        out.append(new[pos:m.start()])
        out.append(('r"' + body + '"') if "\\" in body else m.group(0))
        pos = m.end()
    out.append(new[pos:])
    cand = "".join(out)
    if cand != ln:
        lines[i] = cand
        changed += 1

p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("changed lines:", changed)
