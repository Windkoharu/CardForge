"""ocgcore 原生库的 ctypes 驱动 —— 以 DLL 的**真实导出**为准。

真实 ABI 结论（实测，非推测）
------------------------------
``vendor/engine/ocgcore.dll``（204,194,207 字节，PE32+ x64，MinGW/UCRT64 GCC 16.2.0 构建，
带 DWARF 调试信息所以体积巨大）只导出 **13 个** ``OCG_*`` 符号：

    OCG_CreateDuel  OCG_DestroyDuel  OCG_DuelGetMessage  OCG_DuelNewCard
    OCG_DuelProcess OCG_DuelQuery    OCG_DuelQueryCount  OCG_DuelQueryField
    OCG_DuelQueryLocation OCG_DuelSetResponse OCG_GetVersion OCG_LoadScript
    OCG_StartDuel

它是 **edo9300/ygopro-core（OCG API 11.0）** 的句柄式 API，与旧 EDOPro/YGOPro 的
全局 ``pduel`` 风格完全不同：

* ``OCG_CreateDuel(OCG_Duel* out, const OCG_DuelOptions*) -> int``（0 = 成功）
* 其余全部函数第一个参数是 ``OCG_Duel`` 句柄（``void*``）
* ``OCG_GetVersion(int* major, int* minor)`` —— **两个 int 出参**。
  ⚠ 把它当 ``c_char_p`` / ``c_uint`` 版 getter 调用会 0xC0000005（历史上踩过）。
* **没有** ``OCG_DuelSetPlayerInfo`` / ``OCG_CardLoadCDB`` / ``OCG_AddString``：
  卡组与玩家信息通过 ``OCG_DuelOptions`` + ``OCG_DuelNewCard(OCG_NewCardInfo*)`` 注入；
  卡面数据通过 ``OCG_DataReader`` **回调**向核心索取（所以我们不需要 sqlite3* 句柄）；
  Lua 脚本通过 ``OCG_ScriptReader`` 回调 + ``OCG_LoadScript`` 注入。
* ``OCG_DuelProcess`` 返回 ``0=END / 1=AWAITING / 2=CONTINUE``。
* ``OCG_DuelGetMessage(OCG_Duel, uint32_t* len) -> void*`` 返回**字节缓冲**（不是 uint32 流），
  帧格式 ``[uint32 payload_len][uint8 event_id][payload...]``；
  payload 内部是**紧凑混合宽度**（uint8/uint16/uint32/uint64 按写入顺序排列，无对齐填充）。
* ``OCG_DuelSetResponse(OCG_Duel, const void* buf, uint32_t len)``；核心按
  ``returns.at<T>(i)`` 读取 —— 即**按 T 的宽度做元素索引**，所以响应是「int32 头 + 变宽数组」。

消息与响应的字段布局全部对照本 build 的 ``playerop.cpp`` / ``operations.cpp`` /
``processor.cpp`` / ``field.cpp`` 写入端逐条核对；解析器对**已知布局做严格长度校验**，
未知/不符的消息只保留原始字节并在 ``decode_error`` 里标注，绝不猜。

降级约定
--------
取不到的东西一律留空并写清原因（见 ``OcgCore.library_info``），
库不可用时抛 ``core.errors.EngineUnavailable``。
"""
from __future__ import annotations

import ctypes
import os
import sqlite3
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..core import paths
from ..core.errors import EngineUnavailable

# ══════════════════════════════════════════════════════════════════════
#  常量：核心导出 / 状态码
# ══════════════════════════════════════════════════════════════════════
#: 本 build 期望存在的入口（缺失即视为「不是可用的 ocgcore」）
REQUIRED_SYMBOLS: tuple[str, ...] = (
    "OCG_CreateDuel", "OCG_DestroyDuel", "OCG_StartDuel", "OCG_DuelProcess",
    "OCG_DuelGetMessage", "OCG_DuelSetResponse", "OCG_LoadScript", "OCG_DuelNewCard",
    "OCG_GetVersion",
)
#: 老 EDOPro / YGOPro 常见、但本 build **确实没有**的符号（供 library_info 报告）
ABSENT_SYMBOLS: tuple[str, ...] = (
    "OCG_DuelSetPlayerInfo", "OCG_SetPlayerInfo", "OCG_CardLoadCDB", "OCG_CardLoad",
    "OCG_CardUnload", "OCG_AddString", "OCG_GetStringCount", "OCG_GetStringByKey",
    "OCG_CreateScriptBox", "OCG_LoadLocalScript", "OCG_RenameScript", "OCG_ClearScripts",
    "OCG_SetLogFunction", "OCG_SetProcessorFlag", "OCG_DuelResult",
    "OCG_DuelPendingResponse", "OCG_DuelSetAI", "OCG_DuelChangeField", "OCG_Draw",
    "OCG_GetVersionMajor", "OCG_GetVersionMinor", "OCG_GetVersionExtra",
)
#: ``OCG_DuelCreationStatus``
CREATION_STATUS = {
    0: "OCG_DUEL_CREATION_SUCCESS",
    1: "OCG_DUEL_CREATION_NO_OUTPUT",
    2: "OCG_DUEL_CREATION_NOT_CREATED",
    3: "OCG_DUEL_CREATION_NULL_DATA_READER",
    4: "OCG_DUEL_CREATION_NULL_SCRIPT_READER",
    5: "OCG_DUEL_CREATION_INCOMPATIBLE_LUA_API",
    6: "OCG_DUEL_CREATION_NULL_RNG_SEED",
}
#: ``OCG_DuelStatus``
DUEL_STATUS = {0: "end", 1: "awaiting", 2: "continue"}
#: ``OCG_LogTypes``
LOG_TYPES = {0: "error", 1: "from_script", 2: "for_debug"}

# 位置 / 姿态（与 ocgapi_constants.h、vendor/scripts/constant.lua 双向核对过）
LOCATION_DECK, LOCATION_HAND, LOCATION_MZONE, LOCATION_SZONE = 0x01, 0x02, 0x04, 0x08
LOCATION_GRAVE, LOCATION_REMOVED, LOCATION_EXTRA, LOCATION_OVERLAY = 0x10, 0x20, 0x40, 0x80
POS_FACEUP_ATTACK, POS_FACEDOWN_ATTACK = 0x1, 0x2
POS_FACEUP_DEFENSE, POS_FACEDOWN_DEFENSE = 0x4, 0x8

TYPE_MONSTER, TYPE_SPELL, TYPE_TRAP = 0x1, 0x2, 0x4
TYPE_EXTRA_MASK = 0x40 | 0x80 | 0x2000 | 0x800000 | 0x4000000  # fusion/ritual/synchro/xyz/link

#: ``QUERY_*``（照 ocgapi_constants.h「Card Queries」逐项核对；本工程只用到其中几个）
QUERY_CODE = 0x1
QUERY_POSITION = 0x2
QUERY_ALIAS = 0x4
QUERY_TYPE = 0x8
QUERY_LEVEL = 0x10
QUERY_RANK = 0x20
QUERY_ATTRIBUTE = 0x40
QUERY_RACE = 0x80
QUERY_ATTACK = 0x100
QUERY_DEFENSE = 0x200
QUERY_BASE_ATTACK = 0x400
QUERY_BASE_DEFENSE = 0x800
QUERY_REASON = 0x1000
QUERY_COUNTERS = 0x20000
QUERY_OWNER = 0x40000
QUERY_STATUS = 0x80000
QUERY_LSCALE = 0x200000
QUERY_RSCALE = 0x400000
QUERY_LINK = 0x800000
#: 单卡查询里会出现的字段名（顺序即核心写入顺序，用于把查询字节解成 dict）
QUERY_FIELD_ORDER: tuple[tuple[int, str, str], ...] = (
    (QUERY_CODE, "code", "u32"), (QUERY_POSITION, "position", "u32"),
    (QUERY_ALIAS, "alias", "u32"), (QUERY_TYPE, "type", "u32"),
    (QUERY_LEVEL, "level", "u32"), (QUERY_RANK, "rank", "u32"),
    (QUERY_ATTRIBUTE, "attribute", "u32"), (QUERY_RACE, "race", "u64"),
    (QUERY_ATTACK, "attack", "u32"), (QUERY_DEFENSE, "defense", "u32"),
    (QUERY_BASE_ATTACK, "base_attack", "u32"),
    (QUERY_BASE_DEFENSE, "base_defense", "u32"), (QUERY_REASON, "reason", "u32"),
)

#: 默认选手信息：LP 8000 / 起手 5 / 每回合抽 1。
#: 手牌上限 6 在核心里是固定规则（``DUEL_NO_HAND_LIMIT`` 才能取消），不是可传字段，
#: 所以 ``player_info()`` 只把它记录在返回值里，供上层展示与断言。
#: 核心会例行索取、但**允许不存在**的脚本：给空串，不记进 missing_scripts。
#: c0 = 卡号 0（空位）；proc_unofficial 只在非官方规则 duel 里才需要。
_EMPTY_OK_SCRIPTS: frozenset[str] = frozenset({"c0", "c0.lua", "proc_unofficial",
                                              "proc_unofficial.lua"})

DEFAULT_LP = 8000
DEFAULT_HAND = 5
DEFAULT_HAND_LIMIT = 6
#: 与 vendor/scripts/constant.lua 的 ``DUEL_MODE_MR5`` 同值（已逐位核对）
DUEL_FLAGS_MR5_DEFAULT = 0x2E800

