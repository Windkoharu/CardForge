"""``/api/assistant/*`` —— 星奏·艾莉娅。

她在架构里的位置是**表达层**：所有判断都来自确定性内核，她只负责翻译成人话、
引导下一步、给参谋意见。没有 LLM 时她走 ``NullProvider``（规则 + 模板），
**功能不缺，只是不那么会说话**。
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Optional

from ..core import errors, paths
from . import kernel as K
from .http import Request, Response

__all__ = ["register"]

_SESSIONS: dict[str, Any] = {}
_LOCK = threading.Lock()
_MAX_SESSIONS = 32


def register(app) -> None:

    @app.get("/api/assistant/status")
    def assistant_status(req: Request) -> dict:
        """当前用哪个 provider、能不能用、降级了会怎样。"""
        a = K.try_import("cardforge.assistant")
        if a is None:
            return {"ok": False, "available": False,
                    "error": "assistant 模块不可用",
                    "hint": "艾莉娅还没装上来；造卡主流程不受影响",
                    "name": "星奏·艾莉娅"}
        out: dict[str, Any] = {"ok": True, "available": True,
                              "name": getattr(a, "ASSISTANT_NAME", "星奏·艾莉娅")}
        prov = K.try_import("cardforge.assistant.providers")
        if prov is None:
            out["provider"] = "unknown"
            out["hint"] = "assistant.providers 不可用"
            return out
        t0 = time.perf_counter()
        try:
            p = prov.detect_provider(prefer=req.str_arg("prefer", "auto"))
            out["provider"] = getattr(p, "name", "none")
            out["provider_available"] = bool(p.available()) if hasattr(p, "available") else None
        except Exception as e:
            out["provider"] = "error"
            out["error"] = f"{type(e).__name__}: {e}"
        out["probe_ms"] = int((time.perf_counter() - t0) * 1000)
        try:
            out["providers"] = list(prov.list_providers())
        except Exception:
            pass
        if out.get("provider") in ("none", "null", "error"):
            out["degraded"] = True
            out["hint"] = ("没检测到本地 LLM。艾莉娅会用规则回答（质量门结论、"
                           "知识库检索、下一步建议都照给），只是不会自由聊天。"
                           "想要更自然的对话：起一个 OpenAI 兼容端点、"
                           "Ollama(11434) 或 LM Studio(1234)，再刷新。")
        # 用户**存**的是哪个模型（可能和实测不同：env 优先、或配置指向的服务没起）。
        # 抽屉芯片要能说清「你存了什么」，而不只是「现在谁在说话」。
        lc = K.try_import("cardforge.assistant.llm_config")
        if lc is not None:
            try:
                out["llm_active"] = lc.describe_active()
            except Exception:
                pass
        return out

    @app.get("/api/assistant/personas")
    def assistant_personas(req: Request) -> dict:
        per = K.require("cardforge.assistant.persona", "助手人格模块")
        out: list[dict] = []
        for key, val in (getattr(per, "PERSONAS", {}) or {}).items():
            row = {"key": key}
            if isinstance(val, dict):
                row.update({k: v for k, v in val.items()
                            if isinstance(v, (str, int, float, bool))})
            else:
                for k in ("key", "zh", "desc", "brief"):
                    if hasattr(val, k):
                        row[k] = getattr(val, k)
            out.append(row)
        return {"ok": True, "personas": out,
                "name": getattr(per, "ASSISTANT_NAME", "星奏·艾莉娅"),
                "short": getattr(per, "ASSISTANT_NAME_SHORT", "艾莉娅")}

    @app.get("/api/assistant/line")
    def assistant_line(req: Request) -> dict:
        """给界面立绘气泡的一句话 —— **纯模板渲染**，不发 LLM、不动会话。

        ``kind`` 非空 → 问候语（default/first/idle）；
        否则走工作状态话术：``state=guide|working|alert|pass``，
        ``step/detail/next/facts`` 必须由调用方从**内核结果**逐字抄来 ——
        这一层只做语气包装（三档人格的包装规则在 persona.py，唯一真相源）。
        """
        per = K.require("cardforge.assistant.persona", "助手人格模块")
        persona = req.str_arg("persona", "professional")
        kind = req.str_arg("kind")
        if kind:
            return {"ok": True, "kind": kind, "persona": per.normalize_key(persona),
                    "text": per.greeting(persona, kind)}
        state = req.str_arg("state", "guide")
        text = per.state_line(state, persona,
                              step=req.str_arg("step", ""),
                              detail=req.str_arg("detail", ""),
                              next=req.str_arg("next", ""),
                              facts=req.str_arg("facts", ""))
        return {"ok": True, "kind": "state", "persona": per.normalize_key(persona),
                "state": per.normalize_state(state), "text": text}

    @app.post("/api/assistant/gate-line")
    def assistant_gate_line(req: Request) -> dict:
        """质量门的一句话结论（立绘气泡）。事实由**内核**从 report 生成。"""
        chat = K.require("cardforge.assistant.chat", "助手对话模块")
        fn = getattr(chat, "gate_line", None)
        if not callable(fn):
            raise errors.EnvError("chat.gate_line 不可用", "assistant 模块未完整更新")
        report = req.arg("report")
        if not isinstance(report, dict):
            raise errors.SpecError("report 必须是门的报告对象",
                                   "把 /api/gates/G1 返回的 report 原样传进来")
        try:
            text = fn(report, req.str_arg("persona", "professional"))
        except Exception as e:
            raise errors.LLMUnavailable(
                f"翻译失败：{e}", "门结论原文在「审计」弹层里仍然可读") from e
        return {"ok": True, "text": text,
                "gate": report.get("gate"), "status": report.get("status")}

    @app.post("/api/assistant/session")
    def assistant_session(req: Request) -> dict:
        chat = K.require("cardforge.assistant.chat", "助手对话模块")
        persona = req.str_arg("persona", "professional")
        context = req.arg("context") if isinstance(req.arg("context"), dict) else {}
        sess = chat.new_session(persona=persona, context=context)
        sid = getattr(sess, "id", None) or uuid.uuid4().hex[:12]
        with _LOCK:
            if len(_SESSIONS) >= _MAX_SESSIONS:
                _SESSIONS.pop(next(iter(_SESSIONS)), None)
            _SESSIONS[sid] = sess
        return {"ok": True, "session": _sid_of(sess) or sid,
                "persona": persona, "note": "会话存在内存里，重启服务后重新开始"}

    @app.post("/api/assistant/chat")
    def assistant_chat(req: Request) -> dict:
        chat = K.require("cardforge.assistant.chat", "助手对话模块")
        text = str(req.arg("text") or "").strip()
        if not text:
            raise errors.SpecError("要说的话是空的", "输入一句话再发")
        sess = _session_of(req, chat)
        context = req.arg("context")
        if isinstance(context, dict) and context:
            merged = dict(getattr(sess, "context", {}) or {})
            # 界面发来的「选中了哪张卡」历史上用 ``card`` 这个键，而内核
            # （``_card_ref`` / ``_resolve_spec``）只认 ``card_id`` —— 键名
            # 不一致时上下文被**静默丢弃**：「这张卡…」问谁都得靠猜，工作区
            # 只有一张卡时靠唯一卡兜底蒙混过关，多一张卡就答不上（缺陷 #34）。
            # 这里归一化，旧缓存页发 ``card`` 也立刻生效。
            if context.get("card") and not context.get("card_id"):
                context = dict(context)
                context["card_id"] = context["card"]
            merged.update(context)
            sess.context = merged
        try:
            res = chat.send(sess, text)
        except errors.CardForgeError:
            raise
        except Exception as e:
            raise errors.LLMUnavailable(
                f"助手应答失败：{type(e).__name__}: {e}",
                "这不阻塞你造卡：质量门结论直接看「审计」页，"
                "命令行 cardforge ask 同一句话也能跑") from e
        out = dict(res) if isinstance(res, dict) else {"reply": str(res)}
        out["session"] = _sid_of(sess)
        out.setdefault("ok", True)
        return out

    @app.post("/api/assistant/draft")
    def assistant_draft(req: Request) -> dict:
        """AI 起草卡文草稿 —— **LLM 只提议，裁决归内核**。

        请求：``concept=<概念描述>``（与 spec 至少给一个）；
        可选 ``card=<卡号>`` 或 ``spec=<CardSpec>``（作为事实底座，附赠 G1 审计）、
        ``lang``（默认 zh_cn）。
        响应：``{ok, draft, issues, counts, gate, provider, model}`` ——
        ``issues``/``gate`` 全部来自确定性内核，LLM 的自评不采信；
        没配大模型时 ``ok=false`` + ``degraded``（照实说，不编草稿）。
        """
        draft = K.require("cardforge.assistant.draft", "AI 起草模块")
        fn = getattr(draft, "draft", None)
        if not callable(fn):
            raise errors.EnvError("draft 模块不完整",
                                  "assistant/draft.py 版本过旧，请更新 cardforge")
        spec = None
        if req.arg("spec") is not None:
            try:
                spec = K.spec_from_payload(req.arg("spec"))
            except errors.CardForgeError:
                raise
            except Exception as e:
                raise errors.SpecError(f"spec 载荷无法解析：{e}",
                                       "把 /api/cards/<id> 返回的 spec 原样传进来") from e
        elif req.arg("card") is not None:
            spec = K.load_spec(req.int_arg("card"))
        concept = req.str_arg("concept")
        if not concept and spec is None:
            raise errors.SpecError("没有概念描述，也没有卡片规格",
                                   "写一句概念（如「翻转后堆墓的通常陷阱」），或先选中一张卡")
        try:
            out = fn(concept, spec=spec, lang=req.str_arg("lang", "zh_cn"),
                     with_g1=req.bool_arg("with_g1", True),
                     prefer=req.str_arg("prefer", "auto"))
        except errors.CardForgeError:
            raise
        except Exception as e:
            raise errors.LLMUnavailable(
                f"起草失败：{type(e).__name__}: {e}",
                "这不阻塞造卡：卡文可以手写，或点「生成」走确定性模板") from e
        out.setdefault("ok", True)
        return out

    @app.post("/api/assistant/explain")
    def assistant_explain(req: Request) -> dict:
        """把一个质量门报告交给艾莉娅翻译。

        注意：**报告本身是内核产的**，这里只传不产 —— 界面不许自己编结论。
        """
        chat = K.require("cardforge.assistant.chat", "助手对话模块")
        fn = getattr(chat, "explain_gate", None)
        if not callable(fn):
            raise errors.EnvError("chat.explain_gate 不可用", "assistant 模块未实现完整")
        sess = _session_of(req, chat)
        report: Any = req.arg("report")
        gate = req.str_arg("gate")
        if report is None and gate and req.arg("card") is not None:
            from .api_card import _run_gate_obj
            spec = K.load_spec(req.int_arg("card"))
            rep, _audit = _run_gate_obj(req, gate, spec)
            report = rep.to_dict()
        if report is None:
            raise errors.SpecError("没有可解释的报告", "带上 report=<GateReport> 或 card+gate")
        try:
            return {"ok": True, "text": fn(sess, report)}
        except Exception as e:
            raise errors.LLMUnavailable(f"翻译失败：{e}",
                                        "审计报告原文仍然在「审计」页可读") from e

    @app.get("/api/assistant/guide/<step>")
    def assistant_guide(req: Request) -> dict:
        chat = K.require("cardforge.assistant.chat", "助手引导模块")
        fn = getattr(chat, "guide_step", None)
        if not callable(fn):
            raise errors.EnvError("guide_step 不可用", "assistant 模块未实现完整")
        sess = _session_of(req, chat)
        step = req.params["step"]
        try:
            return {"ok": True, "step": step, "text": fn(step, sess)}
        except Exception as e:
            return {"ok": False, "step": step, "error": str(e),
                    "hint": "看 docs/01-总体设计.md 的流程章节"}

    @app.get("/api/knowledge/search")
    def knowledge_search(req: Request) -> dict:
        q = req.str_arg("q")
        if not q:
            raise errors.SpecError("搜索词为空", "例如 q=HOPT")
        kn = K.require("cardforge.assistant.knowledge", "知识库模块")
        out = K.soft_call("cardforge.assistant.knowledge", "search", q,
                          k=req.int_arg("k", 4), label="知识库检索")
        if out.get("ok"):
            out["value"] = {"hits": out["value"] or []}
        return out

    @app.get("/api/assistant/history")
    def assistant_history(req: Request) -> dict:
        with _LOCK:
            return {"ok": True, "sessions": list(_SESSIONS.keys())}


# ══════════════════════════════════════════════════════════════════════
def _sid_of(sess) -> str:
    return str(getattr(sess, "id", "") or "")


def _session_of(req: Request, chat_mod) -> Any:
    """按 id 找回会话；找不到就新建。会话只存内存，重启即失。"""
    sid = req.str_arg("session")
    with _LOCK:
        sess = _SESSIONS.get(sid)
    if sess is not None:
        return sess
    persona = req.str_arg("persona", "professional")
    context = req.arg("context") if isinstance(req.arg("context"), dict) else None
    sess = chat_mod.new_session(persona=persona, context=context)
    new_id = _sid_of(sess) or uuid.uuid4().hex[:12]
    if not _sid_of(sess):
        try:
            sess.id = new_id
        except Exception:
            pass
    with _LOCK:
        _SESSIONS[new_id] = sess
    return sess
