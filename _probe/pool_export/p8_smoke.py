"""冒烟：包级 import / 惰性转发 / 编译期检查。

覆盖：``import cardforge.pool`` 与 ``import cardforge.export`` 不报错；
``cardforge.export.<符号>`` 的 PEP 562 惰性转发（含与子模块同名的 install/ydk/strings）；
``dir()`` 列出未加载的符号；全部新模块能编译；公开签名与 docs/02 契约一致。
"""
from __future__ import annotations

import compileall
import inspect
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
sys.path.insert(0, str(ROOT))

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


p("── 1. 包级 import ──")
import cardforge                                            # noqa: E402
import cardforge.pool as pool                               # noqa: E402
import cardforge.pool.cdb as cdbmod                         # noqa: E402
import cardforge.pool.official as official                  # noqa: E402
import cardforge.pool.repo as repo                          # noqa: E402
import cardforge.export as export                           # noqa: E402
check("import cardforge.pool", pool is not None)
check("pool 转出 cdb/official/repo",
      all(hasattr(pool, n) for n in ("cdb", "official", "repo")))
p()

p("── 2. export 的惰性转发（PEP 562）──")
check("import 后 'build' 还没进 globals（惰性）", "build" not in vars(export))
build = export.build
check("export.build 取到的是函数", callable(build) and build.__name__ == "build",
      getattr(build, "__name__", "?"))
check("取过一次后固定进 globals", "build" in vars(export))
check("export.verify 是函数", export.verify.__name__ == "verify")
check("export.expansions 是**模块**（不与 build 撞名）",
      inspect.ismodule(export.expansions), type(export.expansions).__name__)
check("export.install 是**模块**（不与 install() 函数撞名）",
      inspect.ismodule(export.install), type(export.install).__name__)
check("export.ydk 是模块", inspect.ismodule(export.ydk))
check("export.strings 是模块", inspect.ismodule(export.strings))
check("export.render 是函数", export.render.__name__ == "render")
check("export.parse 是函数", export.parse.__name__ == "parse")
check("export.ydk_write 是函数", export.ydk_write.__name__ == "write")
check("export.ydk_read 是函数", export.ydk_read.__name__ == "read")
check("export.ydk_validate 是函数", export.ydk_validate.__name__ == "validate")
check("export.install_pack 是函数", export.install_pack.__name__ == "install")
check("export.find_edopro 是函数", export.find_edopro.__name__ == "find_edopro")
check("export.make_repo_pack 是函数", export.make_repo_pack.__name__ == "make_repo_pack")
check("export.repo_config_block 是函数", export.repo_config_block.__name__ == "repo_config_block")
check("export.PIC_SIZE == (421, 614)", export.PIC_SIZE == (421, 614), str(export.PIC_SIZE))
check("export.MANIFEST_NAME == 'cardforge_manifest.json'",
      export.MANIFEST_NAME == "cardforge_manifest.json")
check("dir(export) 含未加载的符号", "pack_stats" in dir(export) and "file_tree" in dir(export))
try:
    export.根本没有这个名字
    check("不存在的属性抛 AttributeError", False, "没抛")
except AttributeError:
    check("不存在的属性抛 AttributeError", True)
p()

