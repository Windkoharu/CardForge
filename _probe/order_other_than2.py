# -*- coding: utf-8 -*-
"""官方卡池实测（第二轮）：排除短语在各句式槽位里的位置。"""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from cardforge.pool import official as O

con = O.OfficialPool()._conn()

Q = [
    ("把「A」以外的1只（把字句·排除在前）", "%把「%」以外的1只%"),
    ("把1只「A」以外的（把字句·数量在前）", "%把1只「%」以外的%"),
    ("把「A」以外的1张", "%把「%」以外的1张%"),
    ("把1张「A」以外的", "%把1张「%」以外的%"),
    ("选「A」以外的1只（选字句·排除在前）", "%选「%」以外的1只%"),
    ("选1只「A」以外的（选字句·数量在前）", "%选1只「%」以外的%"),
    ("选「A」以外的1张", "%选「%」以外的1张%"),
    ("选1张「A」以外的", "%选1张「%」以外的%"),
    ("以「A」以外的自己…（取对象·排除在前）", "%以「%」以外的自己%"),
    ("以…1只「A」以外的…（取对象·数量在前）", "%以%1只「%」以外的%"),
    ("老写法「（这张卡除外）」", "%（这张卡除外）%"),
    ("老写法「（自己场上的这张卡除外）」", "%这张卡除外%"),
    ("从自己墓地把「A」以外的", "%从自己墓地把「%」以外的%"),
    ("从自己墓地选「A」以外的", "%从自己墓地选「%」以外的%"),
    ("从自己墓地选1只「A」以外的", "%从自己墓地选1只「%」以外的%"),
]
for label, pat in Q:
    n = con.execute("SELECT COUNT(*) FROM texts WHERE desc LIKE ?", (pat,)).fetchone()[0]
    print(f"{n:>5}  {label}")

print("\n=== 「从自己墓地/卡组…以外的…」实例 ===")
for r in con.execute("SELECT name,substr(desc,1,120) FROM texts WHERE desc LIKE '%从自己墓地选%' AND desc LIKE '%以外的%' LIMIT 8"):
    print(" ·", r[0], "|", (r[1] or "").replace("\r", " ").replace("\n", " "))
print("\n=== 取对象里的排除写法实例 ===")
for r in con.execute("SELECT name,substr(desc,1,120) FROM texts WHERE desc LIKE '%以「%」以外的自%' LIMIT 6"):
    print(" ·", r[0], "|", (r[1] or "").replace("\r", " ").replace("\n", " "))
