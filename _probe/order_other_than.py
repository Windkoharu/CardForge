# -*- coding: utf-8 -*-
"""官方卡池实测：「以外的」到底写在数量前还是数量后（决定投影语序）。"""
import sys, io, sqlite3
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from cardforge.pool import official as O

p = O.OfficialPool()
con = p._conn()
print("卡池:", p.count())

QUERIES = [
    ("以外的+1张（排除在数量前）", "%以外的1张%"),
    ("以外的+1只（排除在数量前）", "%以外的1只%"),
    ("以外的+2张/2只", "%以外的2%"),
    ("以外的+N张", "%以外的%张"),
    ("以外的+N只", "%以外的%只"),
    ("1张「…」以外的（数量在前）", "%1张「%」以外的%"),
    ("1只「…」以外的（数量在前）", "%1只「%」以外的%"),
    ("N张「…」以外的（数量在前）", "%张「%」以外的%"),
    ("N只「…」以外的（数量在前）", "%只「%」以外的%"),
    ("这张卡以外的+数量", "%这张卡以外的%只%"),
    ("「A」以外の（日文,数量前）", "%を除く%体%"),
]
for label, pat in QUERIES:
    try:
        n = con.execute("SELECT COUNT(*) FROM texts WHERE desc LIKE ?", (pat,)).fetchone()[0]
    except Exception as e:
        n = f"err {e}"
    print(f"{label:<28} {pat:<28} → {n}")

print("\n=== 实例（排除在数量前，简中）===")
for r in con.execute("SELECT t.id,t.name,substr(t.desc,1,150) FROM texts t WHERE t.desc LIKE '%以外的1只%' LIMIT 6"):
    print(" ·", r[1], "|", r[2].replace("\r", " ").replace("\n", " "))
print("\n=== 实例（数量在排除前，简中）===")
for r in con.execute("SELECT t.id,t.name,substr(t.desc,1,150) FROM texts t WHERE t.desc LIKE '%只「%」以外的%' LIMIT 6"):
    print(" ·", r[1], "|", r[2].replace("\r", " ").replace("\n", " "))
