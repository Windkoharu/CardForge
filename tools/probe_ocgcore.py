"""只读探测 vendor/engine/ocgcore.dll —— 真实导出符号与 ABI 结论。

用途
----
本项目第一原则是「绝不假装跑过对局」。ctypes 驱动 ocgcore 的风险在于：
调用约定或 argtypes 猜错会直接 0xC0000005 打死进程。所以本脚本只做**只读**探测：

    ① 解析 PE 头，列出全部 ``OCG_*`` 导出符号（不加载 DLL 也能拿到）
    ② 加载 DLL 后逐个把符号归类，推断 ABI
    ③ ``--duel`` 跑一局真实对战，摘要消息流（写文件，不 print 中文）

用法::

    python tools/probe_ocgcore.py                 # ①②，结果写 workspace/logs/ocgcore_exports.json
    python tools/probe_ocgcore.py --duel           # ③ 需要 cardforge.duel.ocgcore 已就绪

⚠ 已知坑：``OCG_GetVersion`` 符号存在但**不是**版本 getter，
按 ``c_char_p`` / ``c_uint`` 调用会 access violation。见 duel/engine.py::_probe_version。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DLL = ROOT / "vendor" / "engine" / "ocgcore.dll"
OUT_DIR = ROOT / "workspace" / "logs"


# ══════════════════════════════════════════════════════════════════════
#  PE 导出表解析（纯标准库；不加载 DLL，因此崩不了）
# ══════════════════════════════════════════════════════════════════════
def _read_pe_exports(path: Path) -> dict:
    """解析 PE32+ 文件的导出目录，返回 {name: ordinal RVA 信息}。

    用 mmap 而不是 read_bytes：这个 build 有 ~197MB，整块读进内存没必要。
    """
    import mmap

    with path.open("rb") as fh:
        data = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            res = _parse_pe(data)
        finally:
            data.close()
    res["dll_name"] = path.name
    return res


def _parse_pe(data) -> dict:
    if data[:2] != b"MZ":
        return {"error": "不是 PE 文件", "count": 0, "names": []}
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return {"error": f"PE 签名缺失@{e_lfanew}", "count": 0, "names": []}
    coff = e_lfanew + 4
    n_sections = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    pe32plus = magic == 0x20B
    # 数据目录偏移：PE32=96, PE32+=112；导出表是第 0 项（RVA@+0，Size@+4）
    dd_off = opt + (96 if not pe32plus else 112)
    exp_rva, exp_size = struct.unpack_from("<II", data, dd_off)

    sections = []
    sec_off = opt + opt_size
    for i in range(n_sections):
        rec = data[sec_off + i * 40: sec_off + (i + 1) * 40]
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", rec, 8)
        sections.append((vaddr, vsize, rawptr, rawsize))

    def rva_to_off(rva: int) -> int | None:
        for vaddr, vsize, rawptr, rawsize in sections:
            if vaddr <= rva < vaddr + max(vsize, rawsize):
                return rawptr + (rva - vaddr)
        return None

    if not exp_rva:
        return {"error": "无导出目录", "count": 0, "names": [], "pe32plus": pe32plus}
    off = rva_to_off(exp_rva)
    if off is None:
        return {"error": "导出目录 RVA 越界", "count": 0, "names": [], "pe32plus": pe32plus}

    # IMAGE_EXPORT_DIRECTORY 字段偏移：
    #   0 Characteristics, 4 TimeDateStamp, 8 MajorVersion(H), 10 MinorVersion(H),
    #   12 Name, 16 OrdinalBase, 20 NumberOfFunctions, 24 NumberOfNames,
    #   28 AddressOfFunctions, 32 AddressOfNames, 36 AddressOfNameOrdinals
    (flags, ts, vmaj, vmin, name_rva, ord_base,
     n_funcs, n_names) = struct.unpack_from("<IIHHIIII", data, off)
    addr_rva, names_rva, ordinals_rva = struct.unpack_from("<III", data, off + 28)
    n_ordinals = n_funcs

    out: list[dict] = []
    noff = rva_to_off(names_rva)
    ooff = rva_to_off(ordinals_rva)
    aoff = rva_to_off(addr_rva)
    if noff is None or ooff is None or aoff is None:
        return {"error": "导出子表 RVA 越界", "count": 0, "names": []}
    for i in range(n_names):
        str_rva = struct.unpack_from("<I", data, noff + i * 4)[0]
        soffi = rva_to_off(str_rva)
        if soffi is None:
            continue
        end = data.find(b"\0", soffi)
        name = data[soffi:end].decode("ascii", "replace")
        idx = struct.unpack_from("<H", data, ooff + i * 2)[0]
        func_rva = struct.unpack_from("<I", data, aoff + idx * 4)[0]
        fwd = func_rva >= exp_rva and func_rva < exp_rva + exp_size
        out.append({"name": name, "ordinal": ord_base + idx,
                    "rva": func_rva, "forwarded": bool(fwd)})
    return {"count": n_names, "n_ordinals": n_ordinals, "pe32plus": pe32plus,
            "exports": out}


# ══════════════════════════════════════════════════════════════════════
#  加载后探测（只碰 argtypes 明确安全的符号）
# ══════════════════════════════════════════════════════════════════════
_SAFE_GETTERS = {
    "OCG_GetVersionMajor": ctypes.c_uint,
    "OCG_GetVersionMinor": ctypes.c_uint,
    "OCG_GetVersionExtra": ctypes.c_uint,
}


def _load_and_probe(dll: Path) -> dict:
    res: dict = {"loaded": False, "error": ""}
    try:
        lib = ctypes.CDLL(str(dll))
    except OSError as e:
        res["error"] = f"CDLL 加载失败：{e}"
        return res
    res["loaded"] = True
    versions: dict = {}
    for name, restype in _SAFE_GETTERS.items():
        f = getattr(lib, name, None)
        if f is None:
            continue
        try:
            f.restype = restype
            f.argtypes = []
            v = int(f())
            versions[name] = v if 0 <= v < 10 ** 9 else None
        except Exception as e:      # 记录而不是崩
            versions[name] = f"ERR:{e}"
    res["versions"] = versions
    res["symbols_present"] = {
        n: hasattr(lib, n) for n in (
            "OCG_CreateDuel", "OCG_StartDuel", "OCG_DuelProcess", "OCG_DuelGetMessage",
            "OCG_DuelSetResponse", "OCG_DuelPendingResponse", "OCG_DuelResult",
            "OCG_LoadScript", "OCG_LoadLocalScript", "OCG_RenameScript", "OCG_ClearScripts",
            "OCG_DuelNewCard", "OCG_DuelSetPlayerInfo", "OCG_SetPlayerInfo",
            "OCG_DuelQueryField", "OCG_DuelQueryCount", "OCG_DuelQueryLocation",
            "OCG_CardLoadCDB", "OCG_CardDataSet", "OCG_AddString", "OCG_GetStringCount",
            "OCG_CreateScriptBox", "OCG_DeleteScriptBox", "OCG_EnableProdMode",
            "OCG_SetProcessorFlag", "OCG_SetLogFunction", "OCG_DuelGetFieldChangesEnabled",
        )
    }
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ocgcore.dll 只读探测")
    ap.add_argument("--dll", default=str(DEFAULT_DLL))
    ap.add_argument("--out", default=str(OUT_DIR / "ocgcore_exports.json"))
    ap.add_argument("--duel", action="store_true", help="额外跑一局真实对战（需驱动已就绪）")
    ap.add_argument("--filter", default="OCG_")
    args = ap.parse_args(argv)

    dll = Path(args.dll)
    report: dict = {"python": sys.version, "platform": sys.platform, "dll": str(dll)}
    if not dll.exists():
        report["error"] = "DLL 不存在"
    else:
        report["size"] = dll.stat().st_size
        try:
            report["pe"] = _read_pe_exports(dll)
        except Exception as e:
            report["pe"] = {"error": f"PE 解析失败：{e}"}
        report["load"] = _load_and_probe(dll)

    if args.duel:
        try:
            sys.path.insert(0, str(ROOT))
            from cardforge.duel import bot as duel_bot  # type: ignore
            report["duel"] = duel_bot.selftest()
        except Exception as e:
            report["duel"] = {"error": f"{type(e).__name__}: {e}"}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台只打 ASCII，避免 GBK 编码问题
    pe = report.get("pe", {})
    names = [e["name"] for e in pe.get("exports", []) if e["name"].startswith(args.filter)]
    print(f"exports_total={pe.get('count', 0)} filtered={len(names)} out={out}")
    for line in _summary_lines(pe):
        print(line.encode("ascii", "replace").decode("ascii"))
    return 0


def _summary_lines(pe: dict) -> list[str]:
    exports = pe.get("exports", [])
    if not exports:
        return [f"pe-error={pe.get('error', 'no exports')}"]
    ocg = sorted(e["name"] for e in exports if e["name"].startswith("OCG_"))
    groups = {
        "duel_lifecycle": [n for n in ocg if n in (
            "OCG_CreateDuel", "OCG_StartDuel", "OCG_DuelProcess", "OCG_DuelResult",
            "OCG_DeleteDuel", "OCG_DuelPendingResponse", "OCG_DuelGetMessage",
            "OCG_DuelSetResponse", "OCG_Draw", "OCG_DuelChangeField")],
        "script": [n for n in ocg if "Script" in n],
        "card_data": [n for n in ocg if n.startswith("OCG_Card")],
        "query": [n for n in ocg if "Query" in n],
        "strings": [n for n in ocg if "String" in n or "Text" in n],
        "version": [n for n in ocg if "Version" in n],
    }
    lines = [f"ocg_symbols={len(ocg)}"]
    for k, v in groups.items():
        lines.append(f"{k}={len(v)}:{','.join(x[4:] for x in v)}")
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
