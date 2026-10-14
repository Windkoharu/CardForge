"""工作流图构造器 —— API 格式 ↔ **可直接导入 ComfyUI 的 UI 格式**。

两种格式的差异（这是本模块存在的理由）
--------------------------------------
=================  ============================  ==============================
                   API 格式（``POST /prompt``）    UI 格式（File → Save）
=================  ============================  ==============================
节点容器           ``{id: {...}}`` 对象           ``nodes: [...]`` 数组
连线               内联成 ``[src_id, slot]``     独立的 ``links: [...]`` 数组
位置/尺寸/颜色     无                            有（``pos``/``size``/...）
参数值             ``inputs`` 里带**参数名**     ``widgets_values`` **纯值数组**
=================  ============================  ==============================

``widgets_values`` 的坑（本模块已处理）
---------------------------------------
1. **纯值、无参数名**，必须按节点 schema 的 widget 声明顺序对齐；
2. **``seed`` / ``noise_seed`` 后面会跟一个 ``control_after_generate``**
   （``"fixed"`` / ``"randomize"`` / ``"increment"`` …）。它**不是** API 参数，
   但**必须占一个位置** —— 否则导入后后面所有参数整体错位一格。
   实测本机 ComfyUI 0.38.2 的前端就是把它序列化进 ``widgets_values`` 的
   （例如真实的社区工作流里 ``RandomNoise`` 存的是 ``[795140483442838, "fixed"]``）；
   缺失时新前端有启发式恢复，但那是运气不是设计。
3. ``LoadImage`` 的 ``widgets_values`` 是 ``[图片名, "image"]`` —— 第二个是上传按钮。

节点可用性降级
--------------
:class:`Graph` 带一个 ``available`` 节点集合。构造器遇到本机不存在的**增强节点**
（IPAdapter / ControlNet / 抠底 / 放大）时会**优雅跳过**，把原因写进
``graph.warnings``，而不是生成一张跑不通的图。
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from ..core.errors import ComfyError
from ..render.geometry import ART_TARGET_2X
from .client import bump_seed, new_seed
from .profiles import ModelProfile

# ══════════════════════════════════════════════════════════════════════
#  常量
# ══════════════════════════════════════════════════════════════════════
#: 只有这些基础类型能当 widget（画在节点上），其余都是连线槽
WIDGET_TYPES = frozenset({"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO",
                          "COLORCODE", "MARKDOWN"})

#: 这些 widget 名后面要跟一个 control_after_generate 占位值
CONTROL_AFTER = frozenset({"seed", "noise_seed"})

#: 这些 widget 是前端行为，不进 API 参数
UI_ONLY_WIDGETS = frozenset({"control_after_generate", "control_filter_list",
                             "upload", "image_upload"})

#: 节点默认尺寸（UI 格式用；真值由前端按 widget 数量重算，这里只为导入后不重叠）
DEFAULT_NODE_SIZE = (340, 128)
NODE_GAP_X = 380
ROW_GAP_Y = 300
NODES_PER_ROW = 6

SAVE_PREFIX_DEFAULT = "cardforge/art"

#: 2× 交付尺寸（842×1228 = 421×614 的精确 2 倍）—— 从 render.geometry 取，不重复定义
TARGET_2X = tuple(ART_TARGET_2X)


# ══════════════════════════════════════════════════════════════════════
#  内置节点 schema 兜底表
# ══════════════════════════════════════════════════════════════════════
#: 当拿不到 ``/object_info``（离线导出工作流）时，用这张表推断 widget 顺序。
#: 格式：``{class_type: [widget 名（按 UI 声明顺序）...]}``
BUILTIN_WIDGET_ORDER: dict[str, list[str]] = {
    "UNETLoader": ["unet_name", "weight_dtype"],
    "CheckpointLoaderSimple": ["ckpt_name"],
    "CLIPLoader": ["clip_name", "type", "device"],
    "DualCLIPLoader": ["clip_name1", "clip_name2", "type", "device"],
    "VAELoader": ["vae_name"],
    "LoraLoaderModelOnly": ["lora_name", "strength_model"],
    "LoraLoader": ["lora_name", "strength_model", "strength_clip"],
    "CLIPSetLastLayer": ["stop_at_clip_layer"],
    "CLIPTextEncode": ["text"],
    "ModelSamplingFlux": ["max_shift", "base_shift", "width", "height"],
    "ModelSamplingAuraFlow": ["shift"],
    "ModelSamplingDiscrete": ["sampling", "zsnr"],
    "ConditioningZeroOut": [],
    "CFGGuider": ["cfg"],
    "RandomNoise": ["noise_seed"],
    "KSamplerSelect": ["sampler_name"],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "SamplerCustomAdvanced": [],
    "KSampler": ["seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"],
    "KSamplerAdvanced": ["add_noise", "noise_seed", "steps", "cfg", "sampler_name",
                         "scheduler", "start_at_step", "end_at_step",
                         "return_with_leftover_noise"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "EmptySD3LatentImage": ["width", "height", "batch_size"],
    "VAEDecode": [],
    "VAEEncode": [],
    "VAEEncodeForInpaint": ["grow_mask_by"],
    "SetLatentNoiseMask": [],
    "SaveImage": ["filename_prefix"],
    "PreviewImage": [],
    "LoadImage": ["image", "upload"],
    "LoadImageMask": ["image", "channel"],
    "ImageScale": ["upscale_method", "width", "height", "crop"],
    "ImageScaleBy": ["upscale_method", "scale_by"],
    "ImageUpscaleWithModel": [],
    "UpscaleModelLoader": ["model_name"],
    "ImageCompositeMasked": ["x", "y", "resize_source"],
    "GrowMask": ["expand", "tapered_corners"],
    "InvertMask": [],
    "MaskToImage": [],
    "ImageToMask": ["channel"],
    "ThresholdMask": ["value"],
    "SolidMask": ["value", "width", "height"],
    "ImageInvert": [],
    "JoinImageWithAlpha": [],
    "SplitImageWithAlpha": [],
    "BiRefNetRMBG": ["model", "sensitivity", "mask_blur", "mask_offset",
                     "invert_output", "refine_foreground", "background",
                     "background_color"],
    "LoadBackgroundRemovalModel": ["model"],
    "RemoveBackground": [],
    "BriaRemoveImageBackground": ["moderation", "seed"],
    "IPAdapterUnifiedLoader": ["preset"],
    "IPAdapterAdvanced": ["weight", "weight_type", "combine_embeds",
                          "start_at", "end_at", "embeds_scaling"],
    "IPAdapterModelLoader": ["ipadapter_file"],
    "CLIPVisionLoader": ["clip_name"],
    "ControlNetLoader": ["control_net_name"],
    "ControlNetApplyAdvanced": ["strength", "start_percent", "end_percent"],
    "TextEncodeQwenImageEditPlus": ["prompt"],
    "FluxKontextMultiReferenceLatentMethod": ["reference_latents_method"],
    "ReferenceLatent": [],
    "InpaintModelConditioning": ["noise_mask"],
}

#: widget 默认值兜底（拿不到 schema 时用）
BUILTIN_DEFAULTS: dict[tuple[str, str], object] = {
    ("UNETLoader", "weight_dtype"): "default",
    ("CLIPLoader", "type"): "stable_diffusion",
    ("CLIPLoader", "device"): "default",
    ("LoraLoaderModelOnly", "strength_model"): 1.0,
    ("LoraLoader", "strength_model"): 1.0,
    ("LoraLoader", "strength_clip"): 1.0,
    ("CLIPSetLastLayer", "stop_at_clip_layer"): -1,
    ("ModelSamplingFlux", "max_shift"): 1.15,
    ("ModelSamplingFlux", "base_shift"): 0.5,
    ("ModelSamplingFlux", "width"): 1024,
    ("ModelSamplingFlux", "height"): 1024,
    ("ModelSamplingAuraFlow", "shift"): 1.73,
    ("ModelSamplingDiscrete", "sampling"): "eps",
    ("ModelSamplingDiscrete", "zsnr"): False,
    ("CFGGuider", "cfg"): 8.0,
    ("RandomNoise", "noise_seed"): 0,
    ("KSamplerSelect", "sampler_name"): "euler",
    ("BasicScheduler", "scheduler"): "simple",
    ("BasicScheduler", "steps"): 20,
    ("BasicScheduler", "denoise"): 1.0,
    ("KSampler", "steps"): 20,
    ("KSampler", "cfg"): 8.0,
    ("KSampler", "sampler_name"): "euler",
    ("KSampler", "scheduler"): "normal",
    ("KSampler", "denoise"): 1.0,
    ("KSamplerAdvanced", "add_noise"): "enable",
    ("KSamplerAdvanced", "steps"): 20,
    ("KSamplerAdvanced", "cfg"): 8.0,
    ("KSamplerAdvanced", "start_at_step"): 0,
    ("KSamplerAdvanced", "end_at_step"): 10000,
    ("KSamplerAdvanced", "return_with_leftover_noise"): "disable",
    ("EmptyLatentImage", "width"): 1024,
    ("EmptyLatentImage", "height"): 1024,
    ("EmptyLatentImage", "batch_size"): 1,
    ("EmptySD3LatentImage", "width"): 1024,
    ("EmptySD3LatentImage", "height"): 1024,
    ("EmptySD3LatentImage", "batch_size"): 1,
    ("VAEEncodeForInpaint", "grow_mask_by"): 6,
    ("SaveImage", "filename_prefix"): "ComfyUI",
    ("LoadImage", "upload"): "image",
    ("LoadImageMask", "channel"): "alpha",
    ("ImageScale", "upscale_method"): "lanczos",
    ("ImageScale", "width"): 512,
    ("ImageScale", "height"): 512,
    ("ImageScale", "crop"): "disabled",
    ("ImageScaleBy", "upscale_method"): "lanczos",
    ("ImageScaleBy", "scale_by"): 1.0,
    ("ImageCompositeMasked", "x"): 0,
    ("ImageCompositeMasked", "y"): 0,
    ("ImageCompositeMasked", "resize_source"): False,
    ("GrowMask", "expand"): 8,
    ("GrowMask", "tapered_corners"): True,
    ("ImageToMask", "channel"): "red",
    ("ThresholdMask", "value"): 0.5,
    ("SolidMask", "value"): 1.0,
    ("SolidMask", "width"): 512,
    ("SolidMask", "height"): 512,
    ("BiRefNetRMBG", "model"): "BiRefNet_toonout",
    ("BiRefNetRMBG", "sensitivity"): 1.0,
    ("BiRefNetRMBG", "mask_blur"): 0,
    ("BiRefNetRMBG", "mask_offset"): 0,
    ("BiRefNetRMBG", "invert_output"): False,
    ("BiRefNetRMBG", "refine_foreground"): True,
    ("BiRefNetRMBG", "background"): "Alpha",
    ("BiRefNetRMBG", "background_color"): "#222222",
    ("IPAdapterUnifiedLoader", "preset"): "STANDARD (medium strength)",
    ("IPAdapterAdvanced", "weight"): 0.65,
    ("IPAdapterAdvanced", "weight_type"): "style transfer",
    ("IPAdapterAdvanced", "combine_embeds"): "average",
    ("IPAdapterAdvanced", "start_at"): 0.0,
    ("IPAdapterAdvanced", "end_at"): 1.0,
    ("IPAdapterAdvanced", "embeds_scaling"): "K+V",
    ("ControlNetApplyAdvanced", "strength"): 0.7,
    ("ControlNetApplyAdvanced", "start_percent"): 0.0,
    ("ControlNetApplyAdvanced", "end_percent"): 0.5,
    ("FluxKontextMultiReferenceLatentMethod", "reference_latents_method"):
        "index_timestep_zero",
    ("InpaintModelConditioning", "noise_mask"): True,
}

#: 节点默认标题（UI 上显示的名字；不填就用 class_type）
NODE_TITLES = {
    "UNETLoader": "Load Diffusion Model",
    "CheckpointLoaderSimple": "Load Checkpoint",
    "CLIPLoader": "Load CLIP",
    "VAELoader": "Load VAE",
    "LoraLoaderModelOnly": "Load LoRA",
    "LoraLoader": "Load LoRA (Model and CLIP)",
    "CLIPTextEncode": "CLIP Text Encode (Prompt)",
    "CLIPSetLastLayer": "CLIP Set Last Layer",
    "SaveImage": "Save Image",
    "LoadImage": "Load Image",
    "ImageScale": "Upscale Image",
    "ImageUpscaleWithModel": "Upscale Image (using Model)",
    "BiRefNetRMBG": "BiRefNet (RMBG)",
}

#: 部分节点的输出名/类型兜底（拿不到 schema 时用）
BUILTIN_OUTPUTS: dict[str, tuple[list[str], list[str]]] = {
    "UNETLoader": (["MODEL"], ["MODEL"]),
    "CheckpointLoaderSimple": (["MODEL", "CLIP", "VAE"], ["MODEL", "CLIP", "VAE"]),
    "CLIPLoader": (["CLIP"], ["CLIP"]),
    "DualCLIPLoader": (["CLIP"], ["CLIP"]),
    "VAELoader": (["VAE"], ["VAE"]),
    "LoraLoaderModelOnly": (["MODEL"], ["MODEL"]),
    "LoraLoader": (["MODEL", "CLIP"], ["MODEL", "CLIP"]),
    "CLIPSetLastLayer": (["CLIP"], ["CLIP"]),
    "CLIPTextEncode": (["CONDITIONING"], ["CONDITIONING"]),
    "ModelSamplingFlux": (["MODEL"], ["MODEL"]),
    "ModelSamplingAuraFlow": (["MODEL"], ["MODEL"]),
    "ModelSamplingDiscrete": (["MODEL"], ["MODEL"]),
    "ConditioningZeroOut": (["CONDITIONING"], ["CONDITIONING"]),
    "CFGGuider": (["GUIDER"], ["GUIDER"]),
    "RandomNoise": (["NOISE"], ["NOISE"]),
    "KSamplerSelect": (["SAMPLER"], ["SAMPLER"]),
    "BasicScheduler": (["SIGMAS"], ["SIGMAS"]),
    "SamplerCustomAdvanced": (["output", "denoised_output"], ["LATENT", "LATENT"]),
    "KSampler": (["LATENT"], ["LATENT"]),
    "KSamplerAdvanced": (["LATENT"], ["LATENT"]),
    "EmptyLatentImage": (["LATENT"], ["LATENT"]),
    "EmptySD3LatentImage": (["LATENT"], ["LATENT"]),
    "VAEDecode": (["IMAGE"], ["IMAGE"]),
    "VAEEncode": (["LATENT"], ["LATENT"]),
    "VAEEncodeForInpaint": (["LATENT"], ["LATENT"]),
    "SetLatentNoiseMask": (["LATENT"], ["LATENT"]),
    "SaveImage": (["images"], ["IMAGE"]),
    "PreviewImage": (["images"], ["IMAGE"]),
    "LoadImage": (["IMAGE", "MASK"], ["IMAGE", "MASK"]),
    "LoadImageMask": (["MASK"], ["MASK"]),
    "ImageScale": (["IMAGE"], ["IMAGE"]),
    "ImageScaleBy": (["IMAGE"], ["IMAGE"]),
    "ImageUpscaleWithModel": (["IMAGE"], ["IMAGE"]),
    "UpscaleModelLoader": (["UPSCALE_MODEL"], ["UPSCALE_MODEL"]),
    "ImageCompositeMasked": (["IMAGE"], ["IMAGE"]),
    "GrowMask": (["MASK"], ["MASK"]),
    "InvertMask": (["MASK"], ["MASK"]),
    "MaskToImage": (["IMAGE"], ["IMAGE"]),
    "ImageToMask": (["MASK"], ["MASK"]),
    "ThresholdMask": (["MASK"], ["MASK"]),
    "SolidMask": (["MASK"], ["MASK"]),
    "ImageInvert": (["IMAGE"], ["IMAGE"]),
    "JoinImageWithAlpha": (["IMAGE"], ["IMAGE"]),
    "SplitImageWithAlpha": (["IMAGE", "MASK"], ["IMAGE", "MASK"]),
    "BiRefNetRMBG": (["IMAGE", "MASK", "MASK_IMAGE"], ["IMAGE", "MASK", "IMAGE"]),
    "LoadBackgroundRemovalModel": (["BACKGROUND_REMOVAL"], ["BACKGROUND_REMOVAL"]),
    "RemoveBackground": (["mask"], ["MASK"]),
    "IPAdapterUnifiedLoader": (["model", "ipadapter"], ["MODEL", "IPADAPTER"]),
    "IPAdapterAdvanced": (["MODEL"], ["MODEL"]),
    "IPAdapterModelLoader": (["IPADAPTER"], ["IPADAPTER"]),
    "CLIPVisionLoader": (["CLIP_VISION"], ["CLIP_VISION"]),
    "ControlNetLoader": (["CONTROL_NET"], ["CONTROL_NET"]),
    "ControlNetApplyAdvanced": (["positive", "negative"],
                                ["CONDITIONING", "CONDITIONING"]),
    "TextEncodeQwenImageEditPlus": (["CONDITIONING"], ["CONDITIONING"]),
    "FluxKontextMultiReferenceLatentMethod": (["CONDITIONING"], ["CONDITIONING"]),
    "ReferenceLatent": (["CONDITIONING"], ["CONDITIONING"]),
    "InpaintModelConditioning": (["positive", "negative", "latent"],
                                 ["CONDITIONING", "CONDITIONING", "LATENT"]),
}

#: 部分节点的连线输入类型兜底
BUILTIN_INPUT_TYPES: dict[str, dict[str, str]] = {
    "CFGGuider": {"model": "MODEL", "positive": "CONDITIONING",
                  "negative": "CONDITIONING"},
    "BasicScheduler": {"model": "MODEL"},
    "SamplerCustomAdvanced": {"noise": "NOISE", "guider": "GUIDER",
                              "sampler": "SAMPLER", "sigmas": "SIGMAS",
                              "latent_image": "LATENT"},
    "KSampler": {"model": "MODEL", "positive": "CONDITIONING",
                 "negative": "CONDITIONING", "latent_image": "LATENT"},
    "KSamplerAdvanced": {"model": "MODEL", "positive": "CONDITIONING",
                         "negative": "CONDITIONING", "latent_image": "LATENT"},
    "VAEDecode": {"samples": "LATENT", "vae": "VAE"},
    "VAEEncode": {"pixels": "IMAGE", "vae": "VAE"},
    "VAEEncodeForInpaint": {"pixels": "IMAGE", "vae": "VAE", "mask": "MASK"},
    "SetLatentNoiseMask": {"samples": "LATENT", "mask": "MASK"},
    "SaveImage": {"images": "IMAGE"},
    "PreviewImage": {"images": "IMAGE"},
    "ImageScale": {"image": "IMAGE"},
    "ImageScaleBy": {"image": "IMAGE"},
    "ImageUpscaleWithModel": {"upscale_model": "UPSCALE_MODEL", "image": "IMAGE"},
    "BiRefNetRMBG": {"image": "IMAGE"},
    "RemoveBackground": {"bg_removal_model": "BACKGROUND_REMOVAL", "image": "IMAGE"},
    "BriaRemoveImageBackground": {"image": "IMAGE"},
    "ImageCompositeMasked": {"destination": "IMAGE", "source": "IMAGE", "mask": "MASK"},
    "GrowMask": {"mask": "MASK"},
    "InvertMask": {"mask": "MASK"},
    "MaskToImage": {"mask": "MASK"},
    "ImageToMask": {"image": "IMAGE"},
    "ThresholdMask": {"mask": "MASK"},
    "ImageInvert": {"image": "IMAGE"},
    "JoinImageWithAlpha": {"image": "IMAGE", "alpha": "MASK"},
    "SplitImageWithAlpha": {"image": "IMAGE"},
    "CLIPTextEncode": {"clip": "CLIP"},
    "ConditioningZeroOut": {"conditioning": "CONDITIONING"},
    "ConditioningSetTimestepRange": {"conditioning": "CONDITIONING"},
    "ModelSamplingFlux": {"model": "MODEL"},
    "ModelSamplingAuraFlow": {"model": "MODEL"},
    "ModelSamplingDiscrete": {"model": "MODEL"},
    "LoraLoaderModelOnly": {"model": "MODEL"},
    "LoraLoader": {"model": "MODEL", "clip": "CLIP"},
    "CLIPSetLastLayer": {"clip": "CLIP"},
    "IPAdapterAdvanced": {"model": "MODEL", "ipadapter": "IPADAPTER", "image": "IMAGE",
                          "clip_vision": "CLIP_VISION", "attn_mask": "MASK",
                          "image_negative": "IMAGE"},
    "IPAdapterUnifiedLoader": {"model": "MODEL", "ipadapter": "IPADAPTER"},
    "ControlNetApplyAdvanced": {"positive": "CONDITIONING", "negative": "CONDITIONING",
                                "control_net": "CONTROL_NET", "image": "IMAGE",
                                "vae": "VAE"},
    "TextEncodeQwenImageEditPlus": {"clip": "CLIP", "vae": "VAE", "image1": "IMAGE",
                                    "image2": "IMAGE", "image3": "IMAGE"},
    "FluxKontextMultiReferenceLatentMethod": {"conditioning": "CONDITIONING"},
    "ReferenceLatent": {"conditioning": "CONDITIONING", "latent": "LATENT"},
    "InpaintModelConditioning": {"positive": "CONDITIONING",
                                 "negative": "CONDITIONING", "vae": "VAE",
                                 "pixels": "IMAGE", "mask": "MASK"},
}


# ══════════════════════════════════════════════════════════════════════
#  Graph
# ══════════════════════════════════════════════════════════════════════
class Graph:
    """一张工作流图。同时能输出 API 格式与 **可直接导入 ComfyUI** 的 UI 格式。

    >>> g = Graph()                                          # doctest: +SKIP
    >>> a = g.add("UNETLoader", unet_name="m.safetensors")   # doctest: +SKIP
    >>> b = g.add("VAEDecode")                               # doctest: +SKIP
    >>> g.link(b, "vae", a, 0)                               # doctest: +SKIP
    >>> g.to_api()[b]["inputs"]["vae"]                       # doctest: +SKIP
    ['1', 0]

    :param available: 本机已注册的 ``class_type`` 集合。``None`` = 不检查
        （离线导出工作流时用），此时构造器不会跳过任何节点。
    :param schemas: ``class_type → /object_info 条目``（决定 widget 顺序与候选值）。
        ``None`` 时退化为 :data:`BUILTIN_WIDGET_ORDER`。
    """

    def __init__(self, available: set[str] | None = None,
                 schemas: dict | None = None, *, title: str = "") -> None:
        self.title = title
        self.available: set[str] | None = set(available) if available is not None else None
        self.schemas: dict = dict(schemas or {})
        #: ``{node_id: {"class_type":..., "inputs":{...}, "_title":..., "_pos":...}}``
        self.nodes: dict[str, dict] = {}
        #: ``[(src_id, src_slot, dst_id, dst_input), ...]`` 连线顺序
        self.edges: list[tuple[str, int, str, str]] = []
        self.warnings: list[str] = []
        self._seq = 0

    # ── 基本操作 ──────────────────────────────────────────────────
    def add(self, class_type: str, *, _title: str = "", _pos: tuple | None = None,
            **inputs) -> str:
        """加一个节点，返回自增字符串 id。

        :param class_type: **注册类名**（如 ``CheckpointLoaderSimple``），
            不是 UI 显示名（``Load Checkpoint``）。写错会在提交时收到 400。
        :param inputs: 参数。基本类型直接给值；连线用 :meth:`link` 接。
        :param _title: UI 上显示的标题。
        :param _pos: 强制指定 UI 坐标；不给就自动排版。
        """
        self._seq += 1
        nid = str(self._seq)
        node: dict = {"class_type": str(class_type), "inputs": dict(inputs)}
        if _title:
            node["_title"] = _title
        if _pos:
            node["_pos"] = [int(_pos[0]), int(_pos[1])]
        self.nodes[nid] = node
        return nid

    def link(self, node: str, input_name: str, src: str, slot: int = 0) -> None:
        """把 ``src`` 的第 ``slot`` 个输出接到 ``node`` 的 ``input_name``。

        :raises ComfyError: 任一节点不存在（``kind="bad_prompt"``）。
        """
        if node not in self.nodes:
            raise ComfyError(f"连线失败：目标节点 {node} 不在图里",
                             "先 graph.add() 再 link()。", kind="bad_prompt")
        if src not in self.nodes:
            raise ComfyError(f"连线失败：源节点 {src} 不在图里",
                             "检查节点 id（id 是自增字符串）。", kind="bad_prompt")
        self.nodes[node]["inputs"][input_name] = [str(src), int(slot)]
        self.edges = [e for e in self.edges
                      if not (e[2] == str(node) and e[3] == input_name)]
        self.edges.append((str(src), int(slot), str(node), input_name))

    def unlink(self, node: str, input_name: str) -> None:
        """摘掉一根连线。"""
        node_obj = self.nodes.get(node)
        if node_obj and isinstance(node_obj["inputs"].get(input_name), list):
            node_obj["inputs"].pop(input_name, None)
        self.edges = [e for e in self.edges
                      if not (e[2] == str(node) and e[3] == input_name)]

    def set_input(self, node: str, name: str, value) -> None:
        """改一个节点的输入（值或连线都可以）。"""
        if node not in self.nodes:
            raise ComfyError(f"节点 {node} 不在图里", kind="bad_prompt")
        self.nodes[node]["inputs"][name] = value

    def remove(self, *node_ids: str) -> None:
        """删除节点及其全部连线。"""
        for nid in node_ids:
            self.nodes.pop(str(nid), None)
            self.edges = [e for e in self.edges
                          if e[0] != str(nid) and e[2] != str(nid)]

    def has(self, class_type: str) -> bool:
        """本机是否有这个节点（``available is None`` 时一律 ``True``）。"""
        return True if self.available is None else class_type in self.available

    def warn(self, message: str) -> None:
        """记一条降级警告（去重保序）。"""
        if message not in self.warnings:
            self.warnings.append(message)

    def nodes_of(self, class_type: str) -> list[str]:
        """图上所有指定类型的节点 id。"""
        return [nid for nid, n in self.nodes.items() if n["class_type"] == class_type]

    def sink(self) -> str | None:
        """图的汇点（输出节点）；没有 ``SaveImage``/``PreviewImage`` 时返回 ``None``。"""
        for ctype in ("SaveImage", "PreviewImage"):
            ids = self.nodes_of(ctype)
            if ids:
                return ids[-1]
        return None

    def image_source(self, node_id: str | None = None) -> tuple[str, int]:
        """取某个节点的 IMAGE 输入来源；``node_id`` 为空则取汇点。"""
        nid = node_id or self.sink()
        val = (self.nodes.get(str(nid)) or {}).get("inputs", {}).get("images")
        if isinstance(val, (list, tuple)) and len(val) == 2 and isinstance(val[0], str):
            return str(val[0]), int(val[1])
        raise ComfyError(f"节点 {nid} 没有连上 IMAGE 输入",
                         "构造器内部错误；请把这条报告给开发者。", kind="bad_prompt")

    def seed(self) -> int | None:
        """图上第一个 seed/noise_seed 的值。"""
        for node in self.nodes.values():
            for k in ("noise_seed", "seed"):
                v = node["inputs"].get(k)
                if isinstance(v, int):
                    return v
        return None

    # ── 输出：API 格式 ────────────────────────────────────────────
    def to_api(self) -> dict:
        """API 格式：``{node_id: {"class_type": ..., "inputs": {...}}}``。

        被引用的输入写成 ``[src_id, slot]``（内联连线）。
        """
        out: dict[str, dict] = {}
        for nid, node in self.nodes.items():
            entry: dict = {"class_type": node["class_type"],
                           "inputs": deepcopy(node["inputs"])}
            if node.get("_title"):
                entry["_meta"] = {"title": node["_title"]}
            out[nid] = entry
        return out

    # ── 输出：UI 格式 ─────────────────────────────────────────────
    def widget_order(self, class_type: str) -> list[str]:
        """该节点的 widget 顺序（决定 ``widgets_values`` 的对齐）。

        优先用 ``/object_info`` 的真 schema（``input_order`` 或
        ``input.required`` → ``input.optional`` 的声明顺序），
        否则退到 :data:`BUILTIN_WIDGET_ORDER`。
        """
        spec = (self.schemas or {}).get(class_type) or {}
        inp = spec.get("input") or {}
        order: list[str] = []
        if inp:
            for sect in ("required", "optional"):
                keys = (spec.get("input_order") or {}).get(sect)
                if not keys:
                    keys = list((inp.get(sect) or {}).keys())
                for k in keys:
                    entry = (inp.get(sect) or {}).get(k)
                    if entry is None:
                        continue
                    if self._is_widget(class_type, k, entry):
                        order.append(k)
        if order:
            return order
        return list(BUILTIN_WIDGET_ORDER.get(class_type, []))

    def _is_widget(self, class_type: str, name: str, entry) -> bool:
        """一个 schema 条目是不是「画在节点上的 widget」。"""
        if name in UI_ONLY_WIDGETS:
            return False
        if not isinstance(entry, list) or not entry:
            return False
        t = entry[0]
        if isinstance(t, list):          # 老式 COMBO：[["a","b"], {...}]
            return True
        if not isinstance(t, str):
            return name in BUILTIN_WIDGET_ORDER.get(class_type, [])
        if t not in WIDGET_TYPES:
            return False
        opts = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
        return not opts.get("hidden")

    def widget_default(self, class_type: str, name: str):
        """widget 的默认值：真 schema → 内置表 → 按类型猜。"""
        spec = ((self.schemas or {}).get(class_type) or {}).get("input") or {}
        for sect in ("required", "optional"):
            entry = (spec.get(sect) or {}).get(name)
            if not isinstance(entry, list) or not entry:
                continue
            t = entry[0]
            opts = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
            if "default" in opts:
                return opts["default"]
            if isinstance(opts.get("options"), list) and opts["options"]:
                return opts["options"][0]
            if isinstance(t, list) and t:
                return t[0]
            if t == "BOOLEAN":
                return False
            if t in ("INT", "FLOAT"):
                return 0
            return ""
        if (class_type, name) in BUILTIN_DEFAULTS:
            return BUILTIN_DEFAULTS[(class_type, name)]
        return ""

    def widgets_values(self, nid: str) -> list:
        """按 widget 顺序把 ``inputs`` 摊平成**纯值数组**（含 seed 的占位）。

        这是 UI 格式最容易错的地方：``seed`` / ``noise_seed`` 后面必须插一个
        ``control_after_generate``（默认 ``"fixed"``）—— 它不对应任何 API 参数，
        只是占位；缺了它，导入后从这一步往后的参数会整体错位一格。
        """
        node = self.nodes[str(nid)]
        ctype = node["class_type"]
        inputs = node["inputs"]
        order = self.widget_order(ctype)
        values: list = []
        for wname in order:
            raw = inputs.get(wname)
            if self._is_link_value(raw):        # 被连线了
                raw = self.widget_default(ctype, wname)
            elif raw is None:
                raw = self.widget_default(ctype, wname)
            values.append(raw)
            if wname in CONTROL_AFTER:
                ctrl = inputs.get("_control_after_generate")
                values.append(str(ctrl) if isinstance(ctrl, str) else "fixed")
        return values

    def to_ui(self, meta: dict | None = None, *, version: float = 0.4) -> dict:
        """UI 格式：**可被 ComfyUI 直接导入**的工作流 JSON。

        :param meta: 追加到 ``extra`` 的元数据（例如 ``{"cardforge": {...}}``）。
        :param version: 根对象的 ``version`` 字段（当前 ComfyUI 保存的就是 ``0.4``）。
        :return: ``{"last_node_id","last_link_id","nodes":[...],"links":[...],
                    "groups":[],"config":{},"extra":{},"version":0.4}``

        每条 ``links`` 是**数组** ``[id, origin_id, origin_slot, target_id,
        target_slot, type]`` —— 这正是 litegraph ``LLink.serialize()`` 的形状，
        ComfyUI 前端 ``configure()`` 按这个顺序解构。
        """
        id_map = {nid: i + 1 for i, nid in enumerate(self.nodes.keys())}
        # 每个节点在序列化 inputs 数组里的槽位号
        input_slots: dict[tuple[str, str], int] = {}
        for nid, node in self.nodes.items():
            order = self.widget_order(node["class_type"])
            idx = 0
            for iname, val in node["inputs"].items():       # 先连线输入
                if self._is_link_value(val) and iname not in order:
                    input_slots[(nid, iname)] = idx
                    idx += 1
            for iname, val in node["inputs"].items():       # widget 型输入被连线时追加在末尾
                if self._is_link_value(val) and iname in order:
                    input_slots[(nid, iname)] = idx
                    idx += 1

        links: list[list] = []
        input_link_of: dict[tuple[str, str], int] = {}
        output_links: dict[tuple[str, int], list[int]] = {}
        link_id = 0
        for src, src_slot, dst, dst_input in self.edges:
            link_id += 1
            links.append([link_id, id_map[src], int(src_slot), id_map[dst],
                          input_slots.get((dst, dst_input), 0),
                          self.output_type(self.nodes[src]["class_type"], src_slot)])
            input_link_of[(dst, dst_input)] = link_id
            output_links.setdefault((src, int(src_slot)), []).append(link_id)

        nodes_json: list[dict] = []
        for order_idx, (nid, node) in enumerate(self.nodes.items()):
            ctype = node["class_type"]
            order = self.widget_order(ctype)
            node_inputs: list[dict] = []
            for iname, val in node["inputs"].items():
                if not self._is_link_value(val):
                    continue
                item: dict = {
                    "name": iname,
                    "type": self.input_type(ctype, iname),
                    "link": input_link_of.get((nid, iname)),
                }
                if iname in order:
                    item["widget"] = {"name": iname}
                node_inputs.append(item)
            outputs: list[dict] = []
            for slot, oname in enumerate(self.output_names(ctype)):
                outputs.append({
                    "name": oname,
                    "type": self.output_type(ctype, slot),
                    "links": output_links.get((nid, slot)) or None,
                    "slot_index": slot,
                })
            pos = node.get("_pos") or self._auto_pos(order_idx)
            entry: dict = {
                "id": id_map[nid],
                "type": ctype,
                "pos": [int(pos[0]), int(pos[1])],
                "size": list(self._node_size(ctype)),
                "flags": {},
                "order": order_idx,
                "mode": 0,
                "inputs": node_inputs,
                "outputs": outputs,
                "widgets_values": self.widgets_values(nid),
                "properties": {
                    "Node name for S&R": ctype,
                    "cnr_id": "comfy-core",
                    "ver": "1.0.0",
                },
            }
            title = node.get("_title") or NODE_TITLES.get(ctype)
            if title and title != ctype:
                entry["title"] = title
            nodes_json.append(entry)

        extra: dict = {"ds": {"scale": 0.55, "offset": [0, 0]}}
        if self.title:
            extra.setdefault("cardforge", {})["title"] = self.title
        if self.warnings:
            extra.setdefault("cardforge", {})["warnings"] = list(self.warnings)
        if meta:
            cf = extra.setdefault("cardforge", {})
            cf.update(meta)
        return {
            "last_node_id": max(id_map.values()) if id_map else 0,
            "last_link_id": link_id,
            "nodes": nodes_json,
            "links": links,
            "groups": [],
            "config": {},
            "extra": extra,
            "version": version,
        }

    def _auto_pos(self, idx: int) -> tuple[int, int]:
        """自动排版：一行 6 个，按加入顺序从左到右、从上到下（与官方模板同风格）。"""
        return (60 + (idx % NODES_PER_ROW) * NODE_GAP_X,
                60 + (idx // NODES_PER_ROW) * ROW_GAP_Y)

    def _node_size(self, ctype: str) -> tuple[int, int]:
        return (DEFAULT_NODE_SIZE[0], int(DEFAULT_NODE_SIZE[1] + len(self.widget_order(ctype)) * 34))

    # ── schema 查询 ───────────────────────────────────────────────
    def _schema(self, class_type: str) -> dict:
        return (self.schemas or {}).get(class_type) or {}

    def output_names(self, class_type: str) -> list[str]:
        """节点的输出名列表。"""
        spec = self._schema(class_type)
        names = spec.get("output_name") or spec.get("output") or []
        if names:
            return [str(x) for x in names]
        builtin = BUILTIN_OUTPUTS.get(class_type)
        return list(builtin[0]) if builtin else ["OUTPUT"]

    def output_type(self, class_type: str, slot: int) -> str:
        """节点第 ``slot`` 个输出的类型。"""
        types = self._schema(class_type).get("output") or []
        if types and 0 <= int(slot) < len(types):
            return str(types[int(slot)])
        builtin = BUILTIN_OUTPUTS.get(class_type)
        if builtin and 0 <= int(slot) < len(builtin[1]):
            return builtin[1][int(slot)]
        return "*"

    def input_type(self, class_type: str, iname: str) -> str:
        """节点某个连线输入的类型（schema → 连线来源 → 内置表）。"""
        inp = self._schema(class_type).get("input") or {}
        for sect in ("required", "optional"):
            entry = (inp.get(sect) or {}).get(iname)
            if isinstance(entry, list) and entry:
                t = entry[0]
                if isinstance(t, list):
                    return "COMBO"
                if isinstance(t, str) and t not in WIDGET_TYPES:
                    return t
        for src, slot, dst, dst_input in self.edges:
            if dst_input == iname and self.nodes.get(dst, {}).get("class_type") == class_type:
                return self.output_type(self.nodes[src]["class_type"], slot)
        return BUILTIN_INPUT_TYPES.get(class_type, {}).get(iname, "*")

    # ── 指纹 / 摘要 ───────────────────────────────────────────────
    def fingerprint(self) -> str:
        """工作流指纹（16 位十六进制）：**忽略 seed**。

        忽略 seed 的理由：seed 是每张图都要换的变量，
        算进指纹会让「同一套参数」永远无法比较、无法去重。
        """
        canon = self.to_api()
        for node in canon.values():
            for k in ("seed", "noise_seed"):
                if k in (node.get("inputs") or {}):
                    node["inputs"][k] = "<seed>"
        blob = json.dumps(canon, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def summary(self) -> dict:
        """给 UI / 日志用的摘要。"""
        return {
            "title": self.title,
            "nodes": len(self.nodes), "links": len(self.edges),
            "fingerprint": self.fingerprint(), "seed": self.seed(),
            "classes": sorted({n["class_type"] for n in self.nodes.values()}),
            "warnings": list(self.warnings),
        }

    @staticmethod
    def _is_link_value(v) -> bool:
        return isinstance(v, (list, tuple)) and len(v) == 2 and isinstance(v[0], str)


# ══════════════════════════════════════════════════════════════════════
#  内部工具
# ══════════════════════════════════════════════════════════════════════
def _parse_lora(item) -> tuple[str, float]:
    """``"name.safetensors:0.8"`` → ``("name.safetensors", 0.8)``。"""
    if isinstance(item, (list, tuple)) and len(item) == 2:
        return str(item[0]), float(item[1])
    s = str(item or "").strip()
    if not s:
        return "", 1.0
    if ":" in s:
        name, _, strength = s.rpartition(":")
        try:
            return name.strip(), float(strength)
        except ValueError:
            return s, 1.0
    return s, 1.0


def parse_loras(loras) -> list[tuple[str, float]]:
    """把 ``["a.safetensors:0.8", ("b", 0.6)]`` 统一成 ``[(名字, 强度), ...]``（最多 2 个）。"""
    return [_parse_lora(x) for x in list(loras or []) if str(x).strip()][:2]


def _chain_loras(g: Graph, src: str, loras) -> str:
    """串 0-2 个 ``LoraLoaderModelOnly``（Krea/Qwen 链路）；返回最后的 MODEL 源。"""
    items = parse_loras(loras)
    if not items:
        return src
    if not g.has("LoraLoaderModelOnly"):
        g.warn("缺少节点 LoraLoaderModelOnly（Load LoRA）→ 跳过全部 LoRA。")
        return src
    for name, strength in items:
        nid = g.add("LoraLoaderModelOnly", _title=f"LoRA {name} @{strength}",
                    lora_name=name, strength_model=float(strength))
        g.link(nid, "model", src, 0)
        src = nid
    return src


def _krea_sampling(g: Graph, src: str, width: int, height: int,
                   profile: ModelProfile) -> str:
    """Krea/Qwen 的流匹配 shift（``ModelSamplingFlux(max_shift=1.15)``）。"""
    if not g.has("ModelSamplingFlux"):
        g.warn("缺少节点 ModelSamplingFlux → 跳过 shift 1.15（画质可能略降，链路仍可跑）。")
        return src
    ex = profile.extras or {}
    nid = g.add("ModelSamplingFlux",
                max_shift=float(ex.get("max_shift", 1.15)),
                base_shift=float(ex.get("base_shift", 0.5)),
                width=int(width), height=int(height))
    g.link(nid, "model", src, 0)
    return nid


def _krea2_core(g: Graph, *, profile: ModelProfile, ckpt_or_unet: str, clip: str,
                vae: str, positive: str, negative: str, width: int, height: int,
                seed: int, steps: int, cfg: float, sampler: str, scheduler: str,
                loras) -> tuple[str, int]:
    """Krea 2 / Qwen-Image 的采样核心，返回 ``(IMAGE 源 id, 槽位)``。

    ``UNETLoader → LoraLoaderModelOnly×0-2 → ModelSamplingFlux(1.15) →
    CLIPTextEncode + ConditioningZeroOut → CFGGuider(cfg) + RandomNoise +
    KSamplerSelect(euler) + BasicScheduler(simple) → SamplerCustomAdvanced → VAEDecode``
    """
    ex = profile.extras or {}
    need = ("UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode",
            "ConditioningZeroOut", "CFGGuider", "RandomNoise", "KSamplerSelect",
            "BasicScheduler", "SamplerCustomAdvanced", "EmptyLatentImage",
            "VAEDecode")
    missing = [n for n in need if not g.has(n)]
    if missing:
        raise ComfyError(
            "Krea 2 链路缺少必要节点：" + "、".join(missing),
            "这些是 ComfyUI 核心节点，缺说明版本过旧或安装被裁剪；升级 ComfyUI 到 0.3.40+ 即可。"
            "若本机确实没有，请改用 SDXL 系底模（档案 illustrious / animagine）。",
            kind="node_missing", detail={"missing": missing})

    unet = g.add("UNETLoader", unet_name=ckpt_or_unet,
                 weight_dtype=str(ex.get("weight_dtype", "default")))
    clip_node = g.add("CLIPLoader", clip_name=clip,
                      type=str(ex.get("clip_type", "krea2")), device="default")
    vae_node = g.add("VAELoader", vae_name=vae)

    model_src = _chain_loras(g, unet, loras)
    model_src = _krea_sampling(g, model_src, width, height, profile)

    pos = g.add("CLIPTextEncode", text=positive)
    g.link(pos, "clip", clip_node, 0)
    base_neg = g.add("CLIPTextEncode", _title="负向（cfg=1 时不参与前向）", text=negative)
    g.link(base_neg, "clip", clip_node, 0)
    zero = g.add("ConditioningZeroOut", _title="负向清零（cfg=1 时负向不生效）")
    g.link(zero, "conditioning", base_neg, 0)

    guider = g.add("CFGGuider", cfg=float(cfg))
    g.link(guider, "model", model_src, 0)
    g.link(guider, "positive", pos, 0)
    g.link(guider, "negative", zero, 0)

    noise = g.add("RandomNoise", noise_seed=int(seed))
    sel = g.add("KSamplerSelect", sampler_name=sampler)
    sched = g.add("BasicScheduler", scheduler=scheduler, steps=int(steps), denoise=1.0)
    g.link(sched, "model", model_src, 0)
    latent = g.add("EmptyLatentImage", width=int(width), height=int(height), batch_size=1)

    sca = g.add("SamplerCustomAdvanced")
    g.link(sca, "noise", noise, 0)
    g.link(sca, "guider", guider, 0)
    g.link(sca, "sampler", sel, 0)
    g.link(sca, "sigmas", sched, 0)
    g.link(sca, "latent_image", latent, 0)

    dec = g.add("VAEDecode")
    g.link(dec, "samples", sca, 0)
    g.link(dec, "vae", vae_node, 0)
    return dec, 0


def _checkpoint_core(g: Graph, *, profile: ModelProfile, ckpt_or_unet: str,
                     positive: str, negative: str, width: int, height: int,
                     seed: int, steps: int, cfg: float, sampler: str,
                     scheduler: str, loras) -> tuple[str, int]:
    """SDXL / SD1.5 的采样核心：``CheckpointLoaderSimple + KSampler``。

    ``profile.clip_skip`` 非空（Pony / SD1.5 的 ``-2``）时插一个
    ``CLIPSetLastLayer(stop_at_clip_layer=-2)``。
    """
    need = ("CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage",
            "KSampler", "VAEDecode")
    missing = [n for n in need if not g.has(n)]
    if missing:
        raise ComfyError("SDXL/SD1.5 链路缺少必要节点：" + "、".join(missing),
                         "这些都是 ComfyUI 核心节点，升级 ComfyUI 即可。",
                         kind="node_missing", detail={"missing": missing})
    ckpt = g.add("CheckpointLoaderSimple", ckpt_name=ckpt_or_unet)
    model_src: str = ckpt
    clip_src: str = ckpt
    for name, strength in parse_loras(loras):
        if not g.has("LoraLoader"):
            g.warn("缺少节点 LoraLoader → 跳过 LoRA"
                   "（SDXL/SD1.5 链路要用 LoraLoader 才能同时改 CLIP）。")
            break
        nid = g.add("LoraLoader", _title=f"LoRA {name} @{strength}", lora_name=name,
                    strength_model=float(strength), strength_clip=float(strength))
        g.link(nid, "model", model_src, 0)
        g.link(nid, "clip", clip_src, 1)
        model_src, clip_src = nid, nid

    if profile.clip_skip:
        if g.has("CLIPSetLastLayer"):
            cs = g.add("CLIPSetLastLayer", _title=f"CLIP skip {profile.clip_skip}",
                       stop_at_clip_layer=int(profile.clip_skip))
            g.link(cs, "clip", clip_src, 1)
            clip_src = cs
        else:
            g.warn(f"档案 {profile.key} 要求 CLIP skip {profile.clip_skip}，"
                   "但缺少节点 CLIPSetLastLayer → 已跳过（出图质量可能下降）。")

    if profile.key == "noobai" and "vpred" in str(ckpt_or_unet).lower():
        if g.has("ModelSamplingDiscrete"):
            ms = g.add("ModelSamplingDiscrete", _title="V-prediction 修正",
                       sampling="v_prediction", zsnr=False)
            g.link(ms, "model", model_src, 0)
            model_src = ms
        else:
            g.warn("NoobAI 的 vpred 版本需要 ModelSamplingDiscrete(v_prediction)，"
                   "但本机没有该节点 → 出图可能全糊，建议换 eps 版本权重。")

    pos = g.add("CLIPTextEncode", text=positive)
    g.link(pos, "clip", clip_src, 1)
    neg = g.add("CLIPTextEncode", text=negative)
    g.link(neg, "clip", clip_src, 1)
    latent = g.add("EmptyLatentImage", width=int(width), height=int(height), batch_size=1)
    ks = g.add("KSampler", seed=int(seed), steps=int(steps), cfg=float(cfg),
               sampler_name=sampler, scheduler=scheduler, denoise=1.0)
    g.link(ks, "model", model_src, 0)
    g.link(ks, "positive", pos, 0)
    g.link(ks, "negative", neg, 0)
    g.link(ks, "latent_image", latent, 0)
    dec = g.add("VAEDecode")
    g.link(dec, "samples", ks, 0)
    g.link(dec, "vae", ckpt, 2)
    return dec, 0


def _core_for(g: Graph, *, profile: ModelProfile, ckpt_or_unet: str, clip: str,
              vae: str, positive: str, negative: str, width: int, height: int,
              seed: int, steps: int, cfg: float, sampler: str, scheduler: str,
              loras) -> tuple[str, int]:
    """按 ``profile.chain`` 分派到对应采样核心。"""
    if profile.chain in ("krea2", "qwen", "flux"):
        return _krea2_core(g, profile=profile, ckpt_or_unet=ckpt_or_unet, clip=clip,
                           vae=vae, positive=positive, negative=negative,
                           width=width, height=height, seed=seed, steps=steps,
                           cfg=cfg, sampler=sampler, scheduler=scheduler, loras=loras)
    return _checkpoint_core(g, profile=profile, ckpt_or_unet=ckpt_or_unet,
                            positive=positive, negative=negative, width=width,
                            height=height, seed=seed, steps=steps, cfg=cfg,
                            sampler=sampler, scheduler=scheduler, loras=loras)


def _save(g: Graph, src: tuple[str, int], save_prefix: str) -> str:
    if not g.has("SaveImage"):
        raise ComfyError("缺少 SaveImage 节点", "升级 ComfyUI。", kind="node_missing")
    nid = g.add("SaveImage", filename_prefix=save_prefix)
    g.link(nid, "images", src[0], src[1])
    return nid


# ══════════════════════════════════════════════════════════════════════
#  后处理片段
# ══════════════════════════════════════════════════════════════════════
def append_upscale(g: Graph, image_src: tuple[str, int], *,
                   upscale_model: str = "",
                   target: tuple[int, int] | None = None,
                   method: str = "lanczos") -> tuple[str, int]:
    """接「模型放大 → 精确降采样」，返回新的 IMAGE 源。

    ⚠️ ``ImageUpscaleWithModel`` **不能指定目标尺寸**（倍率由模型固定，通常 4x），
    所以**必须后接 ``ImageScale``** 才能落到 ``ART_TARGET_2X``（842×1228）。
    """
    src_id, src_slot = image_src
    if upscale_model:
        if g.has("UpscaleModelLoader") and g.has("ImageUpscaleWithModel"):
            loader = g.add("UpscaleModelLoader", _title=f"放大模型 {upscale_model}",
                           model_name=upscale_model)
            up = g.add("ImageUpscaleWithModel", _title="模型放大（倍率固定，不能指尺寸）")
            g.link(up, "upscale_model", loader, 0)
            g.link(up, "image", src_id, src_slot)
            src_id, src_slot = up, 0
        else:
            g.warn("缺少 UpscaleModelLoader / ImageUpscaleWithModel → 跳过模型放大，"
                   "只做 lanczos 重采样（不增加细节）。")
    tgt = tuple(target) if target else TARGET_2X
    if g.has("ImageScale"):
        sc = g.add("ImageScale", _title=f"降采样到 {tgt[0]}×{tgt[1]}",
                   upscale_method=method, width=int(tgt[0]), height=int(tgt[1]),
                   crop="disabled")
        g.link(sc, "image", src_id, src_slot)
        src_id, src_slot = sc, 0
    else:
        g.warn("缺少 ImageScale → 跳过尺寸归一（输出保持放大后的尺寸）。")
    return src_id, src_slot


def append_remove_bg(g: Graph, image_src: tuple[str, int], *,
                     model: str = "", node: str = "",
                     local_models: list[str] | None = None,
                     invert_core_mask: bool = True,
                     threshold: float = 0.25,
                     grow: int = 1) -> tuple[str, int]:
    """接抠底，返回**带 alpha 的** IMAGE 源。

    选择顺序（**先探测再决定** —— 不能硬上）：

    1. ``BiRefNetRMBG``（ComfyUI-RMBG 插件）：卡图/插画首选 ``BiRefNet_toonout``。
       但**该插件的权重是按 HF 仓库逐个下载的**（``models/RMBG/BiRefNet/``），
       本机只放了一个 ``model.safetensors``（文件名不匹配）→ 选了它会去联网下载。
       所以只有 ``local_models`` 里真的列出了目标权重时才走它。
    2. 核心 ``LoadBackgroundRemovalModel`` + ``RemoveBackground`` + ``JoinImageWithAlpha``
       —— ComfyUI 0.3.x 自带，吃 ``models/background_removal/`` 下的 BiRefNet 权重
       （本机有 ``BiRefNet/model.safetensors``）。**这是本机唯一能离线跑的抠底链路。**
    3. ``BriaRemoveImageBackground``（BRIA 的 API 节点，需要账号）。
    4. 全都没有 → 只记 warning 并原样返回，不报错。

    ⚠️ **核心 ``RemoveBackground`` 的三个坑**（本机实测）：

    * 它只输出 **MASK**，必须自己用 ``JoinImageWithAlpha`` 拼回 alpha 通道；
    * 在这个 ComfyUI 版本上它的 mask **极性与直觉相反** —— 实测对一张
      「暗色主体 + 亮色背景」的卡图，**主体 α=0（全透明）、背景 α=255（不透明）**，
      所以默认要串一个 ``InvertMask``（``invert_core_mask=True``）。
      若你的主体本身是亮色（光属性天使之类）抠出来是空的，把它改成 ``False``；
    * 它的输出是**很软的灰度 matte**，实测半透明像素占 46%（背景烟雾没有被压到 0）
      → 直接拿去合成会「背景透出来」。所以默认再串 ``ThresholdMask(0.25)``
      + ``GrowMask(+1)`` 把背景压成硬透明、同时略微外扩以消除白边。

    :param local_models: ``LoadBackgroundRemovalModel.bg_removal_name`` 的候选列表，
        来自 ``ComfyClient.models()["background_removal"]``。
    :param threshold: ``ThresholdMask`` 的阈值（0 = 不处理；0.2–0.35 是卡图常用区间）。
    :param grow: ``GrowMask`` 的外扩像素（0 = 不处理；1–3 用于消除边缘白边）。
    """
    src_id, src_slot = image_src
    local = [str(x) for x in (local_models or [])]
    want = model or "BiRefNet_toonout"
    birefnet_ok = bool(g.has("BiRefNetRMBG")) and (not local or _weight_present(want, local))
    if birefnet_ok:
        node = node or "BiRefNetRMBG"
    elif not node:
        if (g.has("LoadBackgroundRemovalModel") and g.has("RemoveBackground")
                and g.has("JoinImageWithAlpha") and local):
            node = "core"
        elif g.has("BriaRemoveImageBackground"):
            node = "BriaRemoveImageBackground"
        elif g.has("BiRefNetRMBG"):
            node = "BiRefNetRMBG"          # 本机没有核心权重 → 只能用它（可能要联网下载）
            g.warn(f"BiRefNetRMBG 的权重 `{want}` 不在本机 models/RMBG/ 里 → "
                   "运行时它会去 HuggingFace 下载（需要联网）。"
                   "想离线跑请把权重放进 ComfyUI/models/RMBG/BiRefNet/，"
                   "或改用核心的 LoadBackgroundRemovalModel（吃 "
                   "models/background_removal/）。")
    if node == "BiRefNetRMBG":
        nid = g.add("BiRefNetRMBG", _title="BiRefNet 抠底（插画调优）",
                    model=want, sensitivity=1.0, mask_blur=0, mask_offset=0,
                    invert_output=False, refine_foreground=True,
                    background="Alpha", background_color="#222222")
        g.link(nid, "image", src_id, src_slot)
        return nid, 0
    if node == "core":
        loader = g.add("LoadBackgroundRemovalModel", _title="抠底模型（核心，离线可用）",
                       bg_removal_name=local[0])
        rb = g.add("RemoveBackground", _title="Remove Background（只出 MASK）")
        g.link(rb, "bg_removal_model", loader, 0)
        g.link(rb, "image", src_id, src_slot)
        mask_src: tuple[str, int] = (rb, 0)
        if invert_core_mask:
            inv = _invert_mask(g, (rb, 0))
            if inv is not None:
                mask_src = inv
            else:
                g.warn("缺少 InvertMask / MaskToImage+ImageInvert+ImageToMask 节点 → "
                       "无法修正核心 RemoveBackground 的 mask 极性，"
                       "抠出来的主体可能反而是透明的。")
        if threshold and threshold > 0:
            if g.has("ThresholdMask"):
                th = g.add("ThresholdMask", _title=f"二值化 mask（阈值 {threshold}）",
                           value=float(threshold))
                g.link(th, "mask", mask_src[0], mask_src[1])
                mask_src = (th, 0)
            else:
                g.warn("缺少 ThresholdMask → 跳过二值化，软 matte 会让背景微微透出来。")
        if grow and int(grow) != 0 and g.has("GrowMask"):
            gr = g.add("GrowMask", _title=f"外扩 {int(grow)}px（消白边）",
                       expand=int(grow), tapered_corners=True)
            g.link(gr, "mask", mask_src[0], mask_src[1])
            mask_src = (gr, 0)
        join = g.add("JoinImageWithAlpha", _title="拼回 alpha 通道")
        g.link(join, "image", src_id, src_slot)
        g.link(join, "alpha", mask_src[0], mask_src[1])
        return join, 0
    if node == "BriaRemoveImageBackground":
        nid = g.add("BriaRemoveImageBackground", _title="Bria 抠底（需要 API Key）",
                    moderation="false", seed=0)
        g.link(nid, "image", src_id, src_slot)
        return nid, 0
    g.warn("本机没有可用的抠底节点（BiRefNetRMBG / LoadBackgroundRemovalModel+"
           "RemoveBackground / BriaRemoveImageBackground 都没有）→ 跳过抠底，"
           "输出仍是不透明图。")
    return src_id, src_slot


def _invert_mask(g: Graph, mask_src: tuple[str, int]) -> tuple[str, int] | None:
    """反转一个 MASK。优先用 ``InvertMask``；没有就走 ``MaskToImage`` → ``ImageInvert``
    → ``ImageToMask`` 这三步（注意 **``ImageInvert`` 只吃 IMAGE，不吃 MASK** ——
    直接把它接在 MASK 上会得到 400 的 "Return type mismatch"。本机实测踩过）。

    :return: 反转后的 MASK 源；本机没有任何可行路径时返回 ``None``。
    """
    src_id, src_slot = mask_src
    if g.has("InvertMask"):
        inv = g.add("InvertMask", _title="反转 mask（核心 RemoveBackground 极性相反）")
        g.link(inv, "mask", src_id, src_slot)
        return inv, 0
    if g.has("MaskToImage") and g.has("ImageInvert") and g.has("ImageToMask"):
        m2i = g.add("MaskToImage", _title="MASK → IMAGE（为了能反转）")
        g.link(m2i, "mask", src_id, src_slot)
        inv = g.add("ImageInvert", _title="反转 mask")
        g.link(inv, "image", m2i, 0)
        i2m = g.add("ImageToMask", _title="IMAGE → MASK", channel="red")
        g.link(i2m, "image", inv, 0)
        return i2m, 0
    return None


def _weight_present(want: str, local: list[str]) -> bool:
    """本机 ``models/RMBG/BiRefNet/`` 里有没有目标 BiRefNet 权重。

    ComfyUI-RMBG 插件按 ``<名字>.safetensors`` 下载；本机常见的情况是只放了一个
    ``model.safetensors``（HF 原仓库命名），此时**不能**选它，否则会触发联网下载。
    """
    w = str(want or "").lower()
    for path in local:
        low = str(path).lower().replace("\\", "/")
        base = low.rsplit("/", 1)[-1]
        if base.startswith(w) or w in base:
            return True
    return False


# ══════════════════════════════════════════════════════════════════════
#  构造器
# ══════════════════════════════════════════════════════════════════════
def build_t2i(*, profile: ModelProfile, ckpt_or_unet: str, clip: str = "", vae: str = "",
              positive: str, negative: str, width: int, height: int, seed: int,
              steps: int, cfg: float, sampler: str, scheduler: str, loras=(),
              save_prefix: str = SAVE_PREFIX_DEFAULT,
              available: set[str] | None = None, schemas: dict | None = None,
              upscale: bool = False, upscale_model: str = "",
              target_size: tuple[int, int] | None = None,
              remove_bg: bool = False, bg_model: str = "",
              bg_invert: bool = True,
              local_bg_models: list[str] | None = None) -> Graph:
    """文生图。**按 ``profile.chain`` 分派**到三条链路之一。

    * ``krea2`` → ``UNETLoader``(qwen3vl CLIP, ``type="krea2"``) + ``SamplerCustomAdvanced``
    * ``qwen``  → 同结构，文本编码器 / VAE 按档案 ``extras`` 走
    * ``sdxl`` / ``sd15`` → ``CheckpointLoaderSimple`` + ``KSampler``
      （``sd15`` / ``pony`` 强制 ``CLIPSetLastLayer(stop_at_clip_layer=-2)``）
    * ``flux``  → 按 Krea 2 的流匹配结构处理（同为 DiT + shift）

    :param upscale: 是否追加「放大 → ``target_size``（默认 842×1228）降采样」。
    :param remove_bg: 是否追加抠底（输出 PNG 带 alpha）。
    """
    g = Graph(available=available, schemas=schemas,
              title=f"CardForge t2i ({profile.key})")
    img = _core_for(g, profile=profile, ckpt_or_unet=ckpt_or_unet, clip=clip, vae=vae,
                    positive=positive, negative=negative, width=int(width),
                    height=int(height), seed=int(seed), steps=int(steps),
                    cfg=float(cfg), sampler=sampler, scheduler=scheduler, loras=loras)
    if upscale:
        img = append_upscale(g, img, upscale_model=upscale_model,
                             target=target_size or TARGET_2X)
    if remove_bg:
        img = append_remove_bg(g, img, model=bg_model, local_models=local_bg_models,
                               invert_core_mask=bg_invert)
    _save(g, img, save_prefix)
    return g


def build_style_ref(*, profile: ModelProfile, ckpt_or_unet: str, clip: str = "",
                    vae: str = "", positive: str, negative: str, width: int,
                    height: int, seed: int, steps: int, cfg: float, sampler: str,
                    scheduler: str, style_refs, strength: float = 1.0,
                    style_lora: str = "krea2_style_reference.safetensors",
                    save_prefix: str = SAVE_PREFIX_DEFAULT,
                    available: set[str] | None = None, schemas: dict | None = None,
                    images: dict | None = None) -> Graph:
    """**画风参考**（Krea 2 链路）：注入参考图的风格，不改内容。

    链路：Krea 2 基础链 + ``krea2_style_reference`` LoRA +
    ``TextEncodeQwenImageEditPlus``(image1-3) + ``FluxKontextMultiReferenceLatentMethod``。

    :param style_refs: ComfyUI 侧的图片引用（``ComfyClient.upload()`` 返回的 ``ref``，
        形如 ``CardForge/xxx.png``）或本地路径（会给 warning 提示你先 upload）。
    :param strength: 参考强度；0.5–0.8 是「只统一画风」的区间。
    :param images: ``{本地路径: 服务器引用}`` 映射，用来把本地路径换成服务器引用。
    """
    g = Graph(available=available, schemas=schemas,
              title=f"CardForge style_ref ({profile.key})")
    need = ("TextEncodeQwenImageEditPlus", "FluxKontextMultiReferenceLatentMethod",
            "LoadImage")
    miss = [n for n in need if not g.has(n)]
    if miss:
        raise ComfyError(
            "画风参考链路缺少节点：" + "、".join(miss),
            "画风参考需要 ComfyUI 核心的 TextEncodeQwenImageEditPlus 与 "
            "FluxKontextMultiReferenceLatentMethod（0.3.40+ 自带）。本机若没有，"
            "请改用「固定风格前缀（SERIES_STYLE_KEY）+ 每张换 seed」的 t2i 方案。",
            kind="node_missing", detail={"missing": miss})
    loras = [(style_lora, float(strength))]
    img = _krea2_core(g, profile=profile, ckpt_or_unet=ckpt_or_unet, clip=clip,
                      vae=vae, positive=positive, negative=negative, width=width,
                      height=height, seed=seed, steps=steps, cfg=cfg, sampler=sampler,
                      scheduler=scheduler, loras=loras)
    # 找到正向编码节点，换成带参考图的编码
    pos_id = None
    for nid in g.nodes_of("CLIPTextEncode"):
        if g.nodes[nid]["inputs"].get("text") == positive:
            pos_id = nid
            break
    if pos_id is None:
        raise ComfyError("画风参考：找不到正向编码节点", kind="bad_prompt")
    clip_ref = list(g.nodes[pos_id]["inputs"]["clip"])
    vae_ids = g.nodes_of("VAELoader")
    g.remove(pos_id)
    enc = g.add("TextEncodeQwenImageEditPlus", _title="画风参考编码（最多 3 张）",
                prompt=positive)
    g.link(enc, "clip", str(clip_ref[0]), int(clip_ref[1]))
    if vae_ids:
        g.link(enc, "vae", vae_ids[0], 0)
    img_map = dict(images or {})
    refs = list(style_refs or [])[:3]
    if not refs:
        g.warn("没有给 style_refs → 画风参考链路退化为普通文生图。")
    for i, ref in enumerate(refs, start=1):
        s = str(ref)
        server_ref = img_map.get(s, s)
        if s not in img_map and (":" in s or s.startswith(("/", "\\"))):
            g.warn(f"参考图 {s} 看起来是本地路径；请先 ComfyClient.upload() "
                   "再把返回的 ref 传进来，否则 LoadImage 找不到文件。")
        li = g.add("LoadImage", _title=f"风格参考 {i}", image=server_ref)
        g.link(enc, f"image{i}", li, 0)
    refm = g.add("FluxKontextMultiReferenceLatentMethod", _title="参考 latent 注入方式",
                 reference_latents_method="index_timestep_zero")
    g.link(refm, "conditioning", enc, 0)
    for nid in g.nodes_of("CFGGuider"):
        g.link(nid, "positive", refm, 0)
    _save(g, img, save_prefix)
    return g


def build_ipadapter(*, profile: ModelProfile, ckpt_or_unet: str, clip: str = "",
                    vae: str = "", positive: str, negative: str, width: int,
                    height: int, seed: int, steps: int, cfg: float, sampler: str,
                    scheduler: str, ref_images, weight: float = 0.65,
                    weight_type: str = "style transfer",
                    preset: str = "STANDARD (medium strength)",
                    loras=(), save_prefix: str = SAVE_PREFIX_DEFAULT,
                    clip_vision: str = "", available: set[str] | None = None,
                    schemas: dict | None = None, images: dict | None = None) -> Graph:
    """IPAdapter 一致性：用一张「风格母版」统一画风。

    ⚠️ **必须先探测再决定用不用**：IPAdapter 需要 ``models/clip_vision/`` 下的
    CLIP Vision 模型。本机该目录是空的（``CLIPVisionLoader.clip_name`` 候选为 ``[]``）
    → **本机走 IPAdapter 必然失败**，此时会抛 ``ComfyError(kind="model_missing")``，
    调用方应回落到「固定风格前缀 + 每张换 seed」。

    ``IPAdapterUnifiedLoader`` 的 ``preset`` 要与底模架构匹配：
    ``LIGHT`` / ``FULL FACE`` **仅 SD1.5**，用在 SDXL 上会直接报错。
    """
    g = Graph(available=available, schemas=schemas,
              title=f"CardForge ipadapter ({profile.key})")
    miss = [n for n in ("IPAdapterUnifiedLoader", "IPAdapterAdvanced", "LoadImage")
            if not g.has(n)]
    if miss:
        raise ComfyError(
            "IPAdapter 链路缺少节点：" + "、".join(miss),
            "需要装 ComfyUI_IPAdapter_plus 插件"
            "（github.com/cubiq/ComfyUI_IPAdapter_plus）。装上之前请用"
            "「固定风格前缀 + 每张换 seed」的方案保持系列一致性。",
            kind="node_missing", detail={"missing": miss})
    if profile.chain in ("krea2", "qwen", "flux"):
        raise ComfyError(
            f"IPAdapter 不适用于 {profile.key}（{profile.chain}）链路",
            "IPAdapter 是 SD1.5 / SDXL 的 UNet cross-attention 补丁，"
            "Krea 2 / Qwen-Image 这类 DiT + 流匹配模型没有对应的 IPAdapter 权重。"
            "要统一画风请改用：① krea2 的画风参考链路（build_style_ref）；"
            "② 固定风格前缀 + 不同 seed 的系列批。",
            kind="model_missing", detail={"profile": profile.key, "chain": profile.chain})
    if not clip_vision:
        raise ComfyError(
            "IPAdapter 需要 CLIP Vision 模型，但没有指定 clip_vision",
            "把 CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors（SD1.5/SDXL）或 "
            "CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors（ViT-G）放进 "
            "ComfyUI/models/clip_vision/，然后用 "
            "client.combo_options('CLIPVisionLoader','clip_name') 确认它在候选里。"
            "本机该目录为空 → 目前只能用 t2i 方案。",
            kind="model_missing")
    img_map = dict(images or {})
    ckpt = g.add("CheckpointLoaderSimple", ckpt_name=ckpt_or_unet)
    model_src: str = ckpt
    clip_src: str = ckpt
    for name, strength in parse_loras(loras):
        if not g.has("LoraLoader"):
            g.warn("缺少 LoraLoader → 跳过 IPAdapter 链路前的 LoRA。")
            break
        nid = g.add("LoraLoader", lora_name=name, strength_model=float(strength),
                    strength_clip=float(strength))
        g.link(nid, "model", model_src, 0)
        g.link(nid, "clip", clip_src, 1)
        model_src, clip_src = nid, nid
    unified = g.add("IPAdapterUnifiedLoader", preset=preset)
    g.link(unified, "model", model_src, 0)
    adv = g.add("IPAdapterAdvanced", _title=f"IPAdapter（{weight_type} @{weight}）",
                weight=float(weight), weight_type=weight_type, combine_embeds="average",
                start_at=0.0, end_at=1.0, embeds_scaling="K+V")
    g.link(adv, "model", unified, 0)
    g.link(adv, "ipadapter", unified, 1)
    cv = g.add("CLIPVisionLoader", clip_name=clip_vision)
    g.link(adv, "clip_vision", cv, 0)
    for i, ref in enumerate(list(ref_images or [])[:1]):
        li = g.add("LoadImage", _title=f"风格母版 {i + 1}",
                   image=img_map.get(str(ref), str(ref)))
        g.link(adv, "image", li, 0)
    pos = g.add("CLIPTextEncode", text=positive)
    g.link(pos, "clip", clip_src, 1)
    neg = g.add("CLIPTextEncode", text=negative)
    g.link(neg, "clip", clip_src, 1)
    latent = g.add("EmptyLatentImage", width=int(width), height=int(height), batch_size=1)
    ks = g.add("KSampler", seed=int(seed), steps=int(steps), cfg=float(cfg),
               sampler_name=sampler, scheduler=scheduler, denoise=1.0)
    g.link(ks, "model", adv, 0)
    g.link(ks, "positive", pos, 0)
    g.link(ks, "negative", neg, 0)
    g.link(ks, "latent_image", latent, 0)
    dec = g.add("VAEDecode")
    g.link(dec, "samples", ks, 0)
    g.link(dec, "vae", ckpt, 2)
    _save(g, (dec, 0), save_prefix)
    return g


def _image_entry(g: Graph, image) -> tuple[str, int]:
    """把 ``image`` 参数（图片名 / ``(id, slot)`` / :class:`Graph`）统一成 IMAGE 源。

    传 :class:`Graph` 时会把上游节点**整并进来**（丢掉它的 ``SaveImage`` 汇点），
    这样导出的工作流才是自洽的、能单独导入运行的。
    """
    if isinstance(image, Graph):
        src = image.image_source()
        sink = image.sink()
        id_map: dict[str, str] = {}
        for nid, node in image.nodes.items():
            if nid == sink:
                continue
            new_id = g.add(node["class_type"], _title=node.get("_title", ""))
            id_map[nid] = new_id
            g.nodes[new_id]["inputs"] = dict(node["inputs"])
        for src_id, slot, dst, name in image.edges:
            if src_id in id_map and dst in id_map:
                g.link(id_map[dst], name, id_map[src_id], slot)
        for w in image.warnings:
            g.warn(w)
        if src[0] in id_map:
            return id_map[src[0]], src[1]
        return src
    if isinstance(image, (list, tuple)) and len(image) == 2 and isinstance(image[0], str):
        return str(image[0]), int(image[1])
    if not g.has("LoadImage"):
        raise ComfyError("缺少 LoadImage 节点", "升级 ComfyUI。", kind="node_missing")
    li = g.add("LoadImage", image=str(image))
    return li, 0


def build_upscale(*, graph_or_image, upscale_model: str, target: tuple[int, int],
                  method: str = "lanczos", save_prefix: str = SAVE_PREFIX_DEFAULT,
                  available: set[str] | None = None, schemas: dict | None = None) -> Graph:
    """放大 + 精确降采样。

    ``graph_or_image`` 可以是 :class:`Graph`（会把上游整并进来，保证导入后连线完整）、
    ``(node_id, slot)``，或 ``LoadImage`` 的图片名。

    ``ImageUpscaleWithModel`` 不接尺寸参数，**必须**后接 ``ImageScale`` 才能落到目标尺寸。
    """
    g = Graph(available=available, schemas=schemas, title="CardForge upscale")
    src = _image_entry(g, graph_or_image)
    src = append_upscale(g, src, upscale_model=upscale_model, target=target, method=method)
    _save(g, src, save_prefix)
    return g


def build_remove_bg(*, image, model: str = "", node: str = "",
                    save_prefix: str = SAVE_PREFIX_DEFAULT,
                    available: set[str] | None = None,
                    schemas: dict | None = None,
                    local_models: list[str] | None = None,
                    invert_core_mask: bool = True,
                    threshold: float = 0.25, grow: int = 1) -> Graph:
    """抠底。``image`` 可以是图片名、``(node_id, slot)`` 或 :class:`Graph`。

    节点选择顺序：``BiRefNetRMBG``（本机权重齐全时）→ 核心
    ``LoadBackgroundRemovalModel`` + ``RemoveBackground`` + ``InvertMask`` +
    ``ThresholdMask`` + ``GrowMask`` + ``JoinImageWithAlpha``
    → ``BriaRemoveImageBackground``。一个都没有时**不报错**，
    只在 ``graph.warnings`` 里记一条（图仍可跑，只是没抠底）。

    :param model: BiRefNet 权重名。卡图/插画首选 ``BiRefNet_toonout``；
        输入超过约 1500px 必须用 ``BiRefNet-HR``（否则 general 会内部降采样丢边缘）。
    :param local_models: ``ComfyClient.models()["background_removal"]``，
        用来判断本机是否真有该权重（避免触发联网下载）。
    :param invert_core_mask: 修正核心 ``RemoveBackground`` 的反极性（详见
        :func:`append_remove_bg` 的说明）。
    :param threshold: 二值化阈值（0 = 不处理）。
    :param grow: 外扩像素（0 = 不处理）。
    """
    g = Graph(available=available, schemas=schemas, title="CardForge remove_bg")
    src = _image_entry(g, image)
    src = append_remove_bg(g, src, model=model, node=node, local_models=local_models,
                           invert_core_mask=invert_core_mask, threshold=threshold,
                           grow=grow)
    _save(g, src, save_prefix)
    return g


def build_inpaint_edit(*, profile: ModelProfile, ckpt_or_unet: str, clip: str = "",
                       vae: str = "", image: str, mask: str, instruction: str,
                       negative: str = "", width: int = 0, height: int = 0,
                       seed: int = -1, steps: int = 0, cfg: float = 0.0,
                       sampler: str = "", scheduler: str = "", denoise: float = 0.6,
                       save_prefix: str = SAVE_PREFIX_DEFAULT,
                       available: set[str] | None = None,
                       schemas: dict | None = None) -> Graph:
    """局部重绘 / 指令编辑。

    * ``qwen`` / ``krea2`` 档案 → ``LoadImage`` + ``VAEEncode`` + ``SetLatentNoiseMask``
      + ``TextEncodeQwenImageEditPlus``（i2i 文本编码器）。
    * ``sdxl`` / ``sd15`` 档案 → ``VAEEncodeForInpaint`` + ``KSampler(denoise)``。

    ⚠️ 两个坑（调研结论）：**mask 尺寸必须与图像一致**（否则重绘区域错位）；
    **``denoise`` 不能停在 1.0**（那就等于整图重画），建议 0.6–0.8。
    """
    g = Graph(available=available, schemas=schemas,
              title=f"CardForge inpaint ({profile.key})")
    need = ("LoadImage", "LoadImageMask", "VAEDecode")
    miss = [n for n in need if not g.has(n)]
    if miss:
        raise ComfyError("局部重绘链路缺少节点：" + "、".join(miss),
                         "这些都是 ComfyUI 核心节点，升级 ComfyUI 即可。",
                         kind="node_missing", detail={"missing": miss})
    seed = int(seed) if int(seed) >= 0 else new_seed()
    steps = int(steps or profile.steps)
    cfg = float(cfg or profile.cfg)
    sampler = sampler or profile.sampler
    scheduler = scheduler or profile.scheduler
    denoise = float(denoise)
    if denoise >= 0.995:
        g.warn(f"denoise={denoise} 等于整图重画（局部重绘建议 0.6–0.8）；已按 0.8 处理。")
        denoise = 0.8

    img = g.add("LoadImage", _title="待编辑图", image=image)
    msk = g.add("LoadImageMask", _title="重绘区域（白=重绘）", image=mask, channel="alpha")
    if profile.chain in ("krea2", "qwen", "flux"):
        ex = profile.extras or {}
        unet = g.add("UNETLoader", unet_name=ckpt_or_unet,
                     weight_dtype=str(ex.get("weight_dtype", "default")))
        clip_name = clip or str(ex.get("text_encoder_i2i") or ex.get("clip") or "")
        clip_node = g.add("CLIPLoader", clip_name=clip_name,
                          type=str(ex.get("clip_type", "krea2")), device="default")
        vae_node = g.add("VAELoader", vae_name=vae or str(ex.get("vae") or ""))
        model_src = _krea_sampling(g, _chain_loras(g, unet, ()),
                                   int(width or profile.width),
                                   int(height or profile.height), profile)
        ve = g.add("VAEEncode")
        g.link(ve, "pixels", img, 0)
        g.link(ve, "vae", vae_node, 0)
        snm = g.add("SetLatentNoiseMask", _title="只在白区重绘")
        g.link(snm, "samples", ve, 0)
        g.link(snm, "mask", msk, 0)
        latent = (snm, 0)
        if g.has("TextEncodeQwenImageEditPlus"):
            pos = g.add("TextEncodeQwenImageEditPlus", _title="编辑指令", prompt=instruction)
            g.link(pos, "clip", clip_node, 0)
            g.link(pos, "vae", vae_node, 0)
            g.link(pos, "image1", img, 0)
            pos_ref: tuple[str, int] = (pos, 0)
            if g.has("FluxKontextMultiReferenceLatentMethod"):
                refm = g.add("FluxKontextMultiReferenceLatentMethod",
                             reference_latents_method="index_timestep_zero")
                g.link(refm, "conditioning", pos, 0)
                pos_ref = (refm, 0)
        else:
            p2 = g.add("CLIPTextEncode", text=instruction)
            g.link(p2, "clip", clip_node, 0)
            pos_ref = (p2, 0)
            g.warn("缺少 TextEncodeQwenImageEditPlus → 局部重绘退化为纯提示词重绘"
                   "（不参考原图，一致性会下降）。")
        n2 = g.add("CLIPTextEncode", text=negative)
        g.link(n2, "clip", clip_node, 0)
        zero = g.add("ConditioningZeroOut")
        g.link(zero, "conditioning", n2, 0)
        guider = g.add("CFGGuider", cfg=cfg)
        g.link(guider, "model", model_src, 0)
        g.link(guider, "positive", pos_ref[0], pos_ref[1])
        g.link(guider, "negative", zero, 0)
        noise = g.add("RandomNoise", noise_seed=seed)
        sel = g.add("KSamplerSelect", sampler_name=sampler)
        sched = g.add("BasicScheduler", scheduler=scheduler, steps=steps, denoise=denoise)
        g.link(sched, "model", model_src, 0)
        sca = g.add("SamplerCustomAdvanced")
        g.link(sca, "noise", noise, 0)
        g.link(sca, "guider", guider, 0)
        g.link(sca, "sampler", sel, 0)
        g.link(sca, "sigmas", sched, 0)
        g.link(sca, "latent_image", latent[0], latent[1])
        dec = g.add("VAEDecode")
        g.link(dec, "samples", sca, 0)
        g.link(dec, "vae", vae_node, 0)
    else:
        if not g.has("VAEEncodeForInpaint"):
            raise ComfyError("SDXL 局部重绘需要 VAEEncodeForInpaint 节点",
                             "升级 ComfyUI。", kind="node_missing")
        ckpt = g.add("CheckpointLoaderSimple", ckpt_name=ckpt_or_unet)
        enc = g.add("VAEEncodeForInpaint", grow_mask_by=8)
        g.link(enc, "pixels", img, 0)
        g.link(enc, "vae", ckpt, 2)
        g.link(enc, "mask", msk, 0)
        pos = g.add("CLIPTextEncode", text=instruction)
        g.link(pos, "clip", ckpt, 1)
        neg = g.add("CLIPTextEncode", text=negative)
        g.link(neg, "clip", ckpt, 1)
        ks = g.add("KSampler", seed=seed, steps=steps, cfg=cfg, sampler_name=sampler,
                   scheduler=scheduler, denoise=denoise)
        g.link(ks, "model", ckpt, 0)
        g.link(ks, "positive", pos, 0)
        g.link(ks, "negative", neg, 0)
        g.link(ks, "latent_image", enc, 0)
        dec = g.add("VAEDecode")
        g.link(dec, "samples", ks, 0)
        g.link(dec, "vae", ckpt, 2)
    if g.has("ImageCompositeMasked"):
        comp = g.add("ImageCompositeMasked",
                     _title="把重绘区贴回原图（未遮罩像素保持一致）",
                     x=0, y=0, resize_source=False)
        g.link(comp, "destination", img, 0)
        g.link(comp, "source", dec, 0)
        g.link(comp, "mask", msk, 0)
        out_src = (comp, 0)
    else:
        g.warn("缺少 ImageCompositeMasked → 未遮罩区域也会经过 VAE 往返（有轻微变化）。")
        out_src = (dec, 0)
    _save(g, out_src, save_prefix)
    return g


# ══════════════════════════════════════════════════════════════════════
#  校验 / 工具
# ══════════════════════════════════════════════════════════════════════
def validate(prompt: dict, schemas: dict | None = None) -> list[str]:
    """提交前自检（对应调研报告 A.3.4 的四条）。

    :return: 问题列表（空 = 通过）。
    """
    problems: list[str] = []
    ids = set((prompt or {}).keys())
    if not ids:
        return ["工作流为空。"]
    has_output = False
    for nid, node in (prompt or {}).items():
        ctype = (node or {}).get("class_type", "")
        if not ctype:
            problems.append(f"节点 {nid} 没有 class_type。")
            continue
        if schemas and ctype not in schemas:
            problems.append(f"节点 {nid} 的 class_type `{ctype}` 不在本机 /object_info 里"
                            "（自定义节点没装？）。")
        for iname, val in ((node or {}).get("inputs") or {}).items():
            if isinstance(val, (list, tuple)) and len(val) == 2 and isinstance(val[0], str):
                if val[0] not in ids:
                    problems.append(f"节点 {nid} 的输入 `{iname}` 指向不存在的节点 {val[0]}。")
        if ctype in ("SaveImage", "PreviewImage"):
            has_output = True
    if not has_output:
        problems.append("工作流里没有 SaveImage / PreviewImage —— 跑完不会有任何产物。")
    return problems


def bump_graph_seed(prompt: dict, step: int = 1) -> int:
    """把 API 图里所有 seed 一起换掉（批量出图必须换 seed，见 ``ComfyClient.queue``）。"""
    cur: int | None = None
    for node in (prompt or {}).values():
        for k in ("seed", "noise_seed"):
            v = ((node or {}).get("inputs") or {}).get(k)
            if isinstance(v, int):
                cur = v if cur is None else cur
    new = bump_seed(0 if cur is None else cur, step)
    for node in (prompt or {}).values():
        for k in ("seed", "noise_seed"):
            if isinstance(((node or {}).get("inputs") or {}).get(k), int):
                node["inputs"][k] = new
    return new


def ui_to_api(ui: dict, schemas: dict | None = None) -> dict:
    """把 **UI 格式**工作流反解成 API 格式（用于「导入后再跑一遍」的自检）。

    这是 ``to_ui`` 的逆运算：按 ``widgets_values`` 的顺序（并**跳过
    ``control_after_generate`` 这类 UI-only 占位**）把值映射回参数名。
    """
    schemas = schemas or {}
    nodes = {int(n["id"]): n for n in (ui.get("nodes") or [])}
    out: dict[str, dict] = {}
    for link in (ui.get("links") or []):
        if isinstance(link, dict):        # 兼容对象式 links
            lid, oid, oslot, tid, tslot = (link.get("id"), link.get("origin_id"),
                                           link.get("origin_slot"),
                                           link.get("target_id"),
                                           link.get("target_slot"))
        else:
            lid, oid, oslot, tid, tslot = link[:5]
        tgt = nodes.get(int(tid))
        if tgt is None:
            continue
        name = None
        for inp in (tgt.get("inputs") or []):
            if inp.get("link") == lid:
                name = inp.get("name")
                break
        if name is None:
            continue
        out.setdefault(str(tid), {"class_type": tgt["type"], "inputs": {}})
        out[str(tid)]["inputs"][name] = [str(oid), int(oslot)]
    for nid, node in nodes.items():
        ctype = node["type"]
        spec = schemas.get(ctype) or {}
        inp = spec.get("input") or {}
        order: list[str] = []
        if inp:
            for sect in ("required", "optional"):
                for k, entry in (inp.get(sect) or {}).items():
                    if isinstance(entry, list) and entry and (
                            isinstance(entry[0], list)
                            or (isinstance(entry[0], str) and entry[0] in WIDGET_TYPES)):
                        order.append(k)
        if not order:
            order = list(BUILTIN_WIDGET_ORDER.get(ctype, []))
        values = list(node.get("widgets_values") or [])
        vi = 0
        entry = out.setdefault(str(nid), {"class_type": ctype, "inputs": {}})
        for wname in order:
            if vi >= len(values):
                break
            entry["inputs"][wname] = values[vi]
            vi += 1
            if wname in CONTROL_AFTER:
                vi += 1                 # 跳过 control_after_generate 占位
    return out


__all__ = [
    "Graph", "build_t2i", "build_style_ref", "build_ipadapter", "build_upscale",
    "build_remove_bg", "build_inpaint_edit", "append_upscale", "append_remove_bg",
    "validate", "bump_graph_seed", "ui_to_api", "parse_loras",
    "WIDGET_TYPES", "CONTROL_AFTER", "BUILTIN_WIDGET_ORDER", "BUILTIN_DEFAULTS",
    "BUILTIN_OUTPUTS", "DEFAULT_NODE_SIZE", "SAVE_PREFIX_DEFAULT", "TARGET_2X",
    "NODE_TITLES",
]
