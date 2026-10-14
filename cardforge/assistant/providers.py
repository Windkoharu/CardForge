"""LLM 接入层 —— 四路 provider + 一路无 LLM 降级。

设计要点
--------
1. **只用标准库**（``urllib`` + ``concurrent.futures``），零第三方依赖。
2. **探测必须快且静默。** :func:`detect_provider` 的总预算是
   :data:`DETECT_BUDGET_SEC`（1.5s），所有候选端点**并发**探测
   （每个 :data:`PROBE_TIMEOUT_SEC`），连不上就当作不存在 ——
   本机没跑 Ollama 时绝不能把 doctor / UI 卡住几秒。
   兼容端点探的是 ``/models`` 而不是根路径：真实服务（LM Studio / vLLM /
   Ollama 兼容层）对 ``GET /v1`` 一律回 404，探根路径会把**活服务也探成不在线**。
3. **网络错误一律转成** :class:`~cardforge.core.errors.LLMUnavailable` **并带中文 hint**，
   调用方（``chat.py``）拿它当「降级信号」而不是「故障」。
4. **NullProvider 是正式通路，不是占位。** 它有 ``responder`` 回调，
   由 ``chat.py`` 注入规则引擎（意图 → 工具 → 模板），所以「本机一个 LLM 都没配」
   时 ``cardforge ask`` 依然给出有信息量的中文回答。

Provider 顺序（``prefer="auto"``）：
``openai_compat``（环境变量优先）→ **存档配置**（``llm_config`` 的 active，
即界面里保存的模型）→ 本机常见兼容端口 → ``ollama`` → ``none``。
``prefer="config"`` 则只看存档配置（不可达即降级，不回落本机端口）。
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, Optional, Protocol, runtime_checkable

from ..core.errors import LLMUnavailable

__all__ = ["LLMProvider", "NullProvider", "OpenAICompatProvider", "OllamaProvider",
           "LMStudioProvider", "detect_provider", "list_providers", "reset_probe_cache",
           "probe_many", "probe_models", "config_ready", "build_from_config",
           "DETECT_BUDGET_SEC", "PROBE_TIMEOUT_SEC", "PROVIDER_KEYS"]

#: 探测预算（总）与单次探测超时（秒）—— 实测约束，见 tools/selfcheck_assistant.py
DETECT_BUDGET_SEC: float = 1.5
PROBE_TIMEOUT_SEC: float = 0.8

PROVIDER_KEYS: tuple[str, ...] = ("openai_compat", "ollama", "lmstudio", "none")

#: 常见「本机 OpenAI 兼容」端点（LM Studio / Ollama / vLLM / LocalAI 一类）。
#: 并列探测，靠并发把总耗时压在一个 PROBE_TIMEOUT_SEC 内。
LOCAL_COMPAT_CANDIDATES: tuple[str, ...] = (
    "http://127.0.0.1:1234/v1",     # LM Studio
    "http://127.0.0.1:11434/v1",    # Ollama 的 OpenAI 兼容层
    "http://127.0.0.1:8000/v1",     # vLLM
    "http://127.0.0.1:8080/v1",     # LocalAI / 各类壳
)

OLLAMA_BASE_DEFAULT: str = "http://127.0.0.1:11434"
LMSTUDIO_BASE_DEFAULT: str = "http://127.0.0.1:1234/v1"


# ══════════════════════════════════════════════════════════════════════
#  接口
# ══════════════════════════════════════════════════════════════════════
@runtime_checkable
class LLMProvider(Protocol):
    """统一对话接口。``chat`` 返回 ``{"content": str, "tool_calls": [{"name","args"}]}``。"""

    name: str

    def available(self) -> bool:
        ...

    def chat(self, messages: list[dict], *, tools: Optional[list[dict]] = None,
             stream: bool = False, on_delta: Optional[Callable[[str], None]] = None) -> dict:
        ...


# ══════════════════════════════════════════════════════════════════════
#  底层 HTTP（标准库，失败静默）
# ══════════════════════════════════════════════════════════════════════
def _headers(api_key: str = "") -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _request_json(url: str, payload: Optional[dict] = None, *,
                  api_key: str = "", timeout: float = PROBE_TIMEOUT_SEC,
                  headers: Optional[dict] = None) -> Any:
    """发一个 JSON 请求；网络/解析失败抛 :class:`LLMUnavailable`（带中文 hint）。"""
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or _headers(api_key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise LLMUnavailable(f"LLM 端点返回 HTTP {e.code}",
                             hint="检查模型是否已加载、API Key 与端点路径（多数本地服务用 /v1）。",
                             detail={"url": url, "status": e.code}) from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise LLMUnavailable(f"LLM 端点不可达：{url}",
                             hint="该服务没在本机运行。启动它，或什么都不配 —— "
                                  "没有 LLM 时艾莉娅会走规则引擎，功能不缺失。",
                             detail={"url": url, "error": str(e)}) from e
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except ValueError as e:
        raise LLMUnavailable(f"LLM 端点返回的不是合法 JSON：{url}",
                            hint="确认这是 OpenAI 兼容端点（路径通常以 /v1 结尾）。",
                            detail={"url": "url", "error": str(e)}) from e


def _try_probe(url: str, *, timeout: float = PROBE_TIMEOUT_SEC) -> Optional[dict]:
    """探测用：**任何异常都返回 None**（探测阶段不许炸出去）。"""
    try:
        out = _request_json(url, timeout=timeout)
    except Exception:
        return None
    return out if isinstance(out, (dict, list)) else None


def _models_of(payload: Any) -> list[str]:
    """从**已经取到的** ``/models`` 响应里抠模型 id。

    认两种形状：``{"data": [{"id": …}]}``（OpenAI 标准）与裸列表
    （Ollama 兼容层 / LocalAI 各有点随意）。探测结果复用全靠它 ——
    并发探到的响应当场解析，不必再发一次请求。
    """
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    ids: list[str] = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict):
            mid = it.get("id") or it.get("name") or it.get("model")
            if mid:
                ids.append(str(mid))
        elif it:
            ids.append(str(it))
    return ids


def _probe_models(url: str, *, timeout: float = PROBE_TIMEOUT_SEC) -> list[str]:
    """从 OpenAI 兼容端点取模型 id 列表；不可用返回空表。"""
    return _models_of(_try_probe(url, timeout=timeout))


def _local_probe_urls() -> list[str]:
    """环境变量 / 存档配置里**本机**端点的 ``/models`` 探测目标。

    把它们并进 :func:`_probe_all` 的同一批并发探测，是为了不串行重复探：
    每个没在听的本机端口都要等满一次 :data:`PROBE_TIMEOUT_SEC`，
    ``detect_provider('auto')`` 冷缓存的总耗时会被拖到超时值的两三倍
    （自测 1.1 的预算阈值就是这么被击穿的）。
    """
    urls: list[str] = []

    def _add(base: str) -> None:
        base = str(base or "").strip().rstrip("/")
        if not base.startswith("http"):
            base = "http://" + base
        if "127.0.0.1" in base or "localhost" in base:
            urls.append(f"{base}/models")

    env_base = _env("CARDFORGE_LLM_BASE_URL") or _env("OPENAI_BASE_URL") \
        or _env("OPENAI_API_BASE")
    if env_base:
        _add(env_base)
    try:
        from . import llm_config
        active = llm_config.get_active()
    except Exception:
        active = None
    if active:
        kind = str(active.get("kind") or "openai_compat").strip().lower()
        if kind != "ollama" and active.get("base_url"):
            _add(active["base_url"])
    return urls


def _probe_targets(extra: Optional[Iterable[str]] = None) -> list[str]:
    """一次并发探测要覆盖的全部 URL（键即 URL 本身，供结果复用）。"""
    urls = [f"{u}/models" for u in LOCAL_COMPAT_CANDIDATES]
    urls.append(f"{OLLAMA_BASE_DEFAULT}/api/tags")
    for u in extra or ():
        if u not in urls:
            urls.append(u)
    return urls


def _probe_all(urls: list[str], *, timeout: float = PROBE_TIMEOUT_SEC) -> dict[str, Any]:
    """并发探测多个端点 —— 总耗时 ≈ 单个超时，而不是 N 倍。"""
    if not urls:
        return {}
    out: dict[str, Any] = {}
    workers = min(8, max(1, len(urls)))
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_try_probe, u, timeout=timeout): u for u in urls}
            for fut, u in futs.items():
                try:
                    out[u] = fut.result()
                except Exception:
                    out[u] = None
    except Exception:
        # 线程池本身出问题（极窄路径）：退化为串行，仍保证不抛
        for u in urls:
            out[u] = _try_probe(u, timeout=timeout)
    return out


# ══════════════════════════════════════════════════════════════════════
#  OpenAI 兼容（LM Studio / vLLM / OneAPI / DeepSeek / 云端 …）
# ══════════════════════════════════════════════════════════════════════
class OpenAICompatProvider:
    """任意 OpenAI ``/chat/completions`` 兼容端点。"""

    name = "openai_compat"

    def __init__(self, base_url: str, *, api_key: str = "", model: str = "",
                 timeout: float = 30.0):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.timeout = timeout
        self._models: Optional[list[str]] = None

    # ── 能力 ────────────────────────────────────────────────────
    def available(self) -> bool:
        try:
            return bool(self._discover())
        except Exception:
            return False

    def _discover(self) -> list[str]:
        if self._models is None:
            self._models = _probe_models(f"{self.base_url}/models",
                                         timeout=PROBE_TIMEOUT_SEC) \
                if "127.0.0.1" in self.base_url or "localhost" in self.base_url \
                else ["(env model)"] if self.model else []
            if self.model and not self._models:
                self._models = [self.model]
        return self._models

    def _model_id(self) -> str:
        if self.model:
            return self.model
        ms = self._discover()
        return ms[0] if ms else ""

    def resolved_model(self) -> str:
        """实际生效的模型 id（配置填了就用填的，否则取端点报告的第一个）。

        端点不在响应里回显 ``model`` 时（不少本地服务就这样），调用方要靠它
        把「刚才那句话是谁说的」讲清楚 ——  UI 上的模型 chip 和起草结果都用。
        """
        try:
            return self._model_id()
        except Exception:
            return ""

    # ── 对话 ────────────────────────────────────────────────────
    def chat(self, messages: list[dict], *, tools: Optional[list[dict]] = None,
             stream: bool = False, on_delta: Optional[Callable[[str], None]] = None) -> dict:
        model = self._model_id()
        if not model:
            raise LLMUnavailable(f"{self.name} 端点没报告可用模型",
                                 hint=f"在 {self.base_url} 加载一个模型，或设置环境变量 OPENAI_MODEL。")
        payload = {"model": model, "messages": list(messages), "stream": bool(stream)}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if stream and on_delta is not None:
            return self._chat_stream(payload, on_delta)
        data = _request_json(f"{self.base_url}/chat/completions", payload,
                             api_key=self.api_key, timeout=self.timeout)
        return _from_openai_message(data, self.name)

    def _chat_stream(self, payload: dict, on_delta: Callable[[str], None]) -> dict:
        """SSE 增量。逐行解析 ``data:`` ；任何解析问题都降级为整段返回。"""
        payload = dict(payload, stream=True)
        req = urllib.request.Request(f"{self.base_url}/chat/completions",
                                     data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers=_headers(self.api_key))
        pieces: list[str] = []
        tool_calls: list[dict] = []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        d = json.loads(chunk)
                    except ValueError:
                        continue
                    for ch in (d.get("choices") or []):
                        delta = ch.get("delta") or {}
                        text = delta.get("content") or ""
                        if text:
                            pieces.append(text)
                            try:
                                on_delta(text)
                            except Exception:
                                pass
                        for tc in (delta.get("tool_calls") or []):
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                tool_calls.append({"name": fn["name"],
                                                   "args": _args_of(fn.get("arguments"))})
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise LLMUnavailable(f"{self.name} 流式响应中断",
                                 hint="改用非流式，或确认端点支持 SSE。",
                                 detail={"error": str(e)}) from e
        return {"content": "".join(pieces), "tool_calls": tool_calls,
                "provider": self.name, "model": payload.get("model", ""), "stream": True}


def _args_of(raw: Any) -> dict:
    """工具参数可能是 dict 也可能是 JSON 串；解析失败给空 dict（由内核兜住）。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {"value": v}
        except ValueError:
            return {}
    return {}


