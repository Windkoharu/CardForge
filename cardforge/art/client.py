"""ComfyUI HTTP 客户端 —— **只用标准库 urllib**。

设计要点
--------
1. **模型探测的唯一正确方式**：读 ``/object_info`` 里各 Loader 节点的 COMBO 候选
   （``input.required.<参数名>[0]``）。**不要依赖 ``/models``** —— 那个端点在不同
   自托管版本上行为不一致，而 ``/object_info`` 是已验证的一手数据源。
2. **``/view`` 必须带 ``subfolder``**。``SaveImage`` 的 ``filename_prefix`` 写了
   ``cardforge/art`` 之后，history 返回的 ``filename`` 只有 ``xxx_00001_.png``，
   ``subfolder`` 才是 ``cardforge/art`` —— 漏传直接 404。
3. **错误分类**：把 ComfyUI 的各种失败归到 ``ComfyError(kind=...)`` 的六类
   （``offline`` / ``node_missing`` / ``model_missing`` / ``oom`` / ``timeout`` /
   ``bad_prompt``），每类都给**可执行的中文 hint**。
4. **IS_CHANGED 缓存坑**：``seed`` 不变时 ComfyUI 会判定节点 cache hit，
   **直接复用旧输出文件而不重新生成**。批量出图必须每张换 seed，见 :func:`bump_seed`。
"""
from __future__ import annotations

import json
import mimetypes
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from ..core.errors import ComfyError

DEFAULT_HOST = "http://127.0.0.1:8188"

#: ``models()`` 覆盖的模型类别 → (Loader 节点, 参数名)
MODEL_SOURCES: dict[str, tuple[str, str]] = {
    "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
    "unets": ("UNETLoader", "unet_name"),
    "diffusion_models": ("UNETLoader", "unet_name"),
    "loras": ("LoraLoaderModelOnly", "lora_name"),
    "vaes": ("VAELoader", "vae_name"),
    "clips": ("CLIPLoader", "clip_name"),
    "upscale": ("UpscaleModelLoader", "model_name"),
    "controlnet": ("ControlNetLoader", "control_net_name"),
    "clip_vision": ("CLIPVisionLoader", "clip_name"),
    "ipadapter": ("IPAdapterModelLoader", "ipadapter_file"),
    # 核心抠底节点（0.3.x 自带）的参数名是 bg_removal_name，不是 model
    "background_removal": ("LoadBackgroundRemovalModel", "bg_removal_name"),
}

# ══════════════════════════════════════════════════════════════════════
#  进程级 /object_info 缓存
# ══════════════════════════════════════════════════════════════════════
#: ``GET /object_info`` 在本机实测是 **3.3 MB / 16 秒** —— 每次 generate() 都重拉一次
#: 会让「出图 8 秒、探测 16 秒」本末倒置。而它在 ComfyUI 运行期间是稳定的
#: （只有当插件/模型变化时才会变），所以做**进程级共享缓存**。
#: TTL 之内直接用；超时后仍会用旧的（并在后台语义上标记需要刷新），
#: 只有 ``invalidate_object_info()`` 才真的丢掉。
_OBJECT_INFO_CACHE: dict = {"host": "", "data": None, "ts": 0.0}
OBJECT_INFO_TTL = 900.0          # 15 分钟

#: 节点类名 → UI 上的显示名（报错时给用户看人话）
NODE_DISPLAY: dict[str, str] = {
    "UNETLoader": "Load Diffusion Model（加载扩散模型）",
    "CheckpointLoaderSimple": "Load Checkpoint（加载 checkpoint）",
    "CLIPLoader": "Load CLIP（加载文本编码器）",
    "DualCLIPLoader": "Load Dual CLIP",
    "VAELoader": "Load VAE",
    "LoraLoaderModelOnly": "Load LoRA（仅模型）",
    "LoraLoader": "Load LoRA（模型+CLIP）",
    "ModelSamplingFlux": "ModelSamplingFlux（流匹配 shift）",
    "ModelSamplingAuraFlow": "ModelSamplingAuraFlow（shift）",
    "CLIPTextEncode": "CLIP Text Encode (Prompt)（提示词编码）",
    "CLIPSetLastLayer": "CLIP Set Last Layer（CLIP skip）",
    "ConditioningZeroOut": "Conditioning Zero Out（负向清零）",
    "CFGGuider": "CFG Guider",
    "RandomNoise": "Random Noise（种子）",
    "KSamplerSelect": "KSamplerSelect（采样器）",
    "BasicScheduler": "BasicScheduler（调度器）",
    "SamplerCustomAdvanced": "SamplerCustomAdvanced",
    "KSampler": "KSampler",
    "KSamplerAdvanced": "KSampler (Advanced)",
    "EmptyLatentImage": "Empty Latent Image",
    "VAEDecode": "VAE Decode",
    "SaveImage": "Save Image",
    "LoadImage": "Load Image",
    "LoadImageMask": "Load Image (as Mask)",
    "ImageScale": "Upscale Image（精确尺寸）",
    "ImageScaleBy": "Upscale Image By",
    "ImageUpscaleWithModel": "Upscale Image (using Model)",
    "UpscaleModelLoader": "Load Upscale Model",
    "BiRefNetRMBG": "BiRefNet (RMBG)（抠底）",
    "RemoveBackground": "Remove Background（核心抠底）",
    "LoadBackgroundRemovalModel": "Load Background Removal Model",
    "BriaRemoveImageBackground": "Bria Remove Image Background",
    "JoinImageWithAlpha": "Join Image with Alpha",
    "SplitImageWithAlpha": "Split Image with Alpha",
    "ImageCompositeMasked": "Image Composite Masked",
    "IPAdapterUnifiedLoader": "IPAdapter Unified Loader",
    "IPAdapterAdvanced": "IPAdapter Advanced",
    "IPAdapterModelLoader": "IPAdapter Model Loader",
    "CLIPVisionLoader": "Load CLIP Vision",
    "ControlNetLoader": "Load ControlNet Model",
    "ControlNetApplyAdvanced": "Apply ControlNet (Advanced)",
    "TextEncodeQwenImageEditPlus": "Text Encode Qwen Image Edit Plus",
    "FluxKontextMultiReferenceLatentMethod": "Edit Model Reference Method",
    "VAEEncode": "VAE Encode",
    "VAEEncodeForInpaint": "VAE Encode (for Inpainting)",
    "SetLatentNoiseMask": "Set Latent Noise Mask",
    "GrowMask": "Grow Mask",
}