# ══════════════════════════════════════════════════════════════════════
#  消息号 ↔ 名字（对照 ocgapi_constants.h 的 MSG_*）
# ══════════════════════════════════════════════════════════════════════
MSG_NAMES: dict[int, str] = {
    1: "retry", 2: "hint", 3: "waiting", 4: "start", 5: "win", 6: "update_data",
    7: "update_card", 8: "request_deck",
    10: "select_battlecmd", 11: "select_idlecmd", 12: "select_effectyn", 13: "select_yesno",
    14: "select_option", 15: "select_card", 16: "select_chain", 18: "select_place",
    19: "select_position", 20: "select_tribute", 21: "sort_chain", 22: "select_counter",
    23: "select_sum", 24: "select_disfield", 25: "sort_card", 26: "select_unselect_card",
    30: "confirm_decktop", 31: "confirm_cards", 32: "shuffle_deck", 33: "shuffle_hand",
    34: "refresh_deck", 35: "swap_grave_deck", 36: "shuffle_set_card", 37: "reverse_deck",
    38: "deck_top", 39: "shuffle_extra", 40: "new_turn", 41: "new_phase",
    42: "confirm_extratop",
    50: "move", 53: "pos_change", 54: "set", 55: "swap", 56: "field_disabled",
    60: "summoning", 61: "summoned", 62: "spsummoning", 63: "spsummoned",
    64: "flipsummoning", 65: "flipsummoned",
    70: "chaining", 71: "chained", 72: "chain_solving", 73: "chain_solved", 74: "chain_end",
    75: "chain_negated", 76: "chain_disabled",
    80: "card_selected", 81: "random_selected", 83: "become_target",
    90: "draw", 91: "damage", 92: "recover", 93: "equip", 94: "lpupdate", 95: "unequip",
    96: "card_target", 97: "cancel_target",
    100: "pay_lpcost", 101: "add_counter", 102: "remove_counter",
    110: "attack", 111: "battle", 112: "attack_disabled",
    113: "damage_step_start", 114: "damage_step_end",
    120: "missed_effect", 121: "be_chain_target", 122: "create_relation",
    123: "release_relation",
    130: "toss_coin", 131: "toss_dice", 132: "rock_paper_scissors", 133: "hand_res",
    140: "announce_race", 141: "announce_attribute", 142: "announce_card",
    143: "announce_number",
    160: "card_hint", 161: "tag_swap", 162: "reload_field", 163: "ai_name",
    164: "show_hint", 165: "player_hint", 170: "match_kill", 180: "custom_msg",
    190: "remove_cards",
}
#: 需要玩家应答的消息号（``ANSWER_*`` 语义：核心在这些消息后挂起等响应）
ANSWER_MESSAGES: frozenset[int] = frozenset(
    {10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25, 26,
     132, 140, 141, 142, 143})
#: 胜因（``MSG_WIN`` 第二字节）
WIN_REASONS = {1: "lp_zero", 2: "deck_out", 3: "forfeit", 4: "other", 5: "draw"}
PHASE_NAMES = {
    0x1: "draw", 0x2: "standby", 0x4: "main1", 0x8: "battle_start", 0x10: "battle_step",
    0x20: "damage", 0x40: "damage_cal", 0x80: "battle", 0x100: "main2", 0x200: "end",
}


# ══════════════════════════════════════════════════════════════════════
#  ctypes 结构体（严格照 ocgapi_types.h 的自然对齐；已实测字段偏移）
# ══════════════════════════════════════════════════════════════════════
class CCardData(ctypes.Structure):
    """``OCG_CardData``。"""
    _fields_ = [
        ("code", ctypes.c_uint32), ("alias", ctypes.c_uint32),
        ("setcodes", ctypes.POINTER(ctypes.c_uint16)),
        ("type", ctypes.c_uint32), ("level", ctypes.c_uint32),
        ("attribute", ctypes.c_uint32), ("race", ctypes.c_uint64),
        ("attack", ctypes.c_int32), ("defense", ctypes.c_int32),
        ("lscale", ctypes.c_uint32), ("rscale", ctypes.c_uint32),
        ("link_marker", ctypes.c_uint32),
    ]


class CPlayer(ctypes.Structure):
    """``OCG_Player``：startingLP / startingDrawCount / drawCountPerTurn。"""
    _fields_ = [("startingLP", ctypes.c_uint32),
                ("startingDrawCount", ctypes.c_uint32),
                ("drawCountPerTurn", ctypes.c_uint32)]


class CNewCard(ctypes.Structure):
    """``OCG_NewCardInfo``：team/duelist/code/con/loc/seq/pos。"""
    _fields_ = [("team", ctypes.c_uint8), ("duelist", ctypes.c_uint8),
               ("code", ctypes.c_uint32), ("con", ctypes.c_uint8),
               ("loc", ctypes.c_uint32), ("seq", ctypes.c_uint32),
               ("pos", ctypes.c_uint32)]


class CQueryInfo(ctypes.Structure):
    """``OCG_QueryInfo``：flags/con/loc/seq/overlay_seq。"""
    _fields_ = [("flags", ctypes.c_uint32), ("con", ctypes.c_uint8),
               ("loc", ctypes.c_uint32), ("seq", ctypes.c_uint32),
               ("overlay_seq", ctypes.c_uint32)]


_C_DATAREADER = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32,
                                 ctypes.POINTER(CCardData))
_C_DATAREADER_DONE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(CCardData))
_C_SCRIPTREADER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_char_p)
_C_LOGHANDLER = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int)


class CDuelOptions(ctypes.Structure):
    """``OCG_DuelOptions``（11.0 版字段顺序，末尾 enableUnsafeLibraries）。"""
    _fields_ = [
        ("seed", ctypes.c_uint64 * 4), ("flags", ctypes.c_uint64),
        ("team1", CPlayer), ("team2", CPlayer),
        ("cardReader", _C_DATAREADER), ("payload1", ctypes.c_void_p),
        ("scriptReader", _C_SCRIPTREADER), ("payload2", ctypes.c_void_p),
        ("logHandler", _C_LOGHANDLER), ("payload3", ctypes.c_void_p),
        ("cardReaderDone", _C_DATAREADER_DONE), ("payload4", ctypes.c_void_p),
        ("enableUnsafeLibraries", ctypes.c_uint8),
    ]


# ══════════════════════════════════════════════════════════════════════
#  字节读取原语
# ══════════════════════════════════════════════════════════════════════
class _Reader:
    """紧凑混合宽度读取器；越界抛 ValueError 让上层降级而不是崩。"""

    __slots__ = ("buf", "off")

    def __init__(self, buf: bytes, off: int = 0) -> None:
        self.buf = buf
        self.off = off

    def _take(self, fmt: str, size: int) -> int:
        if self.off + size > len(self.buf):
            raise ValueError(f"payload 越界：需要 {size} 字节@{self.off}，只有 {len(self.buf)}")
        val = struct.unpack_from(fmt, self.buf, self.off)[0]
        self.off += size
        return int(val)

    def u8(self) -> int:
        return self._take("<B", 1)

    def u16(self) -> int:
        return self._take("<H", 2)

    def u32(self) -> int:
        return self._take("<I", 4)

    def u64(self) -> int:
        return self._take("<Q", 8)

    def loc(self) -> dict:
        """``loc_info`` 上线格式：controler u8 + location u8 + sequence u32 + position u32。"""
        return {"player": self.u8(), "location": self.u8(),
                "sequence": self.u32(), "position": self.u32()}

    def card(self) -> dict:
        """``code u32 + loc_info``（核心里绝大多数卡条目的写法）。"""
        code = self.u32()
        out = self.loc()
        out["code"] = code
        return out

    def rest_ints(self) -> list[int]:
        """把剩余字节按 uint32 读（尾部不足 4 字节的按 uint8 收集），用于 ``all``。"""
        out: list[int] = []
        while self.off + 4 <= len(self.buf):
            out.append(self.u32())
        while self.off < len(self.buf):
            out.append(self.u8())
        return out

    def done(self) -> bool:
        return self.off >= len(self.buf)


# ══════════════════════════════════════════════════════════════════════
#  二进制消息解析器
# ══════════════════════════════════════════════════════════════════════
def _p_empty(r: _Reader) -> dict:
    return {}


def _p_hint(r: _Reader) -> dict:
    """``MSG_HINT``：htype u8 + player u8 + 一个或多个 u64。"""
    htype = r.u8()
    player = r.u8()
    descs = []
    while len(r.buf) - r.off >= 8:
        descs.append(r.u64())
    return {"hint_type": htype, "player": player,
            "desc": descs[0] if descs else 0, "descs": descs}


def _p_win(r: _Reader) -> dict:
    winner = r.u8()
    reason = r.u8()
    return {"winner": winner if winner < 2 else None, "player": winner,
            "reason": reason, "reason_name": WIN_REASONS.get(reason, "unknown")}


def _idle_group(r: _Reader, seq_width: int = 4) -> list[dict]:
    out = []
    for _ in range(r.u32()):
        code = r.u32()
        con, loc = r.u8(), r.u8()
        seq = r.u8() if seq_width == 1 else r.u32()
        out.append({"code": code, "player": con, "location": loc, "sequence": seq})
    return out


def _make_idlecmd(repos_u8: bool) -> Callable[[_Reader], dict]:
    """生成一种 ``MSG_SELECT_IDLECMD`` 布局变体。

    ⚠ 变体存在的唯一原因：**实测这个 build 的写入端与源码树不一致** ——
    表示「表示变更」的 repos 条目里 ``sequence`` 实际是 1 字节（用 4 字节解析会
    多读 3 字节导致后续全部错位）。所以解析时按变体轮试，第一个**刚好消费完**
    载荷的算命中，并在 ``layout`` 字段里记录命中了哪一套。
    """
    def parse(r: _Reader) -> dict:
        player = r.u8()
        summon = _idle_group(r)
        spsummon = _idle_group(r)
        repos = _idle_group(r, 1 if repos_u8 else 4)
        mset = _idle_group(r)
        sset = _idle_group(r)
        activate = []
        for _ in range(r.u32()):
            code = r.u32()
            con, loc = r.u8(), r.u8()
            seq = r.u32()
            desc, mode = r.u64(), r.u8()
            activate.append({"code": code, "player": con, "location": loc,
                             "sequence": seq, "desc": desc, "mode": mode})
        return {"player": player, "summon": summon, "spsummon": spsummon, "repos": repos,
                "monster_set": mset, "spell_set": sset, "activate": activate,
                "to_battle": bool(r.u8()), "to_end": bool(r.u8()),
                "can_shuffle": bool(r.u8())}
    return parse


