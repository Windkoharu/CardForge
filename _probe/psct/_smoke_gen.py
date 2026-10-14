"""gen.py 冒烟：手搓几张卡看输出形状（开发期临时脚本）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cardforge.core.models import (  # noqa: E402
    CardSpec, EffectCost, EffectSpec, EffectTarget,
)
from cardforge.content.psct import gen  # noqa: E402


def main() -> int:
    out = []
    spec = CardSpec(
        id=1, name="苍岚的守护龙", name_i18n={"ja": "蒼嵐の守護竜", "en": "Azure Gale Guardian Dragon"},
        frame="effect", attribute="风", race="龙族", level=4, atk=1800, dfd=1500,
        archetype="苍岚",
        effects=[
            EffectSpec(
                kind="search", trigger="NORMAL_SUMMON_SUCCESS", limit="hopt_name",
                target=EffectTarget(filter_kind="archetype", filter_value="苍岚",
                                    from_zone="DECK"),
                params={"optional": True},
            ),
            EffectSpec(
                kind="ssummon_grave", trigger="IGNITION", limit="once_per_turn",
                target=EffectTarget(from_zone="GRAVE", filter_kind="archetype",
                                    filter_value="苍岚"),
                cost=EffectCost(kind="discard", zone="HAND", count=1),
            ),
        ],
    )
    for lang in ("zh_cn", "ja", "en"):
        m = gen.compose_with_meta(spec, lang)
        out.append(f"── {lang} (used={m['used_lang']}, lines={m['lines']}/{m['max_lines']}) ──")
        out.append(m["text"])
        out.append(f"notes={m['notes']}")
        out.append("")
    out.append("type_line zh/ja/en: " + " | ".join(
        gen.type_line(spec, lg) for lg in ("zh_cn", "ja", "en")))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
