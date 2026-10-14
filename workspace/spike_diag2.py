# -*- coding: utf-8 -*-
"""诊断 2：抓 select_chain 的原始载荷、解析结果、我方响应与紧随其后的 RETRY。"""
from __future__ import annotations

import json
from pathlib import Path

from cardforge.core import paths
from cardforge.duel import bot as B
from cardforge.duel import ocgcore as oc

OUT = Path("workspace/logs/diag_chain.json")
sampled = B.sample_card_ids()
core = oc.OcgCore()
core.register_cdb(paths.OFFICIAL_CDB / "cards_zh.cdb")
da = B.build_deck(core, sampled[:20], fillers=sampled)
core.create_duel(seed=42)
core.inject_deck(da["main"], da["main"], da["extra"], da["extra"])
core.start_duel()

bot = B.SimpleBot()
pending = None
trace = []
decode_fail: dict = {}
turns = 0
last_resp = ""
for step in range(1, 3000):
    st = core.process()
    msgs = core.messages()
    retry = False
    ans = None
    for m in msgs:
        if m["id"] == 40:
            turns += 1
        if m.get("decode_error"):
            k = str(m.get("event"))
            decode_fail[k] = decode_fail.get(k, 0) + 1
        if m["id"] == 1:
            retry = True
            trace.append({"step": step, "RETRY_AFTER": {"resp": last_resp,
                        "was": pending.get("event") if pending else None,
                        "raw": (pending.get("raw") or "")[:120] if pending else "",
                        "turn": turns}})
        elif m.get("answer"):
            ans = m
    if ans is not None:
        pending = ans
    if st == 0:
        break
    if st != 1 or pending is None:
        continue
    key = f"{pending['id']}:{pending['raw']}"
    p = dict(pending)
    p["retry_key"] = key
    resp = bot.decide(p, {"turns": turns, "action": {}})
    last_resp = resp.hex() if resp else ""
    if len(trace) < 60 and pending["id"] in (16, 15, 18, 20, 23, 26):
        trace.append({"step": step, "ASK": {"event": pending["event"], "turn": turns,
                    "raw": (pending.get("raw") or "")[:200],
                    "decode_error": pending.get("decode_error", ""),
                    "forced": pending.get("forced"), "chains_n": len(pending.get("chains") or []),
                    "chains": (pending.get("chains") or [])[:2],
                    "cancelable": pending.get("cancelable"), "min": pending.get("min"),
                    "max": pending.get("max"), "cards_n": len(pending.get("cards") or [])}}),
    core.set_response(resp or oc.encode_int32(0))

core.end_duel()
OUT.write_text(json.dumps({"turns": turns, "decode_fail": decode_fail,
                           "trace": trace[:60]}, ensure_ascii=False, indent=2),
               encoding="utf-8")
print("done")
