"""从 data/lexicons/*.json 生成 lexicon.py 的内置兜底表（开发期一次性脚本）。

用法::

    python _probe/psct/_gen_fallback.py

输出 ``_probe/psct/_fallback_fragment.py.txt``：两段可直接粘进
``cardforge/content/psct/lexicon.py`` 的 Python 字面量。

**这是数据搬运脚本，不是运行时依赖**：生成的表会内联进 lexicon.py，
使引擎在 data/lexicons/ 缺失时仍可工作（zh_cn/ja/en 核心术语全覆盖）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEX = ROOT / "data" / "lexicons"

# 兜底覆盖范围：引擎真正会用到的键
WANT_CATEGORIES = ("attribute", "race", "zone", "stat", "psct_phrase")
WANT_ACTIONS = (
    "act_search", "act_add_to_hand", "act_special_summon", "act_normal_summon",
    "act_tribute_summon", "act_flip_summon", "act_set", "act_fusion_summon",
    "act_synchro_summon", "act_xyz_summon", "act_pendulum_summon",
    "act_link_summon", "act_ritual_summon", "act_destroy", "act_banish",
    "act_send", "act_return", "act_tribute", "act_discard", "act_draw",
    "act_place_counter", "act_change_battle_position", "act_attack",
    "act_direct_attack", "act_destroyed_by_battle", "act_piercing",
    "act_negate", "act_negate_activation", "act_negate_effect", "act_target",
    "act_take_control", "act_copy", "act_replace", "act_flip_face_down",
    "act_flip_face_up", "act_shuffle", "act_reveal", "act_confirm",
    "act_declare", "act_gain", "act_lose", "act_detach", "act_attach",
    "act_pay_lp", "act_control",
)
WANT_CARD_TYPES = (
    "card_monster", "card_normal_monster", "card_effect_monster",
    "card_ritual_monster", "card_fusion_monster", "card_synchro_monster",
    "card_xyz_monster", "card_pendulum_monster", "card_link_monster",
    "card_token", "card_spell", "card_trap", "card_normal_spell",
    "card_continuous_spell", "card_equip_spell", "card_field_spell",
    "card_quick_play_spell", "card_ritual_spell", "card_normal_trap",
    "card_continuous_trap", "card_counter_trap", "card_tuner", "card_union",
    "card_gemini", "card_flip", "card_spirit", "card_toon",
    "card_special_summon_monster", "card_effect",
)

LANGS = ("zh_cn", "ja", "en")


def pyval(v: object) -> str:
    """JSON 值 → **Python 字面量**（None/True/False 不能写成 null/true/false）。"""
    if v is None:
        return "None"
    if v is True:
        return "True"
    if v is False:
        return "False"
    return json.dumps(v, ensure_ascii=False)


def pylit(obj: object, indent: int = 0) -> str:
    """递归把 JSON 结构转成 Python 字面量源码（不依赖 json 的关键字差异）。"""
    pad = " " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = [f'{pad}    {json.dumps(str(k), ensure_ascii=False)}: '
                 f'{pylit(v, indent + 4)}' for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(obj, (list, tuple)):
        if not obj:
            return "[]"
        if all(isinstance(x, (str, int, float, bool)) or x is None for x in obj):
            return "[" + ", ".join(pyval(x) for x in obj) + "]"
        items = [f"{pad}    {pylit(v, indent + 4)}" for v in obj]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return pyval(obj)


def main() -> int:
    terms = json.loads((LEX / "terms.json").read_text(encoding="utf-8"))["terms"]
    pats = json.loads((LEX / "psct_patterns.json").read_text(encoding="utf-8"))

    picked: dict[str, dict] = {}
    for k, v in terms.items():
        cat = v.get("category")
        if cat in WANT_CATEGORIES or k in WANT_ACTIONS or k in WANT_CARD_TYPES:
            picked[k] = v

    lines = ["# @@FALLBACK_TERMS@@ 由 _probe/psct/_gen_fallback.py 生成（数据源 data/lexicons/terms.json）",
             "_FALLBACK_TERMS: dict[str, dict[str, str]] = {"]
    for k in sorted(picked):
        v = picked[k]
        cells = ", ".join(f'"{lg}": {pyval(v.get(lg))}' for lg in LANGS)
        lines.append(f'    "{k}": {{{cells}, "category": "{v.get("category")}"}},')
    lines.append("}")
    lines.append("")

    # ── 模式兜底：只保留可编程字段，丢掉长 note 与 source ──
    def trim(d: dict, keys: tuple[str, ...]) -> dict:
        out = {}
        for kk in keys:
            if kk in d and d[kk] not in (None, [], {}):
                out[kk] = d[kk]
        return out

    punct = []
    for p in pats["punctuation"]:
        punct.append(trim(p, ("symbol", "role", "en", "ja", "zh_cn", "zh_tw",
                              "position")))
    conj = []
    for c in pats["conjunctions"]:
        conj.append(trim(c, ("key", "en", "ja", "zh_cn", "zh_tw",
                             "resolution_order", "both_required",
                             "requires_a_for_b", "aborts_b_if_a_fails")))
    hopt = []
    for h in pats["hopt"]:
        hopt.append(trim(h, ("key", "en", "ja", "zh_cn", "zh_tw", "scope",
                             "strictness", "reset_on_leave", "placement",
                             "variants")))
    numbering = trim(pats["numbering"], ("symbols", "ascii_aliases", "rule", "rules"))
    structure = trim(pats["structure"], ("template", "segments", "chain_rule",
                                         "spell_trap_exception"))
    timing = {}
    for k, v in pats["timing_keywords"].items():
        timing[k] = trim(v, ("en", "ja", "zh_cn", "zh_tw", "strictness",
                             "optionality"))
    quad = pats["conjunction_quadrants"]

    lines.append("# @@FALLBACK_PATTERNS@@ 由 _probe/psct/_gen_fallback.py 生成"
                 "（数据源 data/lexicons/psct_patterns.json，已裁掉 note/source）")
    lines.append("_FALLBACK_PATTERNS: dict = {")
    for key, val in (("punctuation", punct), ("conjunctions", conj),
                     ("hopt", hopt), ("numbering", numbering),
                     ("structure", structure), ("timing_keywords", timing),
                     ("conjunction_quadrants", trim(quad, ("axes", "grid")))):
        body = pylit(val, 4)
        lines.append(f'    "{key}": {body},')
    lines.append("}")
    lines.append("")

    out = Path(__file__).resolve().parent / "_fallback_fragment.py.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"terms={len(picked)} punct={len(punct)} conj={len(conj)} hopt={len(hopt)}")
    print(f"written: {out}  ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