#: 六类错误 → 中文 hint
ERROR_HINTS: dict[str, str] = {
    "offline": (
        "ComfyUI 没在跑或端口不通。请先启动它，再重试："
        "（本机）D:\\AI\\ComfyUI-aki-v3.2\\python\\python.exe "
        "D:\\AI\\ComfyUI-aki-v3.2\\ComfyUI\\main.py --auto-launch --preview-method auto。"
        "若改过端口，请把 host 传给 ComfyClient(host='http://127.0.0.1:<端口>')。"
    ),
    "node_missing": (
        "工作流用到了本机 ComfyUI 没有的节点（多半是自定义节点插件没装）。"
        "处理办法：① 在 ComfyUI Manager 里装对应插件后重启；"
        "② 或者让构造器走降级路径（art.graph 的构造器遇到缺失节点会自动跳过并记 warning）。"
    ),
    "model_missing": (
        "模型文件名不在 ComfyUI 的候选列表里（改名/移走/放错目录）。"
        "处理办法：调用 client.models() 打印本机实际可用清单，"
        "把模型放进 D:\\AI\\ComfyUI-aki-v3.2\\ComfyUI\\models\\<对应子目录>，"
        "然后在 ComfyUI 界面点一次刷新（或重启）让 /object_info 重新枚举。"
    ),
    "oom": (
        "显存不足。按这个顺序试：① 降画布（1536→1152→1024）；② 去掉大 LoRA"
        "（krea2_kroma_v031_turbo_opd_r384 约 2.6 GB）；③ client.free(unload_models=True) "
        "释放显存后重试；④ 批大小降到 1。"
    ),
    "timeout": (
        "等待超时。先看 client.queue_depth()：若队列里堆了别的任务，等它跑完再提交；"
        "若确实卡死，调 client.interrupt() 打断。超时也可以调大 "
        "wait(timeout=...)，Krea 2 在 832×1216 上单张约 5-20 秒，SDXL 28 步约 30-60 秒。"
    ),
    "bad_prompt": (
        "提交的工作流本身不合法（参数缺失/类型不对/连线指向不存在的节点）。"
        "这一步**重试无用**。请按 node_errors 里指出的节点与参数名修正："
        "常见的三个坑是 class_type 写成了 UI 显示名、COMBO 值不在候选里、"
        "连线引用 [节点id, 槽位] 指向了已删除的节点。"
    ),
    "unknown": "未归类的 ComfyUI 错误，请把 detail 里的原始报文一起提交以便定位。",
}


# ══════════════════════════════════════════════════════════════════════
#  seed 工具（IS_CHANGED 缓存坑）
# ══════════════════════════════════════════════════════════════════════
#: ComfyUI 的 seed 是 uint64
SEED_MAX = 18446744073709551615


def new_seed() -> int:
    """生成一个随机 seed（uint64 范围内）。"""
    return random.randint(0, SEED_MAX)


def invalidate_object_info(host: str = "") -> None:
    """丢掉进程级的 ``/object_info`` 缓存。

    什么时候需要：往 ComfyUI 里新放了模型/插件之后 —— 候选列表变了，
    缓存里的旧清单会让「本机有但探测不到」的误判发生。
    ``host`` 为空表示清掉所有主机。
    """
    if not host or host.rstrip("/").lower() == str(_OBJECT_INFO_CACHE.get("host", "")).lower():
        _OBJECT_INFO_CACHE.update({"host": "", "data": None, "ts": 0.0})


