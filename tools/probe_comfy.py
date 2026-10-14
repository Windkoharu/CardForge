"""ComfyUI 能力实测探测 —— 用真实 /object_info 替代猜测。

用法: python tools/probe_comfy.py [host]
输出: workspace/logs/comfy_probe.json + 控制台摘要
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error

HOST = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8188"

# 本项目关心的节点（class_type 精确拼写）
INTERESTING = [
    "CheckpointLoaderSimple", "LoraLoader", "LoraLoaderModelOnly", "CLIPTextEncode",
    "EmptyLatentImage", "KSampler", "KSamplerAdvanced", "VAEDecode", "VAEEncode",
    "SaveImage", "PreviewImage", "LoadImage", "ImageScale", "ImageScaleBy",
    "LatentUpscale", "LatentUpscaleBy", "ControlNetLoader", "ControlNetApplyAdvanced",
    "CLIPVisionLoader", "CLIPSetLastLayer", "UpscaleModelLoader", "ImageUpscaleWithModel",
    "SetLatentNoiseMask", "InpaintModelConditioning", "VAEEncodeForInpaint",
    # 第三方/可选增强
    "IPAdapterUnifiedLoader", "IPAdapterAdvanced", "IPAdapterModelLoader",
    "IPAdapterEncoder", "InstantIDModelLoader", "ApplyInstantID", "PulidModelLoader",
    "BiRefNetRMBG", "ImageRemoveBackground", "Image Rembg (Remove Background)",
    "ReferenceLatent", "ReferenceOnlySimple", "ModelSamplingDiscrete",
    "EmptySD3LatentImage", "ConditioningSetTimestepRange", "RepeatLatentBatch",
    "ImageBatch", "ImageBlend", "ImageCompositeMasked", "LoadImageMask",
    "MaskFromColor", "GrowMask", "JoinImageWithAlpha", "SplitImageWithAlpha",
]

# 需要列出候选值的下拉参数
COMBO_OF_INTEREST = {
    "CheckpointLoaderSimple": "ckpt_name",
    "LoraLoader": "lora_name",
    "UpscaleModelLoader": "model_name",
    "ControlNetLoader": "control_net_name",
    "CLIPVisionLoader": "clip_name",
    "KSampler": "sampler_name",
    "KSamplerAdvanced": "sampler_name",
    "IPAdapterUnifiedLoader": "preset",
}


def get(path: str, timeout: int = 30):
    with urllib.request.urlopen(HOST + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def combo_options(info: dict, node: str, param: str):
    try:
        v = info[node]["input"]["required"][param][0]
        return v if isinstance(v, list) else [f"<非列表: {type(v).__name__}>"]
    except Exception as e:
        return [f"<读取失败: {e}>"]


def main() -> int:
    report: dict = {"host": HOST, "ok": False}

    try:
        stats = get("/system_stats")
        report["system"] = {
            "comfyui_version": stats.get("system", {}).get("comfyui_version"),
            "python": stats.get("system", {}).get("python_version", "")[:40],
            "torch": stats.get("system", {}).get("pytorch_version"),
            "devices": [
                {"name": d.get("name"), "vram_total_gb": round(d.get("vram_total", 0) / 2**30, 1),
                 "vram_free_gb": round(d.get("vram_free", 0) / 2**30, 1)}
                for d in stats.get("devices", [])
            ],
        }
    except Exception as e:
        print(f"[X] ComfyUI 不可达 {HOST}: {e}")
        report["error"] = str(e)
        _dump(report)
        return 2

    try:
        info = get("/object_info", timeout=120)
    except Exception as e:
        print(f"[X] /object_info 失败: {e}")
        report["error"] = str(e)
        _dump(report)
        return 2

    report["ok"] = True
    report["node_total"] = len(info)
    report["nodes_present"] = sorted(n for n in INTERESTING if n in info)
    report["nodes_missing"] = sorted(n for n in INTERESTING if n not in info)

    report["combos"] = {}
    for node, param in COMBO_OF_INTEREST.items():
        if node in info:
            opts = combo_options(info, node, param)
            report["combos"][f"{node}.{param}"] = {
                "count": len(opts), "options": opts[:400],
            }

    # KSampler scheduler 候选（调研说 9 个，实测确认）
    for node, param in [("KSampler", "scheduler"), ("KSamplerAdvanced", "scheduler")]:
        if node in info:
            report["combos"][f"{node}.{param}"] = {"options": combo_options(info, node, param)}

    # IPAdapter 精确签名（调研未验证项之一）
    if "IPAdapterAdvanced" in info:
        req = info["IPAdapterAdvanced"]["input"].get("required", {})
        report["ipadapter_advanced_inputs"] = sorted(req)
        for k in ("weight_type", "combine_embeds", "embeds_scaling"):
            if k in req and isinstance(req[k][0], list):
                report["combos"][f"IPAdapterAdvanced.{k}"] = {"options": req[k][0]}

    if "IPAdapterUnifiedLoader" in info:
        req = info["IPAdapterUnifiedLoader"]["input"].get("required", {})
        if "preset" in req and isinstance(req["preset"][0], list):
            report["combos"]["IPAdapterUnifiedLoader.preset"] = {"options": req["preset"][0]}

    # ImageRemoveBackground 家族的真实 class_type
    report["bg_removal_nodes"] = sorted(
        n for n in info if "rembg" in n.lower() or "birefnet" in n.lower()
        or "background" in n.lower()
    )
    report["ipadapter_nodes"] = sorted(n for n in info if "ipadapter" in n.lower())
    report["instantid_pulid_nodes"] = sorted(
        n for n in info if "instantid" in n.lower() or "pulid" in n.lower() or "faceid" in n.lower()
    )
    report["reference_nodes"] = sorted(
        n for n in info if "reference" in n.lower() or "refine" in n.lower()
    )

    _dump(report)
    _print_summary(report)
    return 0


def _dump(report: dict):
    import os
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "workspace", "logs", "comfy_probe.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n完整报告 -> {out}")


def _print_summary(r: dict):
    print("=" * 68)
    print(f"ComfyUI {r.get('comfyui_version')}  @ {r['host']}")
    for d in r.get("system", {}).get("devices", []):
        print(f"  GPU {d['name']}  VRAM {d['vram_free_gb']}/{d['vram_total_gb']} GB free")
    print(f"  节点总数 {r.get('node_total')}")
    print(f"  关键节点缺失: {r.get('nodes_missing')}")
    for k, v in r.get("combos", {}).items():
        if "count" in v:
            print(f"  {k}: {v['count']} 项 -> {v['options'][:10]}")
        else:
            print(f"  {k}: {v['options']}")
    print(f"  `-- 抠底节点: {r.get('bg_removal_nodes')}")
    print(f"  `-- IPAdapter 节点: {r.get('ipadapter_nodes')}")
    print(f"  `-- 人脸一致性节点: {r.get('instantid_pulid_nodes')}")
    if r.get("ipadapter_advanced_inputs"):
        print(f"  `-- IPAdapterAdvanced inputs: {r['ipadapter_advanced_inputs']}")
    print("=" * 68)


if __name__ == "__main__":
    raise SystemExit(main())
