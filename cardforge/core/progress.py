"""启动进度条 —— 给「双击就看得见」的那十几秒用。

设计约束（都是踩过的坑）
------------------------
1. **必须真实**：进度只跟着**真实步骤**走（自检的每一检查项、端口绑定、就绪），
   没有一条是定时器演的。演出来的进度条一旦和实际不符，就变成骗人的东西 ——
   而这个项目的第一原则就是不骗人。
2. **不是 TTY 就降级**：重定向到文件 / 被测试脚本调用时，``\\r`` 重绘会变成
   一堆乱码。非 TTY 时改成一行一个步骤的普通日志，内容一样全。
3. **不依赖颜色**：老 Windows 控制台对 ANSI 转义支持不一，纯文本 + 方块字符
   在任何终端都立得住（编码由 ``core.console`` 兜底成 UTF-8）。
4. **不阻塞主流程**：任何绘制异常都吞掉 —— 进度条坏了不能影响启动本身。
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Optional, TextIO

__all__ = ["Progress", "enabled_by_default"]

_FULL = "█"
_EMPTY = "░"
_MARK = "▓"

#: 环境变量开关：
#:   CARDFORGE_NO_PROGRESS=1  → 关（CI / 日志采集用，off 优先）
#:   CARDFORGE_PROGRESS=1     → 强制开（想把启动过程录进日志、或终端识别不准时用）
def enabled_by_default(stream: Optional[TextIO] = None) -> bool:
    off = str(os.environ.get("CARDFORGE_NO_PROGRESS", "")).strip().lower()
    if off in ("1", "true", "yes", "on"):
        return False
    force = str(os.environ.get("CARDFORGE_PROGRESS", "")).strip().lower()
    if force in ("1", "true", "yes", "on"):
        return True
    s = stream if stream is not None else sys.stdout
    try:
        return bool(s and s.isatty())
    except Exception:
        return False


class Progress:
    """一条进度条：``sub()`` 报当前子步骤，``advance()`` 报确定进度，``done()`` 收尾。

    典型用法::

        p = Progress("CardForge 卡锻 2.0 · 启动中")
        p.sub("环境自检")                  # 不确定进度阶段（条内滑动块）
        p.advance(0.4, "绑定端口")          # 确定进度阶段
        p.done("已就绪 → http://127.0.0.1:8790")
    """

    def __init__(self, title: str = "", *, width: int = 26,
                 stream: Optional[TextIO] = None, enabled: Optional[bool] = None):
        self.stream = stream if stream is not None else sys.stdout
        self.enabled = enabled_by_default(self.stream) if enabled is None else bool(enabled)
        try:
            cols = shutil.get_terminal_size((100, 24)).columns
        except Exception:
            cols = 100
        self.width = max(10, min(width, max(10, cols - 46)))
        self.title = title
        self._last_len = 0
        self._frac = 0.0
        self._tick = 0
        self._started = False
        self.lines: list[str] = []         # 每个走过的步骤（非 TTY 时逐行打印）

    # ── 输出原语（永远不抛）──────────────────────────────────────
    def _write(self, text: str, *, newline: bool = False) -> None:
        try:
            from . import console
            console.eprint(text, file=self.stream,
                           end="\n" if newline else "")
        except Exception:
            try:
                self.stream.write(text + ("\n" if newline else ""))
                self.stream.flush()
            except Exception:
                pass

    def _header(self) -> None:
        if self._started:
            return
        self._started = True
        if self.title:
            if self.enabled:
                self._write("\n  " + self.title + "\n  " + "─" * min(58, self.width + 22) + "\n")
            else:
                self._write("\n  " + self.title + "\n")

    def _bar(self, frac: float, label: str) -> str:
        frac = max(0.0, min(1.0, float(frac or 0.0)))
        filled = int(round(self.width * frac))
        cells = [_EMPTY] * self.width
        for i in range(filled):
            cells[i] = _FULL
        if frac < 1.0 and filled < self.width:
            cells[filled] = _MARK           # 条头一格用中间色调，视觉上"正在走"
        pct = f"{int(frac * 100):3d}%"
        return f"  [{''.join(cells)}] {pct}  {label}"

    # ── 对外 ────────────────────────────────────────────────────
    def sub(self, label: str) -> None:
        """进入一个**子步骤**（项数未知时用滑动块表示"正在做"）。"""
        self._header()
        self._tick += 1
        self.lines.append(label)
        if not self.enabled:
            self._write(f"  · {label}\n")
            return
        # 滑动块：在已有进度条上让一格高亮从左往右游走
        base = self._frac
        span = max(1, self.width - 2)
        pos = self._tick % span
        cells = [_EMPTY] * self.width
        for i in range(int(self.width * base)):
            cells[i] = _FULL
        cells[min(self.width - 1, pos)] = _FULL
        label2 = label if len(label) <= 34 else label[:33] + "…"
        self._redraw(f"  [{''.join(cells)}]      {label2}")

    def advance(self, frac: float, label: str = "") -> None:
        """确定进度（0..1）。用于步骤数已知的阶段。"""
        self._header()
        self._frac = max(self._frac, float(frac or 0.0))
        if label:
            self.lines.append(label)
        if not self.enabled:
            if label:
                self._write(f"  · {label}\n")
            return
        self._redraw(self._bar(self._frac, self._clip(label)))

    def done(self, text: str = "") -> None:
        self._header()
        self._frac = 1.0
        if not self.enabled:
            if text:
                self._write("  ✓ " + text + "\n")
            return
        self._redraw(self._bar(1.0, self._clip(text or "完成")))
        self._write("\n")

    def fail(self, text: str) -> None:
        self._header()
        if not self.enabled:
            self._write("  ✗ " + text + "\n")
            return
        self._write("\n  ✗ " + text + "\n")

    def note(self, text: str) -> None:
        """在条下面补一行说明（不打断条本身）。"""
        self._header()
        if not self.enabled:
            self._write("    " + text + "\n")
            return
        self._write("\n    " + text + "\n")

    # ── 内部 ────────────────────────────────────────────────────
    def _clip(self, label: str) -> str:
        maxlen = max(20, shutil.get_terminal_size((100, 24)).columns - self.width - 12)
        return label if len(label) <= maxlen else label[:maxlen - 1] + "…"

    def _redraw(self, line: str) -> None:
        pad = max(0, self._last_len - len(line))
        self._last_len = len(line)
        self._write("\r" + line + " " * pad)