def object_info_cache_state() -> dict:
    """缓存现状（给 doctor / 自测打印用）。"""
    return {"host": _OBJECT_INFO_CACHE.get("host", ""),
            "nodes": len(_OBJECT_INFO_CACHE.get("data") or {}),
            "age_s": (round(time.time() - float(_OBJECT_INFO_CACHE.get("ts") or 0), 1)
                      if _OBJECT_INFO_CACHE.get("data") else None),
            "ttl_s": OBJECT_INFO_TTL}


def bump_seed(seed: int, step: int = 1) -> int:
    """把 seed 往前推一步 —— **批量出图必须调用它**。

    为什么必须换 seed：ComfyUI 用节点的 ``IS_CHANGED`` 做缓存判定。
    采样节点的输入（含 ``seed``/``noise_seed``）全部没变时，它会直接判定 cache hit，
    **复用上次的输出文件而不重新生成**（你会收到 ``execution_cached`` 事件，
    然后拿到一张旧图）—— 这就是「怎么批量出来都一样」的头号原因。

    :param seed: 当前 seed。
    :param step: 步进（默认 1；跨批次可以用大一点的步长）。
    :return: 新 seed，**一定与入参不同**（``step=0`` 会被纠正为 1）。
    """
    step = int(step) or 1
    s = (int(seed) + abs(step)) % (SEED_MAX + 1)
    if s == int(seed):  # 极端回绕保护
        s = (s + 1) % (SEED_MAX + 1)
    return s


def seed_of(prompt: dict) -> int | None:
    """从 API 图里读出实际的 seed（``seed`` 或 ``noise_seed``）；读不到返回 ``None``。"""
    for node in (prompt or {}).values():
        inputs = (node or {}).get("inputs") or {}
        for k in ("noise_seed", "seed"):
            if isinstance(inputs.get(k), int):
                return int(inputs[k])
    return None


def with_seed(prompt: dict, seed: int) -> dict:
    """把 API 图里所有 ``seed``/``noise_seed`` 换成新值（**原地改**，返回同一个 dict）。"""
    for node in (prompt or {}).values():
        inputs = (node or {}).get("inputs") or {}
        for k in ("noise_seed", "seed"):
            if k in inputs and isinstance(inputs[k], int):
                inputs[k] = int(seed)
    return prompt


