"""场景单测 —— 把「这张卡的效果真的起效了吗」拆成可断言的最小局面。

与 :func:`cardforge.duel.bot.run_duel` 的分工
--------------------------------------------
``run_duel`` 回答「整局跑不跑得完」，本模块回答「**这一条效果**在它的触发时点
有没有产生可观测的结果」。两者都不能替代对方：一局跑完不代表效果对，
效果对也不代表两卡交互没问题。

三条诚实性约束（这是本项目的第一原则，别改）
--------------------------------------------
1. **区分三种失败**：驱动跑不动 / 脚本缺失 / 结算不符预期。
   只有第三种才是"你的卡有问题"，前两种必须写成 ``not_tested``，
   绝不允许算成 pass —— 否则 G3 又变成谎报。
2. **没观测到 ≠ 失败**。简易 bot 不一定会走出触发条件，
   这种情况返回 ``observed=False`` 并说明原因，``ok`` 仍为真。
3. 断言只用**引擎消息里客观存在的东西**（move / destroy / summon / chain / LP 变化），
   不去猜 Lua 内部状态。断言词汇表现在含**数值**：``at_least`` / ``at_most``
   可直接断 LP 与伤害总量（``damage_dealt`` / ``damage_taken`` / ``recover_total`` /
   ``lp_a`` / ``lp_b``），见 :func:`_check`。
"""
from __future__ import annotations

# 注意：Scenario 有个字段就叫 ``field``（契约规定的名字），会把
# ``dataclasses.field`` 遮掉 —— 所以这里按别名导入。
from dataclasses import dataclass, field as _f
from typing import Any, Optional

from ..core import paths
from ..core.models import CardSpec
from . import bot
from . import ocgcore as oc

__all__ = ["Scenario", "SCENARIOS", "run", "run_batch", "official_sample"]

# ── 引擎消息号（与 ocgcore 的 MSG_* 对齐；这里只用到观测断言需要的几个）──
MSG_MOVE = 50
MSG_SUMMONED = 61
MSG_SPSUMMONED = 62
MSG_DESTROY = 53
MSG_RELEASE = 52
MSG_CHAINING = 70
MSG_CHAIN_SOLVING = 72
MSG_CHAIN_SOLVED = 73
MSG_DAMAGE = 91
MSG_RECOVER = 92
MSG_DRAW = 90
MSG_SELECT_CHAIN = 16
LOCATION_HAND, LOCATION_MZONE, LOCATION_GRAVE, LOCATION_REMOVED, LOCATION_DECK = \
    oc.LOCATION_HAND, oc.LOCATION_MZONE, oc.LOCATION_GRAVE, oc.LOCATION_REMOVED, \
    oc.LOCATION_DECK


@dataclass
class Scenario:
    """一个最小可断言局面。"""
    name: str = ""
    hand: list = _f(default_factory=list)      # 要发进手牌的卡号（或 {code,...}）
    field: list = _f(default_factory=list)     # 要摆到场上的卡
    deck: list = _f(default_factory=list)      # 双方卡组（空=自动取官方样本）
    action: dict = _f(default_factory=dict)    # 传给 bot 的倾向提示
    expect: dict = _f(default_factory=dict)    # 断言：见 _check()
    note: str = ""


# ══════════════════════════════════════════════════════════════════════
#  官方卡样本（证明驱动本身是对的，不依赖 DIY 卡）
# ══════════════════════════════════════════════════════════════════════
def official_sample(n: int = 8) -> list[int]:
    """从官方卡池取 n 个**有脚本**的卡号。取不到返回空表。"""
    try:
        ids = bot.sample_card_ids(n)
    except Exception:
        return []
    return [int(i) for i in ids if int(i) > 0][:n]


