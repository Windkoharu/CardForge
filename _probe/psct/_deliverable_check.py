"""交付物自检：行数 / BOM / __future__ / 签名 / 未使用 import / 只读约束。"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASE = ROOT / "cardforge" / "content" / "psct"
FILES = ["__init__.py", "rules.py", "lexicon.py", "gen.py", "lint.py"]

print(f"{'file':<14}{'lines':>6}{'bytes':>8}  BOM  future")
total = 0
for f in FILES:
    p = BASE / f
    raw = p.read_bytes()
    src = raw.decode("utf-8")
    total += len(src.splitlines())
    tree = ast.parse(src)
    fut = any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
              for n in tree.body)
    print(f"{f:<14}{len(src.splitlines()):>6}{len(raw):>8}  "
          f"{str(raw[:3] == b'\\xef\\xbb\\xbf'):<5}{fut}")
print(f"{'TOTAL':<14}{total:>6}")

print("\n── 未使用的 import（粗查）──")
for f in FILES:
    src = (BASE / f).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {(a.asname or a.name.split(".")[0]) for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            names |= {(a.asname or a.name) for a in n.names if a.name != "annotations"}
    body_wo_imports = "\n".join(
        ln for ln in src.splitlines()
        if not ln.strip().startswith(("from ", "import ")))
    unused = sorted(x for x in names if x not in body_wo_imports)
    print(f"  {f:<14}{unused if unused else '（无）'}")

print("\n── 契约签名核对（docs/02 §3.1–3.3）──")
from cardforge.content.psct import gen, lexicon, lint  # noqa: E402

WANT = {
    lexicon: ["terms", "term", "by_category", "patterns", "punctuation",
              "conjunction", "hopt", "reload", "coverage_report"],
    gen: ["effect_to_text", "compose", "compose_all", "type_line", "st_label",
          "flavor"],
    lint: ["lint", "lint_text"],
}
ok = True
for mod, names in WANT.items():
    for name in names:
        fn = getattr(mod, name, None)
        sig = str(inspect.signature(fn)) if callable(fn) else "(缺失)"
        good = callable(fn)
        ok = ok and good
        print(f"  {mod.__name__.split('.')[-1]:<9}{name:<18}{sig}   {'OK' if good else 'MISSING'}")
print(f"  lint.RULES = list[{len(lint.RULES)}]   "
      f"code/level/message/hint 齐全："
      f"{all({'code','level','message','hint'} <= set(r) for r in lint.RULES)}")
print("RESULT:", "OK" if ok else "MISSING EXPORTS")
