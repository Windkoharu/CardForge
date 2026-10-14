"""``/api/llm`` —— 大模型接入的设置面（配模型、切模型、试连、断开）。

边界（和 ``llm_config`` 同一条红线）：本模块**只改配置与试连**，
不产生任何对话结论。艾莉娅说的话照旧走 ``chat.py``；
LLM 在这里只是「提议」，裁决永远归确定性内核。

密钥纪律：响应里永远不见明文 key —— 列表走 ``llm_config.list_providers``
（一律打码）；``POST /api/llm`` 的 ``api_key`` 只进不出，
空串表示「保持旧 key 不动」（界面回传时天然打码，不能把人家的密钥清掉）。
"""
from __future__ import annotations

from ..core import errors
from . import kernel as K
from .http import Request

__all__ = ["register"]

#: 试连默认预算（毫秒）—— 保存前的「测试连接」与保存后的「测试」共用。
_TEST_TIMEOUT_MS = 6000
#: 在线状态并发探测的总预算（毫秒）—— 只探本地端点，见 llm_config.status。
_STATUS_TIMEOUT_MS = 1500

_KINDS = ("openai_compat", "ollama", "lmstudio")


def register(app) -> None:

    # ── 读 ────────────────────────────────────────────────────────
    @app.get("/api/llm")
    def llm_get(req: Request) -> dict:
        """设置面板数据：存档（打码+在线状态）、预设、当前生效、auto 实测。"""
        return _status(_lc(), req)

    # ── 写 ────────────────────────────────────────────────────────
    @app.post("/api/llm")
    def llm_post(req: Request) -> dict:
        """一个入口四种动作：``upsert``（默认）/ ``use`` / ``off`` / ``rm`` / ``preset``。

        每次 mutation 都回传全新 status —— 界面拿一个响应重渲染，
        不用再发一次 GET，也不会出现「改了但列表没动」的撕裂。
        """
        lc = _lc()
        action = (req.str_arg("action") or "upsert").strip().lower()

        if action in ("upsert", "save"):
            return _do_upsert(lc, req, preset="")
        if action == "preset":
            return _do_upsert(lc, req, preset=req.str_arg("preset").strip())
        if action == "use":
            name = req.str_arg("name").strip()
            if not name:
                raise errors.SpecError("要切换的目标名为空", "带上 name=<配置名>")
            if not lc.set_active(name):
                raise errors.SpecError(
                    f"配置里没有「{name}」", "先保存这个 provider，再切换")
            return _status(lc, req)
        if action in ("off", "none", "disable"):
            lc.use_off()
            return _status(lc, req)
        if action in ("rm", "remove", "delete"):
            name = req.str_arg("name").strip()
            if not name:
                raise errors.SpecError("要删除的配置名为空", "带上 name=<配置名>")
            if not lc.remove(name):
                raise errors.SpecError(
                    f"配置里没有「{name}」", "列表可能已刷新，再看一眼")
            return _status(lc, req)
        raise errors.SpecError(
            f"不认识的动作「{action}」",
            "action 可选：upsert / preset / use / off / rm")

    # ── 试连 ──────────────────────────────────────────────────────
    @app.post("/api/llm/test")
    def llm_test(req: Request) -> dict:
        """真连一次：可达性 + 模型列表 + 问一句话。

        带 ``base_url`` = 保存前试连（不落账，设置界面「测试连接」用）；
        带 ``name`` = 测已存的那笔；都不带 = 测当前 active。
        """
        lc = _lc()
        timeout = (req.int_arg("timeout_ms", _TEST_TIMEOUT_MS)
                   or _TEST_TIMEOUT_MS) / 1000.0
        base = req.str_arg("base_url").strip().rstrip("/")
        name = req.str_arg("name").strip()
        if base:
            kind = (req.str_arg("kind") or "openai_compat").strip().lower()
            if kind not in _KINDS:
                raise errors.SpecError(
                    f"不支持的 kind：{kind}", "可选 " + " / ".join(_KINDS))
            if not base.startswith(("http://", "https://")):
                raise errors.SpecError(
                    "base_url 必须以 http:// 或 https:// 开头",
                    "例如 http://127.0.0.1:1234/v1 或 https://api.deepseek.com/v1")
            return lc.probe_url(base, api_key=req.str_arg("api_key"),
                                model=req.str_arg("model"), kind=kind,
                                timeout=timeout)
        return lc.probe(name, timeout=timeout)


