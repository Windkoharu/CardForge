"""模型档案表 —— 「用户装了什么就自动用最合适的那个」。

设计要点
--------
1. **本机事实优先**：本机（RTX 4080 SUPER + ComfyUI 0.38.2）**没有 SDXL 动漫底模**，
   唯一可用的出图链路是 **Krea 2 Turbo**（``UNETLoader`` + ``CLIPLoader(type="krea2")``
   + ``qwen_image_vae``），所以 ``krea2`` 排在优先级最高位。
2. **按 ``/object_info`` 的真实候选匹配**，不猜、不硬编码路径：
   ``detect(available_models)`` 收到的 ``available_models`` 来自
   :meth:`cardforge.art.client.ComfyClient.models`。
3. 每个档案都带 ``notes``，写明**授权要点**（能否商用 / 能否在变现平台推理）。
4. **提示词语言由编码器决定，不由偏好决定**（见 ``bilingual_text_encoder``）：
   Krea 2 / Qwen-Image 的文本编码器就是 Qwen 系多语言 LLM —— 用户在界面写的中文
   **原话直送**，一个字都不丢；SDXL / SD1.5 系的 CLIP 只有英文词表，中文必须过
   词典翻译，翻不出来的词**列清单告诉用户**（绝不静默丢弃）。

授权速查（详细条文见各档案 ``notes``）
--------------------------------------
=================  ==========================================================
档案               商用结论
=================  ==========================================================
``krea2``          Krea 2 Community License，**自托管非商业友好**；商用需看 Krea 条款
``qwen_image``     Apache-2.0，**可商用**
``illustrious``    Fair AI / OpenRAIL-M 系，**禁止闭源专有商业化**
``noobai``         license: other，**以模型页为准**（继承 Illustrious 限制）
``pony``           Fair AI Public License 1.0-SD，**禁止在允许变现的平台推理**
``animagine``      CreativeML OpenRAIL++-M，**允许商用**（授权最干净）
``sdxl``           多数为 CreativeML OpenRAIL++-M；具体看模型页
``sd15``           CreativeML OpenRAIL-M，**允许商用**，禁有害用途
=================  ==========================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..core.enums import FRAMES

#: 画布必须是 16 的倍数（latent 是 1/8 压缩，16 更稳）
SIZE_ALIGN = 16

#: 标准卡图窗比例 —— **实测 1051×1051 ≈ 1.0004，是正方形**。
#: 旧值 0.68567 是「整卡」的比例（813/1185），拿它当窗比例会让模型画竖构图、
#: 再被 cover 裁掉上下约 31%（人物脚/头被切）。窗比例一律以 geometry 实测为准。
ART_WINDOW_RATIO = 1.0004
#: 灵摆合并窗实测比例（1205×1548）
ART_WINDOW_RATIO_PENDULUM = 0.7788


@dataclass(frozen=True)
class ModelProfile:
    """一个底模档案：怎么匹配、怎么采样、提示词该写成什么形状。"""

    key: str
    zh: str
    #: checkpoint / unet 文件名关键词（**小写**匹配，任一命中即算）
    match: tuple[str, ...]
    steps: int
    cfg: float
    sampler: str
    scheduler: str
    width: int
    height: int
    clip_skip: int | None
    prompt_prefix: str
    negative: str
    #: "danbooru" | "natural" | "pony" | "animagine"
    prompt_style: str
    #: "krea2" | "qwen" | "sdxl" | "sd15" | "flux"
    chain: str
    notes: str = ""
    #: 该档案要不要把主体写成自然语言长句（krea2 / qwen / flux 为 True）
    natural_language: bool = False
    #: **文本编码器认不认识中文**。True = 编码器是 Qwen-VL 这类多语言 LLM
    #: （krea2 用 qwen3vl、qwen_image 用 Qwen 系），**用户写的中文原话可以直接送**，
    #: 不需要也不应该再过一遍中英词典（过词典一定会丢词）；
    #: False = CLIP ViT-L/BigG 这类英文词表编码器（SDXL / SD1.5 系），
    #: 中文进不去，只能走词典翻译，且**没翻译出来的词必须如实上报**。
    bilingual_text_encoder: bool = False
    #: 是否为蒸馏少步模型（决定「负向是否有效」的判断）
    distilled: bool = False
    #: 该档案的默认 LoRA 挂载建议（文件名关键词 → 强度），仅用于推荐
    suggest_loras: tuple[tuple[str, float], ...] = ()
    #: 采样时是否需要在文件名/元数据里标记「cfg<=1 时负向无效」
    negative_effective: bool = True
    #: 额外固定参数（进 API 图的常量输入）
    extras: dict = field(default_factory=dict)

    # ── 便利属性 ──────────────────────────────────────────────────
    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def is_sdxl_family(self) -> bool:
        return self.chain in ("sdxl", "sd15") or self.key in (
            "illustrious", "noobai", "pony", "animagine", "sdxl", "sd15")

    @property
    def language_line(self) -> str:
        """提示词语言口径的一句话说明（给 UI 与台账看）。"""
        if self.bilingual_text_encoder:
            return "中文原话直送（文本编码器 = Qwen 系多语言 LLM，不翻译、不丢词）"
        return "必须先翻成英文标签（文本编码器 = 英文词表 CLIP，中文进不去）"

    @property
    def license_line(self) -> str:
        """从 notes 里抽出「授权」那一行的短摘要。"""
        for line in self.notes.splitlines():
            s = line.strip()
            if s.startswith(("授权", "许可", "License", "⚠️ 授权")):
                return s.lstrip("⚠️ ").strip()
        return "未标注"

    def with_params(self, **kw) -> "ModelProfile":
        """派生一个新档案（例如只改 steps / size），不可变语义。"""
        return replace(self, **kw)


# ══════════════════════════════════════════════════════════════════════
#  档案表（顺序 = 优先级，detect 从头到尾扫）
# ══════════════════════════════════════════════════════════════════════

_KREA2_NEG = (
    # cfg=1.0 下负向基本不生效，这里只是为了「万一用户调高 cfg」时可用，
    # 以及给 UI 工作流一个可读的占位文本。
    "text, watermark, signature, username, logo, artist name, "
    "border, frame, letterboxed, multiple views, character sheet, "
    "lowres, worst quality, low quality, blurry, jpeg artifacts"
)

_SDXL_ANIME_NEG = (
    "lowres, worst quality, low quality, bad anatomy, bad hands, bad proportions, "
    "extra digits, fewer digits, missing fingers, extra limbs, fused fingers, "
    "cropped, out of frame, jpeg artifacts, blurry, "
    "text, watermark, signature, username, logo, artist name, copyright name, "
    "web address, speech bubble, border, frame, letterboxed, "
    "multiple views, character sheet, 2girls, 2boys, multiple characters, "
    "sketch, monochrome, greyscale, nsfw"
)

_PONY_NEG = (
    "score_1, score_2, score_3, score_4, score_5, "
    "source_pony, source_furry, source_cartoon, "
    "worst quality, low quality, lowres, "
    "text, watermark, signature, username, logo, border, frame, "
    "multiple views, character sheet"
)

_ANIMAGINE_NEG = (
    # Animagine XL 4.0 官方负向清单（照抄），追加卡图专项
    "lowres, bad anatomy, bad hands, text, error, missing finger, extra digits, "
    "fewer digits, cropped, worst quality, low quality, low score, bad score, "
    "average score, signature, watermark, username, blurry, "
    "border, frame, letterboxed, multiple views, character sheet, logo"
)

_SD15_NEG = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
    "fewer digits, cropped, worst quality, low quality, normal quality, "
    "jpeg artifacts, signature, watermark, username, blurry, artist name, "
    "border, frame, multiple views, character sheet"
)


PROFILES: list[ModelProfile] = [
    # ── 0. Krea 2 Turbo（本机首选；bf16 底模 + Qwen3-VL 文本编码器）──
    ModelProfile(
        key="krea2",
        zh="Krea 2 Turbo（本机首选）",
        match=("krea2", "krea_2", "krea-2"),
        steps=8, cfg=1.0, sampler="euler", scheduler="simple",
        width=832, height=1216,
        clip_skip=None,
        prompt_prefix=(
            "A highly atmospheric anime illustration in a cinematic key-visual style, "
            "rendered with clean lineart and soft cel shading, painted for a trading card artwork."
        ),
        negative=_KREA2_NEG,
        prompt_style="natural",
        chain="krea2",
        natural_language=True,
        bilingual_text_encoder=True,      # qwen3vl_4b → 中文原话可直接送
        distilled=True,
        #: cfg=1.0 → 那一遍负向前向根本不跑
        negative_effective=False,
        suggest_loras=(
            ("krea2_flat_cel_anime", 0.8),
            ("krea2_luminous_anime_film", 0.7),
            ("krea2_softwatercolor", 0.75),
        ),
        extras={"max_shift": 1.15, "base_shift": 0.5, "weight_dtype": "default",
                "clip_type": "krea2",
                "clip": "qwen3vl_4b_fp8_scaled.safetensors",
                "vae": "qwen_image_vae.safetensors"},
        notes=(
            "链路：UNETLoader(krea2_turbo_bf16 / weight_dtype=default) → "
            "LoraLoaderModelOnly×0-2 → ModelSamplingFlux(max_shift=1.15) → CLIPTextEncode "
            "+ ConditioningZeroOut → CFGGuider(cfg=1.0) → SamplerCustomAdvanced"
            "(RandomNoise + KSamplerSelect(euler) + BasicScheduler(simple, steps=8)) → "
            "VAEDecode → SaveImage。\n"
            "CLIP 必须用 CLIPLoader(clip_name=qwen3vl_4b_fp8_scaled.safetensors, type=\"krea2\")，"
            "VAE 用 VAELoader(qwen_image_vae.safetensors) —— type 写错必失败。\n"
            "参数口径：**8 步 / cfg 1.0 / euler / simple / shift 1.15**。"
            "这是蒸馏少步模型，别沿用 SD 的 30 步（会更糊更慢）；cfg 不能设 0（ComfyUI 会直接失败）。\n"
            "cfg=1.0 时**负向提示词基本不生效**（那一遍前向不跑）：要排除的东西必须写进正向描述，"
            "例如把「背景是干净的纯色空墙，画面里没有任何文字」写进正向。\n"
            "画布取 16 的倍数；2:3 → 1024×1536，卡图窗比例 0.68567 → **832×1216 最贴合（误差 0.21%）**。\n"
            "授权：Krea 2 Community License（含 Acceptable Use Policy）。自托管、个人/研究用途清晰；"
            "**商用与「在允许变现的平台上推理」需自行核对 Krea 的最新条款**，"
            "本工程不代为解释。禁止 CSAM / 未成年性化 / NCII / 诽谤类内容。"
        ),
    ),

    # ── 1. Qwen-Image（本机有 qwen_image_2.1_int8_convrot，可做编辑/图生图）──
    ModelProfile(
        key="qwen_image",
        zh="Qwen-Image 2.1（编辑 / 图生图链路）",
        match=("qwen_image", "qwen-image", "qwenimage"),
        steps=8, cfg=1.0, sampler="euler", scheduler="simple",
        width=832, height=1216,
        clip_skip=None,
        prompt_prefix=(
            "A cinematic anime illustration of a duel-monster trading card artwork, "
            "clean lineart, rich lighting, high detail."
        ),
        negative=_KREA2_NEG,
        prompt_style="natural",
        chain="qwen",
        natural_language=True,
        bilingual_text_encoder=True,      # Qwen 系文本编码器，中文原话可直接送
        distilled=True,
        negative_effective=False,
        extras={"weight_dtype": "default", "clip_type": "qwen_image",
                "text_encoder_t2i": "qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors",
                "text_encoder_i2i": "qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors",
                "vae": "qwen_image_2.1_vae_bf16.safetensors"},
        notes=(
            "链路：UNETLoader(qwen_image_2.1_int8_convrot) + "
            "CLIPLoader(type=\"qwen_image\")+VAELoader(qwen_image_2.1_vae_bf16) → "
            "ModelSamplingAuraFlow/Flux → 采样 → VAEDecode。\n"
            "本机是 **int8 量化**权重，显存友好但速度略慢于 bf16；8 步 / cfg 1.0 同 Krea 2 口径。\n"
            "编辑/图生图请配 i2i 文本编码器 "
            "(qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors)，"
            "t2i 用 pe_t2i 那个 —— **两个编码器不可混用**。\n"
            "授权：**Apache-2.0，可商用**（含自托管推理与衍生作品）；模型卡另附可接受使用政策。"
            "本机权重为社区 int8 量化版，量化脚本本身不改变许可。"
        ),
    ),

    # ── 2. Illustrious-XL 系（SDXL 动漫首选，但本机未安装）──
    ModelProfile(
        key="illustrious",
        zh="Illustrious-XL / WAI（SDXL 动漫）",
        match=("illustrious", "wai", "hassaku", "blue_pencil", "bluepencil",
               "kohaku", "nova_anime", "c2fn", "prefectillustrious"),
        steps=28, cfg=5.0, sampler="euler_ancestral", scheduler="normal",
        width=832, height=1216,
        clip_skip=None,
        prompt_prefix="masterpiece, best quality, amazing quality, newest",
        negative=_SDXL_ANIME_NEG,
        prompt_style="danbooru",
        chain="sdxl",
        suggest_loras=(("yugioh", 0.7),),
        notes=(
            "链路：CheckpointLoaderSimple → (可选 LoraLoader) → CLIPTextEncode×2 → "
            "EmptyLatentImage(832×1216) → KSampler(euler_ancestral, 28 步, cfg 5, normal) → "
            "VAEDecode → SaveImage。\n"
            "提示词：**Danbooru2023 标签为主 + 自然语言混合**；加权语法 `(tag:1.2)` 可靠。"
            "**不要**把 Pony 的 score_9 前缀搬过来（在 Illustrious 上是纯噪声 token）。\n"
            "CLIP skip 用默认（-1）—— SDXL 系本来就取倒数第二层。\n"
            "授权：**Illustrious-XL 为 CreativeML OpenRAIL-M / Fair AI Public License 系，"
            "明确禁止闭源专有商业化（prohibits closed-source proprietary monetization）**。"
            "WAI 等 finetune **继承底层限制**。个人/开源项目用没问题；"
            "要做闭源商业产品请改走 Animagine（OpenRAIL++-M）。"
        ),
    ),

    # ── 3. NoobAI-XL ──
    ModelProfile(
        key="noobai",
        zh="NoobAI-XL（Illustrious 进一步训练）",
        match=("noobai", "noob-ai", "noob_ai"),
        steps=28, cfg=4.5, sampler="euler_ancestral", scheduler="karras",
        width=832, height=1216,
        clip_skip=None,
        prompt_prefix="masterpiece, best quality, amazing quality",
        negative=_SDXL_ANIME_NEG,
        prompt_style="danbooru",
        chain="sdxl",
        notes=(
            "链路同 SDXL。**V-prediction 版本（*vpred*）必须配 ModelSamplingDiscrete"
            "(sampling=\"v_prediction\")，否则出图全糊** —— 本模块在建图时会读文件名里有没有 "
            "\"vpred\"/\"v-pred\" 自动挂上。\n"
            "Danbooru 标签依从性极强；社区普遍 CFG 4-5 / euler_ancestral / 28 步 / karras。\n"
            "授权：模型页标注为 **license: other，需以模型页为准**；"
            "它是 Illustrious 的派生训练，**实质继承 Illustrious 的 OpenRAIL-M / Fair AI 限制**"
            "（禁闭源专有商业化）。本工程不代为解释，商用前请自行核对。"
        ),
    ),

    # ── 4. Animagine XL 4.0（授权最干净）──
    ModelProfile(
        key="animagine",
        zh="Animagine XL 4.0（授权最干净）",
        match=("animagine", "anim4gine"),
        steps=25, cfg=6.0, sampler="euler_ancestral", scheduler="normal",
        width=832, height=1216,
        clip_skip=None,
        prompt_prefix="masterpiece, high score, great score, absurdres",
        negative=_ANIMAGINE_NEG,
        prompt_style="animagine",
        chain="sdxl",
        notes=(
            "链路同 SDXL。提示词用 **tag ordering 结构**："
            "`1girl/1boy/1other, 角色名, 出自哪部作品, 其余任意顺序`，画质词放开头或结尾。\n"
            "官方参数：**Euler Ancestral / 25 步 / CFG 6**；分辨率桶 832×1216（官方 2:3 竖版桶）。\n"
            "授权：**CreativeML Open RAIL++-M，允许商用**，仅禁止有害/不道德用途 —— "
            "**如果这个 DIY 项目有任何商业化可能，优先用它**（Cagliostro Research Lab 出品）。"
        ),
    ),

    # ── 5. Pony Diffusion V6 XL（能力强，授权是最大的雷）──
    ModelProfile(
        key="pony",
        zh="Pony Diffusion V6 XL（授权受限）",
        match=("pony", "autismmix", "homosimile", "prefect_pony", "ponyrealism",
               "pony_realism"),
        steps=25, cfg=7.0, sampler="euler_ancestral", scheduler="normal",
        width=832, height=1216,
        clip_skip=-2,
        prompt_prefix=(
            "score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up, "
            "source_anime, rating_safe"
        ),
        negative=_PONY_NEG,
        prompt_style="pony",
        chain="sdxl",
        notes=(
            "链路：CheckpointLoaderSimple → **CLIPSetLastLayer(stop_at_clip_layer=-2)** → "
            "CLIPTextEncode×2 → KSampler(euler_ancestral, 25 步, cfg 7) → VAEDecode。\n"
            "**必须 CLIP skip 2**（官方原文：不设会 getting low quality blobs）；"
            "正向必备 `score_9, score_8_up, ...` 长版（短版 score_9 效果弱得多）；"
            "**必须带 `source_anime`**，否则会偏向兽人/小马域。\n"
            "已知缺陷：**会生成伪签名，且负向词难以去掉**（官方承认是训练问题）。"
            "卡图对「无文字」是硬要求的话，不要用 Pony V6 —— 换 Animagine 或 Illustrious。\n"
            "⚠️ **授权：修改版 Fair AI Public License 1.0-SD**（freedevproject.org/faipl-1.0-sd）。"
            "额外条款：**禁止在任何允许变现的网站 / 应用上推理（含付费推理与加速档），"
            "该限制同样适用于所有衍生模型与融合模型**；商用需邮件申请授权，"
            "已获商用推理许可的仅 CivitAI 与 Hugging Face。"
            "**只适合纯个人 / 研究用途。**"
        ),
    ),

    # ── 6. 通用 SDXL ──
    ModelProfile(
        key="sdxl",
        zh="通用 SDXL / 其它 SDXL finetune",
        match=("sdxl", "_xl", "xl_", "juggernaut", "dreamshaper", "realvis",
               "animeartdiffusion", "aam", "counterfeitxl"),
        steps=25, cfg=7.0, sampler="dpmpp_2m", scheduler="karras",
        width=832, height=1216,
        clip_skip=None,
        prompt_prefix="masterpiece, best quality, highly detailed",
        negative=_SDXL_ANIME_NEG,
        prompt_style="danbooru",
        chain="sdxl",
        notes=(
            "兜底档案：任何没被上面关键词命中的 SDXL 系 checkpoint 都落到这里。\n"
            "链路同 SDXL 标准链（CheckpointLoaderSimple + KSampler）。\n"
            "授权：SDXL 生态**多数权重是 CreativeML OpenRAIL++-M（允许商用，禁有害用途）**，"
            "但**每个 finetune 都可能自加条款**（例如基于 Pony 融的模型会继承 Pony 的禁变现条款）"
            "—— 商用前逐个核对模型页的 license 字段，不要只看底模。"
        ),
    ),

    # ── 7. SD1.5（低显存兜底）──
    ModelProfile(
        key="sd15",
        zh="SD1.5 动漫系（低显存兜底）",
        match=("anything", "counterfeit", "meina", "cetus", "sd15", "sd_1.5",
               "v1-5", "v1_5", "aom3", "abyssorange", "orange_mix"),
        steps=22, cfg=7.0, sampler="dpmpp_2m", scheduler="karras",
        width=512, height=768,
        clip_skip=-2,
        prompt_prefix="masterpiece, best quality, very aesthetic",
        negative=_SD15_NEG,
        prompt_style="danbooru",
        chain="sd15",
        notes=(
            "链路：CheckpointLoaderSimple → **CLIPSetLastLayer(stop_at_clip_layer=-2)** → "
            "CLIPTextEncode×2 → EmptyLatentImage(512×768) → "
            "KSampler(dpmpp_2m + karras, 22 步, cfg 7) → VAEDecode。\n"
            "**CLIP skip -2 是硬要求**；分辨率停在 512×768，768×768 起开始出现双头。\n"
            "对 Danbooru 标签的理解远弱于 SDXL 系，更依赖自然语言，角色知识也差（多数角色要 LoRA）。\n"
            "授权：**CreativeML OpenRAIL-M，允许商用**，仅禁止有害/不道德用途。"
            "注意具体 finetune（Anything / Counterfeit / MeinaMix 等）可能附自己的条款，"
            "商用前看一眼模型页。"
        ),
    ),
]

#: 关键词 → 档案键（供 ``by_key`` 与 UI 提示使用）
BY_KEY: dict[str, ModelProfile] = {p.key: p for p in PROFILES}

#: 兜底档案：所有关键词都没命中时用它（= 通用 SDXL）
FALLBACK_KEY = "sdxl"

#: **非图像模型**的排除关键词。本机装了 YuE2（音乐）、MiniMax-H3（视频）、
#: ACE-Step（音乐）等模型，它们的文件名里也带 ``xl`` / ``sfx`` 之类的子串，
#: 不做排除会让 ``detect`` 误判出一个根本出不了图的档案。
#: 命中任一关键词的**权重文件**会被直接跳过。
NON_IMAGE_KEYWORDS: tuple[str, ...] = (
    "yue2", "yue_2", "minimax", "h3_", "_h3", "acestep", "ace_step", "ace15",
    "_ace", "audio", "music", "vocal", "tts", "speech", "wav2vec", "whisper",
    "fl2v", "ref2v", "i2v", "t2v", "video", "sd2-1", "sdxl-refiner",
    "text_encoder", "textencoder", "clip_", "vae", "control_", "upscale",
    "background_removal", "sam", "onnx", "gguf_only", "insightface",
)

#: 图像模型的**正向**关键词：命中任一才认为「这是个能出图的底模」。
#: 只用于 ``detect`` 的兜底判断（避免把嵌入模型/检测模型当成底模）。
IMAGE_KEYWORDS: tuple[str, ...] = (
    "krea", "qwen_image", "qwen-image", "illustrious", "noobai", "noob-ai",
    "animagine", "anim4gine", "pony", "sdxl", "sd_xl", "sd15", "v1-5", "wan",
    "flux", "schnell", "dev", "turbo", "lightning", "juggernaut", "dreamshaper",
    "anything", "counterfeit", "meina", "cetus", "hassaku", "kohaku", "nova",
    "chroma", "lumina", "pixart", "hidream", "omnigen", "z-image", "zimage",
    "kolors", "playground", "realvis", "aam", "blue_pencil", "bluepencil",
)


def is_non_image_model(name: str) -> bool:
    """这个权重文件名像不像**非图像**模型（音乐 / 视频 / 音频 / 文本编码器）。"""
    low = str(name or "").lower().replace("\\", "/")
    base = low.rsplit("/", 1)[-1]
    return any(kw in base for kw in NON_IMAGE_KEYWORDS)


def _candidates(available_models: dict) -> list[tuple[str, str]]:
    """把 ``models()`` 的结果摊平成 ``[(来源, 文件名)]``，去重且保持稳定顺序。

    * 只取 ``unets`` / ``checkpoints`` / ``diffusion_models``；
    * **跳过非图像模型**（见 :data:`NON_IMAGE_KEYWORDS`）；
    * ``unets`` 与 ``diffusion_models`` 在本机是同一份候选，去重。
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for folder in ("unets", "checkpoints", "diffusion_models"):
        for name in (available_models or {}).get(folder) or []:
            key = str(name)
            if key in seen:
                continue
            seen.add(key)
            if is_non_image_model(key):
                continue
            out.append((folder, key))
    return out


