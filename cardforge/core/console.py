"""控制台输出编码自适应 —— 修掉「Windows 中文环境一打开就报错」。

根因
----
中文 Windows 的控制台默认代码页是 **GBK(cp936)**，Python 因此把
``sys.stdout.encoding`` 报成 ``gbk``。而 CardForge 的输出里必然含有：

* 中文卡名与卡文（GBK 能编，侥幸不炸）
* ``✓`` ``✗``（U+2713 / U+2717）—— **GBK 里没有**
* ``─`` ``═``（GBK 里有，但 U+2500 之外的制表符不一定）
* ①②③（GBK 里有）
* 日文、韩文、西语重音字母（GBK 里没有）

结果就是 ``UnicodeEncodeError: 'gbk' codec can't encode character '\\u2713'``
直接从 ``cli.main()`` 的兜底 except 里冒出来 —— 表现为「软件启动不了」，
而真正的问题跟功能一点关系都没有，只是控制台不许我们说话。

处理顺序
--------
1. Windows 上先把控制台输出代码页切到 **UTF-8(65001)**（``SetConsoleOutputCP``）。
2. 无论第 1 步成败，都把 ``sys.stdout`` / ``sys.stderr`` **重配为 UTF-8 +
   ``errors="replace"``**：重配保证字节流是 UTF-8，``replace`` 保证**任何**
   字形都不会把进程打死（最坏是看到一个 ``?``，而不是崩溃）。
3. ``sys.stdout is None``（``pythonw`` / GUI 启动）时换成静默写入器，
   免得任何一处 ``print`` 都把服务打断。

用户显式设了 ``PYTHONIOENCODING`` 时**不覆盖他的选择**，只补 ``errors``。
"""
from __future__ import annotations

import ctypes
import io
import os
import sys

__all__ = ["setup", "is_utf8_console", "describe", "eprint", "CANNOT_ENCODE"]

#: 兜底占位符。用 ASCII，确保任何代码页下都发得出去。
CANNOT_ENCODE = "?"

_DONE = False
_CONSOLE_CP: int | None = None


# ══════════════════════════════════════════════════════════════════════
#  Windows 控制台代码页
# ══════════════════════════════════════════════════════════════════════
def _set_console_cp(cp: int = 65001) -> int | None:
    """把 Windows 控制台输出代码页切到 ``cp``。非 Windows / 失败返回 None。

    ⚠ 只切 **Output** CP。``SetConsoleCP``（输入）会影响键盘输入解释，
    我们没有读控制台输入的需求，切了反而可能干扰中文输入法。
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        kernel32 = ctypes.windll.kernel32          # type: ignore[attr-defined]
        ok = bool(kernel32.SetConsoleOutputCP(cp))
        return cp if ok else None
    except Exception:
        return None


def _looks_like_console(stream) -> bool:
    try:
        return bool(stream) and stream.isatty()
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
#  空输出流（pythonw / 服务化启动）
# ══════════════════════════════════════════════════════════════════════
class _SilentWriter:
    """``sys.stdout is None`` 时的替身：吞掉一切，但保持文件接口形状。

    刻意不做任何编码 —— 目的就是**绝不允许** ``print`` 抛异常。
    """

    encoding = "utf-8"
    errors = "replace"
    writable = True

    def write(self, s) -> int:  # noqa: D401 - 接口需要
        return len(s) if isinstance(s, str) else 0

    def writelines(self, seq) -> None:
        return None

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise OSError("CardForge：当前进程没有可用的标准输出")

    @property
    def buffer(self):  # 让 io.TextIOWrapper 之类的探测不至于炸
        raise OSError("CardForge：当前进程没有可用的标准输出")


def _reconfigure(stream, encoding: str):
    """把一个流重配成 ``encoding`` + ``errors="replace"``，失败则整包替换。"""
    if stream is None:
        return _SilentWriter()
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding=encoding, errors="replace", line_buffering=True)
            return stream
        except Exception:
            pass
    # 兜底：包一层 UTF-8 writer（重定向到字节流的情形）
    try:
        buffer = getattr(stream, "buffer", None)
        if isinstance(buffer, io.BufferedIOBase):
            return io.TextIOWrapper(buffer, encoding=encoding,
                                    errors="replace", line_buffering=True)
    except Exception:
        pass
    return stream


# ══════════════════════════════════════════════════════════════════════
#  对外入口
# ══════════════════════════════════════════════════════════════════════
def setup(force: bool = False) -> dict:
    """在 CLI / 服务入口最前面调用一次。幂等，``force=True`` 可重跑。

    返回实际做了什么（供 ``doctor`` 与人排障）。
    """
    global _DONE, _CONSOLE_CP
    if _DONE and not force:
        return describe()

    # 用户自己指定了 IO 编码就尊重他，只补上 errors
    user_enc = (os.environ.get("PYTHONIOENCODING") or "").split(":")[0].strip()
    want = user_enc or "utf-8"

    if _CONSOLE_CP is None:
        _CONSOLE_CP = _set_console_cp(65001)

    sys.stdout = _reconfigure(sys.stdout, want)
    sys.stderr = _reconfigure(sys.stderr, want)

    _DONE = True
    return describe()


def is_utf8_console() -> bool:
    """当前是否处于「能安全打印中文与 ✓」的状态（保守判定）。"""
    enc = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
    return _DONE and enc in {"utf8", "utf8mb4", "cp65001", "utf8surrogateescape"}


def describe() -> dict:
    """当前控制台状态报告（``doctor`` 用）。"""
    return {
        "configured": _DONE,
        "platform": sys.platform,
        "stdout_encoding": getattr(sys.stdout, "encoding", "") or "",
        "stderr_encoding": getattr(sys.stderr, "encoding", "") or "",
        "console_cp": _CONSOLE_CP,
        "isatty": _looks_like_console(sys.stdout),
        "user_io_encoding": os.environ.get("PYTHONIOENCODING", ""),
    }


def eprint(*a, **kw) -> None:
    """安全打印：任何字形、任何代码页下都**不会**抛 ``UnicodeEncodeError``。

    需要「真的写到控制台」的场景（进度、错误提示）用这个而不是裸 ``print``。
    """
    setup()
    stream = kw.pop("file", None) or sys.stderr
    sep = kw.pop("sep", " ")
    end = kw.pop("end", "\n")
    text = sep.join(str(x) for x in a) + end
    try:
        stream.write(text)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", "ascii") or "ascii"
        stream.write(text.encode(enc, errors=CANNOT_ENCODE).decode(enc, errors="replace"))
    except Exception:
        pass
    try:
        stream.flush()
    except Exception:
        pass
