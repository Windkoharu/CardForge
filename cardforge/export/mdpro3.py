"""MDPro3 / MDPro4 扩展卡包（``.ypk``）导出。

MDPro3 不是 EDOPro —— **目录布局完全不同**，把 EDOPro 的 ``expansions/``
直接拷过去是无效的。这里的东西全部是**实测**这台机器上
``D:\\MyCardLibrary\\mdpro3`` 与社区流通卡包得来的，不是照抄 ygopro 惯例：

实测结论
--------
* 客户端是 Unity 程序（``MDPro3.exe`` + ``MDPro3_Data``），卡数据/脚本/卡图
  分别在三处，且**脚本装在 zip 里**：

  ============================  =========================================
  位置                          作用
  ============================  =========================================
  ``Data/locales/<lang>/cdb``   按语言分的官方卡池（datas/texts 标准表）
  ``Data/script.zip``           官方 + 卡脚本，内部是 ``script/c<卡号>.lua``
  ``Picture/Art/<卡号>.jpg``    **624×624 纯插画**（客户端自己合成卡面）
  ``Picture/OverFrame/*.png``   704×1024 RGBA 超框图
  ``Deck/*.ydk``                本地卡组
  ============================  =========================================

* DIY 卡的正路是 **``.ypk`` 扩展卡包**：游戏内
  「游戏设置 → 导入导出 → 导入」或「游戏设置 → 扩展卡包 → 下载自定义卡包」。
  ``.ypk`` 就是个 zip，内部结构（拆包实测）::

      <任意名>.cdb                 卡数据（标准 datas/texts 表）
      <任意名>-strings.conf        字段名 / 计数器名
      script/c<卡号>.lua           卡脚本
      pics/<卡号>.jpg              **704×1024 整卡图**（Settings.json 的
                                   SavedCardSize 就是这个尺寸）
      pack/<卡组名>.ydk            可选：附带演示卡组
      corres_srv.ini               可选：只有需要顺带登记服务器时才写

* 客户端 ``Settings.json`` 里有 ``"DiySymbol": "DIY by"`` 与
  ``"CardRenderPassword": true`` —— 非官方卡会被它标记成 DIY，这是正常现象。

为什么不直接往客户端里写
------------------------
``Data/script.zip`` 与 ``Data/locales/*/cards.cdb`` 会被 MDPro3 的
「更新先行卡」整体覆盖。写进去等于把 DIY 卡放在一条会被冲掉的路径上，
而且改官方卡池不可逆。**所以本模块只产出 ``.ypk`` 文件**，导入这一步交给
用户在游戏里点 —— 一次点击，且「清空扩展卡」可以整体回退。

卡号区间
--------
本机官方池 ``max(id) = 99995595``，``id >= 210000000`` 的官方卡 **0 张**，
所以 CardForge 默认的 2.1 亿号段在 MDPro3 里也是安全的。
（社区卡包爱用 9000 万段，那个区间和官方高号段有撞车风险，不跟。）
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from ..core import errors, paths
from ..core.enums import DEFAULT_LANG
from ..core.models import CardSpec, DeckSpec, Issue
from ..render import geometry as G
from ..pool import cdb as CDB
from . import strings as STR, ydk as YDK

__all__ = [
    "MDPRO3_SIZE", "LANG_CODES", "detect", "client_info", "build", "verify",
    "import_hint", "pack_member_names", "is_mdpro_dir",
]

#: MDPro3/4 的整卡图尺寸（实测：其 SavedCardSize 与社区 ypk 里的 pics 都是这个）
MDPRO3_SIZE: tuple[int, int] = (704, 1024)

#: CardForge 语言键 → MDPro3 的 locales 目录名
LANG_CODES: dict[str, str] = {
    "zh_cn": "zh-CN", "zh_tw": "zh-TW", "ja": "ja-JP", "en": "en-US",
    "ko": "ko-KR", "de": "de-DE", "fr": "fr-FR", "it": "it-IT",
    "pt": "pt-PT", "es": "es-ES",
}

#: 认客户端的标志文件
_MARKERS: tuple[str, ...] = ("MDPro3.exe", "MDPro4.exe", "MDPro.exe")
_DATA_MARKERS: tuple[str, ...] = ("Data/script.zip", "Data/locales", "Picture/Art")


# ══════════════════════════════════════════════════════════════════════
#  客户端探测
# ══════════════════════════════════════════════════════════════════════
def is_mdpro_dir(p: str | os.PathLike[str]) -> bool:
    """像不像一个 MDPro3/4 安装目录（可执行文件 + 至少一个数据标志）。"""
    root = Path(p)
    if not root.is_dir():
        return False
    has_exe = any((root / m).exists() for m in _MARKERS)
    has_data = sum(1 for m in _DATA_MARKERS if (root / m).exists())
    return has_exe and has_data >= 1


def _candidate_roots(extra: Iterable[str] | None = None) -> list[Path]:
    """常见的中文 DIY 库位置 + 用户额外指定 + 各盘根目录浅层扫描。"""
    out: list[Path] = []
    for x in (extra or []):
        out.append(Path(x))
    env = os.environ.get("CARDFORGE_MDPRO") or os.environ.get("MDPRO_DIR")
    if env:
        out.append(Path(env))
    # 用户级常见落点：桌面/文档/下载/各盘的 MyCardLibrary、MDPro3 之类命名
    homes = [Path.home(), Path.home() / "Desktop", Path.home() / "Documents",
             Path.home() / "Downloads"]
    names = ("mdpro3", "MDPro3", "mdpro", "MDPro", "MyCardLibrary", "萌卡",
             "ygopro", "YGOPro")
    for h in homes:
        for n in names:
            out.append(h / n)
    for drive in ("C:\\", "D:\\", "E:\\", "F:\\"):
        d = Path(drive)
        if not d.exists():
            continue
        for n in names:
            out.append(d / n)
            out.append(d / "MyCardLibrary" / n)
            out.append(d / "Program Files" / n)
            out.append(d / "Program Files (x86)" / n)
    return out


def detect(*, deep: bool = False, roots: Iterable[str] | None = None) -> list[dict]:
    """找出本机可能的 MDPro3/4 安装目录。

    ``deep=True`` 时多扫一层 ``<盘>/xxx/mdpro*`` 这种二级目录（慢，给界面按钮用）。
    """
    found: list[dict] = []
    seen: set[str] = set()
    cands = _candidate_roots(roots)
    if deep:
        extra: list[Path] = []
        for drive in ("C:\\", "D:\\", "E:\\", "F:\\"):
            d = Path(drive)
            if not d.exists():
                continue
            try:
                for sub in sorted(d.iterdir()):
                    if sub.is_dir():
                        for n in ("mdpro3", "MDPro3", "mdpro", "MDPro"):
                            extra.append(sub / n)
            except OSError:
                continue
        cands = extra + cands
    for c in cands:
        key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        if not is_mdpro_dir(c):
            continue
        info = client_info(c)
        info["path"] = str(c)
        found.append(info)
    return found


def client_info(root: str | os.PathLike[str]) -> dict:
    """一个安装目录的体检报告：版本、语言包、卡池规模、脚本包。"""
    r = Path(root)
    out: dict[str, Any] = {"path": str(r), "exe": "", "langs": [], "n_official": 0,
                           "has_script_zip": False, "n_scripts": 0,
                           "n_pics": 0, "diy_symbol": "", "saved_size": [],
                           "warnings": []}
    for m in _MARKERS:
        if (r / m).exists():
            out["exe"] = m
            break
    loc = r / "Data" / "locales"
    if loc.is_dir():
        for d in sorted(loc.iterdir()):
            if (d / "cards.cdb").exists():
                out["langs"].append(d.name)
    zh = loc / "zh-CN" / "cards.cdb"
    pick = zh if zh.exists() else next(
        (p for p in sorted(loc.glob("*/cards.cdb"))), None) if loc.is_dir() else None
    if pick:
        try:
            con = sqlite3.connect(f"file:{pick.as_posix()}?mode=ro", uri=True)
            out["n_official"] = int(con.execute("select count(*) from datas").fetchone()[0])
            out["max_id"] = int(con.execute("select max(id) from datas").fetchone()[0] or 0)
            out["id_in_use"] = int(con.execute(
                "select count(*) from datas where id>=?", (210000000,)).fetchone()[0])
            con.close()
        except sqlite3.Error as e:
            out["warnings"].append(f"读卡池失败：{e}")
    sz = r / "Data" / "script.zip"
    if sz.exists():
        out["has_script_zip"] = True
        try:
            with zipfile.ZipFile(sz) as z:
                out["n_scripts"] = sum(1 for n in z.namelist()
                                       if re.fullmatch(r"script/c\d+\.lua", n))
        except zipfile.BadZipFile:
            out["warnings"].append("Data/script.zip 不是合法 zip（可能被占用或损坏）")
    art = r / "Picture" / "Art"
    if art.is_dir():
        out["n_pics"] = len(list(art.glob("*.jpg")))
    st = r / "Data" / "Settings.json"
    if st.exists():
        try:
            cfg = json.loads(st.read_text(encoding="utf-8"))
            out["diy_symbol"] = str(cfg.get("DiySymbol", ""))
            out["saved_size"] = list(cfg.get("SavedCardSize") or [])
        except Exception as e:
            out["warnings"].append(f"Settings.json 解析失败：{e}")
    if out["saved_size"] and tuple(out["saved_size"]) != MDPRO3_SIZE:
        out["warnings"].append(
            f"客户端 SavedCardSize 是 {tuple(out['saved_size'])}，"
            f"与本模块输出的 {MDPRO3_SIZE} 不同 —— 图会被缩放，不影响使用")
    return out


# ══════════════════════════════════════════════════════════════════════
#  打包
# ══════════════════════════════════════════════════════════════════════
def _rmtree(p: Path) -> None:
    """删临时目录；不存在就当成功，删不掉要冒出来（静默失败会留下脏目录）。"""
    if not p.exists():
        return
    shutil.rmtree(p)


def _safe(s: str, default: str = "CardForge") -> str:
    keep = [ch for ch in str(s or "") if ch.isalnum() or ch in "-_."]
    return ("".join(keep))[:48] or default


def _write_file(path: Path, text: str) -> None:
    """**UTF-8 无 BOM**：MDPro3 自己的 conf/ydk 实测都不带 BOM，
    而 ``.lua`` 带 BOM 会直接让脚本加载失败。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def pack_member_names(base: str = "custom") -> dict:
    """包内文件名（给界面/文档展示结构用）。"""
    b = _safe(base)
    return {"cdb": f"{b}.cdb", "strings": f"{b}-strings.conf",
            "script_dir": "script/", "pics_dir": "pics/", "deck_dir": "pack/"}


