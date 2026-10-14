"""自测 8（附加）：把其余预设与代码路径全部跑一遍。

* generate_series（系列批量，每张换 seed + 风格前缀冻结）
* t2i + upscale（本机有 3 个放大模型）
* t2i + remove_bg（走 generate 的 remove_bg 分支）
* style_ref / character_sheet / upscale / remove_bg / inpaint_edit / ipadapter 的 export_workflow
* preset() / describe_all() / by_capability() / postprocess() / library rollback
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"D:\游戏王DIY设计")
sys.path.insert(0, str(ROOT))
OUT = ROOT / "_probe" / "art"
buf = io.StringIO()


def w(*a):
    print(*a, flush=True)
    print(*a, file=buf)


from cardforge.core.errors import ComfyError  # noqa: E402
from cardforge.core.models import Archetype, ArtRequest, CardSpec  # noqa: E402
from cardforge.art import run as R  # noqa: E402
from cardforge.art import graph as G  # noqa: E402
from cardforge.art import presets as PS  # noqa: E402
from cardforge.art import library as L  # noqa: E402
from cardforge.art.client import ComfyClient, bump_seed  # noqa: E402

cli = ComfyClient()
models = cli.models()
schemas = cli.object_info()

# ══════════════════════════════════════════════════════════════════════
w("=" * 78)
w("【自测 8a】generate_series：系列批量（风格前缀冻结 + 每张换 seed）")
w("=" * 78)
arch = Archetype(name="_probe_烬霞", concept="熔岩与灰烬的龙族，赛璐璐，逆光，史诗",
                 binding={"attribute": "炎", "race": "龙族"}, setcode="0x9a1")
cards = [
    CardSpec(id=970011, name="烬霞龙·幼体", frame="effect", attribute="炎",
             race="龙族", level=4, atk=1800, dfd=1200, archetype=arch.name),
    CardSpec(id=970012, name="烬霞龙·煌炎", frame="fusion", attribute="炎",
             race="龙族", level=8, atk=2800, dfd=2000, archetype=arch.name),
]
base = ArtRequest(archetype=arch.name, preset="t2i_series", profile="auto",
                  subject="一条龙", seed=990001)
t0 = time.time()
seen_seeds = []


def cb(info):
    if info.get("state") == "done":
        seen_seeds.append(info.get("seed"))


res = R.generate_series(arch, cards, base,
                        on_progress=lambda i: (seen_seeds.append(i.get("seed"))
                                               if i.get("stage") == "graph" else None))
w("批次耗时 : %.2f s" % (time.time() - t0))
for i, (c, r) in enumerate(zip(cards, res)):
    w(f"  [{i}] card_id={c.id} name={c.display_name} ok={r.ok} "
      f"seed={r.meta.get('seed') if r.meta else '-'} took={r.took_ms}ms")
    if r.ok:
        w(f"       series_style = {r.meta['series_style'][:120]}")
        w(f"       images = {[Path(x).name for x in r.images]}")
    else:
        w(f"       error = {r.error}")
seeds = [r.meta.get("seed") for r in res if r.meta]
w("每张 seed 都不同?", len(set(seeds)) == len(seeds), seeds)
ss = [r.meta.get("series_style") for r in res if r.meta]
w("风格前缀是否冻结（两张一致）?", len(set(ss)) == 1 if len(ss) > 1 else "只有一张")

# ══════════════════════════════════════════════════════════════════════
w("")
w("=" * 78)
w("【自测 8b】t2i + upscale（本机放大模型：%s）" % models.get("upscale"))
w("=" * 78)
req_up = ArtRequest(card_id=970021, archetype="_probe_upscale",
                    subject="一座漂浮在星空中的水晶神殿", style="神圣，体积光",
                    profile="auto", seed=770001, upscale=True)
card_up = CardSpec(id=970021, name="星穹神殿", frame="spell", spell_kind="field",
                   attribute="光", race="", archetype="_probe_upscale")
t0 = time.time()
r_up = R.generate(req_up, card=card_up)
w("ok =", r_up.ok, "| 耗时 %.2f s" % ((time.time() - t0)))
if r_up.ok:
    w("images :", r_up.images)
    w("节点 :", [(k, v["class_type"]) for k, v in r_up.workflow.items()])
    from PIL import Image
    with Image.open(r_up.images[0]) as im:
        w("尺寸 :", im.size, "（放大到 4x 再降采样到 842×1228）")
    w("warnings :", r_up.meta.get("warnings"))
else:
    w("error :", r_up.error, "|", r_up.hint)

# ══════════════════════════════════════════════════════════════════════
w("")
w("=" * 78)
w("【自测 8c】t2i + remove_bg（走 generate 的 remove_bg 分支）")
w("=" * 78)
req_rb = ArtRequest(card_id=970022, archetype="_probe_removebg",
                    subject="一只发光的白色小精灵，翅膀半透明",
                    style="赛璐璐，柔光", profile="auto", seed=770101, remove_bg=True)
card_rb = CardSpec(id=970022, name="辉光妖精", frame="effect", attribute="光",
                   race="天使族", level=3, atk=800, dfd=600, archetype="_probe_removebg")
t0 = time.time()
r_rb = R.generate(req_rb, card=card_rb)
w("ok =", r_rb.ok, "| 耗时 %.2f s" % (time.time() - t0))
if r_rb.ok:
    w("images :", r_rb.images)
    w("节点 :", [(k, v["class_type"]) for k, v in r_rb.workflow.items()])
    import numpy as np
    from PIL import Image
    with Image.open(r_rb.images[0]) as im:
        w("mode :", im.mode, "size :", im.size)
        if im.mode == "RGBA":
            a = np.array(im)[..., 3].reshape(-1)
            t = a.size
            w("alpha: 全透明 %.2f%% | 不透明 %.2f%% | 半透明 %.2f%%"
              % (100 * (a == 0).sum() / t, 100 * (a == 255).sum() / t,
                 100 * ((a > 0) & (a < 255)).sum() / t))
else:
    w("error :", r_rb.error, "|", r_rb.hint)

# ══════════════════════════════════════════════════════════════════════
w("")
w("=" * 78)
w("【自测 8d】其余预设的 export_workflow（只建图导出，不提交）")
w("=" * 78)
card3 = CardSpec(id=970031, name="测试", frame="fusion", attribute="暗",
                 race="魔法师族", level=8, atk=2500, dfd=2000, archetype="_probe_烬霞")
# 准备 inpaint 需要的 input 图与 mask
up = cli.upload(str(ROOT / "_probe" / "art" / "removebg" / "probe_removebg_00003_.png"),
                subfolder="CardForge")
w("upload 用于 inpaint :", json.dumps(up, ensure_ascii=False))
from PIL import Image, ImageDraw  # noqa: E402

mask_path = OUT / "inpaint_mask.png"
m = Image.new("L", (832, 1216), 0)
ImageDraw.Draw(m).ellipse((300, 400, 560, 700), fill=255)
m.save(mask_path)
up2 = cli.upload(str(mask_path), subfolder="CardForge")
w("upload mask :", json.dumps(up2, ensure_ascii=False))

for key in PS.keys():
    dst = OUT / f"workflow_{key}.json"
    try:
        req_i = ArtRequest(card_id=card3.id, archetype=card3.archetype, profile="auto",
                           seed=660001, subject="一只暗紫色的魔法师，手持发光法杖",
                           style="厚涂，戏剧性光照")
        kw = {}
        if key == "inpaint_edit":
            kw = {"request": req_i}
        p = R.export_workflow(key, str(dst), profile="auto", spec=card3, **kw)
        ui = json.loads(Path(p).read_text(encoding="utf-8"))
        api = G.ui_to_api(ui, schemas)
        probs = G.validate(api, schemas)
        w(f"  {key:22s} OK  节点={len(ui['nodes']):3d} 连线={len(ui['links']):3d} "
          f"自检={'通过' if not probs else probs}")
    except (ComfyError, KeyError) as exc:
        kind = getattr(exc, "kind", "KeyError")
        w(f"  {key:22s} 失败 kind={kind}")
        w(f"      msg  : {getattr(exc, 'message', exc)}")
        w(f"      hint : {getattr(exc, 'hint', '')}"[:400])

# ══════════════════════════════════════════════════════════════════════
w("")
w("=" * 78)
w("【自测 8e】presets / by_capability / postprocess / library rollback")
w("=" * 78)
ps = PS.preset("t2i_single")
w("preset('t2i_single') 键:", sorted(ps.keys()))
w("preset 是深拷贝?", PS.preset("t2i_single") is not PS.PRESETS["t2i_single"])
caps = R.capabilities()
for row in PS.by_capability(caps):
    w(f"  {row['key']:22s} available={str(row['available']):5s} {row['reason']}")

# postprocess
src = ROOT / "workspace" / "pics" / "art" / "_probe_烬霞" / "970001" / "v1.png"
pp = R.postprocess(str(src), target=(842, 1228))
w("postprocess:", json.dumps(pp, ensure_ascii=False))
pp2 = R.postprocess(str(src), target=(421, 614), flatten=True,
                    out=str(OUT / "pp_421x614.jpg"))
w("postprocess+flatten:", json.dumps(pp2, ensure_ascii=False))

# library
w("library.versions(970001):",
  json.dumps([{k: v[k] for k in ("version", "bytes", "is_current")}
              for v in L.versions(970001, "_probe_烬霞")], ensure_ascii=False))
w("library.current(970001):", json.dumps(L.current(970001, "_probe_烬霞"), ensure_ascii=False))
rb = L.rollback(970001, 1, "_probe_烬霞")
w("rollback -> v1:", json.dumps(rb, ensure_ascii=False))
L.set_current(970001, 2, "_probe_烬霞")
w("set_current -> v2 restored")
w("list_all():")
for row in L.list_all():
    w("   ", json.dumps({k: row[k] for k in ("card_id", "archetype", "versions", "version")},
                        ensure_ascii=False))

(OUT / "selftest_8.txt").write_text(buf.getvalue(), encoding="utf-8")
print("\n-> written", OUT / "selftest_8.txt")
