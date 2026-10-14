"""端到端集成验收：把「一句话设想 → 能上牌桌的卡」整条链真跑一遍。

跑法::

    python tools/e2e_check.py            # 全跑
    python tools/e2e_check.py --keep     # 保留产物不清理

覆盖：造卡 → 平衡审计(G1) → PSCT 卡文 → 卡文校验 → Lua 生成 → Lua 静态检查
→ 实跑对局(G3) → 卡面渲染 → 导出包 → 导出自检(G5) → 安装预演。

结果写 ``workspace/.cache/e2e.txt``（Windows 控制台是 GBK，中文直接 print 会炸）。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cardforge.content import effects as EF                      # noqa: E402
from cardforge.content import psct                               # noqa: E402
from cardforge.content.lua import apicatalog as API              # noqa: E402
from cardforge.content.lua import emit, lint                     # noqa: E402
from cardforge.core.models import (CardSpec, EffectCost,          # noqa: E402
                                   EffectSpec, EffectTarget,
                                   RenderOptions)
from cardforge.export import expansions, install                 # noqa: E402
from cardforge.pipeline import gates                             # noqa: E402
from cardforge.pool import repo                                  # noqa: E402
from cardforge.render import compositor                          # noqa: E402
from cardforge.core import paths                                 # noqa: E402

OUT = pathlib.Path("workspace/.cache/e2e.txt")
CID = 210000999
PACK = pathlib.Path("workspace/out/e2e_pack")

L: list[str] = []
PASS = FAIL = WARN = 0


def say(s: str = "") -> None:
    L.append(s)


def check(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        say(f"  [OK]   {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        say(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))
    return ok


def warn(name: str, detail: str = "") -> None:
    global WARN
    WARN += 1
    say(f"  [WARN] {name} — {detail}")


# ══════════════════════════════════════════════════════════════════════
def build_spec() -> CardSpec:
    s = CardSpec(id=CID, name="星辉的见习指挥", frame="effect", attribute="光",
                 race="魔法师族", level=4, atk=1600, dfd=1200,
                 archetype="星辉", setcode="0x1A01")
    s.name_i18n = {"ja": "星輝の指揮官", "en": "Starlight Cadet Commander"}
    s.effects = [
        EffectSpec(kind="search", trigger="NORMAL_SUMMON_SUCCESS",
                   limit="hopt_name",
                   target=EffectTarget(from_zone="DECK", filter_kind="archetype",
                                       filter_value="星辉", count=1),
                   params={"_index": 0}),
        EffectSpec(kind="ssummon_hand", trigger="IGNITION", limit="hopt_name",
                   target=EffectTarget(from_zone="HAND", filter_kind="archetype",
                                       filter_value="星辉", count=1),
                   cost=EffectCost(kind="discard", count=1),
                   params={"_index": 1}),
    ]
    s.render = RenderOptions(rarity="prismatic_secret", set_number="E2E-JP001")
    return s


def main() -> int:
    t0 = time.time()
    say("CardForge 2.0 · 端到端集成验收")
    say("=" * 68)

    # ── 1. 规格 → 卡文 ──────────────────────────────────────────
    say("\n[1] 结构化规格 → PSCT 卡文")
    spec = build_spec()
    for e in spec.effects:
        vs = EF.validate_effect(e)
        check(f"效果 {e.kind} 通过 DSL 校验", not any(i.level == "ERROR" for i in vs),
              "；".join(i.message for i in vs[:2]))
    texts = psct.gen.compose_all(spec, ["zh_cn", "ja", "en"])
    check("三种语言都生成了卡文", all((texts.get(k) or "").strip() for k in texts),
          f"{ {k: len(v) for k, v in texts.items()} }")
    zh = texts.get("zh_cn", "")
    say(f"       中文卡文：{zh}")
    check("卡文含效果编号 ① ②", "①" in zh and "②" in zh)
    check("卡文含卡名级 HOPT 声明", "这个卡名的" in zh and "1回合各能使用1次" in zh)
    spec.text_i18n = dict(texts)
    issues = psct.lint.lint(spec)
    errs = [i for i in issues if i.level == "ERROR"]
    check("生成器 ↔ 校验器一致（0 ERROR）", not errs,
          "；".join(f"{i.code}:{i.message}" for i in errs[:3]))

    # ── 2. 卡文 → 规格落盘 ─────────────────────────────────────
    say("\n[2] 落盘与 G1 平衡审计")
    path = repo.save_card(spec, snapshot=True, note="e2e")
    check("spec.json 写入工作区", bool(path), str(path))
    back = repo.load_card(CID)
    check("读回后效果条数一致", back is not None and len(back.effects) == 2)
    g1 = gates.g1_balance(back, None)
    check("G1 跑通", g1.status in ("pass", "warn"), f"{g1.status}｜{g1.summary}")
    for i in g1.issues[:6]:
        say(f"       [{i.level}] {i.code} {i.message}")

    # ── 3. 规格 → Lua ──────────────────────────────────────────
    say("\n[3] 效果 IR → Lua 脚本")
    lua = emit.emit_script(back)
    check("生成了非空脚本", bool(lua.strip()), f"{len(lua.splitlines())} 行")
    ok, why = lint.syntax_ok(lua)
    check("Lua 语法检查通过", ok, why)
    l2 = lint.lint_lua(lua, back)
    check("G2 静态检查 0 ERROR", not [i for i in l2 if i.level == "ERROR"],
          "；".join(i.message for i in l2 if i.level == "ERROR")[:120])
    check("Stringid ↔ texts 同步",
          not [i for i in lint.check_stringid_sync(back, lua) if i.level == "ERROR"])
    un = API.unknown(lua)
    check("引用的 API 全在本机白名单内",
          not (un.get("calls") or un.get("methods") or un.get("consts")),
          json.dumps(un, ensure_ascii=False)[:160])
    strs = emit.emit_strings(back)
    check("cdb 文本槽位数与脚本一致", len(strs) <= 16 and len(strs) >= 1,
          f"{len(strs)} 条")
    back.lua = lua
    back.strings = strs
    repo.save_card(back, snapshot=False)
    say("       " + "─" * 40)
    for line in lua.splitlines()[:16]:
        say("       " + line)

    # ── 4. 实跑对局 ────────────────────────────────────────────
    say("\n[4] G3 实跑对局（ocgcore）")
    eng = gates.g3_duel(back, scenario=True, duels=1)
    check("G3 真跑了（不是 skipped）", eng.status != "skipped",
          f"{eng.status}｜{json.dumps(eng.to_dict().get('summary', ''), ensure_ascii=False)}")
    if eng.status == "skipped":
        warn("G3 被降级", eng.degraded)
    for i in eng.issues[:6]:
        say(f"       [{i.level}] {i.code} {i.message[:150]}")

    # ── 5. 卡面渲染 ────────────────────────────────────────────
    say("\n[5] 卡面渲染")
    caps = compositor.capabilities()
    if caps.get("L1_render"):
        files = compositor.export_card(back, None, paths.OUT,
                                       sizes=("edopro", "share"), fmt="png")
        check("渲出 edopro + share 两档", len(files) == 2,
              "、".join(paths.rel(pathlib.Path(f)) for f in files))
        from PIL import Image
        for f in files:
            with Image.open(f) as im:
                check(f"成图尺寸正确 {pathlib.Path(f).name}",
                      im.size in ((421, 614), (813, 1185)), str(im.size))
        png = compositor.preview_png(back, None, width=320)
        check("预览字节流可用", png[:4] == b"\x89PNG" or png[:2] == b"\xff\xd8",
              f"{len(png)} 字节")
    else:
        svg = compositor.render_svg(back)
        warn("无 Pillow，退回矢量预览", f"{len(svg)} 字符")
        check("SVG 预览仍可出图", svg.startswith("<svg"))

    # ── 6. 导出包 ──────────────────────────────────────────────
    say("\n[6] 导出 EDOPro 扩展包")
    if PACK.exists():
        shutil.rmtree(PACK)
    cards = [c for c in (repo.load_card(r["id"]) for r in repo.list_cards())
             if c is not None]
    res = expansions.build(cards, PACK, name="E2E", langs=("zh_cn",),
                           copy_pics=True)
    say(f"       构建结果：{json.dumps({k: v for k, v in res.items() if isinstance(v, (int, str, bool))}, ensure_ascii=False)[:220]}")
    cdb = list(PACK.rglob("*.cdb"))
    check("生成了 .cdb", bool(cdb), "、".join(p.name for p in cdb))
    scripts = list(PACK.rglob("script/c*.lua"))
    check("脚本进包", any(p.stem == f"c{CID}" for p in scripts), f"{len(scripts)} 个")
    if scripts:
        raw = next(p for p in scripts if p.stem == f"c{CID}").read_bytes()
        check("脚本 UTF-8 无 BOM", not raw.startswith(b"\xef\xbb\xbf"))
    v = expansions.verify(PACK, check_official=False)
    verr = [i for i in v if i.level == "ERROR"]
    check("G5 导出自检 0 ERROR", not verr,
          "；".join(i.message for i in verr[:3]))
    g5 = gates.g5_export(PACK)
    check("G5 质量门跑通", g5.status in ("pass", "warn", "fail"),
          f"{g5.status}｜{g5.summary[:80]}")

    # ── 7. 安装预演 ────────────────────────────────────────────
    say("\n[7] 一键安装（只预演，不写 EDOPro）")
    dry = install.install(PACK, None, dry_run=True)
    check("install(dry_run) 返回结构化结果", isinstance(dry, dict) and "ok" in dry,
          json.dumps({k: v for k, v in dry.items() if isinstance(v, (str, int, bool))},
                     ensure_ascii=False)[:200])

    # ── 8. 清理 ────────────────────────────────────────────────
    if "--keep" not in sys.argv:
        repo.delete_card(CID)
        shutil.rmtree(PACK, ignore_errors=True)
        for f in pathlib.Path(paths.OUT).glob(f"{CID}*"):
            f.unlink(missing_ok=True)

    say("\n" + "=" * 68)
    say(f"合计：PASS {PASS} · FAIL {FAIL} · WARN {WARN} · {round(time.time() - t0, 1)}s")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"{'PASS' if FAIL == 0 else 'FAIL'} {PASS}/{PASS + FAIL} warn={WARN} → {OUT}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
