"""从官方脚本库抽取 ocgcore Lua API 白名单。

为什么要抽而不是手写
--------------------
ocgcore 的 Lua API **没有公开发布的权威文档**（调研结论）。社区脚本库
``ProjectIgnis/CardScripts`` 里的 ``constant.lua`` 与 ``utility.lua`` 事实上就是
最权威的"存在哪些函数与常量"清单。本工具把它们解析成结构化 JSON，
供 ``content/lua/apicatalog.py`` 用于 G2 静态校验的 API 存在性检查。

用法::

    python tools/extract_lua_api.py                 # 用 vendor/scripts
    python tools/extract_lua_api.py --dir <路径>     # 指定脚本库
输出::

    data/lua_api.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "vendor" / "scripts"
OUT = ROOT / "data" / "lua_api.json"

# ── 解析规则 ──────────────────────────────────────────────────────────
# 1) Duel.XXX = ...（函数或表）  2) aux.XXX = function / aux.X = {...}
RE_ASSIGN = re.compile(r"^\s*(?:local\s+)?([A-Za-z_][\w.]*)\s*=\s*(.+?)\s*(?:--.*)?$")
RE_FUNC = re.compile(r"^\s*(?:local\s+)?function\s+([A-Za-z_][\w.:]*)")
RE_FUNC_ASSIGN = re.compile(r"^\s*(?:local\s+)?([A-Za-z_][\w.]*)\s*=\s*function\b")
RE_CONST = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\s*=\s*(0[xX][0-9a-fA-F]+|\d+)\s*(?:--.*)?$")
RE_EFFECT_CONST = re.compile(r"^\s*EFFECT_([A-Z0-9_]+)\s*=")
RE_CATEGORY = re.compile(r"^\s*CATEGORY_([A-Z0-9_]+)\s*=")
RE_HINT = re.compile(r"^\s*HINT([A-Z0-9_]*)\s*=")
RE_LOCATION = re.compile(r"^\s*LOCATION_([A-Z0-9_]+)\s*=")
RE_REASON = re.compile(r"^\s*REASON_([A-Z0-9_]+)\s*=")
RE_ATTRIBUTE = re.compile(r"^\s*ATTRIBUTE_([A-Z0-9_]+)\s*=")
RE_RACE = re.compile(r"^\s*RACE_([A-Z0-9_]+)\s*=")
RE_TYPE = re.compile(r"^\s*TYPE_([A-Z0-9_]+)\s*=")
RE_EVENT = re.compile(r"^\s*EVENT_([A-Z0-9_]+)\s*=")
RE_PHASE = re.compile(r"^\s*PHASE_([A-Z0-9_]+)\s*=")
RE_PLAYER = re.compile(r"^\s*PLAYER_([A-Z0-9_]+)\s*=")
RE_POS = re.compile(r"^\s*POS_([A-Z0-9_]+)\s*=")

#: aux.* 里被视为"公开可用"的前缀
AUX_OK_PREFIX = ("aux.", "Aux.")
#: 这些是脚本库内部实现细节，不该出现在用户脚本里
AUX_INTERNAL = ("aux.Stringid", "aux.RegisterClientHint")   # 例外：这两个是公开的


def parse_file(path: Path) -> dict:
    """解析单个 Lua 文件，返回函数名与常量名集合。"""
    funcs: set[str] = set()
    consts: set[str] = set()
    groups: dict[str, set[str]] = {
        "EFFECT_": set(), "CATEGORY_": set(), "HINT": set(), "LOCATION_": set(),
        "REASON_": set(), "ATTRIBUTE_": set(), "RACE_": set(), "TYPE_": set(),
        "EVENT_": set(), "PHASE_": set(), "PLAYER_": set(), "POS_": set(),
    }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e), "funcs": [], "consts": [], "groups": {}}

    for raw in text.splitlines():
        line = raw.split("--")[0] if not raw.strip().startswith("--") else ""
        if not line.strip():
            continue

        m = RE_FUNC.match(line) or RE_FUNC_ASSIGN.match(line) or RE_ASSIGN.match(line)
        if m:
            name = m.group(1)
            if "." in name or name in ("Duel", "aux", "Effect", "Group", "Card"):
                funcs.add(name)

        m = RE_CONST.match(line)
        if m:
            consts.add(m.group(1))

        for key, rx in (("EFFECT_", RE_EFFECT_CONST), ("CATEGORY_", RE_CATEGORY),
                        ("HINT", RE_HINT), ("LOCATION_", RE_LOCATION),
                        ("REASON_", RE_REASON), ("ATTRIBUTE_", RE_ATTRIBUTE),
                        ("RACE_", RE_RACE), ("TYPE_", RE_TYPE), ("EVENT_", RE_EVENT),
                        ("PHASE_", RE_PHASE), ("PLAYER_", RE_PLAYER), ("POS_", RE_POS)):
            mm = rx.match(line)
            if mm:
                groups[key].add((key if key != "HINT" else "HINT") + mm.group(1))

    return {
        "file": path.name,
        "funcs": sorted(funcs),
        "consts": sorted(consts),
        "groups": {k: sorted(v) for k, v in groups.items() if v},
    }


#: 从脚本库里"用到的" API 反向补充（比只解析声明更全）
RE_CALL = re.compile(r"\b(Duel\.[A-Za-z_]\w*|aux\.[A-Za-z_]\w*|Effect\.[A-Za-z_]\w*)")
# 采集任意 ``对象:方法(`` 形式。之前只列了固定的组变量名（c/g/eg/...），
# 漏掉了 ``e1:SetType(...)`` 这类 Effect 方法，导致 lint 把 SetType 报成未知方法。
RE_GROUP_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)\s*\(")
RE_CONST_USE = re.compile(r"\b(EFFECT_[A-Z0-9_]+|CATEGORY_[A-Z0-9_]+|HINT[A-Z0-9_]*|"
                          r"LOCATION_[A-Z0-9_]+|REASON_[A-Z0-9_]+|ATTRIBUTE_[A-Z0-9_]+|"
                          r"RACE_[A-Z0-9_]+|TYPE_[A-Z0-9_]+|EVENT_[A-Z0-9_]+|"
                          r"PHASE_[A-Z0-9_]+|PLAYER_[A-Z0-9_]+|POS_[A-Z0-9_]+)\b")


def harvest_usage(paths: list[Path], limit: int = 4000) -> dict:
    """从真实卡脚本里反向收集"实际被调用过"的 API 与常量（更强的存在性证据）。"""
    calls: set[str] = set()
    methods: set[str] = set()
    consts: set[str] = set()
    for i, p in enumerate(paths[:limit]):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        calls.update(RE_CALL.findall(text))
        for _, m in RE_GROUP_CALL.findall(text):
            methods.add(m)
        consts.update(RE_CONST_USE.findall(text))
    return {"calls": sorted(calls), "methods": sorted(methods), "consts": sorted(consts)}


def main() -> int:
    ap = argparse.ArgumentParser(description="抽取 ocgcore Lua API 白名单")
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="脚本库目录")
    ap.add_argument("--samples", type=int, default=3000, help="抽样多少张卡脚本做反向收集")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    d = Path(args.dir)
    if not d.exists():
        print(f"[X] 脚本库目录不存在：{d}")
        return 2

    core_files = [d / n for n in (
        "constant.lua", "utility.lua", "chain.lua", "cards_specific_functions.lua",
        "archetype_setcode_constants.lua", "card_counter_constants.lua",
        "deprecated_functions.lua", "debug_utility.lua",
    ) if (d / n).exists()]
    if not core_files:
        print(f"[X] 在 {d} 里没找到 constant.lua / utility.lua —— 这不是脚本库目录")
        return 2

    funcs: set[str] = set()
    consts: set[str] = set()
    groups: dict[str, set[str]] = {}
    per_file = []
    for f in core_files:
        r = parse_file(f)
        per_file.append({"file": r.get("file"), "n_funcs": len(r.get("funcs", [])),
                         "n_consts": len(r.get("consts", []))})
        funcs.update(r.get("funcs", []))
        consts.update(r.get("consts", []))
        for k, v in (r.get("groups") or {}).items():
            groups.setdefault(k, set()).update(v)

    # 反向收集：官方单卡脚本里真实出现过的 API
    samples: list[Path] = []
    for sub in ("official", "unofficial", "goat", "pre-errata", "skill", "rush",
                "pre-release", "samples"):
        p = d / sub
        if p.is_dir():
            samples.extend(sorted(p.glob("*.lua")))
    if not samples:
        samples = sorted(d.glob("*.lua"))
    # 核心库文件必须一起进语料：utility.lua 里定义了绝大多数 aux.*，
    # 只扫单卡脚本会漏掉大量辅助函数（实测 64 → 55）。
    samples = list(core_files) + samples
    usage = harvest_usage(samples, args.samples) if samples else {"calls": [], "methods": [], "consts": []}

    funcs.update(usage["calls"])
    consts.update(usage["consts"])
    # 只保留 aux./Aux. 前缀的 aux 函数（去掉内部实现细节）
    aux_funcs = {f for f in funcs if f.startswith(AUX_OK_PREFIX) or f in AUX_INTERNAL}

    data = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_dir": str(d),
        "source_files": [str(f.name) for f in core_files],
        "sampled_card_scripts": len(samples[:args.samples]),
        "counts": {
            "functions": len(funcs), "aux_functions": len(aux_funcs),
            "constants": len(consts), "card_methods": len(usage["methods"]),
        },
        "functions": sorted(funcs),
        "aux_functions": sorted(aux_funcs),
        "constants": sorted(consts),
        "card_methods": usage["methods"],
        "groups": {k: sorted(v) for k, v in sorted(groups.items())},
        "per_file": per_file,
    }

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"脚本库        : {d}")
    print(f"解析的核心文件: {', '.join(f.name for f in core_files)}")
    print(f"抽样的卡脚本  : {len(samples[:args.samples])} 个")
    print(f"函数          : {len(funcs)}（其中 aux.* {len(aux_funcs)}）")
    print(f"常量          : {len(consts)}")
    print(f"卡对象方法    : {len(usage['methods'])}")
    print(f"分组          : " + ", ".join(f"{k}={len(v)}" for k, v in sorted(groups.items())))
    print(f"\n输出 -> {outp}  ({outp.stat().st_size / 1024:.1f} KB)")
    print("\n样例：")
    print("  Duel.* :", [f for f in data["functions"] if f.startswith("Duel.")][:8])
    print("  aux.*  :", data["aux_functions"][:8])
    print("  methods:", data["card_methods"][:10])
    print("  EFFECT_:", data["groups"].get("EFFECT_", [])[:6])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
