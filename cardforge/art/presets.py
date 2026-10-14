"""出图预设 —— 「我要做什么」到「该建哪张图」的映射表。

每个预设声明：用途、必需参数、可选参数、走哪个构造器、需要哪些模型/节点。
:func:`preset` 取一份**深拷贝**，调用方随便改不会污染全局表。
"""
from __future__ import annotations

from copy import deepcopy

__all__ = ["PRESETS", "preset", "keys", "describe_all", "by_capability"]


#: 预设表。每个条目：
#: ``zh`` 中文名 / ``use`` 用途 / ``builder`` 构造器名 / ``requires`` 必需参数 /
#: ``optional`` 可选参数 / ``needs`` 依赖的模型或节点 / ``degrade`` 缺依赖时的降级行为
PRESETS: dict[str, dict] = {
    # ── 1. 单张文生图 ──
    "t2i_single": {
        "zh": "单张文生图",
        "use": ("最常用：一张卡一张图。探测本机模型 → 选档案 → 建 Krea 2 / SDXL 链路 → "
                "提交 → 取图 → 存进资产库。"),
        "builder": "build_t2i",
        "requires": ["positive", "negative", "width", "height", "seed"],
        "optional": ["loras", "steps", "cfg", "sampler", "scheduler",
                     "upscale", "upscale_model", "remove_bg", "bg_model",
                     "save_prefix"],
        "needs": {"models": ["unet 或 checkpoint", "配套的 clip + vae（Krea 2 链路）"],
                  "nodes": ["ComfyUI 核心节点"]},
        "defaults": {"upscale": False, "remove_bg": False},
        "degrade": "缺放大/抠底节点时自动跳过并记 warning，主链不受影响。",
        "bytes_hint": "832×1216 / 8 步 ≈ 5–20 秒（Krea 2，RTX 4080 SUPER）。",
    },

    # ── 2. 分层出图（背景 + 主体两次生成）──
    "t2i_layers": {
        "zh": "分层出图（背景 + 主体）",
        "use": ("**背景与主体分两次生成再叠加**：先出无人物的环境，再出纯色底上的"
                "全身主体并抠底成带 alpha 的独立层。出框时只让**主体**越出卡图窗，"
                "背景严格留在窗内 —— 这是「主体破框」观感的唯一可靠做法。"),
        "builder": "generate_layers",
        "requires": ["subject（主体描述）", "background（背景描述，可空）"],
        "optional": ["cutout_bg（纯色底：grey/white/black/green）", "style",
                     "extra_positive", "extra_negative", "seed", "steps", "cfg"],
        "needs": {"models": ["同 t2i_single", "抠底权重（models/background_removal/）"],
                  "nodes": ["ComfyUI 核心节点 ×2 次采样", "抠底链路"]},
        "defaults": {"cutout_bg": "grey", "count": 1, "passes": 2},
        "degrade": ("抠不出可用 alpha 时自动翻转 mask 极性重跑一次主体 pass；"
                    "仍失败则照原样使用并在 notes 里说明（压平件仍然可用）。"),
        "bytes_hint": ("两次采样 = 两倍耗时（本机 Krea2 1024×1024 单张约 18 秒）。"
                       "产物：v{n}.png（压平）+ v{n}_bg.png + v{n}_subject.png。"),
    },

    # ── 3. 系列批量 ──
    "t2i_series": {
        "zh": "系列批量（共享风格前缀）",
        "use": ("一个系列的多张卡：**冻结风格前缀**（series_context['series_style']）"
                "只让主体变化，**每张必须换 seed**。"),
        "builder": "build_t2i",
        "requires": ["positive（= 冻结前缀 + 该卡主体）", "negative", "width", "height",
                     "seed（每张不同）"],
        "optional": ["loras", "steps", "cfg", "sampler", "scheduler"],
        "needs": {"models": ["同 t2i_single"], "nodes": ["ComfyUI 核心节点"]},
        "defaults": {"count": "按卡片数量", "seed": "base_seed + index"},
        "degrade": "IPAdapter 不可用时（本机就是），风格一致性只靠提示词前缀 —— 约占 60% 效果。",
        "bytes_hint": ("**不要**用同一个 seed 跑整批：构图会高度雷同。"
                       "用 base_seed + index 让噪声分布同族但不同。"),
    },

    # ── 3. 画风参考 ──
    "style_ref": {
        "zh": "画风参考（垫图定风格）",
        "use": ("给 1–3 张参考图，把**画风**注入新图，内容仍由提示词决定。"
                "Krea 2 专属链路：krea2_style_reference LoRA + "
                "TextEncodeQwenImageEditPlus + FluxKontextMultiReferenceLatentMethod。"),
        "builder": "build_style_ref",
        "requires": ["style_refs（已 upload 的服务器引用）", "positive", "negative",
                     "width", "height", "seed"],
        "optional": ["strength（0.5–0.8 只统一画风；1.0+ 会连构图一起带过来）",
                     "style_lora"],
        "needs": {"models": ["krea2 底模 + qwen3vl 文本编码器 + qwen_image_vae",
                             "krea2_style_reference.safetensors"],
                  "nodes": ["TextEncodeQwenImageEditPlus",
                            "FluxKontextMultiReferenceLatentMethod"]},
        "defaults": {"strength": 1.0, "max_refs": 3},
        "degrade": "缺上述节点 → 抛 ComfyError(node_missing)，请改用 t2i_series。",
        "bytes_hint": "先把参考图 ComfyClient.upload()，再把返回的 ref 传进 style_refs。",
    },

    # ── 4. IPAdapter 一致性 ──
    "ipadapter_consistency": {
        "zh": "IPAdapter 风格锚点（本机不可用）",
        "use": ("用一张「风格母版」统一整个系列的画风："
                "weight 0.5–0.8 + weight_type=\"style transfer\" 只统一画风不改内容。"),
        "builder": "build_ipadapter",
        "requires": ["ref_images（风格母版）", "clip_vision（CLIP Vision 模型名）",
                     "positive", "negative", "width", "height", "seed"],
        "optional": ["weight", "weight_type", "preset", "loras"],
        "needs": {"models": ["SD1.5 / SDXL checkpoint",
                             "models/clip_vision/ 下的 CLIP-ViT-H-14（**本机为空**）",
                             "models/ipadapter/ 下的 ip-adapter 权重"],
                  "nodes": ["IPAdapterUnifiedLoader", "IPAdapterAdvanced",
                            "CLIPVisionLoader"]},
        "defaults": {"weight": 0.65, "weight_type": "style transfer",
                     "preset": "STANDARD (medium strength)"},
        "degrade": ("本机 `CLIPVisionLoader.clip_name` 候选为空 → **必然失败**。"
                    "代码会先探测再决定：探测不到就抛 ComfyError(model_missing)，"
                    "调用方回落到 t2i_series。**不要硬上。**"),
        "bytes_hint": ("`preset` 要与底模架构匹配：LIGHT / FULL FACE **仅 SD1.5**，"
                       "用在 SDXL 上直接报错。IPAdapter 也不适用于 Krea 2 / Qwen-Image（DiT）。"),
    },

    # ── 5. 角色三视图 ──
    "character_sheet": {
        "zh": "角色三视图（设定稿）",
        "use": ("给艾莉娅这类角色出**参考设定稿**：正面/侧面/背面同框 + 中性背景，"
                "作为后续卡图的角色锚点。用横版画布，一次出一张图。"),
        "builder": "build_t2i",
        "requires": ["positive（描述角色 + 三视图要求）", "negative", "seed"],
        "optional": ["loras", "steps", "cfg"],
        "needs": {"models": ["同 t2i_single"], "nodes": ["ComfyUI 核心节点"]},
        "defaults": {
            "width": 1536, "height": 1024,
            "positive": ("character design reference sheet, three views of the same "
                         "character side by side: front view, side view, back view, "
                         "full body, identical outfit and proportions across all views, "
                         "neutral plain light-grey background, even soft studio lighting, "
                         "no text, no labels, no annotations"),
            "negative": ("multiple characters, different outfits, inconsistent design, "
                         "text, labels, annotation, arrows, watermark, signature, "
                         "chibi, deformed"),
            "frame": "effect",
        },
        "degrade": "Krea 2 对「严格三视图」的把控有限，可能要 2–3 次换 seed 才拿到干净的三视图。",
        "bytes_hint": ("**注意**：卡图是竖版 832×1216，三视图是横版 —— 三视图只当角色锚点，"
                       "不要直接当卡图用。做卡图时把三视图当角色描述的依据，重新出竖版。"),
    },

    # ── 6. 放大 ──
    "upscale": {
        "zh": "放大 + 精确降采样",
        "use": ("把已出的图放大到交付尺寸。"
                "`ImageUpscaleWithModel` 的倍率由模型固定（通常 4x），"
                "**必须后接 ImageScale** 才能落到目标尺寸。"),
        "builder": "build_upscale",
        "requires": ["graph_or_image（上游图或图片名）", "target (w,h)"],
        "optional": ["upscale_model", "method"],
        "needs": {"models": ["models/upscale_models/ 下的 ESRGAN 系权重"
                             "（本机有 4x_fatal_Anime_500000_G.pth 等 3 个）"],
                  "nodes": ["UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScale"]},
        "defaults": {"target": [842, 1228], "method": "lanczos",
                     "upscale_model": "4x_fatal_Anime_500000_G.pth"},
        "degrade": "没有放大模型时退化为纯 lanczos 重采样（不增加细节），并记 warning。",
        "bytes_hint": ("842×1228 = 421×614 的精确 2×，是推荐交付尺寸。"
                       "crop 必须是 \"disabled\"，否则会裁掉画面。"),
    },

    # ── 7. 抠底 ──
    "remove_bg": {
        "zh": "抠底（输出透明 PNG）",
        "use": ("把主体从背景里抠出来，输出带 alpha 的 PNG。"
                "用于「角色 + 程序化卡框/背景」的合成玩法。"),
        "builder": "build_remove_bg",
        "requires": ["image（图片名或上游图）"],
        "optional": ["model（BiRefNet 权重名）", "node（强制指定抠底节点）"],
        "needs": {"models": ["BiRefNet 权重（随插件/核心下载）"],
                  "nodes": ["BiRefNetRMBG 或 LoadBackgroundRemovalModel+RemoveBackground"
                            " 或 BriaRemoveImageBackground"]},
        "defaults": {"model": "BiRefNet_toonout", "background": "Alpha"},
        "degrade": "一个抠底节点都没有时**不报错**，只记 warning，输出仍是不透明图。",
        "bytes_hint": ("卡图/插画首选 BiRefNet_toonout（为动漫调优）；"
                       "输入超过约 1500px 必须换 BiRefNet-HR，否则会内部降采样丢边缘。"
                       "核心 RemoveBackground 只输出 MASK，要自己 JoinImageWithAlpha 拼回。"),
    },

    # ── 8. 局部重绘 / 指令编辑 ──
    "inpaint_edit": {
        "zh": "局部重绘 / 指令编辑",
        "use": ("改一张已出的图的局部：补画手指、去掉伪签名、换背景。"
                "Qwen-Image 2.1 走 VAEEncode + SetLatentNoiseMask + Edit 编码器；"
                "SDXL 走 VAEEncodeForInpaint。"),
        "builder": "build_inpaint_edit",
        "requires": ["image（原图）", "mask（重绘区域，白=重绘）", "instruction（中文/英文指令）"],
        "optional": ["negative", "denoise（0.6–0.8）", "seed", "steps", "cfg"],
        "needs": {"models": ["Qwen-Image 2.1 i2i 编码器（qwen3.5_9b_..._pe_i2i）"
                             "或 SDXL inpaint checkpoint"],
                  "nodes": ["LoadImage", "LoadImageMask", "VAEEncode",
                            "SetLatentNoiseMask", "ImageCompositeMasked"]},
        "defaults": {"denoise": 0.6, "grow_mask_by": 8},
        "degrade": "缺 TextEncodeQwenImageEditPlus → 退化成纯提示词重绘（不参考原图）。",
        "bytes_hint": ("两个坑：**mask 尺寸必须与图像一致**（否则重绘区域错位）；"
                       "**denoise 不能停在 1.0**（等于整图重画）。"
                       "最后用 ImageCompositeMasked 把重绘区贴回原图，"
                       "保证未遮罩像素完全一致。"),
    },
}


