"""EDOPro expansions 打包 —— 把一批 ``CardSpec`` 变成能直接上桌的目录。

产物布局（``out_dir`` 是**包根**，不是 expansions 本身）::

    <out_dir>/
    ├── expansions/
    │   ├── <name>.cdb            # datas + texts（基础包，langs[0] 的文本）
    │   ├── <name>-<suffix>.cdb   # 各语言（后缀见 core.enums.LANGS[*].cdb_suffix）
    │   ├── pics/<id>.jpg         # 卡图（从 workspace/pics 复制）
    │   ├── pics/field/<id>.jpg   # 场地魔法背景（有才复制）
    │   ├── script/c<id>.lua      # 卡脚本（UTF-8 **无 BOM**，spec.lua 为空则跳过）
    │   ├── strings.conf          # !setname / !counter
    │   └── README.txt            # 导入说明 + 素材/字体许可提示
    ├── README.txt                # 同上（人先看到的通常是包根）
    └── cardforge_manifest.json   # 机器可读清单：卡表/语言/pending 卡图/跳过项

``build()`` 与 ``verify()`` 的分工：``build`` 只管**尽力产出**并把做不到的记成 Issue；
``verify`` 是 **G5 导出自检**，只读产物、独立重算，不信任 build 的返回值。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..core import constants as C
from ..core import paths
from ..core.enums import DEFAULT_LANG
from ..core.errors import SpecError
from ..core.models import CardSpec, Issue
from ..pool import cdb as cdbmod
from ..pool.official import OfficialPool, load as load_official
from . import strings as stringsmod

__all__ = [
    "PIC_SIZE", "MANIFEST_NAME", "README_NAME", "build", "verify",
    "needs_script", "file_tree", "pack_stats", "pic_size_ok", "pack_layout",
]

#: EDOPro 卡图的目标尺寸（``render.geometry.OUTPUT_SIZES["edopro"]``）。
PIC_SIZE: tuple[int, int] = (421, 614)

MANIFEST_NAME = "cardforge_manifest.json"
README_NAME = "README.txt"

#: 判定「需要 Lua 脚本」的 type 位（从 cdb 行反推，不依赖 CardSpec）
_TYPE_MONSTER = C.TYPE_MONSTER
_TYPE_NORMAL = C.TYPE_NORMAL
_TYPE_EFFECT = C.TYPE_EFFECT
_TYPE_PENDULUM = C.TYPE_PENDULUM
_TYPE_TOKEN = C.TYPE_TOKEN


# ══════════════════════════════════════════════════════════════════════
#  判定辅助
# ══════════════════════════════════════════════════════════════════════
#: 卡文位置放 flavor 的卡种（不需要脚本的白板）
_VANILLA_FRAMES: tuple[str, ...] = ("normal", "normal_pendulum", "token")


def needs_script(spec: CardSpec) -> bool:
    """这张卡是否**需要** Lua 脚本。

    * 通常怪兽 / 通常灵摆 / 衍生物不需要 —— 引擎自带白板行为。
      （按 **frame 键**判，不用 ``frame_def.base``：实测 ``FRAMES["normal"].base``
      是 ``"effect"``，照 base 判会把通常怪兽也误判成需要脚本。）
    * 其余怪兽（效果/仪式/融合/同步/超量/连接/灵魂/联合/二重…）与全部魔法·陷阱都需要。
    """
    return spec.frame not in _VANILLA_FRAMES


def needs_script_type(type_bits: int) -> bool:
    """``needs_script`` 的 cdb 行版本（verify 只有 type 位，没有 CardSpec）。"""
    t = int(type_bits or 0)
    if t & _TYPE_TOKEN:
        return False
    if not (t & _TYPE_MONSTER):
        return True                       # 魔法 / 陷阱
    # 白板 = NORMAL 且非 EFFECT（灵摆同理：通常灵摆不需要脚本）
    return not ((t & _TYPE_NORMAL) and not (t & _TYPE_EFFECT))


def _rel(root: Path, p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except Exception:
        return str(p)


def _issue(code: str, level: str, message: str, hint: str = "", field: str = "") -> Issue:
    return Issue(gate="G5", code=code, level=level, message=message, hint=hint, field=field)


def _sort_issues(issues: list[Issue]) -> list[Issue]:
    """ERROR → WARN → INFO 排序，并按 ``(code, field, message)`` **去重**。

    去重是必须的：verify 会逐个 .cdb 检查，多语言包（``<name>.cdb`` +
    ``<name>-zh-CN.cdb`` + ``<name>-ja.cdb``）里同一张卡的脚本/卡图问题会被
    重复发现三次，不去重的话 Issue 列表会变成三倍噪音（实测踩到过）。
    """
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    seen: set[tuple[str, str, str]] = set()
    out: list[Issue] = []
    for i in sorted(issues, key=lambda x: (order.get(x.level, 3), x.code, x.field, x.message)):
        key = (i.code, i.field, i.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
    return out


# ══════════════════════════════════════════════════════════════════════
#  布局探测
# ══════════════════════════════════════════════════════════════════════
def pack_layout(pack_dir: str | os.PathLike[str]) -> tuple[Path, Path, bool]:
    """返回 ``(包根, expansions 目录, 是否存在)``。

    兼容两种传参：包根（含 ``expansions/``）或直接给 ``expansions/`` 本身。
    """
    p = Path(pack_dir)
    if (p / "expansions").is_dir():
        return p, p / "expansions", True
    if p.is_dir() and any(p.glob("*.cdb")):
        return p.parent, p, True
    return p, p / "expansions", False


def _read_manifest(root: Path) -> dict | None:
    f = root / MANIFEST_NAME
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


# ══════════════════════════════════════════════════════════════════════
#  README
# ══════════════════════════════════════════════════════════════════════
_README_BODY = """CardForge 2.0 导出包 —— {name}
生成时间：{ts}

