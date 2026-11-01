"""工作区数据修复：字段码撞车 + 效果对象缺字段名/字段码（配套「检索链路」四个 bug 修复）。

修的是什么
----------
1. **圣痕与星奏共用 ``0x1000``**：两张不同系列的卡在脚本里是同一个字段，
   「检索本家卡」会跨系列互检；同时 圣痕 的系列圣经写的是 ``0x0``，
   而卡上是 ``0x1000`` —— 圣经与卡片对不上，G4 的字段绑定核不进去。
   → 圣痕 换成官方未占用的 ``0x1001``（实测官方卡池 0 张占用），星奏 保留 ``0x1000``。
2. **210000001「圣痕的继承者 空」两条硬伤**：本卡 ``setcode`` 是 ``0x0``
   （不属于任何字段，本家检索检不到它），且检索效果的筛选值是 ``null``
   （脚本里过滤条件整个消失 → 检卡组任意一张卡）。→ 补字段码与本家字段名。
3. **210000021 的 ``limit = "no_limit"``**：取值域里只有 ``none``，
   这个手写值会让卡文与脚本都拿不到次数限制。→ 归一成 ``none``。
4. 所有效果的 ``target.filter_kind == "archetype"`` 都显式写下字段名与字段码，
   脚本生成与 G1 审计用的就是这两格（留空虽然会兜底，但复用 IR 时范围会跟着卡变）。

改完按应用自己的投影重生成卡文与脚本（``psct.gen.fill_spec`` + ``lua.emit``），
保证 spec.json 里的文本/脚本与新字段码不是两套东西。
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardforge.core.models import CardSpec                      # noqa: E402
from cardforge.pool import repo                                 # noqa: E402

ARCH_SETCODE = {"圣痕": "0x1001", "星奏": "0x1000"}
LIMIT_FIX = {"no_limit": "none", "once": "once_per_turn"}


def fix_bibles() -> None:
    for name, code in ARCH_SETCODE.items():
        p = ROOT / "workspace" / "archetypes" / name / "archetype.json"
        if not p.exists():
            print(f"[SKIP] 没有系列圣经 {name}")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if str(d.get("setcode") or "") == code:
            print(f"[OK  ] 圣经 {name} setcode 已是 {code}")
            continue
        before = d.get("setcode")
        d["setcode"] = code
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[FIX ] 圣经 {name} setcode {before} → {code}")


def _get(obj, key, default=None):
    return (obj or {}).get(key, default) if isinstance(obj, dict) \
        else getattr(obj, key, default)


def _set(obj, key, value) -> None:
    if isinstance(obj, dict):
        obj[key] = value
    else:
        setattr(obj, key, value)


def fix_targets(spec: CardSpec, code: str) -> list[str]:
    """改在**落盘形状**上：spec.effects 里通常是 dict，
    ``effect_specs()`` 每次都会把 dict 转成新的 EffectSpec 对象，
    改那个临时对象等于没改（保存时又按原 dict 写回去）。"""
    notes: list[str] = []
    arch = str(spec.archetype or "").strip()
    for i, eff in enumerate(spec.effects or [], start=1):
        old_limit = str(_get(eff, "limit") or "")
        if old_limit in LIMIT_FIX:
            _set(eff, "limit", LIMIT_FIX[old_limit])
            notes.append(f"第 {i} 条效果 limit「{old_limit}」→「{LIMIT_FIX[old_limit]}」")
        tgt = _get(eff, "target")
        if not tgt or str(_get(tgt, "filter_kind") or "") != "archetype":
            continue
        if not str(_get(tgt, "filter_value") or "").strip() and arch:
            _set(tgt, "filter_value", arch)
            notes.append(f"第 {i} 条效果的对象字段名补为「{arch}」")
        if not str(_get(tgt, "setcode") or "").strip() and code:
            _set(tgt, "setcode", code)
            notes.append(f"第 {i} 条效果的对象字段码补为 {code}")
    return notes


def regenerate(spec: CardSpec) -> None:
    """按应用自己的投影重生成卡文 + 脚本 + 文本槽位。

    卡文与脚本都是 IR 的投影（这是这个工具的立身之本：不会出现「文本说一套、
    脚本做一套」）。这次 IR 补了字段码、投影语序也照官方主流校正了，
    所以三样必须一起重生成；只改脚本会把 ``spec.strings`` 与 ``text_i18n``
    拆成两套词，G2 的 Stringid↔texts 同步检查立刻就得报错。
    语言按卡片原有 ``text_i18n`` 的键走，不给人家没写过的语言。
    """
    from cardforge.content.lua import emit
    from cardforge.content.psct import gen
    langs = list((spec.text_i18n or {}).keys()) or ["zh_cn"]
    try:
        gen.fill_spec(spec, langs)
    except Exception as e:                                # noqa: BLE001
        print(f"[WARN] {spec.name} 卡文重生成失败：{e}")
    try:
        spec.lua = emit.emit_script(spec)
        spec.strings = list(emit.emit_strings(spec) or [])
    except Exception as e:                                # noqa: BLE001
        print(f"[WARN] {spec.name} 脚本重生成失败：{e}")


def main() -> int:
    fix_bibles()
    total = 0
    for it in repo.list_cards(""):
        cid = int(it["id"])
        spec = repo.load_card(cid, it.get("archetype") or "")
        if spec is None:
            continue
        code = ARCH_SETCODE.get(str(spec.archetype or "").strip(), "")
        changed = False
        if code and str(spec.setcode or "") != code:
            print(f"[FIX ] {spec.name} setcode {spec.setcode} → {code}")
            spec.setcode = code
            changed = True
        notes = fix_targets(spec, code)
        if notes:
            changed = True
            for n in notes:
                print(f"       · {n}")
        if changed:
            regenerate(spec)
            repo.save_card(spec, snapshot=True, note="字段码与检索对象修复")
            total += 1
    print(f"\n共修复 {total} 张卡")
    # 复跑一遍质量门，确认修完不再有目标相关的 ERROR
    from cardforge.content import design
    for it in repo.list_cards(""):
        spec = repo.load_card(int(it["id"]), it.get("archetype") or "")
        if spec is None:
            continue
        bad = [f"{i.level}:{i.code} {i.message}" for i in design.audit_card(spec, None)
               if i.level == "ERROR" and "TARGET" in i.code]
        if bad:
            print(f"[残留] {spec.name}: " + "；".join(bad))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
