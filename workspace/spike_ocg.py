# -*- coding: utf-8 -*-
"""一次性最小验证（不入库）：CreateDuel → NewCard → StartDuel → Process 循环。"""
from __future__ import annotations

import ctypes, json, os, sqlite3, struct, sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
DLL = ROOT / "vendor/engine/ocgcore.dll"
CDB = ROOT / "vendor/data/cards_zh.cdb"
SCRIPTS = ROOT / "vendor/scripts"
OUT = ROOT / "workspace/logs/spike_ocg.json"

c_u8, c_u16, c_u32, c_u64, c_i32 = (ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint32,
                                    ctypes.c_uint64, ctypes.c_int32)

class CardData(ctypes.Structure):
    _fields_ = [("code", c_u32), ("alias", c_u32), ("setcodes", ctypes.POINTER(c_u16)),
                ("type", c_u32), ("level", c_u32), ("attribute", c_u32), ("race", c_u64),
                ("attack", c_i32), ("defense", c_i32), ("lscale", c_u32), ("rscale", c_u32),
                ("link_marker", c_u32)]

class Player(ctypes.Structure):
    _fields_ = [("startingLP", c_u32), ("startingDrawCount", c_u32), ("drawCountPerTurn", c_u32)]

class NewCardInfo(ctypes.Structure):
    _fields_ = [("team", c_u8), ("duelist", c_u8), ("code", c_u32), ("con", c_u8),
                ("loc", c_u32), ("seq", c_u32), ("pos", c_u32)]

DataReader = ctypes.CFUNCTYPE(None, ctypes.c_void_p, c_u32, ctypes.POINTER(CardData))
ScriptReader = ctypes.CFUNCTYPE(c_i32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
LogHandler = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char_p, c_i32)
DataReaderDone = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(CardData))

class DuelOptions(ctypes.Structure):
    _fields_ = [("seed", c_u64 * 4), ("flags", c_u64), ("team1", Player), ("team2", Player),
                ("cardReader", DataReader), ("payload1", ctypes.c_void_p),
                ("scriptReader", ScriptReader), ("payload2", ctypes.c_void_p),
                ("logHandler", LogHandler), ("payload3", ctypes.c_void_p),
                ("cardReaderDone", DataReaderDone), ("payload4", ctypes.c_void_p),
                ("enableUnsafeLibraries", c_u8)]

report: dict = {"stage": "start"}
os.add_dll_directory(str(DLL.parent))
lib = ctypes.CDLL(str(DLL))

maj, mino = c_i32(), c_i32()
lib.OCG_GetVersion.restype = None
lib.OCG_GetVersion.argtypes = [ctypes.POINTER(c_i32), ctypes.POINTER(c_i32)]
lib.OCG_GetVersion(ctypes.byref(maj), ctypes.byref(mino))
report["version"] = [maj.value, mino.value]

db = sqlite3.connect(str(CDB))
db.row_factory = sqlite3.Row
_keep: list = []

@DataReader
def read_card(payload, code, ptr):
    row = db.execute("SELECT alias,setcode,type,atk,def,level,race,attribute"
                     " FROM datas WHERE id=?", (code,)).fetchone()
    if not row:
        return
    d = ptr.contents
    d.code = code
    d.alias = row["alias"] or 0
    sc, v = [], int(row["setcode"] or 0) & 0xFFFFFFFFFFFFFFFF
    for i in range(4):
        p = (v >> (i * 16)) & 0xFFFF
        if p:
            sc.append(p)
    sc.append(0)
    arr = (c_u16 * len(sc))(*sc)
    _keep.append(arr)
    d.setcodes = arr
    d.type = row["type"]
    lvl = row["level"] or 0
    d.level = lvl & 0xFF
    d.lscale = (lvl >> 24) & 0xFF
    d.rscale = (lvl >> 16) & 0xFF
    d.attribute = row["attribute"]
    d.race = row["race"]
    d.attack = row["atk"]
    d.defense = row["def"]

missing_scripts: list[str] = []
loaded_scripts: list[str] = []