# ══════════════════════════════════════════════════════════════════════
#  执行
# ══════════════════════════════════════════════════════════════════════
def run(sc: Scenario, spec: Optional[CardSpec] = None, *, seed: int = 7) -> dict:
    """跑一个场景。

    返回 ``{"ok","name","detail","observed","status","log"}``：

    * ``status="pass"`` —— 断言成立；
    * ``status="fail"`` —— **脚本层**问题：结算与预期不符 / 引擎报了脚本报错；
    * ``status="not_tested"`` —— 驱动跑不动、或 DIY 卡没有脚本、或 bot 没走出
      触发条件。``ok`` 对 pass 与 not_tested 都为真，但界面必须区别显示。

    ``seed`` 决定主机侧洗牌（见 ``bot.run_duel``）：同 seed 可复现，
    异 seed 发散 —— 多 seed 稳定性检查靠把它换成不同值重跑。
    """
    out: dict[str, Any] = {"name": sc.name or "(未命名场景)", "ok": False,
                           "status": "not_tested", "detail": "", "observed": False,
                           "log": []}
    # ── 0. 引擎在不在 ──
    st = _engine_ok()
    if not st[0]:
        out["detail"] = f"驱动层：引擎不可用（{st[1]}）—— 本场景未运行，不算失败"
        return out

    # ── 1. 被测卡有没有脚本 ──
    code = int(getattr(spec, "id", 0) or 0) if spec is not None else 0
    lua = str(getattr(spec, "lua", "") or "").strip() if spec is not None else ""
    cards: dict[int, Any] = {}
    if code:
        if not lua:
            out["detail"] = (f"脚本层：卡号 {code} 没有 Lua 脚本，本场景无从验证。"
                             f"先跑「生成脚本」再回来 —— 这不算你的效果有问题")
            return out
        cards[code] = spec

    deck = [int(x) for x in (sc.deck or []) if int(x) > 0]
    if not deck:
        deck = official_sample(6)
        if not deck:
            out["detail"] = "驱动层：官方卡池取不到样本卡号，无法组队 —— 本场景未运行"
            return out
    # 被测卡进卡组（各 3 张），保证 bot 有机会摸到它
    subject = [code] * 3 if code else []
    deck_a = (subject + deck * 7)[:40]
    deck_b = (deck[-4:] * 10)[:40]

    scenario: dict[str, Any] = {"field": list(sc.field), "hand": list(sc.hand),
                                "action": dict(sc.action or {})}
    if code:
        # 预置手牌 + 指名召唤：简易 bot 默认会挑它第一个能动的动作，
        # 不告诉它「要召唤这张卡」的话，被测卡可能整局都没上场，
        # 那场景就只能报"没测到"，白跑一局。
        scenario["hand"] = list(sc.hand) + [{"code": code, "loc": LOCATION_HAND,
                                             "seq": 0, "pos": 0}]
        scenario["action"].setdefault("summon_code", code)
    res = bot.run_duel(deck_a, deck_b, seed=int(seed or 7), max_steps=2500,
                       cards=cards or None, scenario=scenario)

    out["log"] = (res.get("log") or [])[:400]
    errors = list(res.get("errors") or [])
    detail = res.get("detail") or {}

    # ── 2. 没跑完：先分清是谁的锅 ──
    blocking = str(res.get("blocking") or "")
    if not res.get("ok") and not res.get("finished"):
        if blocking == "bot" and not errors:
            out["detail"] = ("驱动层：简易 bot 走投无路，整局没跑完"
                             f"（回合 {res.get('turns')}，步数 {res.get('steps')}）。"
                             "引擎没报脚本错 —— 这是内置 bot 的决策局限，"
                             "不算这张卡失败，也不算它通过")
            return out
        if _looks_like_script_error(errors):
            out["status"] = "fail"
            out["detail"] = "脚本层：对局中引擎报出脚本报错 → " + "；".join(errors[:3])
            return out
        out["detail"] = ("驱动层：整局没跑完 → " + "；".join(errors[:3] or ["无错误信息"])
                         + f"（回合 {res.get('turns')}，步数 {res.get('steps')}）")
        return out

    # ── 3. 脚本报错优先于一切断言 ──
    if errors:
        out["status"] = "fail"
        out["detail"] = "脚本层：跑完了但引擎报错 → " + "；".join(errors[:3])
        return out

    # ── 4. 断言 ──
    obs = _observe(out["log"], code, lp=res.get("lp") or [0, 0])
    verdict, why = _check(sc.expect, obs, res, chained=int(obs.get("subject_chained") or 0))
    out["status"] = verdict
    out["ok"] = verdict != "fail"
    out["observed"] = verdict == "pass"
    out["observed_counts"] = {k: v for k, v in obs.items() if isinstance(v, int)}
    out["detail"] = why if verdict != "pass" else f"{why}（回合 {res.get('turns')}）"
    return out


