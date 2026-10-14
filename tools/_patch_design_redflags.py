"""一次性补丁：给 design.py 的红旗规则加 only_if_unlimited 条件。

背景：RF03 / RF08 / RF09 描述的是"该加 HOPT 却没加"，但原实现只看效果种类，
对已经带了「1回合1次」的合规卡也会误报 ERROR。用脚本改而不是手改，
是为了让这次修改可复现、可审计。
"""
import ast
import pathlib
import sys

P = pathlib.Path(__file__).resolve().parents[1] / "cardforge" / "content" / "design.py"
s = P.read_text(encoding="utf-8")
orig = s
applied: list[str] = []


def sub(a: str, b: str, tag: str) -> None:
    global s
    if a not in s:
        print(f"  [SKIP] {tag} —— 未找到目标片段")
        return
    s = s.replace(a, b, 1)
    applied.append(tag)
    print(f"  [ OK ] {tag}")


# ① RedFlag 增加字段
sub(
    '    kinds: tuple = ()   # 命中的效果种类\n    note: str = ""',
    '    kinds: tuple = ()   # 命中的效果种类\n'
    '    only_if_unlimited: bool = False   # 仅当命中效果**没有任何回合限制**时才触发\n'
    '    note: str = ""',
    "RedFlag.only_if_unlimited 字段",
)

# ② 三条规则标记为"仅在无回合限制时触发"
sub(
    '            kinds=("recover", "ssummon_grave")),',
    '            kinds=("recover", "ssummon_grave"), only_if_unlimited=True),',
    "RF03 加 only_if_unlimited",
)
sub(
    '            kinds=("search", "ssummon")),',
    '            kinds=("search", "ssummon"), only_if_unlimited=True),',
    "RF08 加 only_if_unlimited",
)
sub(
    '            "限定检索范围（字段、种族、属性）并加 HOPT"),',
    '            "限定检索范围（字段、种族、属性）并加 HOPT",\n'
    '            kinds=("search",), only_if_unlimited=True),',
    "RF09 加 kinds + only_if_unlimited",
)

# ③ 触发逻辑
sub(
    '        elif rf.kinds and any(e.kind in rf.kinds for e in effects):\n'
    '            if not any(i.code == f"G1_{rf.code}" for i in out):\n'
    '                add(f"G1_{rf.code}", rf.level, rf.zh, rf.hint, "effects")',
    '        elif rf.kinds and any(e.kind in rf.kinds for e in effects):\n'
    '            hits = [e for e in effects if e.kind in rf.kinds]\n'
    '            if rf.only_if_unlimited and all(\n'
    '                    (e.limit or "none") != "none" for e in hits):\n'
    '                continue        # 已经带了回合限制 —— 不构成红旗\n'
    '            if not any(i.code == f"G1_{rf.code}" for i in out):\n'
    '                add(f"G1_{rf.code}", rf.level, rf.zh, rf.hint, "effects")',
    "红旗触发逻辑",
)

if s == orig:
    print("没有任何改动")
    sys.exit(1)

ast.parse(s)                      # 语法自检，不通过就不写盘
P.write_text(s, encoding="utf-8", newline="")
print(f"\n已写入 {P}，应用 {len(applied)} 处改动，语法检查通过")