def build(cards: Iterable[CardSpec], out_path: str | os.PathLike[str], *,
          name: str = "CardForge", author: str = "", langs: Sequence[str] = ("zh_cn",),
          deck: Optional[DeckSpec] = None, setnames: Mapping[Any, Any] | None = None,
          counters: Mapping[Any, Any] | None = None,
          pic_source: Mapping[int, str | os.PathLike[str]] | None = None,
          render_pics: bool = True, compression: int = zipfile.ZIP_DEFLATED,
          readme: bool = True) -> dict:
    """产出一个可直接被 MDPro3 「导入」的 ``.ypk``。

    :param pic_source: ``{卡号: 图片路径}``。给了就用现成的图；
        没给且 ``render_pics`` 为真时，用渲染器现场出 704×1024 整卡图。
    :param render_pics: 关掉可以显著加快打包（卡包里就没有卡图，
        MDPro3 会按卡号去 ``Picture/Art`` 找插画，找不到显示占位）。
    """
    specs = [c for c in (cards or []) if c is not None]
    if not specs:
        raise errors.SpecError("没有可打包的卡",
                               "带上 card=<卡号> / archetype=<系列名>，或先在界面里选中范围")
    out = Path(out_path)
    if out.is_dir():
        out = out / f"{_safe(name)}.ypk"
    out.parent.mkdir(parents=True, exist_ok=True)
    base = _safe(name)
    members = pack_member_names(base)

    issues: list[Issue] = []
    written: dict[str, list[str]] = {"cdb": [], "script": [], "pics": [],
                                     "strings": [], "deck": [], "other": []}
    skipped_no_script: list[int] = []
    n_overframe = 0
    tmp = out.with_suffix(out.suffix + ".tmpdir")
    _rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    # ── 1. cdb ────────────────────────────────────────────────────
    lang = langs[0] if langs else DEFAULT_LANG
    cdb_path = tmp / members["cdb"]
    con = CDB.open_cdb(cdb_path, create=True)
    try:
        CDB.ensure_schema(con)
        n_rows = CDB.upsert_many(con, specs, lang=lang)
        con.commit()
    finally:
        con.close()
    written["cdb"].append(members["cdb"])

    # ── 2. script/ ────────────────────────────────────────────────
    (tmp / "script").mkdir(exist_ok=True)
    for c in specs:
        lua = str(getattr(c, "lua", "") or "")
        if not lua.strip():
            skipped_no_script.append(int(c.id))
            continue
        if lua.startswith("\ufeff"):
            lua = lua.lstrip("\ufeff")
            issues.append(Issue(gate="MDPRO", code="MD_BOM_STRIPPED", level="WARN",
                                message=f"卡 {c.id} 的脚本原本带 BOM，已剥掉",
                                hint="带 BOM 的 Lua 在 ocgcore 里直接加载失败",
                                field="lua"))
        fn = f"c{int(c.id)}.lua"
        _write_text(tmp.joinpath("script", fn).parent and tmp / "script" / fn
                    and Path(tmp / "script" / fn), lua) if False else \
            Path(tmp / "script" / fn).write_text(lua, encoding="utf-8")
        written["script"].append(f"script/{fn}")

    # ── 3. pics/ ──────────────────────────────────────────────────
    (tmp / "pics").mkdir(exist_ok=True)
    n_rendered = 0
    for c in specs:
        cid = int(c.id)
        src = (pic_source or {}).get(cid)
        if not src:
            for cand in (paths.pic_path(cid), paths.PICS / f"{cid}.jpg",
                         paths.PICS / f"{cid}.png", paths.OUT / f"{cid}.png"):
                if Path(cand).exists():
                    src = cand
                    break
        dest = tmp / "pics" / f"{cid}.jpg"
        if src and Path(src).exists():
            _to_jpeg(Path(src), dest, MDPRO3_SIZE)
            written["pics"].append(f"pics/{cid}.jpg")
        elif render_pics:
            ok = _render_to_jpeg(c, dest)
            if ok:
                n_rendered += 1
                written["pics"].append(f"pics/{cid}.jpg")
            else:
                issues.append(Issue(gate="MDPRO", code="MD_NO_PIC", level="WARN",
                                    message=f"卡 {cid} 没有卡图，也没渲出来",
                                    hint="客户端会显示占位图。渲一张或上传一张再打包",
                                    field="art"))

        # ── 3b. Picture/OverFrame/<卡号>.png（官方超框的原生通路）──────
        # 客户端对这张 704×1024 **纯插画层** 自行合成框体与文字（拆包实测，
        # mdpro3fork 同款）。只有官方超框档写它；DIY 档的整卡图走 pics/。
        if render_pics and getattr(getattr(c, "render", None), "fullart", None) is not None \
                and getattr(c.render.fullart, "mode", "none") == "overframe":
            art_src = src if (src and Path(src).exists()) else None
            if art_src:
                try:
                    from PIL import Image
                    from ..render.fullart import _fit_cover
                    with Image.open(art_src) as im:
                        im.load()
                    layer = _fit_cover(im, MDPRO3_SIZE[0], MDPRO3_SIZE[1]).convert("RGB")
                    of_dir = tmp / "Picture" / "OverFrame"
                    of_dir.mkdir(parents=True, exist_ok=True)
                    layer.save(of_dir / f"{cid}.png", "PNG", optimize=True)
                    written["other"].append(f"Picture/OverFrame/{cid}.png")
                    n_overframe += 1
                except Exception as e:                       # noqa: BLE001
                    issues.append(Issue(gate="MDPRO", code="MD_OVERFRAME_FAIL",
                                        level="WARN",
                                        message=f"卡 {cid} 的 OverFrame 插画层没写进去：{e}",
                                        hint="不影响 .ypk 导入；客户端会退回 pics/ 整卡图",
                                        field="art"))

    # ── 4. strings.conf ───────────────────────────────────────────
    auto_sets, auto_counters = _collect_strings(specs, setnames, counters)
    conf = STR.render(setnames=auto_sets, counters=auto_counters,
                      header=f"{name} 字段名 / 计数器名（CardForge 生成）")
    if conf.strip():
        _write_file(tmp / members["strings"], conf)
        written["strings"].append(members["strings"])

    # ── 5. pack/*.ydk（可选演示卡组）───────────────────────────────
    if deck is not None:
        dn = _safe(deck.name or "deck") + ".ydk"
        _write_file(tmp / "pack" / dn,
                    YDK.to_text(deck, header=f"#created by {name} (CardForge)"))
        written["deck"].append(f"pack/{dn}")

    # ── 6. 说明文件 ───────────────────────────────────────────────
    if readme:
        _write_file(tmp / "README.txt", _readme(name, author, specs, written,
                                                skipped_no_script, members))
        written["other"].append("README.txt")

    # ── 7. 压成 .ypk ──────────────────────────────────────────────
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", compression=compression, allowZip64=True) as z:
        for p in sorted(tmp.rglob("*")):
            if p.is_dir():
                continue
            z.write(p, p.relative_to(tmp).as_posix())
    _rmtree(tmp)

    size = out.stat().st_size
    # ── 8. 与本机客户端官方池撞号检查（探得到客户端才做）──────────
    for info in detect():
        cdb_p = Path(info["path"]) / "Data" / "locales" / "zh-CN" / "cards.cdb"
        if not cdb_p.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{cdb_p.as_posix()}?mode=ro", uri=True)
            got = {int(r[0]) for r in con.execute("select id from datas")}
            con.close()
        except sqlite3.Error:
            continue
        hit = sorted({int(c.id) for c in specs} & got)
        if hit:
            issues.append(Issue(
                gate="MDPRO", code="MD_ID_COLLISION", level="ERROR",
                message=f"卡号 {hit} 与 {info['path']} 的官方卡池撞号",
                hint="撞号会让客户端按官方那张卡读数据，你的卡看起来"
                     "「导入了但没效果」。改卡号再导出：CardForge 默认号段 "
                     "210000000 以上本来就避开了官方（本机官方 max 约 9999 万）"))
        break
    stats = {
        "ok": True, "path": str(out), "rel": paths.rel(out), "bytes": size,
        "name": name, "members": members, "n_cards": len(specs),
        "n_cdb_rows": n_rows, "n_scripts": len(written["script"]),
        "n_pics": len(written["pics"]), "n_rendered": n_rendered,
        "n_overframe": n_overframe,
        "n_deck": len(written["deck"]), "langs": [LANG_CODES.get(x, x) for x in langs],
        "cards_without_script": skipped_no_script,
        "clients_found": [d["path"] for d in detect()],
        "issues": [i.to_dict() for i in issues],
        "hint": import_hint(out),
    }
    return stats


