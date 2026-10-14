"""探针：core.FRAMES 的 base 怪相 + 灵摆刻度到底存在 cdb 的哪一列。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
sys.path.insert(0, str(ROOT))
from cardforge.core.enums import FRAMES                      # noqa: E402
from cardforge.core.models import CardSpec                   # noqa: E402

OUT = ROOT / "_probe" / "pool_export" / "_out"
OUT.mkdir(parents=True, exist_ok=True)
lines: list[str] = []
def p(s: str = "") -> None:
    lines.append(str(s))

p("=== FRAMES[*].base 实测 ===")
for k, f in FRAMES.items():
    p(f"  {k:<18} base={f.base:<9} is_monster={f.is_monster!s:<5} "
      f"has_level={f.has_level!s:<5} has_def={f.has_def!s:<5} extra={f.extra_deck}")

p()
p("=== CardSpec.type_bits 实测 ===")
for frame in ("normal", "effect", "normal_pendulum", "pendulum", "link"):
    s = CardSpec(id=1, name="x", frame=frame, level=4, atk=100, dfd=100)
    p(f"  frame={frame:<18} frame_def.base={s.frame_def.base:<9} "
      f"type_bits=0x{s.type_bits:X}  is_monster={s.is_monster}  is_pendulum={s.is_pendulum}")
p("  → 通常怪兽期望 0x11(MONSTER|NORMAL)，实测 0x21(MONSTER|EFFECT)："
  "FRAMES['normal'].base 是 'effect'，疑似 core/enums.py 漏写 base='normal'")

p()
p("=== 灵摆刻度在 cdb 的哪一列？（对比 desc 里的 ←N 与各列）===")
CDB = ROOT / "vendor" / "data" / "cards_zh.cdb"
con = sqlite3.connect("file:" + CDB.as_posix() + "?mode=ro", uri=True)
rows = con.execute(
    "SELECT d.id,t.name,d.level,d.atk,d.def,d.race,d.attribute,t.desc "
    "FROM datas d JOIN texts t ON t.id=d.id WHERE d.type & 0x1000000 LIMIT 12").fetchall()
for rid, name, lvl, atk, dfn, race, attr, desc in rows:
    head = (desc or "").split("\r\n")[0]
    p(f"  id={rid:<9} level列={lvl:<3} desc头={head!r:<26} name={name}")
con.close()
p()
p("  → 若 level 列 != desc 里的刻度，说明 cdb 不存刻度（刻度由 Lua/客户端处理）；")
p("    若 level 列 == 刻度，说明 level 列存的是刻度。")

OUT.joinpath("p0d_frames_scale.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
