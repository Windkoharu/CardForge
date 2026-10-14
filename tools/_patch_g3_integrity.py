"""修正 G3 的「假通过」：引擎在但驱动模块缺失时必须降级为 skipped。

背景：``duel.engine.detect()`` 在本机返回 ``level="ocgcore"``（vendor/engine/ocgcore.dll
真的能加载），于是 g3_duel 走进了"跑对局"分支；但 ``duel/scenario.py`` 与 ``duel/bot.py``
还没实现，两个 _try_import 都返回 None，结果 issues 为空 → 报告成 ``pass``。

**这违反了项目自己的原则：绝不假装跑过对局。** 修法是加一个 ran_anything 标志，
没真跑过任何验证就返回 skipped 并写明缺什么。
"""
import ast
import pathlib

P = (pathlib.Path(__file__).resolve().parents[1]
     / "cardforge" / "pipeline" / "gates.py")
s = P.read_text(encoding="utf-8")
orig = s

# ① 加 ran_anything 初始化
s = s.replace(
    "    issues: list[Issue] = []\n    detail: dict = {}\n    try:\n"
    "        if scenario:",
    "    issues: list[Issue] = []\n    detail: dict = {}\n"
    "    ran_anything = False          # 真的跑过至少一项验证吗？\n"
    "    try:\n        if scenario:",
    1,
)

# ② 场景跑过 → 标记
s = s.replace(
    "                    res = sc_mod.run_batch(list(builtin)[:4], [spec]) or []\n"
    "                    for r in res:",
    "                    res = sc_mod.run_batch(list(builtin)[:4], [spec]) or []\n"
    "                    ran_anything = True\n"
    "                    for r in res:",
    1,
)

# ③ 整局跑过 → 标记
s = s.replace(
    "                res = run(dk, dk, seed=1, max_steps=3000, cards={spec.id: spec})\n"
    "                detail[\"duels\"] = 1",
    "                res = run(dk, dk, seed=1, max_steps=3000, cards={spec.id: spec})\n"
    "                ran_anything = True\n"
    "                detail[\"duels\"] = 1",
    1,
)

# ④ 异常分支也算"跑过"（有结论）
s = s.replace(
    "                            message=f\"实跑验证执行失败：{e}\", hint=\"请反馈此问题\"))\n\n"
    "    rep = _report(\"G3\", issues, t0=t0)",
    "                            message=f\"实跑验证执行失败：{e}\", hint=\"请反馈此问题\"))\n"
    "        ran_anything = True\n\n"
    "    # ⚠ 引擎在、但驱动模块还没就绪时，**绝不能报 pass** —— 那等于假装跑过对局。\n"
    "    #   必须显式降级为 skipped 并写清缺什么。\n"
    "    if not ran_anything:\n"
    "        return GateReport(\n"
    "            gate=\"G3\", status=\"skipped\", issues=issues,\n"
    "            summary=\"对局引擎可用，但对局驱动模块尚未就绪，未实际运行任何验证\",\n"
    "            took_ms=int((time.perf_counter() - t0) * 1000),\n"
    "            degraded=\"驱动模块缺失（duel/scenario.py 与 duel/bot.py）；\"\n"
    "                     \"在此之前 G3 无法给出实跑结论\",\n"
    "        )\n\n"
    "    rep = _report(\"G3\", issues, t0=t0)",
    1,
)

if s == orig:
    print("[X] 没有匹配到任何片段，未修改")
    raise SystemExit(1)
ast.parse(s)
P.write_text(s, encoding="utf-8", newline="")
print("[OK] gates.py 已修正，语法检查通过")