def match_profile(name: str, available_models: dict | None = None) -> ModelProfile | None:
    """给一个具体模型名，返回最匹配的档案（不命中返回 ``None``）。

    非图像模型（音乐 / 视频 / 文本编码器）直接返回 ``None``。
    """
    if is_non_image_model(name):
        return None
    low = str(name or "").lower().replace("\\", "/")
    base = low.rsplit("/", 1)[-1]
    for prof in PROFILES:
        for kw in prof.match:
            if kw in base:
                return prof
    return None


# ══════════════════════════════════════════════════════════════════════
#  选择
# ══════════════════════════════════════════════════════════════════════
def by_key(key: str) -> ModelProfile | None:
    """按档案键取档案；``"auto"`` / 空串返回 ``None``（表示交给 detect）。"""
    k = (key or "").strip().lower()
    if k in ("", "auto"):
        return None
    return BY_KEY.get(k)


def detect(available_models: dict) -> ModelProfile:
    """按优先级从**实际可用模型**里挑一个档案。

    :param available_models: :meth:`ComfyClient.models` 的返回值，
        形如 ``{"checkpoints": [...], "unets": [...], "loras": [...], ...}``。
    :return: 选中的 :class:`ModelProfile`（永不返回 ``None``，兜底为通用 SDXL）

    匹配规则
    --------
    * 只在 ``unets`` / ``checkpoints`` / ``diffusion_models`` 里找
      （本机 Krea 2 / Qwen-Image 都在 unets）；
    * **跳过非图像模型** —— 本机装了 YuE2（音乐）、MiniMax-H3（视频）、
      ACE-Step（音乐），它们的文件名里也有 ``xl`` 之类的子串，
      不排除会误判出一个根本出不了图的档案；
    * 按 :data:`PROFILES` 的顺序（= 优先级）逐条比对关键词，**第一个命中的胜出**。
    """
    for _folder, name in _candidates(available_models):
        prof = match_profile(name)
        if prof is not None:
            return prof
    return BY_KEY[FALLBACK_KEY]


