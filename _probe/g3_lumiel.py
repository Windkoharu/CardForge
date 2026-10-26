# -*- coding: utf-8 -*-
"""把「圣痕龙骑士 露米艾尔」送进真 ocgcore 跑 G3（场景 + bot 对局）。

用法::

    PYTHONIOENCODING=utf-8 python _probe/g3_lumiel.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardforge.duel import engine  # noqa: E402
from cardforge.pipeline import gates  # noqa: E402

sys.path.insert(0, str(ROOT / "_probe"))
from build_lumiel import build  # noqa: E402


def main() -> int:
    out = io.StringIO()
    st = engine.detect()
    out.write(f"引擎：level={getattr(st, 'level', '?')} "
              f"desc={getattr(st, 'description', '') or getattr(st, 'reason', '')}\n")
    spec = build()
    from cardforge.content.lua import emit
    spec.lua = emit.emit_script(spec, tier=1)
    rep = gates.g3_duel(spec, scenario=True, duels=6)
    out.write(f"\nG3 status={rep.status} degraded={rep.degraded}\n")
    out.write(f"summary={rep.summary}\n")
    out.write(f"detail={getattr(rep, 'detail', '')}\n")
    for i in rep.issues:
        out.write(f"  [{i.level}] {i.code}: {i.message}\n")
    text = out.getvalue()
    (ROOT / "_probe" / "g3_lumiel.txt").write_text(text, encoding="utf-8")
    print(text.encode("utf-8", "ignore").decode("utf-8", "ignore")[:1200])
    return 0 if rep.status in ("pass", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
