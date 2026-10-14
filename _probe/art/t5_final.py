"""最终验证：所有公开入口都走一遍，确认交付可复现。"""
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


# 直接 import 包（验证 __init__ 的重导出链）
import cardforge.art as ART  # noqa: E402
from cardforge.core.models import ArtRequest, CardSpec  # noqa: E402
from cardforge.art import presets as PS  # noqa: E402
from cardforge.art import profiles as PF  # noqa: E402
from cardforge.art import graph as G  # noqa: E402
from cardforge.art import prompt as PR  # noqa: E402
from cardforge.art import library as L  # noqa: E402
from cardforge.art import client as CL  # noqa: E402

w("=" * 78)
w("最终验证（全部公开入口）")
w("=" * 78)
w("包重导出 :", ", ".join(sorted(n for n in ART.__all__)))
w()

# 1) 契约签名检查
import inspect  # noqa: E402

sigs = {
    "profiles.ModelProfile": inspect.signature(PF.ModelProfile),
    "profiles.detect": inspect.signature(PF.detect),
    "profiles.by_key": inspect.signature(PF.by_key),
    "profiles.art_size_for": inspect.signature(PF.art_size_for),
    "client.ComfyClient.__init__": inspect.signature(CL.ComfyClient.__init__),
    "client.ComfyClient.queue": inspect.signature(CL.ComfyClient.queue),
    "client.ComfyClient.wait": inspect.signature(CL.ComfyClient.wait),
    "client.ComfyClient.view": inspect.signature(CL.ComfyClient.view),
    "client.ComfyClient.upload": inspect.signature(CL.ComfyClient.upload),
    "client.ComfyClient.free": inspect.signature(CL.ComfyClient.free),
    "graph.Graph.add": inspect.signature(G.Graph.add),
    "graph.Graph.link": inspect.signature(G.Graph.link),
    "graph.Graph.to_api": inspect.signature(G.Graph.to_api),
    "graph.Graph.to_ui": inspect.signature(G.Graph.to_ui),
    "graph.build_t2i": inspect.signature(G.build_t2i),
    "graph.build_upscale": inspect.signature(G.build_upscale),
    "graph.build_remove_bg": inspect.signature(G.build_remove_bg),
    "prompt.build": inspect.signature(PR.build),
    "prompt.zh_to_tags": inspect.signature(PR.zh_to_tags),
    "presets.preset": inspect.signature(PS.preset),
    "library.save": inspect.signature(L.save),
    "library.compare": inspect.signature(L.compare),
    "run.generate": inspect.signature(ART.generate),
    "run.generate_series": inspect.signature(ART.generate_series),
    "run.export_workflow": inspect.signature(ART.export_workflow),
    "run.capabilities": inspect.signature(ART.capabilities),
}
w("--- 公开签名 ---")
for k, v in sigs.items():
    s = str(v)
    w(f"  {k}{s if len(s) < 150 else s[:147] + '...'}")
w()
w("SERIES_STYLE_KEY =", PR.SERIES_STYLE_KEY)
w("PROFILES 档案数 =", len(PF.PROFILES), "->", [p.key for p in PF.PROFILES])
w("PRESETS 预设数 =", len(PS.PRESETS), "->", PS.keys())
w("ZH_TAGS 词条数 =", len(PR.ZH_TAGS))
w("CONTROL_AFTER =", sorted(G.CONTROL_AFTER))

# 2) by_capability 修正后
w()
w("--- 预设可用性（by_capability）---")
caps = ART.capabilities()
for row in PS.by_capability(caps):
    w(f"  {row['key']:22s} available={str(row['available']):5s} {row['reason']}")

# 3) Graph 往返一致性 + 指纹稳定性
w()
w("--- Graph 往返 / 指纹 ---")
card = CardSpec(id=970041, name="验证卡", frame="synchro", attribute="光",
                race="天使族", level=10, atk=3300, dfd=2800, archetype="_probe_verify")
req = ArtRequest(card_id=card.id, archetype=card.archetype, subject="一位白色羽翼的天使",
                 style="神圣，体积光", profile="auto", seed=550001)
res = ART.generate(req, card=card, dry_run=True)
w("dry_run ok =", res.ok, "| images =", res.images, "| 节点数 =", len(res.workflow))
prof = PF.by_key("krea2")
g = G.Graph(available=None, schemas=None)
a = g.add("UNETLoader", unet_name="x.safetensors", weight_dtype="default")
b = g.add("RandomNoise", noise_seed=42)
g.link(b, "model", a, 0) if False else None
ui1 = g.to_ui()
api1 = G.ui_to_api(ui1, None)
w("离线（无 schemas）widgets_values:", json.dumps(ui1["nodes"][1]["widgets_values"]))
w("离线 ui_to_api 还原:", json.dumps(api1, ensure_ascii=False))
# 指纹：同参数不同 seed 应一致；参数变了应不同
g1 = G.Graph(); n = g1.add("RandomNoise", noise_seed=1); fp1 = g1.fingerprint()
g2 = G.Graph(); n2 = g2.add("RandomNoise", noise_seed=999999); fp2 = g2.fingerprint()
g3 = G.Graph(); n3 = g3.add("KSamplerSelect", sampler_name="euler"); fp3 = g3.fingerprint()
w(f"指纹（seed=1）      = {fp1}")
w(f"指纹（seed=999999） = {fp2}  -> 忽略 seed，一致? {fp1 == fp2}")
w(f"指纹（不同节点）    = {fp3}  -> 与上面不同? {fp3 != fp1}")

# 4) 全部预设导出（远端在线）
w()
w("--- 全部预设 export_workflow ---")
cli = CL.ComfyClient()
schemas = cli.object_info()
for key in PS.keys():
    dst = OUT / f"final_workflow_{key}.json"
    try:
        p = ART.export_workflow(key, str(dst), profile="auto", spec=card)
        ui = json.loads(Path(p).read_text(encoding="utf-8"))
        api = G.ui_to_api(ui, schemas)
        probs = G.validate(api, schemas)
        # 关键：往返必须回到同一张图
        w(f"  {key:22s} OK  节点={len(ui['nodes']):3d} links={len(ui['links']):3d} "
          f"version={ui['version']} 自检={'通过' if not probs else probs}")
    except Exception as exc:
        w(f"  {key:22s} 失败 {type(exc).__name__}: "
          f"{getattr(exc, 'message', exc)} | hint={getattr(exc, 'hint', '')}"[:200])

# 5) README 列表
w()
w("--- 生成的 README ---")
for rm in sorted(OUT.glob("README_*.md")):
    w(f"  {rm.name:34s} {rm.stat().st_size:6d} bytes")

# 6) 资产库清单
w()
w("--- 资产库 workspace/pics/art ---")
for row in L.list_all():
    w("  ", json.dumps({k: row[k] for k in ("archetype", "card_id", "versions", "version")},
                       ensure_ascii=False))

# 7) 关键错误分类（六类）
w()
w("--- 六类错误的 hint 是否中文 ---")
for k, v in CL.ERROR_HINTS.items():
    w(f"  {k:14s} 中文? {any(chr(0x4e00) <= c <= chr(0x9fff) for c in v)}  "
      f"{v[:70]}...")

(OUT / "final_verify.txt").write_text(buf.getvalue(), encoding="utf-8")
print("\n-> written", OUT / "final_verify.txt")
