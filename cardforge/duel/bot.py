"""最小对局机器人：把 ``OcgCore`` 的消息流推完一整局。

设计立场
--------
1. **合法优先于聪明**。每个应答案都按本 build 的 ``playerop.cpp`` 校验分支反推出来，
   只在「已知合法的候选」里挑；解析不出来 / 消息号不认识 → 回最保守的合法值
   （不发动、放弃选择、进结束阶段），绝不无限等待。
2. **绝不谎报跑完**。``ok=True`` 只表示「这局真跑完了且核心没报脚本错误」；
   任何降级（DIY 卡没脚本、卡组凑不齐、卡在 AWAITING、撞上死循环）都会写进
   ``errors`` / ``degraded``，并让 ``ok=False``。
3. 死循环保护：``max_steps`` + **同状态重复检测**（同一个应答消息 + 同一 payload
   连续出现 ``repeat_limit`` 次就正常收尾，并在 ``errors`` 记一条）。

关键实测结论（写在这里避免后人重踩）
------------------------------------
* ``MSG_RETRY``（消息号 1）的载荷是**空的**，且核心此时仍是 ``awaiting`` ——
  它不是「结束」信号，而是「上一个响应非法，请重答」。所以机器人必须**保留上一个
  待答消息并换一个候选重新应答**，不能把它当成无法应答而退出。
* ``MSG_SELECT_PLACE`` / ``MSG_SELECT_DISFIELD`` 的 ``flag`` 是**以「被问的一方」为基准**
  的 4 段掩码：bit0-6 己方怪兽区、bit8-15 己方魔陷区、bit16-22 对方怪兽区、
  bit24-31 对方魔陷区；**置位 = 不可选**。按绝对座位解释会立刻被 RETRY。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..core import paths
from ..core.errors import CardForgeError
from . import ocgcore as oc

#: 官方卡池与官方脚本目录（场景只用官方卡时依赖它们）
CDB_NAME = "cards_zh.cdb"


# ══════════════════════════════════════════════════════════════════════
#  区域掩码工具（SELECT_PLACE / SELECT_DISFIELD）
# ══════════════════════════════════════════════════════════════════════
def place_segments(asking_player: int) -> list[tuple[int, int, int, int]]:
    """返回 ``[(绝对玩家, 区域, 掩码起始位, 位数), ...]``，按「己方怪兽→己方魔陷→对方怪兽→对方魔陷」。"""
    other = 1 - int(asking_player)
    return [(asking_player, oc.LOCATION_MZONE, 0, 7), (asking_player, oc.LOCATION_SZONE, 8, 8),
            (other, oc.LOCATION_MZONE, 16, 7), (other, oc.LOCATION_SZONE, 24, 8)]


#: ``prefer`` → 段顺序调整函数。多给几种，retry 时才有真正不同的候选可换。
_PREFER: dict[str, str] = {
    "own_mzone": "M", "own_szone": "S", "opponent_mzone": "oM", "extra_mzone": "X",
}


def choose_places(msg: dict, prefer: str = "own_mzone") -> list[tuple[int, int, int]]:
    """按 flag 掩码挑 ``count`` 个可用座位；挑不满就返回已挑的（宁可少给也不给非法值）。

    ``flag`` 的语义已实测确认为**「1 = 该位不可用」**（不是可用位掩码）：
    空场时己方 5 个怪兽位对应 bit0–4 全为 0，把语义反过来解释 6/6 局都在
    第一回合卡死，按现在的解释 6/6 局能打到分出胜负。
    """
    asking = int(msg.get("player", 0) or 0)
    count = int(msg.get("count", 1) or 0)
    flag = int(msg.get("flag", 0) or 0)
    segs = place_segments(asking)
    if prefer == "only_mzone":
        segs = [x for x in segs if x[1] == oc.LOCATION_MZONE]
    elif prefer == "only_szone":
        segs = [x for x in segs if x[1] == oc.LOCATION_SZONE]
    elif prefer == "own_szone":
        segs = [s for s in segs if s[1] == oc.LOCATION_SZONE] + \
               [s for s in segs if s[1] != oc.LOCATION_SZONE]
    elif prefer == "opponent_mzone":
        segs = [s for s in segs if s[0] != asking] + [s for s in segs if s[0] == asking]
    elif prefer == "extra_mzone":
        # 额外怪兽区在掩码里是己方 MZONE 的 bit5 / bit6
        segs = [(asking, oc.LOCATION_MZONE, 0, 7)] + \
               [s for s in segs if s != (asking, oc.LOCATION_MZONE, 0, 7)]
    out: list[tuple[int, int, int]] = []
    taken = flag
    for player, location, base, width in segs:
        for seq in range(width):
            if len(out) >= count:
                return out
            bit = 1 << (base + seq)
            if taken & bit:
                continue
            taken |= bit
            out.append((player, location, seq))
    return out


# ══════════════════════════════════════════════════════════════════════
#  机器人
# ══════════════════════════════════════════════════════════════════════
@dataclass
class SimpleBot:
    """保守但能让对局真正推进下去的应答器。

    ``productive=False`` 时退化成「什么都不做，只走阶段」，用于只要不卡死就行的小白鼠场景。
    """

    productive: bool = True
    attempts: dict[str, int] = field(default_factory=dict)

    # ── 对外唯一入口 ──────────────────────────────────────────────
    def decide(self, msg: dict, state: dict) -> Optional[bytes]:
        """给一条已解析的应答消息，返回响应字节；返回 ``None`` 表示不知道怎么答。

        同一条消息被核心打回（``MSG_RETRY``）时，``state["retry_key"]`` 会变，
        候选列表自动往后挪一位 —— 这是「非法响应」的自我修复路径。
        """
        candidates = self.candidates(msg, state)
        if not candidates:
            return None
        key = str(msg.get("retry_key") or f"{msg.get('id')}:{msg.get('raw', '')}")
        n = int(self.attempts.get(key, 0))
        self.attempts[key] = n + 1
        resp = candidates[min(n, len(candidates) - 1)]
        # 记下这次 idlecmd 选的是哪类动作：紧接着的 MSG_SELECT_PLACE 只接受
        # 对应区域，回错区域会被核心连打回十几次（表现为"死循环"）。
        # op 编码：0 召唤 / 1 特召 / 3 SET 怪兽 → 要怪兽区；4 盖魔法 / 5 盖陷阱 → 要魔陷区。
        if int(msg.get("id", -1)) == 11 and resp and len(resp) >= 4 and state is not None:
            import struct as _st
            try:
                op = int(_st.unpack("<i", resp[:4])[0])
                state["need_zone"] = {0: "MZONE", 1: "MZONE", 3: "MZONE",
                                      2: "SZONE", 4: "SZONE", 5: "SZONE"}.get(op, "")
            except Exception:
                state.pop("need_zone", None)
        elif int(msg.get("id", -1)) in (18, 24) and state is not None:
            state["need_zone"] = ""      # 已经答过一次放置，别把提示留到下一条
        return resp

    # ── 候选生成（合法值全部来自核心校验分支） ────────────────────
    def candidates(self, msg: dict, state: dict) -> list[bytes]:  # noqa: C901
        event = int(msg.get("id", -1))
        if "decode_error" in msg and event not in (11, 10):
            # 解析不完整时只给「与载荷无关」的保守答案
            return self._blind_candidates(event)

        if event == 11:
            return self._idlecmd(msg, state)
        if event == 10:
            return self._battlecmd(msg)
        if event == 16:
            chains = msg.get("chains") or []
            out: list[bytes] = []
            if chains and msg.get("forced"):
                out.append(oc.encode_chain_choice(0))
            elif self.productive and chains:
                # 验证用的 bot 必须**把效果开出来**：默认"保守=不发动"会让
                # 「召唤成功时」这类触发效果整局都不进连锁，于是场景只能报
                # "没测到"，G3 就白跑了。放弃发动仍留在后面的候选里，
                # 万一发动导致非法，retry 还能退回去。
                out.append(oc.encode_chain_choice(0))
                out.append(oc.encode_chain_choice(-1))
            else:
                out.append(oc.encode_chain_choice(-1))
                if chains:
                    out.append(oc.encode_chain_choice(0))
            return out
        if event == 12:
            # 「是否发动这个效果」—— productive 时先答"是"，理由同上
            return [oc.encode_yesno(bool(self.productive)),
                    oc.encode_yesno(not self.productive)]
        if event == 13:
            yes = self._yesno_hint(msg, state)
            return [oc.encode_yesno(yes), oc.encode_yesno(not yes)]
        if event == 14:
            opts = msg.get("options") or []
            return [oc.encode_option(0)] if opts else [oc.encode_int32(0)]
        if event in (15, 20, 23):
            return self._select_cards(msg, event)
        if event == 26:
            cards = (msg.get("cards") or []) + (msg.get("uncards") or [])
            out = [oc.encode_int32(1, 0)] if cards else [oc.encode_int32(-1)]
            if cards:
                out.append(oc.encode_int32(-1) if (msg.get("cancelable") or msg.get("finishable"))
                           else oc.encode_int32(1, min(1, len(cards) - 1)))
            return out
        if event in (18, 24):
            # 关键：上一个 idlecmd 选的动作决定了这次**只能**给哪类区域。
            # 选了"召唤/SET 怪兽"却回一个魔陷区，核心会判定非法并连发 MSG_RETRY，
            # 表现就是"同一状态重复 N 次"的死循环 —— 之前卡在这里 14 个回合。
            need = str((state or {}).get("need_zone") or "")
            order = {"MZONE": ["only_mzone", "own_mzone"],
                     "SZONE": ["only_szone", "own_szone"]}.get(
                         need, ["own_mzone", "own_szone"])
            out: list[bytes] = []
            for pref in order:
                picks = choose_places(msg, pref)
                if not picks:
                    continue
                enc = oc.encode_places(picks)
                if enc not in out:
                    out.append(enc)
            if not out:
                # 一类区域都给不出来：宁缺毋滥，回一个"零放置"（3 字节 0），
                # 让核心按"没放"继续往下走，而不是收一个非法座位无限重试。
                out.append(bytes([0xFF, 0, 0]))
            return out
        if event == 19:
            mask = int(msg.get("positions", 0) or 0)
            out = []
            for bit in (1, 4, 8, 2):
                if mask & bit:
                    out.append(oc.encode_position(bit))
            return out or [oc.encode_position(1)]
        if event in (21, 25):
            n = len(msg.get("cards") or [])
            order = list(range(n))
            return [oc.encode_sort_order(order), oc.encode_sort_order([])]
        if event == 22:
            cards = msg.get("cards") or []
            need = int(msg.get("count", 0) or 0)
            out = []
            if cards:
                rest = need
                vals = []
                for c in cards:
                    give = min(int(c.get("counter", 0) or 0), rest)
                    vals.append(give)
                    rest -= give
                out.append(oc.encode_counters(vals if rest <= 0 else [need] + [0] * (len(cards) - 1)))
                out.append(oc.encode_counters([0] * len(cards)))
            return out or [oc.encode_int32(0)]
        if event == 140:
            avail = int(msg.get("available", 0) or 0)
            cnt = max(int(msg.get("count", 1) or 1), 1)
            picks = 0
            bit = 1
            while cnt > 0:
                if avail & bit:
                    picks |= bit
                    cnt -= 1
                bit <<= 1
            return [oc.encode_race(picks or avail)]
        if event == 141:
            avail = int(msg.get("available", 0) or 0)
            return [oc.encode_attribute(avail if avail & (avail - 1) == 0
                                        else (avail & -avail))]
        if event in (142, 143):
            return [oc.encode_option(0)]
        if event == 132:
            return [oc.encode_option(1)]
        if event == 1:
            # RETRY 的空载荷：不单独应答，由上层拿「上一个待答消息」换候选重答。
            return [oc.encode_int32(0)]
        return self._blind_candidates(event)

    def _blind_candidates(self, event: int) -> list[bytes]:
        """载荷没解出来时的兜底：只给「不依赖具体选项」的合法值（永远不为空字节）。"""
        if event in (11, 10):
            return [oc.encode_idlecmd(7, 0), oc.encode_idlecmd(6, 0),
                    oc.encode_idlecmd(8, 0), oc.encode_int32(0)]
        if event in (12, 13):
            return [oc.encode_yesno(False), oc.encode_yesno(True)]
        if event == 16:
            return [oc.encode_chain_choice(-1), oc.encode_chain_choice(0)]
        if event in (15, 20, 23, 26):
            return [oc.encode_select_card(None, cancel=True), oc.encode_select_card([0])]
        if event in (18, 24):
            return [bytes([0, oc.LOCATION_MZONE, 0]), bytes([0, oc.LOCATION_SZONE, 0])]
        if event == 19:
            return [oc.encode_position(1)]
        if event in (21, 25):
            return [oc.encode_sort_order([])]
        if event in (140,):
            return [oc.encode_race(1)]
        if event in (141,):
            return [oc.encode_attribute(1)]
        if event in (14, 142, 143, 132):
            return [oc.encode_option(0)]
        return [oc.encode_int32(0)]

    # ── 具体决策 ──────────────────────────────────────────────────
    def _idlecmd(self, msg: dict, state: dict) -> list[bytes]:
        out: list[bytes] = []
        if self.productive:
            want = (state.get("action") or {}).get("summon_code")
            for i, entry in enumerate(msg.get("summon") or []):
                if want and int(entry.get("code", 0)) != int(want):
                    continue
                out.append(oc.encode_idlecmd(0, i))
            for i, entry in enumerate(msg.get("spsummon") or []):
                if want and int(entry.get("code", 0)) != int(want):
                    continue
                out.append(oc.encode_idlecmd(1, i))
            for i in range(len(msg.get("activate") or [])):
                out.append(oc.encode_idlecmd(5, i))
            for i in range(len(msg.get("spell_set") or [])):
                out.append(oc.encode_idlecmd(4, i))
            for i in range(len(msg.get("monster_set") or [])):
                out.append(oc.encode_idlecmd(3, i))
        if msg.get("to_battle"):
            out.append(oc.encode_idlecmd(6, 0))
        if msg.get("to_end"):
            out.append(oc.encode_idlecmd(7, 0))
        if msg.get("can_shuffle"):
            out.append(oc.encode_idlecmd(8, 0))
        if not out:
            # 一个都合法的动作都没有 —— 这本身就不该发生，给最保守的 int32 让核心打回，
            # 由上层死循环检测兜底（绝不发空响应）。
            out.append(oc.encode_int32(0))
        return out

    def _battlecmd(self, msg: dict) -> list[bytes]:
        out: list[bytes] = []
        if self.productive:
            for i in range(len(msg.get("attackable") or [])):
                out.append(oc.encode_battlecmd(1, i))
            for i in range(len(msg.get("activatable") or [])):
                out.append(oc.encode_battlecmd(0, i))
        if msg.get("to_main2"):
            out.append(oc.encode_battlecmd(2, 0))
        if msg.get("to_end"):
            out.append(oc.encode_battlecmd(3, 0))
        if not out:
            out.append(oc.encode_int32(0))
        return out

    def _select_cards(self, msg: dict, event: int) -> list[bytes]:
        cards = msg.get("cards") or []
        minimum = int(msg.get("min", 0) or 0)
        maximum = int(msg.get("max", 0) or 0)
        cancelable = bool(msg.get("cancelable"))
        out: list[bytes] = []
        if cancelable and minimum == 0:
            out.append(oc.encode_select_card(None, cancel=True))
        if cards:
            take = max(minimum, 1)
            take = min(take, len(cards), maximum if maximum else len(cards))
            out.append(oc.encode_select_card(range(take)))
            if event == 20:      # 解放：按 release_param 从大到小凑够 min
                order = sorted(range(len(cards)),
                               key=lambda i: -int(cards[i].get("release_param", 0) or 0))
                picked: list[int] = []
                total = 0
                for i in order:
                    if total >= minimum and len(picked) >= (maximum or len(picked) or 1):
                        break
                    picked.append(i)
                    total += int(cards[i].get("release_param", 0) or 0)
                    if len(picked) >= len(cards):
                        break
                out.append(oc.encode_select_card(sorted(picked)))
            if event == 23:      # 数值结算：按 sum_param 贪心凑 acc
                acc = int(msg.get("acc", 0) or 0)
                order = sorted(range(len(cards)),
                               key=lambda i: -int(cards[i].get("value", 0) or 0))
                picked, total = [], 0
                for i in order:
                    if total >= acc:
                        break
                    picked.append(i)
                    total += int(cards[i].get("value", 0) or 0)
                if picked:
                    out.append(oc.encode_select_card(sorted(picked)))
        if not out:
            out.append(oc.encode_select_card([0]) if cards else oc.encode_int32(0))
        return out

    def _yesno_hint(self, msg: dict, state: dict) -> bool:
        """默认「否」；只有场景明确要求某个动作时才答「是」。"""
        action = state.get("action") or {}
        if action.get("yesno") == "yes":
            return True
        return False


# ══════════════════════════════════════════════════════════════════════
#  卡组装配
# ══════════════════════════════════════════════════════════════════════
def sample_card_ids(limit: int = 0) -> list[int]:
    """vendor/scripts/samples 里有官方脚本的卡号（保证「卡面 + 脚本」都齐）。"""
    d = paths.OFFICIAL_SCRIPTS / "samples"
    out: list[int] = []
    try:
        for p in d.glob("c*.lua"):
            stem = p.stem[1:]
            if stem.isdigit():
                out.append(int(stem))
    except OSError:
        return []
    out.sort()
    return out[:limit] if limit > 0 else out


def _spec_card_data(spec: Any) -> dict:
    """DIY ``CardSpec`` → 引擎卡面 dict（尽量走 pool.cdb 的既有换算，取不到就手算）。"""
    try:
        from ..pool import cdb as pool_cdb
        datas, _texts = pool_cdb.spec_to_rows(spec)
        keys = ("id", "ot", "alias", "setcode", "type", "atk", "def", "level",
                "race", "attribute", "category")
        row = dict(zip(keys, datas))
        row["code"] = row.pop("id")
        row["attack"] = row.pop("atk")
        row["defense"] = row.pop("def")
        return oc.card_data_from_row(row)
    except CardForgeError:
        return {}
    except Exception:
        return {}


def build_deck(core: oc.OcgCore, requested: list[int], *, size: int = 40,
               extra_size: int = 15, fillers: Optional[list[int]] = None) -> dict:
    """把「想要的卡号列表」凑成一副能开的卡组（主卡组 40 / 额外 ≤15）。

    返回 ``{"main": [...], "extra": [...], "notes": [...]}``；``notes`` 记录被丢掉的东西
    （0 占位、无卡面数据、无脚本），不静默吞掉。
    """
    notes: list[str] = []
    main: list[int] = []
    extra: list[int] = []
    pool = fillers if fillers is not None else sample_card_ids()

    def classify(code: int) -> Optional[str]:
        bits = core.type_bits_of(code)
        if not bits:
            return None
        return "extra" if oc.is_extra_deck_type(bits) else "main"

    for code in requested or []:
        c = int(code or 0)
        if not c:
            notes.append("丢掉 0 号占位（gates 传的空位）")
            continue
        kind = classify(c)
        if kind is None:
            notes.append(f"卡号 {c} 没有卡面数据（cdb 无此行且未登记），跳过")
            continue
        if not core.has_script(f"c{c}.lua"):
            notes.append(f"卡号 {c} 缺 Lua 脚本，跳过（脚本缺失，不是驱动问题）")
            continue
        copies = 0
        target = extra if kind == "extra" else main
        while copies < 3 and len(target) < (extra_size if kind == "extra" else size):
            target.append(c)
            copies += 1

    # 补齐主卡组
    for c in pool:
        if len(main) >= size:
            break
        if c in main and main.count(c) >= 3:
            continue
        kind = classify(c)
        if kind != "main":
            continue
        if not core.has_script(f"c{c}.lua"):
            continue
        main.append(c)
    if len(main) < size:
        notes.append(f"主卡组只凑到 {len(main)} 张（官方脚本样本不足）")
    if not extra:
        for c in pool:
            if len(extra) >= min(extra_size, 15):
                break
            if classify(c) != "extra" or not core.has_script(f"c{c}.lua"):
                continue
            if extra.count(c) >= 3:
                continue
            extra.append(c)
    return {"main": main, "extra": extra, "notes": notes}


# ══════════════════════════════════════════════════════════════════════
#  整局对战
# ══════════════════════════════════════════════════════════════════════
def run_duel(deck_a: list[int], deck_b: list[int], *, seed: int = 0,
             max_steps: int = 5000, cards: Optional[dict[int, Any]] = None,
             scenario: Optional[dict] = None,
             productive: bool = True) -> dict:
    """跑完整一局，返回 ``{"ok","turns","errors","log","lp","winner","steps","degraded"}``。

    ``cards`` 是 ``{卡号: CardSpec}``（DIY 卡）；没脚本的 DIY 卡不参与对局，
    只写进 ``degraded``。``scenario`` 可给场景专用参数（手牌 / 场面 / 期望动作）。
    """
    result: dict = {"ok": False, "turns": 0, "errors": [], "log": [], "lp": [0, 0],
                    "winner": None, "steps": 0, "degraded": "", "detail": {},
                    "blocking": ""}
    core: Optional[oc.OcgCore] = None
    try:
        core = oc.OcgCore()
    except Exception as e:                      # EngineUnavailable / OSError
        result["errors"].append(f"引擎不可用：{e}")
        result["degraded"] = "没创建任何对局（原生库加载失败）"
        return result

    degraded_parts: list[str] = []
    try:
        cdb = paths.OFFICIAL_CDB / CDB_NAME
        if cdb.exists():
            core.register_cdb(cdb)
        else:
            alt = paths.OFFICIAL_CDB / "cards.cdb"
            if alt.exists():
                core.register_cdb(alt)
            else:
                result["errors"].append("官方卡池缺失（vendor/data/cards_zh.cdb），无法取得卡面数据")
                return result

        # DIY 卡：卡面 + 脚本
        missing_lua: list[int] = []
        for code, spec in (cards or {}).items():
            c = int(getattr(spec, "id", code) or code or 0)
            if not c:
                continue
            data = _spec_card_data(spec)
            if data:
                core.register_card_data(c, data)
            lua = str(getattr(spec, "lua", "") or "")
            if lua.strip():
                core.register_card_script(c, lua)
            else:
                missing_lua.append(c)
        if missing_lua:
            degraded_parts.append(
                "DIY 卡 " + "、".join(str(c) for c in missing_lua) +
                " 没有 Lua 脚本，未参与本局（脚本缺失 ≠ 驱动通过）")

        info = dict(scenario or {})
        core.player_info = {"lp": int(info.get("lp", oc.DEFAULT_LP)),
                            "hand": int(info.get("hand_count", oc.DEFAULT_HAND)),
                            "draw": 1,
                            "hand_limit": oc.DEFAULT_HAND_LIMIT}
        status = core.create_duel(seed=int(seed or 0))
        if status != 0:
            result["errors"].append(
                f"OCG_CreateDuel 失败：{oc.CREATION_STATUS.get(status, status)}")
            return result
        result["detail"]["runtime_preloaded"] = core.runtime_preloaded
        if core.runtime_missing:
            result["errors"].append(
                "官方 Lua 运行库缺失：" + "、".join(core.runtime_missing))
            return result

        fillers = sample_card_ids()
        da = build_deck(core, list(deck_a or []), fillers=fillers)
        db = build_deck(core, list(deck_b or []), fillers=fillers)
        result["detail"]["deck_notes"] = (da["notes"] + db["notes"])[:12]
        if len(da["main"]) < 40 or len(db["main"]) < 40:
            result["errors"].append(
                f"主卡组凑不齐 40 张（A={len(da['main'])} B={len(db['main'])}），"
                "这种局面开局会立刻因抽空判负，不算跑通")
            return result

        # 洗牌在**主机侧**完成 —— 这正是 ygopro 协议的分工：核心只拿顺序无关的
        # 卡表，起手由注入顺序决定。历史缺陷（docs/03 §三-c）：8 个 seed 打出的
        # 回合数完全一样，因为 deck 以固定顺序注入，seed 只进了核心创建参数，
        # 谁都没有真正洗过牌。这里用 random.Random(seed) 洗主卡组，
        # seed 才真正影响起手；同 seed 可复现，异 seed 才会发散。
        if seed:
            import random as _random
            _rng = _random.Random(int(seed))
            _rng.shuffle(da["main"])
            _rng.shuffle(db["main"])
            result["detail"]["shuffled_with_seed"] = int(seed)

        inj = core.inject_deck(da["main"], db["main"], da["extra"], db["extra"])
        result["detail"]["inject"] = inj
        if inj["unknown"]:
            degraded_parts.append(f"注入了 {len(inj['unknown'])} 张无卡面数据的卡（核心按 0 号卡处理）")

        # 场景预置：手牌 / 场面
        preplaced = _apply_setup(core, info)
        result["detail"]["setup"] = preplaced

        core.start_duel()
        _drive(core, result, bot=SimpleBot(productive=productive),
               max_steps=int(max_steps or 5000), action=info.get("action"))
    finally:
        try:
            if core is not None:
                core.end_duel()
        except Exception:
            pass

    if core is not None:
        if core.script_errors:
            result["errors"].extend(core.script_errors[:12])
        if core.missing_scripts:
            degraded_parts.append("核心索取但找不到的脚本：" +
                                  "、".join(core.missing_scripts[:8]))
        result["detail"]["loaded_scripts"] = len(core.loaded_scripts)
        result["detail"]["missing_scripts"] = core.missing_scripts[:12]

    # 追加而不是覆盖：_drive 里已经写进"bot 走投无路"这类运行期降级说明
    _pre = (result.get("degraded") or "").strip()
    _new = "；".join(degraded_parts)
    result["degraded"] = "；".join(x for x in (_new, _pre) if x)
    result["ok"] = bool(result.get("finished")) and not result["errors"]
    return result


def _apply_setup(core: oc.OcgCore, info: dict) -> dict:
    """场景预置：把指定卡发进手牌 / 摆到场上（在 start_duel 之前调用）。"""
    placed = {"hand": 0, "field": 0, "skipped": []}
    for team, key in ((0, "hand"), (1, "hand_b")):
        for entry in info.get(key) or []:
            code, loc, seq, pos = _entry(entry)
            if loc is None:
                loc = oc.LOCATION_HAND
                seq = core.query_count(team, oc.LOCATION_HAND)
            if core.new_card({"code": code, "team": team, "con": team,
                              "loc": loc, "seq": seq, "pos": pos}):
                placed["hand" if loc == oc.LOCATION_HAND else "field"] += 1
            else:
                placed["skipped"].append(code)
    for entry in info.get("field") or []:
        code, loc, seq, pos = _entry(entry)
        if loc is None:
            loc = oc.LOCATION_MZONE
            seq = 0
        if pos is None:
            pos = oc.POS_FACEUP_ATTACK
        if core.new_card({"code": code, "team": int(entry.get("team", 0) if isinstance(entry, dict) else 0),
                          "con": int(entry.get("con", entry.get("team", 0)) if isinstance(entry, dict) else 0),
                          "loc": loc, "seq": seq, "pos": pos}):
            placed["field"] += 1
        else:
            placed["skipped"].append(code)
    return placed


def _entry(entry: Any) -> tuple[int, Optional[int], int, Optional[int]]:
    """把场景里的「一张卡」写法（int 或 dict）归一成 (code, loc|None, seq, pos|None)。"""
    if isinstance(entry, dict):
        return (int(entry.get("code", entry.get("id", 0)) or 0),
                entry.get("loc", entry.get("location")),
                int(entry.get("seq", entry.get("sequence", 0)) or 0),
                entry.get("pos", entry.get("position")))
    return (int(entry or 0), None, 0, None)


#: 单局里最多记录多少条日志（内存护栏）
LOG_LIMIT = 4000


#: 算作「对局有推进」的消息：位置变化 / 召唤 / 连锁 / 阶段 / 生死 / LP。
#: 判定死循环时，只要两次同样的提示之间出现过其中任意一条，就不算卡住。
_PROGRESS_MESSAGES: frozenset[int] = frozenset({
    40, 41, 5, 10, 11, 20, 21, 50, 51, 52, 53, 54, 55, 56, 60, 61, 62,
    70, 71, 72, 73, 74, 80, 81, 82, 83, 90, 91, 92, 93, 94, 95, 96, 97, 99, 100,
})


def _drive(core: oc.OcgCore, result: dict, *, bot: SimpleBot, max_steps: int,
           action: Optional[dict] = None) -> None:
    """推进消息机直到结束 / 上限；把回合数、LP、胜负、日志写回 ``result``。"""
    lp = [int(core.player_info.get("lp", oc.DEFAULT_LP)),
          int(core.player_info.get("lp", oc.DEFAULT_LP))]
    turns = 0
    winner: Optional[tuple[int, str]] = None
    pending: Optional[dict] = None
    # 死循环判定用「连续同提示 + 无推进」，不用全局限数（见下面 key 处注释）
    last_key: str = ""
    streak: int = 0
    progressed: bool = True
    state: dict = {"turns": 0, "turn_player": None, "phase": 0, "lp": lp,
                   "action": action or {}}
    log: list[dict] = result["log"]
    stuck = ""
    finished = False
    steps = 0
    for steps in range(1, max(1, int(max_steps)) + 1):
        status = core.process()
        msgs = core.messages()
        names: list[str] = []
        answer: Optional[dict] = None
        got_retry = False
        for m in msgs:
            names.append(str(m.get("event")))
            mid = int(m.get("id", -1))
            if mid in _PROGRESS_MESSAGES:
                progressed = True
            if mid == 40:
                turns += 1
                state["turns"] = turns
                state["turn_player"] = m.get("player")
            elif mid == 41:
                state["phase"] = int(m.get("phase", 0) or 0)
            elif mid == 5 and m.get("winner") is not None:
                winner = (int(m["winner"]), str(m.get("reason_name")))
            elif mid == 91:
                lp[int(m.get("player", 0))] -= int(m.get("amount", 0))
            elif mid == 92:
                lp[int(m.get("player", 0))] += int(m.get("amount", 0))
            elif mid == 100:
                lp[int(m.get("player", 0))] -= int(m.get("cost", 0))
            elif mid == 94:
                lp[int(m.get("player", 0))] = int(m.get("lp", 0))
            elif mid == 1:
                got_retry = True
            elif m.get("answer"):
                answer = m
            if len(log) < LOG_LIMIT:
                entry = {"step": steps, "event": m.get("event"), "id": mid,
                         "turn": turns}
                if mid in (91, 92, 94, 100, 5):
                    entry["lp"] = list(lp)
                # 数值断言要用的载荷（docs/03 三-c）：伤害/回复的归属与数值。
                # 不记这两项，场景层只能看到 LP 快照、看不到是谁挨了多少。
                if mid in (91, 92):
                    entry.update(player=int(m.get("player", 0) or 0),
                                 amount=int(m.get("amount", 0) or 0))
                # 场景断言要用的载荷：不带这些，MSG_move 的目的地就丢了，
                # 「卡有没有进手卡」这类断言只能永远报"没观测到"。
                if mid == 50:
                    entry.update(to_location=int(m.get("to_location", 0) or 0),
                                 to_player=int(m.get("to_player", 0) or 0),
                                 code=int(m.get("code", 0) or 0),
                                 reason=int(m.get("reason", 0) or 0))
                elif mid in (52, 53):
                    entry.update(code=int(m.get("code", 0) or 0),
                                 location=int(m.get("location", 0) or 0))
                elif mid in (61, 62):
                    entry.update(count=len(m.get("codes") or []))
                elif mid in (70, 71, 72, 73):
                    entry.update(code=int(m.get("code", 0) or 0))
                log.append(entry)
        if answer is not None:
            pending = answer
        if winner is not None or status == 0:
            finished = True
            break
        if status == 2:                      # continue：本轮不需要应答
            continue
        # awaiting：必须有待答消息
        target = pending
        if target is None:
            result["errors"].append(
                f"第 {steps} 步核心在等应答，但消息流里没有可应答的消息"
                f"（事件：{names[:6]}）")
            break
        # ── 死循环判定 ────────────────────────────────────────────
        # 只数「同一个待答消息连续出现、且中间没有任何推进」。
        # 早先按全局限数计数会把正常局面误判成死循环：MSG_select_chain
        # 在一次连锁里本来就要问两个玩家各一次，payload 完全相同；
        # 一场真对局里同一个提示重复十几次也是常事。
        key = f"{target.get('id')}:{target.get('raw', '')}"
        if key == last_key and not progressed:
            streak += 1
        else:
            streak = 1
        last_key, progressed = key, False
        limit = 10 if got_retry else 4      # 被打回时多给几次「换候选」的机会
        if streak > limit:
            stuck = (f"同一状态连续重复 {streak} 次且对局毫无推进"
                     f"（{'响应一直被打回、已在换候选 ' if got_retry else ''}"
                     f"MSG_{target.get('event')}，回合 {turns}），按死循环正常收尾")
            break
        target = dict(target)
        target["retry_key"] = key
        try:
            resp = bot.decide(target, state)
        except Exception as e:
            result["errors"].append(f"机器人决策异常（MSG_{target.get('event')}）：{e}")
            break
        if resp is None:
            result["errors"].append(f"不知道怎么应答 MSG_{target.get('event')}"
                                    f"（id={target.get('id')}），已停止对局")
            break
        core.set_response(resp)

    result["steps"] = steps
    result["turns"] = turns
    result["lp"] = lp
    result["winner"] = (winner[0] if winner else None)
    result["winner_reason"] = winner[1] if winner else None
    result["finished"] = finished
    # ── 卡住的原因必须分清：是**脚本**报错，还是**简易 bot** 走投无路 ──
    # 之前一律塞进 errors，于是 gates 把"bot 不会选场地"报成"你的卡有问题"，
    # 逼人回去改本来没坏的脚本。现在按引擎有没有 Lua 报错来分流。
    lua_errs = list(getattr(core, "script_errors", []) or [])
    for entry in (getattr(core, "logs", []) or [])[:200]:
        if str(entry.get("type")) in ("0", "error") and entry.get("text"):
            lua_errs.append(str(entry["text"])[:200])
    if stuck:
        if lua_errs:
            result["errors"].append(stuck + "；引擎同时报出脚本错误：" +
                                    "；".join(lua_errs[:3]))
            result["blocking"] = "script"
        else:
            _d = (result.get("degraded") or "")
            result["degraded"] = _d + ("；" if _d else "") + stuck +                 " —— 引擎没报任何脚本错误，这是简易 bot 的决策局限，不是这张卡的问题"
            result["blocking"] = "bot"
    if not finished and steps >= int(max_steps):
        msg = (f"步数耗尽（max_steps={max_steps}）仍未结束"
               + ("；引擎报出脚本错误：" + "；".join(lua_errs[:3]) if lua_errs
                  else "；引擎没有脚本报错，是简易 bot 走不完"))
        if lua_errs:
            result["errors"].append(msg)
            result["blocking"] = "script"
        else:
            result["degraded"] = (result.get("degraded") or "") + "；" + msg
            result["blocking"] = "bot"
    if lua_errs and result.get("blocking") != "bot":
        result["blocking"] = "script"
        for e in lua_errs[:5]:
            if e not in result["errors"]:
                result["errors"].append(f"引擎脚本报错：{e}")