def _from_openai_message(data: Any, provider: str) -> dict:
    """把 OpenAI 风格响应归一成 ``{"content","tool_calls","provider","model"}``。"""
    if not isinstance(data, dict):
        raise LLMUnavailable(f"{provider} 返回结构无法解析",
                             hint="该端点可能不是 OpenAI 兼容的 /v1 路径。")
    if data.get("error"):
        err = data["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise LLMUnavailable(f"{provider} 报错：{msg}",
                             hint="常见原因是上下文超限或模型未加载，可换小模型再试。")
    choices = data.get("choices") or []
    msg = (choices[0].get("message") or {}) if choices else {}
    calls: list[dict] = []
    for tc in (msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        if fn.get("name"):
            calls.append({"name": str(fn["name"]), "args": _args_of(fn.get("arguments"))})
    return {"content": str(msg.get("content") or ""), "tool_calls": calls,
            "provider": provider, "model": str(data.get("model") or "")}


# ══════════════════════════════════════════════════════════════════════
#  Ollama（原生 /api/chat）
# ══════════════════════════════════════════════════════════════════════
class OllamaProvider(OpenAICompatProvider):
    """零配置本地：``http://127.0.0.1:11434``。走原生 ``/api/chat``。"""

    name = "ollama"

    def __init__(self, base: str = OLLAMA_BASE_DEFAULT, *, model: str = "",
                 timeout: float = 60.0):
        super().__init__(base, model=model, timeout=timeout)
        self.base = base.rstrip("/")

    def _discover(self) -> list[str]:
        if self._models is None:
            out = _try_probe(f"{self.base}/api/tags", timeout=PROBE_TIMEOUT_SEC)
            tags = []
            if isinstance(out, dict):
                for m in (out.get("models") or []):
                    if isinstance(m, dict) and m.get("name"):
                        tags.append(str(m["name"]))
            self._models = tags
        return self._models

    def available(self) -> bool:
        try:
            return bool(self._discover())
        except Exception:
            return False

    def chat(self, messages: list[dict], *, tools: Optional[list[dict]] = None,
             stream: bool = False, on_delta: Optional[Callable[[str], None]] = None) -> dict:
        model = self.model or (self._discover()[0] if self._discover() else "")
        if not model:
            raise LLMUnavailable("Ollama 在线但没有任何已拉取的模型",
                                 hint="先执行 `ollama pull qwen2.5:3b`（或本地已备的模型）。")
        payload: dict[str, Any] = {"model": model, "messages": list(messages),
                                   "stream": bool(stream and on_delta is not None)}
        if tools:
            payload["tools"] = tools
        if payload["stream"]:
            return self._chat_stream_api(payload, on_delta)   # type: ignore[arg-type]
        data = _request_json(f"{self.base}/api/chat", payload, timeout=self.timeout)
        if not isinstance(data, dict):
            raise LLMUnavailable("Ollama 返回结构无法解析", hint="确认 /api/chat 可用。")
        msg = data.get("message") or {}
        calls = []
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            if fn.get("name"):
                calls.append({"name": str(fn["name"]), "args": _args_of(fn.get("arguments"))})
        return {"content": str(msg.get("content") or ""), "tool_calls": calls,
                "provider": self.name, "model": model}

    def _chat_stream_api(self, payload: dict, on_delta: Callable[[str], None]) -> dict:
        req = urllib.request.Request(f"{self.base}/api/chat",
                                     data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers=_headers())
        pieces: list[str] = []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    text = ((d.get("message") or {}).get("content")) or d.get("response") or ""
                    if text:
                        pieces.append(text)
                        try:
                            on_delta(text)
                        except Exception:
                            pass
                    if d.get("done"):
                        break
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise LLMUnavailable("Ollama 流式响应中断",
                                 hint="可改为非流式，或重启 Ollama。",
                                 detail={"error": str(e)}) from e
        return {"content": "".join(pieces), "tool_calls": [],
                "provider": self.name, "model": payload.get("model", ""), "stream": True}


# ══════════════════════════════════════════════════════════════════════
#  LM Studio
# ══════════════════════════════════════════════════════════════════════
class LMStudioProvider(OpenAICompatProvider):
    """零配置本地：``http://127.0.0.1:1234/v1``（本质是 OpenAI 兼容壳）。"""

    name = "lmstudio"

    def __init__(self, base_url: str = LMSTUDIO_BASE_DEFAULT, *, model: str = "",
                 timeout: float = 30.0):
        super().__init__(base_url, model=model, timeout=timeout)


# ══════════════════════════════════════════════════════════════════════
#  无 LLM 降级
# ══════════════════════════════════════════════════════════════════════
class NullProvider:
    """完全离线通路：**模板话术 + 规则引擎**，功能不缺失，只是不「聊天」。

    ``responder`` 由 ``chat.py`` 注入（签名 ``(text, ctx) -> dict``）。没注入时
    返回内置的兜底话术，仍然不抛异常。
    """

    name = "none"

    def __init__(self, responder: Optional[Callable[[str, dict], dict]] = None):
        self._responder = responder

    def set_responder(self, responder: Callable[[str, dict], dict]) -> None:
        """注入规则引擎（延迟绑定，避免 providers ↔ chat 循环导入）。"""
        self._responder = responder

    def available(self) -> bool:
        return True          # 降级通路永远可用

    def chat(self, messages: list[dict], *, tools: Optional[list[dict]] = None,
             stream: bool = False, on_delta: Optional[Callable[[str], None]] = None) -> dict:
        text = ""
        for m in reversed(list(messages or [])):
            if isinstance(m, dict) and m.get("role") == "user":
                text = str(m.get("content") or "")
                break
        if self._responder is not None:
            try:
                out = self._responder(text, {"tools": tools, "messages": messages})
            except Exception as e:      # 规则引擎出问题也要给出话，不能整条链路哑掉
                out = {"content": f"（规则引擎异常，已降级为静态话术：{e}）", "tool_calls": []}
        else:
            out = {"content": "当前未接入语言模型，走的是模板通路："
                              "把卡名和质量门编号告诉我，我按确定性结论回答。",
                   "tool_calls": []}
        ctx = out.get("context") if isinstance(out, dict) else None
        reply = str((out.get("content") if isinstance(out, dict) else "") or "")
        if stream and on_delta is not None:
            try:
                on_delta(reply)
            except Exception:
                pass
        return {"content": reply,
                "tool_calls": list(out.get("tool_calls") or []) if isinstance(out, dict) else [],
                "context": ctx if isinstance(ctx, dict) else {},
                "state": str(out.get("state") or "") if isinstance(out, dict) else "",
                "provider": self.name}


# ══════════════════════════════════════════════════════════════════════
#  从存档配置组装（llm_config 消费点）
# ══════════════════════════════════════════════════════════════════════
def build_from_config(cfg: dict) -> LLMProvider:
    """把 ``llm_config`` 里的一笔账组装成 provider 实例。

    ``cfg`` 至少要有 ``kind`` 与 ``base_url``；缺省按 ``openai_compat`` 对待
    （云端各家兼容层都是这一路）。本函数**不探测**——探测是调用方的事，
    这样「配置错」和「端点挂」能分开报。
    """
    cfg = dict(cfg or {})
    kind = str(cfg.get("kind") or "openai_compat").strip().lower()
    base = str(cfg.get("base_url") or "").strip().rstrip("/")
    key = str(cfg.get("api_key") or "")
    model = str(cfg.get("model") or "").strip()
    try:
        timeout = float(cfg.get("timeout") or 30.0)
    except (TypeError, ValueError):
        timeout = 30.0
    if kind == "ollama":
        return OllamaProvider(base or OLLAMA_BASE_DEFAULT, model=model, timeout=timeout)
    if kind in ("lmstudio", "lm_studio"):
        return LMStudioProvider(base or LMSTUDIO_BASE_DEFAULT, model=model, timeout=timeout)
    return OpenAICompatProvider(base, api_key=key, model=model, timeout=timeout)


def _config_provider(probed: Optional[dict] = None) -> tuple[Optional[LLMProvider], dict]:
    """读存档配置的 active provider。没配 / 不可达都返回 ``(None, info)``。

    延迟 import：``llm_config`` 也要反过来用本模块的 provider，模块级导入会成环。
    ``probed`` 是调用方 :func:`_probe_all` 的现成结果（含本机配置端点的
    ``/models``）—— 传进来就不重复探，冷启动少付一次超时。
    """
    try:
        from . import llm_config
    except Exception:
        return None, {"reason": "llm_config 模块不可用"}
    try:
        active = llm_config.get_active()
    except Exception:
        return None, {"reason": "读取 LLM 配置失败"}
    if not active:
        return None, {"reason": "尚未配置 LLM（cardforge llm preset …）"}
    ok, why = config_ready(active, probed=probed)
    if not ok:
        return None, {"reason": f"已配置的「{active.get('name', '')}」{why}，已降级；"
                                "用 cardforge llm test 排查"}
    p = build_from_config(active)
    return p, {"base_url": getattr(p, "base_url", "") or getattr(p, "base", ""),
               "model": p._model_id() if hasattr(p, "_model_id") else "",   # noqa: SLF001
               "source": "config", "name": str(active.get("name") or "")}


def config_ready(cfg: dict, probed: Optional[dict] = None,
                 *, timeout: float = PROBE_TIMEOUT_SEC) -> tuple[bool, str]:
    """存档配置**是否真的能用** —— 探测策略按端点性质分流。

    本地端点（127.0.0.1/localhost）必须真探到模型列表：配了模型名不等于在线，
    服务没起时若放行，每句话都要等满超时才降级 —— 用户看到的是「卡」而不是「没开」。
    云端端点信任配置（不每句都付一次跨境探测），聊不动时由 ``chat`` 降级并说明。
    Ollama 走原生 ``/api/tags``，由它自己的 ``available()`` 探。

    ``probed``（键为 ``/models`` URL）给的是复用机会：调用方已经并发探过，
    就别再串行探一遍。没给就自己探（``timeout`` 控制这次探测的耐心）。
    """
    cfg = dict(cfg or {})
    p = build_from_config(cfg)
    base = getattr(p, "base_url", "") or getattr(p, "base", "")
    kind = str(cfg.get("kind") or "openai_compat").strip().lower()
    is_local = "127.0.0.1" in base or "localhost" in base
    if kind != "ollama" and is_local:
        models_url = f"{base.rstrip('/')}/models"
        if probed is not None and models_url in probed:
            models = _models_of(probed[models_url])
        else:
            models = probe_models(models_url, timeout=timeout)
        if models:
            return True, ""
        return False, f"本地端点不在线（{base}）—— 启动服务后自动恢复"
    try:
        return (True, "") if p.available() else (False, f"端点不可达（{base}）")
    except Exception:
        return False, f"端点探测异常（{base}）"


def probe_models(url: str, *, timeout: float = PROBE_TIMEOUT_SEC) -> list[str]:
    """公开版 :func:`_probe_models` —— 给 ``llm_config`` 的设置界面/测试用。"""
    return _probe_models(url, timeout=timeout)


def probe_many(urls: list[str], *, timeout: float = PROBE_TIMEOUT_SEC) -> dict[str, list[str]]:
    """并发探测一批 ``/models`` URL，返回 ``{url: [模型id…]}``（不可用为空表）。

    设置界面列「哪个 provider 在线」用。本地端点才值得探 —— 云端端点
    每开一次设置都向境外付一次探测，既慢又把密钥暴露给探测方，
    所以**调用方自行过滤**，本函数不判断端点性质。
    """
    probed = _probe_all(list(urls or []), timeout=timeout)
    return {u: _models_of(v) for u, v in probed.items()}


# ══════════════════════════════════════════════════════════════════════
#  探测 / 注册表
# ══════════════════════════════════════════════════════════════════════
_STATE: dict[str, Any] = {"provider": None, "null": None, "cache": None,
                          "probed": {}, "stamp": 0.0}
_LOCK = threading.RLock()

#: 「什么都没探测到」的缓存有效期（秒）。命中的 provider 永久缓存，
#: 负结论只缓存这么久 —— 这样用户中途启动 Ollama 后助手能自己发现，
#: 又不会每句话都付一次探测的代价。
NEGATIVE_TTL_SEC: float = 30.0


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default or "").strip()