def run_batch(scenarios: list[Scenario], specs: list[CardSpec]) -> list[dict]:
    """跑一批。``specs`` 目前取第一张（gates 就是这么传的）。"""
    spec = specs[0] if specs else None
    out: list[dict] = []
    for sc in scenarios or []:
        try:
            out.append(run(sc, spec))
        except Exception as e:
            out.append({"name": getattr(sc, "name", "?"), "ok": False,
                        "status": "fail", "observed": False,
                        "detail": f"场景执行异常（驱动层缺陷）：{type(e).__name__}: {e}",
                        "log": []})
    return out


# ══════════════════════════════════════════════════════════════════════
#  观测与断言
# ══════════════════════════════════════════════════════════════════════
def _observe(log: list[dict], code: int, *, lp: Optional[list] = None) -> dict[str, Any]:
    """把消息流压成几个可断言的计数**与数值**。

    ``code`` 是被测卡号；它单独计一次 ``subject_chained`` —— 有了这个数才能
    区分「bot 没把效果发动出来」（→ 没测到）和「效果发动并结算完了却没产生
    应有结果」（→ 真失败）。把前者算成失败是误报，会把人引去改没坏的脚本。

    数值断言（docs/03 §三-c 的闭环项）：``damage_dealt`` / ``damage_taken`` /
    ``recover_total`` 是消息流里**客观记载**的 LP 变动总量（玩家 0 = 我方，
    1 = 对方），``lp_a`` / ``lp_b`` 是终局 LP。它们可以被 ``at_least`` /
    ``at_most`` 直接断言，例如 ``expect={"at_least": {"damage_dealt": 1000}}``。
    """
    obs: dict[str, Any] = {
        "move": 0, "to_hand": 0, "to_grave": 0, "removed": 0, "to_deck": 0,
        "summoned": 0, "spsummoned": 0, "destroy": 0, "release": 0,
        "chaining": 0, "chain_solved": 0, "damage": 0, "recover": 0,
        "draw": 0, "steps": len(log), "turns": 0,
        "subject_chained": 0, "subject_moved": 0,
        "damage_dealt": 0, "damage_taken": 0, "recover_total": 0,
    }
    _lp = list(lp or [0, 0])
    obs["lp_a"] = int(_lp[0] if len(_lp) > 0 else 0)
    obs["lp_b"] = int(_lp[1] if len(_lp) > 1 else 0)
    for e in log:
        mid = int(e.get("id", -1) or -1)
        obs["turns"] = max(obs["turns"], int(e.get("turn", 0) or 0))
        if mid == MSG_MOVE:
            obs["move"] += 1
            dest = int(e.get("to_location") or 0)
            for bit, key in ((LOCATION_HAND, "to_hand"), (LOCATION_GRAVE, "to_grave"),
                             (LOCATION_REMOVED, "removed"), (LOCATION_DECK, "to_deck")):
                if dest & bit:
                    obs[key] += 1
            if code and int(e.get("code") or 0) == code:
                obs["subject_moved"] += 1
        elif mid == MSG_SUMMONED:
            obs["summoned"] += 1
        elif mid == MSG_SPSUMMONED:
            obs["spsummoned"] += 1
        elif mid == MSG_DESTROY:
            obs["destroy"] += 1
        elif mid == MSG_RELEASE:
            obs["release"] += 1
        elif mid == MSG_CHAINING:
            obs["chaining"] += 1
            if code and int(e.get("code") or 0) == code:
                obs["subject_chained"] += 1
        elif mid == MSG_CHAIN_SOLVED:
            obs["chain_solved"] += 1
            if code and int(e.get("code") or 0) == code:
                obs["subject_chained"] += 1
        elif mid == MSG_DAMAGE:
            obs["damage"] += 1
            amount = int(e.get("amount") or 0)
            # 消息里的 player 是**受伤方**：0 = 我方(A)，1 = 对方(B)
            if int(e.get("player") or 0) == 1:
                obs["damage_dealt"] += amount
            else:
                obs["damage_taken"] += amount
        elif mid == MSG_RECOVER:
            obs["recover"] += 1
            obs["recover_total"] += int(e.get("amount") or 0)
        elif mid == MSG_DRAW:
            obs["draw"] += 1
    return obs


