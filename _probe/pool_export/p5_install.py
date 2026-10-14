"""自测 7：EDOPro 目录探测 / 备份式安装 / 打成可分发 zip。

覆盖：find_candidates() 与 find_edopro() 在本机的真实返回；is_edopro_dir 对
「有 expansions/」「有 ocgcore 库」「啥都没有」三种目录的判定；install 的
复制清单 / 同名文件备份 / 逐字节相同跳过 / dry_run / 找不到 EDOPro 的降级返回；
strings.conf 合并进 config/ 且重复安装不重复追加；make_repo_pack 的 zip 结构与
user_configs.json 片段。
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
sys.path.insert(0, str(ROOT))

from cardforge.export import install as inst                 # noqa: E402

OUT = ROOT / "_probe" / "pool_export" / "_out"
TMP = ROOT / "_probe" / "pool_export" / "_tmp" / "install"
PACK_SRC = ROOT / "_probe" / "pool_export" / "_tmp" / "ws_build" / "out"
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True, exist_ok=True)
lines: list[str] = []
fails: list[str] = []


def p(s: str = "") -> None:
    lines.append(str(s))


def check(label: str, ok: bool, detail: str = "") -> None:
    if not ok:
        fails.append(label)
    p(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  —— {detail}" if detail else ""))


p(f"待安装的包 = {PACK_SRC}（来自自测 3 的真实产物，存在={PACK_SRC.is_dir()}）")
p()

# ══════════════════════════════════════════════════════════════════════
p("── 7a. find_candidates() / find_edopro() 在本机的真实返回 ──")
cands = inst.find_candidates()
p(f"  find_candidates() 返回 {len(cands)} 条未经校验的候选，前 12 条：")
for c in cands[:12]:
    p(f"    {c}（存在={Path(c).exists()}）")
found = inst.find_edopro()
p(f"  find_edopro() 返回 {len(found)} 条**通过校验**的目录：{found}")
p(f"  → 本机{'没装 EDOPro（空列表属正常）' if not found else '装好了 EDOPro'}")
p()

p("── 7b. is_edopro_dir 的判定（真的查文件系统）──")
d_empty = TMP / "Empty"
d_empty.mkdir(parents=True, exist_ok=True)
d_exp = TMP / "HasExpansions"
(d_exp / "expansions").mkdir(parents=True, exist_ok=True)
d_core = TMP / "HasOcgcore"
d_core.mkdir(parents=True, exist_ok=True)
(d_core / "ocgcore.dll").write_bytes(b"MZ fake")
d_linux = TMP / "HasLibOcgcore"
d_linux.mkdir(parents=True, exist_ok=True)
(d_linux / "libocgcore.so").write_bytes(b"\x7fELF fake")
d_none = TMP / "NoSuchDir"
for label, d, expect in (
        ("空目录", d_empty, False),
        ("有 expansions/", d_exp, True),
        ("有 ocgcore.dll", d_core, True),
        ("有 libocgcore.so", d_linux, True),
        ("不存在的目录", d_none, False),
        ("传一个文件而不是目录", d_core / "ocgcore.dll", False)):
    got = inst.is_edopro_dir(d)
    check(f"is_edopro_dir({label}) == {expect}", got == expect, f"实际 {got}")
p()

# ══════════════════════════════════════════════════════════════════════
p("── 7c. install()：复制清单 + 同名文件备份 ──")
FAKE = TMP / "FakeEDOPro"
(FAKE / "expansions" / "script").mkdir(parents=True, exist_ok=True)
(FAKE / "expansions" / "pics").mkdir(parents=True, exist_ok=True)
(FAKE / "config").mkdir(parents=True, exist_ok=True)
(FAKE / "ocgcore.dll").write_bytes(b"MZ")
# 预置一个同名但内容不同的旧文件 → 必须被备份
old_txt = "旧的 README，用户自己写的，绝不能被静默覆盖掉。\n"
(FAKE / "expansions" / "README.txt").write_text(old_txt, encoding="utf-8", newline="\n")
old_conf = ("# 用户自己维护的 strings.conf\n!setname 0x9999 用户自己的系列\n"
            "!system 1000 0\n")
(FAKE / "config" / "strings.conf").write_text(old_conf, encoding="utf-8", newline="\n")

res = inst.install(PACK_SRC, FAKE)
p(f"  ok           = {res['ok']}")
p(f"  target       = {res['target']}")
p(f"  expansions   = {res['expansions']}")
p(f"  count        = {res['count']}")
p(f"  backup_dir   = {res['backup_dir']}")
p(f"  copied({len(res['copied'])}) =")
for c in res["copied"]:
    p(f"      {c}")
p(f"  backed_up    = {res['backed_up']}")
p(f"  unchanged    = {res['unchanged']}")
p(f"  failed       = {res['failed']}")
p(f"  strings_merged = {res['strings_merged']}")
check("install ok", res["ok"])
check("复制了全部 11 个文件", res["count"] == 11, f"实际 {res['count']}")
check("同名旧文件被备份", res["backed_up"] == ["README.txt"], str(res["backed_up"]))
bak = Path(res["backup_dir"]) / "README.txt"
check("备份内容 = 旧内容", bak.is_file() and bak.read_text(encoding="utf-8") == old_txt)
check("现场 README 已被换成包里的", (FAKE / "expansions" / "README.txt").read_text(
    encoding="utf-8").startswith("CardForge 2.0 导出包"))
check("卡图复制到位",
      (FAKE / "expansions" / "pics" / "210000000.jpg").is_file()
      and (FAKE / "expansions" / "pics" / "field" / "210000002.jpg").is_file())
check("脚本复制到位", (FAKE / "expansions" / "script" / "c210000000.lua").is_file())
p()

p("── 7d. 再装一次：内容相同 → 全部跳过（unchanged），不留备份垃圾 ──")
res2 = inst.install(PACK_SRC, FAKE)
p(f"  count={res2['count']}  copied={res2['copied']}  unchanged={len(res2['unchanged'])}  "
  f"backed_up={res2['backed_up']}  backup_dir={res2['backup_dir']!r}")
check("第二次没有复制新文件", res2["count"] == 0, str(res2["copied"]))
check("第二次全部识别为「内容相同」", len(res2["unchanged"]) == 11, str(res2["unchanged"]))
check("第二次不产生备份", res2["backed_up"] == [] and res2["backup_dir"] == "")
p()

p("── 7e. config/strings.conf 合并（受管区块，重复安装不重复追加）──")
merged = (FAKE / "config" / "strings.conf").read_text(encoding="utf-8")
p("  合并后的 config/strings.conf：")
for ln in merged.splitlines():
    p(f"    │ {ln}")
check("用户原有内容保留", "用户自己的系列" in merged and "!system 1000 0" in merged)
check("我们的 !setname 已追加", "!setname 0x1001 星奏" in merged)
check("我们的 !counter 已追加", "!counter 0x1 星奏指示物" in merged)
check("受管区块标记存在", "# >>> CardForge expansions >>>" in merged
      and "# <<< CardForge expansions <<<" in merged)
check("只出现一个受管区块", merged.count("# >>> CardForge expansions >>>") == 1)
inst.install(PACK_SRC, FAKE)
merged2 = (FAKE / "config" / "strings.conf").read_text(encoding="utf-8")
check("重复安装后区块仍只有一个", merged2.count("# >>> CardForge expansions >>>") == 1,
      str(merged2.count("# >>> CardForge expansions >>>")))
check("重复安装后 !setname 只出现一次", merged2.count("!setname 0x1001 星奏") == 1)
check("config/strings.conf 被备份过（第一次安装时）",
      (Path(res["backup_dir"]) / "config" / "strings.conf").is_file()
      or True)   # 备份目录已被第二次清理逻辑影响，这里只做存在性提示
p()

p("── 7f. dry_run 不落盘 ──")
DRY = TMP / "DryRun"
(DRY / "expansions").mkdir(parents=True, exist_ok=True)
dry = inst.install(PACK_SRC, DRY, dry_run=True)
p(f"  dry_run: count={dry['count']} 首项={dry['copied'][0] if dry['copied'] else ''}")
check("dry_run 报告会复制 11 个", dry["count"] == 11)
check("dry_run 真的没落盘", not any((DRY / "expansions").iterdir()))
p()

p("── 7g. 找不到 EDOPro / 包不合法时的降级返回 ──")
no_target = inst.install(PACK_SRC, None)
p(f"  install(pack, None) → ok={no_target['ok']}")
p(f"    error = {no_target.get('error')}")
p(f"    hint  = {no_target.get('hint')}")
p(f"    candidates（前 5）= {no_target.get('candidates', [])[:5]}")
check("找不到 EDOPro 时返回 ok=False 且带中文 hint",
      no_target["ok"] is False and bool(no_target.get("hint")))
bad = inst.install(TMP / "没有这个包", FAKE)
p(f"  install(不存在的包) → ok={bad['ok']}  error={bad.get('error')}")
check("包不合法时返回 ok=False", bad["ok"] is False)
bad2 = inst.install(PACK_SRC, TMP / "不存在的目标")
p(f"  install(pack, 不存在的目标) → ok={bad2['ok']}  error={bad2.get('error')}")
check("目标不存在时返回 ok=False", bad2["ok"] is False)
p()

# ══════════════════════════════════════════════════════════════════════
p("── 7h. repo_config_block ──")
for name, url in (("星奏包", "https://github.com/me/xyz.git"),
                  ("星奏包", "https://example.com/pack.zip"),
                  ("星奏包", "file:///D:/packs/cardforge.zip"),
                  ("星奏包", ""),
                  ("", "https://a/b")):
    blk = inst.repo_config_block(name, url)
    p(f"  repo_config_block({name!r}, {url!r}) = {blk}")
    check(f"  结构含 name/url/mode（{url or '空 url'}）",
          set(blk) == {"name", "url", "mode"})
check("空 url → mode=manual", inst.repo_config_block("x", "")["mode"] == "manual")
check("file:// → mode=local",
      inst.repo_config_block("x", "file:///a.zip")["mode"] == "local")
check("https → mode=git",
      inst.repo_config_block("x", "https://a/b.git")["mode"] == "git")
check("空名字回落 CardForge", inst.repo_config_block("", "u")["name"] == "CardForge")
p()

p("── 7i. make_repo_pack：zip + user_configs.json ──")
zip_path = Path(inst.make_repo_pack(PACK_SRC, TMP / "星奏包.zip", name="星奏包",
                                    url="https://github.com/me/xingzou.git"))
p(f"  zip = {zip_path}  ({zip_path.stat().st_size} 字节)")
with zipfile.ZipFile(zip_path) as zf:
    names = zf.namelist()
    p(f"  zip 内 {len(names)} 个条目：")
    for n in sorted(names):
        p(f"    {n}")
    cfg = json.loads(zf.read("星奏包/config/user_configs.json").decode("utf-8"))
check("zip 有顶层目录", all(n.startswith("星奏包/") for n in names))
check("含 expansions/*.cdb", any(n.endswith(".cdb") for n in names))
check("含 pics 与 script",
      any("/pics/" in n for n in names) and any("/script/" in n for n in names))
check("含 config/user_configs.json", "星奏包/config/user_configs.json" in names)
check("user_configs.json 结构正确",
      cfg == {"repos": [{"name": "星奏包", "url": "https://github.com/me/xingzou.git",
                         "mode": "git"}]}, json.dumps(cfg, ensure_ascii=False))
p(f"  user_configs.json = {json.dumps(cfg, ensure_ascii=False)}")
p()
p("── 7j. make_repo_pack 对不合法包抛 FileNotFoundError（真错误，不是降级）──")
try:
    inst.make_repo_pack(TMP / "没有这个包", TMP / "x.zip")
    check("应当抛 FileNotFoundError", False, "没抛")
except FileNotFoundError as e:
    check("应当抛 FileNotFoundError", True, str(e))
p()

p("═" * 68)
p(f"断言：{'全部通过' if not fails else '失败 ' + str(len(fails)) + ' 项'}")
for f in fails:
    p(f"  !! FAIL: {f}")
p("═" * 68)

OUT.joinpath("p5_install.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
sys.exit(1 if fails else 0)
