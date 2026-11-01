# -*- coding: utf-8 -*-
"""修完之后的回归实测：卡名→卡号、以外的、留空兜底、反解不再误判。"""
import sys, io, json
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from cardforge.core.models import CardSpec, EffectSpec, EffectTarget, EffectCost
from cardforge.content import effects as E
from cardforge.content.psct import gen as G
from cardforge.content.lua import emit
from cardforge.content import design


def spec_of(**kw):
    s = CardSpec(id=100000001, name="星奏的序章", frame="effect", attribute="光",
                 race="魔法师族", level=1, atk=0, dfd=0,
                 archetype="星奏", setcode="0x1000")
    return s


def mk(fk, fv, *, code=0, setcode="", exclude=False, count=1, params=None):
    s = spec_of()
    s.effects = [EffectSpec(kind="search", trigger="NORMAL_SUMMON_SUCCESS",
                            limit="hopt_name",
                            target=EffectTarget(from_zone="DECK", to_zone="HAND",
                                                filter_kind=fk, filter_value=fv,
                                                count=count, controller="self",
                                                code=code, setcode=setcode,
                                                exclude_self=exclude),
                            cost=EffectCost(kind="none"), params=params or {})]
    return s


CASES = [
    ("① 本家任意一张（留空兜底）", lambda: mk("archetype", "")),
    ("② 本家任意一张（写明）", lambda: mk("archetype", "星奏")),
    ("③ 只要本家怪兽", lambda: mk("archetype", "星奏", params={"card_type": "monster"})),
    ("④ 本家某张卡（已解析卡号）", lambda: mk("name", "星奏的和音", code=469865890)),
    ("⑤ 本家某张卡（没卡号）", lambda: mk("name", "星奏的和音")),
    ("⑥ 以外的（不写 select）", lambda: mk("archetype", "星奏", exclude=True)),
    ("⑦ 检索别的字段（填了码）", lambda: mk("archetype", "焰刃", setcode="0x2000")),
    ("⑧ 检索别的字段（没码）", lambda: mk("archetype", "焰刃")),
]

for title, f in CASES:
    s = f()
    filled = E.normalize_targets(s)
    txt = " ".join(G.compose(s, "zh_cn").split())
    lua = emit.emit_script(s)
    fil = [l.strip() for l in lua.splitlines() if "IsSetCard" in l or "IsCode" in l]
    sel = [l.strip() for l in lua.splitlines() if "SelectMatchingCard" in l]
    g1 = [f"{i.level}:{i.code}" for i in design.audit_card(s, None, check_pool=False)]
    ir = [f"{i.level}:{i.code}" for i in E.validate_effects(s)]
    print("=" * 72)
    print(title)
    print(" 补齐 :", filled or "—")
    print(" 卡文 :", txt)
    print(" 过滤 :", fil)
    print(" 选择 :", sel)
    print(" G1   :", g1 or "—")
    print(" IR   :", ir or "—")

print("=" * 72)
print("反解回归（这三句都必须原样 round-trip）")
TEXTS = [
    "①：这张卡召唤成功时才能发动。从卡组把1张「星奏」卡加入手卡。",
    "①：这张卡召唤成功时才能发动。从卡组把1张「星奏的和音」加入手卡。",
    "①：这张卡召唤成功时才能发动。从卡组把「星奏的序章」以外的1张「星奏」卡加入手卡。",
    "①：这张卡召唤成功时才能发动。从卡组把1只「星奏」怪兽加入手卡。",
    "①：这张卡召唤成功时才能发动。从卡组把「星奏的序章」以外的1只「星奏」怪兽加入手卡。",
    "①：以对方场上1张表侧表示的卡为对象才能发动。那张卡的效果直到回合结束时无效。",
]
for text in TEXTS:
    s = spec_of()
    effs = E.infer_from_text(text, s.name, [s.archetype])
    s.effects = effs
    out = " ".join(G.compose(s, "zh_cn").split())
    t = effs[0].target if effs else None
    print("-" * 72)
    print(" 原文 :", text)
    print(" 反解 :", (t.filter_kind if t else "?"), "=", (t.filter_value if t else None),
          "| code", (t.code if t else None), "| 以外", (t.exclude_self if t else None))
    print(" 一致 :", out == " ".join(text.split()), "" if out == " ".join(text.split()) else out)