@ScriptReader
def read_script(payload, duel, name_ptr):
    name = name_ptr.decode("utf-8", "ignore")
    p = SCRIPTS / name
    if not p.exists() and name.startswith("c") and name[1:8].isdigit():
        p = SCRIPTS / "samples" / name
    if not p.exists():
        missing_scripts.append(name)
        return 0
    buf = p.read_bytes()
    loaded_scripts.append(name)
    return 1 if lib.OCG_LoadScript(ctypes.c_void_p(duel), buf, len(buf), name.encode()) else 0

errors: list[str] = []

@LogHandler
def on_log(payload, s, t):
    if s is not None and t in (0, 1):
        errors.append(f"[{t}] {s.decode('utf-8','ignore')}")

@DataReaderDone
def read_done(payload, ptr):
    pass

# 官方真实卡：取 cdb 里存在脚本样本的前 20 张（保证 script 可解析）
ids = [r["id"] for r in db.execute("SELECT id FROM datas ORDER BY id LIMIT 400")]
sampled = {p.stem[1:] for p in (SCRIPTS / "samples").glob("c*.lua")}
picked = [str(i) for i in ids if str(i) in sampled][:20]
report["picked"] = picked
if not picked:
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(0)

opts = DuelOptions()
opts.seed = (c_u64 * 4)(11, 22, 33, 44)
opts.flags = 0x2E800  # DUEL_MODE_MR5
opts.team1 = Player(8000, 5, 1)
opts.team2 = Player(8000, 5, 1)
opts.cardReader = read_card
opts.scriptReader = read_script
opts.logHandler = on_log
opts.cardReaderDone = read_done

lib.OCG_CreateDuel.restype = c_i32
lib.OCG_CreateDuel.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(DuelOptions)]
duel = ctypes.c_void_p()
st = lib.OCG_CreateDuel(ctypes.byref(duel), ctypes.byref(opts))
report["create_status"] = st
if st != 0:
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(1)

lib.OCG_LoadScript.restype = c_i32
lib.OCG_LoadScript.argtypes = [ctypes.c_void_p, ctypes.c_char_p, c_u32, ctypes.c_char_p]
for g in ("constant.lua", "utility.lua"):
    b = (SCRIPTS / g).read_bytes()
    report.setdefault("preload", {})[g] = lib.OCG_LoadScript(duel, b, len(b), g.encode())

lib.OCG_DuelNewCard.restype = None
lib.OCG_DuelNewCard.argtypes = [ctypes.c_void_p, ctypes.POINTER(NewCardInfo)]
main, extra = [], []
EXTRA_BITS = 0x40 | 0x80 | 0x2000 | 0x800000 | 0x4000000  # fusion/ritual/synchro/xyz/link
for cid in picked:
    row = db.execute("SELECT type FROM datas WHERE id=?", (int(cid),)).fetchone()
    (extra if (row["type"] & 0x1) and (row["type"] & EXTRA_BITS) else main).append(int(cid))
report["main"], report["extra"] = len(main), len(extra)
main = (main * 3)[:40]
extra = (extra * 3)[:15]
for team in (0, 1):
    for i, code in enumerate(main):
        lib.OCG_DuelNewCard(duel, NewCardInfo(team, team, code, team, 0x01, i, 0x8))
    for i, code in enumerate(extra):
        lib.OCG_DuelNewCard(duel, NewCardInfo(team, team, code, team, 0x40, i, 0x8))
report["injected"] = (len(main) + len(extra)) * 2

lib.OCG_DestroyDuel.restype = None
lib.OCG_DestroyDuel.argtypes = [ctypes.c_void_p]
lib.OCG_StartDuel.restype = None
lib.OCG_StartDuel.argtypes = [ctypes.c_void_p]
lib.OCG_StartDuel(duel)
lib.OCG_DuelProcess.restype = c_i32
lib.OCG_DuelProcess.argtypes = [ctypes.c_void_p]
lib.OCG_DuelGetMessage.restype = ctypes.c_void_p
lib.OCG_DuelGetMessage.argtypes = [ctypes.c_void_p, ctypes.POINTER(c_u32)]
lib.OCG_DuelSetResponse.restype = None
lib.OCG_DuelSetResponse.argtypes = [ctypes.c_void_p, ctypes.c_void_p, c_u32]