def _env_compat() -> Optional[OpenAICompatProvider]:
    """环境变量优先：``OPENAI_BASE_URL`` / ``OPENAI_API_KEY`` / ``OPENAI_MODEL``
    （另接受 ``OPENAI_API_BASE``、``CARDFORGE_LLM_*``）。"""
    base = _env("CARDFORGE_LLM_BASE_URL") or _env("OPENAI_BASE_URL") or _env("OPENAI_API_BASE")
    key = _env("CARDFORGE_LLM_API_KEY") or _env("OPENAI_API_KEY")
    model = _env("CARDFORGE_LLM_MODEL") or _env("OPENAI_MODEL")
    if not (base or key or model):
        return None
    base = base or "https://api.openai.com/v1"
    if not base.startswith("http"):
        base = "http://" + base
    return OpenAICompatProvider(base, api_key=key, model=model)


def _build(prefer: str) -> tuple[LLMProvider, dict]:
    """按 ``prefer`` 组装 provider。找不到就返回 :class:`NullProvider`。"""
    prefer = (prefer or "auto").strip().lower()
    null = NullProvider(responder=(_STATE.get("null") or NullProvider())._responder)

    if prefer in ("none", "null", "off", "offline"):
        return null, {"reason": "显式要求离线（prefer=none）"}

    if prefer in ("config", "saved", "file"):
        p, info = _config_provider()
        if p is not None:
            return p, info
        return null, info

    if prefer in ("openai_compat", "openai", "compat"):
        p = _env_compat() or OpenAICompatProvider(_env("CARDFORGE_LLM_BASE_URL",
                                                       "http://127.0.0.1:1234/v1"))
        if p.available():
            return p, {"base_url": p.base_url, "model": p._model_id()}
        return null, {"reason": f"openai_compat({p.base_url}) 不可达，已降级为无 LLM 通路"}

    if prefer == "ollama":
        p = OllamaProvider(_env("OLLAMA_BASE_URL", OLLAMA_BASE_DEFAULT),
                           model=_env("OLLAMA_MODEL"))
        if p.available():
            return p, {"base_url": p.base, "model": p._model_id()}
        return null, {"reason": "ollama 不可达，已降级为无 LLM 通路"}

    if prefer in ("lmstudio", "lm_studio", "lm"):
        p = LMStudioProvider(_env("LMSTUDIO_BASE_URL", LMSTUDIO_BASE_DEFAULT),
                             model=_env("LMSTUDIO_MODEL"))
        if p.available():
            return p, {"base_url": p.base_url, "model": p._model_id()}
        return null, {"reason": "lmstudio 不可达，已降级为无 LLM 通路"}

    # ── auto：存档配置优先，其次本机端口，最后 Ollama ──────────────
    # 顺序即语义：用户在界面里保存过模型 → 用它（云端直连）；
    # 没保存过 → 和旧版一样探本机常见端口。环境变量比存档更优先（下面第一站）。
    env_p = _env_compat()
    # 一次并发探测覆盖：本机候选 + Ollama 原生 + 环境变量/存档配置里的本机端点。
    # 后面每一站都复用这份结果 —— 死端口只付一次超时，不是每站各付一次。
    probed = _probe_all(_probe_targets(_local_probe_urls()))
    _STATE["probed"] = dict(probed)

    if env_p is not None:
        ok, why = config_ready(
            {"kind": "openai_compat", "base_url": env_p.base_url,
             "api_key": env_p.api_key, "model": env_p.model},
            probed=probed)
        if ok:
            return env_p, {"base_url": env_p.base_url, "model": env_p._model_id(),
                           "source": "env"}
        # 环境变量指向的端点不在线：不就此罢手，继续往下找本机通路。

    cfg_p, cfg_info = _config_provider(probed=probed)
    if cfg_p is not None:
        return cfg_p, cfg_info

    for u in LOCAL_COMPAT_CANDIDATES:
        models = _models_of(probed.get(f"{u}/models"))
        if not models:
            continue
        if ":11434" in u:
            return OllamaProvider(OLLAMA_BASE_DEFAULT), {
                "base_url": OLLAMA_BASE_DEFAULT, "model": models[0],
                "source": "ollama-openai-layer"}
        p = OpenAICompatProvider(u, api_key=_env("OPENAI_API_KEY"), model=models[0])
        return p, {"base_url": u, "model": models[0], "source": "local_port"}

    tags = probed.get(f"{OLLAMA_BASE_DEFAULT}/api/tags")
    if isinstance(tags, dict):
        names = [str(m.get("name")) for m in (tags.get("models") or [])
                 if isinstance(m, dict) and m.get("name")]
        if names:
            p = OllamaProvider(OLLAMA_BASE_DEFAULT, model=_env("OLLAMA_MODEL"))
            return p, {"base_url": p.base, "model": p._model_id(), "source": "ollama"}

    return null, {"reason": "未探测到任何可用 LLM 端点，走无 LLM 规则通路（功能不缺失）"}


