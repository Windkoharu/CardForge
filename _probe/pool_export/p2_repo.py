"""自测 2：项目仓库（CRUD + 增量快照 + 回滚 + v0.x 迁移）。

覆盖：3 张 CardSpec（效果怪 / 灵摆 / 场地魔法）→ save → load → 字段往返断言
（含 type_bits / def_value / race_bits / attr_bits / effective_level）→ 幂等保存不产生
快照 → 改一次再存 → 两次快照 → rollback 到 v1 → 内容回到旧值；
另测系列/卡组快照、v0.x 旧 JSON 迁移写回、strings.conf 两个入口逐字节一致。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
TMP = ROOT / "_probe" / "pool_export" / "_tmp" / "ws_repo"
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True, exist_ok=True)
os.environ["WORKSPACE"] = str(TMP)          # 必须在 import cardforge 之前设置
sys.path.insert(0, str(ROOT))

from cardforge.core import paths                              # noqa: E402
from cardforge.core.enums import LANGS, SPELL_KINDS           # noqa: E402
from cardforge.core.models import (                           # noqa: E402
    Archetype, CardSpec, DeckEntry, DeckSpec, EffectSpec, EffectTarget,
    RenderOptions, RosterSlot,
)
from cardforge.pool import cdb as cdbmod                      # noqa: E402
from cardforge.pool import repo                               # noqa: E402

OUT = ROOT / "_probe" / "pool_export" / "_out"
OUT.mkdir(parents=True, exist_ok=True)
lines: list[str] = []
fails: list[str] = []


def p(s: str = "") -> None:
    lines.append(str(s))


def check(label: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    if not ok:
        fails.append(label)
    p(f"  [{tag}] {label}" + (f"  —— {detail}" if detail else ""))


p(f"临时 WORKSPACE = {TMP}")
p(f"paths.CARDS   = {paths.CARDS}")
p()

# ══════════════════════════════════════════════════════════════════════
#  造 3 张卡
# ══════════════════════════════════════════════════════════════════════
eff = CardSpec(
    id=210000000, name="焰刃的见习剑士", frame="effect",
    attribute="炎", race="战士族", level=4, atk=1700, dfd=1000,
    archetype="焰刃", setcode="0x3001",
    text_i18n={"zh_cn": "①：这张卡召唤成功时才能发动。从卡组把1张「焰刃」卡加入手卡。"
                        "这个效果1回合只能使用1次。"},
    strings=["①：从卡组把1张「焰刃」卡加入手卡。"],
    effects=[EffectSpec(kind="search", trigger="NORMAL_SUMMON_SUCCESS",
                        target=EffectTarget(from_zone="DECK", to_zone="HAND",
                                            filter_kind="archetype", filter_value="焰刃"),
                        limit="once_per_turn")],
    lua="--[[ 焰刃的见习剑士 ]]\nlocal s,id=GetID()\nfunction s.initial_effect(c)\nend\n",
    render=RenderOptions(rarity="super", set_number="CF01-JP001", lang_text="zh_cn"),
)
pen = CardSpec(
    id=210000001, name="星奏的指挥者 艾莉娅", frame="pendulum",
    attribute="光", race="魔法师族", level=4, atk=1600, dfd=1200,
    pendulum_scale=8, archetype="星奏", setcode="0x1001",
    text_i18n={"zh_cn": "①：这张卡召唤成功时才能发动。从卡组把1张「星奏」卡加入手卡。"},
    pendulum_text_i18n={"zh_cn": "①：自己主要阶段才能发动。从卡组把1只「星奏」怪兽加入手卡。"},
    strings=["①：从卡组把1张「星奏」卡加入手卡。"],
    effects=[EffectSpec(kind="search", trigger="NORMAL_SUMMON_SUCCESS")],
    lua="--[[ 星奏的指挥者 ]]\nlocal s,id=GetID()\n",
)
spell = CardSpec(
    id=210000002, name="星奏的圆舞曲", frame="spell", spell_kind="field",
    archetype="星奏", setcode="0x1001",
    text_i18n={"zh_cn": "①：作为这张卡发动时的效果处理，从卡组把1只「星奏」怪兽加入手卡。"},
    strings=["①：从卡组把1只「星奏」怪兽加入手卡。"],
)

p("── 1. save_card → load_card 往返 ──")
paths_by_id = {}
for spec in (eff, pen, spell):
    pth = repo.save_card(spec)
    paths_by_id[spec.id] = pth
    p(f"  save_card({spec.id}) → {paths.rel(Path(pth))}")
p()

_ROUNDTRIP = ("id", "name", "frame", "attribute", "race", "level", "atk", "dfd",
              "pendulum_scale", "spell_kind", "trap_kind", "tags", "link_markers",
              "archetype", "setcode", "text_i18n", "pendulum_text_i18n", "flavor",
              "strings", "lua", "created", "updated", "schema_version")
_DERIVED = ("type_bits", "def_value", "race_bits", "attr_bits", "link_bits",
            "effective_level", "is_pendulum", "is_monster", "is_extra")

for spec in (eff, pen, spell):
    back = repo.load_card(spec.id)
    check(f"{spec.id} 读得回来", back is not None)
    if back is None:
        continue
    bad = []
    for f in _ROUNDTRIP:
        a, b = getattr(spec, f, None), getattr(back, f, None)
        if a != b and not (f in ("spell_kind", "trap_kind") and not a and not b):
            bad.append(f"{f}: {a!r} != {b!r}")
    check(f"{spec.id} 普通字段往返一致", not bad, "; ".join(bad))
    bad2 = []
    for f in _DERIVED:
        a, b = getattr(spec, f), getattr(back, f)
        if a != b:
            bad2.append(f"{f}: {a!r} != {b!r}")
    check(f"{spec.id} 派生属性往返一致", not bad2, "; ".join(bad2))
    check(f"{spec.id} effects 条数一致", len(spec.effects) == len(back.effects),
          f"{len(spec.effects)} vs {len(back.effects)}")
    check(f"{spec.id} render.rarity 往返", spec.render.rarity == back.render.rarity)
p(f"  派生值实测：")
for spec in (eff, pen, spell):
    p(f"    {spec.id} {spec.name:<18} frame={spec.frame:<9} type_bits=0x{spec.type_bits:X}"
      f"({spec.type_bits}) def_value={spec.def_value} race_bits={spec.race_bits} "
      f"attr_bits={spec.attr_bits} level={spec.effective_level}")
p()

p("── 2. 落盘格式检查（UTF-8 无 BOM / ensure_ascii=False / indent=2）──")
raw = Path(paths_by_id[210000000]).read_bytes()
check("无 BOM", raw[:3] != b"\xef\xbb\xbf", f"前 3 字节 = {raw[:3]!r}")
text = raw.decode("utf-8")
check("中文未被转义", "焰刃的见习剑士" in text)
check("indent=2", '\n  "id"' in text)
check("含 schema_version", '"schema_version": 2' in text, f"当前 SCHEMA_VERSION=2")
p(f"  spec.json 前 12 行：")
for ln in text.splitlines()[:12]:
    p(f"    {ln}")
p()

p("── 3. 幂等保存不产生新快照 ──")
s1 = repo.snapshots("cards", "210000000")
p(f"  首存后快照 = {[(x['version'], x['note'], x['ts']) for x in s1]}")
again = repo.load_card(210000000)
again.atk = again.atk                      # 改回同一个值（内容不变）
repo.save_card(again)
s2 = repo.snapshots("cards", "210000000")
check("内容未变 → 快照数不变", len(s2) == len(s1), f"{len(s1)} → {len(s2)}")
check("内容未变 → updated 不推进",
      repo.load_card(210000000).updated == eff.updated,
      f"{eff.updated!r} vs {repo.load_card(210000000).updated!r}")
p()

p("── 4. 改一次再存 → 生成第二个快照 ──")
changed = repo.load_card(210000000)
changed.atk = 1900
changed.text_i18n["zh_cn"] = "①：改过的卡文。"
repo.save_card(changed, note="把攻击力提到 1900")
s3 = repo.snapshots("cards", "210000000")
p(f"  改后快照 = {[(x['version'], x['note'], x['ts'], x['digest']) for x in s3]}")
check("快照数 = 2", len(s3) == 2, f"实际 {len(s3)}")
check("现场 atk = 1900", repo.load_card(210000000).atk == 1900)
check("updated 已推进", repo.load_card(210000000).updated != eff.updated,
      f"{eff.updated!r} → {repo.load_card(210000000).updated!r}")
p()

p("── 5. rollback 到 v1 ──")
res = repo.rollback("cards", "210000000", 1)
p(f"  rollback 返回 = {{k: res[k] for k in ('ok','kind','key','version','path','new_version','ts')}}")
p(f"    ok={res['ok']} version={res['version']} new_version={res['new_version']}")
p(f"    path={paths.rel(Path(res['path']))}")
after = repo.load_card(210000000)
check("atk 回到旧值 1700", after.atk == 1700, f"实际 {after.atk}")
check("卡文回到旧值", after.text_i18n["zh_cn"] == eff.text_i18n["zh_cn"])
check("updated 回到旧值", after.updated == eff.updated,
      f"{after.updated!r} vs {eff.updated!r}")
s4 = repo.snapshots("cards", "210000000")
p(f"  回滚后快照 = {[(x['version'], x['note']) for x in s4]}")
check("历史只追加不重写（v1 仍在）", s4[0]["version"] == 1 and len(s4) == 3,
      f"版本 = {[x['version'] for x in s4]}")
p()

p("── 6. list_cards / delete_card ──")
lst = repo.list_cards()
p(f"  list_cards() = {len(lst)} 张")
for it in lst:
    p(f"    id={it['id']} name={it['name']} frame={it['frame_label']} level={it['level']} "
      f"atk={it['atk']} def={it['def']} archetype={it['archetype']} "
      f"schema_version={it['schema_version']}")
check("列出 3 张", len(lst) == 3)
check("按卡号升序", [i["id"] for i in lst] == [210000000, 210000001, 210000002])
p(f"  list_cards('星奏') = {[i['id'] for i in repo.list_cards('星奏')]}")
check("按系列过滤", [i["id"] for i in repo.list_cards("星奏")] == [210000001, 210000002])
check("delete_card(210000002) = True", repo.delete_card(210000002) is True)
check("删除后 list_cards = 2", len(repo.list_cards()) == 2)
check("删除后 load_card = None", repo.load_card(210000002) is None)
rb = repo.rollback("cards", "210000002", 1)
check("删除后能 rollback 救回", rb["ok"] and repo.load_card(210000002) is not None)
repo.delete_card(210000002)
p()

p("── 7. 系列圣经 + 卡组 ──")
arch = Archetype(
    name="星奏", setcode="0x1001", concept="以灵摆召唤为核心的音律使团",
    win_method="EFFECT", trumps=["FUSION", "XYZ"], binding={"attribute": "光"},
    dialects=["从卡组把1张「星奏」卡加入手卡。", "那张「星奏」卡破坏。"],
    roster=[RosterSlot(role="starter", count=3, brief="零前置启动"),
            RosterSlot(role="trump", count=2, frame_hint="fusion")],
    target_power="rogue", notes="测试用",
)
ap = repo.save_archetype(arch)
p(f"  save_archetype → {paths.rel(Path(ap))}")
back_a = repo.load_archetype("星奏")
check("系列往返", back_a is not None and back_a.name == "星奏"
      and back_a.setcode == "0x1001" and len(back_a.roster) == 2
      and back_a.roster_total() == 5,
      f"roster_total={back_a.roster_total() if back_a else None}")
check("系列快照 v1", [x["version"] for x in repo.snapshots("archetypes", "星奏")] == [1])
arch.concept = "改过的概念"
repo.save_archetype(arch)
check("系列第二次快照", [x["version"] for x in repo.snapshots("archetypes", "星奏")] == [1, 2])
p(f"  list_archetypes() = {repo.list_archetypes()}")

deck = DeckSpec(
    name="星奏标准", archetype="星奏", target="casual",
    main=[DeckEntry(card_id=210000001, count=3, role="starter", name="星奏的指挥者 艾莉娅"),
          DeckEntry(card_id=89631139, count=3, name="青眼白龙")],
    extra=[DeckEntry(card_id=210000010, count=2, role="trump", name="星奏的终曲")],
    side=[DeckEntry(card_id=210000000, count=2, name="焰刃的见习剑士")],
)
dp = repo.save_deck(deck)
p(f"  save_deck → {paths.rel(Path(dp))}")
back_d = repo.load_deck("星奏标准")
check("卡组往返", back_d is not None and len(back_d.main) == 2
      and back_d.main[0].card_id == 210000001 and back_d.main[0].count == 3
      and len(back_d.extra) == 1 and len(back_d.side) == 1)
check("卡组快照", [x["version"] for x in repo.snapshots("decks", "星奏标准")] == [1])
p(f"  list_decks() = {repo.list_decks()}")
p()

p("── 8. v0.x 旧 JSON 自动迁移并写回 ──")
legacy_src = Path(ROOT) / "workspace" / "_legacy_cards" / "210000011.json"
dst = paths.card_spec_path(210000011, None)
dst.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(legacy_src, dst)
before = json.loads(dst.read_text(encoding="utf-8"))
p(f"  迁移前键 = {sorted(before)}")
p(f"  迁移前 schema_version = {before.get('schema_version', '（无）')}")
p(f"  迁移前 has 'def' = {'def' in before}  has 'text' = {'text' in before}  "
  f"has '_lua' = {'_lua' in before}  has '_strings' = {'_strings' in before}")
mig = repo.load_card(210000011)
after_raw = json.loads(dst.read_text(encoding="utf-8"))
p(f"  迁移后键 = {sorted(after_raw)}")
p(f"  迁移后 schema_version = {after_raw.get('schema_version')}")
check("load 成功", mig is not None)
check("def → dfd", mig.dfd == 1200, f"dfd={mig.dfd}")
check("text → text_i18n", bool(mig.text_i18n.get("zh_cn")))
check("_lua → lua", mig.lua.startswith("--[["))
check("_strings → strings", len(mig.strings) == 2, f"{mig.strings}")
check("type_flags → tags", mig.tags == [])
check("写回后 schema_version = 2", after_raw.get("schema_version") == 2)
check("写回后不再有 'def' 键", "def" not in after_raw)
check("写回后不再有 '_lua' 键", "_lua" not in after_raw)
p(f"  迁移快照 = {[(x['version'], x['note']) for x in repo.snapshots('cards', '210000011')]}")
p()

p("── 9. 归属系列改变时不留下重复卡 ──")
mv = CardSpec(id=210000050, name="搬家测试", frame="effect", attribute="炎",
              race="战士族", level=4, atk=1000, dfd=1000)
flat_path = Path(repo.save_card(mv))
p(f"  先存平铺目录 → {paths.rel(flat_path)}  存在={flat_path.is_file()}")
check("平铺目录里有 spec.json", flat_path.is_file())
mv.archetype = "焰刃"
moved_path = Path(repo.save_card(mv))
p(f"  改系列后再存 → {paths.rel(moved_path)}")
p(f"  旧文件还在吗 = {flat_path.is_file()}")
check("写到了系列目录", moved_path.is_file() and moved_path != flat_path
      and moved_path.parent.parent.name == "焰刃")
check("旧文件被清掉（不留重复卡）", not flat_path.is_file())
check("list_cards 里只出现一次",
      [i["id"] for i in repo.list_cards()].count(210000050) == 1,
      str([i["id"] for i in repo.list_cards()]))
check("load_card 仍读得到，且内容没丢", repo.load_card(210000050).atk == 1000)
check("平铺空目录被删掉", not flat_path.parent.exists(), str(flat_path.parent))
p()

p("── 10. strings.conf：两个入口逐字节一致 ──")
setnames = {0x1001: "星奏", "0x1002": "焰刃"}
counters = {"0x1": "星奏指示物", 2: "焰刃指示物"}
path_a = TMP / "out" / "strings_by_cdb.conf"
cdbmod.write_strings_conf(path_a, setnames, counters)
from cardforge.export import strings as stringsmod           # noqa: E402
path_b = TMP / "out" / "strings_by_export.conf"
stringsmod.write(path_b, setnames=setnames, counters=counters)
a_bytes = Path(path_a).read_bytes()
b_bytes = Path(path_b).read_bytes()
check("pool.cdb.write_strings_conf == export.strings.render（逐字节）", a_bytes == b_bytes)
p("  文件内容：")
for ln in a_bytes.decode("utf-8").splitlines():
    p(f"    {ln}")
p()

# ══════════════════════════════════════════════════════════════════════
p("═" * 68)
p(f"断言：{len(fails) == 0 and '全部通过' or ('失败 ' + str(len(fails)) + ' 项')}"
  f"（共 {len(lines)} 行输出）")
if fails:
    for f in fails:
        p(f"  !! FAIL: {f}")
p("═" * 68)

OUT.joinpath("p2_repo.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
sys.exit(1 if fails else 0)
