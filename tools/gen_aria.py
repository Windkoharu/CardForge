"""星奏·艾莉娅 —— 立绘与表情差分的生成脚本（可复现）。

为什么要单独一个脚本，而不是走 ``cardforge art`` 那条路
--------------------------------------------------------
``cardforge art`` 是**卡图**流水线（832×1216、按卡种氛围词起手）。
艾莉娅的立绘是**界面素材**：她需要 6 张表情差分（同一角色、只换表情）、
一张横幅、一张头像 —— 这些不该塞进卡图档案里，但**出图链路必须与项目一致**：
krea2 档案（UNETLoader + CLIPLoader(type=krea2) + ModelSamplingFlux(1.15) +
CFGGuider(1.0) + SamplerCustomAdvanced(euler/simple/8 步) + VAEDecode）。

抠底用 ComfyUI-RMBG 的 BiRefNet_lite（背景 = Alpha 直出透明 PNG），
模型在 ``models/RMBG/BiRefNet/``（hf-mirror 下载，见 docs/04）。

产出（写入 data/assets/aria/，并镜像到 web/assets/aria/）：
    aria_full.png      全身立绘（透明）
    aria_guide/working/alert/pass/think/surprise.png   半身表情差分（透明）
    aria_banner.png    顶部横幅（带工坊背景，不抠底）
    aria_avatar.png    头像 512×512（由 guide 差分裁出）
    manifest.json      提示词 / seed / 尺寸 / 时间（复现凭据）

用法::

    python tools/gen_aria.py --preset all          # 全部重生成
    python tools/gen_aria.py --preset expr         # 只重出表情差分
    python tools/gen_aria.py --preset avatar       # 只重新裁头像（不跑模型）
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_NATIVE = ROOT / "data" / "assets" / "aria"
OUT_WEB = ROOT / "web" / "assets" / "aria"
COMFY = "http://127.0.0.1:8188"

# ── krea2 档案常量（与 cardforge/art/profiles.py 的 krea2 档案一致）────────
UNET = "krea2_turbo_bf16.safetensors"
CLIP = "qwen3vl_4b_fp8_scaled.safetensors"
CLIP_TYPE = "krea2"
VAE = "qwen_image_vae.safetensors"
STEPS, CFG, SAMPLER, SCHEDULER = 8, 1.0, "euler", "simple"
MAX_SHIFT, BASE_SHIFT = 1.15, 0.5

SEED = 20261014
BANNER_SEED = 20261015

# ══════════════════════════════════════════════════════════════════════
#  角色身份块 —— 六张差分与全身像共用同一段，这是「同一个人」的锚
#  （cfg=1.0 时负向不生效：所有「不要什么」都必须写进正向）
# ══════════════════════════════════════════════════════════════════════
IDENTITY = (
    "Anime illustration of Aria (星奏·艾莉娅), a card-crafting forge-spirit artisan, "
    "a young woman in her early twenties, clean crisp lineart and soft cel shading, "
    "polished official key-visual quality for a desktop app mascot. "
    "She has long silver-white hair with warm golden tips flowing past her waist, "
    "tied in a loose low side ponytail on her right with a brass rhombus hairpin "
    "shaped like a trading-card back emblem, and a tiny golden star hairclip above "
    "her left ear. Amber-gold eyes with soft star-like highlights, delicate features. "
    "She wears a dark walnut-brown leather workshop jacket with the sleeves rolled up "
    "over a parchment-cream shirt, a small brass triangle badge at her collar, a dark "
    "leather craft apron with thin golden rhombus embroidery, fingerless brown gloves, "
    "a sturdy tool belt with brass calipers and a carving stylus, and a small softly "
    "glowing card-shaped pendant on her chest. Color palette: brass gold, dark walnut "
    "brown, parchment cream, faint stardust-blue glow. A few translucent glowing "
    "trading cards float slowly around her. Warm rim light, soft shadows. "
    "The image contains no text, no letters, no watermark, no logo, no signature, "
    "no UI elements. She is the calm, earnest assistant of a card-forging workshop: "
    "she never judges, she only translates the rules into human words."
)

FULL = IDENTITY + (
    " Composition: full body standing pose, entire figure from head to boots visible, "
    "facing the viewer at a slight three-quarter angle, one hand resting on her belt, "
    "the other holding a half-finished glowing card. Plain flat neutral warm-gray "
    "studio background, soft even lighting."
)

EXPRS: dict[str, str] = {
    "guide": " Expression: a calm gentle smile, one hand open in a welcoming gesture, "
             "as if inviting the viewer to proceed.",
    "working": " Expression: focused and concentrated, eyes fixed ahead as if watching "
               "a progress bar, holding a fine brass carving stylus, small determined smile.",
    "alert": " Expression: a raised eyebrow and a serious warning look, one index finger "
             "raised, lips pressed in a firm line.",
    "pass": " Expression: a relieved satisfied smile, giving a small approving nod, "
            "eyes closed gently in a happy arc.",
    "think": " Expression: thoughtful, eyes looking up to the side, one hand raised to "
             "her chin, head slightly tilted.",
    "surprise": " Expression: wide surprised eyes, slightly parted lips, leaning back a "
                "little, one hand raised in mild startle.",
}
EXPR_FRAME = (
    " Composition: upper body portrait framing from head to waist, facing the viewer, "
    "plain flat neutral warm-gray studio background, soft even lighting."
)

BANNER = (
    "Wide cinematic anime banner illustration, wallpaper quality. Aria (星奏·艾莉娅), "
    "a silver-haired card-crafting forge-spirit artisan with warm golden hair tips and "
    "amber-gold eyes, wearing a dark walnut-brown leather workshop jacket and a dark "
    "leather craft apron with golden rhombus embroidery, stands at the right side of "
    "the frame in a warm artisan workshop at night, leaning over a wooden workbench "
    "covered with softly glowing blank trading cards, brass tools and a small anvil. "
    "Behind her: dark wooden shelves stacked with framed trading cards, warm amber "
    "lantern light, drifting stardust motes and a few translucent glowing cards "
    "floating in the air. The left half of the wide frame is calm empty workshop "
    "space with soft bokeh, reserved as negative space for interface text. "
    "Clean lineart, soft cel shading, warm inviting mood, high detail. "
    "The image contains no text, no letters, no watermark, no logo, no signature."
)


# ══════════════════════════════════════════════════════════════════════
#  ComfyUI API 客户端（只依赖标准库）
# ══════════════════════════════════════════════════════════════════════
def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        COMFY + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path: str) -> dict:
    with urllib.request.urlopen(COMFY + path, timeout=60) as r:
        data = r.read()
        return json.loads(data.decode("utf-8")) if data[:1] in (b"{", b"[") else {}


def build_graph(prompt: str, width: int, height: int, seed: int, *,
                cutout: bool, prefix: str) -> dict:
    """krea2 链路（与 profiles.py 档案逐参数一致）+ 可选 BiRefNet 抠底。"""
    g: dict = {}
    g["1"] = {"class_type": "UNETLoader",
              "inputs": {"unet_name": UNET, "weight_dtype": "default"}}
    g["2"] = {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": CLIP_TYPE, "device": "default"}}
    g["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": VAE}}
    g["4"] = {"class_type": "ModelSamplingFlux",
              "inputs": {"model": ["1", 0], "max_shift": MAX_SHIFT,
                         "base_shift": BASE_SHIFT, "width": width, "height": height}}
    g["5"] = {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["2", 0], "text": prompt}}
    g["6"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}}
    g["7"] = {"class_type": "CFGGuider",
              "inputs": {"model": ["4", 0], "positive": ["5", 0],
                         "negative": ["6", 0], "cfg": CFG}}
    g["8"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}}
    g["9"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": SAMPLER}}
    g["10"] = {"class_type": "BasicScheduler",
               "inputs": {"model": ["4", 0], "scheduler": SCHEDULER,
                          "steps": STEPS, "denoise": 1.0}}
    g["11"] = {"class_type": "EmptyLatentImage",
               "inputs": {"width": width, "height": height, "batch_size": 1}}
    g["12"] = {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["8", 0], "guider": ["7", 0], "sampler": ["9", 0],
                          "sigmas": ["10", 0], "latent_image": ["11", 0]}}
    g["13"] = {"class_type": "VAEDecode",
               "inputs": {"samples": ["12", 0], "vae": ["3", 0]}}
    tail = ["13", 0]
    if cutout:
        g["14"] = {"class_type": "BiRefNetRMBG",
                   "inputs": {"image": ["13", 0], "model": "BiRefNet_lite",
                              "sensitivity": 1.0, "mask_blur": 0, "mask_offset": 0,
                              "invert_output": False, "refine_foreground": True,
                              "background": "Alpha"}}
        tail = ["14", 0]
    g["15"] = {"class_type": "SaveImage",
               "inputs": {"images": tail, "filename_prefix": prefix}}
    return g


def run_one(name: str, prompt: str, width: int, height: int, seed: int, *,
            cutout: bool) -> Path:
    prefix = f"aria/{name}"
    g = build_graph(prompt, width, height, seed, cutout=cutout, prefix=prefix)
    res = _post("/prompt", {"prompt": g})
    pid = res.get("prompt_id")
    if not pid:
        raise RuntimeError(f"提交失败：{res}")
    print(f"  · {name}: 已提交（{width}×{height} seed={seed} "
          f"{'抠底' if cutout else '原图'}）pid={pid[:8]}")
    t0 = time.time()
    while True:
        time.sleep(2)
        h = _get(f"/history/{pid}")
        item = h.get(pid)
        if item and item.get("outputs"):
            images = []
            for node in item["outputs"].values():
                images.extend(node.get("images") or [])
            if not images:
                raise RuntimeError(f"{name}: 完成但没有任何输出图")
            info = images[-1]
            q = urllib.parse.urlencode({"filename": info["filename"],
                                        "subfolder": info.get("subfolder", ""),
                                        "type": info.get("type", "output")})
            with urllib.request.urlopen(COMFY + "/view?" + q, timeout=120) as r:
                data = r.read()
            OUT_NATIVE.mkdir(parents=True, exist_ok=True)
            dest = OUT_NATIVE / f"{name}.png"
            dest.write_bytes(data)
            print(f"  ✓ {name}: {dest.name}（{len(data)/1024:.0f} KB，"
                  f"{time.time()-t0:.0f}s）")
            return dest
        st = _get(f"/queue")
        if not any(pid in json.dumps(x) for x in (st.get("queue_running") or [])
                   + (st.get("queue_pending") or [])):
            # 历史里还没有、队列里也没有 —— 可能刚被清或失败
            h2 = _get(f"/history/{pid}")
            if pid not in h2:
                raise RuntimeError(f"{name}: 任务从队列消失且无历史（看 ComfyUI 控制台）")
        if time.time() - t0 > 900:
            raise RuntimeError(f"{name}: 超时（15 分钟）")


# ══════════════════════════════════════════════════════════════════════
#  后处理：头像裁剪 + 镜像到 web/
# ══════════════════════════════════════════════════════════════════════
def make_avatar() -> Path:
    from PIL import Image
    src = OUT_NATIVE / "aria_guide.png"
    if not src.exists():
        src = OUT_NATIVE / "aria_full.png"
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    # 头部在画面上方约 8%~34%：取一个居中的方框再放大
    side = int(w * 0.42)
    left = max(0, (w - side) // 2)
    top = int(h * 0.055)
    box = im.crop((left, top, left + side, top + side)).resize((512, 512), Image.LANCZOS)
    dest = OUT_NATIVE / "aria_avatar.png"
    box.save(dest)
    print(f"  ✓ avatar: {dest.name}（由 {src.name} 裁出）")
    return dest


def mirror_web() -> None:
    OUT_WEB.mkdir(parents=True, exist_ok=True)
    for p in sorted(OUT_NATIVE.glob("*.png")):
        shutil.copy2(p, OUT_WEB / p.name)
    print(f"  ✓ 已镜像 {len(list(OUT_WEB.glob('*.png')))} 张到 {OUT_WEB}")


# ══════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="生成星奏·艾莉娅的立绘与表情差分")
    ap.add_argument("--preset", default="all",
                    choices=["all", "full", "expr", "banner", "avatar"])
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    try:
        _get("/system_stats")
    except Exception as e:
        print(f"[X] ComfyUI 不在线（{COMFY}）：{e}")
        return 1

    manifest: dict = {"generated_at": datetime.now(timezone.utc).isoformat(),
                      "chain": {"unet": UNET, "clip": CLIP, "clip_type": CLIP_TYPE,
                                "vae": VAE, "steps": STEPS, "cfg": CFG,
                                "sampler": SAMPLER, "scheduler": SCHEDULER,
                                "max_shift": MAX_SHIFT, "base_shift": BASE_SHIFT,
                                "cutout": "BiRefNet_lite (ComfyUI-RMBG, Alpha)"},
                      "identity": IDENTITY, "items": {}}
    mf = OUT_NATIVE / "manifest.json"
    if mf.exists():
        try:
            manifest.update({k: v for k, v in json.loads(
                mf.read_text(encoding="utf-8")).items() if k == "items"})
        except Exception:
            pass

    errs = 0

    def try_run(name, prompt, w, h, seed, cutout=True):
        nonlocal errs
        try:
            run_one(name, prompt, w, h, seed, cutout=cutout)
            manifest["items"][name] = {"prompt": prompt, "width": w, "height": h,
                                       "seed": seed, "cutout": cutout}
        except Exception as e:
            errs += 1
            print(f"  [X] {name}: {e}")

    if args.preset in ("all", "full"):
        print("生成全身立绘…")
        try_run("aria_full", FULL, 832, 1216, args.seed)
    if args.preset in ("all", "expr"):
        print("生成 6 张表情差分…")
        for key, expr in EXPRS.items():
            try_run(f"aria_{key}", IDENTITY + expr + EXPR_FRAME, 832, 1216, args.seed)
    if args.preset in ("all", "banner"):
        print("生成横幅…")
        try_run("aria_banner", BANNER, 1536, 640, BANNER_SEED, cutout=False)

    if args.preset in ("all", "avatar") or (
            args.preset in ("all", "expr") and not errs):
        print("裁头像…")
        try:
            make_avatar()
            manifest["items"]["aria_avatar"] = {
                "from": "aria_guide.png", "size": [512, 512]}
        except Exception as e:
            errs += 1
            print(f"  [X] avatar: {e}")

    mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    print(f"manifest: {mf}")
    try:
        mirror_web()
    except Exception as e:
        print(f"  [X] 镜像失败：{e}")
    print("完成。" if not errs else f"完成但有 {errs} 项失败。")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