def _check(expect: dict, obs: dict, res: dict, *, chained: int = 0) -> tuple[str, str]:
    """返回 ``(verdict, 说明)``，verdict ∈ ``pass`` / ``fail`` / ``not_tested``。

    断言只用引擎消息里客观存在的东西（位置变化 / 召唤 / 连锁 / LP 数值），
    不去猜 Lua 内部状态。可用键（全部可选，缺省继承保守默认）：

    * ``min_turns``     —— 最少打到第几回合（默认 2，防止一回合死循环"过关"）
    * ``at_least``      —— ``{计数或数值键: 下界}``；数值键见 :func:`_observe`
                           的 ``damage_dealt / damage_taken / recover_total /
                           lp_a / lp_b``
    * ``at_most``       —— ``{键: 上界}``；超了直接 fail（例如 ``{"damage_taken": 0}``）
    * ``none_of``       —— 兼容旧写法，等价于 ``at_most``（只判计数类键）

    「没观测到」与「失败」仍然严格分开：没有被测卡进连锁的缺席 → not_tested。
    """
    exp = dict(expect or {})
    min_turns = int(exp.get("min_turns", 2))
    if int(res.get("turns") or 0) < min_turns:
        return "fail", (f"只跑到回合 {res.get('turns')}，要求 ≥{min_turns}"
                        f"（多半是脚本里有死循环或非法调用）")
    at_least = dict(exp.get("at_least") or {})
    # 数值类键（LP/伤害/回复）不依赖「被测卡进没进连锁」——它们是全局客观量，
    # 断言不满足就是 fail；而位置/计数类键缺省时仍走「没测到」的诚实降级。
    value_keys = {"damage_dealt", "damage_taken", "recover_total", "lp_a", "lp_b"}
    if at_least:
        unmet = {k: int(obs.get(k, 0)) for k, v in at_least.items()
                 if int(obs.get(k, 0)) < int(v)}
        if not unmet:
            return "pass", "观测到 " + "、".join(
                f"{k}×{obs.get(k)}" for k in at_least)
        only_values = all(k in value_keys for k in unmet)
        if only_values:
            return "fail", ("数值断言未达标（LP/伤害类断言不依赖被测卡是否进连锁，"
                            "直接判定）：" +
                            "、".join(f"{k} 实际 {obs.get(k, 0)}，要求 ≥{at_least[k]}"
                                      for k in unmet))
        if chained:
            return "fail", ("被测卡的效果进了连锁并结算完，却没产生应有结果：" +
                            "、".join(f"{k} 实际 {a}，要求 ≥{b}"
                                      for k, (a, b) in
                                      ((k, (obs.get(k, 0), at_least[k]))
                                       for k in unmet)) +
                            " —— 这是脚本层问题，回去改效果实现")
        return "not_tested", ("没观测到 " + "、".join(
            f"{k}（实际 {obs.get(k, 0)}/{at_least[k]}）" for k in unmet) +
            f"，且被测卡一次都没进过连锁 —— 简易 bot 没走出触发条件。"
            f"「没测到」不等于「不生效」，也不等于「生效了」")
    for k, cap in (exp.get("none_of") or {}).items():
        if int(obs.get(k, 0)) > int(cap):
            return "fail", f"{k} 出现 {obs.get(k)} 次，超过上限 {cap}"
    for k, cap in (exp.get("at_most") or {}).items():
        if k not in obs:
            return "not_tested", f"断言键 {k} 不在可观测项里（拼写错误？）"
        if int(obs.get(k, 0)) > int(cap):
            return "fail", f"{k} = {obs.get(k)}，超过上限 {cap}"
    lp_txt = (f"终局 LP {obs.get('lp_a')}:{obs.get('lp_b')}、"
              f"伤害 己方造成 {obs.get('damage_dealt')} / 承受 {obs.get('damage_taken')}"
              if any(exp.get(k) for k in ("at_least", "at_most", "none_of"))
              or exp.get("show_lp") else "")
    return "pass", (f"局面正常推进：回合 {res.get('turns')}、"
                    f"移动 {obs['move']} 次、连锁解掉 {obs['chain_solved']} 次"
                    + (f"；{lp_txt}" if lp_txt else ""))


