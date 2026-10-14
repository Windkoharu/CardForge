"""修正 lint 的三处误报 + 扩大方法采集范围。

误报原因：
  1. ``c:RegisterEffect(e1)`` 里的 ``c`` 是 initial_effect 的形参，不是 Effect 对象，
     原检查把它当成"未创建的 Effect 变量"。
  2. ``RegisterEffect`` 的目标既可能是 ``变量:RegisterEffect(...)``，也可能是
     ``c:RegisterEffect(变量)``；原检查只看了前者，于是把已注册的 e1 报成未注册。
  3. 方法白名单采集时只匹配了固定的组变量名（c/g/eg...），漏掉了 ``e1:SetType(...)``
     这类 Effect 方法，导致 SetType/SetCode 等被报成未知方法。
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

# ── ① 扩大 extract_lua_api 的方法采集范围 ──────────────────────────
p1 = ROOT / "tools" / "extract_lua_api.py"
s1 = p1.read_text(encoding="utf-8")
old = '''RE_GROUP_CALL = re.compile(r"\\b(c|tc|sg|g|eg|mg|dg|tg|fg|og|sc|rc|ec|ac):"
                           r"([A-Za-z_]\\w*)")'''
new = '''# 采集任意 ``对象:方法(`` 形式。之前只列了固定的组变量名（c/g/eg/...），
# 漏掉了 ``e1:SetType(...)`` 这类 Effect 方法，导致 lint 把 SetType 报成未知方法。
RE_GROUP_CALL = re.compile(r"\\b([A-Za-z_]\\w*)\\s*:\\s*([A-Za-z_]\\w*)\\s*\\(")'''
if old in s1:
    s1 = s1.replace(old, new)
    p1.write_text(s1, encoding="utf-8", newline="")
    ast.parse(s1)
    print("[OK] extract_lua_api：方法采集范围已扩大")
else:
    print("[SKIP] extract_lua_api：未找到目标片段（可能已改）")

# ── ② 修 lint 的 RegisterEffect 检查 ────────────────────────────────
p2 = ROOT / "cardforge" / "content" / "lua" / "lint.py"
s2 = p2.read_text(encoding="utf-8")

s2 = s2.replace(
    'RE_REGISTER = re.compile(r"(\\w+)\\s*:\\s*RegisterEffect\\s*\\(")',
    'RE_REGISTER = re.compile(r"(\\w+)\\s*:\\s*RegisterEffect\\s*\\(")\n'
    '#: 形如 ``X:RegisterEffect(e1)`` —— 取被注册的效果变量\n'
    'RE_REGISTER_ARG = re.compile(r":\\s*RegisterEffect\\s*\\(\\s*(\\w+)\\s*\\)")\n'
    '#: 函数形参名（``c`` 这类不应被当成 Effect 变量）\n'
    'RE_PARAM = re.compile(r"function\\s+[\\w.]+\\s*\\(([^)]*)\\)")'
)

old_block = '''    regs = RE_REGISTER.findall(body)
    for v in set(regs):
        if not re.search(rf"local\\s+{re.escape(v)}\\s*=\\s*Effect\\.CreateEffect", body):
            out.append(_issue("G2_REGISTER_UNDEFINED", "WARN",
                              f"`{v}:RegisterEffect(...)` 的 `{v}` 未用 "
                              f"`Effect.CreateEffect` 创建",
                              "检查变量名是否有笔误"))
    created = re.findall(r"local\\s+(\\w+)\\s*=\\s*Effect\\.CreateEffect", body)
    for v in created:
        if v not in regs:
            out.append(_issue("G2_EFFECT_NOT_REGISTERED", "WARN",
                              f"创建了效果 `{v}` 但没有 `RegisterEffect`",
                              "未注册的效果不会生效"))'''

new_block = '''    # 函数形参（如 initial_effect(c) 的 c）不属于"Effect 变量"，要排除
    params = {p.strip() for grp in RE_PARAM.findall(body) for p in grp.split(",")}
    created = re.findall(r"local\\s+(\\w+)\\s*=\\s*Effect\\.CreateEffect", body)
    # 注册目标有两种写法：``x:RegisterEffect(...)`` 与 ``c:RegisterEffect(x)``
    reg_targets = set(RE_REGISTER.findall(body))
    reg_args = set(RE_REGISTER_ARG.findall(body))
    for v in reg_targets - params:
        if v in created:
            continue
        if re.search(rf"local\\s+{re.escape(v)}\\s*=\\s*Effect\\.CreateEffect", body):
            continue
        out.append(_issue("G2_REGISTER_UNDEFINED", "WARN",
                          f"`{v}:RegisterEffect(...)` 的 `{v}` 未用 "
                          f"`Effect.CreateEffect` 创建",
                          "检查变量名是否有笔误"))
    for v in created:
        if v not in reg_args and v not in reg_targets:
            out.append(_issue("G2_EFFECT_NOT_REGISTERED", "WARN",
                              f"创建了效果 `{v}` 但没有 `RegisterEffect`",
                              "未注册的效果不会生效"))'''

if old_block in s2:
    s2 = s2.replace(old_block, new_block)
    print("[OK] lint：RegisterEffect 检查已修正")
else:
    print("[SKIP] lint：未找到 RegisterEffect 检查片段")

p2.write_text(s2, encoding="utf-8", newline="")
ast.parse(s2)
print("[OK] lint 语法检查通过")
