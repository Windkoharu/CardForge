"""自测 0b：实测 cdb 的字段约定（灵摆 desc / 连接 def+level / ot / setcode 打包）。"""
from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
CDB = ROOT / "vendor" / "data" / "cards_zh.cdb"
OUT = ROOT / "_probe" / "pool_export" / "_out"
OUT.mkdir(parents=True, exist_ok=True)
lines: list[str] = []
def p(s: str = "") -> None:
    lines.append(str(s))

con = sqlite3.connect("file:" + CDB.as_posix() + "?mode=ro", uri=True)

p("=== ot 取值分布 ===")
for ot, n in con.execute("SELECT ot, COUNT(*) FROM datas GROUP BY ot ORDER BY COUNT(*) DESC"):
    p(f"  ot={ot:<4} (0x{ot:x})  n={n}")

p()
p("=== type & 0x1000000 (PENDULUM) 的卡：desc 结构 ===")
rows = con.execute(
    "SELECT t.id, t.name, t.desc FROM texts t JOIN datas d ON d.id=t.id "
    "WHERE d.type & 0x1000000 LIMIT 3").fetchall()
for rid, name, desc in rows:
    p(f"-- id={rid} name={name}")
    p(f"   repr(desc) = {desc!r}")
    p(f"   含 CRLF={chr(13)+chr(10) in desc}  含 \\n={chr(10) in desc}  含 \\r={chr(13) in desc}")
    p()

p("=== type & 0x4000000 (LINK) 的卡：level/def 字段 ===")
for rid, name, typ, atk, dfn, lvl, race, attr in con.execute(
        "SELECT d.id,t.name,d.type,d.atk,d.def,d.level,d.race,d.attribute FROM datas d "
        "JOIN texts t ON t.id=d.id WHERE d.type & 0x4000000 LIMIT 5"):
    p(f"  id={rid} name={name} type=0x{typ:x} atk={atk} def=0x{dfn:x}({dfn}) level={lvl} "
      f"→ 箭头数={bin(dfn).count('1')}")

p()
p("=== 纯通常怪兽 desc 是否为 flavor ===")
for rid, name, desc in con.execute(
        "SELECT d.id,t.name,t.desc FROM datas d JOIN texts t ON t.id=d.id "
        "WHERE d.type=0x11 LIMIT 3"):
    p(f"  id={rid} {name}: {desc!r}")

p()
p("=== desc 换行符统计 ===")
c = Counter()
for (desc,) in con.execute("SELECT desc FROM texts"):
    d = desc or ""
    if "\r\n" in d:
        c["CRLF"] += 1
    elif "\n" in d:
        c["LF-only"] += 1
    else:
        c["none"] += 1
p(f"  {dict(c)}")

p()
p("=== setcode 打包实测（前 8 个非 0）===")
for rid, name, sc in con.execute(
        "SELECT d.id,t.name,d.setcode FROM datas d JOIN texts t ON t.id=d.id "
        "WHERE d.setcode!=0 LIMIT 8"):
    parts = [(sc >> (16 * i)) & 0xFFFF for i in range(4)]
    p(f"  id={rid} {name}: setcode={sc} (0x{sc:08X}) → 槽位 {[hex(x) for x in parts]}")

p()
p("=== 检索实测：LIKE vs FTS5 MATCH ===")
for q in ("星奏", "青眼", "青眼白龙", "水精鳞"):
    nm = con.execute("SELECT COUNT(*) FROM texts WHERE name LIKE ?", (f"%{q}%",)).fetchone()[0]
    dc = con.execute("SELECT COUNT(*) FROM texts WHERE desc LIKE ?", (f"%{q}%",)).fetchone()[0]
    try:
        ft = con.execute("SELECT COUNT(*) FROM card_fts WHERE card_fts MATCH ?", (q,)).fetchone()[0]
    except Exception as e:
        ft = f"ERR {e}"
    # 引号短语
    try:
        ft2 = con.execute('SELECT COUNT(*) FROM card_fts WHERE card_fts MATCH ?',
                          (f'"{q}"',)).fetchone()[0]
    except Exception as e:
        ft2 = f"ERR {e}"
    p(f"  q={q!r:<12} name_LIKE={nm:<5} desc_LIKE={dc:<5} FTS_MATCH={ft} FTS_phrase={ft2}")

p()
p("=== FTS5 索引行数 ===")
p(f"  card_fts count = {con.execute('SELECT COUNT(*) FROM card_fts').fetchone()[0]}")

p()
p("=== id 范围 ===")
mn, mx, n = con.execute("SELECT MIN(id),MAX(id),COUNT(*) FROM datas").fetchone()
p(f"  min={mn} max={mx} n={n}")
p(f"  id >= 210000000 的数量 = {con.execute('SELECT COUNT(*) FROM datas WHERE id>=210000000').fetchone()[0]}")
p(f"  id >= 200000000 的 id 列表 = {[r[0] for r in con.execute('SELECT id FROM datas WHERE id>=200000000 ORDER BY id LIMIT 20')]}")

con.close()
OUT.joinpath("p0b_conventions.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
