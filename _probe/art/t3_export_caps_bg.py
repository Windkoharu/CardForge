"""自测 5+6+7：
5) 导出 t2i_single 的 workflow JSON → 再 POST 回 /prompt 真跑一遍
6) capabilities() + 故意传不存在的模型名断言 ComfyError(kind="model_missing")
7) 抠底链路（拿自测 3 的图跑 remove_bg，检查 alpha 通道）
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
OUT.mkdir(parents=True, exist_ok=True)
buf = io.StringIO()


def w(*a):
    print(*a, flush=True)
    print(*a, file=buf)


from cardforge.core.errors import ComfyError  # noqa: E402
from cardforge.core.models import ArtRequest, CardSpec  # noqa: E402
from cardforge.art import run as R  # noqa: E402
from cardforge.art import graph as G  # noqa: E402
from cardforge.art import presets as PS  # noqa: E402
from cardforge.art.client import ComfyClient  # noqa: E402

card = CardSpec(id=970003, name="测试用卡", frame="fusion", attribute="炎",
                race="龙族", level=8, atk=2800, dfd=2000, archetype="_probe_烬霞")
cli = ComfyClient()
schemas = cli.object_info()

# ══════════════════════════════════════════════════════════════════════
w("=" * 78)
w("【自测 5】导出 t2i_single 的 UI 格式 workflow JSON，并把它 POST 回 /prompt 跑一遍")
w("=" * 78)
wf_path = OUT / "workflow_t2i.json"
req = ArtRequest(card_id=card.id, archetype=card.archetype,
                 subject="一只银白色的独角兽，角上缠绕着青色符文，站在花田里",
                 style="水彩，柔光，治愈", profile="auto", seed=880001)
t0 = time.time()
p = R.export_workflow("t2i_single", str(wf_path), profile="auto", spec=card, request=req)
w("导出路径 :", p)
w("导出耗时 : %.2f s" % (time.time() - t0))
ui = json.loads(Path(p).read_text(encoding="utf-8"))
w("根字段   :", sorted(ui.keys()))
w("version  :", ui["version"])
w("节点数   :", len(ui["nodes"]), "| 连线数:", len(ui["links"]),
  "| last_node_id:", ui["last_node_id"], "| last_link_id:", ui["last_link_id"])
w("")
w("--- 每个节点的 widgets_values（纯值数组，注意 seed 后的 control_after_generate 占位）---")
for n in ui["nodes"]:
    wv = json.dumps(n["widgets_values"], ensure_ascii=False)
    if len(wv) > 130:
        wv = wv[:127] + "..."
    w(f"  id={n['id']:>2} order={n['order']:>2} {n['type']:<28} widgets={wv}")
w("")
w("--- links（数组式 [id, origin_id, origin_slot, target_id, target_slot, type]）---")
for lk in ui["links"]:
    w("  ", lk)
w("")
w("--- README ---")
readmes = sorted(OUT.glob("README_*.md"))
for rm in readmes:
    w("  ", rm.name, f"({rm.stat().st_size} bytes)")

# 关键验证：ui_to_api(ui) 是否等于原始 API 图
ui2api = G.ui_to_api(ui, schemas)
problems = G.validate(ui2api, schemas)
w("")
w("ui_to_api 自检 :", problems or "通过（无问题）")
w("ui_to_api 节点数:", len(ui2api))

# ══════════════════════════════════════════════════════════════════════
w("")
w("=" * 78)
w("【自测 5b】把导出的工作流 POST 回 /prompt 真跑一遍（这是真正的验证）")
w("=" * 78)
w("--- 5b-1：ui_to_api(导出的 JSON) 与原始 API 图逐字段对比 ---")
# 原始 API 图：用导出时的同一套参数重建
prof = R.resolve_profile("auto")
name, clip, vae = R._pick_model(prof, cli.models())
from cardforge.art import prompt as PR  # noqa: E402

pr = PR.build(req, card, prof, None)
w0, h0 = 832, 1216
g_src = G.build_t2i(profile=prof, ckpt_or_unet=name, clip=clip, vae=vae,
                    positive=pr["positive"], negative=pr["negative"],
                    width=w0, height=h0, seed=880001, steps=prof.steps, cfg=prof.cfg,
                    sampler=prof.sampler, scheduler=prof.scheduler, loras=[],
                    save_prefix="cardforge/t2i_single",
                    available=set(schemas.keys()), schemas=schemas)
api_src = g_src.to_api()
w("原始 API 图节点数 :", len(api_src), "| ui_to_api 节点数:", len(ui2api))
diff_fields = 0
for nid, node in api_src.items():
    got = ui2api.get(nid)
    if got is None:
        w(f"  节点 {nid} 在 ui_to_api 里缺失 ❌")
        diff_fields += 1
        continue
    if got["class_type"] != node["class_type"]:
        w(f"  节点 {nid} class_type 不一致：{got['class_type']} != {node['class_type']} ❌")
        diff_fields += 1
    for k, v in node["inputs"].items():
        gv = got["inputs"].get(k, "<缺失>")
        # 连线在 UI 里被拆成 links，比的是 [src, slot]
        if isinstance(v, list) and isinstance(gv, list) and list(v) == list(gv):
            continue
        if v != gv:
            w(f"  节点 {nid} 输入 {k}: 原={v!r} 还原={gv!r} ❌")
            diff_fields += 1
w("往返差异字段数 :", diff_fields, "✅ 完全一致" if diff_fields == 0 else "❌ 有差异")

w("")
w("--- 5b-2：POST ui_to_api 的结果到 /prompt，真跑一遍 ---")
try:
    pid = cli.queue(ui2api, client_id=cli.client_id)
    w("POST /prompt 成功, prompt_id =", pid)
    t0 = time.time()
    entry = cli.wait(pid, timeout=600)
    outs = []
    for _nid, no in (entry.get("outputs") or {}).items():
        for img in no.get("images") or []:
            outs.append(img)
    w("耗时 : %.2f s" % (time.time() - t0))
    w("history.outputs :", json.dumps(outs, ensure_ascii=False))
    if outs:
        blob = cli.view(outs[0]["filename"], outs[0]["subfolder"], outs[0]["type"])
        dst = OUT / f"from_exported_workflow_{outs[0]['filename']}"
        dst.write_bytes(blob)
        w("已下载 :", dst, f"({len(blob)} bytes)")
        w("=> 导出的工作流能被 ComfyUI 跑通 ✅")
except ComfyError as exc:
    w("POST /prompt 失败 ❌")
    w("  kind :", exc.kind)
    w("  msg  :", exc.message)
    w("  hint :", exc.hint)
    w("  detail:", json.dumps(exc.detail, ensure_ascii=False)[:1500])

w("")
w("--- 5b-3：export_workflow(submit=True) 这条代码路径也走一遍 ---")
req_sub = ArtRequest(**req.to_dict())
req_sub.seed = 880123
try:
    p2 = R.export_workflow("t2i_single", str(OUT / "workflow_t2i_submit.json"),
                           profile="auto", spec=card, request=req_sub, submit=True)
    w("export_workflow(submit=True) 成功 :", p2)
    w("对应用例 : export_workflow(submit=True) 已把工作流转回 API 并提交，未抛异常 ✅")
except ComfyError as exc:
    w("export_workflow(submit=True) 失败 ❌", exc.kind, exc.message, "|", exc.hint)

# ══════════════════════════════════════════════════════════════════════
w("")
w("=" * 78)
w("【自测 6】capabilities() + 不存在的模型名断言")
w("=" * 78)
caps = R.capabilities()
w("online          :", caps["online"])
w("summary         :", json.dumps(caps["summary"], ensure_ascii=False))
w("active_profile  :", caps["active_profile"], "|", caps["active_profile_zh"])
w("profile_reason  :", caps["profile_reason"])
w("ready           :", caps["ready"])
w("node_total      :", caps["nodes"].get("node_total"))
w("missing_models  :", json.dumps(caps["missing_models"], ensure_ascii=False))
w("degraded        :")
for d in caps["degraded"]:
    w("   -", d)
w("bg_nodes        :", caps["bg_nodes"])
w("upscale_models  :", caps["upscale_models"])
w("loras_krea2     :", len(caps["loras_krea2"]))
w("")
w("档案可用性：")
for pr in caps["profiles"]:
    w(f"  {pr['key']:12s} usable={str(pr['usable']):5s} {pr['reason']}")
w("")
w("预设：")
for ps in caps["presets"]:
    w(f"  {ps['key']:22s} {ps['zh']}")
w("")
w("upgrade_paths:")
for u in caps["upgrade_paths"]:
    w("   -", u)

w("")
w("--- 方式 A：generate() 返回 ok=False + meta['kind']（符合降级约定）---")
import cardforge.art.run as RR  # noqa: E402

bad = ArtRequest(card_id=0, subject="whatever", profile="krea2",
                 seed=1, width=832, height=1216)
orig = RR._pick_model
RR._pick_model = lambda prof, models: ("THIS_MODEL_DOES_NOT_EXIST.safetensors", "", "")
try:
    res = R.generate(bad, card=None)
    w("结果 ok =", res.ok)
    w("error   :", res.error)
    w("hint    :", res.hint)
    w("kind    :", (res.meta or {}).get("kind"))
    assert res.ok is False, "应该失败"
    assert (res.meta or {}).get("kind") == "model_missing", \
        f"kind 应为 model_missing，实际 {(res.meta or {}).get('kind')}"
    w("断言通过：ok=False 且 kind == 'model_missing' ✅")
    w("hint 是中文 :", any('\u4e00' <= c <= '\u9fff' for c in res.hint), "✅")
except AssertionError as exc:
    w("断言失败 ❌", exc)

w("")
w("--- 方式 B：raise_on_error=True → 抛 ComfyError(kind='model_missing') ---")
try:
    R.generate(bad, card=None, raise_on_error=True)
    w("没有抛异常 ❌")
except ComfyError as exc:
    w("kind :", exc.kind)
    w("msg  :", exc.message)
    w("hint :", exc.hint)
    try:
        assert exc.kind == "model_missing", f"kind 应为 model_missing，实际 {exc.kind}"
        assert any('\u4e00' <= c <= '\u9fff' for c in exc.hint), "hint 必须是中文"
        w("断言通过：ComfyError(kind='model_missing') + 中文 hint ✅")
    except AssertionError as ae:
        w("断言失败 ❌", ae)
finally:
    RR._pick_model = orig

w("")
w("--- 方式 C：直接调 _strict_models 看抛出的 ComfyError ---")
try:
    RR._strict_models(cli, RR.resolve_profile("krea2"), "NOPE.safetensors", "", "", [])
except ComfyError as exc:
    w("kind :", exc.kind)
    w("msg  :", exc.message)
    w("hint :", exc.hint)
    assert exc.kind == "model_missing"
    assert any('\u4e00' <= c <= '\u9fff' for c in exc.hint)
    w("断言通过：ComfyError(kind='model_missing') + 中文 hint ✅")

# ══════════════════════════════════════════════════════════════════════
w("")
w("=" * 78)
w("【自测 7】抠底链路：拿自测 3 的图跑 remove_bg")
w("=" * 78)
src_img = ROOT / "workspace" / "pics" / "art" / "_probe_烬霞" / "970001" / "v1.png"
w("源图 :", src_img, src_img.exists())
up = cli.upload(str(src_img), subfolder="CardForge")
w("upload ->", json.dumps(up, ensure_ascii=False))
ref = up.get("ref") or up.get("name")
# 只用 output 里的文件名给 LoadImage（ComfyUI 的 LoadImage 读 input/ 目录）
from cardforge.art import graph as GG  # noqa: E402

g = GG.build_remove_bg(image=ref, model="BiRefNet_toonout",
                       save_prefix="cardforge/probe_removebg",
                       available=set(schemas.keys()), schemas=schemas,
                       local_models=list(cli.models().get("background_removal") or []))
w("抠底图节点 :", [(k, v["class_type"]) for k, v in g.to_api().items()])
w("warnings   :", g.warnings)
w("background_removal 候选 :", cli.models().get("background_removal"))
for k, v in g.to_api().items():
    w(f"   [{k}] {v['class_type']:28s}", json.dumps(v["inputs"], ensure_ascii=False))
try:
    pid = cli.queue(g.to_api())
    w("queued     :", pid)
    t0 = time.time()
    entry = cli.wait(pid, timeout=600)
    w("耗时       : %.2f s" % (time.time() - t0))
    files = cli.download_outputs(entry, OUT / "removebg")
    w("产物       :", files)
    for f in files:
        from PIL import Image
        import numpy as np
        with Image.open(f) as im:
            w("  ", Path(f).name, "mode =", im.mode, "size =", im.size)
            if im.mode in ("RGBA", "LA"):
                rgba = im.convert("RGBA")
                arr = np.array(rgba)[..., 3].reshape(-1)
                total = arr.size
                zero = int((arr == 0).sum())
                full = int((arr == 255).sum())
                mid = total - zero - full
                w("      alpha: 全透明(0)=%d (%.2f%%) | 不透明(255)=%d (%.2f%%) | 半透明=%d (%.2f%%)"
                  % (zero, 100 * zero / total, full, 100 * full / total,
                     mid, 100 * mid / total))
                # 极性判定：主体应当是不透明的那一侧
                lum = np.array(rgba.convert("RGB"), dtype=np.float32).mean(axis=2)
                a2 = np.array(rgba)[..., 3]
                lo = lum[a2 <= 5].mean() if (a2 <= 5).any() else float("nan")
                hi = lum[a2 >= 250].mean() if (a2 >= 250).any() else float("nan")
                w("      透明区平均亮度=%.1f | 不透明区平均亮度=%.1f" % (lo, hi))
                w("      背景透明?", "是 ✅" if zero / total > 0.02 else "否 ❌（alpha 全不透明）")
                # 边缘质量：半透明像素占比过高说明是「软 mask 铺满整图」而不是真抠图
                w("      边缘带占比 %.2f%%" % (100 * mid / total),
                  "（正常 2%–15%；>40% 说明 mask 是灰度渐变而非二值前景）")
            else:
                w("      ⚠️ 没有 alpha 通道")
except ComfyError as exc:
    w("抠底失败 ❌", exc.kind, exc.message)
    w("hint:", exc.hint)

(OUT / "selftest_5_6_7.txt").write_text(buf.getvalue(), encoding="utf-8")
print("\n-> written", OUT / "selftest_5_6_7.txt")
