"""LLM 接入配置 —— 持久化在 ``workspace/config/llm.json``。

解决什么问题
------------
``providers.py`` 早就支持任意 OpenAI 兼容端点，但配置**只能靠环境变量**：
打包成程序交给用户后，让用户去设 ``OPENAI_API_KEY`` 是不现实的。这里把
「连哪个大模型」变成**文件里的一笔账**：

- 多provider 存档（云端 + 本地混存），一个 ``active``；
- 云端/本地**预设**一键落账（DeepSeek / Kimi / 智谱 / 通义 / OpenAI / LM Studio / Ollama / vLLM）；
- ``api_key`` **打码后才允许出仓库**（日志、API 返回、``list`` 都不见明文）；
- 环境变量仍然优先（``CARDFORGE_LLM_*`` / ``OPENAI_*``）—— 开发者临时切端点不用改文件。

红线
----
本模块**只做配置与探测**，不产生任何对话结论。艾莉娅说的话照旧走
``chat.py``；LLM 在这里只是「提议」，裁决永远归确定性内核。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from ..core import paths

__all__ = ["PRESETS", "load", "save", "list_providers", "upsert", "remove",
           "set_active", "use_off", "get_active", "active_name", "mask_key",
           "probe", "probe_url", "status", "build_provider", "revision",
           "stamp", "describe_active"]

#: 预设：kind + base_url + 默认模型提示。模型随时可在设置里改。
PRESETS: dict[str, dict[str, str]] = {
    "lmstudio": {
        "label": "LM Studio（本机）",
        "kind": "openai_compat",
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "",
        "note": "本机 LM Studio，启动 Developer Server 后即用",
    },
    "ollama": {
        "label": "Ollama（本机）",
        "kind": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "model": "",
        "note": "本机 Ollama，先 ollama pull 一个模型",
    },
    "vllm": {
        "label": "vLLM / LocalAI（本机）",
        "kind": "openai_compat",
        "base_url": "http://127.0.0.1:8000/v1",
        "model": "",
        "note": "本机 OpenAI 兼容服务",
    },
    "deepseek": {
        "label": "DeepSeek（云端）",
        "kind": "openai_compat",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "note": "platform.deepseek.com 申请 API Key",
    },
    "kimi": {
        "label": "Kimi  moonshot（云端）",
        "kind": "openai_compat",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "note": "platform.moonshot.cn 申请 API Key",
    },
    "zhipu": {
        "label": "智谱 GLM（云端）",
        "kind": "openai_compat",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-air",
        "note": "open.bigmodel.cn 申请 API Key",
    },
    "qwen": {
        "label": "通义千问（云端）",
        "kind": "openai_compat",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "note": "DashScope 兼容模式，百炼控制台申请 Key",
    },
    "openai": {
        "label": "OpenAI（云端）",
        "kind": "openai_compat",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "note": "需要可访问 api.openai.com 的网络",
    },
}

KINDS: tuple[str, ...] = ("openai_compat", "ollama", "lmstudio")

_LOCK = threading.RLock()
_STATE: dict[str, Any] = {"rev": 0}      # 每次保存 +1，供 provider 缓存失效判断
_CACHE: dict[str, Any] = {"raw": None, "mtime": 0.0}


# ══════════════════════════════════════════════════════════════════════
#  读写
# ══════════════════════════════════════════════════════════════════════
def _file() -> Path:
    return paths.LLM_CONFIG_FILE


def load(*, refresh: bool = False) -> dict:
    """读配置。文件不存在/损坏时返回空账本（**不抛**——没配过 LLM 是正常状态）。"""
    with _LOCK:
        f = _file()
        try:
            mtime = f.stat().st_mtime if f.exists() else 0.0
        except OSError:
            mtime = 0.0
        if not refresh and _CACHE.get("raw") is not None and _CACHE.get("mtime") == mtime:
            return _CACHE["raw"]
        raw: dict = {}
        if f.is_file():
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    raw = data
            except (ValueError, OSError):
                raw = {}          # 损坏的配置等于没配，界面会提示重建
        raw.setdefault("active", "")
        providers = raw.get("providers")
        raw["providers"] = providers if isinstance(providers, dict) else {}
        _CACHE.update({"raw": raw, "mtime": mtime})
        return raw


def save(cfg: dict) -> dict:
    """落盘。原子写（先写临时文件再 replace），避免半截 JSON。"""
    with _LOCK:
        cfg = dict(cfg or {})
        cfg.setdefault("active", "")
        providers = cfg.get("providers")
        cfg["providers"] = providers if isinstance(providers, dict) else {}
        f = _file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)
        _STATE["rev"] = int(_STATE.get("rev") or 0) + 1
        _CACHE.update({"raw": None, "mtime": 0.0})
        return cfg


def revision() -> int:
    """配置版本号（保存一次 +1）—— ``providers.detect_provider`` 的缓存键要带上它，
    否则「刚在界面里换了模型」要等进程重启才生效。"""
    return int(_STATE.get("rev") or 0)


def stamp() -> tuple:
    """``(revision, mtime)`` —— 跨进程也能发现配置变了。

    只有 revision 不够：服务器进程里 revision 不动，用户在**另一个终端**跑
    ``cardforge llm use other`` 改了文件，服务器的 provider 缓存还认旧账。
    mtime 随每次原子写变化，把它并进缓存键，「CLI 改完服务器立刻跟上」。
    """
    f = _file()
    try:
        mt = f.stat().st_mtime if f.exists() else 0.0
    except OSError:
        mt = 0.0
    return revision(), mt


# ══════════════════════════════════════════════════════════════════════
#  增删改查
# ══════════════════════════════════════════════════════════════════════
def _norm_name(name: str) -> str:
    return str(name or "").strip()


def _safe_name(name: str) -> bool:
    """配置名会当 JSON 键，不当文件名——但照样拒绝空名与超长名。"""
    n = _norm_name(name)
    return bool(n) and len(n) <= 40


def upsert(name: str, *, kind: str = "openai_compat", base_url: str = "",
           api_key: str = "", model: str = "", note: str = "",
           timeout: float = 30.0, set_active: bool = False) -> dict:
    """新建/更新一个 provider。

    ``api_key=""`` 表示**保持原 key 不动**（设置界面回传时天然打码，
    不能因为「用户没重新输」就把人家的密钥清掉）。
    """
    name = _norm_name(name)
    if not _safe_name(name):
        raise ValueError("provider 名不能为空且不超过 40 字")
    kind = str(kind or "openai_compat").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"不支持的 kind：{kind}（可选 {KINDS}）")
    base = str(base_url or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ValueError("base_url 必须以 http:// 或 https:// 开头")
    with _LOCK:
        cfg = load(refresh=True)
        providers = dict(cfg.get("providers") or {})
        old = providers.get(name) or {}
        entry = {
            "kind": kind,
            "base_url": base,
            "api_key": str(api_key or "") or str(old.get("api_key") or ""),
            "model": str(model or "").strip(),
            "note": str(note or ""),
            "timeout": float(timeout or old.get("timeout") or 30.0),
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        providers[name] = entry
        cfg["providers"] = providers
        if set_active or not cfg.get("active"):
            cfg["active"] = name
        save(cfg)
        return entry


def remove(name: str) -> bool:
    with _LOCK:
        cfg = load(refresh=True)
        providers = dict(cfg.get("providers") or {})
        name = _norm_name(name)
        if name not in providers:
            return False
        del providers[name]
        cfg["providers"] = providers
        if cfg.get("active") == name:
            cfg["active"] = next(iter(providers), "")
        save(cfg)
        return True


def set_active(name: str) -> bool:
    name = _norm_name(name)
    with _LOCK:
        cfg = load(refresh=True)
        if name not in (cfg.get("providers") or {}):
            return False
        cfg["active"] = name
        save(cfg)
        return True


def use_off() -> None:
    """显式关闭 LLM（active=""）—— 艾莉娅回到规则通路，功能不缺失。"""
    with _LOCK:
        cfg = load(refresh=True)
        cfg["active"] = ""
        save(cfg)


def active_name() -> str:
    return str(load().get("active") or "")


def get_active() -> Optional[dict]:
    """active provider 的**原始**配置（含明文 key，仅内部使用）。"""
    cfg = load()
    name = str(cfg.get("active") or "")
    if not name:
        return None
    entry = (cfg.get("providers") or {}).get(name)
    return dict(entry, name=name) if isinstance(entry, dict) else None


# ══════════════════════════════════════════════════════════════════════
#  视图（打码）
# ══════════════════════════════════════════════════════════════════════
def mask_key(key: str) -> str:
    """``sk-abcdef…wxyz`` —— 只留前后各几位，够用户认得出是哪把钥匙。"""
    k = str(key or "")
    if not k:
        return ""
    if len(k) <= 8:
        return k[:2] + "…" + k[-1:]
    return f"{k[:3]}…{k[-4:]}（{len(k)} 字符）"


def list_providers() -> list[dict]:
    """给 CLI / UI 的列表：**key 一律打码**。附带每个 provider 的在线状态。"""
    cfg = load()
    active = str(cfg.get("active") or "")
    out: list[dict] = []
    for name, entry in (cfg.get("providers") or {}).items():
        if not isinstance(entry, dict):
            continue
        out.append({
            "name": name,
            "kind": entry.get("kind", "openai_compat"),
            "base_url": entry.get("base_url", ""),
            "model": entry.get("model", ""),
            "note": entry.get("note", ""),
            "masked_key": mask_key(entry.get("api_key", "")),
            "has_key": bool(str(entry.get("api_key") or "").strip()),
            "timeout": entry.get("timeout", 30.0),
            "updated": entry.get("updated", ""),
            "active": name == active,
        })
    out.sort(key=lambda x: (not x["active"], x["name"]))
    return out


def describe_active() -> dict:
    """一句话说清「现在艾莉娅挂在哪」—— 顶栏/抽屉/doctor 都用它。"""
    cfg = load()
    name = str(cfg.get("active") or "")
    if not name:
        return {"active": "", "provider": "none", "detail": "未接入 LLM（规则通路）",
                "ok": True}
    entry = (cfg.get("providers") or {}).get(name) or {}
    return {"active": name, "provider": entry.get("kind", "openai_compat"),
            "base_url": entry.get("base_url", ""), "model": entry.get("model", ""),
            "masked_key": mask_key(entry.get("api_key", "")),
            "detail": f"{name}（{entry.get('base_url', '')}）", "ok": True}


# ══════════════════════════════════════════════════════════════════════
#  探测与组装
# ══════════════════════════════════════════════════════════════════════
def build_provider(name: str = ""):
    """把存档的配置组装成 provider 实例（延迟 import，避免与 providers 循环）。"""
    from . import providers as P

    entry = get_active() if not _norm_name(name) else _entry_of(_norm_name(name))
    if entry is None:
        raise ValueError(f"配置里没有 provider「{name or '(active)'}」")
    return P.build_from_config({k: v for k, v in entry.items() if k != "name"})


def _entry_of(name: str) -> Optional[dict]:
    cfg = load()
    entry = (cfg.get("providers") or {}).get(name)
    return dict(entry, name=name) if isinstance(entry, dict) else None


def _probe_entry(entry: dict, *, timeout: float = 6.0) -> dict:
    """对一笔配置（**已含明文 key**）做完整试连：可达 + 模型列表 + 首字延迟。

    ``llm test``（按名）与设置界面「测试连接」（按 URL，未保存）共用。
    可达性判据走 ``providers.config_ready``（本地端点必须真探到模型），
    所以「服务没起」报的是不在线，而不是先放行、等聊天超时才说聊不了。
    """
    from . import providers as P

    started = time.time()
    base = str(entry.get("base_url") or "")
    ok, why = P.config_ready(entry, timeout=timeout)
    if not ok:
        return {"ok": False, "error": why or "端点不可达或未报告模型",
                "hint": "本地服务确认已启动；云端检查 Key 与 base_url（多以 /v1 结尾）",
                "base_url": base, "models": [],
                "ms": int((time.time() - started) * 1000)}
    p = P.build_from_config({k: v for k, v in entry.items() if k != "name"})
    models: list[str] = []
    try:
        models = list(p._discover() or [])          # noqa: SLF001 —— 同包内部探测
    except Exception:
        models = []
    # 再问一句话，确认不是「能列模型但不能聊」。
    # 超时压到 12s 上限：配置错误时（端点黑洞）宁可快点失败，
    # 也别把 doctor / 设置界面的「测试」按钮挂死。
    try:
        p.timeout = min(float(getattr(p, "timeout", 30.0) or 30.0), 12.0)
    except (TypeError, ValueError):
        pass
    try:
        r = p.chat([{"role": "user", "content": "用一句话自我介绍。"}])
        greet = str((r or {}).get("content") or "")[:120]
    except Exception as e:
        return {"ok": False, "error": f"能列模型但聊不了：{friendly_error(e)}",
                "base_url": base, "models": models,
                "ms": int((time.time() - started) * 1000)}
    return {"ok": True, "base_url": base, "models": models, "greet": greet,
            "provider": getattr(p, "name", ""),
            "model": p._model_id() if hasattr(p, "_model_id") else "",   # noqa: SLF001
            "ms": int((time.time() - started) * 1000)}


def probe(name: str = "", *, timeout: float = 6.0) -> dict:
    """真连一次已保存的 provider：可达性 + 模型列表 + 首字延迟。"""
    entry = get_active() if not _norm_name(name) else _entry_of(_norm_name(name))
    if entry is None:
        return {"ok": False, "error": f"配置里没有 provider「{name or '(active)'}」",
                "models": [], "ms": 0}
    return _probe_entry(entry, timeout=timeout)


def probe_url(base_url: str, *, api_key: str = "", model: str = "",
              kind: str = "openai_compat", timeout: float = 6.0) -> dict:
    """**不落账**试连一个端点 —— 设置界面「测试连接」在保存前用。

    只列模型不够：能列模型但不能聊的端点（Key 没对话权限一类）照样保存不了，
    所以这里和 :func:`probe` 一样问一句话。
    """
    return _probe_entry({"kind": kind, "base_url": base_url, "api_key": api_key,
                         "model": model, "timeout": timeout}, timeout=timeout)


def status(*, timeout: float = 1.5) -> dict:
    """设置界面一屏要的全部：存档列表（带在线状态）+ 预设 + 当前 active。

    在线状态只对**本地**端点真探（并发，总预算 ``timeout``）—— 云端端点
    信任配置：每开一次设置都向境外付一次探测，既慢又把密钥暴露给探测方。
    ``online=None`` 表示「没探，信任配置」。
    """
    from . import providers as P

    entries = list_providers()          # 已打码
    targets: list[str] = []
    index: dict[str, int] = {}
    for i, e in enumerate(entries):
        if str(e.get("kind") or "") == "ollama":
            continue                    # Ollama 原生端点的探测归它自己的 available()
        base = str(e.get("base_url") or "").rstrip("/")
        if "127.0.0.1" in base or "localhost" in base:
            u = f"{base}/models"
            if u not in index:
                targets.append(u)
            index[u] = i
    online: dict[str, bool] = {}
    if targets:
        try:
            online = {u: bool(m) for u, m in
                      P.probe_many(targets, timeout=timeout).items()}
        except Exception:
            online = {}
    for e in entries:
        e["online"] = None
    for u, i in index.items():
        entries[i]["online"] = bool(online.get(u))
    return {"active": active_name(), "providers": entries,
            "presets": [dict(key=k, **v) for k, v in PRESETS.items()],
            "describe": describe_active()}


def raw_request(base_url: str, path: str, *, api_key: str = "",
                timeout: float = 6.0) -> Any:
    """调试用：直接打一个 JSON GET（返回解析后的对象或抛异常）。"""
    url = base_url.rstrip("/") + path
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except ValueError as e:
        raise ValueError(f"不是合法 JSON：{body[:120]}") from e


def friendly_error(e: Exception) -> str:
    """把 urllib 的异常翻译成用户能动手修的一句话。"""
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403):
            return "API Key 不被接受（401/403）—— 检查是否复制完整、是否欠费"
        if e.code == 404:
            return "端点 404 —— base_url 多半少了 /v1 或多了层级"
        if e.code == 429:
            return "触发限流（429）—— 稍后重试或换模型"
        return f"端点返回 HTTP {e.code}"
    if isinstance(e, (urllib.error.URLError, OSError, TimeoutError)):
        return "连不上端点 —— 本地服务确认已启动；云端确认网络与代理"
    return f"{type(e).__name__}: {e}"
