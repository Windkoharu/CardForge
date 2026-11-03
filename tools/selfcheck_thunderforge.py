"""原创「霆铸」竞技系列的构建与回归验收。

用法：
    py -3 tools/selfcheck_thunderforge.py --write       # 通过真实 API 创建/更新系列
    py -3 tools/selfcheck_thunderforge.py              # G1/G2/G4 + YDK 校验
    py -3 tools/selfcheck_thunderforge.py --g3         # 追加每张卡的真实 ocgcore 场景

规格全部从项目原生 IR 构造；卡文和 Lua 均由真实 API 生成，不手写产物。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardforge.core import console as _console                       # noqa: E402
_console.setup()   # 直接 print 中文卡名：GBK 管道下不许把验收打死

from cardforge.content.design import opening_probability
from cardforge.core.models import (
    Archetype, CardSpec, DeckEntry, DeckSpec, EffectCost, EffectSpec, EffectTarget,
    MaterialPart, RenderOptions, RosterSlot, SummonMethod, SummonSpec,
)
from cardforge.export import ydk
from cardforge.pipeline import gates
from cardforge.pool import official, repo
from cardforge.server.app import App
from cardforge.server import api_card
from cardforge.server.http import Request

ARCH = "霆铸"
SETCODE = "0x1003"
BASE_ID = 210100101
IDS = {key: BASE_ID + i for i, key in enumerate((
    "starter", "vanguard", "skirmisher", "circuit", "recovery", "forge", "command",
    "barrier", "revive", "fusion", "synchro", "xyz", "link", "tuner",
))}
ROLES = {
    "starter": [IDS["starter"], IDS["vanguard"], IDS["forge"], IDS["tuner"]],
    "extender": [IDS["skirmisher"], IDS["circuit"]],
    "trump": [IDS["fusion"], IDS["synchro"], IDS["xyz"], IDS["link"]],
    "support": [IDS["forge"], IDS["command"], IDS["barrier"], IDS["revive"]],
    "recovery": [IDS["recovery"], IDS["revive"]],
}


def target(zone: str, filter_kind: str = "archetype", value=None, *, count: int = 1,
           controller: str = "self", exclude: bool = False, face_up: bool = False) -> EffectTarget:
    if filter_kind == "archetype" and value is None:
        value = ARCH
    return EffectTarget(
        from_zone=zone, filter_kind=filter_kind, filter_value=value, count=count,
        controller=controller, exclude_self=exclude, face_up=face_up,
        setcode=SETCODE if filter_kind == "archetype" else "",
    )


def effect(kind: str, trigger: str, zone: str | None = None, *,
           limit: str = "hopt_name", params: dict | None = None,
           cost: EffectCost | None = None, **target_kw) -> EffectSpec:
    return EffectSpec(kind=kind, trigger=trigger, limit=limit,
                      target=target(zone, **target_kw) if zone else None,
                      cost=cost, params=dict(params or {}))


def card(key: str, name: str, frame: str, level: int, atk: int, dfd: int,
         effects: list[EffectSpec], *, tags: list | None = None,
         summon: SummonSpec | None = None, spell_kind: str = "", trap_kind: str = "",
         rarity: str = "common", markers: list | None = None) -> CardSpec:
    return CardSpec(
        id=IDS[key], name=name, frame=frame, attribute="光", race="雷族",
        level=level, atk=atk, dfd=dfd, archetype=ARCH, setcode=SETCODE,
        effects=effects, tags=list(tags or []), summon=summon or SummonSpec(),
        spell_kind=spell_kind, trap_kind=trap_kind, link_markers=list(markers or []),
        render=RenderOptions(rarity=rarity),
    )


def build_specs() -> list[CardSpec]:
    specs = [
        card("starter", "霆铸的炉心术士", "effect", 4, 1600, 1200, [
            effect("search", "SUMMON_ANY_SUCCESS", "DECK"),
        ]),
        card("vanguard", "霆铸的锻锤先锋", "effect", 4, 1500, 1000, [
            effect("ssummon", "NORMAL_SUMMON_SUCCESS", "DECK",
                   params={"card_type": "monster"},
                   cost=EffectCost(kind="discard", zone="HAND", count=1)), 
        ]),
        card("skirmisher", "霆铸的弧光游击", "effect", 4, 1700, 800, [
            effect("ssummon_hand", "IGNITION", "HAND", params={"card_type": "monster"}),
        ]),
        card("circuit", "霆铸的回路与弦", "effect", 3, 1200, 600, [
            effect("ssummon_grave", "WHEN_SENT_GRAVE", "GRAVE",
                   params={"card_type": "monster", "select": True}, exclude=True),
        ]),
        card("recovery", "霆铸的余热回收者", "effect", 4, 1400, 1000, [
            effect("search_grave", "WHEN_SENT_GRAVE", "GRAVE",
                   params={"card_type": "monster", "select": True}, exclude=True),
        ]),
        card("forge", "霆铸炉·雷光锻场", "spell", 0, 0, 0, [
            effect("search", "ON_ACTIVATE", "DECK", limit="hopt_name_activate",
                   params={"card_type": "spelltrap"}),
        ], spell_kind="normal", rarity="rare"),
        card("command", "霆铸炉·突击号令", "spell", 0, 0, 0, [
            effect("ssummon", "ON_ACTIVATE", "DECK", limit="hopt_name_activate",
                   params={"card_type": "monster"},
                   cost=EffectCost(kind="discard", zone="HAND", count=1)), 
        ], spell_kind="quick", rarity="super"),
        card("barrier", "霆铸炉·磁轨护壁", "trap", 0, 0, 0, [
            effect("negate", "OPPONENT_ACTIVATE_MONSTER", limit="once_per_turn",
                   cost=EffectCost(kind="send_grave", zone="FIELD", count=1,
                                   filter_kind="archetype", filter_value=ARCH)),
        ], trap_kind="counter", rarity="super"),
        card("revive", "霆铸炉·余烬再生", "trap", 0, 0, 0, [
            effect("ssummon_grave", "ON_ACTIVATE", "GRAVE", limit="hopt_name_activate",
                   params={"card_type": "monster", "select": True}, exclude=True),
        ], trap_kind="normal", rarity="rare"),
        card("fusion", "霆铸龙王 克罗诺斯", "fusion", 8, 2800, 2200, [
            effect("negate_card", "QUICK", "FIELD", filter_kind="any", controller="opponent",
                   face_up=True, limit="once_per_turn",
                   params={"quick": True, "until_end_turn": True}),
            effect("ssummon_grave", "WHEN_DESTROYED", "GRAVE",
                   params={"card_type": "monster", "select": True,
                           "destroyed_by": "battle_effect"}, exclude=True),
        ], summon=SummonSpec(
            materials=[MaterialPart(kind="archetype", value=ARCH, setcode=SETCODE, count=2)],
            methods=[SummonMethod(action="banish", zone="mz")], limit="must_be",
        ), rarity="ultra"),
        card("synchro", "霆铸机神 奥米茄", "synchro", 8, 2800, 2000, [
            effect("destroy", "QUICK", "FIELD", filter_kind="any", controller="opponent",
                   limit="once_per_turn", params={"quick": True}),
        ], summon=SummonSpec(materials=[
            MaterialPart(kind="archetype", value=ARCH, setcode=SETCODE, count=1, tuner="tuner"),
            MaterialPart(kind="archetype", value=ARCH, setcode=SETCODE,
                         count=1, count_max=2, tuner="non_tuner"),
        ]), rarity="ultra"),
        card("xyz", "霆铸天轨 宙斯", "xyz", 4, 2300, 1800, [
            effect("banish", "QUICK", "FIELD", filter_kind="any", controller="opponent",
                   limit="once_per_turn", params={"quick": True},
                   cost=EffectCost(kind="detach", count=1)),
        ], summon=SummonSpec(materials=[
            MaterialPart(kind="archetype", value=ARCH, setcode=SETCODE, count=2,
                         also=[{"kind": "level", "value": 4}]),
        ]), rarity="ultra"),
        card("link", "霆铸重轨 阿特拉", "link", 3, 2400, 0, [
            effect("ssummon_grave", "SPECIAL_SUMMON_SUCCESS", "GRAVE",
                   params={"card_type": "monster", "select": True}, exclude=True),
            effect("cannot_be_targeted", "CONTINUOUS", limit="none",
                   params={"self_obj": True}),
        ], summon=SummonSpec(materials=[
            MaterialPart(kind="archetype", value=ARCH, setcode=SETCODE, count=2, count_max=3),
        ]), markers=["左下", "下", "右下"], rarity="secret"),
        card("tuner", "霆铸的校准工匠", "effect", 4, 1500, 1200, [
            effect("search", "SUMMON_ANY_SUCCESS", "DECK", params={"card_type": "monster"}),
        ], tags=["tuner"], rarity="rare"),
    ]
    return specs


def build_archetype() -> Archetype:
    return Archetype(
        name=ARCH, name_i18n={"en": "Thunderforge", "ja": "霆鋳"}, setcode=SETCODE,
        concept="光属性雷族锻造师，以检索与特召展开，用四类炉心终端完成压制与斩杀。",
        win_method="MIX", trumps=["FUSION", "SYNCHRO", "XYZ", "LINK"],
        binding={"attribute": "光", "race": "雷族"},
        dialects=["这张卡召唤·特殊召唤成功时才能发动", "这个卡名的效果1回合各能使用1次",
                  "从自己墓地选「霆铸」怪兽特殊召唤"],
        roster=[RosterSlot(role=role, count=len(ids), done=list(ids))
                for role, ids in ROLES.items()],
        target_power="competitive",
        notes="12 张初动（4 种各 3 张）；终端素材全部绑定「霆铸」字段，拒绝泛用外挂。",
    )


def build_deck() -> DeckSpec:
    main_ids = [IDS[k] for k in ("starter", "vanguard", "skirmisher", "circuit", "recovery",
                                 "forge", "command", "barrier", "revive", "tuner")]
    main = [DeckEntry(card_id=cid, count=3, role="starter" if cid in ROLES["starter"] else "support")
            for cid in main_ids]
    # 30 张本家 + 10 张通用竞技卡 = 40；四初动合计 12 张。
    staples = [(14558127, 2), (97268402, 1), (23434538, 2),
               (24224830, 1), (10045474, 2), (14532163, 2)]
    main += [DeckEntry(card_id=cid, count=n, role="handtrap") for cid, n in staples]
    extra = [DeckEntry(card_id=IDS[k], count=3, role="trump")
             for k in ("fusion", "synchro", "xyz", "link")]
    return DeckSpec(name="霆铸竞技", archetype=ARCH, target="competitive",
                    main=main, extra=extra,
                    notes="本家 30 + 通用 10；四初动 12 张；额外四类各 3 张。")


def api(app: App, method: str, path: str, payload: dict | None = None,
        query: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
    req = Request(method, path, query=query or {}, body=body,
                  headers={"content-type": "application/json"} if body else {})
    resp = app.handle(req)
    data = json.loads(resp.body.decode("utf-8"))
    if resp.status >= 400 or data.get("ok") is False:
        raise RuntimeError(f"{method} {path} → {resp.status}: {data}")
    return data


def write_series() -> None:
    app = App()
    api_card.register(app)
    api(app, "POST", "/api/archetypes", build_archetype().to_dict())
    for spec in build_specs():
        api(app, "POST", "/api/cards", spec.to_dict())
        composed = api(app, "POST", "/api/psct/compose",
                       {"card": spec.id, "langs": ["zh_cn"], "write": True})
        if not composed.get("written"):
            raise RuntimeError(f"卡文写回失败：{spec.name}: {composed}")
        emitted = api(app, "POST", "/api/lua/emit", {"card": spec.id, "write": True})
        if emitted.get("script_error") or not emitted.get("script_path"):
            raise RuntimeError(f"Lua 写回失败：{spec.name}: {emitted}")
        print(f"[WRITE] {spec.id} {spec.name}")
    api(app, "POST", "/api/decks", build_deck().to_dict())
    print(f"[WRITE] {len(build_specs())} 张系列卡 + {build_deck().name}")


def validate(run_g3: bool = False) -> int:
    cards = [repo.load_card(spec.id, ARCH) for spec in build_specs()]
    assert all(cards), "系列卡缺失，请先运行 --write"
    cards = [c for c in cards if c is not None]
    arch = repo.load_archetype(ARCH)
    deck = repo.load_deck("霆铸竞技")
    assert arch and deck, "系列圣经或竞技卡组缺失"
    pool = official.load()
    failures: list[str] = []
    warn_count = 0
    for spec in cards:
        reps = [gates.g1_balance(spec, pool), gates.g2_script(spec)]
        if run_g3:
            reps.append(gates.g3_duel(spec, scenario=True, duels=0))
        for rep in reps:
            errors = [i for i in rep.issues if i.level == "ERROR"]
            warns = [i for i in rep.issues if i.level == "WARN"]
            warn_count += len(warns)
            print(f"[{rep.status.upper():6}] {rep.gate} {spec.id} {spec.name} "
                  f"E={len(errors)} W={len(warns)}")
            for issue in rep.issues:
                print(f"       {issue.level} {issue.code}: {issue.message}")
            if rep.status == "fail" or errors:
                failures.append(f"{spec.name}/{rep.gate}: {[i.code for i in errors]}")
    g4 = gates.g4_series(arch, cards, pool)
    print(f"[{g4.status.upper():6}] G4 {ARCH} 共 {len(cards)} 张")
    for issue in g4.issues:
        print(f"       {issue.level} {issue.code}: {issue.message}")
    if g4.status == "fail" or any(i.level == "ERROR" for i in g4.issues):
        failures.append("G4 系列一致性")
    deck_issues = ydk.validate(deck, pool_ids={c.id for c in cards})
    print(f"[{'PASS' if not deck_issues else 'CHECK':6}] YDK {ydk.sizes(deck)} "
          f"初动率={opening_probability(12):.2%}")
    for issue in deck_issues:
        print(f"       {issue.level} {issue.code}: {issue.message}")
    if any(i.level == "ERROR" for i in deck_issues):
        failures.append("YDK 卡组合法性")
    print(f"SUMMARY cards={len(cards)} warnings={warn_count} failures={len(failures)}")
    if failures:
        print("FAIL " + " | ".join(failures))
        return 1
    print("PASS 霆铸系列 G1/G2" + ("/G3" if run_g3 else "") + "/G4/YDK 全部通过")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="通过真实 API 创建/更新系列")
    ap.add_argument("--g3", action="store_true", help="追加真实 ocgcore 场景验证")
    args = ap.parse_args()
    if args.write:
        write_series()
    return validate(args.g3)


if __name__ == "__main__":
    raise SystemExit(main())
