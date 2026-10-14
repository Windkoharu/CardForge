"""自测 10：object_info 缓存后的性能提升（同一进程内连续出两张）。"""
from __future__ import annotations

import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\游戏王DIY设计")

import cardforge.art as ART  # noqa: E402
from cardforge.core.models import ArtRequest, CardSpec  # noqa: E402
from cardforge.art.client import ComfyClient, object_info_cache_state  # noqa: E402

buf = io.StringIO()


def w(*a):
    print(*a, flush=True)
    print(*a, file=buf)


cli = ComfyClient()
card = CardSpec(id=970061, name="缓存测试", frame="effect", attribute="光",
                race="天使族", level=4, atk=1600, dfd=1200, archetype="_probe_perf")

w("=" * 78)
w("【自测 10】object_info 进程级缓存对 generate() 的影响")
w("=" * 78)
w("缓存前状态 :", object_info_cache_state())
w("")
for i in range(2):
    req = ArtRequest(card_id=card.id, archetype=card.archetype,
                     subject="一只发光的小天使", style="赛璐璐，柔光",
                     profile="auto", seed=330000 + i)
    t0 = time.time()
    stages = []

    def cb(info):
        stages.append((info.get("stage"), round(info.get("elapsed", 0), 2)))

    res = ART.generate(req, card=card, on_progress=cb)
    dt = time.time() - t0
    w(f"[{i}] generate() 墙钟 {dt:.2f} s | ok={res.ok} | took_ms={res.took_ms}")
    w(f"     阶段耗时: {stages}")
    if res.ok:
        w(f"     seed={res.meta['seed']} prompt_id={res.meta['prompt_id']} "
          f"图={[__import__('pathlib').Path(x).name for x in res.images]}")
    else:
        w(f"     error={res.error}")
w("")
w("缓存后状态 :", object_info_cache_state())

(ART.__dict__.get("__file__") and None)
out = r"D:\游戏王DIY设计\_probe\art\selftest_10.txt"
open(out, "w", encoding="utf-8").write(buf.getvalue())
print("\n-> written", out)
