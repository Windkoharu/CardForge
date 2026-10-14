"""验证"data/lexicons/ 缺失时引擎仍能工作"（内置兜底表）。

把 ``CARDFORGE_DATA`` 指向一个不存在的目录再导入，词库必须回落到内联兜底表，
且 zh_cn/ja/en 三种语言仍能拼出完整卡文。

用法::

    python _probe/psct/_fallback_only.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["CARDFORGE_DATA"] = str(ROOT / "_probe" / "psct" / "_no_such_data")
sys.path.insert(0, str(ROOT))

from cardforge.core import paths                                  # noqa: E402
from cardforge.content.psct import gen, lexicon                   # noqa: E402
from cardforge.core.models import (                               # noqa: E402
    CardSpec, EffectCost, EffectSpec, EffectTarget,
)


def main() -> int:
    print(f"CARDFORGE_DATA = {paths.DATA}")
    print(f"DATA 存在？{Path(paths.DATA).exists()}")
    print(f"lexicon.available() = {lexicon.available()}")
    print(f"sources = {lexicon.sources()}")
    print(f"内置兜底术语条数 = {len(lexicon.terms())}")
    for key in ("act_search", "race_dragon", "attr_dark", "zone_graveyard",
                "psct_then", "psct_hopt_name_each"):
        row = [lexicon.term(key, lg) for lg in ("zh_cn", "ja", "en")]
        print(f"  {key:<24} {row[0]} | {row[1]} | {row[2]}")
    print(f"ko 回落 = {lexicon.term_or_fallback('act_search', 'ko')}")
    print(f"conjunction('then','ja') = {lexicon.conjunction('then', 'ja')}")
    print(f"hopt('hopt_name_use','zh_cn') = {lexicon.hopt('hopt_name_use', 'zh_cn')}")

    spec = CardSpec(id=1, name="兜底测试龙", name_i18n={"ja": "フォールバック竜",
                                                       "en": "Fallback Dragon"},
                    frame="effect", attribute="炎", race="龙族", level=4,
                    atk=1800, dfd=1200,
                    effects=[EffectSpec(
                        kind="search", trigger="NORMAL_SUMMON_SUCCESS",
                        limit="hopt_name",
                        target=EffectTarget(filter_kind="race", filter_value="龙族",
                                            from_zone="DECK"),
                        params={"optional": True})])
    ok = True
    for lg in ("zh_cn", "ja", "en"):
        meta = gen.compose_with_meta(spec, lg)
        print(f"── {lg}（used={meta['used_lang']}，source={meta['box']}）")
        print(meta["text"])
        ok = ok and bool(meta["text"].strip())
    print(f"类型行 = {gen.type_line(spec, 'zh_cn')} | {gen.type_line(spec, 'ja')} "
          f"| {gen.type_line(spec, 'en')}")
    print("RESULT:", "OK（无 data/lexicons 也能生成三语卡文）" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