def _looks_like_script_error(errors: list[str]) -> bool:
    keys = ("lua", "script", "error", "attempt to", "traceback", "脚本")
    return any(any(k in (e or "").lower() for k in keys) for e in errors)


_ENGINE_OK: Optional[tuple[bool, str]] = None


def _engine_ok() -> tuple[bool, str]:
    """引擎在不在。只探一次并缓存 —— 每条场景都探一遍会拖慢 G3。"""
    global _ENGINE_OK
    if _ENGINE_OK is not None:
        return _ENGINE_OK
    try:
        from . import engine
        st = engine.detect()
        _ENGINE_OK = (getattr(st, "level", "") == "ocgcore",
                      getattr(st, "reason", "") or "")
    except Exception as e:
        _ENGINE_OK = (False, f"engine.detect() 失败：{type(e).__name__}: {e}")
    return _ENGINE_OK


# ══════════════════════════════════════════════════════════════════════
#  内置场景模板
#  顺序有意义：gates.g3_duel 只取前 4 个。
# ══════════════════════════════════════════════════════════════════════
SCENARIOS: list[Scenario] = [
    Scenario(
        name="开局与推进（驱动自检）",
        note="不依赖被测卡的具体效果：能开局、能推进回合、引擎不报错，"
             "就证明 ctypes 驱动与消息机是通的。",
        expect={"min_turns": 4},
    ),
    Scenario(
        name="怪兽召唤与连锁",
        note="场面预置一张怪兽，验证召唤流程会真实发生。"
             "「召唤成功时」类触发点就挂在这条链上。",
        expect={"min_turns": 3, "at_least": {"summoned": 1}},
    ),
    Scenario(
        name="卡区移动（检索 / 回收类的共同观测点）",
        note="任何在卡组 / 手卡 / 墓地之间移动卡的效果，都会在 MSG_move 上"
             "留下目的地位置。这里只断言「至少发生一次进手卡的移动」，"
             "断不到就是没起效。",
        expect={"min_turns": 3, "at_least": {"to_hand": 1}},
    ),
    Scenario(
        name="魔陷发动与结算",
        note="魔法 / 陷阱的发动会走完整连锁（chaining → chain_solved）。"
             "一次连锁都没解掉，说明发动条件或 SetCode 写错了。",
        expect={"min_turns": 3, "at_least": {"chain_solved": 1}},
    ),
]
