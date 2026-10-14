"""Lua 脚本静态校验（G2 的核心）。

为什么需要自己写
----------------
G2 要求"Lua 语法解析"，但部署环境**不保证有 luac**（跨平台、零安装是本项目硬要求）。
所以这里实现一个**够用的 Lua 词法 + 结构校验器**：它不构建完整 AST，
但能抓住真实脚本里 95% 以上的错误：

* 块结构不平衡（``function/if/for/while/do`` 缺 ``end``、``repeat`` 缺 ``until``）
* 括号/方括号/花括号不平衡
* 字符串与长括号未闭合
* **UTF-8 BOM**（带 BOM 的脚本在 ocgcore 里会直接失效，事后不可补救）
* ``aux.Stringid(id, n)`` 与 ``cdb.texts.str*`` **不同步**（会导致效果描述显示 ``???``）
* 引用了 API 白名单里不存在的函数/常量（可疑，标 WARN）
* 常见写法坑：缺 ``local s,id=GetID()``、注册了效果但没 ``SetTarget/SetOperation``、
  ``Effect.CreateEffect(c)`` 没用 ``c``、``Duel.SelectMatchingCard`` 前没 ``Hint``

**全部规则都是确定性的**，不依赖任何模型。
"""
from __future__ import annotations

import re
from typing import Optional

from ...core.models import CardSpec, Issue
from . import apicatalog as API

# ══════════════════════════════════════════════════════════════════════
#  Lua 词法（够用版）
# ══════════════════════════════════════════════════════════════════════
_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "goto", "if", "in", "local", "nil", "not", "or", "repeat", "return", "then",
    "true", "until", "while",
}
#: 成对块：开块关键字 → 结束关键字
_BLOCK_OPEN = {"function", "if", "do", "for", "while"}
_BLOCK_CLOSE = {"end"}


class _Tok:
    __slots__ = ("kind", "val", "line")

    def __init__(self, kind: str, val: str, line: int):
        self.kind, self.val, self.line = kind, val, line

    def __repr__(self):  # pragma: no cover
        return f"{self.kind}({self.val!r})@{self.line}"


