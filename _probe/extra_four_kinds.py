# -*- coding: utf-8 -*-
"""诊断：四类额外卡组召唤（融合 / 同步 / 超量 / 连接）在真 ocgcore 里，
哪些会被引擎列为「可选的特殊召唤」。

素材全部用 DIY 卡（自带脚本，无缺脚本干扰），开局前摆到场上；
只看 MSG_SELECT_IDLECMD 的 ``spsummon`` 列表里有没有被测卡号。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "_probe"))

from cardforge.content.lua import emit                      # noqa: E402
from cardforge.core.models import (CardSpec, MaterialPart,  # noqa: E402
                                   SummonSpec)
from cardforge.duel import bot                              # noqa: E402

VANILLA = "local s,id=GetID()\nfunction s.initial_effect(c)\nend\n"
MAT, TUNER, ATTR = 210000041, 210000042, 210000043
FUS, SYN, XYZ, LNK = 210000061, 210000062, 210000063, 210000064

CAPTURE: list[list[int]] = []
_orig_idle = bot.SimpleBot._idlecmd


def _spy(self, msg, state):
    out = _orig_idle(self, msg, state)
    CAPTURE.append([int(x.get("code") or 0) for x in (msg.get("spsummon") or [])])
    return out


bot.SimpleBot._idlecmd = _spy


def mat(code: int, tags=None) -> CardSpec:
    return CardSpec(id=code, name=f"素材{code}", frame="effect",
                    attribute="光", race="战士族", level=4, atk=1600, dfd=1200,
                    archetype="测试", setcode="0x1000", tags=tags or [],
                    effects=[], lua=VANILLA)


def extra(code: int, frame: str, level: int, parts: list) -> CardSpec:
    spec = CardSpec(id=code, name=f"额外{code}", frame=frame,
                    attribute="光", race="战士族", level=level,
                    atk=3000, dfd=2500, archetype="测试", setcode="0x1000",
                    effects=[{"kind": "pierce", "trigger": "CONTINUOUS"}])
    spec.summon = SummonSpec(materials=parts)
    return spec


def run(tag: str, spec: CardSpec, mats: list, level: int = 0) -> str:
    CAPTURE.clear()
    spec.lua = emit.emit_script(spec, tier=1)
    cards = {spec.id: spec, MAT: mat(MAT), TUNER: mat(TUNER, ["tuner"]),
             ATTR: mat(ATTR)}
    deck_a = [spec.id] * 3 + [m.id for m in mats[:3]]
    res = bot.run_duel(deck_a, [89631139, 45467446, 73176492, 77098843],
                       seed=7, max_steps=260, cards=cards,
                       scenario={"field": [{"code": m.id, "team": 0, "seq": i,
                                            "pos": 1} for i, m in enumerate(mats)],
                                 "action": {"summon_code": spec.id}})
    hits = sum(1 for lst in CAPTURE if spec.id in lst)
    head = [ln.strip() for ln in spec.lua.splitlines()
            if "AddProc" in ln or "AddProcedure" in ln]
    return (f"{tag:<8} 可选={hits}/{len(CAPTURE)}  turns={res.get('turns')} "
            f"err={len(res.get('errors') or [])}\n    {head}\n")


def main() -> int:
    out = []
    out.append(run("融合", extra(FUS, "fusion", 8, [MaterialPart(
        kind="archetype", value="测试",
        also=[MaterialPart(kind="race", value="战士族")], count=3)]),
        [mat(MAT)] * 3))
    out.append(run("同步", extra(SYN, "synchro", 8, [
        MaterialPart(kind="any", value="", tuner="tuner", count=1),
        MaterialPart(kind="any", value="", tuner="non_tuner", count=2)]),
        [mat(TUNER, ["tuner"]), mat(ATTR), mat(ATTR)]))
    out.append(run("超量", extra(XYZ, "xyz", 4, [
        MaterialPart(kind="level", value=4, count=2)]), [mat(MAT), mat(ATTR)]))
    out.append(run("连接", extra(LNK, "link", 2, [
        MaterialPart(kind="any", value="", count=2)]), [mat(MAT), mat(ATTR)]))
    text = "".join(out)
    (ROOT / "_probe" / "extra_four_kinds.txt").write_text(text, encoding="utf-8")
    print(text.encode("utf-8", "ignore").decode("utf-8", "ignore"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
