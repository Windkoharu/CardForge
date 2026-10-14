"""让渲染器的类型行支持多语言（复用 PSCT 术语表）。

问题
----
``CardSpec`` 里的 ``race`` / ``attribute`` 存的是**中文**（``龙族`` / ``炎``）。
``layers.type_line_text`` 直接把它们拼进类型行，于是英文卡渲染出
``[Dragon / 炎 / Tuner]`` 这种中英混排 —— 而 psct/gen.py 生成的文本是正确的
``[Dragon / FIRE / Effect]``，两边口径不一致。

修法
----
在渲染器里加一层**惰性 + 可降级**的术语查询：
  · 从 ``content.psct.lexicon`` 取术语表（拿到就按语言翻译）
  · 拿不到（模块缺失/术语缺失）就原样返回中文，绝不报错
  · 反向索引按 ``zh_cn`` 字段建，并兼容「暗」vs「暗属性」两种写法
"""
import ast
import pathlib

P = (pathlib.Path(__file__).resolve().parents[1]
     / "cardforge" / "render" / "layers.py")
s = P.read_text(encoding="utf-8")
orig = s

HELPER = '''

# ══════════════════════════════════════════════════════════════════════
#  多语言术语查询（惰性 + 可降级）
# ══════════════════════════════════════════════════════════════════════
_LEX_REVERSE: dict | None = None
_LEX_FAILED = False


def _lex_reverse() -> dict:
    """建「中文名 → {lang: 译名}」的反向索引。术语表不可用时返回空 dict。"""
    global _LEX_REVERSE, _LEX_FAILED
    if _LEX_REVERSE is not None or _LEX_FAILED:
        return _LEX_REVERSE or {}
    try:
        from ..content.psct import lexicon as LX          # 惰性：渲染器不硬依赖 content
        table = LX.terms()
    except Exception:
        _LEX_FAILED = True
        _LEX_REVERSE = {}
        return {}
    rev: dict[str, dict] = {}
    for key, item in (table or {}).items():
        if not isinstance(item, dict):
            continue
        zh = item.get("zh_cn")
        if not zh:
            continue
        rev.setdefault(str(zh), item)
        # 属性在术语表里带「属性」后缀（暗属性），而 CardSpec 存的是「暗」
        if str(zh).endswith("属性"):
            rev.setdefault(str(zh)[:-2], item)
    _LEX_REVERSE = rev
    return rev


def lex(zh_value: str, lang: str, fallback: str | None = None) -> str:
    """把中文术语翻成目标语言。查不到就返回原值（**永远不抛异常**）。"""
    if not zh_value or lang in ("zh_cn", "zh_tw"):
        return zh_value or (fallback or "")
    item = _lex_reverse().get(str(zh_value))
    if not item:
        return fallback if fallback is not None else zh_value
    got = item.get(lang)
    if got:
        return str(got)
    # 该语言缺这条 → 回落 en → 原值
    return str(item.get("en") or zh_value)


#: 怪兽标签（MONSTER_TAGS 的键）→ 术语表 key
_TAG_LEX_KEY = {
    "tuner": "card_tuner", "spirit": "card_spirit", "union": "card_union",
    "gemini": "card_gemini", "flip": "card_flip", "toon": "card_toon",
    "special_summon": "card_special_summon",
}

'''

# 在 type_line_text 之前插入辅助函数
anchor = "def type_line_text(spec: CardSpec, lang: str = \"zh_cn\") -> str:"
if anchor not in s:
    print("[X] 未找到 type_line_text")
    raise SystemExit(1)
s = s.replace(anchor, HELPER.lstrip("\n") + anchor, 1)

# 让 type_line_text 走术语表
old = '''    race = spec.race
    if lang == "ja":
        race = spec.race.replace("族", "族")
    parts = [race, spec.attribute]
    if spec.frame == "normal":
        parts.append("通常" if lang != "en" else "Normal")
    for t in spec.tags or []:
        meta = MONSTER_TAGS.get(t)
        if meta:
            parts.append(meta.get(lang, meta["zh_cn"]))
    if spec.frame == "link":
        parts.append("连接" if lang != "en" else "Link")
    elif "pendulum" in spec.frame:
        parts.append("灵摆" if lang != "en" else "Pendulum")'''
new = '''    # 术语一律走术语表（查不到自动回落原值），保证英文卡不会出现中英混排
    race = lex(spec.race, lang)
    parts = [race, lex(spec.attribute, lang)]
    if spec.frame == "normal":
        parts.append("Normal" if lang == "en" else "通常")
    for t in spec.tags or []:
        meta = MONSTER_TAGS.get(t)
        if meta:
            parts.append(meta.get(lang) or meta["zh_cn"])
    if spec.frame == "link":
        parts.append("Link" if lang == "en" else "连接")
    elif "pendulum" in spec.frame:
        parts.append("Pendulum" if lang == "en" else "灵摆")'''
if old in s:
    s = s.replace(old, new, 1)
    print("[OK] type_line_text 走术语表")
else:
    print("[SKIP] type_line_text 主体片段未匹配")

if s == orig:
    print("[X] 无改动")
    raise SystemExit(1)
ast.parse(s)
P.write_text(s, encoding="utf-8", newline="")
print("[OK] layers.py 已更新，语法通过")