def detect_provider(prefer: str = "auto", *, refresh: bool = False) -> LLMProvider:
    """探测并缓存 provider；永远返回可用对象（最差是 :class:`NullProvider`）。

    正结论（真找到端点）永久缓存；负结论只缓存 :data:`NEGATIVE_TTL_SEC`，
    这样「先没开 Ollama、后来开了」不需要重启进程，也不会每句话都探测一次。
    """
    with _LOCK:
        base = (prefer or "auto").lower()
        # 缓存键带上 llm_config 的 (版本, mtime) —— 否则「刚在界面里换了模型」
        # 要等 NEGATIVE_TTL 或重启进程才生效（保存一次 rev+1，缓存立即失效）；
        # mtime 那一半管**跨进程**：用户在别的终端用 CLI 改了配置文件，
        # 服务器进程的 revision 不会动，但文件 mtime 会变。
        # ⚠ 缓存键 ≠ prefer：``_build`` 认的是裸 prefer（"config"/"none"/…），
        # 把带 ``#cfg…`` 后缀的复合键喂进去，所有非 auto 的 prefer 都会被
        # misroute 到 auto 链（缺陷 #35，#8 引入）。
        try:
            from . import llm_config as _lc
            key = f"{base}#cfg{_lc.stamp()}"
        except Exception:
            key = base
        cached = _STATE.get("provider")
        negative = isinstance(cached, NullProvider)
        fresh = (time.time() - float(_STATE.get("stamp") or 0.0)) < NEGATIVE_TTL_SEC
        if not refresh and _STATE.get("cache") == key and cached is not None \
                and (not negative or fresh):
            return cached
        provider, info = _build(base)
        if isinstance(provider, NullProvider):
            provider.set_responder(getattr(_STATE.get("null"), "_responder", None))
            _STATE["null"] = provider
        _STATE["provider"] = provider
        _STATE["cache"] = key
        _STATE["info"] = info
        _STATE["stamp"] = time.time()
        return provider