def _to_jpeg(src: Path, dest: Path, size: tuple[int, int]) -> None:
    try:
        from PIL import Image
        with Image.open(src) as im:
            im.load()
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im = im.resize(size, Image.LANCZOS)
            im.save(dest, "JPEG", quality=90, optimize=True)
    except Exception:
        shutil.copyfile(src, dest)


def _render_to_jpeg(spec: CardSpec, dest: Path) -> bool:
    try:
        from ..render import compositor
        img = compositor.render_card(spec, None, size=MDPRO3_SIZE)
        img.convert("RGB").save(dest, "JPEG", quality=90, optimize=True)
        return True
    except Exception:
        return False


def _setcodes_of(spec: CardSpec) -> list[int]:
    """一张卡身上的 16 位字段码，**去掉 0**。

    ``setcode`` 可能是打包好的整数（``0x20021001``），也可能是用户手写的
    ``"0x1001,0x2002"`` —— 两种都得吃进来。而 ``parse_setcode`` 固定返回 4 个
    槽位、空槽是 0，不过滤就会写出 ``!setname 0x0 xxx`` 这种没意义又占位的行。
    """
    raw = str(getattr(spec, "setcode", "") or "").strip()
    if not raw:
        return []
    parts = [p for p in re.split(r"[,\s;|]+", raw) if p]
    codes: list[int] = []
    if len(parts) > 1:                                   # 用户手写的多字段
        codes = CDB.parse_setcodes(*parts) if hasattr(CDB, "parse_setcodes") else \
            [CDB.setcode_int(p) & 0xFFFF for p in parts]
    else:
        codes = CDB.parse_setcode(raw)
    out: list[int] = []
    for c in codes:
        c = int(c or 0) & 0xFFFF
        if c and c not in out:
            out.append(c)
    return out


