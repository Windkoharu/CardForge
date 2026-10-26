# -*- coding: utf-8 -*-
"""回归锁：界面那条路（kernel）必须让「只有预览脚本」的卡跑得通 G3。

复现记录（2026-10-26 更新后，在本机实测）
----------------------------------------
``210000021`` 的 ``spec.json`` 里没有 ``lua`` 字段，``workspace/script/``
下也没有 ``c210000021.lua``。于是：

* ``POST /api/gates/G3`` → ``fail``，4 项「没有 Lua 脚本」；
* 同一张卡 ``210000011``（旧卡，``lua`` 已持久化）→ ``pass``，11 回合。

根因不是卡，是接线：``kernel._gate_cached`` 把**原始 spec** 传给了
``gates.g3_duel``，而预览脚本只投影在**副本**上（``_lua_of``）；新卡不再把
``lua`` 写回 ``spec.json``，G3 手里就永远是空的。

修法（本次）
------------
1. ``cardforge/server/kernel.py``：G2 / G3 共用同一份投影 spec；
2. ``cardforge/pipeline/gates.py::_spec_with_script``：spec 没脚本时兜底读
   落盘的 ``c<卡号>.lua``（只读文件、只改副本）；
3. ``cardforge/cli.py``：``card verify`` 与界面同口径，先投影再进 G3。

断言
----
1. ``g3_duel(原始 spec)``：确实没有脚本时必须是 ``fail``（不许假装跑过）；
2. ``kernel._gate_cached(spec, "G3")``：与界面同一条路，必须 ``pass``；
3. 把脚本落到 ``workspace/script/c<卡号>.lua`` 后，``g3_duel(原始 spec)``
   必须能自己读进来并 ``pass``（兜底生效），用例跑完删除该文件。

跑法：``python _probe/g3_projection_probe.py [卡号]``
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardforge.core import paths                  # noqa: E402
from cardforge.pool import repo                   # noqa: E402
from cardforge.content.lua import emit            # noqa: E402
from cardforge.pipeline import gates              # noqa: E402
from cardforge.server import kernel               # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def run(cid: int, arch: str) -> int:
    spec = repo.load_card(cid, arch)
    print(f"卡号 {cid}：spec.lua={'有' if (spec.lua or '').strip() else '空'}，"
          f"落盘脚本存在={paths.script_path(cid).exists()}")

    # ① 真没有脚本时，G3 必须如实 fail —— 不能因为「跑完了」就算过
    raw = gates.g3_duel(spec, duels=1)
    check("① 无脚本 → fail（不谎报）", raw.status == "fail", raw.summary[:60])
    has_no_script = any("没有 Lua 脚本" in i.message for i in raw.issues)
    check("① fail 的原因是「没有脚本」而非引擎报错", has_no_script)

    # ② 界面同一条路：投影后的 spec 进 G3，必须 pass
    rep = kernel._gate_cached(spec, "G3")
    ok = str(rep.get("status")) in ("pass", "warn")
    check("② kernel 路径 → pass（界面看到的就是这个）", ok,
          f"{rep.get('status')} {rep.get('summary', '')[:70]}")

    # ③ 落盘脚本的兜底：写一份 c<卡号>.lua，g3_duel 应自己读进来
    p = Path(paths.script_path(cid))
    body = emit.emit_script(repo.load_card(cid, arch))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        back = gates.g3_duel(repo.load_card(cid, arch), duels=1)
        check("③ 有落盘脚本 → 自动读取并 pass", back.status in ("pass", "warn"),
              back.summary[:70])
    finally:
        if p.exists():
            p.unlink()
        check("③ 清理：临时脚本已删除", not p.exists())

    print(f"\n结论：{'全部通过' if not FAILS else '有 ' + str(len(FAILS)) + ' 项失败'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(run(int(sys.argv[1]) if len(sys.argv) > 1 else 210000021, "圣痕"))
