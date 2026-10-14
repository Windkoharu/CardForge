"""自测 8（附加）：strings.conf 渲染 / 解析 / 往返 / 合并。

覆盖：基本渲染、注释与空行、未知指令原样保留、解析→渲染无损往返、十六进制键归一化、
与**旧工程真实产物** `workspace/out/expansions/strings.conf` 的对照解析、merge 幂等、
写盘 UTF-8 无 BOM。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
sys.path.insert(0, str(ROOT))

from cardforge.export import strings as S                    # noqa: E402

OUT = ROOT / "_probe" / "pool_export" / "_out"
TMP = ROOT / "_probe" / "pool_export" / "_tmp" / "strings"
TMP.mkdir(parents=True, exist_ok=True)
lines: list[str] = []
fails: list[str] = []


def p(s: str = "") -> None:
    lines.append(str(s))


def check(label: str, ok: bool, detail: str = "") -> None:
    if not ok:
        fails.append(label)
    p(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  —— {detail}" if detail else ""))


p("── 1. render 基本形态 ──")
txt = S.render({0x1001: "星奏", "0x3001": "焰刃"}, {0x1: "星奏指示物"}, {0x2: "星奏计数器"})
for ln in txt.splitlines():
    p(f"  │ {ln}")
check("首行是注释", txt.startswith("# CardForge"))
check("!setname 按十六进制升序", txt.index("0x1001") < txt.index("0x3001"))
check("!counter_alias 也支持", "!counter_alias 0x2 星奏计数器" in txt)
check("以单个 \\n 结尾", txt.endswith("\n") and not txt.endswith("\n\n"))
p()

p("── 2. hexkey 归一化 ──")
cases = [(4097, "0x1001"), ("0x1001", "0x1001"), ("0x1001".upper(), "0x1001"),
         ("1001", "0x1001"), (0, "0x0"), ("", "0x0"),
         ("不是十六进制", "不是十六进制"), (True, "0x1")]
for src, expect in cases:
    got = S.hexkey(src)
    check(f"hexkey({src!r}) == {expect!r}", got == expect, f"实际 {got!r}")
check("小写 0x 也被收敛成大写",
      S.render({"0xabcd": "x"}).count("!setname 0xABCD x") == 1)
p()

p("── 3. parse：注释 / 空行 / 未知指令 ──")
src = ("# 顶部注释\n"
       "\n"
       "!setname 0x1001 星奏\n"
       "!counter 0x1 星奏指示物\n"
       "!victory 0x1 自定义胜利条件\n"      # 未知指令 → 原样保留
       "这不是指令行\n"                      # 非 ! 开头 → 也算 unknown
       "# 中间注释\n"
       "!setname 0x1002 带 空格 的 名字\n")
parsed = S.parse(src)
p(f"  setnames       = {parsed['setnames']}")
p(f"  counters       = {parsed['counters']}")
p(f"  counters_alias = {parsed['counters_alias']}")
p(f"  unknown        = {parsed['unknown']}")
p(f"  comments       = {parsed['comments']}")
check("解析出 2 个 setname", len(parsed["setnames"]) == 2)
check("名字里的空格被保留", parsed["setnames"]["0x1002"] == "带 空格 的 名字",
      repr(parsed["setnames"]["0x1002"]))
check("未知指令进 unknown", "!victory 0x1 自定义胜利条件" in parsed["unknown"])
check("非指令行进 unknown", "这不是指令行" in parsed["unknown"])
check("注释与空行进 comments", "# 顶部注释" in parsed["comments"]
      and "" in parsed["comments"])
p()

p("── 4. 往返：render(**parse(text)) 保留 unknown 与 comments ──")
again = S.render(parsed["setnames"], parsed["counters"], parsed["counters_alias"],
                 unknown=parsed["unknown"], comments=parsed["comments"], header="")
p("  往返结果：")
for ln in again.splitlines():
    p(f"  │ {ln}")
re2 = S.parse(again)
check("setnames 往返不变", re2["setnames"] == parsed["setnames"])
check("unknown 往返不变", re2["unknown"] == parsed["unknown"])
check("再次往返逐字节相同",
      S.render(re2["setnames"], re2["counters"], re2["counters_alias"],
               unknown=re2["unknown"], comments=re2["comments"], header="") == again)
p()

p("── 5. 对照旧工程真实产物 ──")
old = Path(r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge\workspace\out"
           r"\expansions\strings.conf")
if old.is_file():
    raw = old.read_bytes()
    p(f"  {old}")
    p(f"  字节 = {raw!r}")
    op = S.parse(raw.decode("utf-8"))
    p(f"  解析 = {op['setnames']} / unknown={op['unknown']}")
    check("旧产物的 !setname 0x1001 星奏 解析正确", op["setnames"] == {"0x1001": "星奏"},
          str(op["setnames"]))
    check("旧产物无 unknown", op["unknown"] == [], str(op["unknown"]))
    # 用我们的实现重写一份，语义应等价
    rewritten = S.render(op["setnames"], op["counters"])
    check("重写后语义等价", S.parse(rewritten)["setnames"] == op["setnames"])
    p(f"  重写后 = {rewritten!r}")
else:
    p("  旧工程产物不存在，跳过")
p()

p("── 6. write / read：UTF-8 无 BOM ──")
f = TMP / "strings.conf"
S.write(f, setnames={0x1001: "星奏"}, counters={0x1: "星奏指示物"})
rawb = f.read_bytes()
p(f"  前 3 字节 = {rawb[:3]!r}  大小 = {len(rawb)}")
check("无 BOM", rawb[:3] != b"\xef\xbb\xbf")
check("read 回来一致", S.read(f)["setnames"] == {"0x1001": "星奏"})
check("读不存在的文件返回空结构（不抛异常）",
      S.read(TMP / "没有这个文件.conf")["setnames"] == {})
check("带 BOM 的历史文件也能读（utf-8-sig 容错）",
      S.parse(b"\xef\xbb\xbf!setname 0x1 a\n".decode("utf-8-sig"))["setnames"]
      == {"0x1": "a"})
p()

p("── 7. merge：受管区块替换而非追加 ──")
base = "# 用户自己的\n!system 1000 0\n"
m1 = S.merge(base, tag="t", setnames={0x1: "A"})
m2 = S.merge(m1, tag="t", setnames={0x2: "B"})
m3 = S.merge(m2, tag="t", setnames={0x2: "B"})
for tag, m in (("第一次", m1), ("第二次", m2), ("第三次", m3)):
    p(f"  {tag}：")
    for ln in m.splitlines():
        p(f"    │ {ln}")
check("用户内容始终保留", all("!system 1000 0" in m for m in (m1, m2, m3)))
check("第二次替换掉旧指令（0x1 消失）", "!setname 0x1 A" not in m2)
check("第二次写入新指令", "!setname 0x2 B" in m2)
check("幂等：第三次与第二次逐字节相同", m3 == m2)
check("区块标记成对且只有一组",
      m3.count("# >>> CardForge t >>>") == 1 and m3.count("# <<< CardForge t <<<") == 1)
check("不同 tag 互不干扰",
      S.merge(m3, tag="other", counters={0x1: "C"}).count("# >>> CardForge") == 2)
p()

p("═" * 68)
p(f"断言：{'全部通过' if not fails else '失败 ' + str(len(fails)) + ' 项'}")
for f2 in fails:
    p(f"  !! FAIL: {f2}")
p("═" * 68)

OUT.joinpath("p6_strings.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
sys.exit(1 if fails else 0)