def detect_explain(available_models: dict) -> dict:
    """``detect`` 的可解释版本：给 UI / 调试用，说明「选了谁、为什么、还有谁没被选中」。"""
    cands = _candidates(available_models)
    chosen: ModelProfile | None = None
    chosen_from = ""
    for folder, name in cands:
        prof = match_profile(name)
        if prof is not None:
            chosen, chosen_from = prof, f"{folder}/{name}"
            break
    if chosen is None:
        chosen = BY_KEY[FALLBACK_KEY]
        reason = ("可用模型里没有任何档案关键词命中 → 使用兜底档案「%s」；"
                  "若本机没有 SDXL 动漫底模，出图质量会明显下降。" % chosen.zh)
    else:
        hits = [kw for kw in chosen.match
                if kw in chosen_from.lower().replace("\\", "/").rsplit("/", 1)[-1]]
        reason = ("在 %s 上命中关键词 %s → 选择档案「%s」（优先级 %d/%d）。"
                  % (chosen_from, hits, chosen.zh,
                     PROFILES.index(chosen) + 1, len(PROFILES)))
    return {
        "key": chosen.key,
        "zh": chosen.zh,
        "chain": chosen.chain,
        "from": chosen_from,
        "reason": reason,
        "candidates": [f"{f}/{n}" for f, n in cands],
        "steps": chosen.steps,
        "cfg": chosen.cfg,
        "sampler": chosen.sampler,
        "scheduler": chosen.scheduler,
        "size": list(chosen.size),
        "negative_effective": chosen.negative_effective,
        "skipped_non_image": [n for folder, n in
                              ((f, x) for f in ("unets", "checkpoints", "diffusion_models")
                               for x in ((available_models or {}).get(f) or []))
                              if is_non_image_model(n)],
    }