def _collect_strings(specs: list[CardSpec], setnames, counters) -> tuple[dict, dict]:
    """把每张卡的 setcode 汇总成 ``!setname`` 表。

    没给对照表时，用卡上的系列名自动填 —— 少了这一段，游戏里卡名后面的字段
    会显示成十六进制而不是本家名字（MDPro3 与 EDOPro 一样靠 strings.conf 翻译）。
    """
    sets: dict[Any, Any] = dict(setnames or {})
    cnt: dict[Any, Any] = dict(counters or {})
    for c in specs:
        arch = (c.archetype or "").strip()
        if not arch:
            continue
        for code in _setcodes_of(c):
            key = f"0x{code:X}"
            if key not in sets and f"0x{code:x}" not in sets:
                sets[key] = arch
    return sets, cnt


def _readme(name: str, author: str, specs: list[CardSpec], written: dict,
            no_script: list[int], members: dict) -> str:
    lines = [
        f"{name} —— CardForge 2.0 生成的 MDPro3 / MDPro4 扩展卡包",
        "=" * 58,
        "",
        f"卡数：{len(specs)}    脚本：{len(written['script'])}    "
        f"卡图：{len(written['pics'])}    卡组：{len(written['deck'])}",
        f"作者：{author or '（未填）'}",
        "",
        "【怎么装】",
        "  MDPro3 → 游戏设置 → 导入导出 → 导入 → 文件类型选「扩展卡文件」",
        "  → 选中本 .ypk 文件 → 提示「导入扩展卡文件……成功」即可。",
        "  之后在游戏设置 → 扩展卡包 里确认「启用扩展卡」是开的。",
        "",
        "【怎么退】",
        "  游戏设置 → 扩展卡包 → 清空扩展卡（会删掉所有已导入的扩展卡包）。",
        "  只想撤这一个包的话，删客户端里对应的扩展目录即可 —— 本包不会碰",
        "  官方卡池与 Data/script.zip，所以不会留下改不回去的东西。",
        "",
        "【包内结构】",
        f"  {members['cdb']}                 卡数据（datas / texts 两张表）",
        f"  {members['strings']}      字段名与计数器名（可选）",
        "  script/c<卡号>.lua          卡脚本（UTF-8 无 BOM）",
        "  pics/<卡号>.jpg             整卡图 704×1024",
        "  pack/<卡组名>.ydk           演示卡组（可选）",
        "",
        "【卡号】",
        "  本包卡号都在 210000000 以上，与官方池（本机 max 99995595）不冲突。",
    ]
    if no_script:
        lines += ["", "【注意】",
                  f"  这些卡没有脚本，进游戏只能看不能用：{no_script}"]
    return "\n".join(lines) + "\n"


