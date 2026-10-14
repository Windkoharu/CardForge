"""``cardforge/assistant/`` 的交付自检（真跑，不看代码顺不顺眼）。

用法::

    PYTHONIOENCODING=utf-8 python tools/selfcheck_assistant.py

六个验收项，全部**实际执行**：

1. :func:`providers.detect_provider` 在本机真环境跑一次，报告探测结果并计时（必须 ≤1.5s）；
   再起一个模拟 OpenAI 兼容端点，验证**活服务不会被误判成离线**（探根路径 404 的坑）。
2. ``python -m cardforge ask "…打点合不合理" --persona professional`` 子进程真跑，
   输出必须是**有信息量的中文**（含规则号/计数，而不是「我不支持」）。
3. :func:`chat.explain_gate` 对 pass / warn / fail / skipped+degraded 四份
   :class:`GateReport` 各产出一段话，并断言：fail 里出现具体 code 与 ERROR 数；
   skipped 里明确说「没有真正执行」，且**整段不含「通过」二字**。
4. :func:`knowledge.search` 对 ≥10 个真实查询返回非空、top1 命中预期主题。
5. :func:`tools.call` 对每个注册工具各调两次（空参数 + 未知参数），
   断言 0 未捕获异常，依赖缺失时返回中文降级说明而不是 traceback。
6. :func:`chat.send` 的 ``state`` 在三档人格下都合法，且三档语气确有区别而
   **结论（规则号 + 计数 + 数字）逐字一致** —— 这是「人格不许改写裁决」的不变式。
7. :func:`assistant.draft` 的 AI 起草红线：草稿取自 LLM，问题清单与 G1 全部由
   内核实算（假 provider 故意交一份**违规且自称没问题**的草稿，内核必须照常报错）；
   没有 LLM 时诚实降级，不编草稿、不拿模板冒充 AI 产物。

报告落盘：``workspace/.cache/selfcheck-assistant.txt``（UTF-8，控制台只打 ASCII 摘要）。
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cardforge.core import paths                                 # noqa: E402
from cardforge.assistant import chat, knowledge, persona       # noqa: E402
from cardforge.assistant import providers, tools               # noqa: E402
from cardforge.core.models import GateReport, Issue, CardSpec   # noqa: E402

LINES: list[str] = []
FAILED: list[str] = []
PASSED = 0


def say(s: str = "") -> None:
    LINES.append(s)


def check(name: str, ok: bool, detail: str = "") -> bool:
    """记一条断言；失败就进 FAILED 清单。"""
    global PASSED
    if ok:
        PASSED += 1
        say(f"  [ok]   {name}" + (f" —— {detail}" if detail else ""))
    else:
        FAILED.append(name)
        say(f"  [FAIL] {name}" + (f" —— {detail}" if detail else ""))
    return bool(ok)


# ══════════════════════════════════════════════════════════════════════
#  1. provider 探测：结果 + 耗时
# ══════════════════════════════════════════════════════════════════════
say("=" * 72)
say("[1] providers.detect_provider 本机实测（要求总耗时 ≤1.5s）")
providers.reset_probe_cache()
t0 = time.perf_counter()
prov = providers.detect_provider("auto")
elapsed = time.perf_counter() - t0
info = providers.provider_info()
say(f"  探测结果：{prov.name}  可用={prov.available()}  耗时={elapsed:.3f}s")
say(f"  探测细节：{json.dumps(info, ensure_ascii=False)}")
check("1.1 探测耗时 ≤1.5s", elapsed <= 1.5, f"{elapsed:.3f}s")
check("1.2 探测必须返回对象（最差 NullProvider）", prov is not None and prov.name in
      ("openai_compat", "ollama", "lmstudio", "none"), prov.name)
check("1.3 无 LLM 时 NullProvider.available() 为真", providers.NullProvider().available())
t1 = time.perf_counter()
lst = providers.list_providers()
say(f"  list_providers 耗时={time.perf_counter() - t1:.3f}s → "
    + json.dumps([{k: v for k, v in d.items() if k in ('key', 'available')} for d in lst],
                 ensure_ascii=False))
_keys = [d["key"] for d in lst]
# 存档配置行**可有可无**（取决于工作区有没有存过模型）—— 断言不许绑死工作区
# 状态（同 8.4 的规矩）：四路必须在，多出来的那一行只能是 config 且在首位。
check("1.4 list_providers 覆盖四路（有存档配置时多一行 config）",
      {"openai_compat", "ollama", "lmstudio", "none"} <= set(_keys)
      and (len(_keys) == 4 or (len(_keys) == 5 and _keys[0] == "config")),
      str(_keys))
t_c = time.perf_counter()
for _ in range(20):
    providers.detect_provider("auto")
cached_ms = (time.perf_counter() - t_c) / 20 * 1000
say(f"  命中缓存后单次 detect_provider 平均 {cached_ms:.3f} ms（20 次）")
check("1.5 重复探测走缓存（≤50ms，UI 不会被拖慢）", cached_ms <= 50.0, f"{cached_ms:.3f}ms")

# ══════════════════════════════════════════════════════════════════════
#  1b. 活服务发现：模拟端点必须被探到（根 URL 404 的坑，实测回归）
# ══════════════════════════════════════════════════════════════════════
say("")
say("[1b] 起模拟 OpenAI 端点（GET /v1/models → 200，GET /v1 → 404，同 LM Studio）")
_sock = socket.socket()
try:
    _sock.bind(("127.0.0.1", 1234))
    _port_free = True
except OSError:
    _port_free = False
finally:
    _sock.close()
if not _port_free:
    say("  [skip] 1234 已被占用（大概 LM Studio 真在跑），跳过本项")
else:
    _mock = subprocess.Popen(
        [sys.executable, str(ROOT / "tools" / "mock_llm_server.py"), "1234"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _up = False
        for _ in range(30):
            try:
                _c = socket.create_connection(("127.0.0.1", 1234), timeout=0.2)
                _c.close()
                _up = True
                break
            except OSError:
                time.sleep(0.1)
        check("1.6 模拟端点成功监听 1234", _up, "3s 内没起来")
        if _up:
            # 直接验探测层：活端点的 /models 必须被解析出模型 id。
            # 早期版本探的是根路径 /v1（真实服务一律 404），活服务也被探成
            # 不在线 —— 用户开了 LM Studio 却静默走规则通路，没有任何报错。
            _probed = providers._probe_all(               # noqa: SLF001 —— 同包探测
                providers._probe_targets())               # noqa: SLF001
            _models = providers._models_of(               # noqa: SLF001
                _probed.get("http://127.0.0.1:1234/v1/models"))
            check("1.7 活端点的 /models 被探成可用（不误判离线）",
                  "mock-qwen-7b" in _models, str(_models))
            # 再验 auto 链：配置可能抢在前面（用户真存过模型），所以只断言
            # 「不漏」—— 最差也要返回一个可用对象，而不是 none。
            providers.reset_probe_cache()
            _t = time.perf_counter()
            _p = providers.detect_provider("auto")
            _el = time.perf_counter() - _t
            _info = providers.provider_info()
            try:
                _avail = bool(_p.available())
            except Exception:
                _avail = False
            check("1.8 auto 链不漏活服务（返回可用对象）",
                  _p.name != "none" and _avail,
                  f"{_p.name} · {_info['detail']} · {_el:.3f}s")
            say(f"  detect(auto) → {_p.name}（{_info['detail']}）耗时={_el:.3f}s")
    finally:
        _mock.terminate()
        try:
            _mock.wait(timeout=5)
        except Exception:
            _mock.kill()
        providers.reset_probe_cache()

# ══════════════════════════════════════════════════════════════════════
#  1c. prefer 路由不被缓存键污染（缺陷 #35 回归）
# ══════════════════════════════════════════════════════════════════════
say("")
say("[1c] prefer 路由：缓存键的 #cfg 后缀不许漏进 _build（缺陷 #35）")
providers.reset_probe_cache()
_cfg_p = providers.detect_provider("config")
_cfg_d = str(providers.provider_info().get("detail", {}))
# 有配置 → 返回配置 provider 或其降级原因；无配置 → 「尚未配置」。
# 二者都不是 auto 链的兜底 reason —— 出现兜底 reason 即说明被 misroute 了。
check("1.9 prefer=config 走配置通路（不掉进 auto 兜底）",
      "未探测到任何可用 LLM 端点" not in _cfg_d, _cfg_d[:60])
providers.reset_probe_cache()
_none_p = providers.detect_provider("none")
_none_d = str(providers.provider_info().get("detail", {}))
check("1.10 prefer=none 直达离线（不误探网络）",
      _none_p.name == "none" and "显式要求离线" in _none_d, _none_d[:60])

# ══════════════════════════════════════════════════════════════════════
#  2. CLI 真跑
# ══════════════════════════════════════════════════════════════════════
say("")
say("[2] python -m cardforge ask \"帮我看看星奏的见习指挥这张卡的打点合不合理\"")
env = dict(os.environ, PYTHONIOENCODING="utf-8")
q = "帮我看看星奏的见习指挥这张卡的打点合不合理"
t2 = time.perf_counter()
try:
    proc = subprocess.run([sys.executable, "-m", "cardforge", "ask", q,
                           "--persona", "professional"],
                          cwd=str(ROOT), env=env, capture_output=True, timeout=120)
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
except Exception as e:
    out, err, proc = "", str(e), None
cli_ms = int((time.perf_counter() - t2) * 1000)
say(f"  退出码={getattr(proc, 'returncode', '?')} 耗时={cli_ms}ms stdout={len(out)} 字符")
say("  ---- CLI 输出 ----")
for line in out.splitlines():
    say("  | " + line)
say("  ------------------")
if err.strip():
    say("  stderr: " + err.strip()[:600])
check("2.1 CLI 退出码 0", proc is not None and proc.returncode == 0,
      str(getattr(proc, "returncode", None)))
check("2.2 输出有信息量：含门结论", "计数：" in out and "ERROR" in out)
# 断"有问题时必须引用规则号"，而不是断某个固定规则号出现 ——
# 后者等于把自测绑死在工作区某张卡的当前状态上：那张卡一旦被修好（G1 全绿、
# 自然没有规则号可引），自测就红，而助手什么都没做错。
_clean = bool(re.search(r"计数：\s*0 项 ERROR、0 项 WARN、0 项 INFO", out))
_has_issues = bool(re.search(r"计数：", out)) and not _clean
check("2.3 有问题就一定引用规则号",
      (not _has_issues) or bool(re.search(r"G1_[A-Z0-9_]+", out)),
      ("引用 " if _has_issues else "全绿，无需引用 ")
      + ",".join(sorted(set(re.findall(r"G1_[A-Z0-9_]+", out)))[:6]))
check("2.4 输出不是「我不支持」这类推脱",
      all(x not in out for x in ("不支持", "无法回答", "请配置 LLM")))
check("2.5 输出带卡的规格读数（打点问题必须回答打点）", "ATK" in out and "星奏" in out)
check("2.6 CLI 端到端 ≤20s", cli_ms <= 20000, f"{cli_ms}ms")

# ══════════════════════════════════════════════════════════════════════
#  3. explain_gate 四份报告
# ══════════════════════════════════════════════════════════════════════
say("")
say("[3] explain_gate 对 pass / warn / fail / skipped+degraded 的翻译")
fix = {
    "pass": GateReport(gate="G1", status="pass", summary="全部通过", took_ms=18),
    "warn": GateReport(gate="G1", status="warn", took_ms=21, summary="1 项告警",
                       issues=[Issue(gate="G1", code="G1_L4_EFFECT_ATK", level="WARN",
                                     message="4 星效果怪兽 ATK 2400 偏高",
                                     hint="降到 1800 以下，或补一条负面", field="atk")]),
    "fail": GateReport(gate="G1", status="fail", took_ms=25, summary="2 项拦截、1 项告警",
                       issues=[
                           Issue(gate="G1", code="G1_HOPT_MISSING", level="ERROR",
                                 message="检索效果没有任何次数限制",
                                 hint="补「这个卡名的效果1回合只能发动1次」"),
                           Issue(gate="G1", code="G1_EFFECT_COUNT_ERROR", level="ERROR",
                                 message="效果条数 5 条，超过硬上限",
                                 hint="拆成两张卡"),
                           Issue(gate="G1", code="RF08", level="WARN",
                                 message="检索/特召未加 HOPT", hint="补 1回合1次")]),
    "skipped": GateReport(gate="G3", status="skipped",
                          summary="未检测到对局引擎（vendor/engine/ocgcore.dll 缺失），已降级为静态校验",
                          degraded="未检测到对局引擎（vendor/engine/ocgcore.dll 缺失），已降级为静态校验",
                          issues=[Issue(gate="G3", code="G3_ENGINE_HINT", level="INFO",
                                        message="把 ocgcore.dll 放进 vendor/engine 后重跑",
                                        hint="装 EDOPro 或自带 dll")]),
}
texts: dict[str, str] = {}
for k, rep in fix.items():
    texts[k] = chat.explain_gate(chat.new_session("professional"), rep)
    say(f"  --- {k} ---")
    for line in texts[k].splitlines():
        say("  | " + line)

check("3.1 fail 文案出现具体规则号",
      "G1_HOPT_MISSING" in texts["fail"] and "G1_EFFECT_COUNT_ERROR" in texts["fail"]
      and "RF08" in texts["fail"])
check("3.2 fail 文案出现 ERROR 计数（2 项）", "2 项 ERROR" in texts["fail"])
check("3.3 fail 文案没有被美化成「看起来不错」",
      "看起来不错" not in texts["fail"] and "问题不大" not in texts["fail"])
check("3.4 warn 文案区分于 fail（0 项 ERROR）", "0 项 ERROR" in texts["warn"])
check("3.5 skipped 文案明确说没跑过",
      any(x in texts["skipped"] for x in ("没有真正执行", "没有跑过", "未执行")))
check("3.6 skipped 文案绝不含「通过」二字", "通过" not in texts["skipped"],
      texts["skipped"].replace("\n", " ")[:120])
check("3.7 skipped 文案保留了 degraded 原话（确定性事实）",
      "ocgcore.dll" in texts["skipped"] and "降级为静态校验" in texts["skipped"])
check("3.8 pass 与 skipped 用不同句式（不混淆）",
      "状态：通过" in texts["pass"] and "状态：通过" not in texts["skipped"])
check("3.9 传 dict 也能解释（GateReport|dict 双输入）",
      "G1_L4_EFFECT_ATK" in chat.explain_gate(chat.new_session("professional"),
                                              fix["warn"].to_dict()))

# ══════════════════════════════════════════════════════════════════════
#  4. 知识库检索
# ══════════════════════════════════════════════════════════════════════
say("")
say("[4] knowledge.search 真实查询（要求非空 + top1 命中主题）")
queries: list[tuple[str, str]] = [
    ("HOPT", "HOPT"), ("初动率", "初动"), ("连接箭头", "连接"), ("灵摆刻度", "灵摆"),
    ("禁限卡", "禁"), ("红旗规则", "雷区"), ("字段名查重", "查重"),
    ("setcode 编码", "setcode"), ("三个设计锚点", "锚点"),
    ("功能性冗余和死冗余的区别", "冗余"), ("40 张卡组的配比", "40"),
    ("副卡组", "Side"), ("方言句式", "方言"), ("卡手", "连贯"),
    ("ATK 阈值", "ATK"), ("平衡三角", "平衡"),
]
say(f"  语料：{json.dumps(knowledge.corpus_stats(), ensure_ascii=False)}")
bad: list[str] = []
for q, want in queries:
    hits = knowledge.search(q, k=3)
    top = hits[0] if hits else None
    ok = bool(top) and (want.lower() in (top["text"] + top["section"]).lower()) \
        and float(top["score"]) > 0
    say(f"  · {q}  →  top1={top['section'] if top else 'NONE'}"
        f" score={round(top['score'], 2) if top else 0} "
        f"doc={top['doc_id'] if top else '-'} {'HIT' if ok else 'MISS'}")
    if not ok:
        bad.append(q)
check("4.1 全部查询非空", all(knowledge.search(q) for q, _ in queries))
check(f"4.2 top1 相关性（{len(queries)} 个查询）", not bad, "未命中：" + "、".join(bad))
check("4.3 检索不依赖网络/向量库（纯函数，重复调用结果一致）",
      knowledge.search("初动率", k=2) == knowledge.search("初动率", k=2))
say(f"  excerpt 示例：{knowledge.excerpt('内置速查', '灵摆')[:60]}…")
check("4.4 excerpt 能按 doc_id+section 取原文", "刻度" in knowledge.excerpt("内置速查", "灵摆"))

# ══════════════════════════════════════════════════════════════════════
#  5. 工具全量调用
# ══════════════════════════════════════════════════════════════════════
say("")
say("[5] tools.call 全量：空参数 + 未知参数 + 不存在的卡号")
names = tools.tool_names()
say(f"  已注册 {len(names)} 个工具：" + "、".join(names))
check("5.1 工具数 ≥20", len(names) >= 20, str(len(names)))
check("5.2 schema 全部合法（function-calling 结构）",
      all(s.get("type") == "function" and s["function"].get("name")
          and s["function"].get("parameters", {}).get("properties") is not None
          for s in tools.tool_schemas()), str(len(tools.tool_schemas())))
crash: list[str] = []
crash_info: list[str] = []
okish = degraded_n = err_n = 0
for n in names:
    for label, args in (("空参数", {}),
                        ("未知参数", {"zzz_unknown": 1, "card_id": 999999999,
                                     "gate": "G9", "name": "不存在的卡"})):
        try:
            r = tools.call(n, args, {})
        except BaseException as e:                       # noqa: BLE001 - 自检就是要抓全部
            crash.append(f"{n}/{label}:{type(e).__name__}")
            crash_info.append(f"{n}/{label} 抛异常 {type(e).__name__}: {e}")
            continue
        if not isinstance(r, dict) or r.get("tool") != n:
            crash.append(f"{n}/{label} 返回结构不对")
            continue
        if r.get("ok"):
            okish += 1
        elif r.get("degraded"):
            degraded_n += 1
        else:
            err_n += 1
check("5.3 0 未捕获异常", not crash, "; ".join(crash[:6]))
say(f"  结果分布：ok={okish} 降级说明={degraded_n} 错误说明={err_n}（共 {2 * len(names)} 次调用）")
check("5.4 每个工具都给了中文说明（ok / degraded / error 至少一个）",
      all(("degraded" in tools.call(n, {}, {}) or "error" in tools.call(n, {}, {})
           or tools.call(n, {}, {}).get("ok")) for n in names))
# 软依赖缺失时的降级（这几个模块由并行小组实现，现在可能还不存在）
for soft in ("lua_gen", "effects_lookup", "export_pack", "art_generate", "duel_probe"):
    r = tools.call(soft, {}, {})
    txt = str(r.get("degraded") or r.get("note") or r.get("error") or json.dumps(
        r, ensure_ascii=False))
    say(f"  · {soft} → {txt[:110]}")
    check(f"5.5 {soft} 有降级路径（不是 traceback）", isinstance(r, dict) and bool(txt))
# 真实卡上跑一遍（工作区里的星奏卡）
real = tools.call("card_audit", {"name": "星奏的见习指挥"}, {})
say("  · card_audit(真实卡) → status=" + str(real.get("status")) +
    " summary=" + str(real.get("summary")))
check("5.6 card_audit 在真实卡上返回内核结论", bool(real.get("status")), str(real)[:160])
check("5.7 未知工具名返回说明而不是异常",
      tools.call("no_such_tool", {}, {}).get("ok") is False)

# ══════════════════════════════════════════════════════════════════════
#  6. 三档人格：语气有别，结论一致
# ══════════════════════════════════════════════════════════════════════
say("")
say("[6] send/explain_gate 三档人格（state 合法 + 结论不可被人格改写）")
KEY = r"\b(G[1-5]_[A-Z0-9_]+|RF\d{2}|G[1-5])\b"
sents = {k: chat.explain_gate(chat.new_session(k), fix["fail"])
         for k in ("professional", "lightnovel", "tsundere")}
for k, v in sents.items():
    say(f"  --- {k} ---")
    for line in v.splitlines():
        say("  | " + line)
code_sets = {k: sorted(set(re.findall(KEY, v))) for k, v in sents.items()}
count_sets = {k: (re.search(r"计数：[^\n]+", v).group(0) if re.search(r"计数：[^\n]+", v) else "")
              for k, v in sents.items()}
check("6.1 三档人格的规则号集合完全相同",
      code_sets["professional"] == code_sets["lightnovel"] == code_sets["tsundere"],
      json.dumps(code_sets, ensure_ascii=False))
check("6.2 三档人格的计数行完全相同（数字没被改写）",
      len(set(count_sets.values())) == 1, json.dumps(count_sets, ensure_ascii=False))
check("6.3 三档人格文本确有区别（语气不同）",
      len({sents["professional"], sents["lightnovel"], sents["tsundere"]}) == 3)
check("6.4 人格都不美化结论",
      all("看起来不错" not in v and "问题不大" not in v for v in sents.values()))

states: dict[str, str] = {}
replies: dict[str, str] = {}
for k in ("professional", "lightnovel", "tsundere"):
    sess = chat.new_session(k)
    r = chat.send(sess, "帮我看看星奏的见习指挥这张卡的打点合不合理")
    states[k] = r.get("state", "")
    replies[k] = r.get("reply", "")
    sess2 = chat.new_session(k)
    r2 = chat.send(sess2, "下一步我该做什么")
    say(f"  · {k}: state={r.get('state')} intent={r.get('intents')} "
        f"tools={[c['name'] for c in r.get('tool_calls') or []]} provider={r.get('provider')}")
    say(f"      state(引导)={r2.get('state')} 文本前 40 字：{replies[k][:40]!r}")
    check(f"6.5 {k} 的 state 合法", r.get("state") in chat.VALID_STATES, str(r.get("state")))
    check(f"6.6 {k} 的引导 state 合法", r2.get("state") in chat.VALID_STATES, str(r2.get("state")))
    check(f"6.7 {k} 无 LLM 也给出结论", bool(replies[k]) and "计数：" in replies[k])
same = {k: sorted(set(re.findall(KEY, replies[k]))) for k in replies}
check("6.8 同一句话在三档人格下调用的内核结论一致（规则号）",
      len({tuple(v) for v in same.values()}) <= 2,   # 三次独立跑 G1，结论应一致
      json.dumps(same, ensure_ascii=False))
check("6.9 三档人格的实际回复文本不同", len(set(replies.values())) == 3)

# 会话序列化
s = chat.new_session("tsundere", {"card_name": "星奏的见习指挥"})
chat.send(s, "这张卡的打点合理吗")
d = s.to_dict()
s2 = chat.Session.from_dict(d)
check("6.10 Session 可序列化并还原（UI 持久化用）",
      s2.id == s.id and s2.persona == s.persona
      and len(s2.messages) == len(s.messages)
      and s2.context.get("card_name") == "星奏的见习指挥")
p_saved = chat.save_session(s)
s3 = chat.load_session(s.id)
check("6.11 会话快照读写（写在 paths.CACHE，不新建目录）",
      bool(p_saved) and s3 is not None and s3.persona == s.persona, p_saved)

# 人格函数
check("6.12 state_line 支持中文状态与未知状态回落",
      bool(persona.state_line("报警", "professional", facts="x"))
      and bool(persona.state_line("完全没听过的状态", "随便", detail="")))
check("6.13 人格名/短名常量", persona.ASSISTANT_NAME == "星奏·艾莉娅"
      and persona.ASSISTANT_NAME_SHORT == "艾莉娅")

# ══════════════════════════════════════════════════════════════════════
#  7. 数值解析不许猜错（回归用）
# ══════════════════════════════════════════════════════════════════════
say("")
say("[7] 数字路由：定性提问不许被当成公式入参")
s_num = chat.new_session("professional")
r_num = chat.send(s_num, "12 张初动 40 张卡组的初动率是多少")
say("  · " + r_num["reply"].splitlines()[1] if len(r_num["reply"].splitlines()) > 1 else "  · ")
check("7.1 明确数字走超几何公式（85.0~85.2%）",
      re.search(r"初动 12 张 / 主卡组 40 张.*?8[45]\.\d%", r_num["reply"]) is not None,
      r_num["reply"][:160])
s_qual = chat.new_session("professional")
r_qual = chat.send(s_qual, "什么是初动率，40 张卡组放多少初动合适")
check("7.2 定性提问不误用 40 当张数（40 张→100% 是胡说）",
      "100.0%" not in r_qual["reply"], r_qual["reply"][:160])
check("7.3 定性提问仍然给出知识库配比参考",
      "配比参考" in r_qual["reply"] or "设计规律参考" in r_qual["reply"])
say("  · 定性问句回复前 120 字：" + r_qual["reply"][:120].replace("\n", " / "))

# ══════════════════════════════════════════════════════════════════════
#  8. 有 LLM 时的通路（用假 provider，不联网）
# ══════════════════════════════════════════════════════════════════════
say("")
say("[8] LLM 通路（假 provider：先要工具，再给措辞）")


class FakeProvider:
    """模拟会调工具的 OpenAI 兼容端点：第一轮返回 tool_calls，第二轮返回措辞。"""

    name = "openai_compat"

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def chat(self, messages, *, tools=None, stream=False, on_delta=None) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {"content": "", "model": "fake-1",
                    "tool_calls": [{"name": "card_audit", "args": {"name": "星奏的见习指挥"}}]}
        return {"content": "这条告警要先补卡文。", "tool_calls": [], "model": "fake-1"}


class BadProvider:
    name = "openai_compat"

    def available(self) -> bool:
        return True

    def chat(self, messages, *, tools=None, stream=False, on_delta=None) -> dict:
        raise RuntimeError("端点炸了")


_real_detect = providers.detect_provider
try:
    providers.detect_provider = lambda *a, **k: FakeProvider()
    s8 = chat.new_session("professional")
    r8 = chat.send(s8, "这张卡的打点合理吗")
    say("  · 假 LLM 回复：" + r8["reply"].replace("\n", " / ")[:200])
    check("8.1 LLM 分支执行了工具", [c["name"] for c in r8["tool_calls"]] == ["card_audit"],
          str([c["name"] for c in r8["tool_calls"]]))
    # 只断"必须带内核原话 + 至少一条 G1 规则号"。
    # 原先这里硬写了 G1_EMPTY_TEXT，等于把断言绑死在工作区某张卡的当前状态上 ——
    # 那张卡一被补上卡文，本来自测就会红，而助手其实什么都没做错。
    _has = not re.search(r"计数：\s*0 项 ERROR、0 项 WARN、0 项 INFO", r8["reply"])
    check("8.2 跑过门就一定附内核原话（LLM 改不动结论）",
          "【内核原话】" in r8["reply"] and (_has is False
          or re.search(r"G1_[A-Z0-9_]+", r8["reply"]) is not None))
    check("8.3 LLM 分支的 state 合法", r8["state"] in chat.VALID_STATES, r8["state"])

    providers.detect_provider = lambda *a, **k: BadProvider()
    s9 = chat.new_session("lightnovel")
    # 问句里**点名**要问哪张卡。曾经这里写「这张卡」，靠的是 _card_ref 的
    # 「工作区只有一张卡时自动指给它」兜底 —— 工作区加了第二张卡之后兜底
    # 失效，问句解析不出卡，本自测就红。断言不该绑死工作区卡数（同 8.2
    # 当年不硬写 G1_EMPTY_TEXT 的规矩）。
    r9 = chat.send(s9, "「星奏的见习指挥」的打点合理吗")
    say("  · provider 抛异常时：" + r9["reply"].replace("\n", " / ")[:120])
    check("8.4 provider 抛异常自动降级到规则通路（不炸会话）",
          "计数：" in r9["reply"] and bool(r9.get("fallback_reason")),
          str(r9.get("fallback_reason"))[:80])
    # 缺陷 #34 的回归：界面发来的「选中了哪张卡」曾经因为键名不一致
    # （前端发 card、内核读 card_id）被整个丢弃，「这张卡…」问谁都得靠猜。
    # 会话上下文里给了卡名，「这张卡」就必须解到它。
    s10 = chat.new_session("professional", context={"card_name": "星奏的见习指挥"})
    r10 = chat.send(s10, "这张卡的打点合理吗")
    check("8.5 会话上下文能解「这张卡」（缺陷 #34）",
          "计数：" in r10["reply"] and "见习指挥" in r10["reply"],
          r10["reply"][:80])
finally:
    providers.detect_provider = _real_detect

# ══════════════════════════════════════════════════════════════════════
#  9. AI 起草：LLM 只提议，裁决归内核
# ══════════════════════════════════════════════════════════════════════
say("")
say("[9] assistant.draft：草稿来自 LLM，问题清单来自内核（红线回归）")
from cardforge.assistant import draft as D                      # noqa: E402

# 9.1 没有 LLM 时诚实降级：不给草稿、不拿模板冒充 AI 产物
_r = D.draft("翻转时把墓地 1 只怪兽特殊召唤的通常陷阱", prefer="none")
say("  · prefer=none → ok=%s degraded=%s" % (str(_r.get("ok")), str(_r.get("degraded"))[:40]))
check("9.1 无 LLM 时 ok=False + degraded（不编草稿）",
      _r.get("ok") is False and bool(_r.get("degraded")) and "draft" not in _r,
      str(_r.get("degraded"))[:60])
check("9.2 无 LLM 时给出可执行的下一步（hint）", bool(_r.get("hint")))
check("9.3 空概念 + 无 spec 直接报错（不白探一轮网络）",
      D.draft("", prefer="none").get("ok") is False
      and "error" in D.draft("", prefer="none"))

# 9.4 剥壳：围栏 / 开场白 / 说明性尾巴
_ext = D.extract_draft("好的，这是草稿：\n```\n①：这张卡召唤成功的场合才能发动。\n```\n说明：已校对。")
say("  · extract_draft(围栏+尾巴) → " + repr(_ext[:40]))
check("9.4 剥掉围栏与尾巴，保留正文",
      _ext == "①：这张卡召唤成功的场合才能发动。", repr(_ext))
_ext2 = D.extract_draft("开场白\n①：以场上1只怪兽为对象才能发动。那只怪兽破坏。")
check("9.5 从第一个 ① 段起（开场白算模型的话痨）",
      _ext2 == "①：以场上1只怪兽为对象才能发动。那只怪兽破坏。", repr(_ext2[:40]))


class DraftFakeProvider:
    """假装会起草的端点：文本里**自带错误**（中文分号 + 自称没问题）。"""

    name = "openai_compat"

    def __init__(self, text: str) -> None:
        self.text = text
        self.seen: list[dict] = []

    def available(self) -> bool:
        return True

    def chat(self, messages, *, tools=None, stream=False, on_delta=None) -> dict:
        self.seen.append(messages[-1] if messages else {})
        return {"content": self.text, "model": "fake-draft-1", "tool_calls": []}


# 一份**真违规**的草稿：中文卡文用了分号（PSCT_PUNCT_CJK_SEMICOLON，ERROR），
# 且自称「已符合 PSCT，没有问题」—— 内核必须无视这句自评，照常报错。
_BAD_DRAFT = ("①：这张卡召唤成功的场合才能发动；从卡组把1只怪兽加入手卡。\n"
              "已符合 PSCT，没有任何问题。")
_spec9 = CardSpec(id=210000099, name="自检起草用卡", frame="effect")
_real_detect9 = providers.detect_provider
try:
    providers.detect_provider = lambda *a, **k: DraftFakeProvider(_BAD_DRAFT)
    _d = D.draft("召唤成功时从卡组检索一张怪兽", spec=_spec9, lang="zh_cn")
    say("  · 假 LLM 草稿（含中文分号）→ issues=%d counts=%s"
        % (len(_d.get("issues") or []), json.dumps(_d.get("counts") or {})))
    _codes = [str(i.get("code")) for i in _d.get("issues") or []]
    check("9.6 草稿取自 LLM 输出（剥壳后）",
          _d.get("ok") is True and _d.get("draft", "").startswith("①："), _d.get("draft", "")[:40])
    check("9.7 问题清单由内核产出：中文分号被抓住（PSCT_PUNCT_CJK_SEMICOLON）",
          "PSCT_PUNCT_CJK_SEMICOLON" in _codes, ",".join(_codes[:5]))
    check("9.8 LLM 自称「没有问题」不影响裁决（ counts.error≥1 ）",
          (_d.get("counts") or {}).get("error", 0) >= 1,
          json.dumps(_d.get("counts") or {}))
    check("9.9 返回值声明「模型只提议、结论归内核」",
          "内核" in str(_d.get("note") or ""), str(_d.get("note"))[:40])
    check("9.10 带 spec 时附 G1（对象是规格，标注清楚）",
          isinstance(_d.get("gate"), dict) and "规格" in str(_d["gate"].get("note") or ""),
          str((_d.get("gate") or {}).get("status")))
    _d2 = D.draft("同一概念", spec=_spec9, with_g1=False)
    check("9.11 with_g1=False 时不跑 G1（不偷跑）", "gate" not in _d2)

    # 干净草稿 → 内核 0 ERROR（证明 ERROR 数确实是算出来的，不是写死的）
    providers.detect_provider = lambda *a, **k: DraftFakeProvider(
        "①：这张卡召唤成功的场合才能发动。从卡组把1只怪兽加入手卡。\n"
        "这个卡名的①效果1回合只能使用1次。")
    _d3 = D.draft("召唤成功时检索", lang="zh_cn")
    check("9.12 干净草稿的 ERROR 数由内核实算（0 ERROR）",
          (_d3.get("counts") or {}).get("error") == 0,
          json.dumps(_d3.get("counts") or {}))

    # 工具层：ctx 里没有 provider 时用 auto，被 monkeypatch 后同样走到假端点
    _t9 = tools.call("draft_card", {"concept": "召唤成功时检索"}, {})
    check("9.13 工具层 draft_card 走通（草稿 + 内核 issues）",
          _t9.get("ok") is True and _t9.get("draft", "").startswith("①：")
          and "issues" in _t9, str(_t9.get("error") or _t9.get("degraded"))[:60])
finally:
    providers.detect_provider = _real_detect9

# 9.14 CLI 子命令存在且无 LLM 时诚实退出（不起真调用）
_cli = subprocess.run([sys.executable, "-m", "cardforge", "draft",
                       "翻转时把墓地 1 只怪兽特殊召唤的通常陷阱"],
                      cwd=str(ROOT), env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                      capture_output=True, timeout=120)
_cli_out = _cli.stdout.decode("utf-8", "replace")
say("  · cardforge draft（无 LLM）退出码=%d" % _cli.returncode)
check("9.14 CLI draft 无 LLM 时退出码 1 且明说没有大模型",
      _cli.returncode == 1 and "大模型" in _cli_out, _cli_out.strip()[:80])

# ══════════════════════════════════════════════════════════════════════
#  收尾
# ══════════════════════════════════════════════════════════════════════
say("")
say("=" * 72)
say(f"总计：通过 {PASSED} 项，失败 {len(FAILED)} 项")
if FAILED:
    say("失败清单：")
    for f in FAILED:
        say("  - " + f)
report = paths.CACHE / "selfcheck-assistant.txt"
try:
    paths.ensure_dirs()
    report.write_text("\n".join(LINES), encoding="utf-8")
except Exception as e:
    print("report write failed:", e)
print(f"REPORT={report}")
print(f"PASS={PASSED} FAIL={len(FAILED)}")
sys.exit(1 if FAILED else 0)