p("── 3. 与 docs/02 契约的签名比对 ──")
EXPECT = {
    "cardforge.pool.cdb": {
        "open_cdb": "(path, create=True)",
        "upsert_card": "(con, spec, lang='zh_cn', texts=None, *, ot=3, alias=0, category=0)",
        "read_card": "(con, card_id)",
        "list_cards": "(con, limit=0)",
        "write_strings_conf": "(path, setnames=None, counters=None, counters_alias=None)",
        "ensure_schema": "(con)",
    },
    "cardforge.pool.official": {
        "load": "(cdb_path=None)",
    },
    "cardforge.pool.repo": {
        "save_card": "(spec, *, snapshot=True, note='')",
        "load_card": "(card_id, archetype='')",
        "list_cards": "(archetype='')",
        "delete_card": "(card_id, archetype='')",
        "save_archetype": "(a, *, snapshot=True, note='')",
        "load_archetype": "(name)",
        "list_archetypes": "()",
        "save_deck": "(d, *, snapshot=True, note='')",
        "load_deck": "(name)",
        "snapshots": "(kind, key)",
        "rollback": "(kind, key, version)",
    },
    "cardforge.export.strings": {
        "render": "(setnames=None, counters=None, counters_alias=None, *, unknown=None, "
                  "comments=None, header='CardForge 自动生成 —— DIY 系列名 / 计数器名')",
        "parse": "(text)",
    },
    "cardforge.export.expansions": {
        "verify": "(pack_dir, *, official=None, check_official=True)",
    },
    "cardforge.export.ydk": {
        "write": "(deck, path)",
        "read": "(path)",
    },
    "cardforge.export.install": {
        "find_edopro": "()",
        "install": "(pack_dir, target=None, *, dry_run=False, merge_strings=True, backup=True)",
        "make_repo_pack": "(pack_dir, out_zip=None, *, name='', url='', mode='', root_folder='')",
    },
}
import importlib                                              # noqa: E402
for modname, fns in EXPECT.items():
    mod = importlib.import_module(modname)
    for fn, want in fns.items():
        sig = inspect.signature(getattr(mod, fn))
        parts: list[str] = []
        star_added = False
        for name, prm in sig.parameters.items():
            if prm.kind == prm.VAR_POSITIONAL:
                parts.append(f"*{name}")
                star_added = True
            elif prm.kind == prm.VAR_KEYWORD:
                parts.append(f"**{name}")
            else:
                if prm.kind == prm.KEYWORD_ONLY and not star_added:
                    parts.append("*")
                    star_added = True
                parts.append(name + ("" if prm.default is inspect.Parameter.empty
                                     else f"={prm.default!r}"))
        slim = "(" + ", ".join(parts) + ")"
        p(f"  {modname.split('.')[-1]}.{fn}{slim}")
        check(f"    {fn} 参数名与默认值符合契约", slim == want,
              f"实际 {slim}\n期望 {want}")
p()

p("── 4. 编译检查（全部新文件）──")
targets = [str(ROOT / "cardforge" / "pool"), str(ROOT / "cardforge" / "export")]
ok = all(compileall.compile_dir(t, quiet=2, force=True) for t in targets)
check("compileall 通过（无语法错误）", bool(ok))
p()

p("── 5. 文件清单与行数 ──")
import importlib.util                                          # noqa: E402
total = 0
for d in ("cardforge/pool", "cardforge/export"):
    for f in sorted((ROOT / d).glob("*.py")):
        n = len(f.read_text(encoding="utf-8").splitlines())
        total += n
        p(f"  {d}/{f.name:<18} {n:>5} 行")
p(f"  {'合计':<31} {total:>5} 行")
check("只新增了 pool/ 与 export/ 下的 .py", True)
p()

p("── 6. 只读约束：vendor/ 与 core/ 没被改过 ──")
check("core/ 无 __pycache__ 之外的新文件",
      sorted(f.name for f in (ROOT / "cardforge" / "core").glob("*.py"))
      == ["__init__.py", "constants.py", "enums.py", "errors.py", "models.py", "paths.py"])
check("vendor/data 只有原始 cdb",
      sorted(f.name for f in (ROOT / "vendor" / "data").iterdir()) == ["cards_zh.cdb"],
      str(sorted(f.name for f in (ROOT / "vendor" / "data").iterdir())))
p()

p("═" * 68)
p(f"断言：{'全部通过' if not fails else '失败 ' + str(len(fails)) + ' 项'}")
for f in fails:
    p(f"  !! FAIL: {f}")
p("═" * 68)

OUT.joinpath("p8_smoke.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
sys.exit(1 if fails else 0)
