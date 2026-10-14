"""自测 6：.ydk 读写与校验。

覆盖：write 一个 40 张卡组 → read 回来 → 断言一致；validate 对 39 张卡组报 ERROR；
额外覆盖 61 张 / 额外 16 张 / 副卡 16 张 / 同名 4 张 / pool_ids 存在性 / 空卡组。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
sys.path.insert(0, str(ROOT))

from cardforge.core.models import DeckEntry, DeckSpec      # noqa: E402
from cardforge.export import ydk                            # noqa: E402

OUT = ROOT / "_probe" / "pool_export" / "_out"
TMP = ROOT / "_probe" / "pool_export" / "_tmp" / "ydk"
TMP.mkdir(parents=True, exist_ok=True)
lines: list[str] = []
fails: list[str] = []


def p(s: str = "") -> None:
    lines.append(str(s))


def check(label: str, ok: bool, detail: str = "") -> None:
    if not ok:
        fails.append(label)
    p(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  —— {detail}" if detail else ""))


# 40 张主卡组：13 种 × 3 张 = 39 + 1 张 = 40
main: list[DeckEntry] = []
for i in range(13):
    main.append(DeckEntry(card_id=210000100 + i, count=3, role="starter",
                          name=f"主卡组卡{i + 1}"))
main.append(DeckEntry(card_id=210000200, count=1, role="recovery", name="唯一的回收点"))
deck = DeckSpec(
    name="星奏标准", archetype="星奏", target="competitive",
    main=main,
    extra=[DeckEntry(card_id=210000300 + i, count=2, name=f"额外卡{i + 1}") for i in range(5)],
    side=[DeckEntry(card_id=210000400 + i, count=3, name=f"副卡{i + 1}") for i in range(5)],
)
s = ydk.sizes(deck)
p(f"造出来的卡组：main={s['main']} extra={s['extra']} side={s['side']} total={s['total']}")
p()

p("── write / read 往返 ──")
path = TMP / "星奏标准.ydk"
ret = ydk.write(deck, path)
p(f"  write → {ret}")
raw = Path(ret).read_bytes()
p(f"  文件大小 = {len(raw)} 字节，前 3 字节 = {raw[:3]!r}（无 BOM: {raw[:3] != b'\xef\xbb\xbf'}）")
check("文件无 BOM", raw[:3] != b"\xef\xbb\xbf")
text = raw.decode("utf-8")
for ln in text.splitlines()[:6]:
    p(f"    │ {ln}")
p(f"    │ …（共 {len(text.splitlines())} 行）")
p(f"    │ !side")
p(f"    │ {text.splitlines()[-1]}")
p()

back = ydk.read(path)
check("read 回来不是 None", back is not None)
check("name = 文件名", back.name == "星奏标准", back.name)
check("main 张数一致", ydk.sizes(back)["main"] == 40, str(ydk.sizes(back)))
check("extra 张数一致", ydk.sizes(back)["extra"] == 10, str(ydk.sizes(back)))
check("side 张数一致", ydk.sizes(back)["side"] == 15, str(ydk.sizes(back)))
check("main 展开后逐卡号一致", ydk.expand(back)["main"] == ydk.expand(deck)["main"],
      f"{len(ydk.expand(back)['main'])} vs {len(ydk.expand(deck)['main'])}")
check("extra 逐卡号一致", ydk.expand(back)["extra"] == ydk.expand(deck)["extra"])
check("side 逐卡号一致", ydk.expand(back)["side"] == ydk.expand(deck)["side"])
check("main 种类数一致（14 种）", len(back.main) == len(deck.main),
      f"{len(back.main)} vs {len(deck.main)}")
check("count 字段被合并回张数",
      [e.count for e in back.main[:3]] == [3, 3, 3], str([e.count for e in back.main[:3]]))
check("注释行被保留到 notes", back.notes.startswith("#created by"), back.notes)
check("再写一次结果逐字节相同", ydk.to_text(back) == ydk.to_text(deck))
p()

p("── validate：合规卡组（40 张）──")
issues = ydk.validate(deck)
p(f"  共 {len(issues)} 条：" + ("（空）" if not issues else ""))
for i in issues:
    p(f"    [{i.level:<5}] {i.code:<20} {i.message}")
check("合规卡组 0 条 ERROR", not any(i.level == "ERROR" for i in issues))
p()

p("── validate：39 张主卡组（应报 ERROR）──")
short = DeckSpec(name="差一张", main=list(main))
short.main[0] = DeckEntry(card_id=main[0].card_id, count=2, name=main[0].name)
iss = ydk.validate(short)
for i in iss:
    p(f"    [{i.level:<5}] {i.code:<20} {i.message}")
    p(f"        hint: {i.hint}")
err = [i for i in iss if i.level == "ERROR"]
check("39 张报 ERROR", bool(err) and err[0].code == "YDK_MAIN_SIZE",
      f"{[(i.code, i.level) for i in iss]}")
check("ERROR 信息里带实际张数", "39" in err[0].message if err else False,
      err[0].message if err else "")
p()

p("── validate：其余越界情形 ──")
cases = {
    "61 张主卡组": DeckSpec(name="超了", main=[
        DeckEntry(card_id=210000500 + i, count=3, name=f"卡{i}") for i in range(20)]
        + [DeckEntry(card_id=210000600, count=1, name="尾巴")]),
    "额外 16 张": DeckSpec(name="额外超", main=list(main),
                        extra=[DeckEntry(card_id=210000700 + i, count=1, name=f"额{i}")
                               for i in range(16)]),
    "副卡 16 张": DeckSpec(name="副超", main=list(main),
                        side=[DeckEntry(card_id=210000800 + i, count=1, name=f"副{i}")
                              for i in range(16)]),
    "同名 4 张": DeckSpec(name="四张", main=list(main) + [
        DeckEntry(card_id=210000100, count=1, name="主卡组卡1")]),
    "空卡组": DeckSpec(name=""),
}
for label, d in cases.items():
    got = ydk.validate(d)
    p(f"  {label}：")
    for i in got:
        p(f"    [{i.level:<5}] {i.code:<20} {i.message}")
    codes = {i.code for i in got}
    expect = {"61 张主卡组": "YDK_MAIN_SIZE", "额外 16 张": "YDK_EXTRA_SIZE",
              "副卡 16 张": "YDK_SIDE_SIZE", "同名 4 张": "YDK_COPY_LIMIT"}.get(label)
    if expect:
        check(f"  {label} 触发 {expect}", expect in codes, str(codes))
    else:
        check(f"  {label} 触发 YDK_EMPTY + YDK_NAME_EMPTY",
              {"YDK_EMPTY", "YDK_NAME_EMPTY"} <= codes, str(codes))
p()

p("── validate(pool_ids=…) 存在性校验 ──")
pool_ids = {e.card_id for e in main} | {210000300 + i for i in range(5)} \
    | {210000400 + i for i in range(5)}
ok_ids = ydk.validate(deck, pool_ids)
check("池里有全部 DIY 卡 → 无 YDK_CARD_UNKNOWN",
      not any(i.code == "YDK_CARD_UNKNOWN" for i in ok_ids),
      str([i.code for i in ok_ids]))
missing_pool = pool_ids - {210000101, 210000102}
bad = ydk.validate(deck, missing_pool)
unknown = [i for i in bad if i.code == "YDK_CARD_UNKNOWN"]
for i in unknown:
    p(f"    [{i.level}] {i.code}: {i.message}  hint: {i.hint}")
check("池里缺 2 个 DIY 卡号 → 报 2 条 ERROR",
      len(unknown) == 2 and all(i.level == "ERROR" for i in unknown),
      str([i.message for i in unknown]))
with_official = DeckSpec(name="混官方卡", main=list(main) + [
    DeckEntry(card_id=89631139, count=3, name="青眼白龙")])
mixed = ydk.validate(with_official, pool_ids)
check("官方卡号（< 2.1 亿）不做池存在性校验",
      not any(i.code == "YDK_CARD_UNKNOWN" for i in mixed),
      str([i.code for i in mixed]))
check("pool_ids=None 时跳过存在性校验",
      not any(i.code == "YDK_CARD_UNKNOWN" for i in ydk.validate(deck)))
p()

p("── 容错：读一个手工写坏的文件 ──")
weird = TMP / "weird.ydk"
weird.write_text("#created by hand\n\n#main\n210000100\n# 注释\n!side\nbadline\n"
                 "210000100\n#extra\n210000300\n", encoding="utf-8")
w = ydk.read(weird)
p(f"  main={[(e.card_id, e.count) for e in w.main]}  "
  f"extra={[(e.card_id, e.count) for e in w.extra]}  side={[(e.card_id, e.count) for e in w.side]}")
p(f"  notes={w.notes!r}")
check("坏行不炸，被记进 notes", w is not None and "badline" in w.notes)
check("!side 段被正确识别", [e.card_id for e in w.side] == [210000100])
check("段顺序错乱也不丢卡（#extra 在 !side 之后仍进 extra）",
      [e.card_id for e in w.extra] == [210000300])
check("读不存在的文件返回空 DeckSpec（不抛异常）",
      ydk.read(TMP / "不存在.ydk").name == "不存在")
p()

p("═" * 68)
p(f"断言：{'全部通过' if not fails else '失败 ' + str(len(fails)) + ' 项'}")
for f in fails:
    p(f"  !! FAIL: {f}")
p("═" * 68)

OUT.joinpath("p4_ydk.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
sys.exit(1 if fails else 0)