# ══════════════════════════════════════════════════════════════════════
#  客户端
# ══════════════════════════════════════════════════════════════════════
class ComfyClient:
    """本地 ComfyUI 的极简 HTTP 客户端（零第三方依赖）。

    >>> c = ComfyClient()                                  # doctest: +SKIP
    >>> c.alive()                                          # doctest: +SKIP
    True
    >>> m = c.models()                                     # doctest: +SKIP
    >>> "krea2_turbo_bf16.safetensors" in m["unets"]       # doctest: +SKIP
    True
    """

    def __init__(self, host: str = DEFAULT_HOST, timeout: int = 600,
                 client_id: str | None = None) -> None:
        self.host = (host or DEFAULT_HOST).rstrip("/")
        self.timeout = int(timeout)
        self.client_id = client_id or uuid.uuid4().hex
        self._object_info: dict | None = None

    # ── 底层 ──────────────────────────────────────────────────────
    def _url(self, path: str, query: dict | None = None) -> str:
        url = self.host + path
        if query:
            clean = {k: v for k, v in query.items() if v is not None}
            url += "?" + urllib.parse.urlencode(clean)
        return url

    def _request(self, path: str, *, method: str = "GET", payload=None,
                 query: dict | None = None, timeout: int | None = None,
                 raw: bytes | None = None,
                 content_type: str | None = None) -> bytes:
        """发一个请求，返回原始字节；失败一律抛 :class:`ComfyError`。"""
        url = self._url(path, query)
        headers = {"Accept": "application/json"}
        data = raw
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:  # pragma: no cover - 极端情况
                pass
            self._raise_http(exc.code, body, path)
        except urllib.error.URLError as exc:
            raise ComfyError(
                f"连不上 ComfyUI（{self.host}{path}）：{getattr(exc, 'reason', exc)}",
                ERROR_HINTS["offline"], kind="offline",
                detail={"host": self.host, "path": path}) from exc
        except TimeoutError as exc:
            raise ComfyError(
                f"请求 ComfyUI 超时（{self.host}{path}）",
                ERROR_HINTS["timeout"], kind="timeout",
                detail={"host": self.host, "path": path}) from exc
        raise ComfyError(f"未知网络错误：{self.host}{path}",  # pragma: no cover
                         ERROR_HINTS["unknown"], kind="unknown")

    def _raise_http(self, code: int, body: bytes, path: str) -> None:
        """把 HTTP 错误码 + 响应体翻成 ``ComfyError``。"""
        text = body.decode("utf-8", "replace") if body else ""
        payload: dict = {}
        try:
            payload = json.loads(text or "{}")
        except Exception:
            payload = {}
        node_errors = payload.get("node_errors") or {}
        err = payload.get("error") or {}
        msg = str(err.get("message") or err.get("type") or text[:400] or f"HTTP {code}")
        detail = str(err.get("details") or "")
        # 400 = 工作流不合法；node_errors 精确指出哪个节点的哪个参数有问题
        if code == 400:
            translated = self.node_errors(payload)
            kind = "bad_prompt"
            if any("模型" in t or "not in" in t for t in translated):
                kind = "model_missing"
                # 候选列表可能过时了（用户刚往 models/ 放了文件）→ 让下次探测重拉
                invalidate_object_info()
            raise ComfyError(
                f"ComfyUI 拒绝了这个工作流（HTTP 400）：{msg}"
                + (f" —— {detail}" if detail else ""),
                (translated[0] if translated else ERROR_HINTS[kind]),
                kind=kind,
                detail={"node_errors": node_errors, "translated": translated,
                        "raw": text[:2000], "path": path})
        if code == 404:
            raise ComfyError(
                f"ComfyUI 端点不存在（HTTP 404）：{path}",
                "检查 ComfyUI 版本与路径拼写；/view 漏传 subfolder 也会 404。",
                kind="node_missing", detail={"raw": text[:800], "path": path})
        raise ComfyError(f"ComfyUI 返回 HTTP {code}：{msg}",
                         ERROR_HINTS["unknown"],
                         detail={"raw": text[:2000], "path": path, "code": code})

    def _json(self, path: str, **kw) -> dict:
        raw = self._request(path, **kw)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ComfyError(
                f"ComfyUI 返回了非 JSON 内容（{path}）",
                "通常是端点写错或返回了 HTML 错误页；用 object_info() 复核路径。",
                kind="unknown", detail={"raw": raw[:400].decode("utf-8", "replace")}) from exc

    # ── 存活 / 能力 ────────────────────────────────────────────────
    def alive(self) -> bool:
        """服务器是否在线（``GET /system_stats``，最权威的存活探测）。"""
        try:
            data = self._json("/system_stats", timeout=min(self.timeout, 15))
        except ComfyError:
            return False
        return bool(data.get("system") or data.get("devices"))

    def system_stats(self) -> dict:
        """原始 ``/system_stats``（版本、torch、显卡、显存）。"""
        return self._json("/system_stats", timeout=min(self.timeout, 20))

    def summary(self) -> dict:
        """给 ``capabilities()`` / doctor 用的一行体检摘要。"""
        st = self.system_stats()
        sysinfo = st.get("system") or {}
        devs = st.get("devices") or []
        dev = devs[0] if devs else {}
        return {
            "online": True,
            "host": self.host,
            "comfyui_version": sysinfo.get("comfyui_version", ""),
            "python": (sysinfo.get("python_version") or sysinfo.get("python") or ""),
            "torch": sysinfo.get("pytorch_version", ""),
            "device": dev.get("name", ""),
            "vram_total_gb": round(float(dev.get("vram_total", 0)) / 2**30, 1),
            "vram_free_gb": round(float(dev.get("vram_free", 0)) / 2**30, 1),
        }

    def object_info(self, node: str | None = None, *, refresh: bool = False) -> dict:
        """``GET /object_info``（可只取单个 ``class_type``）。

        ⚠️ 全量响应在本机实测 **3.3 MB / 16 秒**，所以做了**进程级共享缓存**
        （``OBJECT_INFO_TTL`` = 15 分钟，跨 :class:`ComfyClient` 实例生效）。
        批量出图因此只付一次探测成本。

        :param node: 只取这一个 ``class_type``（单节点请求不走缓存，很轻）。
        :param refresh: ``True`` 时强制重拉全量并刷新缓存。
        """
        if node:
            return self._json(f"/object_info/{urllib.parse.quote(node)}")
        cached = _OBJECT_INFO_CACHE.get("data")
        fresh = (time.time() - float(_OBJECT_INFO_CACHE.get("ts") or 0)) < OBJECT_INFO_TTL
        same_host = str(_OBJECT_INFO_CACHE.get("host", "")).lower() == self.host.lower()
        if cached and fresh and same_host and not refresh:
            return cached
        data = self._json("/object_info", timeout=max(self.timeout, 180))
        _OBJECT_INFO_CACHE.update({"host": self.host, "data": data, "ts": time.time()})
        self._object_info = data
        return data

    def forget_cache(self) -> None:
        """丢掉本实例 + 进程级的 ``/object_info`` 缓存（装了新插件/模型后调用）。"""
        self._object_info = None
        invalidate_object_info(self.host)

    def nodes(self) -> set[str]:
        """本机已注册的全部 ``class_type``。"""
        return set((self.object_info() or {}).keys())

    def has_nodes(self, names) -> dict[str, bool]:
        """批量检查节点是否存在（构造器用它做优雅降级）。"""
        have = self.nodes()
        return {str(n): (str(n) in have) for n in (names or [])}

    def combo_options(self, node: str, key: str) -> list[str]:
        """读某个节点某个 COMBO 参数的候选字符串数组（**模型探测的唯一正确方式**）。

        兼容两种 schema：老式 ``[["a","b"], {}]`` 与 0.38+ 的
        ``["COMBO", {"options": [...]}]``。
        """
        spec = (self.object_info(node) or {}).get(node) or {}
        inp = spec.get("input") or {}
        for section in ("required", "optional"):
            entry = (inp.get(section) or {}).get(key)
            if not entry:
                continue
            if isinstance(entry, list) and entry:
                first = entry[0]
                if isinstance(first, list):          # 老式：候选就在 [0]
                    return [str(x) for x in first]
                if isinstance(first, str) and first.isupper() and len(entry) > 1 \
                        and isinstance(entry[1], dict):
                    opts = entry[1].get("options")   # 新式：COMBO + options
                    if isinstance(opts, list):
                        return [str(x) for x in opts]
                    return []
            return []
        return []

    def models(self) -> dict:
        """从 ``/object_info`` 的 COMBO 候选里抽出本机可用模型清单。

        :return: ``{"checkpoints": [...], "unets": [...], "loras": [...],
                    "vaes": [...], "clips": [...], "upscale": [...],
                    "controlnet": [...], "clip_vision": [...],
                    "ipadapter": [...], "background_removal": [...]}``

        ⚠️ 不要用 ``/models`` 端点代替它：``/object_info`` 返回的是**节点真正能接受的值**，
        两者不一致时以这里为准（例如 ``UpscaleModelLoader`` 的候选在某些版本上
        只能从 ``/object_info`` 拿到）。
        """
        out: dict[str, list[str]] = {}
        for folder, (node, key) in MODEL_SOURCES.items():
            try:
                opts = self.combo_options(node, key)
            except ComfyError:
                opts = []
            out[folder] = sorted(set(opts))
        # checkpoints 与 unets 在本机常常是两套目录，保持各自独立
        out["diffusion_models"] = list(out.get("unets", []))
        return out

    # ── 队列 ──────────────────────────────────────────────────────
    def object_info_summary(self) -> dict:
        """节点总数与关键节点是否存在（供 capabilities 用）。"""
        info = self.object_info()
        keys = set(info.keys())
        interesting = [
            "CheckpointLoaderSimple", "UNETLoader", "CLIPLoader", "VAELoader",
            "LoraLoaderModelOnly", "KSampler", "SamplerCustomAdvanced", "CFGGuider",
            "RandomNoise", "BasicScheduler", "CLIPSetLastLayer", "SaveImage",
            "UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScale",
            "ImageInvert", "InvertMask", "MaskToImage", "ImageToMask",
            "BiRefNetRMBG", "RemoveBackground", "LoadBackgroundRemovalModel",
            "JoinImageWithAlpha", "BriaRemoveImageBackground",
            "IPAdapterUnifiedLoader", "IPAdapterAdvanced", "CLIPVisionLoader",
            "ControlNetLoader", "TextEncodeQwenImageEditPlus",
            "FluxKontextMultiReferenceLatentMethod", "VAEDecode", "LoadImage",
        ]
        return {"node_total": len(keys),
                "present": {n: (n in keys) for n in interesting}}

    def queue_depth(self) -> dict:
        """``/queue`` 的 running / pending 数量与条目摘要。"""
        data = self._json("/queue", timeout=min(self.timeout, 30))
        running = data.get("queue_running") or []
        pending = data.get("queue_pending") or []

        def _brief(item) -> dict:
            try:
                return {"number": item[0], "prompt_id": item[1]}
            except Exception:  # pragma: no cover
                return {"raw": str(item)[:120]}

        return {"running": len(running), "pending": len(pending),
                "running_items": [_brief(i) for i in running],
                "pending_items": [_brief(i) for i in pending]}

    def queue(self, prompt: dict, client_id: str | None = None,
              extra_data: dict | None = None, front: bool = False) -> str:
        """``POST /prompt`` 提交一个 API 格式工作流，返回 ``prompt_id``。

        ⚠️ **IS_CHANGED 缓存坑（必读）**
            ComfyUI 会跳过「输入未变化」的节点。如果 ``seed``/``noise_seed``、
            提示词、参数全都没变，采样节点会被判定为 cache hit，你会收到
            ``execution_cached`` 事件，并且**拿到上一次的输出文件（旧图），
            而 ComfyUI 根本没有重新生成**。表现就是「我明明重跑了，图却一模一样」。

            三条解法（推荐第 1 条）：

            1. **每张图都换 seed** —— 用 :func:`bump_seed` / :func:`with_seed`，
               或构造图时直接给新 seed；
            2. 改任意一个会进入节点 hash 的输入（例如 steps 加 1、
               ``filename_prefix`` 换一个）；
            3. ``POST /prompt`` 时用 ``partial_execution_targets``
               强制重跑指定节点（本方法暂未暴露，需要时直接改 payload）。

        :param prompt: ``{node_id: {"class_type": ..., "inputs": {...}}}``
        :param client_id: 复用同一个 id 才能在 WebSocket 里对上号；默认用实例 id。
        :param extra_data: 追加到 payload 的 ``extra_data``。
        :param front: ``True`` 时插队到队首。
        :raises ComfyError: ``kind="bad_prompt"`` —— 400 响应的 ``node_errors``
            会被 :meth:`node_errors` 翻译成中文放进 ``hint``。
        """
        if not isinstance(prompt, dict) or not prompt:
            raise ComfyError("提交的工作流为空", "先用 art.graph 的构造器生成图。",
                             kind="bad_prompt")
        payload: dict = {"prompt": prompt, "client_id": client_id or self.client_id}
        if extra_data:
            payload["extra_data"] = extra_data
        if front:
            payload["front"] = True
        data = self._json("/prompt", method="POST", payload=payload,
                          timeout=max(self.timeout, 120))
        pid = data.get("prompt_id")
        if not pid:
            raise ComfyError(f"ComfyUI 没有返回 prompt_id：{str(data)[:300]}",
                             ERROR_HINTS["bad_prompt"], kind="bad_prompt",
                             detail={"response": data})
        return str(pid)

    def history(self, prompt_id: str | None = None) -> dict:
        """``GET /history`` 或 ``/history/{prompt_id}``。

        注意：**任务完成前 history 里不会有该 prompt_id 的 key** ——
        「key 不存在」= 仍在排队/执行中，不是错误。
        """
        path = f"/history/{urllib.parse.quote(prompt_id)}" if prompt_id else "/history"
        return self._json(path, timeout=min(self.timeout, 60))

    def wait(self, prompt_id: str, on_progress=None,
             timeout: int = 900, interval: float = 1.5) -> dict:
        """轮询 ``/history/{id}`` 直到完成；支持进度回调与超时。

        :param on_progress: 回调 ``fn(info: dict)``，``info`` 形如
            ``{"prompt_id","state","done","total","elapsed","queue_running",
            "queue_pending","cached"}``；``state`` ∈
            ``{"queued","running","done","error"}``。
        :param timeout: 墙钟超时秒数（默认 900）。
        :raises ComfyError: ``kind="timeout"`` 超时；``kind="oom"`` 显存不足；
            其它执行失败按内容归到 ``bad_prompt`` / ``model_missing`` / ``unknown``。
        :return: history 里该 prompt 的条目（含 ``outputs``）。
        """
        t0 = time.time()
        last_info: dict = {"prompt_id": prompt_id, "state": "queued"}
        while True:
            elapsed = time.time() - t0
            if elapsed > timeout:
                raise ComfyError(
                    f"等待 ComfyUI 出图超时（{int(elapsed)}s / 上限 {timeout}s，"
                    f"prompt_id={prompt_id}）",
                    ERROR_HINTS["timeout"], kind="timeout",
                    detail={"prompt_id": prompt_id, "elapsed": round(elapsed, 1)})

            entry = (self.history(prompt_id) or {}).get(prompt_id) or {}
            status = entry.get("status") or {}
            done = bool(status.get("completed")) or status.get("status_str") in ("success", "error")
            state = "running" if entry else "queued"
            if done:
                state = "error" if (status.get("status_str") == "error" or not status.get("completed")) else "done"
                if state == "error":
                    self._raise_execution_error(entry, prompt_id)

            info = self._progress_info(prompt_id, state, elapsed, entry)
            last_info = info
            if on_progress:
                try:
                    on_progress(info)
                except Exception:  # pragma: no cover - 回调不该影响主流程
                    pass
            if done:
                return entry
            time.sleep(max(0.2, float(interval)))

    def _progress_info(self, prompt_id: str, state: str, elapsed: float,
                       entry: dict) -> dict:
        """拼一条进度信息（节点级进度只能靠轮询 history，这里给的是阶段级）。"""
        depth = {"running": 0, "pending": 0}
        try:
            q = self.queue_depth()
            depth = {"running": q.get("running", 0), "pending": q.get("pending", 0)}
        except ComfyError:
            pass
        outputs = entry.get("outputs") or {}
        n_img = sum(len((v or {}).get("images") or []) for v in outputs.values())
        status = entry.get("status") or {}
        messages = status.get("messages") or []
        cached: list[str] = []
        for m in messages:
            if isinstance(m, (list, tuple)) and len(m) >= 2 and m[0] == "execution_cached":
                data = m[1] or {}
                cached = list(data.get("nodes") or [])
        return {
            "prompt_id": prompt_id, "state": state, "elapsed": round(elapsed, 1),
            "queue_running": depth["running"], "queue_pending": depth["pending"],
            "cached": cached, "images": n_img, "messages": len(messages),
        }

    def _raise_execution_error(self, entry: dict, prompt_id: str) -> None:
        """把执行期错误（history.status.messages）翻成分类好的 ``ComfyError``。"""
        status = entry.get("status") or {}
        msgs = status.get("messages") or []
        text = json.dumps(msgs, ensure_ascii=False)
        low = text.lower()
        if "outofmemory" in low or "out of memory" in low or "cuda error" in low:
            kind = "oom"
        elif ("error downloading model files" in low or "cannot find the requested files"
              in low or "local cache" in low or "connection" in low and "hub" in low):
            # 典型：ComfyUI-RMBG 的 BiRefNet 变体按需从 HuggingFace 下载权重，离线就失败
            kind = "model_missing"
        elif "not found" in low or "no such file" in low or "cannot find" in low:
            kind = "model_missing"
        elif "not in list" in low or "value not in list" in low:
            kind = "model_missing"
        elif "timeout" in low:
            kind = "timeout"
        else:
            kind = "bad_prompt"
        # 抽一条人话摘要
        summary = ""
        for m in msgs:
            if isinstance(m, (list, tuple)) and len(m) >= 2 and isinstance(m[1], dict):
                data = m[1]
                if "exception_message" in data:
                    summary = (f"{data.get('node_type') or data.get('node_id')}: "
                               f"{data.get('exception_type', '')} "
                               f"{data.get('exception_message', '')}").strip()
                    break
        hint = ERROR_HINTS.get(kind, ERROR_HINTS["unknown"])
        if kind == "model_missing" and ("downloading model files" in low
                                        or "local cache" in low):
            hint = ("这个节点要按需从 HuggingFace 下载权重，但本机离线/下载失败。"
                    "两条路：① 把权重放进对应目录让它走本地（BiRefNet 系放 "
                    "ComfyUI/models/RMBG/BiRefNet/，核心抠底模型放 "
                    "ComfyUI/models/background_removal/）；"
                    "② 换一个本机已有权重的节点 —— art.graph.append_remove_bg 会"
                    "**先探测再决定**，有核心 LoadBackgroundRemovalModel 就走它。")
        raise ComfyError(
            f"ComfyUI 执行失败（prompt_id={prompt_id}）：{summary or text[:300]}",
            hint, kind=kind,
            detail={"prompt_id": prompt_id, "messages": msgs[:6], "summary": summary})

    # ── 文件 ──────────────────────────────────────────────────────
    def view(self, filename: str, subfolder: str = "", type_: str = "output") -> bytes:
        """``GET /view`` 下载图片字节。

        ⚠️ **必须带 ``subfolder``**：``SaveImage`` 的 ``filename_prefix`` 写成
        ``cardforge/art`` 后，history 里返回的 ``filename`` 只有 ``xxx_00001_.png``、
        ``subfolder`` 才是 ``cardforge/art``；漏传直接 404。
        所以拿到 ``outputs`` 后要**原样**把三个字段都传进来。
        """
        return self._request("/view", query={
            "filename": filename,
            "subfolder": subfolder or "",
            "type": type_ or "output",
        }, timeout=max(self.timeout, 180))

    def download_outputs(self, entry: dict, out_dir: str | os.PathLike,
                         prefix: str = "") -> list[str]:
        """把 history 条目里的所有图片落盘，返回绝对路径列表。"""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for _node_id, node_out in (entry.get("outputs") or {}).items():
            for img in (node_out or {}).get("images") or []:
                blob = self.view(img.get("filename", ""), img.get("subfolder", ""),
                                 img.get("type", "output"))
                name = (prefix + img.get("filename", "out.png")) if prefix else img.get("filename", "out.png")
                dst = out / name
                dst.write_bytes(blob)
                saved.append(str(dst.resolve()))
        return saved

    def upload(self, path: str | os.PathLike, subfolder: str = "CardForge",
               overwrite: bool = True) -> dict:
        """``POST /upload/image`` 上传参考图，返回 ``{name, subfolder, type}``。

        之后给 ``LoadImage`` 的 ``image`` 填 ``"<subfolder>/<name>"``
        （subfolder 为空时只填 name）。
        """
        p = Path(path)
        if not p.exists():
            raise ComfyError(f"要上传的参考图不存在：{p}",
                             "检查路径；参考图建议放在 workspace/pics/ 下。",
                             kind="bad_prompt", detail={"path": str(p)})
        boundary = "----CardForge" + uuid.uuid4().hex
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        chunks: list[bytes] = []
        for key, value in (("type", "input"), ("subfolder", subfolder or ""),
                           ("overwrite", "true" if overwrite else "false")):
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            chunks.append(str(value).encode("utf-8") + b"\r\n")
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="image"; filename="{p.name}"\r\n'.encode("utf-8"))
        chunks.append(f"Content-Type: {ctype}\r\n\r\n".encode("utf-8"))
        chunks.append(p.read_bytes())
        chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(chunks)
        raw = self._request("/upload/image", method="POST", raw=body,
                            content_type=f"multipart/form-data; boundary={boundary}",
                            timeout=max(self.timeout, 180))
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {"name": p.name, "subfolder": subfolder}
        name = data.get("name") or p.name
        sub = data.get("subfolder") or ""
        data["ref"] = f"{sub}/{name}" if sub else name
        return data

    # ── 控制 ──────────────────────────────────────────────────────
    def interrupt(self, prompt_id: str | None = None) -> None:
        """``POST /interrupt`` 打断当前执行（给 ``prompt_id`` 只打断那一个）。"""
        payload = {"prompt_id": prompt_id} if prompt_id else {}
        try:
            self._request("/interrupt", method="POST", payload=payload, timeout=30)
        except ComfyError:
            pass

    def free(self, unload_models: bool = False, free_memory: bool = True) -> None:
        """``POST /free`` 释放显存。批量任务之间调用可防 OOM；切底模时 ``unload_models=True``。"""
        try:
            self._request("/free", method="POST",
                          payload={"unload_models": bool(unload_models),
                                   "free_memory": bool(free_memory)}, timeout=60)
        except ComfyError:
            pass

    def clear_queue(self) -> None:
        """``POST /queue {"clear": true}`` 清空待执行（running 项删不掉，只能 interrupt）。"""
        try:
            self._request("/queue", method="POST", payload={"clear": True}, timeout=30)
        except ComfyError:
            pass

    def clear_history(self) -> None:
        """``POST /history {"clear": true}`` —— history 在内存里，长期跑要定期清。"""
        try:
            self._request("/history", method="POST", payload={"clear": True}, timeout=30)
        except ComfyError:
            pass

    # ── 错误翻译 ──────────────────────────────────────────────────
    def node_errors(self, resp: dict) -> list[str]:
        """把 400 响应里的 ``node_errors`` **翻译成中文**（可执行的修正建议）。

        ComfyUI 的原始报文形如::

            {"node_errors": {"3": {"errors": [{"type": "required",
                                               "message": "Required input is missing",
                                               "details": "model"}],
                                   "class_type": "KSampler"}}}

        返回的中文条目会带上「节点 id / 界面名 / 参数名 / 怎么改」。
        """
        out: list[str] = []
        payload = resp or {}
        ne = payload.get("node_errors") or {}
        for node_id, info in ne.items():
            info = info or {}
            cls = str(info.get("class_type") or info.get("type") or "?")
            disp = NODE_DISPLAY.get(cls, cls)
            for e in (info.get("errors") or []):
                e = e or {}
                etype = str(e.get("type") or "")
                raw_msg = str(e.get("message") or "")
                details = e.get("details")
                detail = str(details) if details not in (None, "", {}) else ""
                out.append(self._translate_one(node_id, cls, disp, etype, raw_msg, detail))
            if not (info.get("errors") or []):
                out.append(f"节点 {node_id}（{disp}）报错但未给出细节，请检查它的所有必填输入。")
        if not out:
            err = payload.get("error") or {}
            if err:
                out.append("ComfyUI 未指出具体节点；顶层错误："
                           + str(err.get("message") or err.get("type") or err)[:200]
                           + "。请对照 class_type 与 /object_info 的候选值逐项核对。")
        return out

    @staticmethod
    def _translate_one(node_id, cls: str, disp: str, etype: str,
                       raw_msg: str, detail: str) -> str:
        """单条 node_error 的中文翻译。"""
        low = (raw_msg + " " + detail + " " + etype).lower()
        head = f"节点 {node_id}（{disp}）"
        if "value_not_in_list" in low or "value not in list" in low or "not in list" in low:
            return (f"{head}：参数 `{detail or '?'}` 的取值不在候选项里。"
                    "多半是模型文件名写错或模型没放进对应目录 —— "
                    "调 client.models() 看实际可用清单，或调 combo_options() 看该参数的候选。")
        if "required" in low or "missing" in low:
            return (f"{head}：缺少必填输入 `{detail or '?'}`。"
                    "通常是构造器少接了一根线（例如 KSampler 没接 model/positive/negative），"
                    "或者该参数是 COMBO 却没给值。")
        if "return_type_mismatch" in low or "type" in low and "mismatch" in low:
            return (f"{head}：连线类型不匹配（{raw_msg}）。"
                    "把 A 节点的输出接到 B 节点的输入时，类型必须一致"
                    "（MODEL→MODEL、LATENT→LATENT、IMAGE→IMAGE）。")
        if "invalid_input" in low or "invalid" in low:
            return (f"{head}：输入非法 `{detail or '?'}`（{raw_msg}）。"
                    "常见原因：数值超范围、枚举值拼写错、图片文件名不在 input/ 目录里。")
        if "custom validation" in low or "exception" in low:
            return (f"{head}：节点自检失败 —— {raw_msg} {detail}".strip()
                    + "。按这句话里的参数名去改；模型/插件版本不匹配也会走到这里。")
        if "model" in low and ("not" in low or "missing" in low):
            return (f"{head}：模型不可用（{raw_msg} {detail}）。"
                    "把模型放进 ComfyUI/models 对应子目录，再刷新 /object_info。")
        return (f"{head}：{raw_msg or etype} {detail}".strip()
                + "。请对照该节点在 /object_info 里的 input.required 逐项核对。")


__all__ = [
    "ComfyClient", "MODEL_SOURCES", "NODE_DISPLAY", "ERROR_HINTS",
    "DEFAULT_HOST", "SEED_MAX", "OBJECT_INFO_TTL", "new_seed", "bump_seed",
    "seed_of", "with_seed", "invalidate_object_info", "object_info_cache_state",
]
