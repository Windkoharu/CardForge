# -*- coding: utf-8 -*-
"""把「用户贴回来的官方卡文」再反解成 IR，看哪里丢信息。

用法::

    PYTHONIOENCODING=utf-8 python _probe/roundtrip.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardforge.content import effects as EF          # noqa: E402
from cardforge.content.psct import gen               # noqa: E402
from cardforge.core.models import CardSpec           # noqa: E402

TEXT = """包含「圣痕」怪兽的战士族怪兽×3
这张卡不能作为融合素材。
这张卡用融合召唤以及以下方法才能特殊召唤。
●把自己场上的上记的卡除外的场合可以从额外卡组特殊召唤。
①：1回合1次，以对方场上1张表侧表示的卡为对象才能发动。那张卡的效果直到回合结束时无效。这个效果在对方回合也能发动。
②：1回合1次，对方把怪兽的效果发动时，从卡组把1只战士族怪兽送去墓地才能发动。那个发动无效并破坏。
③：这张卡被战斗·效果破坏的场合才能发动。从自己墓地选1只「圣痕龙骑士 露米艾尔」以外的战士族怪兽特殊召唤。"""


def main() -> int:
    out = io.StringIO()
    got = EF.infer_from_text(TEXT, "圣痕龙骑士 露米艾尔")
    out.write(f"反解出 {len(got)} 条效果\n")
    for i, e in enumerate(got):
        out.write("-" * 60 + f"\n[{i}] kind={e.kind} trigger={e.trigger} limit={e.limit}\n")
        out.write("    target=" + json.dumps(
            e.target.to_dict() if e.target else None, ensure_ascii=False) + "\n")
        out.write("    cost=" + json.dumps(
            e.cost.to_dict() if e.cost else None, ensure_ascii=False) + "\n")
        out.write("    params=" + json.dumps(e.params, ensure_ascii=False) + "\n")
        out.write("    raw=" + str(e.raw_text)[:160] + "\n")
    # 再投影回卡文，看差异
    spec = CardSpec(id=210000999, name="圣痕龙骑士 露米艾尔", frame="effect",
                    attribute="光", race="战士族", level=8, atk=3000, dfd=2500,
                    archetype="圣痕", setcode="0x1000",
                    effects=[e.to_dict() for e in got])
    text2 = gen.compose(spec, "zh_cn")
    out.write("\n==== 反解后再投影 ====\n" + text2 + "\n")
    txt = out.getvalue()
    (ROOT / "_probe" / "roundtrip.txt").write_text(txt, encoding="utf-8")
    print(txt.encode("utf-8", "ignore").decode("utf-8", "ignore"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