# ══════════════════════════════════════════════════════════════════════
#  助手（模块级 —— 和 api_assistant 的 _session_of 一个路子）
# ══════════════════════════════════════════════════════════════════════
def _lc():
    return K.require("cardforge.assistant.llm_config", "LLM 配置模块",
                     "助手模块不完整；造卡主流程不受影响，只是配不了大模型")


def _detected() -> dict:
    """auto 链**此刻**会解析到谁 —— 顶栏「艾莉娅挂在哪」用。

    带缓存（负结论 30s TTL），所以设置面板反复开不会反复探。
    """
    P = K.try_import("cardforge.assistant.providers")
    if P is None:
        return {}
    try:
        p = P.detect_provider("auto")
        info = P.provider_info()
        return {"provider": getattr(p, "name", "none"),
                "detail": dict(info.get("detail") or {})}
    except Exception:
        return {}


def _status(lc, req: Request) -> dict:
    """存档列表 + 预设 + 当前生效 + auto 实测结论，一屏给全。"""
    out: dict = {"ok": True}
    try:
        out.update(lc.status(
            timeout=(req.int_arg("timeout_ms", _STATUS_TIMEOUT_MS)
                     or _STATUS_TIMEOUT_MS) / 1000.0))
    except Exception as e:
        out["status_error"] = f"{type(e).__name__}: {e}"
    out["detected"] = _detected()
    return out


def _do_upsert(lc, req: Request, preset: str = "") -> dict:
    """新建/更新一笔配置。``preset`` 非空 = 按预设填默认值（表单仍可改）。

    **局部更新语义**（和 CLI ``cardforge llm set`` 一致）：改模型、补 Key
    都不想重贴一遍 URL —— 表单没带 ``base_url`` 就沿用旧值；
    ``kind`` 没带同样沿用。只有全新名字才要求必填。
    """
    existing: dict = {}
    want_name = (req.str_arg("preset").strip() if preset
                 else req.str_arg("name").strip())
    try:
        existing = next((p for p in lc.list_providers()
                         if p.get("name") == want_name), {}) or {}
    except Exception:
        existing = {}

    if preset:
        p = (getattr(lc, "PRESETS", None) or {}).get(preset)
        if not p:
            raise errors.SpecError(
                f"没有预设「{preset}」",
                "可选：" + "、".join(getattr(lc, "PRESETS", {}) or {}))
        name = want_name or preset
        kind = (req.str_arg("kind") or p.get("kind")
                or existing.get("kind") or "openai_compat").strip().lower()
        base = (req.str_arg("base_url") or p.get("base_url")
                or existing.get("base_url") or "").strip().rstrip("/")
        model = req.str_arg("model") or p.get("model") or ""
        note = req.str_arg("note") or p.get("note") or ""
    else:
        name = want_name
        if not name:
            raise errors.SpecError(
                "provider 名不能为空",
                "给这笔配置起个名字，比如「本地LM」「DeepSeek」")
        kind = (req.str_arg("kind") or existing.get("kind")
                or "openai_compat").strip().lower()
        base = (req.str_arg("base_url") or existing.get("base_url") or "").strip().rstrip("/")
        model = req.str_arg("model") or existing.get("model") or ""
        note = req.str_arg("note") or existing.get("note") or ""

    if kind not in _KINDS:
        raise errors.SpecError(
            f"不支持的 kind：{kind}", "可选 " + " / ".join(_KINDS))
    if not base.startswith(("http://", "https://")):
        raise errors.SpecError(
            "base_url 必须以 http:// 或 https:// 开头",
            "本地服务形如 http://127.0.0.1:1234/v1；云端多以 /v1 结尾")

    api_key = req.str_arg("api_key")
    try:
        entry = lc.upsert(name, kind=kind, base_url=base, api_key=api_key,
                          model=model, note=note,
                          timeout=float(req.int_arg("timeout", 30) or 30),
                          set_active=req.bool_arg("set_active", True))
    except ValueError as e:
        raise errors.SpecError(str(e),
                               "名称不超过 40 字；URL 带协议头；timeout 是秒数") from e

    warn = ""
    is_cloud = "127.0.0.1" not in base and "localhost" not in base
    if is_cloud and not str(entry.get("api_key") or "").strip():
        warn = ("云端端点还没有 API Key —— 大多数云端服务会返回 401。"
                "Key 只存在本机 workspace/config/llm.json，不会上传。")
    out = _status(lc, req)
    out.update({"action": "preset" if preset else "upsert", "name": name,
                "kind": kind, "base_url": base, "warn": warn})
    return out