════════════════════════════════════════════════════════════════════
一、怎么装
════════════════════════════════════════════════════════════════════
1) 把本目录 expansions/ 里的**全部内容**复制进 EDOPro 的 expansions/ 目录：

     Windows : %LOCALAPPDATA%\\EDOPro\\expansions
     macOS   : ~/Library/Application Support/EDOPro/expansions
     Linux   : ~/.local/share/EDOPro/expansions

   也可以交给工具自动做（复制前会自动备份同名文件）：

     cardforge export --install
     # 或 python -c "from cardforge.export import install; print(install.install(r'{root}'))"

2) 如果本包带 strings.conf，请把里面的 !setname / !counter 行**追加**到
   EDOPro 的 config/strings.conf（或放在 expansions/strings.conf，两种位置都认）。
   不做这一步，DIY 系列的「字段名」与「计数器名」在游戏里会显示成空白。

3) 重启 EDOPro。卡图放 expansions/pics/<卡号>.jpg，脚本放 expansions/script/c<卡号>.lua。

════════════════════════════════════════════════════════════════════
二、这个包里有什么
════════════════════════════════════════════════════════════════════
  卡数        ：{n_cards}
  卡池文件    ：{cdbs}
  语言        ：{langs}
  卡图        ：{n_pics} 张{pend_txt}
  场地背景    ：{n_field} 张
  卡脚本      ：{n_scripts} 个
  系列名/计数器：{strings_txt}
{skip_txt}
════════════════════════════════════════════════════════════════════
三、素材与字体许可（合规红线，务必读完）
════════════════════════════════════════════════════════════════════
1) 卡框素材的归属是模糊的。所有已知的 PSD/矢量卡框模板（DeviantArt、cardmaker.net
   论坛、百度贴吧）都没有明确的开源许可，卡框本身是 Konami 的美术设计。本项目采用的
   kooriookami/yugioh-card 是唯一带明确 MIT 声明的来源，署名义务由
   data/assets/NOTICE.txt 承担 —— 分发本包时请一并保留该声明。

2) 官方字体全部是商业字体（Matrix / Matrixed / ITC Stone Serif / DF 隷書体 /
   FOT-Rodin / HanWang LiSu / DF Kai W5）。社区流传的「游戏王字体包」属于二次分发，
   法律风险高，本项目不分发。

3) 因此本项目用三层素材策略：A 内置 MIT 素材 / B 系统 CJK 字体回退 / C OFL 开源字体
   （Cinzel、EB Garamond、Noto Serif SC·TC、霞鹜文楷 LXGW WenKai、Noto Serif KR）。

   ⚠ 本包内的卡面是按 A 或 B 层渲染的。**用于商业发行前必须换成 C 层字体与自绘素材。**
   个人 DIY、学习、非商业分享可以按原样使用。

════════════════════════════════════════════════════════════════════
四、问与答
════════════════════════════════════════════════════════════════════
Q: 卡在游戏里看不到？
A: 卡号必须 >= 210000000（避开官方池），且 cdb 必须放在 expansions/ 下、文件名以
   .cdb 结尾。用 cardforge.export.expansions.verify() 跑一遍会告诉你缺什么。

Q: 卡名/卡文是空白的？
A: 该 .cdb 的 texts 表缺行。基础包 <name>.cdb 一定带文本，语言包 <name>-xx.cdb 覆盖它。

Q: 效果不生效？
A: script/c<卡号>.lua 缺失，或 .lua 带了 UTF-8 BOM（BOM 会让 Lua 直接报错）。
   本包内所有 .lua 都已经过无 BOM 校验。
