"""探针：灵摆卡 level 列的打包编码（含左右刻度不对称的卡，确定高位顺序）。"""
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

p("=== 全部灵摆卡的 level 列解码（前 20 张）＋ desc 头对照 ===")
rows = con.execute(
    "SELECT d.id,t.name,d.level,t.desc FROM datas d JOIN texts t ON t.id=d.id "
    "WHERE d.type & 0x1000000 ORDER BY d.id").fetchall()
p(f"  灵摆卡总数 = {len(rows)}")
asym = []
for rid, name, lvl, desc in rows:
    b3, b2, lo = (lvl >> 24) & 0xFF, (lvl >> 16) & 0xFF, lvl & 0xFFFF
    head = (desc or "").split("\r\n")[0]
    if b3 != b2:
        asym.append((rid, name, lvl, b3, b2, lo, head))
p(f"  左右刻度不对称（byte3 != byte2）的卡数 = {len(asym)}")
p()
p("  ── 不对称样本（用 desc 的 ←L 【灵摆】 R→ 反推高低位顺序）──")
for rid, name, lvl, b3, b2, lo, head in asym[:12]:
    p(f"    id={rid:<9} level列=0x{lvl:08X}  byte3={b3} byte2={b2} low16={lo}  "
      f"desc头={head!r}")
    p(f"        name={name}")

p()
p("  ── 对称样本前 8 张 ──")
sym = [r for r in rows if ((r[2] >> 24) & 0xFF) == ((r[2] >> 16) & 0xFF)]
for rid, name, lvl, desc in sym[:8]:
    b3, lo = (lvl >> 24) & 0xFF, lvl & 0xFFFF
    head = (desc or "").split("\r\n")[0]
    p(f"    id={rid:<9} level列=0x{lvl:08X} (scale={b3}, level={lo})  desc头={head!r}  {name}")

p()
p("=== 一致性校验：byte3/byte2 是否等于 desc 里的 ←L / R→ ===")
import re
ok3 = ok2 = total = 0
for rid, name, lvl, desc in rows:
    m = re.match(r"←(\d+) 【灵摆】 (\d+)→", (desc or "").split("\r\n")[0])
    if not m:
        continue
    L, R = int(m.group(1)), int(m.group(2))
    b3, b2 = (lvl >> 24) & 0xFF, (lvl >> 16) & 0xFF
    total += 1
    ok3 += (b3 == L)
    ok2 += (b2 == R)
p(f"  可解析 desc 头的卡 = {total}")
p(f"  (level>>24)&0xFF == desc 左侧刻度 ←L 的卡数 = {ok3}")
p(f"  (level>>16)&0xFF == desc 右侧刻度 R→ 的卡数 = {ok2}")
p(f"  → 结论：level 列 = (lscale<<24)|(rscale<<16)|(level or rank)"
  if ok3 == total and ok2 == total else
  f"  → 结论：需要人工判断（{ok3}/{total} 与 {ok2}/{total}）")

p()
p("=== 非灵摆怪兽的 level 列（确认没有被打包）===")
for rid, name, lvl, typ in con.execute(
        "SELECT d.id,t.name,d.level,d.type FROM datas d JOIN texts t ON t.id=d.id "
        "WHERE (d.type & 0x1) AND NOT (d.type & 0x1000000) AND d.level > 12 LIMIT 6"):
    p(f"    id={rid:<9} level列={lvl} type=0x{typ:X} {name}")
p(f"  非灵摆怪兽里 level>12 的数量 = "
  f"{con.execute('SELECT COUNT(*) FROM datas WHERE (type & 0x1) AND NOT (type & 0x1000000) AND level>12').fetchone()[0]}")
p(f"  非灵摆怪兽 level 最大值 = "
  f"{con.execute('SELECT MAX(level) FROM datas WHERE (type & 0x1) AND NOT (type & 0x1000000)').fetchone()[0]}")

p()
p("=== XYZ 灵摆（rank 在低 16 位吗）===")
for rid, name, lvl, desc in con.execute(
        "SELECT d.id,t.name,d.level,t.desc FROM datas d JOIN texts t ON t.id=d.id "
        "WHERE (d.type & 0x800000) AND (d.type & 0x1000000) LIMIT 5"):
    p(f"    id={rid:<9} level列=0x{lvl:08X} scale={(lvl>>24)&0xFF} rank={lvl & 0xFFFF} {name}")
    p(f"        desc头={(desc or '').split(chr(13)+chr(10))[0]!r}")

con.close()
OUT.joinpath("p0e_pendulum_pack.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
