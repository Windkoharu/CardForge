"""自测 1–2：alive / models / detect 真实输出。结果写 UTF-8 文件避免控制台乱码。"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "_probe" / "art"
OUT.mkdir(parents=True, exist_ok=True)
buf = io.StringIO()


def w(*a):
    print(*a)
    print(*a, file=buf)


from cardforge.art.client import ComfyClient, bump_seed, new_seed  # noqa: E402
from cardforge.art import profiles as PF  # noqa: E402

c = ComfyClient()
w("=" * 78)
w("【自测 1】client.alive() / models()")
w("=" * 78)
w("alive() =", c.alive())
summ = c.summary()
w("summary  =", json.dumps(summ, ensure_ascii=False))
m = c.models()
w("")
w("models() 实际清单（来自 /object_info 的 COMBO 候选）：")
for k in sorted(m):
    v = m[k]
    w(f"  {k:20s} n={len(v)}")
    for name in v:
        w(f"      - {name}")

w("")
w("=" * 78)
w("【自测 2】detect(models)")
w("=" * 78)
info = PF.detect_explain(m)
w("选中档案 :", info["key"], "|", info["zh"])
w("链路     :", info["chain"])
w("原因     :", info["reason"])
w("参数     : steps=%s cfg=%s sampler=%s scheduler=%s size=%s"
  % (info["steps"], info["cfg"], info["sampler"], info["scheduler"], info["size"]))
w("负向有效 :", info["negative_effective"])
w("候选底模 :", info["candidates"])
w("被跳过的非图像模型 :", info.get("skipped_non_image"))
w("")
w("全部档案的可用性：")
for p in PF.PROFILES:
    hit = [n for n in (m.get("unets") or []) + (m.get("checkpoints") or [])
           if PF.match_profile(n) is p]
    w(f"  {p.key:12s} {p.zh:34s} chain={p.chain:6s} "
      f"{'可用: ' + ','.join(hit) if hit else '本机无匹配权重'}")

w("")
w("bump_seed 演示（连续 5 张）：")
s = 12345
seq = []
for _ in range(5):
    s = bump_seed(s)
    seq.append(s)
w("  ", seq)

(OUT / "selftest_1_2.txt").write_text(buf.getvalue(), encoding="utf-8")
print("\n-> written", OUT / "selftest_1_2.txt")