def _make_battlecmd(seq_u8: bool) -> Callable[[_Reader], dict]:
    """生成一种 ``MSG_SELECT_BATTLECMD`` 布局变体（``sequence`` 1 或 4 字节）。"""
    def parse(r: _Reader) -> dict:
        player = r.u8()
        activatable = []
        for _ in range(r.u32()):
            code = r.u32()
            con, loc = r.u8(), r.u8()
            seq = r.u32()
            desc, mode = r.u64(), r.u8()
            activatable.append({"code": code, "player": con, "location": loc,
                                "sequence": seq, "desc": desc, "mode": mode})
        attackable = []
        for _ in range(r.u32()):
            code = r.u32()
            con, loc = r.u8(), r.u8()
            seq = r.u8() if seq_u8 else r.u32()
            direct = r.u8()
            attackable.append({"code": code, "player": con, "location": loc,
                               "sequence": seq, "direct": bool(direct)})
        return {"player": player, "activatable": activatable, "attackable": attackable,
                "to_main2": bool(r.u8()), "to_end": bool(r.u8())}
    return parse


def _p_select_effectyn(r: _Reader) -> dict:
    """``MSG_SELECT_EFFECTYN``：player u8 + code u32 + loc_info + desc u64。"""
    player = r.u8()
    card = r.card()
    return {"player": player, "card": card, "desc": r.u64()}


def _p_select_yesno(r: _Reader) -> dict:
    return {"player": r.u8(), "desc": r.u64()}


def _p_select_option(r: _Reader) -> dict:
    player = r.u8()
    count = r.u8()
    return {"player": player, "options": [r.u64() for _ in range(count)]}


def _p_select_card(r: _Reader) -> dict:
    player = r.u8()
    cancelable = r.u8()
    minimum, maximum, count = r.u32(), r.u32(), r.u32()
    cards = [r.card() for _ in range(count)]
    return {"player": player, "cancelable": bool(cancelable), "min": minimum,
            "max": maximum, "cards": cards}


def _p_select_tribute(r: _Reader) -> dict:
    """``MSG_SELECT_TRIBUTE``：条目是 code u32 + con u8 + loc u8 + seq u32 + release_param u8
    （**不是** loc_info，没有 position 字段）。"""
    player = r.u8()
    cancelable = r.u8()
    minimum, maximum, count = r.u32(), r.u32(), r.u32()
    cards = []
    for _ in range(count):
        code = r.u32()
        con, loc = r.u8(), r.u8()
        seq = r.u32()
        cards.append({"code": code, "player": con, "location": loc,
                      "sequence": seq, "release_param": r.u8()})
    return {"player": player, "cancelable": bool(cancelable), "min": minimum,
            "max": maximum, "cards": cards}


def _p_select_chain(r: _Reader) -> dict:
    player = r.u8()
    spe_count = r.u8()
    forced = r.u8()
    hint_self, hint_opp = r.u32(), r.u32()
    count = r.u32()
    chains = []
    for _ in range(count):
        code = r.u32()
        con, loc = r.u8(), r.u8()
        seq, pos = r.u32(), r.u32()
        desc, mode = r.u64(), r.u8()
        chains.append({"code": code, "player": con, "location": loc, "sequence": seq,
                       "position": pos, "desc": desc, "mode": mode})
    return {"player": player, "spe_count": spe_count, "forced": bool(forced),
            "hint_timing_self": hint_self, "hint_timing_opponent": hint_opp,
            "chains": chains}


def _p_select_place(r: _Reader) -> dict:
    """``MSG_SELECT_PLACE`` / ``MSG_SELECT_DISFIELD``：player u8 + count u8 + flag u32。"""
    return {"player": r.u8(), "count": r.u8(), "flag": r.u32()}


def _p_select_position(r: _Reader) -> dict:
    return {"player": r.u8(), "code": r.u32(), "positions": r.u8()}


def _p_select_counter(r: _Reader) -> dict:
    player = r.u8()
    ctype, count, n = r.u16(), r.u16(), r.u32()
    cards = []
    for _ in range(n):
        code = r.u32()
        con, loc, seq = r.u8(), r.u8(), r.u8()
        cards.append({"code": code, "player": con, "location": loc,
                      "sequence": seq, "counter": r.u16()})
    return {"player": player, "countertype": ctype, "count": count, "cards": cards}


def _p_select_sum(r: _Reader) -> dict:
    player = r.u8()
    mode = r.u8()
    acc, minimum, maximum = r.u32(), r.u32(), r.u32()
    must = []
    for _ in range(r.u32()):
        entry = r.card()
        entry["value"] = r.u32()
        must.append(entry)
    options = []
    for _ in range(r.u32()):
        entry = r.card()
        entry["value"] = r.u32()
        options.append(entry)
    return {"player": player, "mode": mode, "acc": acc, "min": minimum, "max": maximum,
            "must_cards": must, "cards": options}


def _p_sort_card(r: _Reader) -> dict:
    """``MSG_SORT_CARD`` / ``MSG_SORT_CHAIN``：player u8 + count u32 + (code,con,loc,pos,seq)。"""
    player = r.u8()
    count = r.u32()
    cards = []
    for _ in range(count):
        code = r.u32()
        con = r.u8()
        loc = r.u32()
        seq = r.u32()
        cards.append({"code": code, "player": con, "location": loc, "sequence": seq})
    return {"player": player, "cards": cards}


def _p_select_unselect(r: _Reader) -> dict:
    player = r.u8()
    finishable, cancelable = r.u8(), r.u8()
    minimum, maximum = r.u32(), r.u32()
    select = [r.card() for _ in range(r.u32())]
    unselect = [r.card() for _ in range(r.u32())]
    return {"player": player, "finishable": bool(finishable), "cancelable": bool(cancelable),
            "min": minimum, "max": maximum, "cards": select, "uncards": unselect}


def _p_announce_card(r: _Reader) -> dict:
    """``MSG_ANNOUNCE_CARD`` / ``MSG_ANNOUNCE_NUMBER``：player u8 + count u8 + u64 选项表。"""
    player = r.u8()
    count = r.u8()
    return {"player": player, "count": count, "options": [r.u64() for _ in range(count)]}


def _p_announce_mask(r: _Reader) -> dict:
    """``MSG_ANNOUNCE_RACE``(available u64) / ``MSG_ANNOUNCE_ATTRIB``(available u32)。"""
    player = r.u8()
    count = r.u8()
    available = r.u64() if len(r.buf) - r.off >= 8 else r.u32()
    return {"player": player, "count": count, "available": available}


def _p_new_turn(r: _Reader) -> dict:
    return {"player": r.u8()}


def _p_new_phase(r: _Reader) -> dict:
    phase = r.u16()
    return {"phase": phase, "phase_name": PHASE_NAMES.get(phase, "unknown")}


def _p_move(r: _Reader) -> dict:
    card = r.card()
    dest = r.loc()
    return {"code": card["code"], "from_player": card["player"],
            "from_location": card["location"], "from_sequence": card["sequence"],
            "from_position": card["position"], "to_player": dest["player"],
            "to_location": dest["location"], "to_sequence": dest["sequence"],
            "to_position": dest["position"], "reason": r.u32()}


def _p_pos_change(r: _Reader) -> dict:
    return {"code": r.u32(), "player": r.u8(), "location": r.u8(), "sequence": r.u8(),
            "from_position": r.u8(), "to_position": r.u8()}


def _p_code_and_loc(r: _Reader) -> dict:
    return r.card()


def _p_chained(r: _Reader) -> dict:
    return {"chain_count": r.u8()}


def _p_chain_solving(r: _Reader) -> dict:
    return {"chain_count": r.u8()}


def _p_draw(r: _Reader) -> dict:
    player = r.u8()
    count = r.u32()
    cards = [{"code": r.u32(), "position": r.u32()} for _ in range(count)]
    return {"player": player, "count": count, "cards": cards}


def _p_confirm_cards(r: _Reader) -> dict:
    player = r.u8()
    count = r.u32()
    cards = []
    for _ in range(count):
        code = r.u32()
        con, loc = r.u8(), r.u8()
        seq = r.u32()
        cards.append({"code": code, "player": con, "location": loc, "sequence": seq})
    return {"player": player, "count": count, "cards": cards}


def _p_damage(r: _Reader) -> dict:
    player = r.u8()
    amount = r.u32()
    out = {"player": player, "amount": amount}
    if len(r.buf) - r.off >= 4:
        out["reason_card"] = r.u32()
    return out


def _p_recover(r: _Reader) -> dict:
    return {"player": r.u8(), "amount": r.u32()}


def _p_pay_lpcost(r: _Reader) -> dict:
    return {"player": r.u8(), "cost": r.u32()}


def _p_lpupdate(r: _Reader) -> dict:
    return {"player": r.u8(), "lp": r.u32()}


def _p_add_counter(r: _Reader) -> dict:
    return {"countertype": r.u16(), "player": r.u8(), "location": r.u8(),
            "sequence": r.u8(), "count": r.u16()}


def _p_attack(r: _Reader) -> dict:
    """``MSG_ATTACK``：attacker loc_info + target loc_info（无目标时是全零 loc_info）。"""
    attacker = r.loc()
    target = r.loc()
    out = {"attacker_player": attacker["player"], "attacker_location": attacker["location"],
           "attacker_sequence": attacker["sequence"], "attacker_position": attacker["position"]}
    out.update({f"target_{k}": v for k, v in target.items()})
    out["direct"] = not any(target.values())
    return out


