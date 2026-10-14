"""验证新增的三条 PSCT 规则（报告 A8.1 E03 / E28、A9.2）。"""
from cardforge.content.psct import lint

FAILS = []


def run(text, lang, tags, expect_hit, note=""):
    out = lint.lint_text(text, lang)
    codes = {i.code for i in out}
    hit = any(t in codes for t in tags)
    ok = "✓" if hit == expect_hit else "✗"
    if hit != expect_hit:
        FAILS.append((text, lang, tags, expect_hit, sorted(codes)))
    print(f"  {ok} [{lang}] {'命中' if hit else '未命中':<4} {text[:58]}")
    if hit:
        for i in out:
            if i.code in tags:
                print(f"        → {i.code}: {i.message} | {i.field}")


print("=" * 70)
print("【E03】效果处理写在分号之前 —— 应命中")
run("Once per turn: You can add 1 card from your Deck to your hand; draw 1 card.",
    "en", ["PSCT_RESOLUTION_BEFORE_SEMI"], True)
run("①：从卡组把1张卡加入手卡才能发动。抽1张卡。", "zh_cn",
    ["PSCT_RESOLUTION_BEFORE_SEMI"], True)
print("【E03】正确写法 —— 不应命中")
run("Once per turn: You can target 1 monster; destroy it.",
    "en", ["PSCT_RESOLUTION_BEFORE_SEMI"], False)
run("Once per turn: You can Tribute 1 monster; destroy 1 card on the field.",
    "en", ["PSCT_RESOLUTION_BEFORE_SEMI"], False)
run("①：把自己场上的1只怪兽解放才能发动。对方场上的1张卡破坏。", "zh_cn",
    ["PSCT_RESOLUTION_BEFORE_SEMI"], False)

print()
print("=" * 70)
print("【E28】内置特召缺来源括号 —— 应命中")
run("You can Special Summon this card. If you do, draw 1 card.", "en",
    ["PSCT_BUILTIN_SS_NO_ORIGIN"], True)
print("【E28】带来源括号 —— 不应命中")
run("You can Special Summon this card (from your hand).", "en",
    ["PSCT_BUILTIN_SS_NO_ORIGIN"], False)

print()
print("=" * 70)
print("【A9.2】HERO 大小写 —— 应命中")
run('Special Summon 1 "Elemental Hero Neos" from your Deck.', "en",
    ["PSCT_HERO_CASE"], True)
run('Add 1 "Destiny Hero - Malicious" to your hand.', "en",
    ["PSCT_HERO_CASE"], True)
print("【A9.2】正确/特例 —— 不应命中")
run('Special Summon 1 "Elemental HERO Neos" from your Deck.', "en",
    ["PSCT_HERO_CASE"], False)
run('Special Summon 1 "Hero Kid" from your Deck.', "en",
    ["PSCT_HERO_CASE"], False)

print()
print("=" * 70)
if FAILS:
    print(f"✗ {len(FAILS)} 个用例不符合预期：")
    for t, l, tags, exp, got in FAILS:
        print(f"   [{l}] {t[:50]!r} 期望命中={exp} 实际规则={got}")
    raise SystemExit(1)
print("✓ 全部用例通过")
