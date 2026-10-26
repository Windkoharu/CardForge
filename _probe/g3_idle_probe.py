# -*- coding: utf-8 -*-
"""诊断：真 ocgcore 在 IDLE 提示里到底有没有给出「额外卡组的自我特殊召唤」选项。

接触召唤能不能被 bot 走出来，取决于 cmd51 的哪一条列表里出现被测卡号；
这里把每张 IDLE 的各列表内容抓下来看，不猜协议。

用法::

    PYTHONIOENCODING=utf-8 python _probe/g3_idle_probe.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "_probe"))

from build_lumiel import build  # noqa: E402
from cardforge.content.lua import emit  # noqa: E402
from cardforge.duel import bot  # noqa: E402
from g3_contact import MAT_ID, material  # noqa: E402

CAPTURE: list[dict] = []
_orig_idle = bot.SimpleBot._idlecmd


def _spy(self, msg, state):
    out = _orig_idle(self, msg, state)
    snap = {k: [int(x.get("code") or 0) for x in (msg.get(k) or [])]
            for k in ("summon", "spsummon", "monster_set", "spell_set", "activate")}
    snap["keys"] = sorted(msg.keys())
    snap["turn_player"] = state.get("turn_player")
    snap["turn"] = state.get("turns")
    CAPTURE.append(snap)
    return out


bot.SimpleBot._idlecmd = _spy


def main() -> int:
    lum = build()
    lum.lua = emit.emit_script(lum, tier=1)
    mat = material()
    fillers = [89631139, 45467446, 73176492, 77098843, 85861495, 385172]
    deck_a = [lum.id] * 3 + [mat.id] * 3 + fillers
    deck_b = fillers[:4] * 6
    info = {"field": [{"code": mat.id, "team": 0, "seq": i, "pos": 1}
                      for i in range(3)],
            "action": {"summon_code": lum.id}}
    res = bot.run_duel(deck_a, deck_b, seed=7, max_steps=900,
                       cards={lum.id: lum, mat.id: mat}, scenario=info)
    out = io.StringIO()
    out.write(f"steps={res.get('steps')} turns={res.get('turns')} "
              f"errors={res.get('errors')}\n")
    out.write(f"IDLE 提示共 {len(CAPTURE)} 次\n\n")
    hits = [c for c in CAPTURE if lum.id in (c.get("summon") or [])
            or lum.id in (c.get("spsummon") or [])]
    out.write(f"被测卡出现在 IDLE 列表里的次数：{len(hits)}\n")
    for c in hits[:5]:
        out.write(f"  turn={c['turn']} keys={c['keys']} "
                  f"summon={c['summon']} spsummon={c['spsummon']}\n")
    # 头几次 IDLE 的完整内容（看协议里到底有哪些键）
    out.write("\n前 3 次 IDLE 快照：\n")
    for c in CAPTURE[:3]:
        out.write("  " + repr(c)[:400] + "\n")
    # 场上素材是否被除外 / 额外卡组是否动过
    moves = [e for e in (res.get("log") or []) if int(e.get("id") or 0) == 50]
    out.write(f"\n位置移动 {len(moves)} 条；涉及被测卡/素材的：\n")
    for e in moves:
        if int(e.get("code") or 0) in (lum.id, mat.id):
            out.write(f"  turn={e.get('turn')} code={e.get('code')} "
                      f"from={e.get('from_location')} to={e.get('to_location')}\n")
    text = out.getvalue()
    (ROOT / "_probe" / "g3_idle_probe.txt").write_text(text, encoding="utf-8")
    print(text.encode("utf-8", "ignore").decode("utf-8", "ignore"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
