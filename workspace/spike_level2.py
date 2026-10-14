# -*- coding: utf-8 -*-
"""级别 1/2 验证：用 cardforge.duel.bot.run_duel 跑官方卡整局。"""
from __future__ import annotations

import json
from pathlib import Path

from cardforge.core import paths
from cardforge.duel import bot as B

OUT = Path("workspace/logs/level2_duel.json")

sampled = B.sample_card_ids()
con = __import__("sqlite3").connect(str(paths.OFFICIAL_CDB / "cards_zh.cdb"))
con.row_factory = __import__("sqlite3").Row
rows = {r["id"]: r for r in con.execute("SELECT id,type FROM datas")}
monsters, spells, extras = [], [], []
for cid in sampled:
    row = rows.get(cid)
    if not row:
        continue
    t = int(row["type"] or 0)
    if t & 0x40820C0 and t & 1:
        extras.append(cid)
    elif t & 0x20 and t & 1:
        monsters.append(cid)
    elif t & 0x6:
        spells.append(cid)

decks = {
    "mirror_monsters": (monsters[:8] * 2)[:20] + spells[:12],
    "wide": monsters[:20] + spells[:20],
    "xyz_heavy": monsters[:10] + extras[:4] * 2 + spells[:10] + monsters[20:26],
}
def _hist(log: list) -> dict:
    out: dict = {}
    for e in log:
        k = e.get("event")
        out[k] = out.get(k, 0) + 1
    return out



report: dict = {}
for name, main in decks.items():
    res = B.run_duel(main, main, seed=42, max_steps=8000)
    res.pop("log", None)
    report[name] = {k: v for k, v in res.items() if k != "detail"} | {
        "detail_keys": {kk: res["detail"].get(kk) for kk in
                        ("inject", "runtime_preloaded", "deck_notes", "setup",
                         "loaded_scripts", "missing_scripts")}}
    if name == "mirror_monsters":
        res2 = B.run_duel(main, main, seed=42, max_steps=8000)
        report[name]["event_histogram"] = _hist(res2["log"])
    report[name]["sample_log"] = (report.get(name, {}).get("sample_log") or [])


OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("done")
