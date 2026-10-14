"""Lua 生成器回归自测：覆盖 15 种卡框 × 多效果组合。

验收口径（与 docs/03 一致，全部**真跑**）：

* ``lint.syntax_ok`` 为真
* ``lint.lint_lua`` 0 ERROR
* ``lint.check_stringid_sync`` 空
* ``apicatalog.unknown`` 三个桶全空 —— 命中即说明生成了这个 build 里不存在的 API

结果写文件（Windows 控制台是 GBK，直接 print 中文会炸）。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cardforge.content import effects as EF                      # noqa: E402
from cardforge.content.psct import rules                                     # noqa: E402
from cardforge.content.lua import apicatalog as API              # noqa: E402
from cardforge.content.lua import emit, lint                     # noqa: E402
from cardforge.content.lua.fragments import FRAGMENTS as FRAGS               # noqa: E402
from cardforge.core.models import (CardSpec, EffectCost,         # noqa: E402
                                   EffectSpec, EffectTarget, RenderOptions)

OUT = pathlib.Path("workspace/.cache/selfcheck-lua.txt")

KINDS = list(EF.EFFECT_KINDS)


def mk(cid: int, name: str, frame: str, **kw) -> CardSpec:
    s = CardSpec(id=cid, name=name, frame=frame, **kw)
    s.render = RenderOptions(lang_text="zh_cn")
    return s


def eff(kind: str, *, trigger: str = "IGNITION", limit: str = "once_per_turn",
        zone: str = "DECK", filt: str = "archetype", val=None, n: int = 1,
        cost=None, **params) -> EffectSpec:
    e = EffectSpec(kind=kind, trigger=trigger, limit=limit,
                   target=EffectTarget(from_zone=zone, filter_kind=filt,
                                       filter_value=val, count=n),
                   cost=EffectCost(**(cost or {})) if cost else None,
                   params=dict(params))
    return e


def cases() -> list[tuple[str, CardSpec]]:
    out: list[tuple[str, CardSpec]] = []

    s = mk(210000001, "测试·效果怪兽", "effect", attribute="暗", race="战士族",
           level=4, atk=1800, dfd=1200, archetype="测试", setcode="0x1001")
    s.effects = [eff("search", trigger="NORMAL_SUMMON_SUCCESS", val="测试"),
                 eff("ssummon_hand", limit="hopt_name", val="测试",
                     cost={"kind": "discard", "count": 1}),
                 eff("draw", trigger="END_PHASE", limit="once_duel", n=1)]
    out.append(("效果怪兽·3 效果", s))

    out.append(("通常怪兽（应无脚本）",
                mk(210000002, "测试·通常", "normal", attribute="光", race="龙族",
                   level=4, atk=1800, dfd=1200)))

    s = mk(210000003, "测试·仪式", "ritual", attribute="水", race="魔法师族",
           level=6, atk=2200, dfd=1800, archetype="测试", setcode="0x1001")
    s.effects = [eff("destroy", zone="FIELD", filt="race", val="龙族",
                     cost={"kind": "detach"})]
    out.append(("仪式怪兽", s))

    s = mk(210000004, "测试·融合", "fusion", attribute="炎", race="龙族",
           level=7, atk=2600, dfd=2000, archetype="测试", setcode="0x1001")
    s.effects = [eff("banish", zone="FIELD", filt="any", n=2),
                 eff("lp_damage", n=1, value=800, trigger="QUICK")]
    out.append(("融合怪兽", s))

    s = mk(210000005, "测试·同步", "synchro", attribute="风", race="机械族",
           level=8, atk=2700, dfd=2000, tags=["tuner"], archetype="测试", setcode="0x1001")
    s.effects = [eff("negate", trigger="OPPONENT_ACTIVATE", limit="hopt_name_activate")]
    out.append(("同步怪兽", s))

    s = mk(210000006, "测试·超量", "xyz", attribute="暗", race="恶魔族",
           level=4, atk=2500, dfd=2000, archetype="测试", setcode="0x1001")
    s.effects = [eff("send_grave", zone="FIELD", cost={"kind": "detach", "count": 1}),
                 eff("gain_atk", zone="FIELD", value=500, n=1)]
    out.append(("超量怪兽", s))

    s = mk(210000007, "测试·连接", "link", attribute="光", race="电子界族",
           atk=2300, dfd=0, link_markers=["左下", "右下", "左", "右"],
           archetype="测试", setcode="0x1001")
    s.effects = [eff("return_hand", zone="FIELD", n=1, limit="once_per_turn"),
                 eff("ssummon_extra", val="测试", limit="hopt_name")]
    out.append(("连接怪兽·4 箭头", s))

    s = mk(210000008, "测试·灵摆", "pendulum_effect", attribute="暗", race="魔法师族",
           level=4, atk=1500, dfd=1500, pendulum_scale=4,
           archetype="测试", setcode="0x1001")
    s.effects = [eff("draw", n=1, trigger="CONTINUOUS"),
                 eff("search", val="测试", trigger="IGNITION")]
    s.pendulum_effect_indices = [0]
    out.append(("灵摆效果怪兽·双文本框", s))

    s = mk(210000009, "测试·通常灵摆", "normal_pendulum", attribute="地", race="岩石族",
           level=2, atk=800, dfd=800, pendulum_scale=2)
    out.append(("通常灵摆（应无脚本）", s))

    for k, kind in [("速攻魔法", "quick"), ("永续魔法", "continuous"),
                    ("装备魔法", "equip"), ("场地魔法", "field"), ("仪式魔法", "ritual")]:
        s = mk(210000010, f"测试·{k}", "spell", spell_kind=kind,
               archetype="测试", setcode="0x1001")
        s.effects = [eff("search", val="测试",
                         trigger="IGNITION" if kind != "quick" else "QUICK")]
        out.append((k, s))

    for k, kind in [("通常陷阱", "normal"), ("永续陷阱", "continuous"),
                    ("反击陷阱", "counter")]:
        s = mk(210000011, f"测试·{k}", "trap", trap_kind=kind,
               archetype="测试", setcode="0x1001")
        s.effects = [eff("negate" if kind == "counter" else "destroy",
                         trigger="OPPONENT_ACTIVATE" if kind == "counter"
                         else "WHEN_DESTROYED", zone="FIELD")]
        out.append((k, s))

    out.append(("衍生物（应无脚本）",
                mk(210000012, "测试·衍生物", "token", attribute="光", race="兽族",
                   level=1, atk=500, dfd=500)))

    s = mk(210000013, "测试·技能卡", "skill", archetype="测试", setcode="0x1001")
    out.append(("技能卡", s))

    s = mk(210000014, "测试·全种类", "effect", attribute="光", race="龙族",
           level=4, atk=1600, dfd=1200, archetype="测试", setcode="0x1001")
    s.effects = [eff(kind, zone="FIELD" if kind not in
                     ("search", "draw", "mill", "ssummon_deck", "excavate",
                      "set_from_deck", "discard_opponent", "ssummon_grave",
                      "ssummon_extra", "ssummon_hand", "search_grave",
                      "recover", "return_deck", "shuffle_deck",
                      "search_banished", "ssummon_banished") else "DECK",
                     val="测试", value=300, counter=0x1, n=1,
                     trigger="CONTINUOUS" if kind in rules.CONTINUOUS_KINDS
                     else "IGNITION")
                 for kind in KINDS]
    out.append((f"单卡塞满 {len(KINDS)} 种效果", s))

    return out


def main() -> int:
    lines: list[str] = []
    fails = 0
    total = 0
    for title, spec in cases():
        total += 1
        try:
            lua = emit.emit_script(spec)
        except Exception as e:
            fails += 1
            lines.append(f"[EXC ] {title}: {type(e).__name__}: {e}")
            continue
        if not lua.strip():
            vanilla = spec.frame in ("normal", "normal_pendulum", "token")
            lines.append(f"[{'OK  ' if vanilla else 'FAIL'}] {title}: 空脚本"
                         f"{'（该卡种本就无脚本）' if vanilla else ' ← 不该为空'}")
            fails += 0 if vanilla else 1
            continue
        problems: list[str] = []
        ok, why = lint.syntax_ok(lua)
        if not ok:
            problems.append(f"语法：{why}")
        for i in lint.lint_lua(lua, spec):
            if i.level == "ERROR":
                problems.append(f"{i.code}：{i.message}")
        for i in lint.check_stringid_sync(spec, lua):
            if i.level == "ERROR":
                problems.append(f"Stringid：{i.message}")
        un = API.unknown(lua)
        for bucket in ("calls", "methods", "consts"):
            if un.get(bucket):
                problems.append(f"白名单外 {bucket}：{un[bucket]}")
        todos = lua.count("需人工补写")
        if problems:
            fails += 1
            lines.append(f"[FAIL] {title} → " + " | ".join(problems))
        else:
            lines.append(f"[OK  ] {title}: {len(lua.splitlines())} 行"
                         f"{'，%d 处降级注释' % todos if todos else ''}")
    head = [f"CardForge · Lua 生成器自测",
            f"效果种类 {len(KINDS)} 个 / 片段 {len(FRAGS)} 个",
            f"用例 {total}，失败 {fails}", "─" * 60]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    print(f"{'PASS' if fails == 0 else 'FAIL'} {total - fails}/{total} → {OUT}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