def provider_info() -> dict:
    """最近一次探测的结论（doctor / UI 用；含降级原因）。"""
    with _LOCK:
        p = _STATE.get("provider")
        return {"provider": getattr(p, "name", "") if p else "",
                "detail": dict(_STATE.get("info") or {})}


def set_responder(responder: Callable[[str, dict], dict]) -> None:
    """给 :class:`NullProvider` 注入规则引擎（``chat.py`` 导入时调用）。"""
    null = _STATE.get("null")
    if null is None:
        null = NullProvider(responder=responder)
        _STATE["null"] = null
    else:
        null.set_responder(responder)
    cur = _STATE.get("provider")
    if isinstance(cur, NullProvider):
        cur.set_responder(responder)


def reset_probe_cache() -> None:
    """清空探测缓存（自测/切换环境用）。"""
    with _LOCK:
        _STATE.update({"provider": None, "cache": None, "info": {},
                       "probed": {}, "stamp": 0.0})


def list_providers() -> list[dict]:
    """列出各通路状态；探测同样受 :data:`PROBE_TIMEOUT_SEC` 约束且静默。

    存档配置（``llm_config``）作为第一行给出 —— 用户在界面里保存的模型
    应该在这里一眼看见，而不是只出现在环境变量语义里。
    """
    probed = _probe_all(_probe_targets(_local_probe_urls()))
    env_p = _env_compat()
    out: list[dict] = []
    # 存档配置行
    try:
        from . import llm_config as _lc
        saved = _lc.list_providers()
        active = next((s for s in saved if s.get("active")), None)
        if active:
            reach, why = config_ready(active, probed=probed)
            out.append({
                "key": "config",
                "label": f"存档配置 · {active['name']}（{active.get('kind', '')}）",
                "available": bool(reach),
                "endpoint": active.get("base_url", ""),
                "model": active.get("model", ""),
                "hint": "" if reach else (why or "端点当前不可达；用 cardforge llm test 排查"),
            })
    except Exception:
        pass
    compat = [u for u in LOCAL_COMPAT_CANDIDATES if _models_of(probed.get(f"{u}/models"))]
    out.append({
        "key": "openai_compat",
        "label": "OpenAI 兼容端点（LM Studio / vLLM / OneAPI / 云端）",
        "available": bool(env_p is not None and env_p.available()) or bool(compat),
        "endpoint": (env_p.base_url if env_p else (compat[0] if compat else "")),
        "hint": "设置 OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL 即可指向任意兼容端点；"
                "不设则自动尝试本机常见端口。" if not compat else "本机已发现兼容端点。",
    })
    ollama_ok = isinstance(probed.get(f"{OLLAMA_BASE_DEFAULT}/api/tags"), dict)
    out.append({
        "key": "ollama",
        "label": "Ollama（零配置本地）",
        "available": ollama_ok,
        "endpoint": OLLAMA_BASE_DEFAULT if ollama_ok else "",
        "hint": "未探测到服务。启动 Ollama 并 `ollama pull` 一个模型后重试。" if not ollama_ok else "",
    })
    lm_ok = bool(_models_of(probed.get(f"{LMSTUDIO_BASE_DEFAULT}/models")))
    out.append({
        "key": "lmstudio",
        "label": "LM Studio（本机 :1234）",
        "available": bool(lm_ok),
        "endpoint": LMSTUDIO_BASE_DEFAULT if lm_ok else "",
        "hint": "未探测到服务。在 LM Studio 里启动 Developer Server 后重试。" if not lm_ok else "",
    })
    out.append({
        "key": "none",
        "label": "无 LLM 降级（模板话术 + 规则引擎）",
        "available": True,
        "endpoint": "",
        "hint": "永远可用。结论仍然来自确定性内核，只是表达由模板拼装。",
    })
    return out
