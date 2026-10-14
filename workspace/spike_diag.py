# -*- coding: utf-8 -*-
"""诊断：把前 30 次 RETRY 的待答消息 + 我方响应抓出来。"""
from __future__ import annotations

import json
from pathlib import Path

from cardforge.core import paths
from cardforge.duel import bot as B
from cardforge.duel import ocgcore as oc

OUT = Path("workspace/logs/diag_retry.json")
sampled = B.sample_card_ids()
con = __import__("sqlite3").connect(str(paths.OFFICIAL_CDB / "cards_zh.cdb"))
con.row_factory = __import__("sqlite3").Row
rows = {r["id"]: r for r in con.execute("SELECT id,type FROM datas")}
monsters, spells = [], []
for cid in sampled:
    row = rows.get(cid)
    if not row:
        continue
    t = int(row["type"] or 0)
    if t & 1 and not (t & 0x40820C0):
        monsters.append(cid)
    elif t & 0x6:
        spells.append(cid)
main = (monsters[:8] * 2)[:20] + spells[:12]

core = oc.OcgCore()
core.register_cdb(paths.OFFICIAL_CDB / "cards_zh.cdb")
da = B.build_deck(core, main, fillers=sampled)
status = core.create_duel(seed=42)
core.inject_deck(da["main"], da["main"], da["extra"], da["extra"])
core.start_duel()

bot = B.SimpleBot()
events: list = []
pending = None
captures = []
turns = 0
for step in range(1, 400):
    st = core.process()
    msgs = core.messages()
    ans = None
    retry = False
    for m in msgs:
        if m["id"] == 40:
            turns += 1
        if m["id"] == 1:
            retry = True
        elif m.get("answer"):
            ans = m
    if ans is not None:
        pending = ans
    if st != 1:
        events.append({"step": step, "status": st, "ids": [m["id"] for m in msgs]})
        if st == 0:
            break
        continue
    if pending is None:
        events.append({"step": step, "problem": "awaiting 但无待答消息",
                       "ids": [m["id"] for m in msgs]})
        break
    key = f"{pending['id']}:{pending['raw']}"
    if retry and len(captures) < 30:
        captures.append({"step": step, "turn": turns, "event": pending["event"],
                         "id": pending["id"], "raw": pending["raw"],
                         "fields": {k: v for k, v in pending.items()
                                    if k not in ("raw", "all")},
                         "last_response": "",
                         "decode_error": pending.get("decode_error", "")})
    pending2 = dict(pending)
    pending2["retry_key"] = key
    resp = bot.decide(pending2, {"turns": turns, "action": {}})
    if len(captures) < 30:
        captures.append({"SENT": {"step": step, "event": pending["event"],
                                  "resp": (resp.hex() if resp else None),
                                  "attempt_key": key[:80]}})
    core.set_response(resp or b"")

core.end_duel()
OUT.write_text(json.dumps({"turns": turns, "captures": captures[:60],
                           "events": events[:40]}, ensure_ascii=False, indent=2),
               encoding="utf-8")
print("done")
