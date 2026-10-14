"""PSCT 卡文生成与校验引擎 —— 自测（1–7 项）。

跑法::

    python _probe/psct/p_psct_selfcheck.py

输出写到 ``_probe/psct/_out/psct_selfcheck.txt``（UTF-8 无 BOM），
控制台另打印一页"摘要"（避免中文乱码时看不到结果）。

覆盖：
  1. coverage_report() 各语言覆盖率
  2. 8 张覆盖不同情况的卡 × zh_cn/ja/en = 24 段卡文（全部打印）
  3. 这 24 段跑 lint()，断言零 ERROR（生成器 ↔ 校验器一致性）
  4. 6 段故意写错的卡文，断言 linter 报出对应 code
  5. 灵摆卡：pendulum_text_i18n 与 text_i18n 都非空且内容不同
  6. type_line / st_label × 15 种 frame × zh_cn/ja/en
  7. 缺口语言回落（ko）不返回 None，且标明实际使用的语言
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cardforge.content import psct                                    # noqa: E402
from cardforge.content.psct import gen, lexicon, lint, rules          # noqa: E402
from cardforge.core.enums import FRAMES                               # noqa: E402
from cardforge.core.models import (                                   # noqa: E402
    CardSpec, EffectCost, EffectSpec, EffectTarget,
)

OUT_DIR = Path(__file__).resolve().parent / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT = OUT_DIR / "psct_selfcheck.txt"
LANGS = ("zh_cn", "ja", "en")

_lines: list[str] = []
_checks: list[tuple[bool, str]] = []


def say(msg: str = "") -> None:
    _lines.append(msg)


def check(ok: bool, label: str) -> bool:
    _checks.append((bool(ok), label))
    say(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    return bool(ok)


def head(title: str) -> None:
    say("")
    say("═" * 78)
    say(title)
    say("═" * 78)


# ══════════════════════════════════════════════════════════════════════
#  8 张测试卡
# ══════════════════════════════════════════════════════════════════════
def card_normal() -> CardSpec:
    """① 通常怪兽（文本框 = 说明文）。"""
    return CardSpec(
        id=9100001, name="苍岚的古代龙", frame="normal", attribute="光",
        race="龙族", level=6, atk=2400, dfd=2000, archetype="苍岚",
        flavor="传说在苍岚之巅守护着古老誓约的巨龙，鳞片会映出极光。",
        flavor_i18n={
            "ja": "蒼嵐の頂で古き誓いを守るという伝説の竜。その鱗は極光を映す。",
            "en": "A legendary dragon said to guard an ancient oath atop the azure "
                  "peak. Its scales mirror the aurora.",
        },
    )


def card_single() -> CardSpec:
    """② 效果怪兽·单效果（召唤成功时检索 + 单数卡名 HOPT）。"""
    return CardSpec(
        id=9100002, name="苍岚的斥候", name_i18n={"ja": "蒼嵐の斥候",
                                                 "en": "Azure Gale Scout"},
        frame="effect", attribute="风", race="鸟兽族", level=3, atk=1200, dfd=600,
        archetype="苍岚",
        effects=[EffectSpec(
            kind="search", trigger="NORMAL_SUMMON_SUCCESS", limit="hopt_name",
            target=EffectTarget(filter_kind="archetype", filter_value="苍岚",
                                from_zone="DECK"),
            params={"optional": True},
        )],
    )


def card_double() -> CardSpec:
    """③ 双效果·卡名 HOPT（①② 各能使用1次）。"""
    return CardSpec(
        id=9100003, name="苍岚的双刃龙", name_i18n={"ja": "蒼嵐の双刃竜",
                                                   "en": "Azure Gale Twin-Blade Dragon"},
        frame="effect", attribute="风", race="龙族", level=8, atk=2800, dfd=2000,
        archetype="苍岚",
        effects=[
            EffectSpec(kind="search", trigger="IGNITION", limit="hopt_name",
                       target=EffectTarget(filter_kind="archetype",
                                           filter_value="苍岚", from_zone="DECK",
                                           count=1),
                       params={"optional": True,
                               "condition": {"zh_cn": "自己场上有「苍岚」卡存在的场合",
                                             "ja": "自分フィールドに「苍岚」カードが存在する場合",
                                             "en": "If you control a \"苍岚\" card"}}),
            EffectSpec(kind="ssummon_grave", trigger="WHEN_DESTROYED",
                       limit="hopt_name",
                       target=EffectTarget(from_zone="GRAVE", filter_kind="archetype",
                                           filter_value="苍岚"),
                       params={"optional": True, "timing": "if"}),
        ],
    )


def card_ignition() -> CardSpec:
    """④ 起动效果（1回合1次 + 解放代价 + 取对象）。"""
    return CardSpec(
        id=9100004, name="苍岚的审判者", name_i18n={"ja": "蒼嵐の審判者",
                                                   "en": "Azure Gale Adjudicator"},
        frame="effect", attribute="光", race="天使族", level=5, atk=2100, dfd=1600,
        archetype="苍岚",
        effects=[EffectSpec(
            kind="destroy", trigger="IGNITION", limit="once_per_turn",
            cost=EffectCost(kind="release", zone="MZONE", count=1),
            target=EffectTarget(from_zone="FIELD", controller="opponent", count=1),
            params={"optional": True},
        )],
    )


def card_continuous() -> CardSpec:
    """⑤ 永续效果（不入连锁：中日文有「：」，英文不带冒号/分号）。"""
    return CardSpec(
        id=9100005, name="苍岚的旗帜", name_i18n={"ja": "蒼嵐の旗印",
                                                 "en": "Azure Gale Banner"},
        frame="effect", attribute="风", race="魔法师族", level=4, atk=1500, dfd=1200,
        archetype="苍岚",
        effects=[EffectSpec(
            kind="continuous_gain_atk", trigger="CONTINUOUS", limit="none",
            target=EffectTarget(filter_kind="any", controller="self", from_zone="FIELD"),
            params={"n": 500, "optional": False},
        )],
    )


def card_pendulum() -> CardSpec:
    """⑥ 灵摆卡：灵摆效果框 + 怪兽效果框（两套独立编号）。"""
    return CardSpec(
        id=9100006, name="苍岚的钟摆龙", name_i18n={"ja": "蒼嵐のペンデュラム竜",
                                                   "en": "Azure Gale Pendulum Dragon"},
        frame="pendulum", attribute="风", race="龙族", level=4, atk=1700, dfd=1400,
        pendulum_scale=3, archetype="苍岚",
        effects=[
            EffectSpec(kind="continuous_gain_atk", trigger="CONTINUOUS", limit="none",
                       target=EffectTarget(filter_kind="any", controller="self",
                                           from_zone="FIELD"),
                       params={"n": 300, "optional": False}),
            EffectSpec(kind="search", trigger="SPECIAL_SUMMON_SUCCESS",
                       limit="hopt_name",
                       target=EffectTarget(filter_kind="archetype",
                                           filter_value="苍岚", from_zone="DECK"),
                       params={"optional": True}),
            EffectSpec(kind="ssummon_deck", trigger="IGNITION", limit="hopt_name",
                       target=EffectTarget(filter_kind="archetype",
                                           filter_value="苍岚", from_zone="DECK"),
                       cost=EffectCost(kind="pay_lp", lp=800),
                       params={"optional": True}),
            EffectSpec(kind="return_deck", trigger="END_PHASE", limit="none",
                       target=EffectTarget(filter_kind="any", controller="self",
                                           from_zone="GRAVE"),
                       params={"optional": False}),
        ],
        pendulum_effect_indices=[2, 3],
    )


def card_quick_spell() -> CardSpec:
    """⑦ 速攻魔法。"""
    return CardSpec(
        id=9100007, name="苍岚的急袭", name_i18n={"ja": "蒼嵐の急襲",
                                                 "en": "Azure Gale Raid"},
        frame="spell", spell_kind="quick", archetype="苍岚",
        effects=[EffectSpec(
            kind="destroy", trigger="QUICK", limit="none",
            target=EffectTarget(from_zone="FIELD", controller="opponent", count=1),
            params={"optional": True},
        )],
    )


def card_counter_trap() -> CardSpec:
    """⑧ 反击陷阱。"""
    return CardSpec(
        id=9100008, name="苍岚的反击", name_i18n={"ja": "蒼嵐の反撃",
                                                 "en": "Azure Gale Counter"},
        frame="trap", trap_kind="counter", archetype="苍岚",
        effects=[EffectSpec(
            kind="negate", trigger="ON_ACTIVATE", limit="none",
            cost=EffectCost(kind="discard_self", count=1),
            params={"optional": True},
        )],
    )


CARDS = [
    ("①通常怪兽", card_normal),
    ("②效果怪兽·单效果", card_single),
    ("③双效果·卡名HOPT", card_double),
    ("④起动效果", card_ignition),
    ("⑤永续效果", card_continuous),
    ("⑥灵摆卡双文本", card_pendulum),
    ("⑦速攻魔法", card_quick_spell),
    ("⑧反击陷阱", card_counter_trap),
]


# ══════════════════════════════════════════════════════════════════════
#  1. 覆盖率
# ══════════════════════════════════════════════════════════════════════
def test_coverage() -> None:
    head("1. 术语覆盖率 coverage_report()")
    rep = lexicon.coverage_report()
    say(f"术语总数 {rep['total']}；数据源：terms={rep['sources'].get('terms')}")
    say(f"                patterns={rep['sources'].get('patterns')}")
    say("")
    say(f"{'语言':<8}{'有值':>6}{'null':>6}{'覆盖率':>9}  原生模板  可用于生成  缺口分类")
    for lg, d in rep["by_lang"].items():
        gaps = ",".join(f"{k}:{v}" for k, v in sorted(d["missing_by_category"].items()))
        say(f"{lg:<8}{d['present']:>6}{d['null']:>6}{d['coverage']:>9.1%}"
            f"  {'是' if d['native_templates'] else '否':<8}"
            f"  {'是' if d['usable_for_generation'] else '否（降级 en）':<10}  {gaps}")
    say("")
    say(f"按分类：{rep['by_category']}")
    say(f"降级语言：{rep['degraded_langs']}")
    check(rep["total"] >= 200, f"术语表加载成功（{rep['total']} 条）")
    check(rep["by_lang"]["ko"]["null"] > 0, "ko 的缺口被如实报告（不是 0）")


# ══════════════════════════════════════════════════════════════════════
#  2/3. 生成 + lint
# ══════════════════════════════════════════════════════════════════════
def test_generate_and_lint() -> dict:
    head("2. 8 张卡 × zh_cn / ja / en 生成结果（全部打印）")
    specs: dict[str, CardSpec] = {}
    all_issues: list[tuple[str, str, object]] = []
    for label, factory in CARDS:
        spec = factory()
        specs[label] = spec
        metas = gen.fill_spec(spec, LANGS)
        say("")
        say("─" * 78)
        say(f"【{label}】{spec.name}  frame={spec.frame} "
            f"type_line(zh)={gen.type_line(spec, 'zh_cn') or gen.st_label(spec, 'zh_cn')}")
        say("─" * 78)
        for lg in LANGS:
            meta = metas[lg]
            say(f"── {lg}（used={meta['used_lang']}，行数估算 {meta['lines']}"
                f"/{meta['max_lines']}，source={meta['source']}）")
            say(meta["text"] or "（空）")
            if spec.is_pendulum:
                pm = meta.get("pendulum") or {}
                say(f"   ↳ 灵摆效果框（{pm.get('lines')}/{pm.get('max_lines')} 行）")
                say("   " + (pm.get("text") or "（空）").replace("\n", "\n   "))
            for note in meta["notes"]:
                say(f"   · 注：{note}")

    head("3. 24 段卡文跑 lint()，断言零 ERROR（生成器 ↔ 校验器一致性）")
    for label, spec in specs.items():
        issues = lint.lint(spec)
        errs = [i for i in issues if i.level == "ERROR"]
        all_issues.append((label, "lint(spec)", issues))
        say("")
        say(f"【{label}】lint(spec) → {len(issues)} 条："
            f"ERROR {sum(1 for i in issues if i.level == 'ERROR')} / "
            f"WARN {sum(1 for i in issues if i.level == 'WARN')} / "
            f"INFO {sum(1 for i in issues if i.level == 'INFO')}")
        for i in issues:
            say(f"   [{i.level:<5}] {i.code:<28} {i.field:<28} {i.message}")
        check(not errs, f"{label}：lint(spec) 零 ERROR"
                        + ("" if not errs else f"（实得 {[i.code for i in errs]}）"))

    # 逐语言 lint_text（带 spec，做跨语言对照）
    for label, spec in specs.items():
        for lg in LANGS:
            text = (spec.text_i18n or {}).get(lg, "")
            issues = lint.lint_text(text, lg, spec)
            errs = [i for i in issues if i.level == "ERROR"]
            check(not errs, f"{label}/{lg}：lint_text 零 ERROR"
                            + ("" if not errs else f"（实得 {[i.code for i in errs]}）"))
    return specs


# ══════════════════════════════════════════════════════════════════════
#  4. 故意写错的卡文
# ══════════════════════════════════════════════════════════════════════
BAD_CASES: list[tuple[str, str, str, str, str]] = [
    # (说明, 语言, 卡文, 期望命中的 code, 期望 level)
    ("中文用了分号", "zh_cn",
     "①：1回合1次，自己主要阶段才能发动；从卡组把1张「苍岚」卡加入手卡。",
     "PSCT_PUNCT_CJK_SEMICOLON", "ERROR"),
    ("英文把 cost 写在分号之后", "en",
     "① Once per turn: You can target 1 monster you control; "
     "Tribute it, and if you do, draw 1 card.",
     "PSCT_COST_AFTER_SEMI", "ERROR"),
    ("编号跳号（①→③）", "zh_cn",
     "①：自己主要阶段才能发动。从卡组把1张「苍岚」卡加入手卡。\n"
     "③：这张卡被破坏时才能发动。自己从卡组抽1张卡。",
     "PSCT_NUM_SEQUENCE", "ERROR"),
    ("检索没有回合限制", "zh_cn",
     "①：自己主要阶段才能发动。从卡组把1张「苍岚」卡加入手卡。",
     "PSCT_HOPT_MISSING", "ERROR"),
    ("中文里混入英文连接词", "zh_cn",
     "①：1回合1次，自己主要阶段才能发动。then 从卡组抽1张卡。",
     "PSCT_CONJ_FOREIGN_IN_CJK", "ERROR"),
    ("中文写取对象、英文没写", "zh_cn",
     "①：以对方场上的1张卡为对象才能发动。把那张卡破坏。",
     "PSCT_TARGET_MISSING_EN", "ERROR"),
    ("英文有 target、中文没写", "zh_cn",
     "①：1回合1次，自己主要阶段才能发动。把对方场上的1张卡破坏。",
     "PSCT_TARGET_MISSING_ZH", "WARN"),
    ("HOPT 写在条件之后（英文）", "en",
     "① You can target 1 card in your GY: Once per turn, add it to your hand.",
     "PSCT_HOPT_POSITION", "WARN"),
    ("编号没在段首", "zh_cn",
     "①：1回合1次，自己主要阶段才能发动。③：把对方场上的1张卡破坏。",
     "PSCT_NUM_MID_PARAGRAPH", "ERROR"),
    ("民间误译（同调）", "zh_cn",
     "①：1回合1次，自己主要阶段才能发动。把1只同调怪兽特殊召唤。",
     "PSCT_FOLK_TERM", "WARN"),
    ("同一段里时/场合混用", "zh_cn",
     "①：自己场上有「苍岚」卡存在的场合，这张卡被破坏时才能发动。自己从卡组抽1张卡。",
     "PSCT_TIMING_MIXED", "WARN"),
    ("英文有两段结构却缺分号", "en",
     "① Once per turn: You can target 1 card in your GY add it to your hand.",
     "PSCT_PUNCT_EN_MISSING_SEMI", "WARN"),
    ("中文用半角双引号", "zh_cn",
     "①：1回合1次，自己主要阶段才能发动。从卡组把1张\"苍岚\"卡加入手卡。",
     "PSCT_QUOTE_STYLE", "WARN"),
    ("引用了卡名但没加引号", "zh_cn",
     "①：1回合1次，自己主要阶段才能发动。从卡组把1张苍岚的双刃龙加入手卡。",
     "PSCT_NAME_UNQUOTED", "WARN"),
    ("卡文超出文本框容量", "zh_cn",
     "①：1回合1次，自己主要阶段才能发动。从卡组把1张「苍岚」卡加入手卡，"
     "那之后，把1张手卡送去墓地，并且自己从卡组抽1张卡，此外，"
     "直到回合结束时自己场上的怪兽的攻击力上升500。\n"
     "②：这张卡被破坏的场合才能发动。从墓地把1只「苍岚」怪兽特殊召唤，"
     "那个场合，自己回复1000点LP，此外，那之后，把对方场上的1张卡破坏。\n"
     "③：把这张卡解放才能发动。把对方场上的1张卡除外，并且自己抽1张卡。\n"
     "这个卡名的①②的效果1回合各能使用1次。",
     "PSCT_TEXT_TOO_LONG", "WARN"),
    ("编号超过⑩", "zh_cn",
     "①：自己主要阶段才能发动。从卡组把1张「苍岚」卡加入手卡。\n"
     "⑪：1回合1次，这张卡被破坏时才能发动。自己从卡组抽1张卡。",
     "PSCT_NUM_BEYOND_TABLE", "WARN"),
]


def test_bad_texts(specs: dict) -> None:
    head("4. 故意写错的卡文 → 断言 linter 报出对应 code")
    base = specs["③双效果·卡名HOPT"]
    for label, lang, text, code, level in BAD_CASES:
        spec = None
        if code in ("PSCT_TARGET_MISSING_EN", "PSCT_TARGET_MISSING_ZH"):
            # 跨语言检查需要一份 spec：把对照语言写成"缺 target"的样子
            spec = CardSpec(id=9200000, name="对照卡", frame="effect",
                            attribute="暗", race="战士族", level=4, atk=1000, dfd=1000)
            if code == "PSCT_TARGET_MISSING_EN":
                spec.text_i18n = {"zh_cn": text,
                                  "en": "① Once per turn: You can destroy 1 card "
                                        "your opponent controls."}
            else:
                spec.text_i18n = {"zh_cn": text,
                                  "en": "① Once per turn: You can target 1 card "
                                        "your opponent controls; destroy it."}
        elif code == "PSCT_NAME_UNQUOTED":
            # 卡名未加引号的检查需要知道卡名
            spec = CardSpec(id=9200001, name="苍岚的双刃龙", frame="effect",
                            attribute="暗", race="战士族", level=4, atk=1000, dfd=1000)
            spec.text_i18n = {"zh_cn": text}
        issues = lint.lint_text(text, lang, spec) if spec is None else lint.lint(spec)
        codes = [i.code for i in issues]
        hit = code in codes
        say("")
        say(f"【{label}】期望 {level} {code}")
        say(f"   文本：{text.replace(chr(10), ' / ')}")
        for i in issues:
            say(f"   [{i.level:<5}] {i.code:<28} {i.message}")
        check(hit, f"{label}：命中 {code}"
                   + ("" if hit else f"（实得 {sorted(set(codes))}）"))

    # 反向对照：正文里**引用**编号（这个卡名的③效果）不该被误判为段落编号
    ref_text = ("①：1回合1次，自己主要阶段才能发动。这个卡名的③效果适用，"
                "从卡组把1张「苍岚」卡加入手卡。")
    ref_codes = [i.code for i in lint.lint_text(ref_text, "zh_cn")]
    say("")
    say("【反向对照】正文引用编号「这个卡名的③效果」不应触发 PSCT_NUM_MID_PARAGRAPH")
    for i in lint.lint_text(ref_text, "zh_cn"):
        say(f"   [{i.level:<5}] {i.code:<28} {i.message}")
    check("PSCT_NUM_MID_PARAGRAPH" not in ref_codes,
          f"引用编号不算段落起始违规（实得 {sorted(set(ref_codes))}）")

    # 编号超过 ⑳：需要 21 条效果，用程序生成
    many = "\n".join(
        f"{rules.number_symbol(i)}：1回合1次，自己主要阶段才能发动。自己从卡组抽1张卡。"
        for i in range(1, 22))
    many_issues = lint.lint_text(many, "zh_cn")
    many_codes = [i.code for i in many_issues]
    say("")
    say("【编号超过⑳】21 条编号效果")
    for i in many_issues:
        say(f"   [{i.level:<5}] {i.code:<28} {i.message}")
    check("PSCT_NUM_OVERFLOW" in many_codes,
          f"编号超过 ⑳ 报 ERROR（实得 {sorted(set(many_codes))}）")


# ══════════════════════════════════════════════════════════════════════
#  5. 灵摆双文本
# ══════════════════════════════════════════════════════════════════════
def test_pendulum(specs: dict) -> None:
    head("5. 灵摆卡：pendulum_text_i18n 与 text_i18n 都非空且内容不同")
    spec = specs["⑥灵摆卡双文本"]
    for lg in LANGS:
        a = (spec.text_i18n or {}).get(lg, "")
        b = (spec.pendulum_text_i18n or {}).get(lg, "")
        say("")
        say(f"── {lg}")
        say(f"   怪兽效果框：{a.replace(chr(10), ' ⏎ ')}")
        say(f"   灵摆效果框：{b.replace(chr(10), ' ⏎ ')}")
        check(bool(a) and bool(b), f"{lg}：两个文本框都非空")
        check(a != b, f"{lg}：两个文本框内容不同")
    check(bool(spec.pendulum_effect_indices), "pendulum_effect_indices 已设置（效果分流）")


# ══════════════════════════════════════════════════════════════════════
#  6. 15 种 frame 的类型行
# ══════════════════════════════════════════════════════════════════════
def test_type_lines() -> None:
    head("6. type_line / st_label × 全部 frame × zh_cn/ja/en（人工核对格式）")
    say("")
    say(f"{'frame':<20}{'zh_cn':<28}{'ja':<32}{'en'}")
    for key, fd in FRAMES.items():
        spec = CardSpec(id=1, name="样本", frame=key, attribute="暗", race="魔法师族",
                        level=4, atk=1800, dfd=1200, tags=["tuner"] if key == "synchro" else [])
        if key == "spell":
            spec.spell_kind = "quick"
        if key == "trap":
            spec.trap_kind = "counter"
        if key in ("normal", "normal_pendulum"):
            spec.effects = []
        else:
            spec.effects = [EffectSpec(kind="draw", trigger="IGNITION")]
        cells = []
        for lg in LANGS:
            txt = gen.type_line(spec, lg) or gen.st_label(spec, lg)
            cells.append(txt)
        say(f"{key:<20}{cells[0]:<28}{cells[1]:<32}{cells[2]}")
    # 格式断言
    dragon = CardSpec(id=2, name="x", frame="effect", attribute="炎", race="龙族",
                      level=4, atk=1800, dfd=1200,
                      effects=[EffectSpec(kind="draw")])
    check(gen.type_line(dragon, "zh_cn") == "【龙族／炎属性／效果】",
          "简中类型行 = 【龙族／炎属性／效果】（种族带「族」、全角斜杠）")
    check(gen.type_line(dragon, "ja") == "【ドラゴン族／炎／効果】",
          "日文类型行 = 【ドラゴン族／炎／効果】")
    check(gen.type_line(dragon, "en") == "[Dragon / FIRE / Effect]",
          "英文类型行 = [Dragon / FIRE / Effect]")
    quick = CardSpec(id=3, name="x", frame="spell", spell_kind="quick")
    counter = CardSpec(id=4, name="x", frame="trap", trap_kind="counter")
    check(gen.st_label(quick, "zh_cn") == "【速攻魔法】", "速攻魔法 = 【速攻魔法】")
    check(gen.st_label(counter, "zh_cn") == "【反击陷阱】", "反击陷阱 = 【反击陷阱】")
    check(gen.st_label(quick, "en") == "[Quick-Play Spell]",
          "英文速攻 = [Quick-Play Spell]")
    check(gen.type_line(quick, "zh_cn") == "", "魔陷没有怪兽类型行")


# ══════════════════════════════════════════════════════════════════════
#  7. 缺口语言回落
# ══════════════════════════════════════════════════════════════════════
def test_fallback(specs: dict) -> None:
    head("7. 缺口语言回落（ko）：不返回 None，且标明实际语言")
    text, used = lexicon.term_or_fallback("act_search", "ko")
    say(f"term_or_fallback('act_search', 'ko') = ({text!r}, {used!r})")
    check(used == "en" and bool(text), "ko 缺口回落到 en 并标明 used_lang='en'")
    check(lexicon.term("act_search", "ko") is not None, "term() 对缺口语言不返回 None")

    missing = [k for k, v in lexicon.terms().items() if not v.get("ko")]
    ok = True
    for k in missing:
        for lg in ("ko", "xx", "de"):
            if lexicon.term(k, lg) is None:
                ok = False
    say(f"ko 缺口术语 {len(missing)} 条，逐条查 ko/xx/de 均无 None：{ok}")
    check(ok, f"{len(missing)} 条 ko 缺口术语全部有回落值（永不 None）")

    spec = specs["③双效果·卡名HOPT"]
    meta = gen.compose_with_meta(spec, "ko")
    say("")
    say(f"compose_with_meta(spec, 'ko') → used_lang={meta['used_lang']}，"
        f"degraded={meta['degraded']}")
    say(f"   reason: {meta['reason']}")
    say(f"   text  : {meta['text'].splitlines()[0] if meta['text'] else '(空)'}")
    check(meta["degraded"] and meta["used_lang"] == "en" and bool(meta["reason"]),
          "ko 生成降级到 en 且在返回结构里标注了 used_lang/degraded/reason")
    zh_tw = gen.compose_with_meta(spec, "zh_tw")
    check(zh_tw["used_lang"] == "en", "zh_tw 同样降级（未手写繁中句式，不硬造）")


# ══════════════════════════════════════════════════════════════════════
#  8. HOPT 三种写法必须区分
# ══════════════════════════════════════════════════════════════════════
def test_hopt_forms() -> None:
    head("8. HOPT 三种写法（与 psct_patterns.json 的 hopt 对应，必须区分）")
    rows = [
        ("once_per_turn（写进发动条件）", "once_per_turn"),
        ("hopt_name（段末另起一句，①/①②）", "hopt_name_use"),
        ("hopt_name（单数：只限制①）", "hopt_name_this"),
        ("hopt_name_activate（怪兽）", "hopt_name_activate_monster"),
        ("hopt_name_activate（魔陷）", "hopt_name_activate"),
        ("hopt_name_apply（决斗中1次）", "hopt_name_apply"),
        ("hopt_gain_effect_once", "hopt_gain_effect_once"),
        ("hopt_once_while_face_up", "hopt_once_while_face_up"),
    ]
    for label, key in rows:
        say("")
        say(f"【{label}】key={key}")
        for lg in LANGS:
            if key == "hopt_name_this":
                text = lexicon.hopt_single(lg, "样本卡", "①")
            else:
                text = lexicon.hopt(key, lg, "样本卡", numbers="①②")
            say(f"   {lg:<7} {text}")
    check(lexicon.hopt("once_per_turn", "zh_cn").strip() == "1回合1次，".strip(),
          "once_per_turn 的中文写法是「1回合1次，」（写在发动条件里）")
    check("各能使用1次" in lexicon.hopt("hopt_name_use", "zh_cn"),
          "hopt_name 用「① ② 各能使用1次」复数句式")
    check("只能使用1次" in lexicon.hopt_single("zh_cn", "样本卡"),
          "单效果限制用「只能使用1次」单数句式")
    check("只能发动1次" in lexicon.hopt("hopt_name_activate_monster", "zh_cn"),
          "怪兽的 activate 档写「这个卡名的效果1回合只能发动1次」")
    check("只能发动1张" in lexicon.hopt("hopt_name_activate", "zh_cn"),
          "魔陷的 activate 档写「「X」1回合只能发动1张」（官方句式）")


# ══════════════════════════════════════════════════════════════════════
#  9. 内置兜底表（data/lexicons 缺失）
# ══════════════════════════════════════════════════════════════════════
def test_builtin_fallback() -> None:
    head("9. data/lexicons/ 缺失时的内置兜底表（子进程实测）")
    import subprocess
    script = Path(__file__).resolve().parent / "_fallback_only.py"
    try:
        res = subprocess.run([sys.executable, str(script)], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=120, cwd=str(ROOT))
        out = (res.stdout or "") + (res.stderr or "")
    except Exception as e:                                          # pragma: no cover
        out = f"子进程失败：{type(e).__name__}: {e}"
    for line in out.splitlines():
        say("   " + line)
    check("RESULT: OK" in out, "无 data/lexicons 时三语卡文仍可生成（内置兜底表生效）")
    check("内置兜底术语条数 = 208" in out, "兜底表覆盖 208 条核心术语")


# ══════════════════════════════════════════════════════════════════════
def main() -> int:
    say("PSCT 卡文生成与校验引擎 · 自测报告")
    say(f"生成器原生语言：{rules.NATIVE_GEN_LANGS}；"
        f"降级语言：{rules.LOW_COVERAGE_LANGS} + 其余非原生语言")
    say(f"规则条数：{len(lint.RULES)}；编号上限 {rules.NUMBER_MAX}")
    try:
        test_coverage()
        specs = test_generate_and_lint()
        test_bad_texts(specs)
        test_pendulum(specs)
        test_type_lines()
        test_fallback(specs)
        test_hopt_forms()
        test_builtin_fallback()
    except Exception:
        say("")
        say("！！自测脚本异常：")
        say(traceback.format_exc())

    passed = sum(1 for ok, _ in _checks if ok)
    total = len(_checks)
    head(f"汇总：{passed}/{total} 项断言通过")
    for ok, label in _checks:
        if not ok:
            say(f"  FAIL  {label}")
    if passed == total:
        say("  全部通过。")

    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    print(f"[selfcheck] {passed}/{total} passed → {OUT}")
    for ok, label in _checks:
        if not ok:
            print(f"  FAIL {label}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
