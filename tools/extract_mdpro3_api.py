#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract the MDPro3 client Lua API whitelist from Data/script.zip.

Reads the client script archive (three library files + all official card
scripts) directly from the zip (no extraction to disk) and emits a JSON
whitelist used by the CardForge exporter as a static cross-check gate:
generated scripts must not reference symbols the client does not know.

Usage (from repo root):
    python -X utf8 tools/extract_mdpro3_api.py
    python -X utf8 tools/extract_mdpro3_api.py --client-dir D:\\MyCardLibrary\\mdpro3 --out data\\mdpro3_api.json
"""

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CLIENT_DIR = r"D:\MyCardLibrary\mdpro3"
LIB_NAMES = ("script/constant.lua", "script/procedure.lua", "script/utility.lua")
CARD_RE = re.compile(r"^script/c\d+\.lua$")

# --- library definitions ---------------------------------------------------
# function <Name>.<name>( / function <Name>:<name>( ... (dotted or colon form)
RE_FUNC_DOTTED = re.compile(
    r"^[ \t]*(?:local[ \t]+)?function[ \t]+([A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)+)[ \t]*\(",
    re.M,
)
# top-level bare: function <name>(   (local function excluded)
RE_FUNC_BARE = re.compile(
    r"^[ \t]*function[ \t]+([A-Za-z_]\w*)[ \t]*\(",
    re.M,
)
# assigned ALL-CAPS identifier: NAME = ... / local NAME = ...
RE_CONST = re.compile(
    r"^[ \t]*(?:local[ \t]+)?([A-Z][0-9A-Z_]{2,})[ \t]*=(?!=)",
    re.M,
)
# assigned dotted form X.Y = ... -> keep the full dotted name
RE_CONST_DOTTLED = re.compile(
    r"^[ \t]*(?:local[ \t]+)?([A-Z][0-9A-Z_]{2,})\.([A-Za-z_]\w*)[ \t]*=(?!=)",
    re.M,
)
# alias assignment: aux=Auxiliary  (lowercase name = Uppercase table)
RE_ALIAS = re.compile(
    r"^[ \t]*([a-z_]\w*)[ \t]*=[ \t]*([A-Z][A-Za-z0-9_]*)[ \t]*$",
    re.M,
)
# first function definition marks the end of a lib file's "header"
RE_FIRST_FUNC = re.compile(r"^[ \t]*(?:local[ \t]+)?function[ \t]", re.M)

# --- official card script observations -------------------------------------
RE_CALL_DOTTED = re.compile(r"\b[A-Za-z_][\w.]*[.:]([A-Za-z_]\w*)[ \t]*\(")
RE_CALL_ANY = re.compile(r"[.:]([A-Za-z_]\w*)[ \t]*\(")
RE_UPPER_TOKEN = re.compile(r"\b[A-Z][0-9A-Z_]{3,}\b")


def read_text(zf: zipfile.ZipFile, name: str) -> str:
    """Read a zip member as text: UTF-8 first, GBK fallback with replacement."""
    raw = zf.read(name)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def lib_header(text: str) -> str:
    """Portion of a library file before its first function definition."""
    m = RE_FIRST_FUNC.search(text)
    return text[: m.start()] if m else text


def extract(client_dir: Path, out_path: Path) -> dict:
    zip_path = client_dir / "Data" / "script.zip"
    if not zip_path.is_file():
        sys.exit(f"error: script.zip not found: {zip_path}")

    zf = zipfile.ZipFile(zip_path, "r")
    names = zf.namelist()
    entry_count = len(names)

    # ---- libraries ----
    libs_info = {}
    defined_functions = set()
    defined_bare_functions = set()
    constants = set()
    aliases = {}
    lib_texts = {}

    for lib in LIB_NAMES:
        raw = zf.read(lib)
        text = read_text(zf, lib)
        lib_texts[lib] = text
        libs_info[lib] = {
            "sha1": hashlib.sha1(raw).hexdigest(),
            "bytes": len(raw),
        }
        # dotted function definitions, colon normalised to dot
        for m in RE_FUNC_DOTTED.finditer(text):
            defined_functions.add(m.group(1).replace(":", "."))
        for m in RE_FUNC_BARE.finditer(text):
            defined_bare_functions.add(m.group(1))
        for m in RE_ALIAS.finditer(text):
            alias, target = m.group(1), m.group(2)
            if alias != target:
                aliases.setdefault(alias, target)

    # constants: whole constant.lua + headers of the other two libs
    for m in RE_CONST.finditer(lib_texts["script/constant.lua"]):
        constants.add(m.group(1))
    for m in RE_CONST_DOTTLED.finditer(lib_texts["script/constant.lua"]):
        constants.add(f"{m.group(1)}.{m.group(2)}")
    for lib in ("script/procedure.lua", "script/utility.lua"):
        header = lib_header(lib_texts[lib])
        for m in RE_CONST.finditer(header):
            constants.add(m.group(1))
        for m in RE_CONST_DOTTLED.finditer(header):
            constants.add(f"{m.group(1)}.{m.group(2)}")

    # ---- official card scripts ----
    official_tokens = set()
    card_count = 0
    for name in names:
        if not CARD_RE.match(name):
            continue
        card_count += 1
        text = read_text(zf, name)
        for m in RE_CALL_DOTTED.finditer(text):
            official_tokens.add(m.group(1))
        for m in RE_CALL_ANY.finditer(text):
            official_tokens.add(m.group(1))
        for m in RE_UPPER_TOKEN.finditer(text):
            official_tokens.add(m.group(0))
    zf.close()

    return {
        "schema": "mdpro3-api-v1",
        "source": {
            "client_dir": str(client_dir),
            "entry_count": entry_count,
            "libs": libs_info,
            "extracted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "defined_functions": sorted(defined_functions),
        "defined_bare_functions": sorted(defined_bare_functions),
        "constants": sorted(constants),
        "official_tokens": sorted(official_tokens),
        "aliases": {k: aliases[k] for k in sorted(aliases)},
        "_card_scripts_scanned": card_count,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--client-dir", default=DEFAULT_CLIENT_DIR,
                    help=f"MDPro3 client root (default: {DEFAULT_CLIENT_DIR})")
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "mdpro3_api.json"),
                    help="output JSON path (default: <repo>/data/mdpro3_api.json)")
    args = ap.parse_args()

    out_path = Path(args.out)
    data = extract(Path(args.client_dir), out_path)
    card_count = data.pop("_card_scripts_scanned")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    size = out_path.stat().st_size
    print(f"scanned {card_count} card scripts, "
          f"{len(data['defined_functions'])} dotted fns, "
          f"{len(data['defined_bare_functions'])} bare fns, "
          f"{len(data['constants'])} constants, "
          f"{len(data['official_tokens'])} official tokens, "
          f"aliases={data['aliases']}")
    print(f"wrote {out_path} ({size} bytes)")


if __name__ == "__main__":
    main()