def _p_battle(r: _Reader) -> dict:
    """``MSG_BATTLE``：attacker loc_info + aa u32 + ad u32 + bd0 u8
    + target loc_info + da u32 + dd u32 + bd1 u8。"""
    attacker = r.loc()
    aa, ad = r.u32(), r.u32()
    bd0 = r.u8()
    target = r.loc()
    da, dd = r.u32(), r.u32()
    bd1 = r.u8()
    out = {"attacker_player": attacker["player"], "attacker_location": attacker["location"],
           "attacker_sequence": attacker["sequence"], "attacker_position": attacker["position"],
           "attack_announce": aa, "attack_damage": ad, "destroyed_first": bd0,
           "destroyed_second": bd1}
    out.update({f"target_{k}": v for k, v in target.items()})
    out["defender_attack"] = da
    out["defender_damage"] = dd
    return out


def _p_chaining(r: _Reader) -> dict:
    handler = r.card()
    trg_player, trg_loc = r.u8(), r.u8()
    trg_seq = r.u32()
    desc = r.u64()
    chain_count = r.u32()
    return {"code": handler["code"], "handler_player": handler["player"],
            "handler_location": handler["location"], "handler_sequence": handler["sequence"],
            "handler_position": handler["position"], "triggering_player": trg_player,
            "triggering_location": trg_loc, "triggering_sequence": trg_seq,
            "desc": desc, "chain_count": chain_count}


def _p_become_target(r: _Reader) -> dict:
    count = r.u32()
    return {"count": count, "cards": [r.loc() for _ in range(count)]}


def _p_missed_effect(r: _Reader) -> dict:
    loc = r.loc()
    return {**{f"handler_{k}": v for k, v in loc.items()}, "code": r.u32()}


def _p_coin_or_dice(r: _Reader) -> dict:
    player = r.u8()
    count = r.u8()
    return {"player": player, "count": count, "results": [r.u8() for _ in range(count)]}


def _p_card_hint(r: _Reader) -> dict:
    """``MSG_CARD_HINT``：loc_info + hint u8 + value u64。"""
    loc = r.loc()
    out = {f"card_{k}": v for k, v in loc.items()}
    out["hint"] = r.u8()
    out["value"] = r.u64() if len(r.buf) - r.off >= 8 else 0
    return out


def _p_player_hint(r: _Reader) -> dict:
    """``MSG_PLAYER_HINT``：player u8 + hint u8 + desc u64。"""
    return {"player": r.u8(), "hint": r.u8(), "desc": r.u64()}


def _p_two_locs(r: _Reader) -> dict:
    """``MSG_EQUIP`` / ``MSG_CARD_TARGET`` / ``MSG_CANCEL_TARGET``：两个 loc_info。"""
    a, b = r.loc(), r.loc()
    return {"source": a, "target": b}


def _p_swap(r: _Reader) -> dict:
    """``MSG_SWAP``：code u32 + loc_info + code u32 + loc_info。"""
    first = r.card()
    second = r.card()
    return {"first": first, "second": second}


def _p_u32_only(r: _Reader) -> dict:
    return {"value": r.u32()}


def _p_u8_only(r: _Reader) -> dict:
    return {"player": r.u8()}


def _p_remove_cards(r: _Reader) -> dict:
    count = r.u32()
    return {"count": count, "cards": [r.loc() for _ in range(count)]}


#: 每个消息号对应**一组**候选布局（按顺序试，第一个刚好消费完载荷的算命中）。
#: 只有 10 / 11 需要多套：实测这个 build 的 ``sequence`` 宽度与源码树不一致。
_MESSAGE_PARSERS: dict[int, list[Callable[[_Reader], dict]]] = {
    2: [_p_hint], 5: [_p_win],
    10: [_make_battlecmd(True), _make_battlecmd(False)],
    11: [_make_idlecmd(True), _make_idlecmd(False)],
    12: [_p_select_effectyn], 13: [_p_select_yesno], 14: [_p_select_option],
    15: [_p_select_card], 16: [_p_select_chain], 18: [_p_select_place],
    19: [_p_select_position], 20: [_p_select_tribute], 21: [_p_sort_card],
    22: [_p_select_counter], 23: [_p_select_sum], 24: [_p_select_place],
    25: [_p_sort_card], 26: [_p_select_unselect],
    30: [_p_confirm_cards], 31: [_p_confirm_cards], 42: [_p_confirm_cards],
    40: [_p_new_turn], 41: [_p_new_phase],
    50: [_p_move], 53: [_p_pos_change], 54: [_p_code_and_loc], 55: [_p_swap],
    56: [_p_u32_only],
    60: [_p_code_and_loc], 62: [_p_code_and_loc], 64: [_p_code_and_loc],
    61: [_p_empty], 63: [_p_empty], 65: [_p_empty],
    70: [_p_chaining], 71: [_p_chained], 72: [_p_chain_solving],
    73: [_p_chain_solving], 75: [_p_chained], 76: [_p_chained], 74: [_p_empty],
    81: [_p_become_target], 83: [_p_become_target],
    90: [_p_draw], 91: [_p_damage], 92: [_p_recover], 93: [_p_two_locs],
    94: [_p_lpupdate], 96: [_p_two_locs], 97: [_p_two_locs],
    100: [_p_pay_lpcost], 101: [_p_add_counter], 102: [_p_add_counter],
    110: [_p_attack], 111: [_p_battle], 112: [_p_empty], 113: [_p_empty],
    114: [_p_empty],
    120: [_p_missed_effect], 130: [_p_coin_or_dice], 131: [_p_coin_or_dice],
    140: [_p_announce_mask], 141: [_p_announce_mask], 142: [_p_announce_card],
    143: [_p_announce_card],
    160: [_p_card_hint], 165: [_p_player_hint], 190: [_p_remove_cards],
}

#: 变体名的可读标签（写进消息的 ``layout`` 字段，方便报告「到底哪套布局命中」）
_LAYOUT_LABELS: dict[int, list[str]] = {
    10: ["实测:attackable.seq=u8", "源码:attackable.seq=u32"],
    11: ["实测:repos.seq=u8", "源码:repos.seq=u32"],
}


# ══════════════════════════════════════════════════════════════════════
#  响应编码器（决策 → 字节序列）
# ══════════════════════════════════════════════════════════════════════
def encode_int32(*values: int) -> bytes:
    """一个或多个 int32（``returns.at<int32_t>(i)`` 的第 i 个元素）。"""
    return struct.pack(f"<{len(values)}i", *[int(v) for v in values])


def encode_idlecmd(op: int, index: int = 0) -> bytes:
    """``ANSWER_IDLECMD``：低 16 位是动作号，高 16 位是列表下标。

    动作号：0 召唤 / 1 特殊召唤 / 2 表示变更 / 3 盖怪兽 / 4 盖魔陷 / 5 发动 /
    6 进战斗阶段 / 7 进结束阶段 / 8 洗牌。
    """
    return encode_int32((int(op) & 0xFFFF) | ((int(index) & 0xFFFF) << 16))


def encode_battlecmd(op: int, index: int = 0) -> bytes:
    """``ANSWER_BATTLECMD``：0 发动 / 1 攻击 / 2 _main2 / 3 结束。"""
    return encode_int32((int(op) & 0xFFFF) | ((int(index) & 0xFFFF) << 16))


def encode_select_card(indices: Iterable[int] | None, cancel: bool = False) -> bytes:
    """``ANSWER_SELECTCARD/TRIBUTE/SUM``：type int32 + 数量 uint32 + 下标 uint32 数组。"""
    if cancel:
        return encode_int32(-1)
    idx = [int(i) for i in (indices or [])]
    return encode_int32(0, len(idx)) + struct.pack(f"<{len(idx)}I", *idx)


def encode_select_bitmask(bits: int) -> bytes:
    """type=3 形态：从第 2 个 int32 起按位标记选中的候选。"""
    return encode_int32(3, int(bits))


def encode_chain_choice(index: int = -1) -> bytes:
    """``ANSWER_SELECTCHAIN``：-1 = 不连锁。"""
    return encode_int32(int(index))


def encode_yesno(yes: bool) -> bytes:
    """``ANSWER_SELECTYESNO`` / ``ANSWER_SELECTEFFECTYN``：0 否 / 1 是（其它值必被 RETRY）。"""
    return encode_int32(1 if yes else 0)


def encode_option(index: int = 0) -> bytes:
    """``ANSWER_SELECTOPTION`` / ``ANSWER_ANNOUNCE*``（number/card）：候选下标。"""
    return encode_int32(int(index))


def encode_position(mask: int) -> bytes:
    """``ANSWER_SELECTPOSITION``：必须是 1/2/4/8 之一。"""
    return encode_int32(int(mask))


def encode_places(picks: Iterable[tuple[int, int, int]]) -> bytes:
    """``ANSWER_SELECTPLACE`` / ``ANSWER_SELECTDISFIELD``：每个选择 (player, location, seq) 各 1 字节。"""
    out = bytearray()
    for player, location, seq in picks:
        out += bytes([int(player) & 0xFF, int(location) & 0xFF, int(seq) & 0xFF])
    return bytes(out)


def encode_sort_order(order: Iterable[int]) -> bytes:
    """``ANSWER_SORTCARD``：每个 int8 给出该位置卡在原列表中的下标；-1 表示放弃排序。"""
    vals = [int(v) for v in order]
    if not vals:
        return encode_int32(-1)
    return bytes(struct.pack(f"<{len(vals)}b", *vals))


def encode_counters(values: Iterable[int]) -> bytes:
    """``ANSWER_SELECTCOUNTER``：每张卡一个 int16。"""
    vals = [int(v) for v in values]
    return struct.pack(f"<{len(vals)}h", *vals) if vals else encode_int32(0)


