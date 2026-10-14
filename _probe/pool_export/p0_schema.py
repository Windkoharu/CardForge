"""自测 0：实测官方 cdb 的真实 schema。"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
CDB = ROOT / "vendor" / "data" / "cards_zh.cdb"
OUT = ROOT / "_probe" / "pool_export" / "_out"
OUT.mkdir(parents=True, exist_ok=True)

lines: list[str] = []


def p(s: str = "") -> None:
    lines.append(str(s))


uri = "file:" + CDB.as_posix() + "?mode=ro"
con = sqlite3.connect(uri, uri=True)
p(f"cdb = {CDB}")
p(f"size = {CDB.stat().st_size/1024/1024:.2f} MB")
p()
p("=== sqlite_master ===")
for typ, name, tbl_name, sql in con.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"):
    p(f"-- {typ} {name} (tbl={tbl_name})")
    p((sql or "").strip())
    p()

for t in ("datas", "texts"):
    p(f"=== PRAGMA table_info({t}) ===")
    p(f"{'cid':>4} {'name':<12} {'type':<10} {'notnull':>7} {'dflt':>6} {'pk':>3}")
    for cid, name, ctype, notnull, dflt, pk in con.execute(f"PRAGMA table_info({t})"):
        p(f"{cid:>4} {name:<12} {ctype:<10} {notnull:>7} {str(dflt):>6} {pk:>3}")
    p()

# 行数
for t in ("datas", "texts"):
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    p(f"COUNT({t}) = {n}")
p()

# FTS5 探测
fts = con.execute(
    "SELECT name,sql FROM sqlite_master WHERE type='table' AND sql LIKE '%fts5%'"
).fetchall()
p(f"FTS5 虚拟表 = {fts}")
p()

# index 列表
p("=== indexes ===")
for name, tbl, sql in con.execute(
        "SELECT name,tbl_name,sql FROM sqlite_master WHERE type='index'"):
    p(f"{name} on {tbl}: {sql}")
p()

# 样本行
p("=== 样本 datas 行（青眼）===")
for row in con.execute("SELECT * FROM datas WHERE id IN (89631139, 4007, 23545031) LIMIT 3"):
    p(str(row))
p()
p("=== 样本 texts 行 ===")
for row in con.execute("SELECT * FROM texts WHERE id IN (89631139, 4007, 23545031) LIMIT 3"):
    p(str(row)[:600])
p()

# 多语言约定探测：是否存在 cards_*.cdb 兄弟文件
vdir = CDB.parent
p(f"=== {vdir} 目录清单 ===")
for f in sorted(vdir.iterdir()):
    p(f"  {f.name}  {f.stat().st_size/1024/1024:.2f} MB")
p()

con.close()
(OUT / "p0_schema.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