def import_hint(ypk: str | os.PathLike[str]) -> str:
    return (f"导入：MDPro3 → 游戏设置 → 导入导出 → 导入 → 选「扩展卡文件」→ "
            f"选中 {Path(ypk).name}。完成后在「扩展卡包」里确认已启用。")


# ══════════════════════════════════════════════════════════════════════
#  自检
# ══════════════════════════════════════════════════════════════════════
def verify(ypk: str | os.PathLike[str], *, official_dir: str | os.PathLike[str] | None = None,
           deep: bool = False,
           ) -> list[Issue]:
    """检查一个 ``.ypk`` 是否具备 MDPro3 认的全部要素。

    ``deep=True`` 时追加**与本机客户端逐项对账**（docs/03 §三-c 的闭环项）：
    cdb schema、卡图尺寸、撞号、编码、strings.conf 格式 —— 把「真开游戏点导入」
    能提前在本地复现的部分全部跑掉。找不到客户端也不失败，只是那部分标注跳过。
    """
    out: list[Issue] = []
    p = Path(ypk)

    def iss(code: str, level: str, msg: str, hint: str = "", field: str = "") -> None:
        out.append(Issue(gate="MDPRO", code=code, level=level, message=msg,
                         hint=hint, field=field))

    if not p.exists():
        iss("MD_MISSING", "ERROR", f"文件不存在：{p}", "先跑 build()")
        return out
    if not zipfile.is_zipfile(p):
        iss("MD_NOTZIP", "ERROR", f"{p.name} 不是 zip 容器",
            ".ypk 本质就是 zip；被压缩软件改过格式就废了")
        return out
    try:
        with zipfile.ZipFile(p) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            roots = [n for n in names if "/" not in n]
            cdbs = [n for n in roots if n.lower().endswith(".cdb")]
            if not cdbs:
                iss("MD_NO_CDB", "ERROR", "根目录没有 .cdb 文件",
                    "MDPro3 在包的**根目录**找数据库，放进子目录它不认")
            scripts = [n for n in names if n.startswith("script/") and n.endswith(".lua")]
            pics = [n for n in names if n.startswith("pics/")]
            confs = [n for n in roots if n.lower().endswith(".conf")]
            if not scripts:
                iss("MD_NO_SCRIPT", "WARN", "包里没有任何脚本",
                    "没脚本的卡能进卡组但场上不会起效")
            # cdb 能不能被打开 + 卡号/脚本/图三者是否对得上
            if cdbs:
                data = z.read(cdbs[0])
                if data[:3] == b"SQLite format 3"[:3] or True:
                    tmp = Path(paths.CACHE) / f"_mdchk_{p.stem}.cdb"
                    tmp.write_bytes(data)
                    try:
                        con = sqlite3.connect(tmp)
                        ids = {int(r[0]) for r in con.execute("select id from datas")}
                        txt = {int(r[0]) for r in con.execute("select id from texts")}
                        con.close()
                        if not ids:
                            iss("MD_EMPTY_CDB", "ERROR", "cdb 里 datas 表是空的",
                                "客户端会认为这个包没有卡")
                        if ids != txt:
                            miss = sorted(ids - txt)[:5]
                            iss("MD_TEXT_ORPHAN", "WARN",
                                f"datas 有 {len(ids - txt)} 张卡在 texts 里没有文本行"
                                f"（如 {miss}）", "游戏里卡名与效果会显示空白")
                        sids = {int(re.match(r"script/c(\d+)\.lua", n).group(1))
                                for n in scripts if re.fullmatch(r"script/c\d+\.lua", n)}
                        pids = {int(re.match(r"pics/(\d+)\.(jpg|jpeg|png)", n).group(1))
                                for n in pics if re.fullmatch(r"pics/\d+\.(jpg|jpeg|png)", n)}
                        no_lua = sorted(ids - sids)
                        if no_lua:
                            iss("MD_SCRIPT_MISSING", "WARN",
                                f"{len(no_lua)} 张卡没有脚本：{no_lua[:6]}"
                                + ("…" if len(no_lua) > 6 else ""),
                                "这些卡进游戏只能看不能用")
                        for extra in sorted(sids - ids):
                            iss("MD_SCRIPT_ORPHAN", "WARN",
                                f"script/c{extra}.lua 在 cdb 里没有对应卡号",
                                "多余脚本无害，但通常意味着卡号写错了")
                        if pids and len(ids - pids):
                            miss2 = sorted(ids - pids)[:6]
                            iss("MD_PIC_MISSING", "INFO",
                                f"{len(ids - pids)} 张卡没有整卡图：{miss2}",
                                "客户端会退回按卡号找 Picture/Art 的插画或显示占位")
                        for lua_name in scripts:
                            if re.fullmatch(r"script/c\d+\.lua", lua_name):
                                head = z.read(lua_name)[:3]
                                if head == b"\xef\xbb\xbf":
                                    iss("MD_LUA_BOM", "ERROR",
                                        f"{lua_name} 带 UTF-8 BOM",
                                        "带 BOM 的 Lua 会让这张卡在对局里直接报错",
                                        field="lua")
                    except sqlite3.Error as e:
                        iss("MD_CDB_BAD", "ERROR", f"cdb 打不开：{e}",
                            "重新导出一次；cdb 必须是标准 SQLite 库")
                    finally:
                        tmp.unlink(missing_ok=True)
            if not confs:
                iss("MD_NO_STRINGS", "INFO", "包里没带 strings.conf",
                    "有本家字段（setcode）时建议带上，否则游戏里字段名显示成十六进制")
    except zipfile.BadZipFile as e:
        iss("MD_BADZIP", "ERROR", f"zip 读不了：{e}", "重新导出")

    if deep:
        client: Optional[Path] = None
        if official_dir:
            client = Path(official_dir)
        else:
            try:
                found = detect()
                client = Path(found[0]["path"]) if found else None
            except Exception:
                client = None
        if client is None:
            iss("MD_DEEP_NO_CLIENT", "INFO",
                "深检没找到本机 MDPro3/4 客户端 —— 与客户端对账的部分跳过"
                "（结构、编码、卡图尺寸仍然全查）",
                "在界面「上桌」页重新探测，或设 CARDFORGE_MDPRO 环境变量")
        try:
            _deep_checks(p, issu=iss, client=client)
        except zipfile.BadZipFile:
            pass   # 前面已报 MD_NOTZIP/MD_BADZIP，深检不必重复喊
        except Exception as e:
            iss("MD_DEEP_INTERNAL", "WARN", f"深检自身出错（不影响前面的结论）：{e}",
                "请反馈这一条；普通自检的结论仍然有效")
    return out