"""


def _readme_text(name: str, stats: dict, root: Path) -> str:
    pend = stats.get("pending_pics") or []
    pend_txt = (f"；待补 {len(pend)} 张：{', '.join(str(p) for p in pend[:12])}"
                f"{' …' if len(pend) > 12 else ''}") if pend else ""
    skipped = stats.get("skipped") or []
    if skipped:
        lines = ["", "  跳过项（前 20 条）："]
        for it in skipped[:20]:
            lines.append(f"    - [{it.get('kind','')}] {it.get('id','')} {it.get('reason','')}")
        if len(skipped) > 20:
            lines.append(f"    … 另有 {len(skipped) - 20} 条")
        skip_txt = "\n".join(lines)
    else:
        skip_txt = ""
    cdb_names = [Path(v).name for v in (stats.get("cdbs") or {}).values()]
    return _README_BODY.format(
        name=name,
        ts=stats.get("ts", ""),
        root=str(root),
        n_cards=stats.get("n_cards", 0),
        cdbs=", ".join(cdb_names) or "（无）",
        langs=", ".join(stats.get("langs") or []) or "（无）",
        n_pics=stats.get("n_pics", 0),
        pend_txt=pend_txt,
        n_field=stats.get("n_field_pics", 0),
        n_scripts=stats.get("n_scripts", 0),
        strings_txt=("已生成 strings.conf"
                     if stats.get("strings_conf") else "本包未使用自定义系列名/计数器"),
        skip_txt=skip_txt,
    )


# ══════════════════════════════════════════════════════════════════════
#  build
# ══════════════════════════════════════════════════════════════════════
def build(
    cards: Iterable[CardSpec],
    out_dir: str | os.PathLike[str] | None = None,
    *,
    name: str = "CardForge",
    langs: Sequence[str] = (DEFAULT_LANG,),
    copy_pics: bool = True,
    setnames: Mapping[Any, str] | None = None,
    counters: Mapping[Any, str] | None = None,
    counters_alias: Mapping[Any, str] | None = None,
    base_cdb: bool = True,
    suffix_map: Mapping[str, str] | None = None,
    ot: int = cdbmod.DEFAULT_OT,
    pic_dir: str | os.PathLike[str] | None = None,
    script_dir: str | os.PathLike[str] | None = None,
    use_disk_scripts: bool = False,
    manifest: bool = True,
) -> dict:
    """把一批卡打包成 EDOPro 可用的 expansions。

    :param out_dir: **包根**目录（会在其下建 ``expansions/``）。
        默认 ``core.paths.OUT``，即 ``workspace/out/expansions`` —— 所有导出共用同一个
        expansions 目录，这正是 EDOPro 的组织方式（一个目录里放多个 .cdb）。
    :param langs: 要出的语言；第一项同时用作基础包 ``<name>.cdb`` 的文本。
    :param copy_pics: False 则完全跳过卡图（只出数据，供服务器端预生成时用）。
    :param use_disk_scripts: True 时，``spec.lua`` 为空会回退去 ``script_dir``
        找 ``c<id>.lua``；默认 False（严格只用 ``spec.lua``）。
    :returns: 统计字典，键包括 ``ok/pack_dir/expansions_dir/n_cards/cdbs/langs/
        n_pics/n_field_pics/n_scripts/pending_pics/skipped/files/issues``。
        ``issues`` 是 ``Issue.to_dict()`` 的列表（可直接 json 化）。
    """
    ts = datetime.now().isoformat(timespec="seconds")
    root = Path(out_dir) if out_dir else Path(paths.OUT)
    exp = root / "expansions"
    exp.mkdir(parents=True, exist_ok=True)
    pics_out = exp / "pics"
    field_out = pics_out / "field"
    script_out = exp / "script"

    src_pics = Path(pic_dir) if pic_dir else Path(paths.PICS)
    src_scripts = Path(script_dir) if script_dir else Path(paths.WORKSPACE) / "script"

    issues: list[Issue] = []
    skipped: list[dict] = []
    files: list[str] = []

    # ── 1. 去重与基础校验（同一批次内卡号必须唯一） ──────────────────
    items: list[CardSpec] = []
    seen: dict[int, CardSpec] = {}
    for spec in cards or []:
        if spec is None:
            continue
        cid = int(spec.id or 0)
        if not cid:
            issues.append(_issue("G5_ID_ZERO", "ERROR",
                                 f"卡「{spec.name}」没有卡号，已跳过",
                                 hint="先分配卡号（pool.official.next_free_id）。"))
            skipped.append({"kind": "card", "id": 0, "name": spec.name,
                            "reason": "卡号为 0"})
            continue
        if cid in seen:
            issues.append(_issue("G5_ID_DUP_INPUT", "ERROR",
                                 f"卡号 {cid} 在本批次里出现两次（{seen[cid].name} / {spec.name}）",
                                 hint="同一批次里每个卡号只能有一张卡；已保留先出现的那张。",
                                 field=str(cid)))
            skipped.append({"kind": "card", "id": cid, "name": spec.name,
                            "reason": "卡号与本批次重复"})
            continue
        seen[cid] = spec
        items.append(spec)
        if spec.is_pendulum and not spec.pendulum_scale:
            issues.append(_issue(
                "G5_PENDULUM_SCALE", "WARN",
                f"卡 {cid}「{spec.name}」是灵摆卡但没有刻度（pendulum_scale 为空）",
                hint="刻度会被写成 0，EDOPro 里这张卡的灵摆区无法正常使用；"
                     "先补 CardSpec.pendulum_scale。", field=str(cid)))

    # ── 2. cdb（每语言一份 + 基础包） ────────────────────────────────
    cdbs: dict[str, str] = {}
    if items:
        try:
            res = cdbmod.export_multilang(items, exp, name=name, langs=langs,
                                          base=base_cdb, suffix_map=suffix_map, ot=ot)
            cdbs = dict(res.get("files") or {})
            files.extend(_rel(root, Path(p)) for p in cdbs.values())
        except (SpecError, sqlite3.Error, OSError) as e:
            issues.append(_issue("G5_CDB_WRITE", "ERROR", f"写卡池失败：{e}",
                                 hint="检查目标目录是否可写、卡号是否重名。"))
    else:
        issues.append(_issue("G5_NO_CARDS", "ERROR", "没有可导出的卡",
                             hint="传进来的 cards 为空，或全部缺卡号。"))

    # ── 3. 卡图 ──────────────────────────────────────────────────────
    n_pics = 0
    n_field = 0
    pending_pics: list[int] = []
    if copy_pics:
        try:
            from PIL import Image  # noqa: F401  —— 仅用于确认可转换 png
            have_pil = True
        except Exception:
            have_pil = False
        for spec in items:
            cid = int(spec.id)

            # 场地魔法背景独立于卡图：卡图缺失时也要复制（实测曾因 continue 漏掉）
            fsrc = _find_pic(src_pics / "field", cid)
            if fsrc is not None:
                field_out.mkdir(parents=True, exist_ok=True)
                fdst = field_out / f"{cid}.jpg"
                try:
                    if fsrc.suffix.lower() in (".jpg", ".jpeg"):
                        shutil.copy2(fsrc, fdst)
                    elif have_pil:
                        from PIL import Image
                        with Image.open(fsrc) as im:
                            im.convert("RGB").save(fdst, "JPEG", quality=92)
                    else:
                        shutil.copy2(fsrc, fdst)
                    n_field += 1
                    files.append(_rel(root, fdst))
                except (OSError, ValueError) as e:
                    issues.append(_issue("G5_FIELD_COPY", "WARN",
                                         f"卡 {cid} 的场地背景复制失败：{e}",
                                         field=str(cid)))

            src = _find_pic(src_pics, cid)
            if src is None:
                pending_pics.append(cid)
                issues.append(_issue(
                    "G5_PIC_MISSING", "WARN",
                    f"卡 {cid}「{spec.name}」没有卡图",
                    hint=f"出图后放到 {paths.rel(src_pics)}/{cid}.jpg，或重跑 build(copy_pics=True)。",
                    field=str(cid)))
                skipped.append({"kind": "pic", "id": cid, "name": spec.name,
                                "reason": "卡图不存在"})
                continue
            pics_out.mkdir(parents=True, exist_ok=True)
            dst = pics_out / f"{cid}.jpg"
            try:
                if src.suffix.lower() in (".jpg", ".jpeg"):
                    shutil.copy2(src, dst)
                elif have_pil:
                    from PIL import Image
                    with Image.open(src) as im:
                        im.convert("RGB").save(dst, "JPEG", quality=92)
                else:
                    shutil.copy2(src, dst)
                n_pics += 1
                files.append(_rel(root, dst))
            except (OSError, ValueError) as e:
                pending_pics.append(cid)
                issues.append(_issue("G5_PIC_COPY", "WARN",
                                     f"卡 {cid} 的卡图复制失败：{e}",
                                     hint="确认文件未被占用、格式可读。", field=str(cid)))
                skipped.append({"kind": "pic", "id": cid, "name": spec.name,
                                "reason": f"复制失败：{e}"})

    # ── 4. 卡脚本 ────────────────────────────────────────────────────
    n_scripts = 0
    for spec in items:
        cid = int(spec.id)
        lua = str(spec.lua or "")
        if not lua.strip() and use_disk_scripts:
            fallback = src_scripts / f"c{cid}.lua"
            if fallback.is_file():
                try:
                    lua = fallback.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeDecodeError) as e:
                    issues.append(_issue("G5_SCRIPT_READ", "WARN",
                                         f"卡 {cid} 的脚本读不出来：{e}", field=str(cid)))
                    lua = ""
        if not lua.strip():
            if needs_script(spec):
                issues.append(_issue(
                    "G5_SCRIPT_MISSING", "WARN",
                    f"卡 {cid}「{spec.name}」需要脚本，但 spec.lua 是空的",
                    hint="在卡工程里生成 Lua，或把现成脚本放到 "
                         f"{paths.rel(src_scripts)}/c{cid}.lua 再用 use_disk_scripts=True。",
                    field=str(cid)))
                skipped.append({"kind": "script", "id": cid, "name": spec.name,
                                "reason": "spec.lua 为空"})
            continue
        script_out.mkdir(parents=True, exist_ok=True)
        dst = script_out / f"c{cid}.lua"
        # 去掉可能从别处抄来的 BOM —— 带 BOM 的 Lua 会被引擎直接拒绝
        body = lua.lstrip("\ufeff")
        if not body.endswith("\n"):
            body += "\n"
        try:
            dst.write_text(body, encoding="utf-8", newline="\n")
            n_scripts += 1
            files.append(_rel(root, dst))
        except OSError as e:
            issues.append(_issue("G5_SCRIPT_WRITE", "ERROR",
                                 f"卡 {cid} 的脚本写不进去：{e}", field=str(cid)))

    # ── 5. strings.conf ──────────────────────────────────────────────
    strings_path = ""
    if setnames or counters or counters_alias:
        try:
            strings_path = stringsmod.write(exp / "strings.conf", setnames=setnames,
                                            counters=counters,
                                            counters_alias=counters_alias)
            files.append(_rel(root, Path(strings_path)))
        except OSError as e:
            issues.append(_issue("G5_STRINGS_WRITE", "WARN", f"写 strings.conf 失败：{e}",
                                 hint="检查 expansions/ 是否可写。"))

    # ── 6. README + manifest ─────────────────────────────────────────
    stats: dict[str, Any] = {
        "ok": True,
        "ts": ts,
        "pack_dir": str(root),
        "expansions_dir": str(exp),
        "name": name,
        "n_cards": len(items),
        "cdbs": cdbs,
        "langs": [str(l) for l in (langs or (DEFAULT_LANG,))],
        "n_pics": n_pics,
        "n_field_pics": n_field,
        "n_scripts": n_scripts,
        "pending_pics": sorted(pending_pics),
        "strings_conf": strings_path,
        "skipped": skipped,
        "card_ids": [int(s.id) for s in items],
    }
    readme = _readme_text(name, stats, root)
    readme_paths: list[str] = []
    for target in (root / README_NAME, exp / README_NAME):
        try:
            target.write_text(readme, encoding="utf-8", newline="\n")
            readme_paths.append(str(target))
            files.append(_rel(root, target))
        except OSError as e:
            issues.append(_issue("G5_README_WRITE", "WARN", f"写 README 失败：{e}"))
    stats["readme"] = readme_paths

    manifest_path = ""
    if manifest:
        mf = {
            "generator": "CardForge 2.0",
            "ts": ts,
            "name": name,
            "langs": stats["langs"],
            "cdbs": cdbs,
            "card_ids": stats["card_ids"],
            "pending_pics": stats["pending_pics"],
            "cards": [
                {"id": int(s.id), "name": s.display_name or s.name,
                 "frame": s.frame, "archetype": s.archetype,
                 "setcode": s.setcode, "needs_script": needs_script(s),
                 "has_script": bool(str(s.lua or "").strip()),
                 "has_pic": int(s.id) not in set(pending_pics)}
                for s in items
            ],
            "skipped": skipped,
            "stats": {k: v for k, v in stats.items()
                      if k in ("n_cards", "n_pics", "n_field_pics", "n_scripts")},
        }
        try:
            (root / MANIFEST_NAME).write_text(
                json.dumps(mf, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n")
            manifest_path = str(root / MANIFEST_NAME)
            files.append(_rel(root, Path(manifest_path)))
        except OSError as e:
            issues.append(_issue("G5_MANIFEST_WRITE", "WARN", f"写 manifest 失败：{e}"))
    stats["manifest"] = manifest_path
    stats["files"] = sorted(set(files))
    stats["issues"] = [i.to_dict() for i in _sort_issues(issues)]
    stats["ok"] = not any(i.level == "ERROR" for i in issues)

    # ── 兼容别名 ─────────────────────────────────────────────────────
    # 契约（docs/02 §8）只写了 build(...) -> dict，没规定键名。为了让 cli.py
    # （用了 res.get("cards") / paths.rel(Path(res.get("dir"))) / res.get("stats")）
    # 与 pipeline/gates.g5_export(res["dir"]) 直接可用，这里补 3 个别名键，
    # **不动**上面那些信息量更大的原生键。
    stats["cards"] = stats["n_cards"]
    stats["dir"] = stats["pack_dir"]
    stats["stats"] = {
        "cards": stats["n_cards"],
        "pics": stats["n_pics"],
        "field_pics": stats["n_field_pics"],
        "scripts": stats["n_scripts"],
        "langs": ", ".join(stats["langs"]),
        "cdbs": ", ".join(Path(p).name for p in stats["cdbs"].values()),
        "pending_pics": len(stats["pending_pics"]),
        "issues_error": sum(1 for i in stats["issues"] if i["level"] == "ERROR"),
        "issues_warn": sum(1 for i in stats["issues"] if i["level"] == "WARN"),
    }
    return stats


def _find_pic(base: Path, card_id: int) -> Path | None:
    """找 ``<base>/<id>.{jpg,jpeg,png}``（按优先级）。"""
    for ext in (".jpg", ".jpeg", ".png"):
        p = Path(base) / f"{int(card_id)}{ext}"
        if p.is_file():
            return p
    return None


# ══════════════════════════════════════════════════════════════════════
#  verify（G5）
# ══════════════════════════════════════════════════════════════════════
def pic_size_ok(path: str | os.PathLike[str]) -> tuple[bool, tuple[int, int] | str]:
    """读图尺寸。返回 ``(是否 421×614, (w,h) 或 错误说明)``。

    Pillow 缺失时返回 ``(True, "Pillow 不可用，未检查尺寸")`` —— 降级为「不报错」。
    """
    try:
        from PIL import Image
    except Exception:
        return True, "Pillow 不可用，未检查尺寸"
    try:
        with Image.open(path) as im:
            return (im.size == PIC_SIZE), im.size
    except Exception as e:
        return False, f"读图失败：{e}"


def verify(pack_dir: str | os.PathLike[str], *, official: OfficialPool | None = None,
           check_official: bool = True) -> list[Issue]:
    """**G5 导出自检** —— 只读产物、独立重算，返回 ``list[Issue]``（不抛异常）。

    检查清单：

    ==========================  ======  ==========================================
    code                        级别    内容
    ==========================  ======  ==========================================
    ``G5_PACK_MISSING``         ERROR   包根不存在
    ``G5_EXPANSIONS_MISSING``   ERROR   没有 ``expansions/``
    ``G5_CDB_MISSING``          ERROR   一个 ``.cdb`` 都没有
    ``G5_CDB_OPEN``             ERROR   cdb 打不开
    ``G5_CDB_SCHEMA``           ERROR   ``datas``/``texts`` 表或列缺失
    ``G5_CDB_ROW_MISSING``      ERROR   卡在 cdb 里没有记录（datas 或 texts 缺行）
    ``G5_CDB_ID_DUP``           ERROR   同一 cdb 内卡号重复 / texts 与 datas 不对齐
    ``G5_ID_CONFLICT``          ERROR   卡号与**官方池**冲突
    ``G5_LANG_MISMATCH``        WARN    语言包的卡号集合与基础包不一致
    ``G5_SCRIPT_MISSING``       WARN    需要脚本的卡没有 ``script/c<id>.lua``
    ``G5_PENDULUM_SCALE``       WARN    灵摆卡的 level 列解出来刻度是 0
    ``G5_LUA_BOM``              ERROR   ``.lua`` 带 UTF-8 BOM（脚本会直接失效）
    ``G5_LUA_ENCODING``         ERROR   ``.lua`` 不是合法 UTF-8
    ``G5_LUA_EMPTY``            WARN    ``.lua`` 是空文件
    ``G5_PIC_MISSING``          WARN    没有卡图，且没在 manifest 里标 pending
    ``G5_PIC_PENDING``          INFO    没有卡图，但 manifest 已明确标记 pending
    ``G5_PIC_SIZE``             WARN    卡图不是 421×614（附实测尺寸）
    ``G5_PIC_UNREADABLE``       WARN    卡图读不出来
    ``G5_STRINGS_MISSING``      INFO    没有 strings.conf
    ``G5_STRINGS_BAD``          WARN    strings.conf 有无法解析的键
    ``G5_MANIFEST_MISSING``     INFO    没有 ``cardforge_manifest.json``
    ==========================  ======  ==========================================
    """
    issues: list[Issue] = []
    try:
        return _verify_impl(pack_dir, official, check_official, issues)
    except Exception as e:                      # noqa: BLE001 —— 自检绝不把异常抛给调用方
        issues.append(_issue("G5_VERIFY_CRASH", "ERROR", f"自检过程出错：{e}",
                             hint="这是自检自身的 bug，请把包目录与异常一起上报。"))
        return _sort_issues(issues)


def _verify_impl(pack_dir: str | os.PathLike[str], official: OfficialPool | None,
                 check_official: bool, issues: list[Issue]) -> list[Issue]:
    root, exp, exists = pack_layout(pack_dir)
    if not root.exists():
        issues.append(_issue("G5_PACK_MISSING", "ERROR", f"包目录不存在：{pack_dir}",
                             hint="先跑 expansions.build() 生成包。"))
        return _sort_issues(issues)
    if not exists or not exp.is_dir():
        issues.append(_issue("G5_EXPANSIONS_MISSING", "ERROR",
                             f"包目录里没有 expansions/：{root}",
                             hint="EDOPro 只认 expansions/<name>.cdb，目录层级不能少。"))
        return _sort_issues(issues)

    cdb_files = sorted(exp.glob("*.cdb"))
    if not cdb_files:
        issues.append(_issue("G5_CDB_MISSING", "ERROR", f"expansions/ 里没有 .cdb：{exp}",
                             hint="cdb 文件名必须以 .cdb 结尾。"))
        return _sort_issues(issues)

    manifest = _read_manifest(root)
    if manifest is None:
        issues.append(_issue("G5_MANIFEST_MISSING", "INFO",
                             f"没有 {MANIFEST_NAME}，按 cdb 内容推断待检卡表",
                             hint="build(manifest=True) 会生成它，便于标记 pending 卡图。"))
    pending = {int(i) for i in (manifest or {}).get("pending_pics", []) or []}

    # ── cdb 结构与卡号 ───────────────────────────────────────────────
    ids_by_cdb: dict[str, set[int]] = {}
    datas_by_cdb: dict[str, dict[int, tuple[int, int]]] = {}   # id -> (type, level)
    for f in cdb_files:
        try:
            con = cdbmod.open_cdb_ro(f)
        except sqlite3.Error as e:
            issues.append(_issue("G5_CDB_OPEN", "ERROR", f"打不开 {f.name}：{e}",
                                 hint="确认不是其它程序正占用，或文件已损坏。"))
            continue
        try:
            missing_cols = []
            for table, cols in (("datas", cdbmod.DATAS_COLS), ("texts", cdbmod.TEXTS_COLS)):
                have = {str(r[1]) for r in con.execute(f"PRAGMA table_info({table})")}
                if not have:
                    missing_cols.append(f"{table}（整张表缺失）")
                    continue
                for col in cols:
                    if col not in have:
                        missing_cols.append(f"{table}.{col}")
            if missing_cols:
                issues.append(_issue(
                    "G5_CDB_SCHEMA", "ERROR",
                    f"{f.name} 表结构不完整，缺：{', '.join(missing_cols[:8])}"
                    f"{' …' if len(missing_cols) > 8 else ''}",
                    hint="cdb 必须有 datas(id,ot,alias,setcode,type,atk,def,level,race,"
                         "attribute,category) 与 texts(id,name,desc,str1..str16)。",
                    field=f.name))

            d_ids = [int(r[0]) for r in con.execute("SELECT id FROM datas")]
            t_ids = {int(r[0]) for r in con.execute("SELECT id FROM texts")}
            ids_by_cdb[f.name] = set(d_ids) | t_ids
            for r in con.execute("SELECT id, type, level FROM datas"):
                datas_by_cdb.setdefault(f.name, {})[int(r[0])] = (
                    int(r[1] or 0), int(r[2] or 0))

            if len(d_ids) != len(set(d_ids)):
                dup = sorted({i for i in d_ids if d_ids.count(i) > 1})[:8]
                issues.append(_issue("G5_CDB_ID_DUP", "ERROR",
                                     f"{f.name} 里卡号重复：{dup}",
                                     hint="datas.id 是主键，重复说明文件被外部工具破坏。"))
            only_data = sorted(set(d_ids) - t_ids)
            only_text = sorted(t_ids - set(d_ids))
            if only_data or only_text:
                issues.append(_issue(
                    "G5_CDB_ROW_MISSING", "ERROR",
                    f"{f.name} 中 datas/texts 不对齐："
                    f"缺文本 {only_data[:8]}{' …' if len(only_data) > 8 else ''}；"
                    f"缺数据 {only_text[:8]}{' …' if len(only_text) > 8 else ''}",
                    hint="没有 texts 行 = 卡名卡文全空白；没有 datas 行 = 卡不出现。"))
        except sqlite3.Error as e:
            issues.append(_issue("G5_CDB_OPEN", "ERROR", f"读 {f.name} 出错：{e}"))
        finally:
            con.close()

    # 基础包 = 名字里没有 "-" 的那个；其余按语言包对待
    plain = [f for f in cdb_files if "-" not in f.stem]
    base = plain[0] if plain else cdb_files[0]
    base_ids = ids_by_cdb.get(base.name, set())
    for f in cdb_files:
        if f is base:
            continue
        got = ids_by_cdb.get(f.name, set())
        if got != base_ids:
            miss = sorted(base_ids - got)[:8]
            extra = sorted(got - base_ids)[:8]
            issues.append(_issue(
                "G5_LANG_MISMATCH", "WARN",
                f"语言包 {f.name} 与基础包 {base.name} 卡号集合不一致"
                f"（少 {miss}{' …' if len(base_ids - got) > 8 else ''}；"
                f"多 {extra}{' …' if len(got - base_ids) > 8 else ''}）",
                hint="语言包只覆盖部分卡时，未覆盖的卡在该语言下会显示为空白。",
                field=f.name))

    expected = {int(i) for i in (manifest or {}).get("card_ids", []) or []} or set(base_ids)
    for f in cdb_files:
        got = ids_by_cdb.get(f.name, set())
        for cid in sorted(expected - got)[:12]:
            issues.append(_issue("G5_CDB_ROW_MISSING", "ERROR",
                                 f"卡 {cid} 在 {f.name} 里没有记录",
                                 hint="从 manifest 看它应该在这个包里。", field=str(cid)))

    # ── 卡号与官方池冲突 ─────────────────────────────────────────────
    if check_official:
        pool = official if official is not None else load_official()
        if pool.available:
            all_ids: set[int] = set()
            for s in ids_by_cdb.values():
                all_ids |= s
            conflicts = [cid for cid in sorted(all_ids) if pool.id_taken(cid)]
            for cid in conflicts[:20]:
                issues.append(_issue(
                    "G5_ID_CONFLICT", "ERROR",
                    f"卡号 {cid} 与官方卡池冲突（共 {len(conflicts)} 个）",
                    hint="官方池实测最大 id 为 99995595；DIY 卡号请用 210000000 起。",
                    field=str(cid)))
        else:
            issues.append(_issue("G5_OFFICIAL_UNAVAILABLE", "INFO",
                                 "官方卡池不可用，跳过卡号冲突检查",
                                 hint="；".join(pool.warnings[:2])))

    # ── 脚本 + 灵摆刻度 ──────────────────────────────────────────────
    script_dir = exp / "script"
    for f in cdb_files:
        for cid, (tbits, lvl) in sorted(datas_by_cdb.get(f.name, {}).items()):
            if needs_script_type(tbits) and not (script_dir / f"c{cid}.lua").is_file():
                issues.append(_issue(
                    "G5_SCRIPT_MISSING", "WARN",
                    f"卡 {cid} 需要脚本，但缺 script/c{cid}.lua",
                    hint="效果怪/魔陷都靠 c<卡号>.lua 生效；白板卡可忽略本条。",
                    field=str(cid)))
            info = cdbmod.parse_level_column(lvl, tbits)
            if info["pendulum"] and not info["lscale"]:
                issues.append(_issue(
                    "G5_PENDULUM_SCALE", "WARN",
                    f"卡 {cid} 是灵摆卡，但 level 列解出的刻度是 0"
                    f"（level 列 = 0x{lvl:08X}）",
                    hint="level 列应为 (刻度<<24)|(刻度<<16)|等级；刻度 0 的灵摆在"
                         "EDOPro 里无法正常使用。", field=str(cid)))

    try:
        from PIL import Image  # noqa: F401
        have_pil = True
        pil_note = ""
    except Exception:
        have_pil = False
        pil_note = "（Pillow 不可用，未检查图片尺寸）"

    lua_files = sorted(exp.rglob("*.lua"))
    for f in lua_files:
        try:
            raw = f.read_bytes()
        except OSError as e:
            issues.append(_issue("G5_LUA_ENCODING", "ERROR", f"读不了 {f.name}：{e}"))
            continue
        if raw[:3] == b"\xef\xbb\xbf":
            issues.append(_issue(
                "G5_LUA_BOM", "ERROR",
                f"{_rel(root, f)} 带 UTF-8 BOM（前 3 字节 EF BB BF）",
                hint="BOM 会让 Lua 解析直接失败、脚本完全不生效；以 utf-8 无 BOM 重写。",
                field=_rel(root, f)))
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as e:
            issues.append(_issue("G5_LUA_ENCODING", "ERROR",
                                 f"{_rel(root, f)} 不是合法 UTF-8：{e}",
                                 hint="Lua 脚本必须是 UTF-8（无 BOM）。"))
        if not raw.strip():
            issues.append(_issue("G5_LUA_EMPTY", "WARN", f"{_rel(root, f)} 是空文件",
                                 hint="删掉它，或补上真正的脚本内容。"))

    # ── 卡图 ─────────────────────────────────────────────────────────
    pics_dir = exp / "pics"
    for f in cdb_files:
        for cid in sorted(ids_by_cdb.get(f.name, set())):
            pic = pics_dir / f"{cid}.jpg"
            if not pic.is_file():
                if cid in pending:
                    issues.append(_issue("G5_PIC_PENDING", "INFO",
                                         f"卡 {cid} 的卡图待补（manifest 已标记）",
                                         hint=f"出图后放到 {_rel(root, pics_dir)}/{cid}.jpg。",
                                         field=str(cid)))
                else:
                    issues.append(_issue("G5_PIC_MISSING", "WARN",
                                         f"卡 {cid} 没有卡图，也没标记 pending",
                                         hint=f"补 {_rel(root, pics_dir)}/{cid}.jpg（421×614）。",
                                         field=str(cid)))
                continue
            ok, size = pic_size_ok(pic)
            if isinstance(size, str):
                if not ok:
                    issues.append(_issue("G5_PIC_UNREADABLE", "WARN",
                                         f"卡 {cid} 的卡图读不出来：{size}", field=str(cid)))
            elif not ok:
                issues.append(_issue(
                    "G5_PIC_SIZE", "WARN",
                    f"卡 {cid} 的卡图是 {size[0]}×{size[1]}，EDOPro 用 {PIC_SIZE[0]}×{PIC_SIZE[1]}",
                    hint="不匹配时 EDOPro 会拉伸变形；用 render.compositor.export_card("
                         "sizes=('edopro',)) 重出。", field=str(cid)))
    if pil_note and (pics_dir.is_dir()):
        issues.append(_issue("G5_PIC_NO_PILLOW", "INFO", f"卡图尺寸未校验{pil_note}",
                             hint="装 Pillow 后重跑 verify()。"))

    # ── strings.conf ─────────────────────────────────────────────────
    conf = exp / "strings.conf"
    if not conf.is_file():
        issues.append(_issue("G5_STRINGS_MISSING", "INFO",
                             "包里没有 strings.conf",
                             hint="只有用到自定义字段名/计数器时才需要它。"))
    else:
        parsed = stringsmod.read(conf)
        for line in parsed.get("unknown", [])[:8]:
            issues.append(_issue("G5_STRINGS_BAD", "WARN",
                                 f"strings.conf 里认不出的行：{line.strip()[:80]}",
                                 hint="只支持 !setname / !counter / !counter_alias，"
                                      "其余行会原样保留但 EDOPro 也读不懂。"))
        if not (parsed.get("setnames") or parsed.get("counters")
                or parsed.get("counters_alias")):
            issues.append(_issue("G5_STRINGS_EMPTY", "INFO",
                                 "strings.conf 里没有任何指令", field="strings.conf"))
    return _sort_issues(issues)


# ══════════════════════════════════════════════════════════════════════
#  展示辅助
# ══════════════════════════════════════════════════════════════════════
def file_tree(pack_dir: str | os.PathLike[str], *, limit: int = 400) -> list[str]:
    """把包内文件列成带缩进的树（自测/CLI 打印用）。超过 ``limit`` 条会截断。"""
    root, _exp, _exists = pack_layout(pack_dir)
    if not root.is_dir():
        return [f"（不存在）{root}"]
    out: list[str] = [f"{root.name}/"]
    count = 0
    # 按相对路径的「部分元组」排序 = 真正的深度优先树序（父目录紧跟自己的子项）
    for p in sorted(root.rglob("*"),
                    key=lambda q: tuple(part.lower() for part in q.relative_to(root).parts)):
        depth = len(p.relative_to(root).parts)
        if depth > 4:
            continue
        count += 1
        if count > limit:
            out.append(f"  … 另有更多文件（已截断到 {limit} 条）")
            break
        prefix = "  " * depth
        if p.is_dir():
            out.append(f"{prefix}{p.name}/")
        else:
            try:
                kb = p.stat().st_size / 1024
                out.append(f"{prefix}{p.name}  ({kb:.1f} KB)")
            except OSError:
                out.append(f"{prefix}{p.name}")
    return out


def pack_stats(pack_dir: str | os.PathLike[str]) -> dict:
    """包里有什么（数量统计，供 CLI/UI 展示）。"""
    root, exp, exists = pack_layout(pack_dir)
    if not exists:
        return {"ok": False, "pack_dir": str(root), "error": "没有 expansions/ 目录"}
    return {
        "ok": True,
        "pack_dir": str(root),
        "expansions_dir": str(exp),
        "cdbs": [p.name for p in sorted(exp.glob("*.cdb"))],
        "n_pics": len(list((exp / "pics").glob("*.jpg"))) if (exp / "pics").is_dir() else 0,
        "n_field_pics": len(list((exp / "pics" / "field").glob("*.jpg")))
        if (exp / "pics" / "field").is_dir() else 0,
        "n_scripts": len(list((exp / "script").glob("*.lua")))
        if (exp / "script").is_dir() else 0,
        "strings_conf": (exp / "strings.conf").is_file(),
        "readme": (root / README_NAME).is_file() or (exp / README_NAME).is_file(),
        "manifest": (root / MANIFEST_NAME).is_file(),
    }
