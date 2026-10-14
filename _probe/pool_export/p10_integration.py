"""集成自测：与兄弟模块 pipeline/gates.py 和 cli.py 的调用约定对齐。

cli.py 里对 build()/install() 返回值的用法是**兄弟模块写的**，契约没规定键名。
本脚本按 cli.py 的真实取键方式跑一遍，确认不炸；同时跑 pipeline/gates.g5_export()
看它是真能消费我们返回的 list[Issue]。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
TMP = ROOT / "_probe" / "pool_export" / "_tmp" / "integ"
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True, exist_ok=True)
os.environ["WORKSPACE"] = str(TMP)
sys.path.insert(0, str(ROOT))

from cardforge.core import paths                            # noqa: E402
from cardforge.core.models import CardSpec                  # noqa: E402
from cardforge.export import expansions                     # noqa: E402
from cardforge.export import install as inst                # noqa: E402
from cardforge.pool import repo                             # noqa: E402

OUT = ROOT / "_probe" / "pool_export" / "_out"
lines: list[str] = []
fails: list[str] = []
counters = {"i": 0}


def p(s: str = "") -> None:
    lines.append(str(s))


def check(label: str, ok: bool, detail: str = "") -> None:
    if not ok:
        fails.append(label)
    p(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  —— {detail}" if detail else ""))


paths.ensure_dirs()
for spec in (CardSpec(id=210000000, name="集成效果怪", frame="effect", attribute="光",
                      race="魔法师族", level=4, atk=1800, dfd=1200, setcode="0x1001",
                      text_i18n={"zh_cn": "①：集成测试。"},
                      lua="local s,id=GetID()\n"),
             CardSpec(id=210000001, name="集成通常怪", frame="normal", attribute="地",
                      race="岩石族", level=3, atk=800, dfd=1800, flavor="白板。")):
    repo.save_card(spec)
cards = [c for c in (repo.load_card(210000000), repo.load_card(210000001)) if c]
p(f"从 repo 读出 {len(cards)} 张卡：{[c.name for c in cards]}")
p()

p("── 1. 按 cli.py 的真实取键方式调用 build() ──")
res = expansions.build(cards, ROOT / "_probe" / "pool_export" / "_tmp" / "integ_out",
                       name="CardForge", langs=("zh_cn",))
p(f"  res['cards'] = {res.get('cards')}")
p(f"  res['dir']   = {res.get('dir')}")
p(f"  res['stats'] = {res.get('stats')}")
check("cli.py 用的 res['cards'] 存在且是整数",
      isinstance(res.get("cards"), int) and res["cards"] == 2, str(res.get("cards")))
check("cli.py 用的 res['dir'] 存在且是包根（含 expansions/）",
      isinstance(res.get("dir"), str) and (Path(res["dir"]) / "expansions").is_dir(),
      str(res.get("dir")))
check("cli.py 用的 res['stats'] 是 dict", isinstance(res.get("stats"), dict))
check("原生键没被别名顶掉（n_cards/pack_dir 仍在）",
      res.get("n_cards") == 2 and res.get("pack_dir") == res.get("dir"))
p("  cli.py 会这样打印（逐个 stats 项）：")
for k, v in (res.get("stats") or {}).items():
    p(f"      {k}: {v}")
p()

p("── 2. pipeline/gates.g5_export(res['dir']) 真跑一遍 ──")
try:
    from cardforge.pipeline import gates
    rep = gates.g5_export(res["dir"])
    p(f"  gate     = {rep.gate}")
    p(f"  status   = {rep.status}")
    p(f"  summary  = {rep.summary}")
    p(f"  degraded = {rep.degraded!r}")
    p(f"  has_error= {rep.has_error}")
    p(f"  issues({len(rep.issues)})：")
    for i in rep.issues:
        lvl = getattr(i, "level", None) or i.get("level")
        code = getattr(i, "code", None) or i.get("code")
        msg = getattr(i, "message", None) or i.get("message")
        p(f"      [{lvl:<5}] {code:<22} {msg}")
    check("g5_export 能消费 verify() 的返回", rep is not None)
    check("gates 能按对象/字典两种方式读到 Issue 字段",
          all((getattr(i, "code", None) or i.get("code")) for i in rep.issues)
          if rep.issues else True)
    check("status 不是 fail（无 ERROR）", rep.status != "fail", rep.status)
except ImportError as e:
    p(f"  （pipeline/gates.py 还不可用：{e}，跳过）")
except Exception as e:                                     # noqa: BLE001
    p(f"  !! gates.g5_export 抛异常：{type(e).__name__}: {e}")
    check("gates.g5_export 不抛异常", False, f"{type(e).__name__}: {e}")
p()

p("── 3. 按 cli.py 的取键方式调用 install() ──")
FAKE = TMP / "FakeEDOPro"
(FAKE / "expansions").mkdir(parents=True, exist_ok=True)
(FAKE / "ocgcore.dll").write_bytes(b"MZ")
r = inst.install(res["dir"], FAKE)
p(f"  r['target'] = {r.get('target')}")
p(f"  r['copied'] 的类型 = {type(r.get('copied')).__name__}，长度 {len(r.get('copied') or [])}")
p(f"  r['copied_count'] = {r.get('copied_count')}   r['count'] = {r.get('count')}")
p(f"  cli.py 现在会打印：已安装到 {r.get('target')}，复制 {r.get('copied', 0)} 个文件")
p(f"  → 改成 r.get('copied_count') 后会打印：已安装到 {r.get('target')}，"
  f"复制 {r.get('copied_count', 0)} 个文件")
check("r['target'] 存在", bool(r.get("target")))
check("r['copied'] 是复制清单（列表）", isinstance(r.get("copied"), list)
      and len(r["copied"]) == 4, str(r.get("copied")))
check("r['copied_count'] 是数量 4", r.get("copied_count") == 4, str(r.get("copied_count")))
check("install ok", r.get("ok") is True)
p()

p("── 4. install(pack) 无 target 时的返回（cli.py 只取 target/copied）──")
r2 = inst.install(res["dir"])
p(f"  ok={r2.get('ok')}  error={r2.get('error')!r}  target={r2.get('target')!r}")
check("无 target 时也有 target 键（空串）", "target" in r2)
check("无 target 时 ok=False 且给 hint", r2["ok"] is False and bool(r2.get("hint")))
p()

p("═" * 68)
p(f"断言：{'全部通过' if not fails else '失败 ' + str(len(fails)) + ' 项'}")
for f in fails:
    p(f"  !! FAIL: {f}")
p("═" * 68)

OUT.joinpath("p10_integration.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
sys.exit(1 if fails else 0)
