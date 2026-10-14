"""自测 9：style_ref 与 remove_bg 两个预设真跑一遍（端到端）。"""
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
from cardforge.core.models import ArtRequest, CardSpec  # noqa: E402
from cardforge.art import run as R  # noqa: E402
from cardforge.art import presets as PS  # noqa: E402
from cardforge.art.client import ComfyClient  # noqa: E402

cli = ComfyClient()
schemas = cli.object_info()

w("=" * 78)
w("【自测 9a】style_ref 端到端：垫一张风格参考图真跑一遍")
w("=" * 78)
# 用自测 3 出的那张龙当风格参考
ref_local = ROOT / "workspace" / "pics" / "art" / "_probe_烬霞" / "970001" / "v1.png"
up = cli.upload(str(ref_local), subfolder="CardForge")
ref = up["ref"]
w("upload ->", json.dumps(up, ensure_ascii=False))

from cardforge.art import graph as G  # noqa: E402
from cardforge.art import prompt as PR  # noqa: E402

prof = R.resolve_profile("auto")
name, clip, vae = R._pick_model(prof, cli.models())
card = CardSpec(id=970051, name="风格参考测试", frame="effect", attribute="炎",
                race="龙族", level=4, atk=1600, dfd=1000, archetype="_probe_styleref")
req = ArtRequest(card_id=card.id, archetype=card.archetype, subject="一只灰色的小石像鬼",
                 style="赛璐璐，逆光", profile="auto", seed=440001)
pr = PR.build(req, card, prof, None)
g = G.build_style_ref(profile=prof, ckpt_or_unet=name, clip=clip, vae=vae,
                      positive=pr["positive"], negative=pr["negative"],
                      width=832, height=1216, seed=req.seed, steps=prof.steps,
                      cfg=prof.cfg, sampler=prof.sampler, scheduler=prof.scheduler,
                      style_refs=[ref], strength=0.8,
                      save_prefix="cardforge/probe_styleref",
                      available=set(schemas.keys()), schemas=schemas)
w("节点 :", [(k, v["class_type"]) for k, v in g.to_api().items()])
w("warnings :", g.warnings)
try:
    pid = cli.queue(g.to_api())
    t0 = time.time()
    entry = cli.wait(pid, timeout=600)
    w("耗时 %.2f s | prompt_id=%s" % (time.time() - t0, pid))
    files = cli.download_outputs(entry, OUT / "styleref")
    w("产物:", files)
except ComfyError as exc:
    w("失败 ❌", exc.kind, exc.message)
    w("hint:", exc.hint)

w("")
w("=" * 78)
w("【自测 9b】用 export_workflow 导出 style_ref，再 POST 回 /prompt")
w("=" * 78)
# 9b-1：不给真实参考图 → 应抛 PlaceholderRef（可执行的中文提示）
try:
    R.export_workflow("style_ref", str(OUT / "final_style_ref_submit.json"),
                      profile="auto", spec=card, submit=True)
    w("9b-1 没有抛异常（不应该）")
except R.PlaceholderRef as exc:
    w("9b-1 正确抛出 PlaceholderRef ✅")
    w("      kind :", exc.kind)
    w("      msg  :", exc.message)
    w("      hint :", exc.hint)
except ComfyError as exc:
    w("9b-1 抛了 ComfyError（kind=%s）❌ 期望 PlaceholderRef：%s" % (exc.kind, exc.message))

w("")
w("9b-2：给真实本地参考图（会被自动 upload）→ 应该能提交")
req_ref = ArtRequest(card_id=card.id, archetype=card.archetype,
                     subject="一只灰色的小石像鬼", style="赛璐璐，逆光",
                     profile="auto", seed=440777, style_refs=[str(ref_local)])
try:
    p = R.export_workflow("style_ref", str(OUT / "final_style_ref_submit.json"),
                          profile="auto", spec=card, request=req_ref, submit=True)
    w("export_workflow(submit=True) OK :", p)
    ui = json.loads(Path(p).read_text(encoding="utf-8"))
    w("placeholders :", ui["extra"]["cardforge"].get("placeholders"))
    w("LoadImage 节点 :", [n["widgets_values"] for n in ui["nodes"]
                          if n["type"] == "LoadImage"])
except ComfyError as exc:
    w("失败 ❌", exc.kind, exc.message)
    w("hint:", exc.hint)

w("")
w("=" * 78)
w("【自测 9c】remove_bg 预设：导出 + 提交（用已 upload 的真实图）")
w("=" * 78)
try:
    req_bg = ArtRequest(card_id=card.id, profile="auto", seed=1)
    p = R.export_workflow("remove_bg", str(OUT / "final_remove_bg.json"),
                          profile="auto", spec=card)
    w("导出的占位符 :",
      json.loads(Path(p).read_text(encoding="utf-8"))["extra"]["cardforge"].get("placeholders"))
    # 用真实图手动提交一次（把 LoadImage 的占位名换成刚上传的 ref）
    up2 = cli.upload(str(ROOT / "_probe" / "art" / "removebg" / "probe_removebg_00003_.png"),
                     subfolder="CardForge")
    ui = json.loads(Path(p).read_text(encoding="utf-8"))
    for n in ui["nodes"]:
        if n["type"] == "LoadImage":
            n["widgets_values"] = [up2["ref"], "image"]
    api = G.ui_to_api(ui, schemas)
    probs = G.validate(api, schemas)
    w("替换占位图后自检 :", probs or "通过")
    pid = cli.queue(api)
    t0 = time.time()
    entry = cli.wait(pid, timeout=600)
    files = cli.download_outputs(entry, OUT / "removebg")
    w("remove_bg 提交成功 ✅ 耗时 %.2f s | 产物 %s" % (time.time() - t0, files))
except ComfyError as exc:
    w("失败 ❌", exc.kind, exc.message)

w("")
w("=" * 78)
w("【自测 9d】修正后的 by_capability")
w("=" * 78)
for row in PS.by_capability(R.capabilities()):
    w(f"  {row['key']:22s} available={str(row['available']):5s} {row['reason']}")

(OUT / "selftest_9.txt").write_text(buf.getvalue(), encoding="utf-8")
print("\n-> written", OUT / "selftest_9.txt")
