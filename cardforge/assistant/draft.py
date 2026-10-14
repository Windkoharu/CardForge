"""AI 起草卡文 —— **LLM 只提议，裁决归内核**。

数据流::

    概念描述（+ 可选 CardSpec）
      → 约束提示词（PSCT 句式硬规则）
      → LLM 一次性起草
      → 内核 ``content.psct.lint.lint_text``（+ spec 在场时 ``pipeline.gates.g1_balance``）
      → ``{"draft", "issues", "gate", ...}``

红线（本模块存在的前提，改动时不许破坏）
--------------------------------------
* ``draft`` 是语言模型的输出 —— **只是提议**，不是结论；
* ``issues`` / ``counts`` / ``gate`` 全部由确定性内核产出，LLM 在文本里
  自带的任何自评（「已符合 PSCT」「没有问题」）一律**不采信、不回传**；
* 没有 LLM 时**不编草稿**：返回 ``ok=False`` + ``degraded``，明说规则通路
  不支持自由起草（规则通路能做的确定性事在 ``assistant/tools.py``，不在这里）；
* 剥壳只做「削掉围栏/开场白/尾巴」这类无损清理，**绝不改写正文字**——
  内核校验器看到的必须和用户看到的是同一份文本。
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..core.models import CardSpec

__all__ = ["draft", "constraints_prompt", "extract_draft"]


# ══════════════════════════════════════════════════════════════════════
#  PSCT 句式约束（提示词用）—— 条目与 content/psct/rules.py 的 LINT_RULES
#  一一对应；这里只做「让草稿别离大谱」的预防，真正的裁决在 lint_text。
# ══════════════════════════════════════════════════════════════════════
_CONSTRAINTS = (
    "1. 效果编号用①②③…，从①开始连续不跳号；每条效果独占一段，编号写在段首。",
    "2. 中文/日文卡文不使用分号「；」：代价与取对象靠语序写在「才能发动／発動できる」"
    "之前；只有英文才用「;」分隔「发动条件; 效果处理」。",
    "3. 触发时机必须显式写出：中文「…时／…的场合」、日文「…時／…場合」、"
    "英文 When/If；同一段里不要混用「时」与「场合」。",
    "4. 取对象写作「以…为对象才能发动」，且只能出现在发动条件里，"
    "不能挪到效果处理段；不取对象的效果不许写「以…为对象」。",
    "5. 代价写在「发动」之前：中文句式「把…解放才能发动。」；英文写在「;」左侧。",
    "6. 「1回合1次，」写在「才能发动」之前；多效果卡用卡名限制："
    "「这个卡名的①②效果1回合各能使用1次。」",
    "7. 检索／特殊召唤／抽卡类效果必须带回合限制，漏写算错误。",
    "8. 卡名与字段名加引号：中文与日文用「」，英文用半角双引号；"
    "「HERO」字段全大写（Elemental HERO）。",
    "9. 中文/日文卡文里不许出现英文连接词（then/and/also），"
    "用「并且／那之后／此外／那个场合」。",
    "10. 特殊召唤必须写「怪兽」这一单位，内置特殊召唤要标来源括号，"
    "如「（从手卡）」「(from your GY)」。",
    "11. 只输出卡文正文：不要解释、不要注释、不要代码块围栏、不要复述要求。",
)


def constraints_prompt(lang: str) -> str:
    """PSCT 硬约束的提示词片段（``lang`` 目前只影响结尾句，条目本身跨语言通用）。"""
    return ("【PSCT 硬约束 —— 违反任何一条，草稿都会被内核校验器打回】\n"
            + "\n".join(_CONSTRAINTS)
            + f"\n\n目标语言：{lang or 'zh_cn'}。按该语言的官方 PSCT 写法输出。")


def _spec_brief(spec: Optional[CardSpec]) -> str:
    """把 CardSpec 压成一段中文简述（只搬字段事实，不替模型做设计决定）。"""
    if spec is None:
        return ""
    try:
        s = spec.summary() or {}
    except Exception:
        s = {}
    head = (f"卡片：{s.get('name') or spec.display_name}"
            f"（{s.get('frame_label') or spec.frame}）")
    bits = []
    if spec.is_monster:
        bits.append(f"{spec.attribute}・{spec.race}・"
                    f"{'Lv.' + str(spec.effective_level) if spec.effective_level else ''}")
        if spec.atk is not None:
            tail = f"／{spec.def_value}" if spec.def_value is not None else ""
            bits.append(f"ATK {spec.atk}{tail}")
    if spec.archetype:
        bits.append(f"系列：{spec.archetype}")
    kinds = []
    for e in (spec.effects or []):
        k = getattr(e, "kind", "") if not isinstance(e, dict) else str(e.get("kind") or "")
        if k:
            kinds.append(str(k))
    body = f"已定义效果 {len(kinds)} 条：" + "、".join(kinds) if kinds else "尚未定义结构化效果。"
    flavor = ""
    try:
        flavor = spec.flavor_in(getattr(spec.render, "lang_text", "zh_cn")) or ""
    except Exception:
        flavor = ""
    tail = f"\n既有背景文字（供语气参考，可不采用）：{flavor}" if flavor else ""
    return f"{head}｜{'・'.join(b for b in bits if b)}\n{body}{tail}"


_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\s*\n?(.*?)```", re.S)
# 尾巴上的「说明/注意/Note:」整段算模型的话痨，不是卡文
_CHATTER_TAIL = re.compile(
    r"^\s*(?:说明|注意|备注|注释|以上|Note[s]?\s*[:：]|Explanation|This text)\b", re.I)


def extract_draft(content: str) -> str:
    """把 LLM 的回复削成「卡文正文」。

    LLM 常做三件多余的事：包 markdown 围栏、加开场白、结尾挂「说明：」。
    剥法（纯行级清理，不动字句）：围栏取最长块 → 从第一个 ① 段起
    （之前的算开场白）→ 遇到说明性段落整行截断。
    剥不干净也不丢内容：内核校验器对剥完的文本说话，不会偷偷改字。
    """
    text = str(content or "").strip()
    if not text:
        return ""
    blocks = _FENCE.findall(text)
    if blocks:
        text = max(blocks, key=len).strip()
    lines = text.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("①"):
            start = i
            break
    end = len(lines)
    for j in range(start, len(lines)):
        if _CHATTER_TAIL.match(lines[j]):
            end = j
            break
    return "\n".join(lines[start:end]).strip()


# ══════════════════════════════════════════════════════════════════════
#  内核裁决（本地实现，避免反向依赖 tools 的私有助手）
# ══════════════════════════════════════════════════════════════════════
def _norm_issues(issues: Any) -> list[dict]:
    out: list[dict] = []
    for i in issues or []:
        if hasattr(i, "to_dict"):
            try:
                out.append(dict(i.to_dict()))
                continue
            except Exception:
                pass
        if isinstance(i, dict):
            out.append(dict(i))
        else:
            out.append({"message": str(i)})
    return out


def _counts(issues: list[dict]) -> dict:
    c = {"error": 0, "warn": 0, "info": 0, "waived": 0}
    for i in issues:
        if bool(i.get("waived")):
            c["waived"] += 1
            continue
        lvl = str(i.get("level") or "").upper()
        if lvl == "ERROR":
            c["error"] += 1
        elif lvl == "WARN":
            c["warn"] += 1
        elif lvl == "INFO":
            c["info"] += 1
    c["total"] = len(issues)
    return c


def _lint(draft: str, lang: str, spec: Optional[CardSpec]) -> tuple[Optional[list[dict]], str]:
    """跑内核 PSCT 校验。返回 ``(issues, degraded)``；issues 为 None 表示没跑成。"""
    import importlib
    try:
        mod = importlib.import_module(".content.psct.lint", package="cardforge")
    except Exception as e:
        return None, f"PSCT 校验模块不可用：{e}"
    fn = getattr(mod, "lint_text", None)
    if not callable(fn):
        return None, "PSCT 校验模块缺少 lint_text。"
    try:
        return _norm_issues(fn(draft, lang, spec)), ""
    except Exception as e:
        return None, f"PSCT 校验执行异常：{e}"


def _g1(spec: Optional[CardSpec]) -> tuple[Optional[dict], str]:
    """spec 在场时补一刀 G1 平衡审计（审计的是规格，不是草稿文字）。"""
    if spec is None:
        return None, "没有附带 CardSpec，这一门没有可审计的对象。"
    import importlib
    try:
        gates = importlib.import_module(".pipeline.gates", package="cardforge")
    except Exception as e:
        return None, f"质量门模块不可用：{e}"
    fn = getattr(gates, "g1_balance", None)
    if not callable(fn):
        return None, "质量门模块缺少 g1_balance。"
    try:
        rep = fn(spec)
    except Exception as e:
        return None, f"G1 执行异常：{e}"
    d = rep.to_dict() if hasattr(rep, "to_dict") else dict(rep or {})
    d["note"] = "G1 审计的是规格本身（代价/数值/词条），不是这份草稿的文字。"
    return d, ""


# ══════════════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════════════
def draft(concept: str, *, spec: Optional[CardSpec] = None, lang: str = "zh_cn",
          prefer: str = "auto", with_g1: bool = True,
          timeout: float = 60.0) -> dict:
    """起草一份卡文。**永远返回 dict，绝不抛异常。**

    参数
    ----
    concept:
        概念描述（「一张能复活墓地怪兽的仪式魔法…」）。与 ``spec`` 至少给一个：
        都没给时返回 ``ok=False`` + ``error``。
    spec:
        可选。给了会把卡片字段与效果清单喂给模型当事实底座，
        并附赠一次 G1 审计（审计规格，不审计草稿）。
    prefer:
        provider 选择（auto / none / ollama…），语义同
        :func:`cardforge.assistant.providers.detect_provider`。
    """
    concept = str(concept or "").strip()
    if not concept and spec is None:
        return {"ok": False, "error": "既没有概念描述也没有卡片规格，没东西可起草。",
                "hint": "给一句概念（比如「翻转后堆墓的通常陷阱」），或先选中一张卡。"}

    # ── 拿 provider（软导入：assistant 之外的调用方也不会被拖下水） ──
    import importlib
    try:
        prov_mod = importlib.import_module(".providers", package="cardforge.assistant")
    except Exception as e:
        return {"ok": False, "degraded": f"provider 模块不可用：{e}",
                "hint": "这不阻塞造卡：卡文可以手写，或点「生成」走确定性模板。"}
    try:
        provider = prov_mod.detect_provider(str(prefer or "auto"))
    except Exception as e:
        return {"ok": False, "degraded": f"大模型探测失败：{e}",
                "hint": "检查模型端点是否还在线；规则通路的确定性功能不受影响。"}
    pname = str(getattr(provider, "name", "none"))
    if pname in ("none", "null"):
        return {"ok": False,
                "degraded": "当前没有可用的大模型 —— 规则通路不做自由起草，"
                            "所以这里不给草稿，也不拿模板文本冒充 AI 产物。",
                "hint": "配一个本地端点（LM Studio / Ollama）或云端模型再试："
                        "界面顶栏「⚙模型」，或命令行 cardforge llm preset lmstudio。"}
    try:
        if hasattr(provider, "timeout") and timeout:
            provider.timeout = max(float(getattr(provider, "timeout") or 0), float(timeout))
    except Exception:
        pass

    # ── 提示词：约束 + 事实底座 + 输出契约 ──
    brief = _spec_brief(spec)
    user = concept
    if brief:
        user = f"{concept}\n\n【这张卡的既有事实（按它写，别改设定）】\n{brief}"
    msgs = [
        {"role": "system", "content":
             "你是游戏王 DIY 制卡工具的卡文起草器。只做一件事：把概念描述写成"
             "符合 PSCT（Problem-Solving Card Text）规范的卡文草稿。\n\n"
             + constraints_prompt(lang)},
        {"role": "user", "content": user},
    ]
    try:
        resp = provider.chat(msgs)
    except Exception as e:
        return {"ok": False, "error": f"大模型调用失败：{e}",
                "hint": "可能是上下文超限或模型未加载；换个小模型，或直接手写卡文。"}
    raw = str(resp.get("content") or "").strip()
    body = extract_draft(raw)
    if not body:
        return {"ok": False, "error": "模型回了空内容，没有可校验的草稿。",
                "hint": "重试一次；持续为空就换模型或手写。"}

    # ── 裁决：全部来自内核 ──
    issues, lint_bad = _lint(body, lang, spec)
    gate, g1_bad = ((None, "") if not with_g1 else _g1(spec))
    out: dict[str, Any] = {
        "ok": True,
        "draft": body,
        "lang": lang,
        "provider": pname,
        "model": str(resp.get("model")
                     or (provider.resolved_model() if hasattr(provider, "resolved_model")
                         else getattr(provider, "model", "")) or ""),
        "note": "草稿由语言模型提议；问题清单与门结论全部来自确定性内核，"
                "LLM 在文本里的任何自评都未采信。",
    }
    if raw != body:
        out["raw"] = raw
    if issues is None:
        out["degraded"] = lint_bad
        out["issues"] = []
        out["counts"] = _counts([])
    else:
        out["issues"] = issues
        out["counts"] = _counts(issues)
    if with_g1:
        if gate is None:
            out["gate"] = None
            if g1_bad:
                out["gate_degraded"] = g1_bad
        else:
            out["gate"] = gate
    return out