def preset(key: str) -> dict:
    """取一个预设的**深拷贝**（改它不会污染 :data:`PRESETS`）。

    :raises KeyError: 预设不存在（附可用键列表）。
    """
    k = str(key or "").strip()
    if k not in PRESETS:
        raise KeyError(f"未知预设 {k!r}；可用：{', '.join(PRESETS)}")
    return deepcopy(PRESETS[k])


def keys() -> list[str]:
    """全部预设键（顺序即 :data:`PRESETS` 的声明顺序）。"""
    return list(PRESETS)


def describe_all() -> list[dict]:
    """给 UI 下拉用的预设清单。"""
    out = []
    for k, v in PRESETS.items():
        out.append({"key": k, "zh": v.get("zh", k), "use": v.get("use", ""),
                    "requires": list(v.get("requires", [])),
                    "optional": list(v.get("optional", [])),
                    "needs": deepcopy(v.get("needs", {})),
                    "degrade": v.get("degrade", ""),
                    "bytes_hint": v.get("bytes_hint", "")})
    return out


def by_capability(caps: dict) -> list[dict]:
    """按 ``capabilities()`` 的结果标注每个预设「现在能不能用」。

    :param caps: :func:`cardforge.art.run.capabilities` 的返回值。
    :return: 每项多出 ``available`` / ``reason`` 两个字段的预设清单。

    判定只看**真正的增强依赖**（放大 / 抠底 / IPAdapter / 画风参考），
    ``needs.nodes`` 里那些「ComfyUI 核心节点」之类的描述不算依赖 —— 它们
    在任何能跑的 ComfyUI 上都有，报「缺失」只会制造噪声。
    """
    nodes = set((caps.get("nodes") or {}).get("present") or {})
    present_map = (caps.get("nodes") or {}).get("present") or {}
    models = caps.get("models") or {}
    #: 每个预设真正会「因为缺东西而跑不通/降级」的节点（全缺才算不可用）。
    #: 抠底只看 BiRefNetRMBG —— 核心的 LoadBackgroundRemovalModel / RemoveBackground
    #: 是 ComfyUI 自带节点，永远存在，把它们算进来只会误报「缺依赖」。
    bg_nodes = ("BiRefNetRMBG",)
    style_nodes = ("TextEncodeQwenImageEditPlus",
                   "FluxKontextMultiReferenceLatentMethod")
    up_nodes = ("UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScale")
    ip_nodes = ("IPAdapterUnifiedLoader", "IPAdapterAdvanced", "CLIPVisionLoader")
    checks: dict[str, tuple[tuple[str, ...], str]] = {
        "remove_bg": (bg_nodes,
                      "没有 ComfyUI-RMBG 插件（BiRefNetRMBG）→ 会退回核心 "
                      "LoadBackgroundRemovalModel / RemoveBackground 链路"),
        "style_ref": (style_nodes, "缺少画风参考所需节点"),
        "upscale": (up_nodes, "缺少放大链路节点"),
        "ipadapter_consistency": (ip_nodes, "缺少 IPAdapter 节点"),
    }
    #: 抠底额外要看「本机有没有权重」—— 光有节点但没权重，跑起来会去联网下载
    bg_weights = list(models.get("background_removal") or [])

    def _missing(pool: tuple[str, ...]) -> list[str]:
        """只把**明确探测过且确实没有**的节点算缺失。

        ``present_map`` 是 ``object_info_summary()`` 的固定关注清单，
        里面没有的键（``.get() is None``）表示**没探测过**，
        不能当成缺失 —— 那只会制造假警告（本项目踩过这个坑）。
        """
        return [n for n in pool if present_map.get(n) is False]
    out = []
    for item in describe_all():
        ok, reason = True, "可用"
        key = item["key"]
        if key == "ipadapter_consistency" and not models.get("clip_vision"):
            ok, reason = False, "本机没有 CLIP Vision 模型（models/clip_vision/ 为空）"
        elif key == "upscale" and not models.get("upscale"):
            ok, reason = False, "没有放大模型（models/upscale_models/ 为空）"
        elif key == "remove_bg" and not bg_weights:
            ok, reason = False, ("models/background_removal/ 为空 → "
                                 "抠底节点在但没有权重，跑起来会去联网下载")
        elif key == "t2i_layers" and not bg_weights:
            ok, reason = False, ("分层出图的主体 pass 要抠底，"
                                 "models/background_removal/ 为空 → 拿不到 alpha 层")
        elif key in checks:
            pool, why = checks[key]
            missing = _missing(pool)
            if len(missing) == len(pool):
                ok, reason = False, why
            elif missing:
                reason = "部分依赖缺失，会自动降级：" + "、".join(missing)
        # 那些「一定要有否则完全跑不通」的核心节点（只认明确探测过的）
        core_missing = [n for n in ("KSampler", "VAEDecode", "SaveImage")
                        if present_map.get(n) is False]
        if core_missing:
            ok, reason = False, "缺少 ComfyUI 核心节点：" + "、".join(core_missing)
        out.append({**item, "available": ok, "reason": reason})
    return out


__all__ = ["PRESETS", "preset", "keys", "describe_all", "by_capability"]