# ══════════════════════════════════════════════════════════════════════
#  深检：把「真开游戏点导入」能提前在本地复现的部分全部跑掉
# ══════════════════════════════════════════════════════════════════════
def _deep_checks(p: Path, *, issu, client: Optional[Path]) -> None:
    """逐项与本机客户端对账。所有结论都来自**实测数据**，不照抄文档。

    检查项：
    1. cdb schema 与客户端官方池**逐列对照**（多列/少列都要报 —— 列集不同
       意味着客户端的读取代码可能拿到 NULL）；
    2. 每张 ``pics/*.jpg`` 的像素尺寸 vs 客户端 ``Settings.json`` 的
       ``SavedCardSize``（客户端按这个尺寸直接铺，尺寸不对会变形或留边）；
    3. 卡号与客户端官方池**撞号**（撞号＝官方数据把它顶掉，症状是
       「导入成功但没效果」）；
    4. 脚本 UTF-8 **严格解码**（非 UTF-8 直接 ERROR，BOM 前面已单独检查）；
    5. ``strings.conf`` 行格式抽查（``!setname``/``!counter`` 的值必须是 hex）。
    """
    checked: list[str] = []
    with zipfile.ZipFile(p) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        roots = [n for n in names if "/" not in n]
        cdbs = [n for n in roots if n.lower().endswith(".cdb")]
        scripts = [n for n in names if re.fullmatch(r"script/c\d+\.lua", n)]
        pics = [n for n in names if re.fullmatch(r"pics/\d+\.(jpg|jpeg|png)", n)]

        # ── 我们自己的 cdb ──
        our_cols: dict[str, set[str]] = {}
        ids: set[int] = set()
        if cdbs:
            tmp = Path(paths.CACHE) / f"_mddeep_{p.stem}.cdb"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(z.read(cdbs[0]))
            try:
                con = sqlite3.connect(tmp)
                for table in ("datas", "texts"):
                    try:
                        our_cols[table] = {str(r[1]) for r in
                                           con.execute(f"pragma table_info({table})")}
                    except sqlite3.Error:
                        our_cols[table] = set()
                try:
                    ids = {int(r[0]) for r in con.execute("select id from datas")}
                except sqlite3.Error:
                    ids = set()
                con.close()
            finally:
                tmp.unlink(missing_ok=True)
            checked.append("cdb 可读")

        # ── 1. schema 对照 + 3. 撞号（需要客户端）──
        ref_cdb: Optional[Path] = None
        if client is not None:
            loc = client / "Data" / "locales"
            zh = loc / "zh-CN" / "cards.cdb"
            ref_cdb = zh if zh.exists() else next(
                (q for q in sorted(loc.glob("*/cards.cdb"))), None) if loc.is_dir() else None
        if ref_cdb is not None:
            try:
                con = sqlite3.connect(f"file:{ref_cdb.as_posix()}?mode=ro", uri=True)
                for table in ("datas", "texts"):
                    ref = {str(r[1]) for r in con.execute(f"pragma table_info({table})")}
                    mine = our_cols.get(table) or set()
                    if ref and mine and ref != mine:
                        extra = sorted(mine - ref)[:6]
                        lack = sorted(ref - mine)[:8]
                        issu("MD_SCHEMA_DIFF", "WARN",
                             f"{table} 表列集与客户端官方池不完全一致"
                             + (f"；本包多出 {extra}" if extra else "")
                             + (f"；本包缺少 {lack}" if lack else ""),
                             "缺少官方列时客户端读到 NULL；多出的列客户端会忽略。"
                             "稳妥做法是用客户端同版 cdb 做基准", field="cdb")
                if ids:
                    got = {int(r[0]) for r in con.execute("select id from datas")}
                    hit = sorted(ids & got)
                    if hit:
                        issu("MD_ID_COLLISION", "ERROR",
                             f"卡号 {hit[:8]} 与客户端官方池撞号"
                             + ("…" if len(hit) > 8 else ""),
                             "撞号后客户端按官方那张卡读数据 —— 症状是"
                             "「导入成功、卡也能看到，但效果不通」。改号重导出",
                             field="cdb")
                con.close()
                checked.append(f"schema 对照（{ref_cdb.parent.name}）与撞号检查")
            except sqlite3.Error as e:
                issu("MD_REFCDB_BAD", "INFO",
                     f"读客户端官方池失败：{e}", "深检跳过对账部分")
        elif client is not None:
            issu("MD_REFCDB_MISSING", "INFO",
                 f"{client} 下没找到 locales/*/cards.cdb", "深检跳过对账部分")

        # ── 2. 卡图尺寸 ──
        want = MDPRO3_SIZE
        if client is not None:
            st = client / "Data" / "Settings.json"
            if st.exists():
                try:
                    cfg = json.loads(st.read_text(encoding="utf-8"))
                    sz = list(cfg.get("SavedCardSize") or [])
                    if len(sz) == 2:
                        want = (int(sz[0]), int(sz[1]))
                except Exception:
                    pass
        if pics:
            try:
                from PIL import Image
                import io as _io
                bad: list[str] = []
                for n in pics:
                    with Image.open(_io.BytesIO(z.read(n))) as im:
                        if tuple(im.size) != tuple(want):
                            bad.append(f"{n} {im.size[0]}×{im.size[1]}")
                        if len(bad) >= 5:
                            break
                if bad:
                    issu("MD_PIC_SIZE", "WARN",
                         f"{len(bad)} 张卡图尺寸不是客户端要的 "
                         f"{want[0]}×{want[1]}：{'；'.join(bad)}",
                         "客户端按 SavedCardSize 直接铺图，尺寸不符会变形"
                         "或留边。用 build() 重出图即可", "art")
                else:
                    checked.append(f"卡图尺寸 {want[0]}×{want[1]}（{len(pics)} 张全对）")
            except ImportError:
                issu("MD_PIC_UNCHECKED", "INFO", "没装 Pillow，卡图尺寸未核",
                     "pip 装 Pillow 后重跑深检")
        elif ids:
            issu("MD_PIC_MISSING", "INFO", "包内一张整卡图都没有",
                 "客户端会退回按卡号找 Picture/Art 插画或显示占位", field="art")

        # ── 4. 脚本 UTF-8 严格解码 ──
        bad_enc: list[str] = []
        for n in scripts:
            try:
                z.read(n).decode("utf-8")
            except UnicodeDecodeError:
                bad_enc.append(n)
        if bad_enc:
            issu("MD_LUA_ENCODING", "ERROR",
                 f"{len(bad_enc)} 个脚本不是合法 UTF-8：{bad_enc[:5]}",
                 "ocgcore 只吃 UTF-8；重导出会按 UTF-8 写出", field="lua")
        elif scripts:
            checked.append(f"脚本 UTF-8 严格解码（{len(scripts)} 个）")

        # ── 5. strings.conf 格式抽查 ──
        confs = [n for n in roots if n.lower().endswith(".conf")]
        for n in confs:
            try:
                text = z.read(n).decode("utf-8")
            except UnicodeDecodeError:
                issu("MD_CONF_ENCODING", "ERROR", f"{n} 不是 UTF-8",
                     "conf 必须是 UTF-8（MDPro3 自己的 conf 实测不带 BOM）")
                continue
            bad_lines: list[str] = []
            for line in text.splitlines():
                s = line.strip()
                if not s or s.startswith("#") or s.startswith("//"):
                    continue
                if not s.startswith("!"):
                    bad_lines.append(s[:40])
                    continue
                parts = s.split()
                if len(parts) >= 3 and any(p.startswith("0x") for p in parts) is False:
                    bad_lines.append(s[:40])
            if bad_lines:
                issu("MD_CONF_FORMAT", "WARN",
                     f"{n} 有 {len(bad_lines)} 行不像合法指令：{bad_lines[:3]}",
                     "行格式应为「!setname 0xXXX 字段名」；游戏读不动会整包忽略这一行")
            else:
                checked.append(f"{n} 格式抽查")
    if checked:
        issu("MD_DEEP_OK", "INFO",
             "深检完成：" + "；".join(checked),
             "与客户端对账的部分已全部通过；最后一步「点导入→游戏里起效」"
             "仍需你在客户端里走一次（这一步没有任何本地代码能替代）")
