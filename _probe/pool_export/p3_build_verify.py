"""自测 3/4/5：export.build() 打真包 → verify() 自检 → **独立 sqlite3 读回** → BOM 检查。

覆盖：
  3. build() 一个真包（多语言 + 卡图 + 脚本 + strings.conf + README + manifest），
     打印文件树与 verify 的 Issue 列表（应无 ERROR）。
  4. 用**标准库 sqlite3**（不走本项目代码）SELECT 出卡，断言 name/desc/atk/def/type/
     race/attribute 与 CardSpec 一致 —— 这是「别的程序能不能读到我们写的卡」的关键验证。
     另含连接怪兽 def=箭头掩码、level=连接数、灵摆 desc 版式、通常怪 flavor 的断言。
  5. 断言所有生成的 .lua 前 3 字节不是 EF BB BF；并人为注入一个带 BOM 的脚本，
     证明 verify() 真的会报 ERROR。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
TMP = ROOT / "_probe" / "pool_export" / "_tmp" / "ws_build"
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True, exist_ok=True)
os.environ["WORKSPACE"] = str(TMP)
sys.path.insert(0, str(ROOT))

from cardforge.core import constants as C                      # noqa: E402
from cardforge.core import paths                               # noqa: E402
from cardforge.core.models import CardSpec, EffectSpec         # noqa: E402
from cardforge.export import expansions                        # noqa: E402
from cardforge.pool import cdb as cdbmod                       # noqa: E402
from cardforge.pool.official import load as load_official      # noqa: E402

OUT = ROOT / "_probe" / "pool_export" / "_out"
OUT.mkdir(parents=True, exist_ok=True)
lines: list[str] = []
fails: list[str] = []


def p(s: str = "") -> None:
    lines.append(str(s))


def check(label: str, ok: bool, detail: str = "") -> None:
    if not ok:
        fails.append(label)
    p(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  —— {detail}" if detail else ""))


LUA_EFF = ("--[[ 焰刃的见习剑士 ]]\nlocal s,id=GetID()\n"
           "function s.initial_effect(c)\n\tlocal e1=Effect.CreateEffect(c)\n"
           "\te1:SetDescription(aux.Stringid(id,0))\n\tc:RegisterEffect(e1)\nend\n")
LUA_LINK = "--[[ 星奏的连接兽 ]]\nlocal s,id=GetID()\nfunction s.initial_effect(c)\nend\n"

p(f"临时 WORKSPACE = {TMP}")
p()

# ── 准备卡图（一张正确尺寸、一张错误尺寸、其余缺图）──────────────────
try:
    from PIL import Image
    paths.ensure_dirs()
    (paths.PICS / "field").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (421, 614), (40, 60, 90)).save(paths.pic_path(210000000), "JPEG", quality=90)
    Image.new("RGB", (400, 600), (90, 40, 60)).save(paths.pic_path(210000001), "JPEG", quality=90)
    Image.new("RGB", (512, 512), (30, 90, 60)).save(paths.field_pic_path(210000002), "JPEG", quality=90)
    pics_ready = True
    p(f"已造卡图：{paths.rel(paths.pic_path(210000000))} 421×614（正确）")
    p(f"          {paths.rel(paths.pic_path(210000001))} 400×600（错误，用于触发 WARN）")
    p(f"          {paths.rel(paths.field_pic_path(210000002))} 512×512（场地背景）")
except Exception as e:                                     # pragma: no cover
    pics_ready = False
    p(f"Pillow 不可用，跳过卡图准备：{e}")
p()

# ── 造 5 张卡 ────────────────────────────────────────────────────────
cards = [
    CardSpec(
        id=210000000, name="焰刃的见习剑士", name_i18n={"ja": "焔刃の見習い剣士"},
        frame="effect", attribute="炎", race="战士族", level=4, atk=1700, dfd=1000,
        archetype="焰刃", setcode="0x3001",
        text_i18n={"zh_cn": "①：这张卡召唤成功时才能发动。从卡组把1张「焰刃」卡加入手卡。"
                            "这个效果1回合只能使用1次。",
                   "ja": "①：このカードが召喚に成功した時に発動できる。"
                         "デッキから「焔刃」カード1枚を手札に加える。"},
        strings=["①：从卡组把1张「焰刃」卡加入手卡。"],
        effects=[EffectSpec(kind="search", trigger="NORMAL_SUMMON_SUCCESS")],
        lua=LUA_EFF,
    ),
    CardSpec(
        id=210000001, name="星奏的指挥者 艾莉娅", name_i18n={"ja": "星奏の指揮者アリア"},
        frame="pendulum", attribute="光", race="魔法师族", level=4, atk=1600, dfd=1200,
        pendulum_scale=8, archetype="星奏", setcode="0x1001",
        text_i18n={"zh_cn": "①：这张卡召唤成功时才能发动。从卡组把1张「星奏」卡加入手卡。",
                   "ja": "①：このカードが召喚に成功した時に発動できる。"},
        pendulum_text_i18n={"zh_cn": "①：自己主要阶段才能发动。从卡组把1只「星奏」怪兽加入手卡。",
                            "ja": "①：自分メインフェイズに発動できる。"},
        strings=["①：从卡组把1张「星奏」卡加入手卡。", "灵摆效果"],
        lua="--[[ 星奏的指挥者 ]]\nlocal s,id=GetID()\n",
    ),
    CardSpec(
        id=210000002, name="星奏的圆舞曲", name_i18n={"ja": "星奏のワルツ"},
        frame="spell", spell_kind="field", archetype="星奏", setcode="0x1001",
        text_i18n={"zh_cn": "①：作为这张卡发动时的效果处理，从卡组把1只「星奏」怪兽加入手卡。",
                   "ja": "①：このカードの発動時の効果処理として、デッキから「星奏」モンスター1体を手札に加える。"},
        strings=["①：从卡组把1只「星奏」怪兽加入手卡。"],
        # 故意不给 lua → verify 应报 G5_SCRIPT_MISSING（WARN，非 ERROR）
    ),
    CardSpec(
        id=210000003, name="星奏的连接兽", frame="link", attribute="光", race="魔法师族",
        level=3, atk=2400, link_markers=["左下", "下", "右下"], archetype="星奏",
        setcode="0x1001",
        text_i18n={"zh_cn": "「星奏」怪兽2只以上\n①：这张卡连接召唤成功时才能发动。抽1张卡。"},
        lua=LUA_LINK,
    ),
    CardSpec(
        id=210000004, name="古老的奏者", frame="normal", attribute="地", race="岩石族",
        level=3, atk=800, dfd=1800, flavor="在废墟里弹奏无声竖琴的石头人。",
        # 通常怪兽不需要脚本
    ),
]
p("── 造的卡 ──")
for s in cards:
    p(f"  {s.id} {s.name:<18} frame={s.frame:<9} type_bits=0x{s.type_bits:<9X} "
      f"def_value={s.def_value:<5} level={s.effective_level} 需要脚本={expansions.needs_script(s)}")
p()

# ══════════════════════════════════════════════════════════════════════
#  3. build
# ══════════════════════════════════════════════════════════════════════
p("── 3. expansions.build() ──")
PACK = TMP / "out"
stats = expansions.build(
    cards, PACK, name="CardForge", langs=("zh_cn", "ja"), copy_pics=True,
    setnames={0x1001: "星奏", 0x3001: "焰刃"},
    counters={0x1: "星奏指示物"},
)
p(f"  ok            = {stats['ok']}")
p(f"  pack_dir      = {paths.rel(Path(stats['pack_dir']))}")
p(f"  expansions    = {paths.rel(Path(stats['expansions_dir']))}")
p(f"  n_cards       = {stats['n_cards']}")
p(f"  cdbs          = { {k or '(base)': Path(v).name for k, v in stats['cdbs'].items()} }")
p(f"  langs         = {stats['langs']}")
p(f"  n_pics        = {stats['n_pics']}   n_field_pics = {stats['n_field_pics']}   "
  f"n_scripts = {stats['n_scripts']}")
p(f"  pending_pics  = {stats['pending_pics']}")
p(f"  strings_conf  = {Path(stats['strings_conf']).name if stats['strings_conf'] else '（无）'}")
p(f"  manifest      = {Path(stats['manifest']).name if stats['manifest'] else '（无）'}")
p(f"  readme        = {[Path(x).name for x in stats['readme']]}")
p(f"  skipped({len(stats['skipped'])})  = ")
for it in stats["skipped"]:
    p(f"      {it}")
p(f"  build issues({len(stats['issues'])}) = ")
for it in stats["issues"]:
    p(f"      [{it['level']}] {it['code']}: {it['message']}")
p()

p("── 包内文件树 ──")
for ln in expansions.file_tree(PACK):
    p(f"  {ln}")
p()

# ══════════════════════════════════════════════════════════════════════
#  4. 独立 sqlite3 读回（关键验证）
# ══════════════════════════════════════════════════════════════════════
p("── 4. 用标准库 sqlite3 独立读回生成的 cdb ──")
EXP = Path(stats["expansions_dir"])
base_cdb = EXP / "CardForge.cdb"
p(f"  cdb = {paths.rel(base_cdb)}  ({base_cdb.stat().st_size} 字节)")
con = sqlite3.connect(str(base_cdb))            # 注意：普通 connect，完全不经过本项目代码
p(f"  sqlite_master = {[r[0] for r in con.execute(chr(83)+'ELECT name FROM sqlite_master ORDER BY name')]}")
p(f"  PRAGMA table_info(datas) 列 = {[r[1] for r in con.execute('PRAGMA table_info(datas)')]}")
p(f"  PRAGMA table_info(texts) 列 = {[r[1] for r in con.execute('PRAGMA table_info(texts)')]}")
p(f"  表内卡数 datas={con.execute('SELECT COUNT(*) FROM datas').fetchone()[0]} "
  f"texts={con.execute('SELECT COUNT(*) FROM texts').fetchone()[0]}")
p()

for spec in cards:
    row = con.execute(
        "SELECT d.id,d.ot,d.alias,d.setcode,d.type,d.atk,d.def,d.level,d.race,"
        "d.attribute,d.category,t.name,t.desc,t.str1 "
        "FROM datas d JOIN texts t ON t.id=d.id WHERE d.id=?", (spec.id,)).fetchone()
    check(f"{spec.id} 在 cdb 里有记录", row is not None)
    if row is None:
        continue
    (cid, ot, alias, setcode, type_, atk, dfn, level, race, attr, cat,
     name, desc, str1) = row
    p(f"  ── {cid} {name} ──")
    p(f"     ot={ot} alias={alias} setcode=0x{setcode:X} type=0x{type_:X} "
      f"atk={atk} def={dfn} level={level} race=0x{race:X} attribute=0x{attr:X} category={cat}")
    exp_atk = spec.atk
    exp_def = spec.def_value
    exp_type = cdbmod.engine_type_bits(spec)
    exp_level = cdbmod.level_column(spec)
    if not spec.is_monster:
        exp_atk = exp_def = exp_level = 0
    check(f"  {cid} name 一致", name == spec.name, f"{name!r} vs {spec.name!r}")
    check(f"  {cid} desc 一致（cdb.card_desc 推导）",
          desc == cdbmod.card_desc(spec, "zh_cn"),
          f"{desc[:40]!r} vs {cdbmod.card_desc(spec, 'zh_cn')[:40]!r}")
    check(f"  {cid} atk 一致", atk == exp_atk, f"{atk} vs {exp_atk}")
    check(f"  {cid} def 一致", dfn == exp_def, f"{dfn} vs {exp_def}")
    check(f"  {cid} type 一致（engine_type_bits，通常怪已修正为 0x11）",
          type_ == exp_type, f"0x{type_:X} vs 0x{exp_type:X}")
    check(f"  {cid} level 列一致（灵摆为刻度打包）",
          level == exp_level, f"0x{level:08X} vs 0x{exp_level:08X}")
    check(f"  {cid} race 一致（魔陷为 0）", race == (spec.race_bits if spec.is_monster else 0),
          f"0x{race:X} vs 0x{(spec.race_bits if spec.is_monster else 0):X}")
    check(f"  {cid} attribute 一致（魔陷为 0）",
          attr == (spec.attr_bits if spec.is_monster else 0),
          f"0x{attr:X} vs 0x{(spec.attr_bits if spec.is_monster else 0):X}")
    check(f"  {cid} setcode 一致", setcode == int(spec.setcode, 16),
          f"0x{setcode:X} vs {spec.setcode}")
    check(f"  {cid} ot = 3 (OCG|TCG)", ot == 3, f"{ot}")
    p(f"     str1={str1!r}")
    p(f"     desc={desc!r}")
    p()

# 连接怪兽专项
r = con.execute("SELECT def, level FROM datas WHERE id=210000003").fetchone()
p("  ── 连接怪兽专项（箭头掩码 / 连接数）──")
p(f"     arrows_bits 期望 = 0x{C.link_markers_bits(['左下','下','右下']):X} "
  f"({C.link_markers_bits(['左下','下','右下'])})，实测 def=0x{r[0]:X} ({r[0]})")
check("连接怪兽 def = 箭头掩码", r[0] == C.link_markers_bits(["左下", "下", "右下"]))
check("连接怪兽 level = 连接数 3", r[1] == 3, f"level={r[1]}")
p()

# 通常怪兽 type 位（core 的 FRAMES["normal"].base 是 "effect"，本层兜住）
r = con.execute("SELECT type FROM datas WHERE id=210000004").fetchone()
p("  ── 通常怪兽 type 位（core 偏差兜底）──")
p(f"     CardSpec.type_bits        = 0x{cards[4].type_bits:X}  "
  f"（= MONSTER|EFFECT，因为 FRAMES['normal'].base=='effect'，core 疑似漏写）")
p(f"     cdb.engine_type_bits(spec)= 0x{cdbmod.engine_type_bits(cards[4]):X}  "
  f"（= MONSTER|NORMAL，写进 cdb 的值）")
p(f"     cdb 实测 type             = 0x{r[0]:X}")
check("通常怪兽写进 cdb 的 type = 0x11 (MONSTER|NORMAL)", r[0] == 0x11, f"0x{r[0]:X}")
p()

# 灵摆 level 列打包（对齐官方 399 张灵摆卡的实测编码）
r = con.execute("SELECT level FROM datas WHERE id=210000001").fetchone()
info = cdbmod.parse_level_column(r[0], C.TYPE_MONSTER | C.TYPE_PENDULUM | C.TYPE_EFFECT)
p("  ── 灵摆卡 level 列打包（对齐官方编码）──")
p(f"     期望 = (8<<24)|(8<<16)|4 = 0x{(8 << 24) | (8 << 16) | 4:08X}")
p(f"     cdb 实测 level = 0x{r[0]:08X} → 解出 {info}")
check("灵摆 level 列 = (刻度<<24)|(刻度<<16)|等级", r[0] == (8 << 24) | (8 << 16) | 4,
      f"0x{r[0]:08X}")
check("逆运算解出刻度 8 / 等级 4", info["lscale"] == 8 and info["rscale"] == 8
      and info["level"] == 4, str(info))
p()

# 灵摆卡 desc 版式
r = con.execute("SELECT desc FROM texts WHERE id=210000001").fetchone()
desc = r[0]
p("  ── 灵摆卡 desc 版式 ──")
p(f"     repr = {desc!r}")
check("以「←8 【灵摆】 8→」开头", desc.startswith("←8 【灵摆】 8→"))
check("含 CRLF 分隔", "\r\n" in desc)
check("含【怪兽效果】段标记", "【怪兽效果】" in desc)
check("灵摆效果在怪兽效果之前",
      desc.index("自己主要阶段") < desc.index("【怪兽效果】"))
p()

# 通常怪兽 flavor
r = con.execute("SELECT desc FROM texts WHERE id=210000004").fetchone()
check("通常怪兽 desc = flavor", r[0] == "在废墟里弹奏无声竖琴的石头人。", repr(r[0]))
p()

# str1..str16
r = con.execute("SELECT str1,str2,str3,str16 FROM texts WHERE id=210000001").fetchone()
check("strings 落到 str1/str2，str3+ 为空",
      r[0] == "①：从卡组把1张「星奏」卡加入手卡。" and r[1] == "灵摆效果"
      and not r[2] and not r[3], f"{r}")
p()

# 多语言 cdb
p("  ── 多语言 cdb ──")
for f in sorted(EXP.glob("*.cdb")):
    c2 = sqlite3.connect(str(f))
    nm = c2.execute("SELECT name FROM texts WHERE id=210000000").fetchone()
    n = c2.execute("SELECT COUNT(*) FROM datas").fetchone()[0]
    p(f"     {f.name:<26} 卡数={n}  210000000 的卡名 = {nm[0]!r}")
    c2.close()
ja = sqlite3.connect(str(EXP / "CardForge-ja.cdb"))
ja_name = ja.execute("SELECT name FROM texts WHERE id=210000000").fetchone()[0]
ja_desc = ja.execute("SELECT desc FROM texts WHERE id=210000000").fetchone()[0]
ja.close()
check("ja 包里卡名是日文", ja_name == "焔刃の見習い剣士", ja_name)
check("ja 包里卡文是日文", "召喚に成功した" in ja_desc, ja_desc[:40])
p()
con.close()

# ══════════════════════════════════════════════════════════════════════
#  5. BOM 检查
# ══════════════════════════════════════════════════════════════════════
p("── 5. 生成的 .lua 无 BOM ──")
lua_files = sorted((EXP / "script").glob("*.lua"))
for f in lua_files:
    head = f.read_bytes()[:3]
    p(f"  {f.name}  前 3 字节 = {head!r}  ({head.hex(' ')})")
    check(f"{f.name} 无 BOM", head != b"\xef\xbb\xbf")
check("脚本按需生成（3 个：效果怪 + 灵摆 + 连接兽；通常怪/魔陷没有）",
      [f.name for f in lua_files] == ["c210000000.lua", "c210000001.lua", "c210000003.lua"],
      f"实际 {[f.name for f in lua_files]}")
p()

# ══════════════════════════════════════════════════════════════════════
#  3b. verify
# ══════════════════════════════════════════════════════════════════════
p("── 3b. expansions.verify()（干净包，应无 ERROR）──")
issues = expansions.verify(PACK)
p(f"  共 {len(issues)} 条")
for i in issues:
    p(f"    [{i.level:<5}] {i.code:<22} {i.message}")
n_err = sum(1 for i in issues if i.level == "ERROR")
check("干净包无 ERROR", n_err == 0, f"ERROR={n_err}")
check("缺脚本的卡被点名（G5_SCRIPT_MISSING）",
      any(i.code == "G5_SCRIPT_MISSING" and i.field == "210000002" for i in issues))
check("尺寸不符被点名（G5_PIC_SIZE，带实测尺寸）",
      any(i.code == "G5_PIC_SIZE" and "400×600" in i.message for i in issues))
check("缺卡图标成 pending（G5_PIC_PENDING）",
      any(i.code == "G5_PIC_PENDING" for i in issues))
check("通常怪兽没被要求脚本",
      not any(i.code == "G5_SCRIPT_MISSING" and i.field == "210000004" for i in issues))
p()

p("── 3c. 人为注入带 BOM 的 .lua → verify 必须报 ERROR ──")
bom_file = EXP / "script" / "c210000002.lua"
bom_file.write_bytes(b"\xef\xbb\xbf" + "-- 带 BOM 的脚本\n".encode("utf-8"))
issues_bom = expansions.verify(PACK)
bom_issues = [i for i in issues_bom if i.code == "G5_LUA_BOM"]
for i in bom_issues:
    p(f"    [{i.level}] {i.code}: {i.message}")
    p(f"        hint: {i.hint}")
check("BOM 被检出且为 ERROR",
      bool(bom_issues) and bom_issues[0].level == "ERROR",
      f"{[(i.code, i.level) for i in bom_issues]}")
check("注入 BOM 后包不再通过（有 ERROR）",
      any(i.level == "ERROR" for i in issues_bom))
bom_file.unlink()
p()

p("── 3d. 卡号与官方池冲突 → verify 必须报 ERROR ──")
pool = load_official()
p(f"  官方池可用 = {pool.available}，青眼白龙 89631139 已占用 = {pool.id_taken(89631139)}")
bad_pack = TMP / "out_bad"
expansions.build([CardSpec(id=89631139, name="占用了官方卡号的白龙", frame="normal",
                           attribute="光", race="龙族", level=8, atk=3000, dfd=2500,
                           flavor="测试用")],
                 bad_pack, name="BadPack", langs=("zh_cn",), copy_pics=False)
bad_issues = expansions.verify(bad_pack)
conf = [i for i in bad_issues if i.code == "G5_ID_CONFLICT"]
for i in conf:
    p(f"    [{i.level}] {i.code}: {i.message}")
check("卡号冲突被检出且为 ERROR",
      bool(conf) and conf[0].level == "ERROR", f"{[(i.code, i.level) for i in conf]}")
p()

p("── 3e. manifest 内容 ──")
mf = json.loads((PACK / expansions.MANIFEST_NAME).read_text(encoding="utf-8"))
p(f"  keys = {sorted(mf)}")
p(f"  cards = {json.dumps(mf['cards'], ensure_ascii=False)[:400]}…")
p(f"  pending_pics = {mf['pending_pics']}")
check("manifest 记录 5 张卡", len(mf["cards"]) == 5)
check("manifest 标出 pending 卡图", set(mf["pending_pics"]) == {210000002, 210000003, 210000004},
      f"{mf['pending_pics']}")
p()

p("── 3f. README.txt 前 40 行 ──")
readme = (PACK / "README.txt").read_text(encoding="utf-8")
for ln in readme.splitlines()[:40]:
    p(f"  │ {ln}")
check("README 含许可提示", "许可" in readme and "MIT" in readme)
check("README 含导入路径", "%LOCALAPPDATA%" in readme)
check("README 在包根与 expansions/ 各一份",
      (PACK / "README.txt").is_file() and (EXP / "README.txt").is_file())
p()

p("── 附加：pack_stats / file_tree 截断 ──")
p(f"  pack_stats = {expansions.pack_stats(PACK)}")
p()

p("═" * 68)
p(f"断言：{'全部通过' if not fails else '失败 ' + str(len(fails)) + ' 项'}")
for f in fails:
    p(f"  !! FAIL: {f}")
p("═" * 68)

OUT.joinpath("p3_build_verify.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
sys.exit(1 if fails else 0)
