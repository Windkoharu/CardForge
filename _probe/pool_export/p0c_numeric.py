"""自测 0c：atk/def 的 '?' 编码、str1..16 使用率、魔陷行、两表一致性。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
CDB = ROOT / "vendor" / "data" / "cards_zh.cdb"
OUT = ROOT / "_probe" / "pool_export" / "_out"
OUT.mkdir(parents=True, exist_ok=True)
lines: list[str] = []
def p(s: str = "") -> None:
    lines.append(str(s))

con = sqlite3.connect("file:" + CDB.as_posix() + "?mode=ro", uri=True)

p("=== atk/def 负值（'?' 编码候选）===")
for col in ("atk", "def"):
    rows = con.execute(
        f"SELECT {col}, COUNT(*) FROM datas WHERE {col}<0 GROUP BY {col} ORDER BY COUNT(*) DESC").fetchall()
    p(f"  datas.{col} < 0 : {rows}")
    for rid, name, atk, dfn in con.execute(
            f"SELECT d.id,t.name,d.atk,d.def FROM datas d JOIN texts t ON t.id=d.id "
            f"WHERE d.{col}<0 LIMIT 4"):
        p(f"    id={rid} {name}: atk={atk} def={dfn}")
p(f"  atk 为 NULL 的数量 = {con.execute('SELECT COUNT(*) FROM datas WHERE atk IS NULL').fetchone()[0]}")
p(f"  def 为 NULL 的数量 = {con.execute('SELECT COUNT(*) FROM datas WHERE def IS NULL').fetchone()[0]}")

p()
p("=== 魔陷的 datas 行样本 ===")
for rid, name, typ, atk, dfn, lvl, race, attr, cat in con.execute(
        "SELECT d.id,t.name,d.type,d.atk,d.def,d.level,d.race,d.attribute,d.category "
        "FROM datas d JOIN texts t ON t.id=d.id WHERE d.type & 0x2 LIMIT 2"):
    p(f"  id={rid} {name}: type=0x{typ:x} atk={atk} def={dfn} level={lvl} race={race} attr={attr} cat={cat}")
for rid, name, typ, atk, dfn in con.execute(
        "SELECT d.id,t.name,d.type,d.atk,d.def FROM datas d JOIN texts t ON t.id=d.id "
        "WHERE d.type & 0x4 LIMIT 2"):
    p(f"  id={rid} {name}: type=0x{typ:x} atk={atk} def={dfn}")

p()
p("=== texts.str1..str16 使用率 ===")
tot = con.execute("SELECT COUNT(*) FROM texts").fetchone()[0]
for i in range(1, 17):
    n = con.execute(f"SELECT COUNT(*) FROM texts WHERE str{i} IS NOT NULL AND str{i}!=''").fetchone()[0]
    p(f"  str{i:<3} 非空 = {n} / {tot}")

p()
p("=== 两表一致性 ===")
p(f"  datas 无 texts: {con.execute('SELECT COUNT(*) FROM datas d LEFT JOIN texts t ON t.id=d.id WHERE t.id IS NULL').fetchone()[0]}")
p(f"  texts 无 datas: {con.execute('SELECT COUNT(*) FROM texts t LEFT JOIN datas d ON d.id=t.id WHERE d.id IS NULL').fetchone()[0]}")

p()
p("=== 字段查重实测（archetype_hits 语义）===")
for f in ("星奏", "青眼", "焰刃", "水精鳞", "Cipher", "密码"):
    nm = [r[0] for r in con.execute("SELECT id FROM texts WHERE name LIKE ?", (f"%{f}%",))]
    dc = [r[0] for r in con.execute("SELECT id FROM texts WHERE desc LIKE ?", (f"%{f}%",))]
    fts = []
    try:
        fts = [r[0] for r in con.execute(
            "SELECT rowid FROM card_fts WHERE card_fts MATCH ?", (f'"{f}"',))]
    except Exception as e:
        p(f"    FTS err {e}")
    p(f"  field={f!r:<10} name={len(nm):<4} desc={len(dc):<4} union={len(set(nm)|set(dc)):<4} "
      f"FTS={len(fts)}  FTS⊆LIKE? {set(fts) <= set(nm)|set(dc)}")

con.close()
OUT.joinpath("p0c_numeric.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
