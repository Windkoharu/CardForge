"""编排 —— 从 :class:`ArtRequest` 到磁盘上的卡图。

主流程（:func:`generate`）
-------------------------
``探测存活`` → ``拉模型清单`` → ``选档案`` → ``编译提示词`` → ``建图`` →
``提交`` → ``轮询等结果`` → ``取图落盘`` → ``存进资产库`` → ``返回 ArtResult``

三个必须记住的工程事实
----------------------
1. **``/view`` 必须带 ``subfolder``**（否则 404）—— 这里原样透传 history 的三个字段。
2. **每张图必须换 seed** —— ``ComfyUI`` 的 ``IS_CHANGED`` 缓存会让「输入没变」的采样节点
   直接复用旧输出文件。:func:`generate_series` 用 ``base_seed + index`` 强制换 seed。
3. **``cfg <= 1`` 时负向不生效** —— 提示词层已把排除意图改写进正向（见 ``prompt.build``）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..core import paths as P
from ..core.errors import ComfyError
from ..core.models import Archetype, ArtRequest, ArtResult, CardSpec
from . import graph as G
from . import library as L
from . import presets as PS
from . import profiles as PF
from . import prompt as PR
from .client import ComfyClient, bump_seed, new_seed
from .profiles import ModelProfile

__all__ = [
    "generate", "generate_layers", "generate_series", "export_workflow",
    "capabilities", "postprocess", "resolve_profile", "probe", "DEFAULT_HOST",
]

DEFAULT_HOST = "http://127.0.0.1:8188"

#: 这些 ``class_type`` 是「增强节点」：缺了要优雅降级，而不是报错
ENHANCEMENT_NODES = (
    "UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScale",
    "BiRefNetRMBG", "LoadBackgroundRemovalModel", "RemoveBackground",
    "JoinImageWithAlpha", "BriaRemoveImageBackground",
    "IPAdapterUnifiedLoader", "IPAdapterAdvanced", "CLIPVisionLoader",
    "ControlNetLoader", "ControlNetApplyAdvanced",
)

#: 放大模型优先级（动漫优先 —— 插画场景 ESRGAN 动漫权重明显更好）
UPSCALE_PREFER = ("anime", "ultrasharp", "siax", "remacri", "nmkd", "superscale", "fatal")

#: 各 chain 的文本编码器候选关键词（**按优先级**）。
#: 本机 ``CLIPLoader.clip_name`` 里有 ``MINIMAX-H3\qwen3vl_32b_...``（视频模型编码器），
#: 名字里也带 ``qwen3vl`` —— 如果不排除，Krea 2 会拿它当文本编码器，
#: 报错 "Krea2 expects conditioning with 12x2560=30720 features ... but got 5120"。
#: 所以这里既做**正向优先**也做**负向排除**。
CLIP_PREFER: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "krea2": (("qwen3vl_4b", "krea2"), ("minimax", "32b", "ace", "yue2", "8b")),
    "qwen": (("qwen_image_2.1_pe_t2i", "qwen_image_2.1", "qwen_image"), ("minimax", "ace", "yue2")),
    "flux": (("t5xxl", "clip_l", "flux"), ("minimax", "ace", "yue2")),
}

#: 各 chain 的 VAE 候选关键词（正向优先 / 负向排除）
VAE_PREFER: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "krea2": (("qwen_image_vae",), ("minimax", "video", "audio", "ace")),
    "qwen": (("qwen_image_2.1_vae", "qwen_image_vae"), ("minimax", "ace")),
    "flux": (("ae.safetensors", "flux"), ("minimax", "ace", "yue2")),
}


def _prefer(names: list[str], prefer: tuple[tuple[str, ...], tuple[str, ...]],
            strict: list[str] | None = None) -> str:
    """从候选里按「正向关键词优先级 + 负向排除」挑一个；挑不到返回空串。"""
    pool = [str(x) for x in (names or [])]
    if strict:
        for want in strict:
            if want and want in pool:
                return want
    good, bad = prefer
    for kw in good:
        for cand in pool:
            low = cand.lower().replace("\\", "/")
            if kw in low and not any(b in low for b in bad):
                return cand
    for cand in pool:
        low = cand.lower().replace("\\", "/")
        if not any(b in low for b in bad):
            return cand
    return ""


# ══════════════════════════════════════════════════════════════════════
#  探测
# ══════════════════════════════════════════════════════════════════════
def probe(host: str = DEFAULT_HOST, timeout: int = 600) -> dict:
    """一次性探测：存活、节点、模型、档案选择。

    :return: ``{"client","summary","models","nodes","profile","profile_reason",
        "online","missing","upgrade_paths"}``

    **永不抛异常** —— 探测失败时 ``online=False``，其余字段给空值/兜底档案。
    """
    client = ComfyClient(host=host, timeout=timeout)
    out: dict = {"host": host, "online": False, "client": client,
                 "summary": {}, "models": {}, "nodes": {}, "missing": [],
                 "profile": None, "profile_reason": "", "upgrade_paths": []}
    if not client.alive():
        out["profile"] = PF.by_key(PF.FALLBACK_KEY)
        out["profile_reason"] = (
            "ComfyUI 不在线（/system_stats 连不上）→ 返回兜底档案，"
            "所有出图调用都会抛 ComfyError(kind='offline')。"
        )
        out["upgrade_paths"] = ["启动 ComfyUI 后重试；检查 host 与端口。"]
        return out
    out["online"] = True
    out["summary"] = client.summary()
    out["models"] = client.models()
    out["nodes"] = client.object_info_summary()
    missing = [n for n in ENHANCEMENT_NODES
               if not (out["nodes"].get("present") or {}).get(n)
               and n not in ("ImageScale", "UpscaleModelLoader", "ImageUpscaleWithModel")]
    out["missing"] = [n for n in missing
                      if n not in (out["nodes"].get("present") or {})]
    chosen = PF.detect(out["models"])
    out["profile"] = chosen
    out["profile_reason"] = PF.detect_explain(out["models"])["reason"]
    # 记录降级原因
    deg: list[str] = []
    if not out["models"].get("clip_vision"):
        deg.append("没有 CLIP Vision 模型（models/clip_vision/ 为空）→ IPAdapter 链路不可用，"
                   "系列一致性只能靠固定风格前缀 + 每张换 seed。")
    if not out["models"].get("upscale"):
        deg.append("没有放大模型（models/upscale_models/ 为空）→ 放大链路退化为 lanczos 重采样。")
    if not out["models"].get("controlnet"):
        deg.append("没有 ControlNet 模型（models/controlnet/ 为空）→ 姿势/构图锁定不可用。")
    if not out["models"].get("checkpoints"):
        deg.append("CheckpointLoaderSimple 候选为空 → SDXL/SD1.5 链路不可用"
                   "（只能走 Krea 2 / Qwen-Image 的 UNETLoader 链路）。")
    out["degraded"] = deg
    out["upgrade_paths"] = _upgrade_paths(out)
    return out


def _upgrade_paths(p: dict) -> list[str]:
    """给用户看的「想更好该怎么装」清单。"""
    tips: list[str] = []
    key = (p.get("profile").key if p.get("profile") else "")
    if key in ("krea2", "qwen_image"):
        tips.append("想要干净的商用授权 + Danbooru 标签体系：装 Animagine XL 4.0"
                    "（CreativeML OpenRAIL++-M，允许商用）→ 档案自动切到 animagine。")
        tips.append("想要更强的标签依从性与社区 LoRA 生态：装 Illustrious/NoobAI"
                    "（注意其授权禁止闭源专有商业化）。")
    tips.append("想要「一张风格母版统一整个系列」：往 models/clip_vision/ 放 "
                "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors + models/ipadapter/ 放 "
                "ip-adapter-plus_sdxl_vit-h.safetensors（**注意 IPAdapter 对 DiT 模型无效**）。")
    tips.append("想要更好的放大：往 models/upscale_models/ 放 "
                "RealESRGAN_x4plus_anime_6B.pth（动漫首选）或 4x-UltraSharp.pth。")
    return tips


def resolve_profile(profile_key: str = "auto", models: dict | None = None,
                    host: str = DEFAULT_HOST) -> ModelProfile:
    """把 ``profile`` 参数（键名或 ``"auto"``）解析成 :class:`ModelProfile`。

    ``"auto"`` 时按本机实际可用模型自动选（见 :func:`cardforge.art.profiles.detect`）。
    """
    prof = PF.by_key(profile_key)
    if prof is not None:
        return prof
    if models is None:
        client = ComfyClient(host=host)
        models = client.models() if client.alive() else {}
    return PF.detect(models)


def _pick_model(profile: ModelProfile, models: dict) -> tuple[str, str, str]:
    """挑出 ``(unet_or_ckpt, clip, vae)``。

    排序原则（避免「选了本机最像但维度不对的权重」这类坑）：

    1. 先按档案关键词匹配，且**跳过非图像模型**（见
       :data:`cardforge.art.profiles.NON_IMAGE_KEYWORDS`）；
    2. 再退到 unets / checkpoints 里第一个非图像模型之外的候选。
    """
    unets = [x for x in (models.get("unets") or []) if not PF.is_non_image_model(x)]
    ckpts = [x for x in (models.get("checkpoints") or []) if not PF.is_non_image_model(x)]
    src = unets or ckpts
    if not src:
        raise ComfyError(
            "本机没有任何可用的**图像**底模（UNETLoader.unet_name 与 "
            "CheckpointLoaderSimple.ckpt_name 里只剩音乐/视频模型）",
            "把图像底模放进 ComfyUI/models/diffusion_models（DiT，如 Krea 2 / Qwen-Image）"
            "或 ComfyUI/models/checkpoints（SDXL/SD1.5），然后在界面点一次刷新。",
            kind="model_missing",
            detail={"unets": models.get("unets"), "checkpoints": models.get("checkpoints")})
    name = ""
    for cand in src:
        if PF.match_profile(cand) is profile:
            name = cand
            break
    if not name:
        name = src[0]
    clips = list(models.get("clips") or [])
    vaes = list(models.get("vaes") or [])
    ex = profile.extras or {}
    clip = vae = ""
    if profile.chain in ("krea2", "qwen", "flux"):
        strict_clip = [str(ex.get("clip") or ""), str(ex.get("text_encoder_t2i") or "")]
        clip = _prefer(clips, CLIP_PREFER.get(profile.chain, ((), ())), strict_clip)
        strict_vae = [str(ex.get("vae") or "")]
        vae = _prefer(vaes, VAE_PREFER.get(profile.chain, ((), ())), strict_vae)
        miss = [n for n, v in (("文本编码器", clip), ("VAE", vae)) if not v]
        if miss:
            raise ComfyError(
                f"{profile.zh} 链路缺少 {'、'.join(miss)}",
                "把 qwen3vl_4b_fp8_scaled.safetensors 放进 ComfyUI/models/text_encoders/、"
                "qwen_image_vae.safetensors 放进 ComfyUI/models/vae/，然后刷新 ComfyUI。"
                "⚠️ 注意不要选到 MINIMAX-H3 / ACE-Step / YuE2 的编码器 —— 它们名字里"
                "也带 qwen 字样，但特征维度不匹配（Krea 2 需要 12×2560=30720 维）。",
                kind="model_missing", detail={"clips": clips, "vaes": vaes,
                                              "chosen_clip": clip, "chosen_vae": vae})
    return name, clip, vae


def _pick_upscale_model(models: dict) -> str:
    """按「动漫优先」的优先级挑放大模型；没有返回空串。"""
    cands = list(models.get("upscale") or [])
    for kw in UPSCALE_PREFER:
        for c in cands:
            if kw in c.lower():
                return c
    return cands[0] if cands else ""


def _strict_models(client: ComfyClient, profile: ModelProfile, name: str,
                   clip: str, vae: str, loras) -> None:
    """提交前校验模型名真的在候选里（否则抛 ``model_missing`` + 中文 hint）。

    这是「故意传一个不存在的模型名」时的正确行为：**在提交前**就给出可执行的提示，
    而不是等 ComfyUI 返回 400。
    """
    models = client.models()
    pools = {        "底模": (list(models.get("unets") or []) + list(models.get("checkpoints") or []),
                "models/diffusion_models 或 models/checkpoints"),
        "文本编码器": (list(models.get("clips") or []), "models/text_encoders"),
        "VAE": (list(models.get("vaes") or []), "models/vae"),
    }
    checks = [("底模", name), ("文本编码器", clip), ("VAE", vae)]
    for label, value in checks:
        if not value:
            continue
        pool, folder = pools[label]
        if pool and value not in pool:
            raise ComfyError(
                f"{label} `{value}` 不在 ComfyUI 的候选列表里",
                f"把 `{value}` 放进 ComfyUI/{folder}，然后在界面点一次刷新"
                f"（或重启）让 /object_info 重新枚举。本机现有{label} {len(pool)} 个，"
                f"调 client.models() 看完整清单。",
                kind="model_missing",
                detail={"field": label, "value": value, "available": pool[:50]})
    lora_pool = list(models.get("loras") or [])
    for lname, _strength in G.parse_loras(loras):
        if lora_pool and lname not in lora_pool:
            raise ComfyError(
                f"LoRA `{lname}` 不在 ComfyUI 的候选列表里",
                "把 LoRA 放进 ComfyUI/models/loras/ 并刷新。注意 LoRA 与底模必须同族"
                "（Krea 2 的 LoRA 不能用在 SDXL 上）。本机 krea2_* LoRA 有 "
                f"{len([x for x in lora_pool if x.lower().startswith('krea2')])} 个。",
                kind="model_missing",
                detail={"field": "LoRA", "value": lname, "available": lora_pool[:50]})
    _ = profile


# ══════════════════════════════════════════════════════════════════════
#  能力清单
# ══════════════════════════════════════════════════════════════════════
def capabilities(host: str = DEFAULT_HOST) -> dict:
    """ComfyUI 是否在线、可用档案、缺哪些模型、降级原因。

    :return: ``{"online","host","summary","models","nodes","profiles",
        "active_profile","profile_reason","missing_models","degraded",
        "upgrade_paths","presets","loras_krea2","bg_nodes","upscale_models",
        "ready"}``
    """
    p = probe(host=host)
    models = p.get("models") or {}
    nodes_present = (p.get("nodes") or {}).get("present") or {}
    active = p.get("profile")
    # 哪些档案「现在就能用」
    prof_avail: list[dict] = []
    src = list(models.get("unets") or []) + list(models.get("checkpoints") or [])
    for prof in PF.PROFILES:
        hit = [n for n in src if PF.match_profile(n) is prof]
        usable = bool(hit)
        if not usable and prof.chain in ("krea2", "qwen", "flux"):
            usable = False
        reason = ("本机有匹配权重：" + "、".join(hit)) if hit else "本机没有匹配的权重"
        prof_avail.append({"key": prof.key, "zh": prof.zh, "chain": prof.chain,
                           "usable": usable, "reason": reason,
                           "steps": prof.steps, "cfg": prof.cfg,
                           "size": list(prof.size), "license": prof.license_line})
    missing_models: list[str] = []
    if not src:
        missing_models.append("任何底模（unets/checkpoints 都为空）")
    if active and active.chain in ("krea2", "qwen", "flux"):
        if not models.get("clips"):
            missing_models.append("文本编码器（CLIPLoader.clip_name 为空）")
        if not models.get("vaes"):
            missing_models.append("VAE（VAELoader.vae_name 为空）")
    if not models.get("clip_vision"):
        missing_models.append("CLIP Vision（models/clip_vision/ 为空）→ IPAdapter 不可用")
    if not models.get("upscale"):
        missing_models.append("放大模型（models/upscale_models/ 为空）")
    if not models.get("controlnet"):
        missing_models.append("ControlNet（models/controlnet/ 为空）")
    bg_nodes = [n for n in ("BiRefNetRMBG", "RemoveBackground",
                            "BriaRemoveImageBackground", "LoadBackgroundRemovalModel")
                if nodes_present.get(n)]
    return {
        "online": bool(p.get("online")),
        "host": host,
        "summary": p.get("summary") or {},
        "models": models,
        "nodes": p.get("nodes") or {},
        "profiles": prof_avail,
        "active_profile": (active.key if active else ""),
        "active_profile_zh": (active.zh if active else ""),
        "profile_reason": p.get("profile_reason", ""),
        "missing_models": missing_models,
        "degraded": p.get("degraded") or [],
        "upgrade_paths": p.get("upgrade_paths") or [],
        "presets": [{k: v for k, v in item.items() if k in ("key", "zh", "use")}
                    for item in PS.describe_all()],
        "loras_krea2": [x for x in (models.get("loras") or [])
                        if str(x).lower().startswith("krea2")],
        "bg_nodes": bg_nodes,
        "upscale_models": list(models.get("upscale") or []),
        "ready": bool(p.get("online")) and bool(models.get("unets") or models.get("checkpoints")),
    }


# ══════════════════════════════════════════════════════════════════════
#  出图
# ══════════════════════════════════════════════════════════════════════
def _make_request(req: ArtRequest | None, **over) -> ArtRequest:
    base = {"preset": "t2i_single", "profile": "auto"}
    if req is None:
        req = ArtRequest(**base)
    for k, v in over.items():
        if v is not None and hasattr(req, k):
            setattr(req, k, v)
    return req


def generate(req: ArtRequest, card: CardSpec | None = None,
             on_progress=None, *, host: str = DEFAULT_HOST,
             client: ComfyClient | None = None,
             dry_run: bool = False,
             raise_on_error: bool = False,
             store: bool = True,
             prompts: dict | None = None) -> ArtResult:
    """出**一张**卡图。完整链路：探测 → 选档案 → 建图 → 提交 → 取图 → 入库 → 返回。

    :param req: 出图请求。``width``/``height``/``steps``/``cfg``/``sampler``/
        ``scheduler`` 给 0 或空串时按档案与卡种自动补。
    :param card: 卡牌规格（决定卡种氛围词、比例、入库的 card_id）。
    :param on_progress: 回调 ``fn(info: dict)``；``info`` 里带 ``stage`` 字段
        （``probe``/``prompt``/``graph``/``submit``/``wait``/``download``/``save``）
        与 ``elapsed``/``queue_running``/``queue_pending`` 等。
    :param dry_run: ``True`` 时只建图不提交（用于预览工作流）。
    :param raise_on_error: 默认 ``False`` —— 失败也返回 ``ok=False`` 的
        :class:`ArtResult`（符合「可降级的能力失败返回 None/空集合，不抛异常」的约定）。
        传 ``True`` 时把 :class:`ComfyError` 原样抛出，便于调用方按 ``kind`` 分支。
    :return: :class:`ArtResult`。失败时 ``ok=False``，``error``/``hint`` 是中文，
        ``meta["kind"]`` 是 ``offline``/``node_missing``/``model_missing``/``oom``/
        ``timeout``/``bad_prompt`` 之一。
    :raises ComfyError: 仅当 ``raise_on_error=True``。
    """
    t0 = time.time()
    notes: list[str] = []

    def report(stage: str, **kw) -> None:
        if on_progress:
            try:
                on_progress({"stage": stage, "elapsed": round(time.time() - t0, 2), **kw})
            except Exception:  # pragma: no cover
                pass

    report("probe")
    cli = client or ComfyClient(host=host, timeout=600)
    if not cli.alive():
        return ArtResult(ok=False, error="ComfyUI 不在线",
                         hint=("启动 ComfyUI：D:\\AI\\ComfyUI-aki-v3.2\\python\\python.exe "
                               "D:\\AI\\ComfyUI-aki-v3.2\\ComfyUI\\main.py --auto-launch "
                               "--preview-method auto"),
                         took_ms=int((time.time() - t0) * 1000))
    models = cli.models()
    schemas = cli.object_info()
    profile = resolve_profile(getattr(req, "profile", "auto"), models, host)

    # 尺寸 / 采样参数：0 = 按档案与卡种自动
    frame = (card.frame if card is not None else "effect")
    width, height = PF.art_size_for(frame, profile,
                                    int(getattr(req, "width", 0) or 0),
                                    int(getattr(req, "height", 0) or 0))
    steps = int(getattr(req, "steps", 0) or profile.steps)
    cfg = float(getattr(req, "cfg", 0.0) or profile.cfg)
    sampler = str(getattr(req, "sampler", "") or profile.sampler)
    scheduler = str(getattr(req, "scheduler", "") or profile.scheduler)
    seed = int(getattr(req, "seed", -1))
    if seed < 0:
        seed = new_seed()
        notes.append(f"seed 未指定 → 随机 {seed}")

    report("prompt", profile=profile.key)
    arch = None
    if getattr(req, "archetype", ""):
        arch = _load_arch(req.archetype, card)
    # 分层出图会把**同一份请求的两套提示词**分别送进来，所以允许外部传 prompts
    pr = prompts if isinstance(prompts, dict) else PR.build(req, card, profile, arch)
    notes.append(pr["notes"])

    report("graph", profile=profile.key, width=width, height=height, steps=steps,
           cfg=cfg, seed=seed)
    try:
        name, clip, vae = _pick_model(profile, models)
        if not dry_run:
            _strict_models(cli, profile, name, clip, vae, getattr(req, "loras", []))
    except ComfyError as exc:
        if raise_on_error:
            raise
        return ArtResult(ok=False, error=exc.message, hint=exc.hint,
                         meta={"kind": exc.kind, "detail": exc.detail},
                         took_ms=int((time.time() - t0) * 1000))
    up_model = _pick_upscale_model(models) if getattr(req, "upscale", False) else ""
    try:
        g = G.build_t2i(
            profile=profile, ckpt_or_unet=name, clip=clip, vae=vae,
            positive=pr["positive"], negative=pr["negative"],
            width=width, height=height, seed=seed, steps=steps, cfg=cfg,
            sampler=sampler, scheduler=scheduler, loras=getattr(req, "loras", []),
            save_prefix=getattr(req, "save_prefix", "") or _save_prefix(req, card),
            available=set(schemas.keys()), schemas=schemas,
            upscale=bool(getattr(req, "upscale", False)), upscale_model=up_model,
            remove_bg=bool(getattr(req, "remove_bg", False)),
            bg_invert=bool(getattr(req, "cutout_invert", True)),
            local_bg_models=list(models.get("background_removal") or []))
    except ComfyError as exc:
        if raise_on_error:
            raise
        return ArtResult(ok=False, error=exc.message, hint=exc.hint,
                         meta={"kind": exc.kind, "detail": exc.detail},
                         took_ms=int((time.time() - t0) * 1000))
    problems = G.validate(g.to_api(), schemas)
    if problems:
        return ArtResult(ok=False, error="工作流自检未通过：" + "；".join(problems),
                         hint="按提示修正参数或节点后再提交。",
                         workflow=g.to_api(), took_ms=int((time.time() - t0) * 1000))
    fp = g.fingerprint()
    meta = {
        "profile": profile.key, "profile_zh": profile.zh, "chain": profile.chain,
        "model": name, "clip": clip, "vae": vae,
        "positive": pr["positive"], "negative": pr["negative"],
        "style_tags": pr["style_tags"], "series_style": pr["series_style"],
        "loras": list(getattr(req, "loras", [])), "seed": seed,
        "width": width, "height": height, "steps": steps, "cfg": cfg,
        "sampler": sampler, "scheduler": scheduler,
        "prompt_prefix": profile.prompt_prefix,
        "workflow_fingerprint": fp, "preset": getattr(req, "preset", "t2i_single"),
        "request": req.to_dict(), "warnings": list(g.warnings),
        "negative_effective": profile.negative_effective,
        "notes": notes,
    }
    if dry_run:
        return ArtResult(ok=True, images=[], meta=meta, workflow=g.to_api(),
                         took_ms=int((time.time() - t0) * 1000))

    report("submit", fingerprint=fp)
    try:
        pid = cli.queue(g.to_api(), client_id=cli.client_id)
    except ComfyError as exc:
        return ArtResult(ok=False, error=exc.message, hint=exc.hint,
                         meta={**meta, "kind": exc.kind}, workflow=g.to_api(),
                         took_ms=int((time.time() - t0) * 1000))

    report("wait", prompt_id=pid)
    try:
        entry = cli.wait(pid, on_progress=lambda info: report("wait", **info),
                         timeout=max(120, int(getattr(req, "timeout", 0) or 900)))
    except ComfyError as exc:
        return ArtResult(ok=False, error=exc.message, hint=exc.hint,
                         meta={**meta, "kind": exc.kind, "prompt_id": pid},
                         workflow=g.to_api(), took_ms=int((time.time() - t0) * 1000))

    report("download", prompt_id=pid)
    tmp = Path(P.WORKSPACE) / ".cache" / "art" / f"{pid[:8]}"
    try:
        files = cli.download_outputs(entry, tmp)
    except ComfyError as exc:
        return ArtResult(ok=False, error=exc.message, hint=exc.hint,
                         meta={**meta, "kind": exc.kind, "prompt_id": pid},
                         workflow=g.to_api(), took_ms=int((time.time() - t0) * 1000))
    if not files:
        return ArtResult(ok=False,
                         error="ComfyUI 跑完了但 history 里没有任何图片输出",
                         hint=("多半是 IS_CHANGED 缓存命中导致复用了旧输出，"
                               "或者工作流里没有 SaveImage。换一个 seed 再提交一次。"),
                         meta={**meta, "prompt_id": pid}, workflow=g.to_api(),
                         took_ms=int((time.time() - t0) * 1000))

    report("save", files=len(files))
    took = int((time.time() - t0) * 1000)
    card_id = int(getattr(req, "card_id", 0) or (card.id if card is not None else 0) or 0)
    arch_name = str(getattr(req, "archetype", "") or
                    (card.archetype if card is not None else "") or "")
    meta.update({"prompt_id": pid, "took_ms": took,
                 "outputs": [Path(f).name for f in files]})
    saved: list[dict] = []
    if card_id and store:
        for f in files:
            try:
                saved.append(L.save(card_id, f, meta, arch_name))
            except Exception as exc:  # pragma: no cover - 入库失败不该毁掉出图结果
                notes.append(f"入库失败（{f}）：{exc}")
        meta["notes"] = notes
        # 入库结果回带给上层：``L.save`` 已经把 current 指过去了，
        # 上层再 save 一次就会每出一张图多存一个重复版本。
        meta["saved"] = saved
    elif card_id and not store:
        notes.append("store=False → 只落盘不入库（分层出图的中间 pass 用）")
    else:
        notes.append("card_id 为 0 → 只落盘不版本化；"
                     "把卡片 id 填进 ArtRequest.card_id 才会写进资产库。")
        meta["notes"] = notes
    return ArtResult(ok=True, images=list(files), meta=meta, workflow=g.to_api(),
                     took_ms=took)


def _alpha_ratio(path: str) -> tuple[float, float]:
    """``(不透明占比, 半透明占比)`` —— 判断抠底极性对不对的硬指标。"""
    from PIL import Image
    with Image.open(path) as im:
        if im.mode != "RGBA":
            return 1.0, 0.0                      # 没 alpha = 抠底根本没生效
        hist = im.getchannel("A").histogram()
    n = sum(hist) or 1
    return sum(hist[230:]) / n, sum(hist[16:230]) / n


def _flatten_layers(bg_path: str, subj_path: str, out_path: str) -> str:
    """把两层压平成一张普通卡图（主体按窗高对齐、水平居中）。

    压平件是 ``v{n}.png``：导出/卡面/预览这些**不认识分层**的老链路照旧用它。
    """
    from PIL import Image
    bg = Image.open(bg_path).convert("RGBA")
    sub = Image.open(subj_path).convert("RGBA")
    k = bg.height / max(1, sub.height)
    sub = sub.resize((max(1, int(sub.width * k)), bg.height), Image.LANCZOS)
    if sub.width > bg.width:                     # 主体过宽时居中裁切，不让它撑破预览
        x0 = (sub.width - bg.width) // 2
        sub = sub.crop((x0, 0, x0 + bg.width, bg.height))
    out = bg.copy()
    out.alpha_composite(sub, ((bg.width - sub.width) // 2, 0))
    out.convert("RGB").save(out_path, "PNG")
    return out_path


def generate_layers(req: ArtRequest, card: CardSpec | None = None,
                    on_progress=None, *, host: str = DEFAULT_HOST,
                    client: ComfyClient | None = None,
                    dry_run: bool = False) -> ArtResult:
    """**背景与主体分两次生成**，主体抠底成 alpha 层，最后压平入库。

    为什么要拆层：出框时只想让**主体**越出卡图窗，背景仍然严实地留在窗内 ——
    一张压平的整图做不到，必须让主体带 alpha 单独成层。

    流程：

    1. :func:`cardforge.art.prompt.build_layers` 出两套提示词；
    2. 背景 pass（不带任何主体导向的氛围词与构图词）；
    3. 主体 pass（纯色底 + 全身 + 四周留白）→ 抠底；
    4. **探测 alpha**：不透明占比 ≈0 或 ≈1 说明抠反了/没抠动 → 翻转 mask 极性重跑一次
       （本机实测：默认极性适配「暗主体亮底」，白龙这类亮色主体会被抠空）；
    5. 压平成 ``v{n}.png``，两层另存 ``v{n}_bg.png`` / ``v{n}_subject.png``。

    两个 pass 共用同一风格前缀与同一模型档案，光照一致性靠它们 + 提示词里的
    同一段 lighting 句子；**seed 各取一个**（同 seed 跨两套不同提示词没有意义）。
    """
    from dataclasses import replace

    t0 = time.time()
    cli = client or ComfyClient(host=host, timeout=600)
    if not cli.alive():
        return ArtResult(ok=False, error="ComfyUI 不在线",
                         hint="启动 ComfyUI 后重试；分层出图需要跑两次采样。",
                         took_ms=int((time.time() - t0) * 1000))
    models = cli.models()
    profile = resolve_profile(getattr(req, "profile", "auto"), models, host)
    arch = _load_arch(req.archetype, card) if getattr(req, "archetype", "") else None
    pr = PR.build_layers(req, card, profile, arch)

    meta = {"mode": "layers", "profile": profile.key, "profile_zh": profile.zh,
            "chain": profile.chain, "cutout_bg": pr["cutout_bg"],
            "prompt_background": pr["background"]["positive"],
            "prompt_subject": pr["subject"]["positive"],
            "negative_background": pr["background"]["negative"],
            "negative_subject": pr["subject"]["negative"],
            "style_tags": pr["style_tags"], "series_style": pr["series_style"],
            "preset": "t2i_layers", "request": req.to_dict(),
            "notes": pr["notes"]}
    if dry_run:
        return ArtResult(ok=True, images=[], meta=meta, workflow={},
                         took_ms=int((time.time() - t0) * 1000))

    def _cb(stage):
        def inner(info):
            if on_progress:
                try:
                    on_progress({**info, "pass": stage})
                except Exception:  # noqa: BLE001  进度回调不该影响出图
                    pass
        return inner

    # ── pass 1：背景 ──
    r_bg = replace(req, layers=False, remove_bg=False, preset="t2i_single")
    a = generate(r_bg, card, on_progress=_cb("background"), host=host, client=cli,
                 store=False, prompts=pr["background"])
    if not a.ok:
        return ArtResult(ok=False, error="背景 pass 失败：" + a.error,
                         hint=a.hint, meta={**meta, "bg": a.meta}, took_ms=a.took_ms)
    if not a.images:
        return ArtResult(ok=False, error="背景 pass 没有产出图片",
                         hint="看 ComfyUI 控制台是否有节点报错。", meta=meta)
    bg_path = a.images[0]

    # ── pass 2：主体（纯色底 → 抠底）──
    r_sub = replace(req, layers=False, remove_bg=True, preset="t2i_single")
    b = generate(r_sub, card, on_progress=_cb("subject"), host=host, client=cli,
                 store=False, prompts=pr["subject"])
    if not b.ok or not b.images:
        return ArtResult(ok=False,
                         error="主体 pass 失败：" + (b.error or "没有产出图片"),
                         hint=b.hint, meta={**meta, "bg": bg_path}, took_ms=b.took_ms)
    subj_path = b.images[0]

    opaque, semi = _alpha_ratio(subj_path)
    notes = list(meta.get("notes", "").split("\n"))
    if opaque < 0.02 or opaque > 0.985:
        # 抠反了（亮色主体在默认极性下会被抠空 / 底没去掉）→ 翻极性重跑一次
        notes.append(f"首次抠底不透明占比 {opaque:.1%} 不合理 → 翻转 mask 极性重跑主体 pass。")
        r_sub2 = replace(r_sub, cutout_invert=not bool(getattr(req, "cutout_invert", True)))
        c = generate(r_sub2, card, on_progress=_cb("subject-retry"), host=host,
                     client=cli, store=False, prompts=pr["subject"])
        if c.ok and c.images:
            o2, s2 = _alpha_ratio(c.images[0])
            if 0.02 <= o2 <= 0.985:
                subj_path, opaque, semi = c.images[0], o2, s2
                b = c
            else:
                notes.append(f"翻转后仍不合理（{o2:.1%}）→ 主体层按原样使用；"
                             "出框时请换 cutout_bg（如 white/green）或降低 ThresholdMask。")
    notes.append(f"抠底：不透明 {opaque:.1%} · 半透明 {semi:.1%}。")

    # ── 压平 + 入库 ─
    cid = int(getattr(req, "card_id", 0) or (card.id if card is not None else 0) or 0)
    arch_name = str(getattr(req, "archetype", "") or
                    (card.archetype if card is not None else "") or "")
    flat_dir = Path(P.WORKSPACE) / ".cache" / "art" / "layers"
    flat_dir.mkdir(parents=True, exist_ok=True)
    flat = _flatten_layers(bg_path, subj_path,
                           str(flat_dir / f"{Path(bg_path).stem}_flat.png"))
    meta.update({"layers": {"background": bg_path, "subject": subj_path},
                 "alpha_opaque": round(opaque, 4), "alpha_semi": round(semi, 4),
                 "seed_background": (a.meta or {}).get("seed"),
                 "seed_subject": (b.meta or {}).get("seed"),
                 "took_background_ms": a.took_ms, "took_subject_ms": b.took_ms,
                 "notes": "\n".join(x for x in notes if x)})
    saved = []
    if cid:
        try:
            saved.append(L.save(cid, flat, meta, arch_name,
                                layers={"background": bg_path, "subject": subj_path}))
        except Exception as e:  # noqa: BLE001
            meta.setdefault("notes", "")
            meta["notes"] += f"\n入库失败：{type(e).__name__}: {e}"
    meta["saved"] = saved
    return ArtResult(ok=True, images=[flat, bg_path, subj_path], meta=meta,
                     workflow={}, took_ms=int((time.time() - t0) * 1000))


def _save_prefix(req: ArtRequest, card: CardSpec | None) -> str:
    """给 ``SaveImage.filename_prefix`` 拼一个可读前缀（决定 output 下的子目录）。"""
    arch = str(getattr(req, "archetype", "") or
               (card.archetype if card is not None else "") or "cards")
    cid = int(getattr(req, "card_id", 0) or (card.id if card is not None else 0) or 0)
    tag = f"{arch}/{cid}" if cid else f"{arch}/preview"
    safe = "".join("_" if c in '<>:"/\\|?*' else c for c in tag)
    return f"cardforge/{safe}"


def _load_arch(name: str, card: CardSpec | None) -> Archetype | None:
    """尽力加载系列圣经；失败返回 ``None``（不抛异常 —— 风格前缀会退化）。"""
    if not name:
        return None
    try:
        p = Path(P.archetype_dir(name)) / "spec.json"
        if p.exists():
            return Archetype.from_dict(json.loads(p.read_text(encoding="utf-8")))
        p2 = Path(P.archetype_dir(name)) / "archetype.json"
        if p2.exists():
            return Archetype.from_dict(json.loads(p2.read_text(encoding="utf-8")))
        for cand in Path(P.ARCHETYPES).glob("*/*.json"):
            data = json.loads(cand.read_text(encoding="utf-8"))
            if str(data.get("name") or "") == name:
                return Archetype.from_dict(data)
    except Exception:
        return None
    if card is not None:
        return Archetype(name=name, binding={"attribute": card.attribute,
                                             "race": card.race})
    return Archetype(name=name)


def generate_series(arch: Archetype, cards: list[CardSpec], base: ArtRequest,
                    on_progress=None, *, host: str = DEFAULT_HOST,
                    client: ComfyClient | None = None) -> list[ArtResult]:
    """**共享风格前缀批量出图**：同一系列的多张卡，只变主体。

    关键约定
    --------
    * **风格前缀冻结**：第一张卡编译出的 ``series_style`` 会写回
      ``base.series_context[SERIES_STYLE_KEY]``，后续所有卡共用同一段
      （一个字都不改）—— 这是零额外模型、见效最快的一致性手段。
    * **每张必须换 seed**：``seed = base_seed + index``。用同一个 seed 跑整批，
      构图会高度雷同；而**完全不换 seed 还会撞上 ComfyUI 的 IS_CHANGED 缓存**，
      直接拿到上一张的旧文件。

    :param arch: 系列圣经（提供风格前缀的来源）。
    :param cards: 该系列的卡列表。
    :param base: 基础请求（``subject`` 会被每张卡覆盖）。
    :param on_progress: 回调 ``fn(info)``，``info["index"]``/``info["total"]`` 可用。
    :return: 与 ``cards`` 等长的 :class:`ArtResult` 列表（逐张失败不会中断整批）。
    """
    cli = client or ComfyClient(host=host, timeout=600)
    results: list[ArtResult] = []
    base_seed = int(getattr(base, "seed", -1))
    if base_seed < 0:
        base_seed = new_seed()
    ctx = dict(getattr(base, "series_context", None) or {})
    total = len(cards)
    for i, card in enumerate(cards):
        req = ArtRequest(**base.to_dict())
        req.series_context = dict(ctx)
        req.card_id = int(card.id or req.card_id or 0)
        req.archetype = str(arch.name or req.archetype or "")
        req.subject = (card.display_name or card.name or req.subject)
        req.seed = bump_seed(base_seed, i + 1) if i else base_seed

        def _cb(info, i=i):
            if on_progress:
                try:
                    on_progress({**info, "index": i, "total": total,
                                 "card_id": int(cards[i].id or 0),
                                 "name": cards[i].display_name})
                except Exception:  # pragma: no cover
                    pass
        res = generate(req, card=card, on_progress=_cb, client=cli)
        if i == 0 and res.meta.get("series_style"):
            ctx[PR.SERIES_STYLE_KEY] = res.meta["series_style"]
            base.series_context = dict(ctx)
        results.append(res)
    return results


# ══════════════════════════════════════════════════════════════════════
#  本地后处理（Pillow，不经过 ComfyUI）
# ══════════════════════════════════════════════════════════════════════
def postprocess(src: str, *, target: tuple[int, int] | None = None,
                scale: float = 0.0, method: str = "lanczos",
                flatten: bool = False, background: str = "#FFFFFF",
                out: str = "") -> dict:
    """本地 Pillow 后处理：精确降采样 / 等比缩放 / 透明图合成到纯色底。

    为什么需要它：ComfyUI 的 ``ImageUpscaleWithModel`` 只能按模型倍率放大
    （通常 4x），落到交付尺寸必须再接 ``ImageScale``；而**已经出好的图**
    想重新落到 421×614 / 842×1228 时，不该再跑一次 GPU —— 这里直接做。

    :param src: 源图路径。
    :param target: 目标 ``(w, h)``；不给就按 ``scale`` 等比缩放。
    :param scale: 等比倍率（``target`` 为空时生效）。
    :param method: 重采样方式：放大用 ``lanczos``，缩小用 ``area``。
    :param flatten: ``True`` 时把 alpha 合成到 ``background`` 纯色底（EDOPro 的 JPG 卡图需要）。
    :param out: 输出路径；不给则在源图旁写 ``<name>_pp.png``。
    :return: ``{"ok","src","dst","size","mode","bytes"}``
    """
    from PIL import Image

    s = Path(src)
    if not s.exists():
        raise ComfyError(f"后处理的源图不存在：{s}", "检查路径。", kind="bad_prompt")
    resample = {"nearest": Image.NEAREST, "nearest-exact": Image.NEAREST,
                "bilinear": Image.BILINEAR, "bicubic": Image.BICUBIC,
                "area": Image.BOX, "lanczos": Image.LANCZOS}.get(
                    str(method).lower(), Image.LANCZOS)
    with Image.open(s) as im:
        img = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
        if target:
            tw, th = int(target[0]), int(target[1])
        elif scale:
            tw, th = max(1, round(img.width * float(scale))), \
                     max(1, round(img.height * float(scale)))
        else:
            tw, th = img.size
        if (tw, th) != img.size:
            img = img.resize((tw, th), resample)
        if flatten and img.mode == "RGBA":
            bg = Image.new("RGB", img.size, background)
            bg.paste(img, mask=img.split()[-1])
            img = bg
        dst = Path(out) if out else s.with_name(f"{s.stem}_pp.png")
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, "PNG" if img.mode == "RGBA" else "JPEG",
                 quality=95, **({} if img.mode == "RGBA" else {"subsampling": 0}))
    return {"ok": True, "src": str(s.resolve()), "dst": str(dst.resolve()),
            "size": [tw, th], "mode": img.mode, "bytes": dst.stat().st_size}


# ══════════════════════════════════════════════════════════════════════
#  导出工作流
# ══════════════════════════════════════════════════════════════════════
class PlaceholderRef(ComfyError):
    """导出的工作流里还留着**占位图片名**，无法直接提交。

    这是 :func:`export_workflow` 的 ``submit=True`` 分支的专用错误 ——
    导出本身是成功的（占位符正是为了让用户导入后自己替换），
    只是「就地跑一遍」这一步缺图。
    """

    def __init__(self, message: str, hint: str, detail: dict | None = None) -> None:
        super().__init__(message, hint, kind="model_missing", detail=detail)


#: 会被当成「占位符」的图片名（都不带子目录，因为它们是假的）
PLACEHOLDER_IMAGES = ("cardforge_style_ref.png", "cardforge_style_anchor.png",
                      "cardforge_input.png", "cardforge_mask.png")


def _upload_refs(cli: ComfyClient, req: ArtRequest) -> dict:
    """把请求里的本地参考图上传到 ComfyUI，返回 ``{本地路径: 服务器引用}``。"""
    out: dict[str, str] = {}
    for local in list(getattr(req, "style_refs", None) or []):
        p = Path(str(local))
        if p.exists():
            try:
                info = cli.upload(str(p), subfolder="CardForge")
                out[str(local)] = info.get("ref") or info.get("name") or str(local)
            except ComfyError:
                pass
    return out


def export_workflow(preset: str, path: str, *, profile: str = "auto",
                    spec: CardSpec | None = None, host: str = DEFAULT_HOST,
                    request: ArtRequest | None = None,
                    submit: bool = False,
                    images: dict | None = None) -> str:
    """导出**可直接导入 ComfyUI** 的工作流 JSON（UI 格式），并在同目录写说明。

    :param preset: :data:`cardforge.art.presets.PRESETS` 的键。
    :param path: 目标 ``.json`` 路径。
    :param profile: 档案键或 ``"auto"``。
    :param spec: 卡牌规格（决定卡种氛围词与画布比例）。
    :param request: 自定义请求（覆盖 ``spec`` 推导出的提示词）。
        它的 ``style_refs`` 会被**自动上传**并替换掉占位图名。
    :param submit: ``True`` 时顺手把它转回 API 格式**提交一次做真验证**
        （默认 ``False``，因为这会真的占用显存出一张图）。
        注意：占位图名（``cardforge_*.png``）**不能提交** ——
        这一步必须给出真实存在的参考图（走 ``request.style_refs`` 或 ``images``），
        否则抛 :class:`PlaceholderRef`。
    :param images: ``{本地路径: 服务器引用}`` 映射；给了就不再自动上传。
    :return: 写出的 JSON 路径。
    :raises KeyError: 预设不存在。
    :raises ComfyError: 建图失败（缺节点 / 缺模型）。
    :raises PlaceholderRef: ``submit=True`` 但工作流里还是占位图名。
    """
    p = PS.preset(preset)                       # 不存在会抛 KeyError
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cli = ComfyClient(host=host)
    online = cli.alive()
    models = cli.models() if online else {}
    schemas = cli.object_info() if online else {}
    prof = resolve_profile(profile, models, host)

    req = request or ArtRequest(preset=preset, profile=prof.key,
                                archetype=(spec.archetype if spec else ""),
                                card_id=int(spec.id if spec else 0),
                                subject=(spec.display_name if spec else ""))
    req.preset = preset
    pr = PR.build(req, spec, prof, None)
    frame = (spec.frame if spec is not None else "effect")
    width, height = PF.art_size_for(frame, prof, int(req.width or 0), int(req.height or 0))
    defaults = p.get("defaults") or {}
    if preset == "character_sheet":
        width = int(defaults.get("width", 1536))
        height = int(defaults.get("height", 1024))
        pr["positive"] = str(defaults.get("positive") or pr["positive"])
        pr["negative"] = str(defaults.get("negative") or pr["negative"])

    steps = int(req.steps or prof.steps)
    cfg = float(req.cfg or prof.cfg)
    sampler = req.sampler or prof.sampler
    scheduler = req.scheduler or prof.scheduler
    seed = int(req.seed) if int(req.seed) >= 0 else new_seed()
    name, clip, vae = _pick_model(prof, models) if online else _offline_models(prof)
    up_model = _pick_upscale_model(models) if preset == "upscale" else ""
    av = set(schemas.keys()) if online else None
    sc = schemas or None

    # 参考图：先把本地文件上传，得到服务器引用；没有就给占位名（导出仍可用）
    img_map = dict(images or {})
    if online and not img_map:
        img_map = _upload_refs(cli, req)
    style_refs = [img_map.get(str(x), str(x)) for x in (req.style_refs or [])] or \
        ["cardforge_style_ref.png"]
    anchor = img_map.get(str((req.style_refs or [""])[0]), "cardforge_style_anchor.png")

    if preset == "remove_bg":
        img = str((defaults or {}).get("image") or "cardforge_input.png")
        g = G.build_remove_bg(image=img, model=str(defaults.get("model") or ""),
                              available=av, schemas=sc,
                              local_models=list(models.get("background_removal") or []))
    elif preset == "upscale":
        img = str((defaults or {}).get("image") or "cardforge_input.png")
        tgt = tuple(defaults.get("target") or G.TARGET_2X)
        g = G.build_upscale(graph_or_image=img,
                            upscale_model=up_model or str(defaults.get("upscale_model") or ""),
                            target=tgt, available=av, schemas=sc)
    elif preset == "ipadapter_consistency":
        g = G.build_ipadapter(profile=prof, ckpt_or_unet=name, clip=clip, vae=vae,
                              positive=pr["positive"], negative=pr["negative"],
                              width=width, height=height, seed=seed, steps=steps,
                              cfg=cfg, sampler=sampler, scheduler=scheduler,
                              ref_images=[anchor], images=img_map,
                              clip_vision="", available=av, schemas=sc)
    elif preset == "style_ref":
        g = G.build_style_ref(profile=prof, ckpt_or_unet=name, clip=clip, vae=vae,
                              positive=pr["positive"], negative=pr["negative"],
                              width=width, height=height, seed=seed, steps=steps,
                              cfg=cfg, sampler=sampler, scheduler=scheduler,
                              style_refs=style_refs, images=img_map,
                              strength=float(defaults.get("strength", 1.0)),
                              available=av, schemas=sc)
    elif preset == "inpaint_edit":
        g = G.build_inpaint_edit(profile=prof, ckpt_or_unet=name, clip=clip, vae=vae,
                                 image="cardforge_input.png",
                                 mask="cardforge_mask.png",
                                 instruction=pr["positive"], negative=pr["negative"],
                                 width=width, height=height, seed=seed, steps=steps,
                                 cfg=cfg, sampler=sampler, scheduler=scheduler,
                                 denoise=float(defaults.get("denoise", 0.6)),
                                 available=av, schemas=sc)
    else:
        g = G.build_t2i(profile=prof, ckpt_or_unet=name, clip=clip, vae=vae,
                        positive=pr["positive"], negative=pr["negative"],
                        width=width, height=height, seed=seed, steps=steps, cfg=cfg,
                        sampler=sampler, scheduler=scheduler, loras=list(req.loras or []),
                        save_prefix=f"cardforge/{preset}", available=av, schemas=sc,
                        upscale=bool(req.upscale), upscale_model=up_model,
                        remove_bg=bool(req.remove_bg),
                        local_bg_models=list(models.get("background_removal") or []))

    cf_meta = {
        "version": "cardforge.art 1.0",
        "preset": preset,
        "preset_zh": p.get("zh", preset),
        "profile": prof.key, "profile_zh": prof.zh, "chain": prof.chain,
        "model": name, "clip": clip, "vae": vae,
        "seed": seed, "size": [width, height], "steps": steps, "cfg": cfg,
        "sampler": sampler, "scheduler": scheduler,
        "fingerprint": g.fingerprint(),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "warnings": list(g.warnings),
        "positive": pr["positive"],
        "negative": pr["negative"],
    }
    # 先序列化一遍，才能知道图里还留着哪些占位图片名
    placeholders = [x for x in PLACEHOLDER_IMAGES if x in json.dumps(g.to_ui(meta=cf_meta))]
    cf_meta["placeholders"] = placeholders
    ui = g.to_ui(meta=cf_meta)
    out.write_text(json.dumps(ui, ensure_ascii=False, indent=2), encoding="utf-8")

    # 同目录写一份 README（说明怎么用、要哪些模型、参数含义）
    readme = out.with_name(f"README_{_ascii(preset)}.md")
    readme.write_text(_readme_text(preset, p, prof, ui, g, name, clip, vae,
                                   pr, width, height, steps, cfg, online,
                                   json_name=out.name),
                      encoding="utf-8")

    if submit and online:
        api = G.ui_to_api(ui, schemas)
        problems = G.validate(api, schemas)
        if problems:
            raise ComfyError("导出的工作流自检未通过：" + "；".join(problems),
                             "按提示修正后重新导出。", kind="bad_prompt",
                             detail={"problems": problems})
        placeholders = ui["extra"]["cardforge"].get("placeholders") or []
        if placeholders:            raise PlaceholderRef(
                "导出的工作流里还有占位图片名，无法直接提交：" + "、".join(placeholders),
                "导出本身成功了 —— 这些占位符是给用户导入后自己换图的。"
                "要在这里就地跑一遍验证，请把真实图片传进来："
                "① export_workflow(..., request=ArtRequest(style_refs=['D:/x.png'])) "
                "（本地路径会被自动 upload）；② 或直接给 images={'D:/x.png': "
                "'CardForge/x.png'}。t2i_single / character_sheet 这类不需要参考图的"
                "预设可以直接 submit=True。",
                detail={"placeholders": placeholders, "json": str(out)})
        cli.queue(api)
    return str(out.resolve())


def _offline_models(profile: ModelProfile) -> tuple[str, str, str]:
    """离线导出时给占位模型名（用户导入到自己的 ComfyUI 后自己改）。"""
    ex = profile.extras or {}
    if profile.chain == "krea2":
        return ("krea2_turbo_bf16.safetensors",
                "qwen3vl_4b_fp8_scaled.safetensors", "qwen_image_vae.safetensors")
    if profile.chain == "qwen":
        return ("qwen_image_2.1_int8_convrot.safetensors",
                str(ex.get("text_encoder_t2i")
                    or "qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors"),
                str(ex.get("vae") or "qwen_image_2.1_vae_bf16.safetensors"))
    return ("model.safetensors", "", "")


def _ascii(name: str) -> str:
    """把预设名转成 ASCII 安全的文件名片段（避免控制台/工具链编码问题）。"""
    s = "".join(c if (c.isascii() and (c.isalnum() or c in "-_")) else "_"
                for c in str(name))
    return s.strip("_") or "workflow"


def _readme_text(preset: str, p: dict, prof: ModelProfile, ui: dict, g: G.Graph,
                 name: str, clip: str, vae: str, pr: dict, width: int, height: int,
                 steps: int, cfg: float, online: bool, json_name: str = "") -> str:
    """生成配套 README（中文）。"""
    lines: list[str] = []
    A = lines.append
    A(f"# {p.get('zh', preset)} —— ComfyUI 工作流使用说明")
    A("")
    A(f"> 由 **CardForge `cardforge.art`** 自动生成。工作流文件：`{json_name or '(见同目录 .json)'}`")
    A("")
    A("## 1. 怎么用")
    A("")
    A("1. 打开 ComfyUI（本机默认 `http://127.0.0.1:8188`）。")
    A(f"2. 把 `{json_name or 'workflow.json'}` **直接拖进 ComfyUI 画布**"
      "（或菜单 Workflow → Open 选中它）。")
    A("3. 检查三个 Loader 节点的下拉值是否是**你本机实际有**的模型"
      "（见下面「需要的模型」一节）。下拉里选不到 = 文件不在对应目录。")
    if preset in ("style_ref", "ipadapter_consistency"):
        A("4. 把工作流里的 `cardforge_style_ref.png` / `cardforge_style_anchor.png` "
          "占位图换成你自己的参考图（先拖进 ComfyUI 的 input 目录，"
          "或在 LoadImage 节点上点 choose file 上传）。")
    elif preset in ("upscale", "remove_bg", "inpaint_edit"):
        A("4. 把工作流里的 `cardforge_input.png`（以及 `cardforge_mask.png`）"
          "换成你自己的图 —— 直接拖进 ComfyUI 的 input 目录即可。")
    else:
        A("4. 直接点 **Queue** 就能出图。")
    A(f"5. 想复现当前这张：seed 已经固定为 `{ui['extra']['cardforge'].get('seed')}`，"
      "`control_after_generate` 保持 `fixed` 就是同一张；"
      "改成 `randomize` 才会每跑一次换一张。")
    A("")
    A("## 2. 用途")
    A("")
    A(f"{p.get('use', '')}")
    A("")
    A("## 3. 需要的模型")
    A("")
    A(f"- 档案：**{prof.zh}**（键 `{prof.key}`，链路 `{prof.chain}`）")
    if prof.chain in ("krea2", "qwen", "flux"):
        A(f"- 扩散模型 `UNETLoader.unet_name` = `{name}`  → 放 `ComfyUI/models/diffusion_models/`")
        A(f"- 文本编码器 `CLIPLoader.clip_name` = `{clip}`，"
          f"**type = `{(prof.extras or {}).get('clip_type', 'krea2')}`**  → 放 `ComfyUI/models/text_encoders/`")
        A(f"- VAE `VAELoader.vae_name` = `{vae}`  → 放 `ComfyUI/models/vae/`")
        A("")
        A("> ⚠️ **`CLIPLoader.type` 必须是 `krea2`（Krea 2 链路）**，写错必失败。")
    else:
        A(f"- checkpoint `CheckpointLoaderSimple.ckpt_name` = `{name}`  → 放 `ComfyUI/models/checkpoints/`")
        if prof.clip_skip:
            A(f"- 需要 `CLIPSetLastLayer(stop_at_clip_layer={prof.clip_skip})`"
              "（本工作流已内建）")
    for extra_need in (p.get("needs") or {}).get("models") or []:
        A(f"- {extra_need}")
    A("")
    A("## 4. 参数含义（当前值 → 怎么调）")
    A("")
    A(f"| 参数 | 当前值 | 含义 / 调整建议 |")
    A(f"|---|---|---|")
    A(f"| 画布 | {width}×{height} | 卡图窗比例 0.68567；832×1216 误差仅 0.21%。"
      "改尺寸请取 **16 的倍数**。|")
    A(f"| steps | {steps} | "
      + ("Krea 2 是 8 步蒸馏模型，**别加步数**（会更糊更慢），想更清晰就升画布。"
         if prof.distilled else "SDXL/SD1.5 常规 20–30 步。")
      + " |")
    A(f"| cfg | {cfg} | "
      + ("**必须 1.0，不能设 0**（设 0 ComfyUI 会直接失败）。"
         "cfg=1 时**负向提示词基本不生效** —— 要排除的东西已写进正向描述。"
         if not prof.negative_effective else "SDXL/SD1.5 常规 5–7。")
      + " |")
    A(f"| sampler | `{ui['extra']['cardforge'].get('sampler')}` | "
      "流匹配系用 euler 家族；Karras 调度器在流匹配模型上会直接失败。 |")
    A(f"| scheduler | `{ui['extra']['cardforge'].get('scheduler')}` | "
      "Krea 2 / Qwen-Image 用 `simple`；SDXL/SD1.5 常用 `normal` 或 `karras`。 |")
    A(f"| seed | `{ui['extra']['cardforge'].get('seed')}` | "
      "**IS_CHANGED 缓存坑**：seed 与参数都不变时 ComfyUI 会判定 cache hit，"
      "直接复用旧输出文件而**不重新生成**。要出新图就换 seed。 |")
    if prof.clip_skip:
        A(f"| CLIP skip | {prof.clip_skip} | `CLIPSetLastLayer.stop_at_clip_layer`，该档案的硬要求。 |")
    A("")
    A("## 5. 提示词（当前正向 / 负向）")
    A("")
    A("**正向**")
    A("")
    A("```text")
    A(pr["positive"])
    A("```")
    A("")
    A("**负向**")
    A("")
    A("```text")
    A(pr["negative"])
    A("```")
    A("")
    if not prof.negative_effective:
        A(f"> ⚠️ 负向在 `cfg={cfg}` 下**不参与计算**（那一遍前向不跑），"
          "上面这段只是留给你手动调高 cfg 时用。")
        A("")
    A("## 6. 授权要点")
    A("")
    A(prof.notes)
    A("")
    A("## 7. 节点结构（共 %d 个节点 / %d 条连线）" % (len(g.nodes), len(g.edges)))
    A("")
    A("```text")
    for nid in g.nodes:
        node = g.nodes[nid]
        A(f"  [{nid}] {node['class_type']}")
    A("```")
    A("")
    A(f"工作流指纹（**忽略 seed**）：`{g.fingerprint()}`")
    A("")
    if g.warnings:
        A("## 8. 降级警告")
        A("")
        for w in g.warnings:
            A(f"- {w}")
        A("")
    A("## 9. 排障")
    A("")
    A("| 症状 | 处理 |")
    A("|---|---|")
    A("| 下拉里选不到模型 | 文件不在 `ComfyUI/models/<对应目录>/`；放进去后在界面点一次刷新 |")
    A("| 提交即报 400 | 多半是 `class_type` 拼错或 COMBO 值不在候选里；看 `node_errors` 指出的节点 |")
    A("| 重跑还是同一张 | `IS_CHANGED` 缓存：换 seed，或改 `filename_prefix` |")
    A("| 图上有文字/水印 | Krea 2 在 cfg=1 下负向无效 → 把「画面里没有任何文字」写进**正向** |")
    A("| 显存不足 | 降画布 → 去掉大 LoRA → `POST /free {\"unload_models\":true}` |")
    A("")
    A(f"*导出时 ComfyUI {'在线' if online else '**不在线**'}——"
      + ("工作流已按本机实际模型与节点填写。" if online else
         "模型名是**占位值**，导入后请自行改成你本机有的。") + "*")
    A("")
    return "\n".join(lines)


__all__ = [
    "generate", "generate_series", "export_workflow", "capabilities", "probe",
    "resolve_profile", "postprocess", "PlaceholderRef", "PLACEHOLDER_IMAGES",
    "ENHANCEMENT_NODES", "UPSCALE_PREFER", "CLIP_PREFER", "VAE_PREFER",
    "DEFAULT_HOST",
]