def encode_race(mask: int) -> bytes:
    return struct.pack("<Q", int(mask))


def encode_attribute(mask: int) -> bytes:
    return encode_int32(int(mask))


# ══════════════════════════════════════════════════════════════════════
#  帧解析入口
# ══════════════════════════════════════════════════════════════════════
def parse_frames(raw: bytes) -> list[tuple[int, bytes]]:
    """``[uint32 len][uint8 event][payload]`` → ``[(event_id, payload), ...]``。"""
    out: list[tuple[int, bytes]] = []
    off = 0
    n = len(raw)
    while off + 5 <= n:
        (plen,) = struct.unpack_from("<I", raw, off)
        if plen < 1 or off + 4 + plen > n:
            break
        out.append((raw[off + 4], raw[off + 5: off + 4 + plen]))
        off += 4 + int(plen)
    return out


def decode_message(event: int, payload: bytes) -> dict:
    """把一条消息解成结构化 dict（字段名英文小写，原始数值保留在 ``all``）。

    先按「刚好消费完全部载荷」的标准依次试该消息号的候选布局；全都不吻合才判
    ``decode_error``（保留原始字节，绝不猜）。
    """
    name = MSG_NAMES.get(event, f"unknown_{event}")
    base = {"id": event, "event": name, "answer": event in ANSWER_MESSAGES,
            "all": list(payload), "raw": payload.hex()}
    variants = _MESSAGE_PARSERS.get(event)
    if not variants:
        base["decode_error"] = f"未核对布局的消息号 {event}（保留原始字节）"
        return base
    first_error = ""
    for idx, fn in enumerate(variants):
        try:
            r = _Reader(payload)
            fields = fn(r)
        except (ValueError, struct.error, IndexError) as e:
            if not first_error:
                first_error = str(e)
            continue
        if not r.done():
            continue                      # 有剩余字节 → 这套布局不对，换下一套
        base.update(fields)
        labels = _LAYOUT_LABELS.get(event)
        base["layout"] = labels[idx] if labels and idx < len(labels) else f"variant{idx}"
        return base
    base["decode_error"] = (f"{len(variants)} 套候选布局都不吻合 {name}"
                            f"（首个失败原因：{first_error or '载荷未被消费完'}）")
    return base


def parse_messages(raw: bytes) -> list[dict]:
    """整块消息缓冲 → 结构化消息列表（``bot.SimpleBot`` 的输入）。"""
    return [decode_message(ev, pl) for ev, pl in parse_frames(raw)]


# ══════════════════════════════════════════════════════════════════════
#  查询缓冲解析（OCG_DuelQuery / OCG_DuelQueryField）
# ══════════════════════════════════════════════════════════════════════
_QUERY_FLAG_NAMES: dict[int, str] = {
    0x1: "code", 0x2: "position", 0x4: "alias", 0x8: "type", 0x10: "level",
    0x20: "rank", 0x40: "attribute", 0x80: "race", 0x100: "attack",
    0x200: "defense", 0x400: "base_attack", 0x800: "base_defense",
    0x1000: "reason", 0x2000: "reason_card", 0x4000: "equip_card",
    0x8000: "target_card", 0x10000: "overlay_card", 0x20000: "counters",
    0x40000: "owner", 0x80000: "status", 0x100000: "is_public",
    0x200000: "lscale", 0x400000: "rscale", 0x800000: "link",
    0x1000000: "is_hidden", 0x2000000: "cover",
}


def parse_query(raw: bytes) -> dict:
    """``OCG_DuelQuery`` 的单卡查询字节 → dict。

    每段是 ``[uint16 负载长度][uint32 字段位][值]``（对照 ``card::get_infos`` 的
    ``CHECK_AND_INSERT_T`` 宏）；未知字段保留在 ``all`` 里。
    """
    out: dict = {"all": [], "raw": raw.hex()}
    off = 0
    n = len(raw)
    while off + 6 <= n:
        (size,) = struct.unpack_from("<H", raw, off)
        (flag,) = struct.unpack_from("<I", raw, off + 2)
        if size < 4 or off + 2 + size > n:
            break
        payload = raw[off + 6: off + 2 + size]
        name = _QUERY_FLAG_NAMES.get(flag, f"field_{flag:x}")
        value = int.from_bytes(payload[:8], "little") if payload else 0
        if name in out:
            out.setdefault("all", []).append({name: value})
        else:
            out[name] = value
        off += 2 + int(size)
    out["consumed"] = off
    return out


def parse_field(raw: bytes) -> dict:
    """``OCG_DuelQueryField`` 的整场快照 → dict（LP / 区域占用 / 各堆数量 / 当前链）。"""
    out: dict = {"players": [], "all": [], "raw": raw.hex()}
    r = _Reader(raw)
    try:
        out["duel_flags"] = r.u32()
        for _ in range(2):
            p: dict = {"lp": r.u32(), "monster_zones": [], "spell_zones": []}
            for key, count in (("monster_zones", 7), ("spell_zones", 8)):
                for _i in range(count):
                    present = r.u8()
                    if present:
                        p[key].append({"occupied": True, "position": r.u8(),
                                       "materials": r.u32()})
                    else:
                        p[key].append({"occupied": False})
            p["deck"], p["hand"], p["grave"], p["removed"], p["extra"], p["pendulum_count"] = (
                r.u32(), r.u32(), r.u32(), r.u32(), r.u32(), r.u32())
            out["players"].append(p)
        chains = []
        for _ in range(r.u32()):
            entry = r.card()
            entry["triggering_player"] = r.u8()
            entry["triggering_location"] = r.u8()
            entry["triggering_sequence"] = r.u32()
            entry["desc"] = r.u64()
            chains.append(entry)
        out["chains"] = chains
        out["lp"] = [p["lp"] for p in out["players"]]
    except (ValueError, struct.error) as e:
        out["decode_error"] = f"场快照解析中断：{e}"
    return out


# ══════════════════════════════════════════════════════════════════════
#  PE 导出表（只读；不加载 DLL 也能枚举）
# ══════════════════════════════════════════════════════════════════════
def pe_exports(path: Path) -> list[dict]:
    """解析 PE32+ 导出目录，返回 ``[{name, ordinal, rva}, ...]``；失败返回空列表。"""
    import mmap

    try:
        with path.open("rb") as fh:
            data = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
    except (OSError, ValueError):
        return []
    try:
        return _parse_pe_exports(data)
    finally:
        data.close()


def _parse_pe_exports(data) -> list[dict]:
    if data[:2] != b"MZ":
        return []
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return []
    coff = e_lfanew + 4
    nsec = struct.unpack_from("<H", data, coff + 2)[0]
    optsz = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (112 if magic == 0x20B else 96)
    exp_rva, exp_size = struct.unpack_from("<II", data, dd)
    if not exp_rva:
        return []
    sec_off = opt + optsz
    sections = []
    for i in range(nsec):
        rec = data[sec_off + i * 40: sec_off + (i + 1) * 40]
        if len(rec) < 40:
            break
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", rec, 8)
        sections.append((vaddr, vsize, rawptr, rawsize))

    def to_off(rva: int) -> Optional[int]:
        for vaddr, vsize, rawptr, rawsize in sections:
            if vaddr <= rva < vaddr + max(vsize, rawsize):
                return rawptr + (rva - vaddr)
        return None

    off = to_off(exp_rva)
    if off is None:
        return []
    (_fl, _ts, _maj, _min, _name, ord_base, n_funcs,
     n_names) = struct.unpack_from("<IIHHIIII", data, off)
    addr_rva, names_rva, ords_rva = struct.unpack_from("<III", data, off + 28)
    aoff, noff, ooff = to_off(addr_rva), to_off(names_rva), to_off(ords_rva)
    if aoff is None or noff is None or ooff is None:
        return []
    out: list[dict] = []
    for i in range(n_names):
        soffi = to_off(struct.unpack_from("<I", data, noff + i * 4)[0])
        if soffi is None:
            continue
        end = data.find(b"\0", soffi)
        if end < 0:
            continue
        name = data[soffi:end].decode("ascii", "replace")
        idx = struct.unpack_from("<H", data, ooff + i * 2)[0]
        rva = struct.unpack_from("<I", data, aoff + idx * 4)[0]
        out.append({"name": name, "ordinal": ord_base + idx, "rva": rva})
    return out


# ══════════════════════════════════════════════════════════════════════
#  卡面数据
# ══════════════════════════════════════════════════════════════════════
def card_data_from_row(row: dict | sqlite3.Row) -> dict:
    """cdb 的 ``datas`` 行 → 本模块的卡面 dict。

    ``level`` 列是打包值：``(左刻度<<24)|(右刻度<<16)|等级``（官方池实测）。
    """
    get = row.get if isinstance(row, dict) else (lambda k, d=None: row[k])
    level = int(get("level", 0) or 0)
    return {
        "code": int(get("code", 0) or get("id", 0) or 0),
        "alias": int(get("alias", 0) or 0),
        "setcodes": [int(x) for x in _unpack_setcode(get("setcode", 0))],
        "type": int(get("type", 0) or 0),
        "level": level & 0xFF,
        "lscale": (level >> 24) & 0xFF,
        "rscale": (level >> 16) & 0xFF,
        "attribute": int(get("attribute", 0) or 0),
        "race": int(get("race", 0) or 0),
        "attack": int(get("attack", 0) or get("atk", 0) or 0),
        "defense": int(get("defense", 0) or get("def", 0) or 0),
        "link_marker": int(get("def", 0) or 0) if (int(get("type", 0) or 0) & 0x4000000) else 0,
    }


def _unpack_setcode(value) -> list[int]:
    v = int(value or 0) & 0xFFFFFFFFFFFFFFFF
    out = []
    for i in range(4):
        part = (v >> (i * 16)) & 0xFFFF
        if part:
            out.append(part)
    return out