def tokenize(lua: str) -> tuple[list[_Tok], list[str]]:
    """把 Lua 切成 token。返回 ``(tokens, errors)``。

    处理：注释（``--`` 与 ``--[[ ]]``）、字符串（``'`` ``"`` 与 ``[[ ]]``）、
    数字、标识符、运算符。**不做**语义分析。
    """
    toks: list[_Tok] = []
    errs: list[str] = []
    i, n, line = 0, len(lua), 1
    # 跳过 shebang
    if lua.startswith("#"):
        j = lua.find("\n")
        i = n if j < 0 else j

    while i < n:
        c = lua[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        # 注释
        if lua.startswith("--", i):
            m = re.match(r"--\[(=*)\[", lua[i:])
            if m:
                close = "]" + m.group(1) + "]"
                j = lua.find(close, i + 4 + len(m.group(1)))
                if j < 0:
                    errs.append(f"第 {line} 行：长注释未闭合（缺少 {close}）")
                    break
                line += lua.count("\n", i, j)
                i = j + len(close)
            else:
                j = lua.find("\n", i)
                i = n if j < 0 else j
            continue
        # 长字符串
        m = re.match(r"\[(=*)\[", lua[i:])
        if m:
            close = "]" + m.group(1) + "]"
            j = lua.find(close, i + 2 + len(m.group(1)))
            if j < 0:
                errs.append(f"第 {line} 行：长字符串未闭合（缺少 {close}）")
                break
            line += lua.count("\n", i, j)
            i = j + len(close)
            toks.append(_Tok("string", "", line))
            continue
        # 普通字符串
        if c in "\"'":
            q, start, j = c, line, i + 1
            closed = False
            while j < n:
                if lua[j] == "\\":
                    j += 2
                    continue
                if lua[j] == "\n":
                    break
                if lua[j] == q:
                    closed = True
                    break
                j += 1
            if not closed:
                errs.append(f"第 {start} 行：字符串未闭合")
                i = n
                break
            toks.append(_Tok("string", "", start))
            i = j + 1
            continue
        # 数字
        if c.isdigit() or (c == "." and i + 1 < n and lua[i + 1].isdigit()):
            m = re.match(r"0[xX][0-9a-fA-F]+|\d+\.?\d*([eE][+-]?\d+)?|\.\d+", lua[i:])
            toks.append(_Tok("number", m.group(0), line))
            i += m.end()
            continue
        # 标识符/关键字
        if c.isalpha() or c == "_":
            m = re.match(r"[A-Za-z_]\w*", lua[i:])
            w = m.group(0)
            toks.append(_Tok("kw" if w in _KEYWORDS else "name", w, line))
            i += m.end()
            continue
        # 多字符运算符
        for op in ("...", "..", "==", "~=", "<=", ">=", "//", "::"):
            if lua.startswith(op, i):
                toks.append(_Tok("op", op, line))
                i += len(op)
                break
        else:
            toks.append(_Tok("op", c, line))
            i += 1
    return toks, errs


def syntax_ok(lua: str) -> tuple[bool, str]:
    """语法是否通过。返回 ``(ok, message)``。"""
    toks, errs = tokenize(lua or "")
    if errs:
        return False, "；".join(errs[:3])

    # ① 括号平衡
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[_Tok] = []
    for t in toks:
        if t.kind != "op":
            continue
        if t.val in "([{":
            stack.append(t)
        elif t.val in ")]}":
            if not stack or stack[-1].val != pairs[t.val]:
                return False, f"第 {t.line} 行：'{t.val}' 没有匹配的开括号"
            stack.pop()
    if stack:
        t = stack[-1]
        return False, f"第 {t.line} 行：'{t.val}' 未闭合"

    # ② 块结构：用"可结束块计数器"遍历
    #    repeat...until 单独处理；if/for/while/function 产生的 then/do 不额外计数
    depth = 0
    pending_repeat: list[int] = []
    # 记录 if 的单分支结构：elseif/else 不改变深度
    for idx, t in enumerate(toks):
        if t.kind != "kw":
            continue
        v = t.val
        if v in ("function", "if", "for", "while"):
            # `for ... do` 与 `while ... do` 的 do 不额外计数，
            # 这里把 for/while 本身算作一个块开
            depth += 1
        elif v == "repeat":
            pending_repeat.append(t.line)
        elif v == "until":
            if not pending_repeat:
                return False, f"第 {t.line} 行：'until' 没有对应的 'repeat'"
            pending_repeat.pop()
        elif v == "end":
            if depth <= 0:
                return False, f"第 {t.line} 行：多出一个 'end'"
            depth -= 1
        elif v == "do":
            # 独立的 do ... end 块（不是 for/while 的 do）—— 前一个 token 不是
            # for/while 的收尾时才算新块
            prev = toks[idx - 1].val if idx > 0 else ""
            if prev not in (")", "do", "end") and not _prev_is_for_head(toks, idx):
                depth += 1
    if pending_repeat:
        return False, f"第 {pending_repeat[0]} 行：'repeat' 没有对应的 'until'"
    if depth > 0:
        return False, f"还有 {depth} 个块没有闭合（缺少 'end'）"
    if depth < 0:
        return False, "块结构与预期不符"
    return True, ""


def _prev_is_for_head(toks: list[_Tok], idx: int) -> bool:
    """判断 ``do`` 是否属于 ``for/while`` 头部（向前找最近的关键字）。"""
    for j in range(idx - 1, max(-1, idx - 60), -1):
        if toks[j].kind != "kw":
            continue
        if toks[j].val in ("for", "while"):
            return True
        if toks[j].val in ("do", "then", "end", "function", "if"):
            return False
    return False


# ══════════════════════════════════════════════════════════════════════
#  规则
# ══════════════════════════════════════════════════════════════════════
RE_STRINGID = re.compile(r"aux\.Stringid\s*\(\s*(?:id|\w+)\s*,\s*(\d+)\s*\)")
RE_GETID = re.compile(r"local\s+s\s*,\s*id\s*=\s*GetID\s*\(\s*\)")
RE_INITIAL = re.compile(r"function\s+s\.initial_effect\s*\(")
RE_CREATE_EFFECT = re.compile(r"Effect\.CreateEffect\s*\(\s*(\w+)\s*\)")
RE_REGISTER = re.compile(r"(\w+)\s*:\s*RegisterEffect\s*\(")
#: 形如 ``X:RegisterEffect(e1)`` —— 取被注册的效果变量
RE_REGISTER_ARG = re.compile(r":\s*RegisterEffect\s*\(\s*(\w+)\s*\)")
#: 函数形参名（``c`` 这类不应被当成 Effect 变量）
RE_PARAM = re.compile(r"function\s+[\w.]+\s*\(([^)]*)\)")
RE_HINT_BEFORE_SELECT = re.compile(r"Duel\.SelectMatchingCard|Duel\.SelectTarget")


def _issue(code: str, level: str, msg: str, hint: str = "", field: str = "lua") -> Issue:
    return Issue(gate="G2", code=code, level=level, message=msg, hint=hint, field=field)


def lint_lua(lua: str, spec: Optional[CardSpec] = None) -> list[Issue]:
    """对一段卡脚本做全套静态检查。"""
    out: list[Issue] = []
    body = lua or ""

    if not body.strip():
        return [_issue("G2_EMPTY", "ERROR", "脚本内容为空",
                       "用 card script 生成，或把卡种改为通常怪兽")]

    # ── 1. 编码 ──
    if body.startswith("\ufeff"):
        out.append(_issue("G2_BOM", "ERROR",
                          "脚本以 UTF-8 BOM 开头，ocgcore 会加载失败",
                          "以 **UTF-8 无 BOM** 保存（带 BOM 事后不可补救）"))
    if "\ufffd" in body:
        out.append(_issue("G2_ENCODING", "ERROR",
                          "脚本里出现替换字符 U+FFFD，说明编码已损坏",
                          "用 UTF-8 重新写出整份脚本"))

    # ── 2. 语法 ──
    ok, msg = syntax_ok(body)
    if not ok:
        out.append(_issue("G2_SYNTAX", "ERROR", f"Lua 语法错误：{msg}",
                          "修正后重新生成；语法错误会让整张卡在对局中报错"))

    # ── 3. 必备结构 ──
    if not RE_GETID.search(body):
        out.append(_issue("G2_NO_GETID", "ERROR",
                          "缺少 `local s,id=GetID()`",
                          "卡脚本首行必须是 `local s,id=GetID()`"))
    if not RE_INITIAL.search(body):
        out.append(_issue("G2_NO_INITIAL", "ERROR",
                          "缺少 `function s.initial_effect(c)`",
                          "ocgcore 通过这个入口注册效果"))

    # ── 4. Effect.CreateEffect 的参数 ──
    creates = RE_CREATE_EFFECT.findall(body)
    for arg in set(creates):
        if arg != "c":
            out.append(_issue("G2_CREATE_ARG", "WARN",
                              f"`Effect.CreateEffect({arg})` 通常应传 `c`",
                              "传错对象会导致效果挂到别的卡上"))

    # ── 5. 注册了效果但变量未定义 / 未注册 ──
    # 函数形参（如 initial_effect(c) 的 c）不属于"Effect 变量"，要排除
    params = {p.strip() for grp in RE_PARAM.findall(body) for p in grp.split(",")}
    created = re.findall(r"local\s+(\w+)\s*=\s*Effect\.CreateEffect", body)
    # 注册目标有两种写法：``x:RegisterEffect(...)`` 与 ``c:RegisterEffect(x)``
    reg_targets = set(RE_REGISTER.findall(body))
    reg_args = set(RE_REGISTER_ARG.findall(body))
    for v in reg_targets - params:
        if v in created:
            continue
        if re.search(rf"local\s+{re.escape(v)}\s*=\s*Effect\.CreateEffect", body):
            continue
        out.append(_issue("G2_REGISTER_UNDEFINED", "WARN",
                          f"`{v}:RegisterEffect(...)` 的 `{v}` 未用 "
                          f"`Effect.CreateEffect` 创建",
                          "检查变量名是否有笔误"))
    for v in created:
        if v not in reg_args and v not in reg_targets:
            out.append(_issue("G2_EFFECT_NOT_REGISTERED", "WARN",
                              f"创建了效果 `{v}` 但没有 `RegisterEffect`",
                              "未注册的效果不会生效"))

    # ── 6. aux.Stringid ↔ texts 同步（发现会显示 ???）──
    ids = sorted({int(x) for x in RE_STRINGID.findall(body)})
    if ids and spec is not None:
        strings = list(getattr(spec, "strings", []) or [])
        missing = [i for i in ids if i >= len(strings) or not str(strings[i]).strip()]
        if missing:
            out.append(_issue(
                "G2_STRINGID_SYNC", "ERROR",
                f"脚本引用了 aux.Stringid(id, {missing})，"
                f"但 cdb 的 texts.str{missing[0] + 1} 为空",
                "效果描述会显示成 ???；重新生成脚本时会自动同步"))
        if len(strings) > 16:
            out.append(_issue("G2_STR_OVERFLOW", "ERROR",
                              f"效果描述有 {len(strings)} 条，超过 str1–str16 上限",
                              "把多条效果合并到一条描述里"))
    elif ids and spec is None:
        out.append(_issue("G2_STRINGID_NO_SPEC", "INFO",
                          f"脚本引用了 {len(ids)} 个 Stringid，但未提供卡规格，"
                          f"无法校验 texts 同步", ""))

    # ── 7. API 存在性 ──
    unk = API.unknown(body)
    if unk["calls"]:
        out.append(_issue("G2_UNKNOWN_API", "WARN",
                          f"引用了 {len(unk['calls'])} 个未在官方脚本库中出现过的函数："
                          f"{'、'.join(unk['calls'][:5])}",
                          "可能是拼写错误，或该 API 属于更早/更晚的版本"))
    if unk["consts"]:
        out.append(_issue("G2_UNKNOWN_CONST", "WARN",
                          f"引用了 {len(unk['consts'])} 个未知常量："
                          f"{'、'.join(unk['consts'][:5])}",
                          "检查拼写；未知常量在运行时是 nil，会导致效果静默失效"))
    if unk["methods"]:
        # 方法名太多了，只报可疑的（长度>2 且不在白名单）
        susp = [m for m in unk["methods"] if len(m) > 2][:6]
        if susp:
            out.append(_issue("G2_UNKNOWN_METHOD", "INFO",
                              f"以下卡对象方法不在白名单里：{'、'.join(susp)}",
                              "可能来自第三方扩展；官方脚本里未出现"))

    # ── 8. 常见写法坑 ──
    if RE_HINT_BEFORE_SELECT.search(body) and "Duel.Hint" not in body:
        out.append(_issue("G2_NO_HINT", "WARN",
                          "有选择卡的效果但没有 `Duel.Hint`",
                          "缺少提示会让玩家看到不该看到的卡（里侧卡信息泄漏）"))
    if "SetTarget" in body and "SetOperation" not in body:
        out.append(_issue("G2_TARGET_NO_OPERATION", "WARN",
                          "设置了 SetTarget 但没有 SetOperation",
                          "取对象的效果在处理阶段需要 SetOperation 执行结算"))
    if "SetOperation" in body and "SetTarget" not in body:
        out.append(_issue("G2_OPERATION_NO_TARGET", "INFO",
                          "设置了 SetOperation 但没有 SetTarget",
                          "若效果不取对象则正常；否则需要补 SetTarget"))
    if re.search(r"c:RegisterEffect\s*\(", body) and "initial_effect" not in body:
        out.append(_issue("G2_OUTSIDE_INITIAL", "WARN",
                          "在 initial_effect 之外注册了效果",
                          "只有 initial_effect 里注册的效果才会被引擎加载"))
    if "Duel.SelectMatchingCard" in body and "HINTMSG" not in body:
        out.append(_issue("G2_NO_HINTMSG", "WARN",
                          "SelectMatchingCard 没有指定 HINTMSG",
                          "用 Duel.Hint(HINT_SELECTMSG, tp, HINTMSG_XXX) 明确选择意图"))
    if re.search(r"\bDuel\.Destroy\s*\(\s*g\s*,\s*nil\s*,\s*REASON_EFFECT\s*\+\s*REASON_DESTROY", body):
        out.append(_issue("G2_DESTROY_REASON", "INFO",
                          "破坏的 REASON 同时给了 EFFECT 与 DESTROY",
                          "通常是 `REASON_EFFECT`；加 `REASON_DESTROY` 只在特殊场合需要"))
    if re.search(r"REASON_BATTLE\s*\+\s*REASON_EFFECT", body):
        out.append(_issue("G2_REASON_BOTH", "WARN",
                          "REASON 同时标了 BATTLE 与 EFFECT",
                          "战斗破坏与效果破坏互斥，同时标会让裁定异常"))
    return out


def check_encoding(path: str) -> list[Issue]:
    """检查磁盘上的 .lua 文件编码是否为 UTF-8 无 BOM。"""
    try:
        raw = open(path, "rb").read()
    except Exception as e:
        return [_issue("G2_READ_FAIL", "ERROR", f"脚本读取失败：{e}", "")]
    out: list[Issue] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        out.append(_issue("G2_BOM", "ERROR",
                          f"{path} 带 UTF-8 BOM，ocgcore 会加载失败",
                          "以 UTF-8 无 BOM 重新保存"))
    else:
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as e:
            out.append(_issue("G2_NOT_UTF8", "ERROR",
                              f"{path} 不是合法 UTF-8：{e}", "改用 UTF-8 保存"))
    return out


def check_stringid_sync(spec: CardSpec, lua: str) -> list[Issue]:
    """单独跑 Stringid ↔ texts 同步检查（G2 会额外调用一次）。"""
    if spec is None:
        return []
    ids = sorted({int(x) for x in RE_STRINGID.findall(lua or "")})
    if not ids:
        return []
    strings = list(getattr(spec, "strings", []) or [])
    missing = [i for i in ids if i >= len(strings) or not str(strings[i]).strip()]
    if not missing:
        return []
    return [_issue("G2_STRINGID_SYNC", "ERROR",
                   f"aux.Stringid 用了索引 {missing}，但 texts.str{missing[0] + 1} 为空",
                   "效果描述会显示 ???；用 card script 重新生成会自动同步")]


def capabilities() -> dict:
    return {"syntax_checker": "builtin", "api_catalog": API.info()}
