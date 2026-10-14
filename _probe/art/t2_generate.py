"""自测 3+4：真出两张卡图（无 LoRA / 挂 krea2_flat_cel_anime），并统计对比。

结果写 UTF-8 文件；图存到 _probe/art/。
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "_probe" / "art"
OUT.mkdir(parents=True, exist_ok=True)
buf = io.StringIO()


def w(*a):
    print(*a, flush=True)
    print(*a, file=buf)


from cardforge.core.models import ArtRequest, CardSpec  # noqa: E402
from cardforge.art import run as R  # noqa: E402
from cardforge.art import prompt as PR  # noqa: E402
from cardforge.art import profiles as PF  # noqa: E402
from cardforge.art import library as L  # noqa: E402
from cardforge.art import graph as G  # noqa: E402

# ── 造一张融合怪兽卡（用于卡种氛围词测试）──
card = CardSpec(
    id=970001, name="烬霞龙·煌炎", frame="fusion", attribute="炎",
    race="龙族", level=8, atk=2800, dfd=2000, archetype="_probe_烬霞",
)
card.text_i18n = {"zh_cn": "「测试用」怪兽2只\n①：这张卡特殊召唤成功时才能发动。给对方2000伤害。"}
print("card:", card.summary())

req = ArtRequest(
    card_id=card.id, archetype=card.archetype,
    subject=("一条巨大的黑曜石鳞片古龙，双翼张开，龙角燃着金色火焰，"
             "胸口有熔岩裂纹，竖直瞳孔发红光，正踏在崩塌的浮空石台上"),
    style="赛璐璐，逆光，戏剧性光照，史诗",
    preset="t2i_single", profile="auto", seed=777001,
)

# ── 3a. 无 LoRA ──
w("=" * 78)
w("【自测 3】Krea 2 真出图（832×1216 / 8 步 / cfg 1.0，无 LoRA）")
w("=" * 78)
t0 = time.time()
res = R.generate(req, card=card, on_progress=lambda i: print("  progress:", i, flush=True))
w("ok        :", res.ok)
w("took_ms   :", res.took_ms, f"({res.took_ms/1000:.2f} s)")
w("images    :", res.images)
if not res.ok:
    w("error     :", res.error)
    w("hint      :", res.hint)
    (OUT / "selftest_3_4.txt").write_text(buf.getvalue(), encoding="utf-8")
    sys.exit(1)
m = res.meta
w("profile   :", m["profile"], "|", m["profile_zh"], "| chain =", m["chain"])
w("model     :", m["model"], "| clip =", m["clip"], "| vae =", m["vae"])
w("size      :", m["width"], "x", m["height"], "| steps =", m["steps"],
  "| cfg =", m["cfg"], "| sampler =", m["sampler"], "| scheduler =", m["scheduler"])
w("seed      :", m["seed"], "| prompt_id =", m["prompt_id"])
w("fingerprint:", m["workflow_fingerprint"])
w("warnings  :", m["warnings"])
w("")
w("--- 实际正向提示词 ---")
w(m["positive"])
w("")
w("--- 实际负向提示词（cfg=1 时不生效，仅记录）---")
w(m["negative"][:400], "...")
w("")
w("--- 提示词 notes ---")
w(m["notes"])
w("")
w("--- 节点结构 ---")
for k, v in res.workflow.items():
    ins = {kk: ("<-" + vv[0] if isinstance(vv, list) else vv)
           for kk, vv in v["inputs"].items()}
    w(f"  [{k:>3}] {v['class_type']:28s} {json.dumps(ins, ensure_ascii=False)}")

img1 = res.images[0]
w("")
w("入库结果：")
for row in L.list_all(card.archetype):
    if row["card_id"] == card.id:
        w("  ", json.dumps({k: row[k] for k in ("card_id", "archetype", "versions",
                                                "version", "current")},
                           ensure_ascii=False))

# ── 4. 挂 LoRA ──
w("")
w("=" * 78)
w("【自测 4】同一提示词 + 风格 LoRA krea2_flat_cel_anime.safetensors:0.8")
w("=" * 78)
req4 = ArtRequest(**req.to_dict())
req4.loras = ["krea2_flat_cel_anime.safetensors:0.8"]
req4.seed = req.seed          # 刻意用同一个 seed，只变 LoRA
t1 = time.time()
res4 = R.generate(req4, card=card, on_progress=lambda i: None)
w("ok        :", res4.ok)
w("took_ms   :", res4.took_ms, f"({res4.took_ms/1000:.2f} s)")
w("images    :", res4.images)
if res4.ok:
    w("loras     :", res4.meta["loras"])
    w("nodes     :", len(res4.workflow), "节点")
    lora_nodes = [v for v in res4.workflow.values()
                  if v["class_type"] == "LoraLoaderModelOnly"]
    for ln in lora_nodes:
        w("  LoraLoaderModelOnly ->", json.dumps(ln["inputs"], ensure_ascii=False))
    img2 = res4.images[0]
    # 像素级对比
    cmp = L.compare(card.id, 1, 2, card.archetype)
    w("像素差统计:", json.dumps(cmp["stats"], ensure_ascii=False))
    w("并排图    :", cmp["sbs"])
    w("差异热力图:", cmp["diff"])
else:
    w("error:", res4.error, "| hint:", res4.hint)

(OUT / "selftest_3_4.txt").write_text(buf.getvalue(), encoding="utf-8")
json.dump({"img_no_lora": img1,
           "img_with_lora": (res4.images[0] if res4.ok else ""),
           "took_no_lora_ms": res.took_ms,
           "took_lora_ms": (res4.took_ms if res4.ok else 0)},
          open(OUT / "selftest_3_4.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("\n-> written", OUT / "selftest_3_4.txt")
