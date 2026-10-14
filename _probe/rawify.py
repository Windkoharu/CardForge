# -*- coding: utf-8 -*-
"""把 effects.py 里「正则条目行」的第一个字符串字面量规范成 raw string。

做法：用 ``ast`` 取到该字面量的**运行时值**（已经把 ``\\\\d`` 之类解好转义），
再用 ``r"..."`` 原样写出 —— 这样无论源码里写的是一层还是两层反斜杠，
运行时正则都保持 ``\\d`` 的语义。
"""
import ast
import pathlib
import re

p = pathlib.Path(r"D:\游戏王DIY设计\cardforge\content\effects.py")
lines = p.read_text(encoding="utf-8").splitlines()

LIT = re.compile(r'"((?:[^"\\]|\\.)*)"')
ENTRY = re.compile(r'^\s*\(r?"')

changed = 0
for i, ln in enumerate(lines):
    if not ENTRY.match(ln) or "\\" not in ln:
        continue
    m = LIT.search(ln)
    if not m:
        continue
    if m.start() > 0 and ln[m.start() - 1] == "r":
        continue                                   # 已经是 raw string，别重复加前缀
    value = ast.literal_eval(m.group(0))          # 运行时正则文本
    if "r\"" in ln[:m.start() + 1] or m.group(0).startswith('r"'):
        pass
    if '"' in value or value.endswith("\\"):
        continue                                   # 不适合 raw 化，跳过（人工处理）
    if value == m.group(0)[1:-1]:
        # 运行时值与源码字面量一致 → 只需加 r 前缀
        new = ln[:m.start()] + 'r"' + value + '"' + ln[m.end():]
    else:
        new = ln[:m.start()] + 'r"' + value + '"' + ln[m.end():]
    if new != ln:
        lines[i] = new
        changed += 1

p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("rawified entry lines:", changed)
