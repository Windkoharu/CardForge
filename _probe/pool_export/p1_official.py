"""自测 1：官方卡池只读查询（真实数据 vendor/data/cards_zh.cdb）。

覆盖：PRAGMA 真实 schema / 总卡数 / FTS5 与 LIKE 检索 / 字段查重 /
next_free_id / setcode_used / 只读性证明（文件哈希前后一致 + 写语句被拒）。
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
sys.path.insert(0, str(ROOT))

from cardforge.core import paths                       # noqa: E402
from cardforge.pool import official                    # noqa: E402

OUT = ROOT / "_probe" / "pool_export" / "_out"
OUT.mkdir(parents=True, exist_ok=True)
lines: list[str] = []
def p(s: str = "") -> None:
    lines.append(str(s))

CDB = Path(paths.OFFICIAL_CDB) / "cards_zh.cdb"
p(f"官方卡池 = {CDB}")
p(f"存在 = {CDB.is_file()}  大小 = {CDB.stat().st_size / 1048576:.2f} MB")
sha_before = hashlib.sha256(CDB.read_bytes()).hexdigest()
p(f"查询前 sha256 = {sha_before[:32]}…")
p()

# ── 1. 真实 schema ───────────────────────────────────────────────────
raw = sqlite3.connect("file:" + CDB.as_posix() + "?mode=ro", uri=True)
for t in ("datas", "texts"):
    p(f"PRAGMA table_info({t}):")
    p(f"  {'cid':>3} {'name':<10} {'type':<8} {'notnull':>7} {'pk':>3}")
    for cid, name, ctype, notnull, dflt, pk in raw.execute(f"PRAGMA table_info({t})"):
        p(f"  {cid:>3} {name:<10} {ctype:<8} {notnull:>7} {pk:>3}")
    n = raw.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    p(f"  → COUNT(*) = {n}")
p(f"sqlite_master 里的表 = {[r[0] for r in raw.execute(chr(83)+'ELECT name FROM sqlite_master WHERE type=%s' % chr(39)+'table'+chr(39))]}")
fts_sql = raw.execute("SELECT sql FROM sqlite_master WHERE name='card_fts'").fetchone()
p(f"FTS5 虚拟表 = {fts_sql[0] if fts_sql else '（无）'}")
raw.close()
p()

# ── 2. OfficialPool ─────────────────────────────────────────────────
pool = official.load()
p(f"pool.path      = {pool.path}")
p(f"pool.available = {pool.available}")
p(f"pool.count()   = {pool.count()}")
p(f"检测到的 FTS5 表 = {pool._fts_table()!r}")
p(f"warnings       = {pool.warnings}")
p()

p("── search('星奏') ──")
hits = pool.search("星奏", limit=5)
p(f"  返回 {len(hits)} 条  →  {hits}")
p("── search('青眼') ──")
hits2 = pool.search("青眼", limit=5)
p(f"  返回 {len(hits2)} 条")
for h in hits2:
    p(f"    id={h['id']} name={h['name']} matched={h['matched']} atk={h['atk']} def={h['def']}")
p("── search('水精鳞', limit=3) ──")
for h in pool.search("水精鳞", limit=3):
    p(f"    id={h['id']} name={h['name']} matched={h['matched']}")
p()

p("── 对照：FTS5 / LIKE 各自命中数（证明 FTS 是 token 精确、LIKE 是子串）──")
con = pool._conn()
for q in ("星奏", "青眼", "青眼白龙", "水精鳞", "密码"):
    nm = con.execute("SELECT COUNT(*) FROM texts WHERE name LIKE ?", (f"%{q}%",)).fetchone()[0]
    dc = con.execute("SELECT COUNT(*) FROM texts WHERE desc LIKE ?", (f"%{q}%",)).fetchone()[0]
    ft = con.execute("SELECT COUNT(*) FROM card_fts WHERE card_fts MATCH ?",
                     (f'"{q}"',)).fetchone()[0]
    p(f"  q={q!r:<12} name_LIKE={nm:<4} desc_LIKE={dc:<4} FTS_MATCH={ft:<4} "
      f"→ search() 返回 {len(pool.search(q, limit=50))} 条（并集）")
p()

# ── 3. 字段查重 ──────────────────────────────────────────────────────
p("── archetype_hits（字段名查重）──")
for field in ("星奏", "青眼", "焰刃", "水精鳞", "Cipher"):
    hs = pool.archetype_hits(field, limit=3)
    p(f"  field={field!r:<10} 命中 {len(hs)} 条")
    for h in hs[:3]:
        p(f"      id={h['id']} where={h['where']} name={h['name']}")
        p(f"        excerpt={h.get('excerpt','')[:70]}")
p()

# ── 4. 卡号 ──────────────────────────────────────────────────────────
p("── 卡号 ──")
p(f"  all_ids()          = {len(pool.all_ids())} 个")
p(f"  id_taken(89631139) = {pool.id_taken(89631139)}   # 青眼白龙（官方）")
p(f"  id_taken(210000000)= {pool.id_taken(210000000)}  # DIY 起始号")
p(f"  next_free_id()               = {pool.next_free_id()}")
p(f"  next_free_id(483)            = {pool.next_free_id(483)}   # 483 是官方最小 id")
p(f"  alloc_ids(3)                 = {pool.alloc_ids(3)}")
p(f"  alloc_ids(3, start=99995595) = {pool.alloc_ids(3, start=99995595)}  # 官方最大 id 附近")
p()

# ── 5. setcode ───────────────────────────────────────────────────────
p("── setcode_used（逐槽位打包匹配）──")
for sc in ("0x1001", "0x74", "0xDD", "0x6E"):
    used = pool.setcode_used(sc)
    p(f"  setcode={sc:<8} 官方占用 {len(used)} 张" +
      (f"  例：{[u['name'] for u in used[:3]]}" if used else ""))
p(f"  setcode_used('0x0') = {pool.setcode_used('0x0')}   # 0 视为未使用")
p()

# ── 6. name_exists / text_of ─────────────────────────────────────────
p("── name_exists / text_of ──")
ne = pool.name_exists("青眼白龙")
p(f"  name_exists('青眼白龙') = id={ne['id']} name={ne['name']}")
p(f"  name_exists('星奏·艾莉娅') = {pool.name_exists('星奏·艾莉娅')}")
t = pool.text_of(89631139)
p(f"  text_of(89631139) = name={t['name']!r} desc={t['desc']!r} "
  f"strings 非空数={sum(1 for s in t['strings'] if s)}")
p()

# ── 7. 只读性证明 ────────────────────────────────────────────────────
p("── 只读性证明 ──")
try:
    con.execute("INSERT INTO datas (id) VALUES (1)")
    p("  !! 写语句竟然成功了 —— 只读保证失效")
except sqlite3.Error as e:
    p(f"  写语句被拒：{type(e).__name__}: {e}")
try:
    pool._con.execute("DELETE FROM texts WHERE id=89631139")
    p("  !! DELETE 竟然成功了 —— 只读保证失效")
except sqlite3.Error as e:
    p(f"  DELETE 被拒：{type(e).__name__}: {e}")
pool.close()
sha_after = hashlib.sha256(CDB.read_bytes()).hexdigest()
p(f"查询后 sha256 = {sha_after[:32]}…")
p(f"文件未被改动 = {sha_before == sha_after}")
p()

# ── 8. 缺失卡池时的降级 ──────────────────────────────────────────────
p("── 卡池缺失时的降级（不抛异常）──")
missing = official.load(CDB.parent / "不存在的卡池.cdb")
p(f"  available = {missing.available}")
p(f"  count     = {missing.count()}")
p(f"  search    = {missing.search('青眼')}")
p(f"  hits      = {missing.archetype_hits('青眼')}")
p(f"  next_free = {missing.next_free_id()}")
p(f"  setcode   = {missing.setcode_used('0x1001')}")
p(f"  text_of   = {missing.text_of(89631139)}")
p(f"  id_taken  = {missing.id_taken(89631139)}")
p(f"  warnings  = {missing.warnings}")
p(f"  describe  = {missing.describe()}")

p()
p(f"describe() = {pool.describe()}")

OUT.joinpath("p1_official.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
