# -*- coding: utf-8 -*-
"""一次性修复脚本：修 effects.py 里被转义搞坏的字面量，并把正则改成 raw string。"""
import pathlib
import re

p = pathlib.Path(r"D:\游戏王DIY设计\cardforge\content\effects.py")
lines = p.read_text(encoding="utf-8").splitlines()
BS = chr(92)  # 反斜杠，避免在源码里写转义

# ① 修复被拆坏的那行（原意：按换行切段）
for i, ln in enumerate(lines):
    if ln.strip() == 'parts = [x.strip() for x in re.split(r"':
        lines[i] = '    parts = [x.strip() for x in re.split(r"' + BS + 'n+", src) if x.strip()]'
        if i + 1 < len(lines) and lines[i + 1].strip().startswith('",'):
            del lines[i + 1]
        break

# ② 元组里第一个字符串字面量（正则）若含反斜杠且还不是 raw → 加 r 前缀
fixed = 0
for i, ln in enumerate(lines):
    st = ln.lstrip()
    if st.startswith('("') and BS in ln and 'r"' not in ln:
        j = ln.index('"')
        lines[i] = ln[:j] + 'r"' + ln[j + 1:]
        fixed += 1
print("tuple lines rawified:", fixed)

# ③ 仍可疑的行（有转义但字符串不是 raw）
pat = re.compile('(?<!r)"[^"]*' + re.escape(BS) + '[dnwDNWSsS]')
bad = [i + 1 for i, ln in enumerate(lines) if pat.search(ln)]
print("still suspicious:", bad[:40])

p.write_text("\n".join(lines) + "\n", encoding="utf-8")
