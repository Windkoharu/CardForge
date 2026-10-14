# -*- coding: utf-8 -*-
"""按行号替换 effects.py 里的三个探测正则（避免手工转写出错）。"""
import pathlib

p = pathlib.Path(r"D:\游戏王DIY设计\cardforge\content\effects.py")
lines = p.read_text(encoding="utf-8").splitlines()

# 定位三处（按唯一片段匹配，比硬记行号稳）
def find(sub, start=0):
    for i in range(start, len(lines)):
        if sub in lines[i]:
            return i
    raise SystemExit(f"not found: {sub}")

i_ref = find("_REFERENCE_RE = re.compile(")
i_cont = find("_CONTINUOUS_RE = re.compile(")
i_until = find("UNTIL_RE = re.compile(")
print("lines:", i_ref, i_cont, i_until)

new_ref = [
    "#: 处理段指代词（官方写法用代词而不是重抄对象短语，见 rules.REFERENCE_PHRASES）。",
    "#: 「那个／那只／那张」→ ``it``；「那个对象」→ ``that_target``；",
    "#: 「那些」是复数，官方模板没有对应简中代词 → 记进 EffectSpec.note 提示人工复核。",
    '_REFERENCE_RE = re.compile(r"那个对象|その対象|that target|那些|それら|那个|那只|那张|それ")',
]
new_cont = [
    "#: 「不入连锁」的措辞（永续效果 / 装备效果 / 规则文本）——",
    "#: 官方卡文里这类句子**没有「才能发动」**，Lua 侧也不能登记成 IGNITION/TRIGGER。",
    "#: 注意：时限措辞「直到…为止／直到…时」**不属于**永续（它是入连锁效果的持续时长），",
    "#: 所以这里不收「until／直到」，否则「攻击力直到回合结束时上升1000」会被误判成永续。",
    "_CONTINUOUS_RE = re.compile(",
    '    r"只要|限り|存在する(?:場合|限り)|while this card|is unaffected"',
    '    r"|cannot be|不能|不受|不会被|当作|作为[^。；;]{1,12}存在", re.I)',
]
new_until = [
    "#: 「直到…为止／直到…时」的时限措辞（脚本侧要写 SetReset(RESET_PHASE+PHASE_END)）",
    "UNTIL_RE = re.compile(",
    '    r"直到[^。；;]{0,16}?(?:为止|时)|回合结束为止|until the end of the turn|まで", re.I)',
]

# 从后往前替换，行号才不会失效
lines[i_until:i_until + 2] = new_until
lines[i_cont:i_cont + 3] = new_cont
# i_ref 之后紧跟一行注释 + 定义（原块共 2 行：注释 + 定义）
lines[i_ref - 1:i_ref + 1] = new_ref

p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("patched")
