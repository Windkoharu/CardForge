"""会话编排 —— 意图 → 确定性内核 → 人格化转述。

数据流（**判断永远在左边，这一层只在右边**）::

    用户话术 → 意图规则匹配 → tools.call(内核) → 确定性事实串 → persona 模板 → 回复

* 有 LLM 时：LLM 负责选择工具与组织语言；但只要本轮跑过质量门，
  回复里**必定原文附上内核结论**（``【内核原话】``），LLM 改不动数字。
* 没 LLM 时（:class:`~cardforge.assistant.providers.NullProvider`）：
  走本模块的规则通路，功能不缺失 —— 只是表达由模板拼装，不闲聊。
* 三档人格共用**同一个事实串**，所以「结论一致、只有语气不同」是结构性保证。
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..core import paths
from ..core.errors import LLMUnavailable
from ..core.models import GateReport
from . import knowledge
from . import persona as P
from . import providers, tools

__all__ = ["Session", "new_session", "send", "explain_gate", "guide_step",
           "gate_line",
           "STEPS", "status_label", "gate_facts", "gate_counts", "detect_intents",
           "save_session", "load_session", "invalidate_card_cache", "VALID_STATES"]

VALID_STATES: tuple[str, ...] = P.STATE_KEYS


# ══════════════════════════════════════════════════════════════════════
#  会话
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Session:
    """一次会话。可序列化（UI 要持久化），但默认纯内存；落盘只写 ``paths.CACHE``。"""
    id: str = ""
    persona: str = P.DEFAULT_PERSONA
    messages: list = field(default_factory=list)
    context: dict = field(default_factory=dict)

    # ── 序列化 ──────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {"id": self.id, "persona": self.persona,
                "messages": list(self.messages or []),
                "context": dict(self.context or {}),
                "schema_version": 1}

    @staticmethod
    def from_dict(d: dict) -> "Session":
        d = dict(d or {}) if isinstance(d, dict) else {}
        msgs = d.get("messages")
        return Session(id=str(d.get("id") or ""),
                       persona=P.normalize_key(d.get("persona")),
                       messages=list(msgs) if isinstance(msgs, list) else [],
                       context=dict(d.get("context") or {}))

    # ── 便捷 ────────────────────────────────────────────────────
    def note(self, text: str, reply: str, state: str) -> None:
        self.messages.append({"role": "user", "content": str(text or "")})
        self.messages.append({"role": "assistant", "content": str(reply or ""),
                              "state": state})
        if len(self.messages) > 60:
            self.messages = self.messages[-60:]

    @property
    def last_gate(self) -> dict:
        rep = (self.context or {}).get("last_gate_report")
        return rep if isinstance(rep, dict) else {}


def new_session(persona: str = "professional", context: Optional[dict] = None) -> Session:
    """建会话。未知人格键回落到默认（不抛）。"""
    ctx = dict(context or {})
    ctx.setdefault("provider", "auto")
    return Session(id=uuid.uuid4().hex[:12], persona=P.normalize_key(persona),
                   messages=[], context=ctx)


def save_session(session: Session) -> str:
    """会话快照写 ``workspace/.cache/session-<id>.json``（UTF-8 无 BOM）。"""
    try:
        paths.ensure_dirs()
        p = paths.CACHE / f"session-{session.id}.json"
        p.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
                     encoding="utf-8")
        return str(p)
    except Exception:
        return ""


def load_session(session_id: str) -> Optional[Session]:
    """读回会话快照；不存在或损坏返回 None。"""
    try:
        p = paths.CACHE / f"session-{str(session_id)}.json"
        if not p.is_file():
            return None
        return Session.from_dict(json.loads(p.read_text(encoding="utf-8-sig")))
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════
#  质量门 → 事实串
# ══════════════════════════════════════════════════════════════════════
_GATE_NAMES_FALLBACK = {"G1": "平衡审计", "G2": "脚本静态检查", "G3": "实跑验证",
                        "G4": "系列一致性", "G5": "导出自检", "G-text": "卡文校验"}


def _gate_names() -> dict:
    m = tools._try_import(".pipeline.gates")
    return dict(getattr(m, "GATE_NAMES", {}) or _GATE_NAMES_FALLBACK) if m else _GATE_NAMES_FALLBACK


_STATUS_LABEL = {"pass": "通过", "warn": "告警", "fail": "拦截", "waived": "带豁免放行",
                 "pending": "待检", "skipped": "未执行（没有跑过）"}


def status_label(status: str) -> str:
    return _STATUS_LABEL.get(str(status or "").lower(), str(status or "未知"))


def _state_of(status: str) -> str:
    """门状态 → 艾莉娅的工作状态。skipped/pending 一律是「引导」，不是「通过」。"""
    s = str(status or "").lower()
    if s in ("fail", "warn"):
        return "alert"
    if s in ("pass", "waived"):
        return "pass"
    return "guide"


def _issue_list(d: dict) -> list[dict]:
    out = []
    for i in (d.get("issues") or []):
        if isinstance(i, dict):
            out.append(i)
        elif hasattr(i, "to_dict"):
            try:
                out.append(i.to_dict())
            except Exception:
                out.append({"message": str(i)})
        else:
            out.append({"message": str(i)})
    return out


def gate_counts(d: dict) -> dict:
    """按内核字段数清楚：ERROR / WARN / INFO / 已豁免（不做任何判断）。"""
    issues = _issue_list(d)
    c = {"error": 0, "warn": 0, "info": 0, "waived": 0}
    for i in issues:
        lvl = str(i.get("level") or "").upper()
        if bool(i.get("waived")):
            c["waived"] += 1
            continue
        if lvl == "ERROR":
            c["error"] += 1
        elif lvl == "WARN":
            c["warn"] += 1
        elif lvl == "INFO":
            c["info"] += 1
    c["total"] = len(issues)
    return c


def _issue_lines(d: dict, *, limit: int = 8) -> list[str]:
    lines: list[str] = []
    issues = _issue_list(d)
    for i in issues[:limit]:
        lvl = str(i.get("level") or "INFO")
        code = str(i.get("code") or "（无规则号）")
        msg = str(i.get("message") or "").strip()
        mark = "（已强制放行）" if bool(i.get("waived")) else ""
        lines.append(f"- [{lvl}] {code}{mark}：{msg}")
        hint = str(i.get("hint") or "").strip()
        if hint:
            lines.append(f"  建议：{hint}")
    if len(issues) > limit:
        lines.append(f"  …另有 {len(issues) - limit} 条未展开。")
    return lines


def gate_facts(d: dict, *, card: str = "") -> str:
    """把一份门报告翻成**保留全部确定性事实**的中文串。

    规则（历史缺陷 #12 的教训）：
    * ``skipped`` 必须说成「没有真正跑过」，绝不写成通过；
    * ``pass`` 才是通过；两者用完全不同的句式。
    * ``degraded`` 有两种语义，要分开说：skipped 时是「整道门没跑的原因」，
      其余时候是「部分子检查没跑成的补充说明」。
    """
    d = dict(d or {}) if isinstance(d, dict) else {}
    gate = str(d.get("gate") or "?")
    name = _gate_names().get(gate, "")
    status = str(d.get("status") or "pending").lower()
    degraded = str(d.get("degraded") or "").strip()
    summary = str(d.get("summary") or "").strip()
    c = gate_counts(d)

    head = f"{gate}（{name}）" if name else gate
    if card:
        head += f" ｜对象：{card}"
    lines = [f"{head} —— 状态：{status_label(status)}（内核状态值 {status}）"]

    if status == "skipped":
        lines.append("这一门**没有真正执行过**，所以现在给不出任何结论，"
                     "请把下面这条当成「待补」而不是「没问题」。")
        if degraded:
            lines.append(f"为什么没跑（内核原话）：{degraded}")
        elif summary:
            lines.append(f"内核原话：{summary}")
        body = _issue_lines(d)
        if body:
            lines.append("附带的提示：")
            lines.extend(body)
        lines.append(f"计数：{c['error']} 项 ERROR、{c['warn']} 项 WARN、"
                     f"{c['info']} 项 INFO（都是附带信息，不代表跑过）。")
        return "\n".join(lines)

    cnt = f"计数：{c['error']} 项 ERROR、{c['warn']} 项 WARN、{c['info']} 项 INFO"
    if c["waived"]:
        cnt += f"、{c['waived']} 项已强制放行（留痕）"
    lines.append(cnt)
    if summary:
        lines.append(f"内核原话：{summary}")
    body = _issue_lines(d)
    if body:
        lines.extend(body)
    elif status in ("pass", "waived"):
        lines.append("逐条检查项都没有命中问题。")
    if degraded and status != "skipped":
        lines.append(f"注意（部分子检查没跑成，门结论仍有效）：{degraded}")
    took = d.get("took_ms")
    if isinstance(took, (int, float)) and took:
        lines.append(f"耗时：{int(took)} ms")
    return "\n".join(lines)


def explain_gate(session: Optional[Session], report: Any) -> str:
    """把 ``GateReport``（或它的 dict）翻译成人话 —— 事实照抄，语气换皮。"""
    if isinstance(report, GateReport):
        d = report.to_dict()
    elif isinstance(report, dict):
        d = dict(report)
    else:
        d = {"gate": "?", "status": "pending", "summary": str(report or "")}
    key = P.normalize_key(getattr(session, "persona", "") if session else "")
    state = _state_of(d.get("status"))
    facts = gate_facts(d)
    advice = [str(i.get("hint")).strip() for i in _issue_list(d)
              if str(i.get("hint") or "").strip()][:4]
    if isinstance(session, Session):
        session.context["last_gate_report"] = d
        session.context["last_gate_state"] = state
    return _compose(key, state, facts, advice)


def gate_line(report: Any, persona_key: str = "") -> str:
    """质量门结论的**一句话**版本 —— 给界面立绘气泡用。

    与 :func:`explain_gate` 同源：事实来自同一批内核函数
    （``gate_counts`` / ``status_label`` / ``_state_of``），只是裁短。
    三档人格仍然只包装语气；``skipped`` 依然必须说「没有真正跑过」。
    """
    if isinstance(report, GateReport):
        d = report.to_dict()
    elif isinstance(report, dict):
        d = dict(report)
    else:
        d = {"gate": "?", "status": "pending", "summary": str(report or "")}
    key = P.normalize_key(persona_key)
    gate = str(d.get("gate") or "?")
    name = _gate_names().get(gate, "")
    status = str(d.get("status") or "pending").lower()
    c = gate_counts(d)
    state = _state_of(status)
    if status == "skipped":
        # skipped 走 guide 模板（不是 pass、也不是 alert —— 见 _state_of 的注释）。
        # guide 模板渲染 {step}/{detail}/{next} 而不是 {facts}，所以把话放进对应槽位。
        why = str(d.get("degraded") or d.get("summary") or "").strip()
        detail = ("这一门**没有真正跑过**"
                  + (f"：{why[:70]}" if why else "") + "，按「待补」算。")
        return P.state_line(state, key,
                            step=f"{gate}（{name}）" if name else gate,
                            detail=detail,
                            next="补上所需条件后重跑这一门")
    facts = (f"{gate}（{name}）{status_label(status)}："
             f"ERROR {c['error']}、WARN {c['warn']}、INFO {c['info']}"
             + (f"、已放行 {c['waived']} 条（留痕）" if c["waived"] else ""))
    return P.state_line(state, key, facts=facts, step=gate, detail="", next="")


# ══════════════════════════════════════════════════════════════════════
#  制卡步骤向导
# ══════════════════════════════════════════════════════════════════════
STEPS: dict[str, dict] = {
    "new_card": {"zh": "建卡", "why": "CardSpec 是全流程唯一真相源，卡面/卡文/Lua/cdb 都从它派生",
                 "do": "定卡号、卡名、卡种、属性、种族、等级、ATK/DEF",
                 "next": "anchor", "tool": "card_get", "ask": "g4_binding"},
    "anchor": {"zh": "定三个设计锚点", "why": "锚点没定就开工 → 系列不连贯 → 必然卡手（方法论 §2.2）",
               "do": "胜利方式（战斗/效果/削血/混合）、王牌形态（融合/同调/超量/连接/仪式/主卡组）、属性·种族绑定",
               "next": "audit", "tool": "archetype_get", "ask": "三个设计锚点"},
    "audit": {"zh": "平衡审计（G1）", "why": "单卡过强是 DIY 最大死因；这一道是确定性代码在把关",
              "do": "跑 card_audit，逐条看规则号与建议；要放行必须填理由（留痕）",
              "next": "text", "tool": "card_audit", "ask": "平衡三角 七条铁律"},
    "text": {"zh": "卡文（PSCT）", "why": "卡文是效果 IR 的投影，措辞不合 PSCT 会让脚本与卡面对不上",
             "do": "psct_gen 生成，再 psct_lint 校验；有告警回规格层改",
             "next": "script", "tool": "psct_lint", "ask": "HOPT 一回合一次"},
    "script": {"zh": "Lua 脚本（G2）", "why": "ocgcore 只认脚本；带 BOM 或用了不存在的 API 直接加载失败",
               "do": "lua_gen 生成 → lua_lint 静态检查（语法/API/Stringid 同步）",
               "next": "render", "tool": "lua_lint", "ask": "脚本 BOM Stringid"},
    "render": {"zh": "卡面渲染", "why": "三段式管线（基座/内容/效果），只在最后降采样一次",
               "do": "先 render_capabilities 看字体与素材是否齐，再渲预览",
               "next": "art", "tool": "render_capabilities", "ask": "卡面"},
    "art": {"zh": "卡图（ComfyUI）", "why": "角色一致性靠 IPAdapter + 参考图，同一套管线",
            "do": "art_status 确认在线 → art_generate（需显式 confirm）",
            "next": "series", "tool": "art_status", "ask": "卡图"},
    "series": {"zh": "系列批量（G4）", "why": "方言句式 ≤5 条、属性种族要有交集、角色覆盖要够",
               "do": "series_plan 出蓝图 → gate_run G4 查一致性",
               "next": "deck", "tool": "series_plan", "ask": "方言句式 主题效果"},
    "deck": {"zh": "卡组构筑（配比/初动率）",
             "why": "40 张是初动上手率最高的解；功能性冗余 vs 死冗余是核心判据",
             "do": "deck_analyze 看覆盖与初动率；用 opening_probability 复算",
             "next": "export", "tool": "deck_analyze", "ask": "初动率 40 张 配比"},
    "export": {"zh": "导出 EDOPro 包（G5）",
               "why": "导出自检是最后一道闸：编码、卡号冲突、cdb 表结构，拦截就不出包",
               "do": "export_pack（需 confirm）→ gate_run G5 自检",
               "next": "", "tool": "export_pack", "ask": "cdb 卡号"},
}


def guide_step(step: str, session: Optional[Session]) -> str:
    """当前在哪一步、下一步做什么、为什么这一步存在。"""
    key = P.normalize_key(getattr(session, "persona", "") if session else "")
    k = str(step or "").strip()
    info = STEPS.get(k)
    if info is None:
        for name, item in STEPS.items():
            if k and (k in name or k in str(item.get("zh") or "")):
                info = item
                break
    if info is None:
        detail = "可讲的步骤：" + "、".join(f"{v['zh']}" for v in STEPS.values())
        return P.state_line("guide", key, step="制卡流程", detail=detail,
                            next="从「建卡」开始，或直接把卡名告诉我")
    detail = f"为什么有这一步：{info['why']}。现在要做：{info['do']}。"
    nxt = STEPS.get(info.get("next") or "", {})
    reply = P.state_line("guide", key, step=info["zh"], detail=detail,
                         next=(nxt.get("zh", "收尾") if info.get("next") else "没有后续步骤了"))
    hits = knowledge.search(str(info.get("ask") or info["zh"]), k=1)
    if hits and hits[0].get("score", 0) > 0:
        h = hits[0]
        quote = str(h.get("text") or "")[:160]
        reply += f"\n知识库参考（{h['section']}）：{quote}"
    return reply


# ══════════════════════════════════════════════════════════════════════
#  表达层：人格换皮，事实不动
# ══════════════════════════════════════════════════════════════════════
def _compose(persona_key: str, state: str, facts: str,
             advice: Optional[list[str]] = None, tail: str = "") -> str:
    """把「事实串 + 内核给的建议」包上人格语气。

    ``facts`` 与 ``advice`` 全部来自内核返回值，本函数**只做字符串拼接**，
    因此同一条结论在三档人格下数字与规则号逐字一致。
    """
    p = P.persona(persona_key)
    style = p.style or {}
    head_slot = {"alert": "alert_head", "pass": "pass_head"}.get(state, "")
    parts: list[str] = []
    opener = str(style.get("opener") or "")
    if opener:
        parts.append(opener)
    if head_slot:
        head = P.flavor(persona_key, head_slot, "")
        if head:
            parts.append(head)
    if facts:
        parts.append(facts)
    lines = [str(a).strip() for a in (advice or []) if str(a).strip()]
    if lines:
        joiner = str(style.get("advice_join") or "；")
        parts.append(f"{str(style.get('advice_prefix') or '建议：')}{joiner.join(lines)}")
    if tail:
        parts.append(tail)
    closer = str(style.get("closer") or "")
    if closer:
        parts.append(closer)
    out = "\n".join(x for x in parts if x)
    return out or P.state_line(state, persona_key, detail=facts, step="", next="")


# ══════════════════════════════════════════════════════════════════════
#  意图识别（规则/正则；这是「路由」，不是「裁决」）
# ══════════════════════════════════════════════════════════════════════
_INTENTS: list[tuple[str, str]] = [
    ("gate_explain", r"(质量门|门结论|门的结论|审计结果|检查报告|报告|G[1-5]|gate)"),
    ("balance", r"(打点|平衡|超模|太强|太弱|强度|合理|不合理|泛用|被禁|禁卡|atk|攻击力|守备力|数值)"),
    ("text", r"(卡文|文案|psct|措辞|效果文|文本|句式|术语)"),
    ("script", r"(脚本|lua|代码|ocgcore)"),
    ("deck", r"(卡组|构筑|配比|卡手|brick|side|副卡组|初动率|初动|上手)"),
    ("pool", r"(官方卡池|官方|卡池|查重|撞名|同名|字段名|相似|setcode|卡号|编号)"),
    ("env", r"(引擎|渲染|字体|素材|comfy|出图|环境|doctor|能力|可用|依赖)"),
    ("export", r"(导出|打包|扩展包|cdb|ydk|安装包)"),
    ("guide", r"(下一步|我该|怎么做|如何开始|从哪|流程|不懂|不会|help|指引|说明一下)"),
    ("knowledge", r"(什么是|为什么|该怎么|规则|方法论|惯例|铁律|红旗|灵摆|刻度|箭头|连接|"
                  r"禁限|方言|三锚点|一致性|冗余|初动点|素材|代价|设计)"),
    ("greeting", r"^(你好|您好|嗨|哈喽|hi|hello|在吗|在不在|早上好|晚上好)"),
]

_RE_QUOTED = re.compile(r"[「《“\"']([^」》”\"']{1,60})[」》”\"']")
_RE_GATE = re.compile(r"\b(G[1-5])\b", re.I)
_RE_STARTERS = re.compile(r"(\d{1,2})\s*张(?:的)?(?:初动|启动点|starter)"
                          r"|(?:初动(?:点)?|启动点)[\s的有]{0,4}(\d{1,2})\s*张")
_RE_DECK_SIZE = re.compile(r"(\d{2})\s*张(?:的)?(?:主)?卡组")

#: 「像卡文而不像卡名」的特征：够长 + 有句子符号 / 效果动词
_TEXT_MARKERS = ("。", "；", ";", "①", "②", "效果", "发动", "特殊召唤", "送去墓地",
                 "加入手卡", "回合")

_CARD_NAME_CACHE: dict[str, Any] = {"names": None, "archetypes": None}


def looks_like_card_text(quoted: str) -> bool:
    """引号里的东西是卡文还是卡名 —— 卡名不会带上句读和效果动词。"""
    q = str(quoted or "").strip()
    if not q:
        return False
    return len(q) >= 12 or any(m in q for m in _TEXT_MARKERS)


def _quoted(text: str) -> str:
    m = _RE_QUOTED.search(str(text or ""))
    return m.group(1).strip() if m else ""


def invalidate_card_cache() -> None:
    _CARD_NAME_CACHE.update({"names": None, "archetypes": None})


def _workspace_card_names() -> list[str]:
    if _CARD_NAME_CACHE["names"] is None:
        names: list[str] = []
        res = tools.call("card_list", {}, {})
        for item in (res.get("cards") or []):
            if isinstance(item, dict):
                n = str(item.get("name") or "").strip()
                if n:
                    names.append(n)
        _CARD_NAME_CACHE["names"] = names
    return _CARD_NAME_CACHE["names"] or []


def _card_ref(text: str, session: Optional[Session]) -> dict:
    """从话里找出「说的是哪张卡」：引号里的卡名 → 工作区卡名子串 → 会话上下文。

    引号内容如果更像卡文（带句读/效果动词、够长），就**不当卡名**，
    否则「校一下卡文：『……』」会被当成查不到的卡。
    """
    ctx = getattr(session, "context", {}) or {}
    body = str(text or "")
    out: dict[str, Any] = {}
    q = _quoted(body)
    if q and not looks_like_card_text(q):
        out["name"] = q
    if not out.get("name"):
        for n in sorted(_workspace_card_names(), key=len, reverse=True):
            if n and n in body:
                out["name"] = n
                break
    nums = re.findall(r"\b(\d{6,12})\b", body)
    if nums:
        out["card_id"] = int(nums[0])
    if not out.get("name") and not out.get("card_id"):
        if ctx.get("card_id"):
            out["card_id"] = ctx.get("card_id")
        elif ctx.get("card_name"):
            out["name"] = ctx.get("card_name")
        elif len(_workspace_card_names()) == 1:
            out["name"] = _workspace_card_names()[0]
    return out


def detect_intents(text: str) -> list[str]:
    """按顺序匹配意图（可多命中，第一个是主意图）。纯路由，不碰结论。

    大小写不敏感 —— 用户写 ``g3`` 还是 ``G3`` 都得认（门编号规则里有大写）。
    """
    t = str(text or "").strip()
    if not t:
        return ["unknown"]
    hits: list[str] = []
    for key, pat in _INTENTS:
        if key == "greeting":
            if re.search(r"^(你好|您好|嗨|哈喽|hi|hello|在吗|在不在|早上好|晚上好)",
                         t.lower()):
                hits.append(key)
        elif re.search(pat, t, re.I):
            hits.append(key)
    return hits or ["unknown"]


# ══════════════════════════════════════════════════════════════════════
#  规则通路（无 LLM）
# ══════════════════════════════════════════════════════════════════════
def _ctx_of(session: Optional[Session]) -> dict:
    ctx = dict(getattr(session, "context", {}) or {})
    ctx["session"] = session
    return ctx


def _rule_send(session: Optional[Session], text: str,
               on_event: Optional[Callable] = None) -> dict:
    """意图 → 工具 → 事实串 → 人格模板。返回 ``{"facts","advice","state",
    "tool_calls","gate_changed","intents","tail"}``。"""
    sess = session if isinstance(session, Session) else new_session()
    ctx = _ctx_of(sess)
    calls: list[dict] = []
    tail = ""

    def run(name: str, args: dict) -> dict:
        res = tools.call(name, args, ctx)
        calls.append({"name": name, "args": args, "result": res})
        if on_event is not None:
            try:
                on_event({"type": "tool", "name": name, "args": args,
                          "ok": bool(res.get("ok"))})
            except Exception:
                pass
        return res

    intents = detect_intents(text)
    lead = intents[0]
    ref = _card_ref(text, sess)
    card_label = ""
    facts = ""
    advice: list[str] = []
    state = "guide"
    gate_changed = False

    # ── 门结论解释 ────────────────────────────────────────────
    if lead == "gate_explain":
        gm = _RE_GATE.search(str(text or ""))
        gate = (gm.group(1).upper() if gm else "G1")
        if sess.context.get("last_gate_report") and gate == str(
                sess.context["last_gate_report"].get("gate") or "").upper() and not ref:
            d = dict(sess.context["last_gate_report"])
        else:
            args: dict[str, Any] = {"gate": gate}
            args.update(ref)
            d = run("gate_run", args).copy()
            d.setdefault("gate", gate)
        card_label = _label_of(d, ref, sess)
        facts = gate_facts(d, card=card_label)
        state = _state_of(d.get("status"))
        advice = _hints(d)
        gate_changed = bool(d.get("status"))
        sess.context["last_gate_report"] = d

    # ── 平衡/打点：G1 + 知识库参考 ─────────────────────────────
    elif lead == "balance":
        args = dict(ref)
        d = run("card_audit", args)
        if not d.get("ok") and not d.get("status"):
            facts = (f"内核没有给出结论：{d.get('error') or d.get('degraded') or '未知原因'}"
                     "\n没有具体某张卡时，我只能给设计规律，不能给裁决。")
            state = "guide"
            know = run("knowledge_search",
                       {"query": "打点 攻击力 阈值 代价 未成文规则", "k": 1})
            hits = know.get("hits") or []
            if hits and not hits[0].get("low_confidence"):
                facts += (f"\n设计规律参考（{hits[0]['section']}，相关度 "
                          f"{round(hits[0]['score'], 2)}）：" + str(hits[0]["text"])[:260])
        else:
            d.setdefault("gate", "G1")
            card_label = str((d.get("card") or {}).get("name") or ref.get("name") or "")
            spec_res = run("card_get", args)
            stat = _stat_line(spec_res.get("summary") or {})
            facts = (f"卡的规格读数：{stat}\n" if stat else "") + gate_facts(d, card=card_label)
            state = _state_of(d.get("status"))
            advice = _hints(d)
            gate_changed = True
            sess.context["last_gate_report"] = d
            know = run("knowledge_search", {"query": "打点 攻击力 平衡 阈值 代价", "k": 2})
            tail = _know_tail(know.get("hits") or [])

    # ── 卡文 ──────────────────────────────────────────────────
    elif lead == "text":
        args: dict[str, Any] = dict(ref)
        quoted = _quoted(text)
        m = re.search(r"(?:卡文|文案|文本|措辞)[:：]\s*(.+)$", str(text or "").strip())
        if m:
            args = {"text": m.group(1).strip()}
        elif quoted and looks_like_card_text(quoted):
            args = {"text": quoted}          # 引号里是卡文本身，不是卡名
        d = run("psct_lint", args)
        issues = d.get("issues") or []
        if not d.get("ok"):
            facts = f"卡文校验没跑成：{d.get('error') or d.get('degraded')}"
        else:
            facts = _issues_facts(
                "卡文校验（G-text 规则，来自 content/psct/lint.py）", issues)
            advice = _hints({"issues": issues})
            state = "alert" if any(str(i.get("level")).upper() in ("ERROR", "WARN")
                                   for i in issues) else "pass"
        if state == "guide":
            state = "alert" if advice else "pass"

    # ── 脚本 ──────────────────────────────────────────────────
    elif lead == "script":
        quoted = _quoted(text)
        wants_gen = re.search(r"(生成|写(一[份个]|个)?|出|create|emit)", str(text or "")) is not None
        if quoted and re.search(r"[(){:；;]|function|end\b", quoted):
            d = run("lua_lint", {"lua": quoted})       # 引号里就是脚本本体
        elif wants_gen:
            d = run("lua_gen", dict(ref))
        else:
            d = run("lua_lint", dict(ref))
        if not d.get("ok"):
            facts = f"脚本这一步没跑成：{d.get('error') or d.get('degraded')}"
            state = "guide"
        elif d.get("lua") is not None and "chars" in d:
            issues = d.get("issues") or []
            facts = (f"脚本已生成（{d.get('chars')} 字符）。"
                     + _issues_facts("随后跑的 Lua 静态检查（G2 规则）", issues))
            advice = _hints({"issues": issues})
            state = "alert" if advice else "pass"
        else:
            issues = d.get("issues") or []
            facts = _issues_facts("Lua 静态检查（G2 规则，来自 content/lua/lint.py）", issues)
            advice = _hints({"issues": issues})
            state = "alert" if advice else "pass"
        probe = run("duel_probe", {})
        if probe.get("engine_level") != "ocgcore" or not probe.get("bot_ready"):
            tail = ("实跑环境读数：引擎层级 "
                    f"{probe.get('engine_level')}、对局驱动就绪 "
                    f"{bool(probe.get('bot_ready'))} —— 所以 G3 现在只能是 skipped（没跑过）。")

    # ── 卡组 / 初动率 ─────────────────────────────────────────
    elif lead == "deck":
        n = _starters_count(text)
        ds = _deck_size(text)
        if n:
            d = run("opening_probability",
                    {"n_starters": n} if not ds else {"n_starters": n, "deck_size": ds})
            if d.get("ok"):
                facts = (f"初动率（超几何分布，内核函数 opening_probability）："
                         f"初动 {d['n_starters']} 张 / 主卡组 {d['deck_size']} 张 / "
                         f"起手 {d['hand']} 张 → 至少 1 张的概率 {d['percent']}%")
                state = "pass"
                know = run("knowledge_search", {"query": "初动率 40 张 配比", "k": 1})
                tail = _know_tail(know.get("hits") or [])
            else:
                facts = f"初动率没算出来：{d.get('error') or d.get('degraded')}"
        else:
            name = str(ctx.get("deck") or "")      # 卡组名只认会话上下文，别把卡名当卡组
            lines: list[str] = []
            if name:
                d = run("deck_analyze", {"name": name})
                if d.get("ok"):
                    lines.append("卡组分析（content/design.analyze_deck）："
                                 + _compact(d.get("result") or {}))
                    state = "pass"
                else:
                    lines.append(f"卡组分析没跑成：{d.get('error') or d.get('degraded')}")
            else:
                lines.append("没在工作区里找到要分析的卡组。两种问法我都能答："
                             "①给我卡组名（deck_analyze 会跑覆盖率与冗余判据）；"
                             "②直接给数字，例如「12 张初动 40 张卡组的初动率」，我用超几何公式算。")
            know = run("knowledge_search", {"query": text or "初动 配比 40 张", "k": 1})
            hits = know.get("hits") or []
            if hits and not hits[0].get("low_confidence"):
                lines.append(f"配比参考（{hits[0]['section']}，相关度 "
                             f"{round(hits[0]['score'], 2)}）：" + str(hits[0]["text"])[:260])
            facts = "\n".join(lines)
            state = "pass" if name and state == "pass" else "guide"

    # ── 官方池 / 查重 / setcode ────────────────────────────────
    elif lead == "pool":
        quoted = _quoted(text)
        # 引号里的东西优先当「要查重的字段名」；没引号再退到正则抽字段词
        field_name = (quoted if quoted and not looks_like_card_text(quoted)
                      else _field_ref(text)) or ref.get("name") or ""
        if "setcode" in str(text or "").lower():
            d = run("setcode_suggest", {})
            facts = (f"setcode 分配（design.suggest_setcode）：{d.get('setcode')}"
                     if d.get("ok") else f"没能给出：{d.get('error') or d.get('degraded')}")
            if d.get("pool_available") is False:
                tail = "注意：官方池不可用，返回的是安全区起点，没有做占用校验。"
            state = "pass" if d.get("ok") else "guide"
        else:
            lines = []
            if field_name:
                dd = run("pool_dupcheck", {"name": field_name})
                if dd.get("ok") and dd.get("checked"):
                    lines.append(f"字段查重「{field_name}」：精确同名 {len(dd.get('exact') or [])} 条、"
                                 f"官方名子串命中 {len(dd.get('substring') or [])} 条")
                    for h in (dd.get("exact") or [])[:5]:
                        lines.append(f"  · 同名：{h if isinstance(h, str) else json.dumps(h, ensure_ascii=False)}")
                    for h in (dd.get("substring") or [])[:5]:
                        lines.append(f"  · 子串：{h if isinstance(h, str) else json.dumps(h, ensure_ascii=False)}")
                    state = "alert" if (dd.get("exact") or dd.get("substring")) else "pass"
                    advice = ["换一个不会被官方卡名包含的字段名（Cipher Soldier 事件就是这么发生的）。"] \
                        if (dd.get("exact") or dd.get("substring")) else []
                else:
                    lines.append(f"字段查重没执行：{dd.get('error') or dd.get('degraded') or '官方池不可用'}")
                    state = "guide"
            q = str(ref.get("name") or field_name or "")
            ps = run("pool_search", {"query": q, "limit": 6})
            if ps.get("ok"):
                names = [str(c.get("name") or c.get("id")) for c in (ps.get("cards") or [])[:6]]
                lines.append(f"官方池检索「{q}」：命中 {ps.get('count')} 条"
                             + (f" → {'、'.join(names)}" if names else "（卡池里没有相关卡名）"))
            else:
                lines.append(f"官方池不可用：{ps.get('degraded') or ps.get('error')}")
            facts = "\n".join(lines)
            if not field_name:
                state = "pass" if ps.get("ok") else "guide"

    # ── 环境能力 ──────────────────────────────────────────────
    elif lead == "env":
        eng = run("engine_detect", {})
        ren = run("render_capabilities", {})
        art = run("art_status", {})
        lines = []
        if eng.get("ok"):
            lines.append(f"对局引擎：{eng.get('level_zh') or eng.get('level')}"
                         + (f"（原因：{eng.get('reason')}）" if eng.get("reason") else ""))
        else:
            lines.append(f"对局引擎：{eng.get('degraded') or eng.get('error')}")
        lines.append("渲染能力：" + _compact(ren.get("capabilities") or ren))
        if art.get("ok"):
            lines.append(f"ComfyUI：{'在线' if art.get('online') else '不在线'}（{art.get('host')}）")
        probe = run("duel_probe", {})
        lines.append(f"G3 实跑所需模块：引擎 {probe.get('engine_level')} / "
                     f"bot {'就绪' if probe.get('bot_ready') else '未就绪'} / "
                     f"scenario {'就绪' if probe.get('scenario_ready') else '未就绪'}")
        facts = "\n".join(lines)
        state = "working"
        tail = "这些读数都来自各模块自己的探测函数，我没有加工过。"

    # ── 导出 ──────────────────────────────────────────────────
    elif lead == "export":
        d = run("export_pack", {"name": str(ref.get("name") or "CardForge")})
        g5 = run("gate_run", {"gate": "G5", "pack_dir": str(ctx.get("pack_dir") or "")})
        lines = [d.get("degraded") or d.get("error") or "导出请求已识别（未执行）。"]
        if g5.get("status"):
            lines.append(gate_facts(g5))
        facts = "\n".join(lines)
        state = _state_of(g5.get("status")) if g5.get("status") else "guide"
        gate_changed = bool(g5.get("status"))

    # ── 向导 ──────────────────────────────────────────────────
    elif lead == "guide":
        step = _step_ref(text) or str(sess.context.get("step") or "anchor")
        key = P.normalize_key(sess.persona)
        facts = guide_step(step, sess)
        state = "guide"
        tail = ""
        # guide_step 已经是人格话术，这里不再套一层，避免语气重复
        return {"facts": facts, "advice": [], "state": state, "tool_calls": calls,
                "gate_changed": False, "intents": intents, "tail": "",
                "raw_personality_text": True}

    # ── 知识库参谋 ────────────────────────────────────────────
    elif lead == "knowledge":
        know = run("knowledge_search", {"query": text, "k": 3})
        hits = know.get("hits") or []
        if hits:
            facts = "知识库命中（data/knowledge/ 原文，我没改写）：\n" + "\n".join(
                f"· [{h['section']}] 相关度 {round(h['score'], 2)}\n  {str(h['text'])[:300]}"
                for h in hits[:3])
            state = "guide"
        else:
            facts = "知识库里没有相关条目，我不编。"
            state = "guide"

    # ── 问候 / 未知 ───────────────────────────────────────────
    elif lead == "greeting":
        return {"facts": P.greeting(P.normalize_key(sess.persona), "default"),
                "advice": [], "state": "guide", "tool_calls": calls,
                "gate_changed": False, "intents": intents, "tail": "",
                "raw_personality_text": True}
    else:
        key = P.normalize_key(sess.persona)
        return {"facts": str((P.persona(key).style or {}).get("unknown") or "我不确定。"),
                "advice": [], "state": "guide", "tool_calls": calls,
                "gate_changed": False, "intents": ["unknown"], "tail": "",
                "raw_personality_text": True}

    return {"facts": facts or "内核这次没有给出可读结论。", "advice": advice,
            "state": state, "tool_calls": calls, "gate_changed": gate_changed,
            "intents": intents, "tail": tail, "card_label": card_label,
            "raw_personality_text": False}


def _hints(d: dict) -> list[str]:
    return [str(i.get("hint") or "").strip() for i in _issue_list(d)
            if str(i.get("hint") or "").strip()][:5]


def _label_of(d: dict, ref: dict, session: Optional[Session]) -> str:
    card = d.get("card") if isinstance(d.get("card"), dict) else {}
    return str(card.get("name") or ref.get("name")
               or (getattr(session, "context", {}) or {}).get("card_name") or "")


def _stat_line(summary: dict) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    parts = [f"卡名 {summary.get('name')}", f"卡种 {summary.get('frame_label')}",
             f"{summary.get('attribute')}·{summary.get('race')}·{summary.get('level')}",
             f"ATK {summary.get('atk')} / DEF {summary.get('def')}",
             f"效果条数 {summary.get('n_effects')}"]
    return " ｜ ".join(str(p) for p in parts)


def _issues_facts(title: str, issues: list, *, limit: int = 8) -> str:
    """校验类结果的事实串：条数 + 逐条「级别/规则号/说明」。"""
    issues = [i for i in (issues or []) if isinstance(i, dict)]
    if not issues:
        return f"{title}：0 条命中，逐条检查项都没有问题。"
    lines = [f"- [{i.get('level')}] {i.get('code')}：{i.get('message')}"
             for i in issues[:limit]]
    if len(issues) > limit:
        lines.append(f"…另有 {len(issues) - limit} 条未展开。")
    return f"{title}：{len(issues)} 条命中\n" + "\n".join(lines)


def _know_tail(hits: list) -> str:
    if not hits:
        return ""
    h = hits[0]
    if h.get("low_confidence"):
        return ""
    return (f"设计规律参考（{h['section']}，相关度 {round(h['score'], 2)}）："
            f"{str(h['text'])[:220]}")


def _compact(obj: Any, *, limit: int = 400) -> str:
    """把任意结构压成一行短文本（进回复或进提示词用，别把上下文撑爆）。"""
    try:
        s = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        s = str(obj)
    return s[:limit]


def _field_ref(text: str) -> str:
    m = re.search(r"(?:字段|系列|archetype)(?:名|code)?[为是:：]?\s*"
                  r"[「《“\"']?([\u4e00-\u9fffA-Za-z0-9 ]{1,20})", str(text or ""))
    got = m.group(1).strip() if m else ""
    # 「字段名」这类话里的“名”字会被正则吃进去，剔掉纯语法尾巴
    for junk in ("名", "称", "字", "的", "有", "是"):
        if got == junk:
            return ""
    return got


def _starters_count(text: str) -> int:
    """从话里取「初动点张数」。**只认与「初动」紧邻的数字**，
    免得「40 张卡组放多少初动」把 40 当成初动数（参数解析，不是判断）。"""
    m = _RE_STARTERS.search(str(text or ""))
    if not m:
        return 0
    for g in m.groups():
        if g:
            try:
                v = int(g)
            except (TypeError, ValueError):
                return 0
            return v if 1 <= v <= 40 else 0
    return 0


def _deck_size(text: str) -> int:
    m = _RE_DECK_SIZE.search(str(text or ""))
    if not m:
        return 0
    try:
        v = int(m.group(1))
    except (TypeError, ValueError):
        return 0
    return v if 20 <= v <= 60 else 0


def _step_ref(text: str) -> str:
    t = str(text or "")
    for key, item in STEPS.items():
        if key in t.lower() or str(item.get("zh") or "") in t:
            return key
    return ""


# ══════════════════════════════════════════════════════════════════════
#  对外入口
# ══════════════════════════════════════════════════════════════════════
def send(session: Session, text: str, on_event: Optional[Callable] = None) -> dict:
    """一轮对话。返回 ``{"reply","state","tool_calls","gate_changed", ...}``。"""
    sess = session if isinstance(session, Session) else new_session()
    sess.persona = P.normalize_key(sess.persona)
    body = str(text or "").strip()
    if not body:
        reply = P.greeting(sess.persona, "idle")
        sess.note(body, reply, "guide")
        return {"reply": reply, "state": "guide", "tool_calls": [],
                "gate_changed": False, "provider": "none", "intents": ["empty"]}

    provider = None
    try:
        provider = providers.detect_provider(str(sess.context.get("provider") or "auto"))
    except Exception:
        provider = None

    result: dict
    if provider is not None and getattr(provider, "name", "none") != "none":
        try:
            result = _llm_send(sess, body, provider, on_event)
        except LLMUnavailable as e:
            result = _rule_send(sess, body, on_event)
            result["fallback_reason"] = str(e)
        except Exception as e:
            result = _rule_send(sess, body, on_event)
            result["fallback_reason"] = f"语言模型调用失败，已走规则通路：{e}"
    else:
        result = _rule_send(sess, body, on_event)

    key = P.normalize_key(sess.persona)
    if result.get("raw_personality_text"):
        reply = str(result.get("facts") or "")
    else:
        reply = _compose(key, str(result.get("state") or "guide"),
                         str(result.get("facts") or ""),
                         list(result.get("advice") or []), str(result.get("tail") or ""))
    state = str(result.get("state") or "guide")
    if state not in VALID_STATES:
        state = "guide"
    sess.note(body, reply, state)
    sess.context["last_state"] = state
    if (result.get("card_label") or result.get("gate_changed")) and isinstance(
            result.get("card_label"), str) and result.get("card_label"):
        sess.context["card_name"] = result["card_label"]

    out = {"reply": reply, "state": state,
           "tool_calls": list(result.get("tool_calls") or []),
           "gate_changed": bool(result.get("gate_changed")),
           "intents": list(result.get("intents") or []),
           "provider": getattr(provider, "name", "none") if provider else "none",
           "persona": key}
    for k in ("fallback_reason", "model", "facts"):
        if result.get(k):
            out[k] = result[k]
    if on_event is not None:
        try:
            on_event({"type": "state", "state": state, "reply": reply})
        except Exception:
            pass
    return out


def _llm_send(session: Session, text: str, provider: Any,
              on_event: Optional[Callable] = None) -> dict:
    """有 LLM 时的一轮：LLM 选工具 + 组织语言；**跑过门就一定附内核原话**。"""
    p = P.persona(session.persona)
    msgs: list[dict] = [{"role": "system", "content":
                         p.system_prompt + "\n\n可用工具都只做一件事：转调确定性内核。"
                         "引用结论时必须带规则号与计数，禁止概括成「看起来不错」。"}]
    for m in (session.messages or [])[-12:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": str(m["content"])[:1200]})
    msgs.append({"role": "user", "content": text})

    resp = provider.chat(msgs, tools=tools.tool_schemas(), stream=on_event is not None,
                         on_delta=(lambda d: on_event({"type": "delta", "text": d}))
                         if on_event is not None else None)
    calls: list[dict] = []
    ctx = _ctx_of(session)
    gate_facts_text = ""
    ran_gate = False
    for tc in (resp.get("tool_calls") or []):
        name = str(tc.get("name") or "")
        args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        res = tools.call(name, args, ctx)
        calls.append({"name": name, "args": args, "result": res})
        if on_event is not None:
            try:
                on_event({"type": "tool", "name": name, "args": args, "ok": bool(res.get("ok"))})
            except Exception:
                pass
        if name in ("card_audit", "gate_run") and res.get("status"):
            session.context["last_gate_report"] = res
            gate_facts_text = gate_facts(res, card=str((res.get("card") or {}).get("name") or ""))
            ran_gate = True

    content = str(resp.get("content") or "").strip()
    if calls:
        # 把工具结果回灌给模型再要一次措辞（很多本地小模型不支持 tool，
        # 这一步失败就直接走规则通路，保证一定有信息量）
        msgs.append({"role": "assistant", "content": content or "（已调用工具）",
                     "tool_calls": [{"name": c["name"], "args": c["args"]} for c in calls]})
        for c in calls:
            msgs.append({"role": "tool", "name": c["name"],
                         "content": _compact(c["result"], limit=3500)})
        msgs.append({"role": "system", "content":
                     "只依据上面的工具结果作答。必须逐字引用其中的规则号、级别与计数；"
                     "结果标记为 degraded/error 时要如实说明「没跑成」，不许编结论。"})
        try:
            resp2 = provider.chat(msgs, tools=None)
            content = str(resp2.get("content") or "").strip() or content
        except Exception:
            content = content

    if not content:
        # LLM 只选了工具没说话 → 把工具结论直接翻成人话（走规则通路，保证有信息量）
        rule = _rule_send(session, text, None)
        rule["tool_calls"] = calls + list(rule.get("tool_calls") or [])
        rule["model"] = resp.get("model", "")
        return rule

    if ran_gate and gate_facts_text:
        content = f"{content}\n\n【内核原话】\n{gate_facts_text}"
    return {"reply": content, "facts": content, "state": _state_of(
        (session.context.get("last_gate_report") or {}).get("status")) if ran_gate else "working",
        "tool_calls": calls, "gate_changed": ran_gate, "intents": ["llm"],
        "tail": "", "advice": [], "raw_personality_text": True,
        "model": resp.get("model", "")}


def _responder(text: str, ctx: dict) -> dict:
    """:class:`~cardforge.assistant.providers.NullProvider` 的规则引擎入口。"""
    session = ctx.get("session") if isinstance(ctx, dict) else None
    out = _rule_send(session if isinstance(session, Session) else None, str(text or ""), None)
    key = P.normalize_key(getattr(session, "persona", "") if session else "")
    return {"content": _compose(key, str(out.get("state") or "guide"),
                                str(out.get("facts") or ""),
                                list(out.get("advice") or []), str(out.get("tail") or "")),
            "tool_calls": out.get("tool_calls") or [], "state": out.get("state") or "guide",
            "context": {"intents": out.get("intents") or [],
                        "gate_changed": bool(out.get("gate_changed"))}}


providers.set_responder(_responder)