# ══════════════════════════════════════════════════════════════════════
#  画布
# ══════════════════════════════════════════════════════════════════════
def _align(v: int, step: int = SIZE_ALIGN) -> int:
    """向上取到 ``step`` 的倍数（ComfyUI 画布要求）。"""
    v = int(v)
    return max(step, (v + step - 1) // step * step)


def _bucket(v: float, step: int = 64) -> int:
    """吸附到模型常见的分桶（64 的倍数），避免出现 1006 这种非分桶尺寸。"""
    return max(step, int(round(v / step)) * step)


def art_size_for(frame: str, profile: ModelProfile,
                 width: int = 0, height: int = 0) -> tuple[int, int]:
    """给卡种 + 档案算出图尺寸（16 的倍数，自动吸附到 64 分桶）。

    * 显式给了 ``width``/``height`` → 只做 16 对齐，尊重用户。
    * 只给了一边 → 按**该卡种自己的窗比例**补另一边。
    * 都没给 → 先看档案默认画布是否已经贴合窗比例（差 2% 以内）→ 直接用；
      否则保持档案的像素量级（面积）按比例重算，再吸附到 64 分桶。

    :param frame: ``core.enums.FRAMES`` 的键，如 ``"fusion"``。
    :param profile: 选中的模型档案。
    """
    fd = FRAMES.get(frame)
    ratio = float(getattr(fd, "art_ratio", ART_WINDOW_RATIO) or ART_WINDOW_RATIO)
    if width and height:
        return _align(width), _align(height)
    if width and not height:
        return _align(width), _align(round(width / ratio))
    if height and not width:
        return _align(round(height * ratio)), _align(height)

    if abs(ratio - profile.width / max(1, profile.height)) < 0.02:
        # 档案默认画布本来就贴合这个窗 → 直接用（分桶最稳）
        return profile.width, profile.height
    # 比例不同（标准框=正方形、灵摆窗=0.78）：同面积重算 + 吸附分桶
    area = profile.width * profile.height
    h = (area / max(ratio, 1e-6)) ** 0.5
    w = h * ratio
    return _bucket(w), _bucket(h)


def describe_all() -> list[dict]:
    """给 UI 下拉用的档案清单。"""
    return [{
        "key": p.key, "zh": p.zh, "match": list(p.match), "chain": p.chain,
        "steps": p.steps, "cfg": p.cfg, "sampler": p.sampler,
        "scheduler": p.scheduler, "size": list(p.size), "clip_skip": p.clip_skip,
        "prompt_style": p.prompt_style, "natural_language": p.natural_language,
        "bilingual_text_encoder": p.bilingual_text_encoder,
        "negative_effective": p.negative_effective,
        "license": p.license_line, "notes": p.notes,
    } for p in PROFILES]


__all__ = [
    "ModelProfile", "PROFILES", "BY_KEY", "FALLBACK_KEY", "SIZE_ALIGN",
    "ART_WINDOW_RATIO", "NON_IMAGE_KEYWORDS", "IMAGE_KEYWORDS",
    "detect", "detect_explain", "match_profile", "is_non_image_model",
    "by_key", "art_size_for", "describe_all",
]
