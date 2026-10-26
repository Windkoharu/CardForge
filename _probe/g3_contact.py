# -*- coding: utf-8 -*-
"""**定向 G3**：让真 ocgcore 实际执行「把上记的卡除外 → 从额外卡组接触召唤」。

官方卡池里没有字段码 0x1000 的战士族怪兽，所以素材也用 DIY 卡：
一张 4 星战士族「圣痕的战士」摆 3 只上场，再看露米艾尔能不能除外它们上场。

判定分两层，都记进报告：

1. **引擎把接触召唤当作合法动作提供了吗** —— IDLE(cmd51) 的 ``spsummon``
   列表里出现被测卡号（这一层与 bot 的选择无关，纯看脚本的召唤流程）；
2. **真的执行了吗** —— 同一回合里素材进入除外区、被测卡进入怪兽区域。

用法::

    PYTHONIOENCODING=utf-8 python _probe/g3_contact.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "_probe"))

from build_lumiel import build  # noqa: E402
from cardforge.content import summon as CS  # noqa: E402
from cardforge.content.lua import emit  # noqa: E402
from cardforge.core.models import CardSpec  # noqa: E402
from cardforge.duel import bot, ocgcore as oc  # noqa: E402

MAT_ID = 210000041
MZONE = oc.LOCATION_MZONE
REMOVED = oc.LOCATION_REMOVED
VANILLA_SCRIPT = "local s,id=GetID()\nfunction s.initial_effect(c)\nend\n"

CAPTURE: list[dict] = []
_orig_idle = bot.SimpleBot._idlecmd


def _spy(self, msg, state):
    out = _orig_idle(self, msg, state)
    CAPTURE.append({"turn": state.get("turns"),
                    "player": msg.get("player"),
                    "spsummon": [int(x.get("code") or 0)
                                 for x in (msg.get("spsummon") or [])]})
    return out


bot.SimpleBot._idlecmd = _spy


def material() -> CardSpec:
    return CardSpec(id=MAT_ID, name="圣痕的战士", frame="effect",
                    attribute="光", race="战士族", level=4, atk=1600, dfd=1200,
                    archetype="圣痕", setcode="0x1000", effects=[],
                    lua=VANILLA_SCRIPT)


def try_seed(lum: CardSpec, mat: CardSpec, deck_a: list, deck_b: list,
             info: dict, seed: int) -> dict:
    CAPTURE.clear()
    res = bot.run_duel(deck_a, deck_b, seed=seed, max_steps=2500,
                       cards={lum.id: lum, mat.id: mat}, scenario=info)
    offered = [c for c in CAPTURE if lum.id in (c.get("spsummon") or [])]
    moves = [e for e in (res.get("log") or []) if int(e.get("id") or 0) == 50]
    up = [e for e in moves if int(e.get("code") or 0) == lum.id
          and int(e.get("to_location") or 0) & MZONE]
    ban = [e for e in moves if int(e.get("code") or 0) == mat.id
           and int(e.get("to_location") or 0) & REMOVED]
    turns_up = {int(e.get("turn") or 0) for e in up}
    turns_ban = {int(e.get("turn") or 0) for e in ban}
    executed = bool(turns_up & turns_ban) and len(ban) >= 3
    return {"seed": seed, "ok": bool(res.get("ok")), "turns": res.get("turns"),
            "errors": res.get("errors") or [], "offered": len(offered),
            "offered_turns": sorted({int(c["turn"] or 0) for c in offered})[:6],
            "up": len(up), "banished": len(ban), "executed": executed,
            "up_turns": sorted(turns_up)[:6], "ban_turns": sorted(turns_ban)[:6]}


def main() -> int:
    out = io.StringIO()
    lum = build()
    lum.lua = emit.emit_script(lum, tier=1)
    mat = material()
    fillers = [89631139, 45467446, 73176492, 77098843, 85861495, 385172]
    deck_a = [lum.id] * 3 + [mat.id] * 3 + fillers
    deck_b = fillers[:4] * 6
    info = {"field": [{"code": mat.id, "team": 0, "seq": i, "pos": 1}
                      for i in range(3)],
            "action": {"summon_code": lum.id}}
    out.write(f"被测卡：{lum.name}（{lum.id}）｜素材：{mat.name}（{mat.id}）×3 上场\n")
    out.write(f"素材条件：{CS.material_line(lum, 'zh_cn')}\n\n")
    results = []
    for seed in (7, 11, 13, 17, 23, 29, 31, 37):
        r = try_seed(lum, mat, deck_a, deck_b, info, seed)
        results.append(r)
        out.write(f"seed={r['seed']:>3} 局终={r['ok']} 回合={r['turns']:>2} "
                  f"引擎提供接触召唤={r['offered']}次(回合{r['offered_turns']}) "
                  f"上场={r['up']} 素材除外={r['banished']} "
                  f"同回合执行={r['executed']} 报错={len(r['errors'])}\n")
        if r["errors"]:
            out.write(f"        errors={r['errors'][:2]}\n")
        if r["executed"]:
            break
    offered_any = any(r["offered"] for r in results)
    executed_any = any(r["executed"] for r in results)
    script_err = any(any("lua" in str(e).lower() or "script" in str(e).lower()
                         for e in r["errors"]) for r in results)
    out.write("\n==== 结论 ====\n")
    out.write(f"1) 引擎把接触召唤列为合法动作：{'是' if offered_any else '否'}\n")
    out.write(f"2) 实际执行（除外 3 只上记的卡 → 从额外卡组特殊召唤）："
              f"{'是' if executed_any else '否'}\n")
    out.write(f"3) 脚本运行期报错：{'有' if script_err else '无'}\n")
    text = out.getvalue()
    (ROOT / "_probe" / "g3_contact.txt").write_text(text, encoding="utf-8")
    print(text.encode("utf-8", "ignore").decode("utf-8", "ignore"))
    return 0 if (offered_any and executed_any and not script_err) else 1


if __name__ == "__main__":
    sys.exit(main())
