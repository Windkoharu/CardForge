"""一键跑完全部自测，并把结果汇总成一份报告。

用法::

    python _probe/pool_export/run_all.py

每步一个独立进程（仓库自测需要先设 WORKSPACE 环境变量），退出码非 0 即失败。
汇总写到 ``_probe/pool_export/_out/REPORT.txt``。
"""
from __future__ import annotations

import io
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "_out"
OUT.mkdir(parents=True, exist_ok=True)

#: (脚本, 说明, 对应交付项)
STEPS: list[tuple[str, str, str]] = [
    ("p0_schema.py", "官方 cdb 真实 schema（PRAGMA table_info）", "自测 1 前置"),
    ("p0b_conventions.py", "字段约定：ot / 灵摆 desc / 连接 def / setcode 打包 / 换行",
     "自测 1 前置"),
    ("p0c_numeric.py", "atk·def 的 '?' 编码 / str1..16 使用率 / 字段查重语义", "自测 1 前置"),
    ("p0d_frames_scale.py", "core.FRAMES.base 偏差 + 灵摆刻度存储位置", "风险实测"),
    ("p0e_pendulum_pack.py", "灵摆 level 列打包编码（398/398 对齐 desc）", "风险实测"),
    ("p1_official.py", "官方卡池只读查询（pool/official.py）", "自测 1"),
    ("p2_repo.py", "仓库 CRUD + 增量快照 + 回滚 + v0.x 迁移（pool/repo.py）", "自测 2"),
    ("p3_build_verify.py", "打真包 + G5 自检 + 独立 sqlite3 读回 + BOM（export/expansions.py）",
     "自测 3/4/5"),
    ("p4_ydk.py", ".ydk 读写与校验（export/ydk.py）", "自测 6"),
    ("p5_install.py", "EDOPro 探测 / 备份式安装 / zip 分发（export/install.py）", "自测 7"),
    ("p6_strings.py", "strings.conf 渲染·解析·往返·合并（export/strings.py）", "附加"),
    ("p7_misc.py", "边角 API：补列 / 多语言 / 失败分支 / 空输入", "附加"),
    ("p8_smoke.py", "包级 import / PEP 562 惰性转发 / 契约签名比对 / 编译", "附加"),
    ("p9_static.py", "静态自查：未使用的 import / 死代码 / TODO 残留", "附加"),
    ("p10_integration.py", "与兄弟模块 cli.py / pipeline.gates 的接口对齐", "集成"),
]


def main() -> int:
    lines: list[str] = []
    rows: list[tuple[str, str, bool, float, str]] = []
    for script, desc, item in STEPS:
        path = HERE / script
        if not path.is_file():
            rows.append((script, desc, False, 0.0, "脚本缺失"))
            continue
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, str(path)], cwd=str(ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        took = time.time() - t0
        text = proc.stdout.decode("utf-8", "replace")
        (OUT / f"{path.stem}_stdout.txt").write_text(text, encoding="utf-8")
        verdict = ""
        for ln in text.splitlines():
            if ln.startswith("断言："):
                verdict = ln.strip()
        ok = proc.returncode == 0
        rows.append((script, desc, ok, took, verdict or f"退出码 {proc.returncode}"))

    lines.append("CardForge 2.0 · pool/ + export/ 自测汇总")
    lines.append("=" * 78)
    n_ok = sum(1 for r in rows if r[2])
    for script, desc, ok, took, verdict in rows:
        lines.append(f"[{'OK  ' if ok else 'FAIL'}] {script:<24} {took:6.2f}s  {desc}")
        lines.append(f"         └─ {verdict}")
    lines.append("=" * 78)
    lines.append(f"合计 {n_ok}/{len(rows)} 步通过")
    lines.append("")
    lines.append("明细报告（UTF-8）：" + ", ".join(sorted(p.name for p in OUT.glob("p*.txt"))))
    report = "\n".join(lines)
    (OUT / "REPORT.txt").write_text(report, encoding="utf-8")
    print(report)
    return 0 if n_ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