turns = 0
lp = [8000, 8000]
seen: dict[int, int] = {}
winner = None
msgs_by_type: dict[str, int] = {}
steps = 0
for steps in range(1, 40001):
    status = lib.OCG_DuelProcess(duel)
    ln = c_u32()
    buf = lib.OCG_DuelGetMessage(duel, ctypes.byref(ln))
    n = ln.value
    raw = ctypes.string_at(buf, n) if buf and n else b""
    off = 0
    last = None
    while off + 5 <= len(raw):
        (plen,) = struct.unpack_from("<I", raw, off)
        if plen < 1 or off + 4 + plen > len(raw):
            break
        tp = raw[off + 4]
        pl = raw[off + 5: off + 4 + plen]
        msgs_by_type[str(tp)] = msgs_by_type.get(str(tp), 0) + 1
        if tp == 40 and pl:
            turns += 1
        if tp == 5 and len(pl) >= 2:
            winner = (pl[0], pl[1])
        if tp == 91 and len(pl) >= 5:
            lp[pl[0]] -= struct.unpack_from("<I", pl, 1)[0]
        if tp == 92 and len(pl) >= 5:
            lp[pl[0]] += struct.unpack_from("<I", pl, 1)[0]
        if tp == 100 and len(pl) >= 5:
            lp[pl[0]] -= struct.unpack_from("<I", pl, 1)[0]
        last = (tp, pl)
        off += 4 + plen
    if winner is not None or status == 0:
        break
    if status != 1:
        continue
    if last is None:
        break
    tp, pl = last
    if tp == 11:      # SELECT_IDLECMD：无脑进 EP（末字节 to_ep=1）
        resp = struct.pack("<i", 7 | (0 << 16))
    elif tp == 10:    # SELECT_BATTLECMD：进 M2/EP
        resp = struct.pack("<i", 3 | (0 << 16))
    elif tp == 16:    # SELECT_CHAIN：不连锁
        resp = struct.pack("<i", -1)
    elif tp in (12, 13):
        resp = struct.pack("<i", 0)
    elif tp == 15:    # SELECT_CARD：选最小数量
        p2, cancelable = pl[0], pl[1]
        mn, mx, cnt = struct.unpack_from("<III", pl, 2)
        picks = list(range(min(mn, cnt) if mn else 0, 0)) if mn == 0 else list(range(mn))
        resp = struct.pack("<iI", 0, len(picks)) + struct.pack(f"<{len(picks)}I", *picks)
    elif tp == 14:
        resp = struct.pack("<i", 0)
    elif tp == 18:
        p2, cnt = pl[0], pl[1]
        (flag,) = struct.unpack_from("<I", pl, 2)
        chosen = bytearray()
        f = flag
        for _ in range(cnt):
            for seq in range(8):
                if not (f >> seq) & 1:
                    chosen += bytes([p2, 0x04, seq]); f |= 1 << seq; break
            else:
                for seq in range(8):
                    if not (f >> (8 + seq)) & 1:
                        chosen += bytes([p2, 0x08, seq]); f |= 1 << (8 + seq); break
        resp = bytes(chosen)
    elif tp == 19:
        mask = struct.unpack_from("<I", pl, 5)[0] if len(pl) >= 9 else 1
        bit = 1
        for i in range(8):
            if mask & (1 << i):
                bit = 1 << i
                break
        resp = struct.pack("<i", bit)
    elif tp == 1:
        resp = struct.pack("<i", 7)
    else:
        resp = struct.pack("<i", 0)
    lib.OCG_DuelSetResponse(duel, resp, len(resp))

report.update(steps=steps, turns=turns, lp=lp, winner=winner,
              msg_types=msgs_by_type, errors=errors[:20], error_count=len(errors),
              loaded=len(loaded_scripts), missing=sorted(set(missing_scripts))[:20])
lib.OCG_DestroyDuel(duel)
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("OK")