def is_extra_deck_type(type_bits: int) -> bool:
    """按 ``datas.type`` 位判断是否是额外卡组卡（融合/仪式/同调/超量/连接）。"""
    return bool(int(type_bits or 0) & TYPE_EXTRA_MASK)


def split_main_extra(codes: Iterable[int],
                      type_of: Callable[[int], int]) -> tuple[list[int], list[int]]:
    """把一串卡号按卡面 type 位拆成 ``(主卡组, 额外卡组)``；``type_of`` 取不到类型时按主卡组算。"""
    main: list[int] = []
    extra: list[int] = []
    for code in codes:
        c = int(code or 0)
        if not c:
            continue
        try:
            bits = int(type_of(c) or 0)
        except Exception:
            bits = 0
        (extra if is_extra_deck_type(bits) else main).append(c)
    return main, extra


# ══════════════════════════════════════════════════════════════════════
#  驱动主体
# ══════════════════════════════════════════════════════════════════════
@dataclass
class OcgCore:
    """ocgcore 的一层薄封装：持有 DLL、duel 句柄与三个回调闭环。

    用法（对上层只暴露语义，不暴露 ABI）::

        core = OcgCore()
        core.register_card_data(4698641, {...})           # 或 register_cdb(path)
        core.register_script("c4698641.lua", "...")
        core.create_duel(seed=1)                          # 0 = 成功
        core.inject_deck(main_a, extra_a, main_b, extra_b)
        core.start_duel()
        while core.process() == 1:
            core.set_response(...)                        # 配合 parse_messages()
        core.end_duel()
    """

    lib_path: Optional[str] = None
    card_data: dict[int, dict] = field(default_factory=dict)
    memory_scripts: dict[str, str] = field(default_factory=dict)
    script_dirs: list[Path] = field(default_factory=list)
    player_info: dict = field(default_factory=dict)
    duel_flags: int = DUEL_FLAGS_MR5_DEFAULT

    _lib: Optional[object] = None
    _duel: Optional[object] = None
    _exports: Optional[list[dict]] = None
    _cdbcdb: Optional[sqlite3.Connection] = None

    # 运行期收集
    script_errors: list[str] = field(default_factory=list)
    missing_scripts: list[str] = field(default_factory=list)
    loaded_scripts: list[str] = field(default_factory=list)
    runtime_missing: list[str] = field(default_factory=list)
    runtime_preloaded: dict = field(default_factory=dict)
    logs: list[dict] = field(default_factory=list)
    unknown_events: dict[str, int] = field(default_factory=dict)

    #: 回调必须活得比 duel 久，否则核心调用了已释放的函数指针
    _cb_refs: dict = field(default_factory=dict)
    _card_cache: dict = field(default_factory=dict)

    # ── 构造与库定位 ────────────────────────────────────────────────
    def __post_init__(self) -> None:
        if not self.script_dirs:
            self.script_dirs = [paths.OFFICIAL_SCRIPTS, paths.OFFICIAL_SCRIPTS / "samples"]
        self._load_library()

    def _candidate_paths(self) -> list[Path]:
        """按优先级给出候选 DLL：显式路径 → 环境变量 → vendor/engine → 安装目录。"""
        from . import engine

        out: list[Path] = []
        if self.lib_path:
            out.append(Path(self.lib_path))
        else:
            st = engine.detect()
            if st.lib_path:
                out.append(Path(st.lib_path))
            out.extend(paths.ENGINE_DIR / n for n in engine.platform_lib_names())
        return out

    def _load_library(self) -> None:
        """加载原生库并绑定**真实** ABI；失败抛 ``EngineUnavailable``。"""
        if not sys.platform.startswith("win"):
            raise EngineUnavailable(
                "当前平台不是 Windows，vendor 里只有 MinGW 版 ocgcore.dll",
                hint="需要对应平台的 libocgcore.so / .dylib。")
        tried: list[str] = []
        for cand in self._candidate_paths():
            tried.append(str(cand))
            if not cand.exists():
                continue
            try:
                try:
                    os.add_dll_directory(str(cand.parent))  # 同目录的 libstdc++/libgcc/libwinpthread
                except Exception:
                    pass
                lib = ctypes.CDLL(str(cand))
            except OSError as e:
                raise EngineUnavailable(f"加载 {cand.name} 失败：{e}",
                                        hint="把 EDOPro 目录里的 libstdc++-6.dll / "
                                             "libgcc_s_seh-1.dll / libwinpthread-1.dll "
                                             "与本 DLL 放在一起。")
            self.lib_path = str(cand)
            self._lib = lib
            self._bind()
            return
        raise EngineUnavailable("未找到可用的 ocgcore 原生库",
                                hint=f"试过：{'; '.join(tried)}")

    def _bind(self) -> None:
        """按 ocgapi.h 的真实签名设置 argtypes/restype。"""
        lib = self._lib
        assert lib is not None
        vp = ctypes.c_void_p
        lib.OCG_GetVersion.restype = None
        lib.OCG_GetVersion.argtypes = [ctypes.POINTER(ctypes.c_int),
                                       ctypes.POINTER(ctypes.c_int)]
        lib.OCG_CreateDuel.restype = ctypes.c_int
        lib.OCG_CreateDuel.argtypes = [ctypes.POINTER(vp), ctypes.POINTER(CDuelOptions)]
        lib.OCG_DestroyDuel.restype = None
        lib.OCG_DestroyDuel.argtypes = [vp]
        lib.OCG_StartDuel.restype = None
        lib.OCG_StartDuel.argtypes = [vp]
        lib.OCG_DuelProcess.restype = ctypes.c_int
        lib.OCG_DuelProcess.argtypes = [vp]
        lib.OCG_DuelGetMessage.restype = vp
        lib.OCG_DuelGetMessage.argtypes = [vp, ctypes.POINTER(ctypes.c_uint32)]
        lib.OCG_DuelSetResponse.restype = None
        lib.OCG_DuelSetResponse.argtypes = [vp, ctypes.c_void_p, ctypes.c_uint32]
        lib.OCG_LoadScript.restype = ctypes.c_int
        lib.OCG_LoadScript.argtypes = [vp, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p]
        lib.OCG_DuelNewCard.restype = None
        lib.OCG_DuelNewCard.argtypes = [vp, ctypes.POINTER(CNewCard)]
        lib.OCG_DuelQueryCount.restype = ctypes.c_uint32
        lib.OCG_DuelQueryCount.argtypes = [vp, ctypes.c_uint8, ctypes.c_uint32]
        lib.OCG_DuelQuery.restype = vp
        lib.OCG_DuelQuery.argtypes = [vp, ctypes.POINTER(ctypes.c_uint32),
                                      ctypes.POINTER(CQueryInfo)]
        lib.OCG_DuelQueryLocation.restype = vp
        lib.OCG_DuelQueryLocation.argtypes = [vp, ctypes.POINTER(ctypes.c_uint32),
                                              ctypes.POINTER(CQueryInfo)]
        lib.OCG_DuelQueryField.restype = vp
        lib.OCG_DuelQueryField.argtypes = [vp, ctypes.POINTER(ctypes.c_uint32)]

    # ── 数据 / 脚本供给 ────────────────────────────────────────────
    def register_card_data(self, code: int, data: dict) -> None:
        """登记一张卡的引擎侧卡面（DIY 卡没有 cdb 行时由上层提供）。"""
        code = int(code or 0)
        if not code:
            return
        merged = dict(data or {})
        merged["code"] = code
        self.card_data[code] = merged
        self._card_cache.pop(code, None)

    def register_cdb(self, cdb_path: str | Path) -> None:
        """挂一个只读 cdb 作为卡面来源（官方卡池）。"""
        p = Path(cdb_path)
        if not p.exists():
            return
        con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        self._cdbcdb = con

    def register_script(self, name: str, content: str) -> None:
        """把一段 Lua 源码登记成可被核心按名索取的脚本（DIY 卡走这里）。"""
        if not name or not (content or "").strip():
            return
        self.memory_scripts[name] = content

    def register_card_script(self, code: int, lua: str) -> None:
        """按 ``c<code>.lua`` 的命名规则登记卡脚本。"""
        if int(code or 0) <= 0 or not (lua or "").strip():
            return
        self.register_script(f"c{int(code)}.lua", lua)

    # ── 契约方法 ────────────────────────────────────────────────────
    #: 开局前必须塞进 Lua 状态的全局运行库（实测：`GetID` 等定义在 utility.lua，
    #: 数值常量在 constant.lua；核心**不会**主动来要这两个文件）。
    RUNTIME_SCRIPTS: tuple[str, ...] = ("constant.lua", "utility.lua")

    def create_duel(self, seed: int, flags: int = DUEL_FLAGS_MR5_DEFAULT) -> int:
        """创建一局；返回核心的 ``OCG_DuelCreationStatus``（0 = 成功）。

        成功后立刻把全局运行库（``RUNTIME_SCRIPTS``）注入 Lua 状态 —— 实测不这么做，
        卡脚本里的 ``GetID()`` 就是 nil，每张卡都会报 「attempt to call an error function」。
        """
        assert self._lib is not None
        self.duel_flags = int(flags)
        info = self.player_info or dict(
            lp=DEFAULT_LP, hand=DEFAULT_HAND, draw=1, hand_limit=DEFAULT_HAND_LIMIT)
        self.player_info = info
        opts = CDuelOptions()
        s = int(seed or 0)
        # 核心要求 seed 非全零（Xoshiro256**），否则返回 NULL_RNG_SEED
        opts.seed = (ctypes.c_uint64 * 4)(s | 1, (s * 2654435761) & 0xFFFFFFFF,
                                          (s ^ 0x9E3779B9) | 2, (s + 44) | 4)
        opts.flags = self.duel_flags
        lp = int(info.get("lp", DEFAULT_LP))
        hand = int(info.get("hand", DEFAULT_HAND))
        per_turn = int(info.get("draw", 1))
        opts.team1 = CPlayer(lp, hand, per_turn)
        opts.team2 = CPlayer(lp, hand, per_turn)

        self._cb_refs = {}
        opts.cardReader = self._cb("cardReader", _C_DATAREADER, self._on_read_card)
        opts.cardReaderDone = self._cb("cardReaderDone", _C_DATAREADER_DONE,
                                       self._on_read_card_done)
        opts.scriptReader = self._cb("scriptReader", _C_SCRIPTREADER, self._on_read_script)
        opts.logHandler = self._cb("logHandler", _C_LOGHANDLER, self._on_log)

        duel = ctypes.c_void_p()
        status = int(self._lib.OCG_CreateDuel(ctypes.byref(duel), ctypes.byref(opts)))
        if status == 0:
            self._duel = duel
            self.preload_runtime()
        return status

    def preload_runtime(self, names: Iterable[str] = RUNTIME_SCRIPTS) -> dict:
        """把官方 Lua 运行库按名注入；返回 ``{名字: 是否成功}``，取不到文件的记进 runtime_missing。"""
        result: dict[str, bool] = {}
        for name in names:
            blob = self.resolve_script(name)
            if blob is None:
                result[name] = False
                if name not in self.runtime_missing:
                    self.runtime_missing.append(name)
                continue
            self.load_script(name, blob.decode("utf-8", "ignore"))
            result[name] = True
        self.runtime_preloaded = result
        return result

    def _cb(self, key, ctype, fn):  # type: ignore[no-untyped-def]
        inst = ctype(fn)
        self._cb_refs[key] = inst
        return inst

    def start_duel(self) -> None:
        """开局（核心的 Startup 流程：洗牌、抽起手、进入第一回合）。"""
        if self._duel is None or self._lib is None:
            raise EngineUnavailable("还没有创建对局，无法 start_duel")
        self._lib.OCG_StartDuel(self._duel)

    def process(self) -> int:
        """推进一步；返回 ``0=end / 1=awaiting / 2=continue``。"""
        if self._duel is None or self._lib is None:
            raise EngineUnavailable("还没有创建对局，无法 process")
        return int(self._lib.OCG_DuelProcess(self._duel))

    def get_message(self) -> bytes:
        """取当前消息缓冲的**原始字节**（未分帧）。"""
        if self._duel is None or self._lib is None:
            return b""
        ln = ctypes.c_uint32()
        buf = self._lib.OCG_DuelGetMessage(self._duel, ctypes.byref(ln))
        n = int(ln.value)
        if not buf or n <= 0:
            return b""
        return ctypes.string_at(buf, n)

    def messages(self) -> list[dict]:
        """``get_message()`` 的结构化版本（``bot`` 用的就是这个）。"""
        return parse_messages(self.get_message())

    def set_response(self, resp: bytes) -> None:
        """把响应字节交给核心（``bytes``/``bytearray``/``memoryview``）。"""
        if self._duel is None or self._lib is None:
            return
        data = bytes(resp or b"")
        self._lib.OCG_DuelSetResponse(self._duel, data, len(data))

    def load_script(self, name: str, content: str) -> None:
        """直接把脚本塞进核心（对应 ``OCG_LoadScript(duel, buf, len, name)``）。"""
        if self._duel is None or self._lib is None:
            raise EngineUnavailable("还没有创建对局，无法 load_script")
        buf = (content or "").encode("utf-8")
        self._lib.OCG_LoadScript(self._duel, buf, len(buf), str(name).encode("utf-8"))

    def new_card(self, data: dict) -> int:
        """注入一张卡（``OCG_DuelNewCard``）；返回卡号，0 表示没注入。"""
        if self._duel is None or self._lib is None:
            raise EngineUnavailable("还没有创建对局，无法 new_card")
        code = int(data.get("code", data.get("id", 0)) or 0)
        if not code:
            return 0
        info = CNewCard()
        info.team = int(data.get("team", data.get("owner", 0))) & 0xFF
        info.duelist = int(data.get("duelist", 0)) & 0xFF
        info.code = code
        info.con = int(data.get("con", data.get("controller", info.team))) & 0xFF
        info.loc = int(data.get("loc", data.get("location", LOCATION_DECK)))
        info.seq = int(data.get("seq", data.get("sequence", 0)))
        info.pos = int(data.get("pos", data.get("position", POS_FACEDOWN_DEFENSE)))
        self._lib.OCG_DuelNewCard(self._duel, ctypes.byref(info))
        return code

    def query(self, con: int = 0, loc: int = 0, seq: int = 0,
              flags: int = QUERY_CODE | QUERY_POSITION | QUERY_ATTACK | QUERY_DEFENSE,
              overlay_seq: int = 0, *, location_wide: bool = False) -> bytes:
        """``OCG_DuelQuery`` / ``OCG_DuelQueryLocation`` → 原始查询字节。"""
        if self._duel is None or self._lib is None:
            return b""
        info = CQueryInfo(flags, int(con) & 0xFF, int(loc), int(seq), int(overlay_seq))
        ln = ctypes.c_uint32()
        fn = (self._lib.OCG_DuelQueryLocation if location_wide else self._lib.OCG_DuelQuery)
        buf = fn(self._duel, ctypes.byref(ln), ctypes.byref(info))
        n = int(ln.value)
        return ctypes.string_at(buf, n) if buf and n > 0 else b""

    def query_card(self, con: int, loc: int, seq: int,
                   flags: int = QUERY_CODE | QUERY_POSITION | QUERY_ATTACK | QUERY_DEFENSE
                   | QUERY_BASE_ATTACK | QUERY_TYPE,
                   overlay_seq: int = 0) -> dict:
        """查询场上/区域里一张卡，返回解好的 dict（``parse_query``）。"""
        return parse_query(self.query(con, loc, seq, flags, overlay_seq))

    def query_field(self) -> bytes:
        """``OCG_DuelQueryField``：整场快照的原始字节。"""
        if self._duel is None or self._lib is None:
            return b""
        ln = ctypes.c_uint32()
        buf = self._lib.OCG_DuelQueryField(self._duel, ctypes.byref(ln))
        n = int(ln.value)
        return ctypes.string_at(buf, n) if buf and n > 0 else b""

    def field_state(self) -> dict:
        """整场快照的解析结果（LP、区域占用、各堆数量、当前链）。"""
        return parse_field(self.query_field())

    def query_count(self, team: int = 0, location: int = LOCATION_HAND) -> int:
        """某区域的数量（手牌 / 卡组 / 墓穴 / 除外 / 额外 / 怪兽区 / 魔陷区）。"""
        if self._duel is None or self._lib is None:
            return 0
        return int(self._lib.OCG_DuelQueryCount(self._duel, int(team) & 0xFF, int(location)))

    def end_duel(self) -> None:
        """销毁对局；回调引用一并释放。"""
        if self._duel is not None and self._lib is not None:
            try:
                self._lib.OCG_DestroyDuel(self._duel)
            finally:
                self._duel = None
        self._cb_refs.clear()
        self._card_cache.clear()
        if self._cdbcdb is not None:
            try:
                self._cdbcdb.close()
            except Exception:
                pass
            self._cdbcdb = None

    # ── 卡组注入 ───────────────────────────────────────────────────
    def inject_deck(self, deck_a: list[int], deck_b: list[int],
                    extra_a: Optional[list[int]] = None,
                    extra_b: Optional[list[int]] = None,
                    *, position: int = POS_FACEDOWN_DEFENSE) -> dict:
        """把两个卡组（卡号列表）注入对局。

        ``deck_*`` 是主卡组，``extra_*`` 是额外卡组；``0`` 是 gates 那边占位的
        「空位」，会被丢掉并记进 ``detail`` —— 绝不假装注入。
        """
        out = {"main": [0, 0], "extra": [0, 0], "skipped_zero": 0, "unknown": []}
        for team, main, extra in ((0, deck_a, extra_a or []), (1, deck_b, extra_b or [])):
            seq = 0
            for code in list(main or []):
                code = int(code or 0)
                if not code:
                    out["skipped_zero"] += 1
                    continue
                if not self._has_card_data(code):
                    out["unknown"].append(code)
                if self.new_card({"code": code, "team": team, "con": team,
                                 "loc": LOCATION_DECK, "seq": seq, "pos": position}):
                    out["main"][team] += 1
                    seq += 1
            eseq = 0
            for code in list(extra or []):
                code = int(code or 0)
                if not code:
                    out["skipped_zero"] += 1
                    continue
                if not self._has_card_data(code):
                    out["unknown"].append(code)
                if self.new_card({"code": code, "team": team, "con": team,
                                 "loc": LOCATION_EXTRA, "seq": eseq,
                                 "pos": position}):
                    out["extra"][team] += 1
                    eseq += 1
        return out

    def place_field(self, team: int, location: int, sequence: int, code: int,
                    pos: int = POS_FACEUP_ATTACK) -> bool:
        """场面预置（场景单测用）：直接把卡放到指定区域。"""
        return bool(self.new_card({"code": int(code), "team": team, "con": team,
                                  "loc": location, "seq": sequence, "pos": pos}))

    def _has_card_data(self, code: int) -> bool:
        if code in self.card_data:
            return True
        return self._cdb_row(code) is not None

    def type_bits_of(self, code: int) -> int:
        """卡面 ``type`` 位；取不到返回 0（调用方据此判断「不知道这是什么卡」）。"""
        code = int(code or 0)
        data = self.card_data.get(code)
        if data:
            return int(data.get("type", 0) or 0)
        row = self._cdb_row(code)
        return int(row["type"] or 0) if row is not None else 0

    def has_script(self, name: str) -> bool:
        """这张脚本能不能取到（内存登记过或在 script_dirs 里）；不污染 ``missing_scripts``。"""
        return self.resolve_script(name, record=False) is not None

    # ── 三个回调的实现 ─────────────────────────────────────────────
    def _cdb_row(self, code: int):
        if self._cdbcdb is None:
            return None
        try:
            return self._cdbcdb.execute(
                "SELECT id,alias,setcode,type,atk,def,level,race,attribute"
                " FROM datas WHERE id=?", (code,)).fetchone()
        except sqlite3.Error:
            return None

    def _built_card_data(self, code: int) -> Optional[CCardData]:
        cached = self._card_cache.get(code)
        if cached is not None:
            return cached
        raw = self.card_data.get(code) or {}
        row = self._cdb_row(code)
        if row is not None:
            raw = {**card_data_from_row(dict(zip(row.keys(), tuple(row)))), **raw}
        if not raw and not code:
            return None
        d = CCardData()
        d.code = code
        d.alias = int(raw.get("alias", 0) or 0)
        setcodes = [int(x) & 0xFFFF for x in (raw.get("setcodes") or [])][:4]
        arr = (ctypes.c_uint16 * (len(setcodes) + 1))(*setcodes, 0)
        d.setcodes = ctypes.cast(arr, ctypes.POINTER(ctypes.c_uint16))
        d.type = int(raw.get("type", 0) or 0)
        d.level = int(raw.get("level", 0) or 0) & 0xFF
        d.attribute = int(raw.get("attribute", 0) or 0)
        d.race = int(raw.get("race", 0) or 0)
        d.attack = int(raw.get("attack", 0) or 0)
        d.defense = int(raw.get("defense", 0) or 0)
        d.lscale = int(raw.get("lscale", 0) or 0) & 0xFF
        d.rscale = int(raw.get("rscale", 0) or 0) & 0xFF
        d.link_marker = int(raw.get("link_marker", 0) or 0)
        # arr 必须活着：由 _card_cache 持有引用
        self._card_cache[code] = d
        setattr(d, "_setcodes_array", arr)  # noqa: B010  防止数组被回收
        return d

    def _on_read_card(self, _payload, code: int, ptr) -> None:  # type: ignore[no-untyped-def]
        """``OCG_DataReader``：核心按卡号来要卡面数据。"""
        try:
            d = self._built_card_data(int(code))
        except Exception as e:
            self.script_errors.append(f"卡面数据回调异常（{code}）：{e}")
            return
        if d is None or not ptr:
            return
        ctypes.memmove(ptr, ctypes.byref(d), ctypes.sizeof(CCardData))

    def _on_read_card_done(self, _payload, _ptr) -> None:
        """``OCG_DataReaderDone``：本实现把数据缓存在 Python 侧，无需释放。"""
        return None

    def resolve_script(self, name: str, *, record: bool = True) -> Optional[bytes]:
        """按名找脚本：内存（DIY）→ script_dirs。找不到返回 None（``record`` 决定是否记名）。"""
        text = self.memory_scripts.get(name)
        if text is not None:
            return text.encode("utf-8")
        plain = name[:-4] if name.endswith(".lua") else name
        text = self.memory_scripts.get(plain)
        if text is not None:
            return text.encode("utf-8")
        for d in self.script_dirs:
            for cand in (d / name, d / f"{plain}.lua", d / f"{plain}"):
                try:
                    if cand.is_file():
                        return cand.read_bytes()
                except OSError:
                    continue
        # 空脚本白名单：这些名字核心会例行索取，但**本来就可以没有**。
        # c0.lua 是卡号 0（空位/未初始化卡）；proc_unofficial 只在非官方规则
        #  duel 里用到。给空串而不是记进 missing_scripts，否则每局都报一条
        # 吓人的"缺脚本"降级说明。
        if plain in _EMPTY_OK_SCRIPTS or name in _EMPTY_OK_SCRIPTS:
            return b""
        if record and name not in self.missing_scripts:
            self.missing_scripts.append(name)
        return None

    def _on_read_script(self, _payload, duel, name_ptr) -> int:
        """``OCG_ScriptReader``：核心索要脚本时回调进来。返回 1 表示加载成功。"""
        try:
            name = (name_ptr or b"").decode("utf-8", "ignore") if isinstance(name_ptr, bytes) \
                else str(name_ptr)
        except Exception:
            return 0
        blob = self.resolve_script(name)
        if blob is None or self._lib is None:
            return 0
        try:
            ok = self._lib.OCG_LoadScript(ctypes.c_void_p(duel), blob, len(blob),
                                          name.encode("utf-8"))
        except Exception as e:
            self.script_errors.append(f"OCG_LoadScript({name}) 异常：{e}")
            return 0
        if ok:
            if name not in self.loaded_scripts:
                self.loaded_scripts.append(name)
            return 1
        return 0

    def _on_log(self, _payload, text, kind: int) -> None:
        """``OCG_LogHandler``：脚本报错都从这里出来，是 G3 的第一手证据。"""
        msg = (text or b"").decode("utf-8", "ignore") if isinstance(text, bytes) else str(text)
        entry = {"type": LOG_TYPES.get(int(kind), str(kind)), "text": msg}
        self.logs.append(entry)
        if entry["type"] == "error":
            self.script_errors.append(msg)

    # ── 元信息 ─────────────────────────────────────────────────────
    def version(self) -> str:
        """``OCG_GetVersion(int*, int*)`` —— 必须按两个 int 出参调用（否则 0xC0000005）。"""
        if self._lib is None:
            return ""
        try:
            maj, mino = ctypes.c_int(), ctypes.c_int()
            self._lib.OCG_GetVersion(ctypes.byref(maj), ctypes.byref(mino))
            if 0 <= int(maj.value) < 1000 and 0 <= int(mino.value) < 1000:
                return f"{int(maj.value)}.{int(mino.value)}"
        except Exception:
            return ""
        return ""

    def exported_symbols(self) -> list[str]:
        """真实导出的 ``OCG_*`` 符号名（PE 解析，不执行任何代码）。"""
        if self._exports is None:
            p = Path(self.lib_path) if self.lib_path else None
            self._exports = [e["name"] for e in (pe_exports(p) if p else [])]
        return sorted(self._exports)

    def library_info(self) -> dict:
        """这个 build 到底导出了什么、缺什么、卡数据与脚本怎么注入。取不到就留空并写明原因。"""
        syms = self.exported_symbols()
        pe_note = ""
        if not syms:
            pe_note = "PE 导出表解析失败（或该库无导出表），符号清单不可用"
        missing_required = [s for s in REQUIRED_SYMBOLS if s not in syms]
        present_extra = [s for s in syms if s not in REQUIRED_SYMBOLS and s not in ABSENT_SYMBOLS]
        version = self.version()
        if not version:
            version_note = "OCG_GetVersion 调用失败或返回值不合理，版本留空（不猜）"
        else:
            version_note = "来自 OCG_GetVersion(int*, int*)（两个 int 出参）"
        return {
            "lib_path": self.lib_path or "",
            "api": "edo9300/ygopro-core 句柄式 API（ocgapi.h）" if syms else "",
            "version": version,
            "version_note": version_note,
            "exported_ocg_symbols": syms,
            "exported_count": len(syms),
            "missing_required": missing_required,
            "absent_expected": [s for s in ABSENT_SYMBOLS if s not in syms],
            "extra_symbols": present_extra,
            "pe_note": pe_note,
            "injection": {
                "card_data": "OCG_DuelOptions.cardReader 回调（void(*)(void*,uint32,OCG_CardData*)）"
                             "；核心自带 data_cache，另配 cardReaderDone 释放钩子。"
                             "没有 OCG_CardLoadCDB —— 不能把 sqlite3* 塞给核心，"
                             "本驱动改为在回调里查 cdb（sqlite3 标准库）。",
                "deck": "OCG_DuelNewCard(duel, OCG_NewCardInfo*)：team/duelist/con/loc/seq/pos；"
                        "duelist=0 走 add_card 直接进 list_main/list_extra，"
                        "注入顺序即卡组顺序（seq 递增）。",
                "player_info": "OCG_DuelOptions.team1/team2 = OCG_Player{startingLP,"
                               " startingDrawCount, drawCountPerTurn}。"
                               "⚠ 手牌上限**不是**可传字段：核心固定 6 张，"
                               "只有 DUEL_NO_HAND_LIMIT(0x1000000) 能取消，"
                               f"所以 player_info 里的 hand_limit={DEFAULT_HAND_LIMIT} 仅作记录。",
                "scripts": "OCG_ScriptReader 回调按名索取（constant.lua/utility.lua/c<code>.lua/"
                           "initial.lua…），回调里调 OCG_LoadScript(duel, buf, len, name)；"
                           "本驱动还允许纯内存脚本（DIY 卡的 lua 直接 register_script）。"
                           "这个 build 的 Startup 是 C++ 处理器，不要求 initial.lua。",
                "strings": "没有 OCG_AddString/OCG_GetStringByKey —— 卡名文本无法进核心，"
                           "消息里只有卡号，名称由上层从 cdb texts 表翻译。",
            },
            "notes": [
                "OCG_GetVersion 是 (int* major, int* minor)，按 c_char_p/c_uint 调会 0xC0000005。",
                "OCG_DuelGetMessage 返回的是字节缓冲指针 + uint32 长度，"
                "帧格式 [uint32 len][uint8 event][紧凑混合宽度 payload]。",
                "响应按 returns.at<T>(i) 读取：T 决定元素宽度与索引步长，"
                "所以编码时不能一律按 int32 数组对齐（SELECT_PLACE 是 int8 三元组，"
                "SELECT_COUNTER 是 int16 数组）。",
            ],
            "script_dirs": [str(p) for p in self.script_dirs],
            "memory_scripts": sorted(self.memory_scripts),
            "duel_flags": hex(self.duel_flags),
        }
