# -*- coding: utf-8 -*-
"""级别 1 验证：用 cardforge.duel.ocgcore 跑一局官方卡对战（最小应答案）。"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from cardforge.core import paths
from cardforge.duel import ocgcore as oc

OUT = Path("workspace/logs/level1_duel.json")

SAMPLES = paths.OFFICIAL_SCRIPTS / "samples"
ids = sorted(int(p.stem[1:]) for p in SAMPLES.glob("c*.lua") if p.stem[1:].isdigit())

core = oc.OcgCore()
core.register_cdb(paths.OFFICIAL_CDB / "cards_zh.cdb")

# 按卡面 type 拆主/额外
main, extra = [], []
for cid in ids:
    row = core._cdb_row(cid)
    if not row:
        continue
    t = int(row["type"] or 0)
    if not (t & oc.TYPE_MONSTER):
        (main if t & (oc.TYPE_SPELL | oc.TYPE_TRAP) else main).append(cid)
        continue
    (extra if oc.is_extra_deck_type(t) else main).append(cid)

deck_main = (main[:14] * 3)[:40]
deck_extra = (extra[:5] * 3)[:15]
report = {"main_count": len(main), "extra_count": len(extra),
          "deck_main": len(deck_main), "deck_extra": len(deck_extra)}

status = core.create_duel(seed=7)
report["create_status"] = status
if status:
    report["create_status_name"] = oc.CREATION_STATUS.get(status)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(1)

inj = core.inject_deck(deck_main + [0] * (40 - len(deck_main)), deck_main,
                       deck_extra, deck_extra)
report["inject"] = inj
core.start_duel()

def _respond(m: dict, n: int) -> bytes:
    ev = m["id"]
    if ev == 11:
        if m.get("summon") and n == 0:
            return oc.encode_idlecmd(0, 0)
        if m.get("spsummon") and n <= 1:
            return oc.encode_idlecmd(1, 0)
        if m.get("to_end"):
            return oc.encode_idlecmd(7, 0)
        if m.get("to_battle"):
            return oc.encode_idlecmd(6, 0)
        return oc.encode_idlecmd(5, 0) if m.get("activate") else b""
    if ev == 10:
        if m.get("attackable") and n == 0:
            return oc.encode_battlecmd(1, 0)
        return oc.encode_battlecmd(3 if m.get("to_end") else 2, 0)
    if ev == 16:
        return oc.encode_chain_choice(0 if m.get("forced") and n == 0 else -1)
    if ev in (12, 13):
        return oc.encode_yesno(0)
    if ev == 14:
        return oc.encode_option(0)
    if ev in (15, 20, 23):
        if m.get("cancelable"):
            return oc.encode_select_card(None, cancel=True)
        cnt = min(max(int(m.get("min", 1)), 1), len(m.get("cards") or []) or 1)
        return oc.encode_select_card(range(cnt))
    if ev in (18, 24):
        return oc.encode_places(_zones(m, n))
    if ev == 19:
        mask = int(m.get("positions", 1))
        for bit in (1, 4, 8, 2):
            if mask & bit:
                return oc.encode_position(bit)
        return oc.encode_position(1)
    if ev in (21, 25):
        return oc.encode_sort_order([])
    if ev == 22:
        return oc.encode_counters([0] * len(m.get("cards") or []))
    if ev in (140,):
        return oc.encode_race(int(m.get("available", 1)) & -int(m.get("available", 1)))
    if ev in (141,):
        return oc.encode_attribute(int(m.get("available", 1)) & -int(m.get("available", 1)))
    if ev in (142, 143):
        return oc.encode_option(0)
    if ev == 132:
        return oc.encode_option(1)
    if ev == 26:
        return oc.encode_int32(1, 0)
    return oc.encode_int32(0)


def _zones(m: dict, n: int) -> list:
    flag = int(m.get("flag", 0))
    count = int(m.get("count", 1))
    out = []
    f = flag
    for _ in range(count):
        placed = False
        for loc, base, limit in ((0x04, 0, 7), (0x08, 8, 8), (0x04, 16, 7), (0x08, 24, 8)):
            for seq in range(limit):
                if not (f >> (base + seq)) & 1:
                    player = 0 if base < 16 else 1
                    out.append((player, loc, seq if loc == 0x04 else (seq if base == 8 else seq - 8)))
                    f |= 1 << (base + seq)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            break
    return out



lp = [8000, 8000]
turns = 0
phase = 0
winner = None
attempts: dict = {}
seen_fp: dict = {}
log = []
steps = 0
stuck = ""
tail: list = []
oc_raw: list = []
last_resp = None
for steps in range(1, 20001):
    st = core.process()
    raw = core.get_message()
    oc_raw.append(len(raw))
    msgs = oc.parse_messages(raw)
    names = []
    answer = None
    for m in msgs:
        names.append(m["event"])
        if m["id"] == 40:
            turns += 1
        if m["id"] == 41:
            phase = m.get("phase", phase)
        if m["id"] == 5:
            winner = (m.get("player"), m.get("reason_name"))
        if m["id"] == 91:
            lp[m["player"]] -= m["amount"]
        if m["id"] == 92:
            lp[m["player"]] += m["amount"]
        if m["id"] == 100:
            lp[m["player"]] -= m["cost"]
        if m["id"] == 94:
            lp[m["player"]] = m["lp"]
        if m.get("answer"):
            answer = m
    if log and log[-1][0] == names and log[-1][1] == answer is None:
        pass
    log.append((names, answer["id"] if answer else None))
    tail.append({"step": steps, "status": st, "len": len(raw),
                 "events": [(m["id"], m.get("decode_error", "")[:40],
                             m.get("raw", "")[:64]) for m in msgs][:4],
                 "last_resp": (last_resp.hex() if last_resp else "")})
    tail = tail[-14:]
    if winner is not None or st == 0:
        break
    if st == 2:
        continue
    if answer is None:
        report["no_answer_message_at"] = steps
        report["no_answer_raw_len"] = oc_raw[-1] if oc_raw else 0
        report["tail"] = tail
        break
    fp = (answer["id"], answer["raw"], turns)
    seen_fp[fp] = seen_fp.get(fp, 0) + 1
    if seen_fp[fp] > 6:
        stuck = f"重复状态：event={answer['event']} 连续 7 次（回合 {turns}）"
        break
    n = attempts.get(fp, 0)
    attempts[fp] = n + 1
    resp = _respond(answer, n)
    last_resp = resp
    core.set_response(resp)


report.update(steps=steps, turns=turns, lp=lp, winner=winner, stuck=stuck,
              script_errors=core.script_errors[:15],
              error_count=len(core.script_errors),
              missing_scripts=core.missing_scripts[:15],
              loaded=len(core.loaded_scripts))
counts = {}
for names, _ in log:
    for e in names:
        counts[e] = counts.get(e, 0) + 1
report["event_counts"] = counts
report["distinct_events"] = sorted(counts)
report["raw_lens"] = oc_raw[-20:]
report["tail"] = tail
core.end_duel()
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("done")
