"""自测 9（附加）：不太好走到但会被 server/cli 用到的分支。

覆盖：cdb 的 ensure_schema 补列 / list_cards / iter_cards / delete_card_row /
read_card 的 str1..16 / export_multilang 的 suffix_map 覆盖 / upsert_card 幂等；
official 的 read / alloc_ids / describe；repo 的 rollback 失败分支 / snapshots 元信息 /
strings.conf 空输入；expansions 的 pack_stats 对不存在的包；ydk 空卡组写读。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
TMP = ROOT / "_probe" / "pool_export" / "_tmp" / "misc"
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True, exist_ok=True)
os.environ["WORKSPACE"] = str(TMP)
sys.path.insert(0, str(ROOT))

from cardforge.core import paths                            # noqa: E402
from cardforge.core.models import CardSpec                  # noqa: E402
from cardforge.export import expansions, strings, ydk       # noqa: E402
from cardforge.pool import cdb as cdbmod                    # noqa: E402
from cardforge.pool import official, repo                   # noqa: E402

OUT = ROOT / "_probe" / "pool_export" / "_out"
lines: list[str] = []
fails: list[str] = []


def p(s: str = "") -> None:
    lines.append(str(s))


def check(label: str, ok: bool, detail: str = "") -> None:
    if not ok:
        fails.append(label)
    p(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  —— {detail}" if detail else ""))


# ══════════════════════════════════════════════════════════════════════
p("── 1. open_cdb / ensure_schema ──")
fresh = TMP / "fresh.cdb"
con = cdbmod.open_cdb(fresh, create=True)
p(f"  open_cdb(create=True) → 文件存在={fresh.is_file()}")
p(f"  datas 列 = {[r[1] for r in con.execute('PRAGMA table_info(datas)')]}")
p(f"  texts 列 = {[r[1] for r in con.execute('PRAGMA table_info(texts)')]}")
check("datas 列与官方一致",
      [r[1] for r in con.execute("PRAGMA table_info(datas)")] == list(cdbmod.DATAS_COLS))
check("texts 列与官方一致",
      [r[1] for r in con.execute("PRAGMA table_info(texts)")] == list(cdbmod.TEXTS_COLS))
check("新建 cdb 卡数 = 0", cdbmod.count_cards(con) == 0)
con.close()

p("  再 open 一次（幂等，不重建）")
con = cdbmod.open_cdb(fresh, create=True)
check("重复 open 不报错且列不变",
      [r[1] for r in con.execute("PRAGMA table_info(texts)")] == list(cdbmod.TEXTS_COLS))
con.close()

try:
    cdbmod.open_cdb(TMP / "不存在.cdb", create=False)
    check("create=False 且文件不存在 → 抛 EnvError", False, "没抛")
except Exception as e:
    check("create=False 且文件不存在 → 抛 EnvError",
          type(e).__name__ == "EnvError", f"{type(e).__name__}: {e}")
try:
    cdbmod.open_cdb_ro(TMP / "不存在.cdb")
    check("open_cdb_ro 对不存在的文件抛 EnvError（不会把它建出来）", False, "没抛")
except Exception as e:
    check("open_cdb_ro 对不存在的文件抛 EnvError（不会把它建出来）",
          type(e).__name__ == "EnvError")
check("确实没被建出来", not (TMP / "不存在.cdb").exists())
p()

p("── 2. ensure_schema 补齐缺列的旧 cdb ──")
broken = TMP / "broken.cdb"
b = sqlite3.connect(str(broken))
b.execute("CREATE TABLE datas (id integer primary key, ot integer, setcode integer)")
b.execute("CREATE TABLE texts (id integer primary key, name text, desc text)")
b.execute("INSERT INTO datas VALUES (1, 3, 4097)")
b.execute("INSERT INTO texts VALUES (1, '老卡', '老卡文')")
b.commit()
b.close()
p(f"  补列前 datas 列 = {[r[1] for r in sqlite3.connect(str(broken)).execute('PRAGMA table_info(datas)')]}")
c2 = cdbmod.open_cdb(broken, create=True)
after_datas = [r[1] for r in c2.execute("PRAGMA table_info(datas)")]
after_texts = [r[1] for r in c2.execute("PRAGMA table_info(texts)")]
p(f"  补列后 datas 列 = {after_datas}")
p(f"  补列后 texts 列 = {after_texts}")
p(f"  官方规范顺序     = {list(cdbmod.DATAS_COLS)}")
check("datas 的列名齐全（顺序可能因 ALTER 追加而不同，EDOPro 按列名取值）",
      set(after_datas) == set(cdbmod.DATAS_COLS) and len(after_datas) == len(cdbmod.DATAS_COLS),
      str(after_datas))
check("texts 的列名齐全", set(after_texts) == set(cdbmod.TEXTS_COLS), str(after_texts))
check("id 仍是第一列且是主键",
      [r[1] for r in c2.execute("PRAGMA table_info(datas)") if r[5]] == ["id"])
kept = c2.execute("SELECT name FROM texts WHERE id=1").fetchone()
check("已有数据没被重建丢掉", kept[0] == "老卡", str(kept))
c2.close()
p()

# ══════════════════════════════════════════════════════════════════════
p("── 3. upsert / read / list / iter / delete ──")
db = TMP / "cards.cdb"
con = cdbmod.open_cdb(db, create=True)
spec = CardSpec(id=210000000, name="幂等测试", frame="effect", attribute="光",
                race="天使族", level=4, atk=1500, dfd=1000, setcode="0x1001",
                text_i18n={"zh_cn": "①：测试。"},
                strings=["①：一", "②：二", "③：三"])
for _ in range(3):
    cdbmod.upsert_card(con, spec)
check("重复 upsert 3 次仍只有 1 行",
      con.execute("SELECT COUNT(*) FROM datas").fetchone()[0] == 1)
check("texts 也只有 1 行", con.execute("SELECT COUNT(*) FROM texts").fetchone()[0] == 1)
rec = cdbmod.read_card(con, 210000000)
p(f"  read_card → { {k: rec[k] for k in ('id','ot','setcode','type','atk','def','level','race','attribute','category','name')} }")
p(f"  desc={rec['desc']!r}  strings={rec['strings'][:4]}")
check("strings 定长 16", len(rec["strings"]) == 16)
check("str1..3 正确", rec["strings"][:3] == ["①：一", "②：二", "③：三"])
check("str4..16 为空", all(s == "" for s in rec["strings"][3:]))
check("read_card 不存在的卡 → None", cdbmod.read_card(con, 1) is None)
lst = cdbmod.list_cards(con)
p(f"  list_cards() = {lst}")
check("list_cards 带 name", lst and lst[0]["name"] == "幂等测试")
check("list_cards(limit=0) 不限", len(cdbmod.list_cards(con, 0)) == 1)
check("list_cards(limit=-1) 也不限", len(cdbmod.list_cards(con, -1)) == 1)
check("iter_cards 能迭代", list(cdbmod.iter_cards(con))[0]["id"] == 210000000)

# 多语言：同一文件里换语言会覆盖（这正是必须分文件的原因）
cdbmod.upsert_card(con, spec, "ja", {"name": "べきとうテスト"})
rec2 = cdbmod.read_card(con, 210000000)
check("同文件换语言会覆盖文本（证明多语言必须分 cdb）",
      rec2["name"] == "べきとうテスト" and rec2["desc"] == "①：测试。",
      f"name={rec2['name']!r}")
cdbmod.upsert_card(con, spec, "zh_cn")

# texts 覆盖参数
cdbmod.upsert_card(con, spec, texts={"name": "覆盖名", "desc": "覆盖文", "str5": "第五"})
rec3 = cdbmod.read_card(con, 210000000)
check("texts 覆盖 name/desc/str5",
      rec3["name"] == "覆盖名" and rec3["desc"] == "覆盖文" and rec3["strings"][4] == "第五",
      f"{rec3['name']!r} {rec3['desc']!r} {rec3['strings'][4]!r}")
check("未覆盖的 str1 保留", rec3["strings"][0] == "①：一")
cdbmod.upsert_card(con, spec)

check("delete_card_row 删得掉", cdbmod.delete_card_row(con, 210000000) is True)
check("删完 count=0", cdbmod.count_cards(con) == 0)
check("删不存在的返回 False", cdbmod.delete_card_row(con, 999) is False)
try:
    cdbmod.upsert_card(con, CardSpec(id=0, name="没编号"))
    check("卡号为 0 → 抛 SpecError", False, "没抛")
except Exception as e:
    check("卡号为 0 → 抛 SpecError", type(e).__name__ == "SpecError",
          f"{type(e).__name__}: {e}")
con.close()
p()

p("── 4. export_multilang：suffix_map 覆盖 + 行数 ──")
specs = [CardSpec(id=210000000 + i, name=f"卡{i}", frame="effect", attribute="光",
                  race="天使族", level=4, atk=1000 + i, dfd=1000,
                  name_i18n={"ja": f"カード{i}", "en": f"Card {i}"},
                  text_i18n={"zh_cn": f"①：中文{i}。", "ja": f"①：日本語{i}。",
                             "en": f"①: English {i}."},
                  setcode="0x1001")
         for i in range(3)]
res = cdbmod.export_multilang(specs, TMP / "ml", name="ML", langs=("zh_cn", "ja", "en"))
p(f"  files = { {k or '(base)': Path(v).name for k, v in res['files'].items()} }")
p(f"  rows  = {res['rows']}")
check("生成 4 个文件（base + 3 语言）", len(res["files"]) == 4, str(res["files"]))
check("每个文件 3 行", all(v == 3 for v in res["rows"].values()), str(res["rows"]))
check("base 用 langs[0] 的文本", Path(res["base"]).is_file())
d = sqlite3.connect(str(TMP / "ml" / "ML-en.cdb"))
check("en 包是英文文本",
      d.execute("SELECT name, desc FROM texts WHERE id=210000001").fetchone()
      == ("Card 1", "①: English 1."),
      str(d.execute("SELECT name FROM texts WHERE id=210000001").fetchone()))
d.close()

res2 = cdbmod.export_multilang(specs, TMP / "ml2", name="ML2", langs=("ja",),
                               suffix_map={"ja": "JP-custom"}, base=False)
p(f"  suffix_map 覆盖 → {[Path(v).name for v in res2['files'].values()]}")
check("suffix_map 生效", (TMP / "ml2" / "ML2-JP-custom.cdb").is_file())
check("base=False 不生成基础包", res2["base"] == ""
      and not (TMP / "ml2" / "ML2.cdb").exists())
try:
    cdbmod.export_multilang(specs, TMP / "ml3", langs=("xx",))
    check("未知语言抛 SpecError", False, "没抛")
except Exception as e:
    check("未知语言抛 SpecError", type(e).__name__ == "SpecError")
p()

# ══════════════════════════════════════════════════════════════════════
p("── 5. official.read / alloc_ids / describe ──")
pool = official.load()
r = pool.read(89631139)
p(f"  official.read(89631139) → keys 数 = {len(r)}  name={r['name']!r} level={r['level']}")
check("read 返回完整 datas+texts", "atk" in r and "desc" in r and r["atk"] == 3000,
      str(r.get("atk")))
check("read 不存在的卡 → None", pool.read(1) is None)
check("alloc_ids(0) = []", pool.alloc_ids(0) == [])
check("alloc_ids 数量正确", len(pool.alloc_ids(5)) == 5)
got = pool.alloc_ids(3, start=89631138)
p(f"  alloc_ids(3, start=89631138) = {got}（89631139 是青眼白龙，其后若干号也被官方占用）")
check("alloc_ids 返回的全部是空位",
      all(not pool.id_taken(i) for i in got) and got == sorted(got)
      and all(i >= 89631138 for i in got), str(got))
check("alloc_ids 跳过了 89631139", 89631139 not in got, str(got))
p(f"  describe() = {pool.describe()}")
check("describe 含 fts",
      pool.describe().get("fts") == "card_fts", str(pool.describe().get("fts")))
check("setcode_used('不是十六进制') 返回 []", pool.setcode_used("zzz") == [])
p()

# ══════════════════════════════════════════════════════════════════════
p("── 6. repo：rollback 失败分支 / snapshots 元信息 ──")
sp = CardSpec(id=210000900, name="回滚测试", frame="effect", attribute="暗",
              race="恶魔族", level=4, atk=1000, dfd=1000)
repo.save_card(sp)
sp.atk = 2000
repo.save_card(sp, note="加强")
snaps = repo.snapshots("cards", "210000900")
p(f"  snapshots = {snaps}")
check("快照含 version/ts/note/digest/path/bytes/file",
      all({"version", "ts", "note", "digest", "path", "bytes", "file"} <= set(s) for s in snaps))
check("两个快照", [s["version"] for s in snaps] == [1, 2])
bad = repo.rollback("cards", "210000900", 99)
p(f"  rollback(version=99) → {bad}")
check("不存在的版本返回 ok=False + 可用版本提示",
      bad["ok"] is False and "99" in bad["error"] and "1" in bad["hint"], str(bad))
bad2 = repo.rollback("nope", "x", 1)
check("未知 kind 返回 ok=False", bad2["ok"] is False, str(bad2))
ok = repo.rollback("cards", "210000900", 2)
check("rollback v2 后 atk = 2000", repo.load_card(210000900).atk == 2000)
check("rollback 追加了 v3", [s["version"] for s in repo.snapshots("cards", "210000900")]
      == [1, 2, 3])
check("snapshots 对不存在的对象返回 []", repo.snapshots("cards", "1") == [])
check("load_card 不存在的卡 → None", repo.load_card(1) is None)
check("delete_card 不存在的卡 → False", repo.delete_card(1) is False)
try:
    repo.save_card(CardSpec(id=0, name="x"))
    check("save_card(卡号 0) → SpecError", False, "没抛")
except Exception as e:
    check("save_card(卡号 0) → SpecError", type(e).__name__ == "SpecError")
try:
    repo.save_archetype(__import__("cardforge.core.models", fromlist=["Archetype"]).Archetype())
    check("save_archetype(空名字) → SpecError", False, "没抛")
except Exception as e:
    check("save_archetype(空名字) → SpecError", type(e).__name__ == "SpecError")
try:
    repo.save_deck(__import__("cardforge.core.models", fromlist=["DeckSpec"]).DeckSpec())
    check("save_deck(空名字) → SpecError", False, "没抛")
except Exception as e:
    check("save_deck(空名字) → SpecError", type(e).__name__ == "SpecError")
check("list_cards 在空工作区返回 []", repo.list_cards("不存在的系列") == [])
check("list_archetypes 在空工作区返回 []", repo.list_archetypes() == [])
check("list_decks 在空工作区返回 []", repo.list_decks() == [])
p()

# ══════════════════════════════════════════════════════════════════════
p("── 7. expansions：空输入 / 不存在的包 ──")
res = expansions.build([], TMP / "empty", name="Empty", langs=("zh_cn",))
p(f"  build([]) → ok={res['ok']}  issues={[i['code'] for i in res['issues']]}")
check("空输入 ok=False 且报 G5_NO_CARDS",
      res["ok"] is False and any(i["code"] == "G5_NO_CARDS" for i in res["issues"]))
iss = expansions.verify(TMP / "根本没有这个包")
p(f"  verify(不存在) → {[(i.code, i.level) for i in iss]}")
check("verify 对不存在的包返回 G5_PACK_MISSING ERROR",
      len(iss) == 1 and iss[0].code == "G5_PACK_MISSING" and iss[0].level == "ERROR")
iss2 = expansions.verify(TMP / "empty")
p(f"  verify(空包) → {[(i.code, i.level) for i in iss2]}")
check("verify 对只有 expansions/ 的包报 G5_CDB_MISSING",
      any(i.code == "G5_CDB_MISSING" for i in iss2), str([i.code for i in iss2]))
p(f"  pack_stats(不存在) = {expansions.pack_stats(TMP / '根本没有这个包')}")
check("pack_stats 对不存在的包返回 ok=False",
      expansions.pack_stats(TMP / "根本没有这个包")["ok"] is False)
p(f"  needs_script 逐卡种：")
for frame in ("normal", "normal_pendulum", "token", "effect", "ritual", "fusion",
              "synchro", "xyz", "link", "pendulum", "spell", "trap", "skill"):
    s = CardSpec(id=1, name="x", frame=frame, level=4, atk=1, dfd=1)
    p(f"    {frame:<18} needs_script={expansions.needs_script(s)!s:<5} "
      f"type_bits=0x{cdbmod.engine_type_bits(s):X}")
check("通常怪/通常灵摆/衍生物不需要脚本",
      not expansions.needs_script(CardSpec(frame="normal"))
      and not expansions.needs_script(CardSpec(frame="normal_pendulum"))
      and not expansions.needs_script(CardSpec(frame="token")))
check("效果怪/魔陷需要脚本",
      expansions.needs_script(CardSpec(frame="effect"))
      and expansions.needs_script(CardSpec(frame="spell")))
p()

p("── 8. ydk：空卡组 / 只有额外 / to_text-from_text 往返 ──")
empty = ydk.from_text("")
check("from_text('') → 三段皆空",
      not empty.main and not empty.extra and not empty.side)
only_extra = ydk.from_text("#main\n#extra\n1\n2\n!side\n")
check("只读 #extra 段", [e.card_id for e in only_extra.extra] == [1, 2]
      and only_extra.main == [])
rt = ydk.from_text(ydk.to_text(only_extra))
check("to_text → from_text 往返", [e.card_id for e in rt.extra] == [1, 2])
check("空 text 的 to_text 仍有三段标记",
      ydk.to_text(empty).splitlines() == ["#created by CardForge 2.0", "#main",
                                         "#extra", "!side"])
p(f"  empty to_text = {ydk.to_text(empty)!r}")
p()

p("── 9. strings：全空输入 ──")
check("render() 只留首行注释", strings.render().splitlines() == ["# CardForge 自动生成 —— DIY 系列名 / 计数器名"],
      repr(strings.render()))
check("render(header='') 无首行", strings.render(header="") == "")
check("parse('') 结构完整",
      set(strings.parse("")) >= {"setnames", "counters", "counters_alias",
                                "unknown", "comments", "lines"})
check("!setname 缺名字也不炸", strings.parse("!setname 0x1")["setnames"] == {"0x1": ""})
check("!counter 缺键也不炸", strings.parse("!counter")["unknown"] == ["!counter"])
p()

p("═" * 68)
p(f"断言：{'全部通过' if not fails else '失败 ' + str(len(fails)) + ' 项'}")
for f in fails:
    p(f"  !! FAIL: {f}")
p("═" * 68)

OUT.joinpath("p7_misc.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
sys.exit(1 if fails else 0)
