"""卡面文字排版引擎 —— 断行、禁则、悬挂缩进、两方向自适应、PSCT 强调。

本模块只做**排版**，不碰素材、不碰卡框、不认识 ``CardSpec``：
字体一律由调用方通过 ``font_of(size) -> ImageFont`` 回调传入（便于换字体、换字号、
以及单测注入假字体），因此不会与 :mod:`cardforge.render.assets` /
:mod:`cardforge.render.fonts` 形成循环依赖。

设计要点（对应旧版踩过的坑）
--------------------------
1. **断行按语言**：``LANGS[lang].wrap == "cjk"`` 走单字断行，``"word"`` 走词断行
   （标点吸附到前一个词，不留行首）。两种模式都会把**同一个 run 里的中英混排**
   再切成字符/词单元（``_units``），所以 ``"攻撃力500アップ"`` 这样的混排串
   也能在 ``500`` 与 ``アップ`` 之间断开。
2. **禁则**：行首不得出现 ``）」』】、。：；！？・ー～%,.!?:;)]}`` 等，
   行尾不得出现 ``（「『【([{`` 等。触发时**移动**相邻字符（把行首禁则字符拉回上一行、
   或把行尾禁则字符推到下一行），绝不静默丢弃任何字符。
3. **①②③ 悬挂缩进**：行首的 ``①``、``(1)``、``1.`` 之后的正文左边界成为续行的左边界，
   即首行比续行**少缩进**一个编号宽。
4. **两方向自适应**（:func:`fit`）：先在 ``FIT_PROFILES[profile]`` 里从大到小降字号
   （每档字号 × :func:`geometry.font_scale`），都不行才按
   ``COMPRESS["autoScaleXQuantifier"]`` 步长横压，最多压 ``maxAutoCompressionX``；
   仍放不下则返回最小档并置 ``overflow=True``（**不抛异常**）。
   横压时**可用宽度按 ``max_w / squeeze_x`` 放宽**，所以横压确实能多塞字；
   但搜索顺序是「字号优先、横压其次」，且同档内从 ``1.00`` 起试，不会像旧版那样
   一路压到 0.80 才停。
5. **中英混排间距**：CJK 与拉丁/数字相邻时自动补一点额外字距
   （:data:`CJK_LATIN_GAP` em），避免「贴在一起」；测量与绘制用同一套算法，
   保证 ``wrap`` 算得下就真的画得下。
6. **横向压缩**：Pillow 没有横向字距缩放，``squeeze_x < 1`` 时把整行先画到临时
   透明图再横向缩放粘贴；``squeeze_x == 1`` 直接画在目标画布上（省一次贴图）。
7. **性能**：字宽逐字符缓存 + 词宽按 token 缓存，累积宽度用**加法**而不是
   每加一个字就把整串重测一遍（旧版 476 字卡文因此要 2.7 s）。
   ``fit()`` 里同一档位只做一次 ``wrap()``，横压步长只重算行宽，不重跑断行。

坐标系
------
``box`` / ``xy`` / ``max_w`` / ``spacing`` 全部是**目标画布像素**，模块内部不做任何
``Frame`` 换算；调用方用 :meth:`geometry.Frame.box` 取好框、用
``frame.font(REF 字号)`` 取好字号再传进来即可。``size`` 是**最终像素字号**
（已含 ``font_scale(lang)``），可以直接喂给 ``font_of``。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from ..core.enums import LANGS
from .geometry import COMPRESS, FIT_PROFILES, font_scale, text_inset

try:  # Pillow 是唯一硬依赖；缺失时本模块仍可断行/标记，只是画不出来
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - 环境缺 Pillow
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]

__all__ = [
    "TextRun", "Fitted", "LineMetrics",
    "tokenize", "wrap", "wrap_sized", "fit", "draw_fitted", "mark_psct",
    "forbidden_line_start", "forbidden_line_end",
    "PsctSpan", "psct_spans", "measure_runs", "line_text", "plain_text",
    "token_width", "line_metrics", "render_lines", "clear_cache",
    "clear_font_cache", "PSCT_KEYWORDS", "CJK_LATIN_GAP", "HEURISTIC_CHAR_W",
    "FAUX_BOLD", "REF_SIZE",
]

#: 默认档位
DEFAULT_PROFILE = "description"

#: 横压量化步长（来自 COMPRESS，通常 0.01）
_QUANT = float(COMPRESS.get("autoScaleXQuantifier", 0.01) or 0.01)
#: 最多横压比例（0.20 = 最扁到 0.80）
_MAX_COMPRESS = float(COMPRESS.get("maxAutoCompressionX", 0.20) or 0.0)

#: CJK ↔ 拉丁/数字之间的额外字距（em）。官方中文卡文里「攻击力500」不贴字。
CJK_LATIN_GAP = 0.08
#: 拿不到真实字体宽度时（font_of 返回 None）的兜底半角字宽（em）
HEURISTIC_CHAR_W = 0.50
#: ``wrap()`` 没有字号参数，内部统一按这个基准字号量宽度（见 :func:`wrap` 文档）
REF_SIZE = 30
#: 硬换行（原文里的 ``\n``）产生的行标记：该行是**空行**，绘制时应跳过缩进
_HARD_BREAK = -1.0
#: 伪粗体的描边宽度（px）
FAUX_BOLD = 0.9
#: 伪斜体的横向切变量（相对行高）
FAUX_ITALIC_SHEAR = 0.18

#: 行首禁则 —— 中日文（按字断行的语言）
FORBIDDEN_START_CJK = (
    "）」』】〕〉》〗〙〛、。，．：；！？‥…・ー～ゝゞヽヾ"
    "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮ々"      # 小字假名不得起行
    "%,.!?:;)]}"
)
#: 行尾禁则 —— 中日文（开括号类不得被留在行尾）
FORBIDDEN_END_CJK = "（「『【〔〈《〖〘〚([{"
#: 行首禁则 —— 按词断行的语言（混排时中日标点仍可能出现）
FORBIDDEN_START_WORD = ",.;:!?)]}%、。，．：；！？‥…・ー～」』】〕〉》〗"

#: 「①」–「⑳」编号（段落起始标记，触发悬挂缩进）
_CIRCLED_NUM = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
#: 「（1）」「(1)」形式（括号编号，引用别卡效果时的固定写法，不受段落起点限制）
_RE_PAREN_LABEL = re.compile(r"^\s*[（(]\s*\d{1,2}\s*[)）]")
#: 「1.」「1：」形式 —— **仅在段落起始**才算编号（正文里的 ``1500。`` 不算）
_RE_BARE_LABEL = re.compile(r"^\s*\d{1,2}\s*[.、．:：]")
#: 编号后要紧跟的冒号 / 空白
_LABEL_TAIL = "：:．.、 \u3000\t"

# ══════════════════════════════════════════════════════════════════════
#  基础辅助
# ══════════════════════════════════════════════════════════════════════


def _is_cjk(ch: str) -> bool:
    """该字符是否属于「按字断行、与拉丁之间要补间距」的方块文字（CJK/假名/全角）。"""
    o = ord(ch)
    return (
        0x3400 <= o <= 0x4DBF        # 扩展 A
        or 0x4E00 <= o <= 0x9FFF     # 基本区
        or 0xF900 <= o <= 0xFAFF     # 兼容表意
        or 0x3000 <= o <= 0x303F     # CJK 标点（、。「」等）
        or 0x3040 <= o <= 0x30FF     # 平假名 / 片假名
        or 0xFF00 <= o <= 0xFFEF     # 全角形式（！？：；０-９Ａ-Ｚ）
        or 0x2E80 <= o <= 0x2EFF     # 部首补充
        or 0x31C0 <= o <= 0x31EF     # 笔画
        or 0x3200 <= o <= 0x32FF     # 带圈字符（①㊤）
        or 0x3300 <= o <= 0x33FF     # 平方单位
        or 0xFE30 <= o <= 0xFE4F     # 兼容标点
        or 0x1F200 <= o <= 0x1F2FF   # 带圈表意
    )


def _asciiish(ch: str) -> bool:
    """拉丁字母 / 数字 / 半角标点 —— 与 CJK 相邻时需要补间距的一侧。"""
    return ch.isascii() and not ch.isspace()


def _wordish(ch: str) -> bool:
    """词内字符：字母 / 数字 / 组合附加符号。"""
    return ch.isalnum() or unicodedata.category(ch).startswith("M")


def _is_space(ch: str) -> bool:
    return ch.isspace()


def _lang_wrap(lang: str) -> str:
    spec = LANGS.get((lang or "").strip().lower().replace("-", "_"))
    return getattr(spec, "wrap", "word") or "word"


def _norm_lang(lang: str) -> str:
    return (lang or "").strip().lower().replace("-", "_")


def _profile_tiers(profile: str) -> list[dict]:
    tiers = FIT_PROFILES.get(profile) or FIT_PROFILES.get(DEFAULT_PROFILE) or []
    return [dict(t) for t in tiers]


def _compress_steps() -> list[float]:
    """横压步长（从 1.00 递减），末项不小于 ``1 - maxAutoCompressionX``。"""
    q = _QUANT if _QUANT > 0 else 0.01
    n = int(round((_MAX_COMPRESS or 0.0) / q))
    steps = [round(1.0 - i * q, 4) for i in range(n + 1)]
    floor = round(max(0.05, 1.0 - (_MAX_COMPRESS or 0.0)), 4)
    return [s for s in steps if s >= floor - 1e-9] or [1.0]


def _hanging_split(tok: str, para_start: bool = True) -> tuple[str, str] | None:
    """把编号 token 拆成 ``(编号前缀, 其余)``；不是编号返回 ``None``。

    * ``①`` → ``("①：", "")``（``：`` 一起算进编号宽，续行正文才对得齐）
    * ``①：文`` → ``("①：", "文")``
    * ``(1)`` → ``("(1)：", "")``；``(1)Blah`` → ``("(1)", "Blah")``
    * ``1.`` → ``("1.", "")`` —— 仅当 ``para_start`` 为真（调用方还要用
      :func:`_para_ok_units` 证明确有段落起点），避免把正文里的 ``1500。`` 当编号
    """
    if not tok:
        return None
    cut = 0
    i = 0
    while i < len(tok) and tok[i] in _CIRCLED_NUM:
        i += 1
    if i:
        cut = i
    else:
        m = _RE_PAREN_LABEL.match(tok)
        if m:
            cut = m.end()
        elif para_start and (m := _RE_BARE_LABEL.match(tok)):
            cut = m.end()
        else:
            return None
    j = cut
    while j < len(tok) and tok[j] in _LABEL_TAIL:
        j += 1
    if j == cut and cut >= len(tok):
        return tok[:cut], ""
    return tok[:j], tok[j:]


def _hanging_indent(prefix: str, size: int, font_of: "FontOf",
                    para_start: bool = True) -> float:
    """行的前若干个字符若以编号开头，返回「编号 + 冒号 + 空白」的宽度，否则 0.0。

    这个宽度就是**续行的左缩进**（首行不缩进），即悬挂缩进。
    官方卡文写的是 ``①：正文``，续行若只让过 ``①`` 会与 ``：`` 差半格，
    所以把编号后紧跟的 ``：``/``:``/``.`` 也算进缩进，续行正好与**正文**左对齐。

    ``prefix`` 必须是**跨 run 拼起来**的行首文本（``mark_psct`` 会把 ``①`` 与 ``：``
    切成两个 run，只看第一个 run 会漏掉冒号）。
    """
    if not prefix:
        return 0.0
    split = _hanging_split(prefix, para_start)
    if split is None:
        return 0.0
    marker = split[0]
    if not marker.strip():
        return 0.0
    return float(token_width(marker, _font_for(font_of, size), size))


def _line_prefix(runs: Sequence["TextRun"], limit: int = 8) -> str:
    """跨 run 取行首至多 ``limit`` 个字符（编号 + 冒号常落在两个 run 里）。"""
    out: list[str] = []
    n = 0
    for run in runs:
        if not run.text or n >= limit:
            break
        take = run.text[: limit - n]
        out.append(take)
        n += len(take)
    return "".join(out)


def _para_ok_units(units: Sequence["_Unit"]) -> bool:
    """该处是否是**真正**的段落起点（原文里有显式换行）。

    裸编号（``1.``）只在段落起点才算编号：正文里的 ``1500。``/``3.5倍`` 不能被当成
    编号去缩进。中日文的 ``①`` 与 ``(1)`` 无歧义，不受此限。
    """
    for u in units:
        if not u.text:
            continue
        if u.text[0] == "\n":
            return True
        if u.text[0] in " \t\u3000":
            continue                       # 行首空白继续往后看
        return False
    return False


def _units_prefix(units: Sequence["_Unit"], limit: int = 8) -> str:
    """跨单元取行首至多 ``limit`` 个字符。"""
    out: list[str] = []
    n = 0
    for u in units:
        if n >= limit:
            break
        take = u.text[: limit - n]
        out.append(take)
        n += len(take)
    return "".join(out)


def _document_indent(runs: Sequence["TextRun"], size: int, font_of: "FontOf",
                     lang: str, para_start: bool = True) -> float:
    """一行的有效左缩进（= 该行若以编号开头，让过编号宽）。"""
    return _hanging_indent(_line_prefix(runs).lstrip(" \t\u3000"), size, font_of,
                           para_start)


def _indent_for_units(units: Sequence["_Unit"], size: int, font_of: "FontOf",
                      lang: str, para_start: bool) -> float:
    """给一组断行单元算左缩进。

    ``para_start`` 是调用方的判断（上一行是否收在句读点上），这里再与
    :func:`_para_ok_units` 的**硬证据**（原文显式换行）取与，避免把正文里的
    ``1500。`` 误判成 ``1.`` 编号。
    """
    ok = bool(para_start) and _para_ok_units(units)
    return _hanging_indent(_units_prefix(units).lstrip(" \t\u3000"), size, font_of, ok)


# ══════════════════════════════════════════════════════════════════════
#  数据结构
# ══════════════════════════════════════════════════════════════════════


@dataclass
class TextRun:
    """一段同样式文本。``size_scale`` 用于同段落内混排不同字号（精灵/注音）。"""
    text: str
    bold: bool = False
    italic: bool = False
    size_scale: float = 1.0

    def scaled(self, size: int) -> int:
        return max(1, int(round(size * (self.size_scale or 1.0))))


@dataclass
class Fitted:
    """一次自适应排版的结果。``squeeze_x`` 是**横向压缩比**（0.80~1.0）。

    ``indents`` 是**可选扩展**：每行的左缩进（px），由 :func:`fit` 填好，
    :func:`draw_fitted` 用它保证「① 段落续行与编号后正文对齐」。
    手搓 ``Fitted`` 时可以不管它（为空则退回按编号启发式判定）。
    """
    lines: list[list[TextRun]] = field(default_factory=list)
    size: int = 0
    line_height: float = 0.0
    squeeze_x: float = 1.0
    overflow: bool = False
    indents: list[float] = field(default_factory=list)
    # ── 内部：给 draw_fitted 还原「画布像素」用（见 text.fit 的单位约定）──
    #: ``font_of`` 会自己放大字号（``render/layers.py`` 那种写法）时为 True，
    #: 此时 :func:`draw_fitted` 应把 ``size`` 原样交给回调，由回调负责换算。
    _px_hint: bool = False
    #: 画布像素磅数（``size × Frame.k``），用于量度量与缩进换算
    _px_size: int = 0

    @property
    def n_lines(self) -> int:
        return len(self.lines)

    @property
    def block_height(self) -> float:
        return len(self.lines) * float(self.line_height)

    def texts(self) -> list[str]:
        """每行的纯文本（行数 = ``len(lines)``）。"""
        return [line_text(l) for l in self.lines]

    def joined(self) -> str:
        """把各行按 ``\\n`` 拼回纯文本（连续空行折成一个换行，便于落盘/比对）。"""
        return "\n".join(t for t in self.texts() if t)

    def indent_of(self, idx: int) -> float:
        """第 ``idx`` 行的左缩进（越界或未填时返回 0.0）。"""
        if 0 <= idx < len(self.indents):
            return float(self.indents[idx])
        return 0.0


@dataclass(frozen=True)
class LineMetrics:
    """真实字体度量（画基线用）。字体不可用时退回「``size`` 当作 ascent」的估算值。"""
    ascent: float
    descent: float
    height: float
    real: bool = True


# ══════════════════════════════════════════════════════════════════════
#  tokenize
# ══════════════════════════════════════════════════════════════════════


def tokenize(text: str, lang: str) -> list[str]:
    """把文本切成断行基本单元。**保证 ``"".join(...) == text``**（不丢空格）。

    * ``wrap == "cjk"``：CJK / 假名 / 全角标点逐字成 token；拉丁数字连成一个
      token（``2000`` 不会被拆）；空白各自成 token（换行时在行首丢弃）。
    * ``wrap == "word"``：按空白切词，并把紧跟在词后的标点（``,`` ``.`` ``"`` 等）
      吸附进同一个 token，避免 ``"the end,"`` 的逗号被甩到下一行行首。
    """
    out: list[str] = []
    if not text:
        return out
    if _lang_wrap(lang) == "cjk":
        buf: list[str] = []
        for ch in text:
            keep = _wordish(ch) or ch in "'\u2019-"
            if _is_cjk(ch) or not keep:
                if buf:
                    out.append("".join(buf))
                    buf = []
                out.append(ch)
            else:
                buf.append(ch)
        if buf:
            out.append("".join(buf))
        return out
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\n":
            out.append("\n")
            i += 1
            continue
        if _is_space(text[i]):
            j = i
            while j < n and _is_space(text[j]) and text[j] != "\n":
                j += 1
            out.append(text[i:j])
            i = j
            continue
        j = i
        while j < n and not _is_space(text[j]):
            j += 1
        k = j - i
        while k > 1 and (unicodedata.category(text[i + k - 1]).startswith("P")
                         or text[i + k - 1] in "\u201d\u2019"):
            k -= 1
        out.append(text[i:i + k])
        i += k
    return out


# ══════════════════════════════════════════════════════════════════════
#  禁则
# ══════════════════════════════════════════════════════════════════════


def forbidden_line_start(lang: str) -> str:
    """该语言下行首**不允许**出现的字符集合（返回字符串，逐字符 ``in`` 判定）。"""
    return FORBIDDEN_START_CJK if _lang_wrap(lang) == "cjk" else FORBIDDEN_START_WORD


def forbidden_line_end(lang: str) -> str:
    """该语言下行尾**不允许**出现的字符集合（开括号类不得被留在行尾）。"""
    return FORBIDDEN_END_CJK


# ══════════════════════════════════════════════════════════════════════
#  字宽测量（带缓存；CJK↔拉丁自动补间距）
# ══════════════════════════════════════════════════════════════════════

FontOf = Callable[[int], object]
#: 缓存上限，超过就整表清空（防止长时间运行下无限增长）
_CACHE_CAP = 200_000
#: ``font_of`` memo 的上限（缓存键里握着回调本身，防止 id 复用并限制内存）
_FONT_CACHE_CAP = 256
_font_cache: dict[tuple, object] = {}
_char_cache: dict[tuple, float] = {}
_tok_cache: dict[tuple, float] = {}
_met_cache: dict[tuple, tuple[float, float]] = {}


def _glyph_len(font, ch: str) -> float:
    """单个字符的前进宽度。"""
    get = getattr(font, "getlength", None)
    if callable(get):
        try:
            return float(get(ch))
        except Exception:
            pass
    try:                                   # 兜底：老版本 Pillow 只有 getbbox
        box = font.getbbox(ch)
        if box:
            return float(box[2] - box[0])
    except Exception:
        pass
    return 0.0


def _heuristic(char_w: float, ch: str) -> float:
    """没有字体对象时的估算字宽（px）。"""
    if ch == "\u3000":
        return char_w * 2.0
    wide = _is_cjk(ch) or unicodedata.east_asian_width(ch) in ("W", "F")
    return char_w * (2.0 if wide else 1.0)


def _char_w(font, ch: str, size: int) -> float:
    if font is None:
        return _heuristic(float(size) * HEURISTIC_CHAR_W, ch)
    key = (id(font), ch, size)
    hit = _char_cache.get(key)
    if hit is not None:
        return hit
    val = _glyph_len(font, ch)
    if len(_char_cache) > _CACHE_CAP:
        _char_cache.clear()
    _char_cache[key] = val
    return val


def _pair_gap(prev: str | None, ch: str) -> float:
    """相邻两字符之间是否需要补 CJK↔拉丁间距（返回 em 系数，0 或 ``CJK_LATIN_GAP``）。"""
    if prev is None:
        return 0.0
    if (_is_cjk(prev) and _asciiish(ch)) or (_asciiish(prev) and _is_cjk(ch)):
        return CJK_LATIN_GAP
    return 0.0


def token_width(tok: str, font, size: int) -> float:
    """一个 token 的渲染宽度（含 CJK↔拉丁额外间距）。"""
    if not tok:
        return 0.0
    key = (id(font) if font is not None else 0, tok, size)
    hit = _tok_cache.get(key)
    if hit is not None:
        return hit
    total = 0.0
    prev: str | None = None
    for ch in tok:
        total += _char_w(font, ch, size) + _pair_gap(prev, ch) * size
        prev = ch
    if len(_tok_cache) > _CACHE_CAP:
        _tok_cache.clear()
    _tok_cache[key] = total
    return total


def measure_runs(runs: Iterable[TextRun], font_of: FontOf | None, size: int) -> float:
    """量一段 run 的宽度（与 :func:`draw_fitted` 的绘制算法完全一致）。"""
    total = 0.0
    prev: str | None = None
    for run in runs:
        if not run.text:
            continue
        rs = run.scaled(size)
        font = _font_for(font_of, rs)
        for ch in run.text:
            total += _char_w(font, ch, rs) + _pair_gap(prev, ch) * rs
            prev = ch
    return total


def _font_for(font_of: FontOf | None, size: int):
    """安全取字体：回调缺失/抛异常/返回 None 一律降级为 None（走估算字宽）。

    带**memо 缓存**：``fit()`` 会对同一个字号问上几千次（每个断行单元、每个横压步长
    各一次），而 ``ImageFont.truetype`` 打开一个 25 MB 的中文字体要 ~15 ms ——
    不缓存的话一次 ``fit`` 能跑几十秒。缓存只记住「回调对该字号的答复」，
    因此要求 ``font_of`` 是**确定性**的（同一 size 给同一字体，这是本来就该有的性质）。
    调用方自己的缓存（如 ``frames.fonts.load`` 或按 size 建 dict）依然有效，两层不冲突。
    """
    if font_of is None:
        return None
    size = max(1, int(size))
    key = (id(font_of), font_of, size)
    hit = _font_cache.get(key)
    if hit is not None:
        return hit
    try:
        font = font_of(size)
    except Exception:
        font = None
    if len(_font_cache) > _FONT_CACHE_CAP:
        _font_cache.clear()
    _font_cache[key] = font
    return font or None


def clear_font_cache() -> None:
    """清空 ``font_of`` 的 memo（换字体/换皮肤后调用）。"""
    _font_cache.clear()
    _char_cache.clear()
    _tok_cache.clear()
    _met_cache.clear()


def _strict_font_of(font_of: FontOf) -> FontOf:
    """按「回调收到几磅就返回几磅」的约定包装 ``font_of``，并核对 ``font.size``。

    ``fit(..., size_scale=...)`` 的路径用它，也让 :func:`_probe_px` 能问出回调的换算倍率。
    像 ``render/layers.py`` 那样把 ``Frame.k`` 写进回调的调用方，一旦对回调的返回值
    再问一次（例如逐字符量宽 / 取基线度量），就会得到「k 的平方」那么大的字 ——
    这正是叠字的来源。这里按磅数缓存并校正，使本函数内部始终用「size 磅」的字体。
    """
    got: dict[int, object] = {}

    def resolve(size: int):
        size = max(1, int(size))
        if size in got:
            return got[size]
        raw = _font_for(font_of, size)          # 走 memo，避免重复打开 25MB 字体
        font = raw
        try:
            have = getattr(raw, "size", size) if raw is not None else size
            if raw is not None and isinstance(have, int) and have != size:
                path = getattr(raw, "path", None)
                if path:
                    font = ImageFont.truetype(path, size,
                                              index=int(getattr(raw, "index", 0) or 0))
        except Exception:
            font = raw
        got[size] = font
        return font

    return resolve


def _probe_px(cb: FontOf | None, ref_size: int) -> tuple[bool, int]:
    """探测 ``font_of`` 的换算约定，返回 ``(回调是否会自己放大, 画布像素磅数)``。

    :func:`_strict_font_of` 收出的字体其 ``.size`` 就是画布像素磅数；与 ``ref_size``
    不同即说明回调内部会放大字号（layers 式），此时 :func:`draw_fitted` 必须把
    ``size`` **原样**交给回调，而不能交像素磅数。
    """
    if cb is None:
        return False, max(1, int(ref_size))
    try:
        px = int(getattr(_strict_font_of(cb)(ref_size), "size", ref_size) or ref_size)
    except Exception:
        px = max(1, int(ref_size))
    return (px != int(ref_size)), max(1, px)


def _px_size_of(cb: FontOf | None, ref_size: int) -> int:
    """该基准磅数在画布上的实际磅数（未探测时即等于自身）。"""
    return _probe_px(cb, ref_size)[1]


def _ink_top(font, size: int) -> float:
    """字形墨迹顶到**基线**的距离（px）。

    CJK 字体的 ``getmetrics().ascent`` 往往**小于**汉字实际的墨迹高度
    （实测 ``msyh`` 100 px 时 ascent=106 但「永」墨高 ~118；``ygo-sc`` 86 vs 88），
    直接按 ascent 定位基线会让字顶冒进上一行 —— 就是「叠字」的来源。
    所以量一个代表字形（永/永 字八法覆盖横竖撇捺）的 bbox 作为校正依据。
    """
    for sample in ("永", "国", "H"):
        try:
            box = font.getbbox(sample)
        except Exception:
            continue
        if box and box[3] > box[1]:
            return float(box[3])
    return 0.0


def line_metrics(font_of: FontOf | None, size: int) -> LineMetrics:
    """该字号下主字体的真实度量（画基线用）。字体不可用时返回估算值。

    ``ascent`` 已按 :func:`_ink_top` 校正过：保证「行盒顶部 + ascent」放得下最高字形。
    """
    size = max(1, int(size))
    font = _font_for(font_of, size)
    if font is None:
        return LineMetrics(float(size), float(size) * 0.25, float(size) * 1.25, False)
    key = (id(font), size)
    hit = _met_cache.get(key)
    if hit is None:
        try:
            asc, desc = font.getmetrics()
            asc, desc = float(asc), float(desc)
        except Exception:
            asc, desc = float(size), float(size) * 0.25
        ink = _ink_top(font, size)
        if ink > asc:
            # 字形比字体自报的 ascent 还高 → 基线整体下移，宁可压扁一点行间空白
            asc = min(ink, max(asc, (asc + desc) * 0.92))
        if len(_met_cache) > _CACHE_CAP:
            _met_cache.clear()
        hit = (asc, desc)
        _met_cache[key] = hit
    return LineMetrics(hit[0], hit[1], hit[0] + hit[1], True)


# ══════════════════════════════════════════════════════════════════════
#  断行
# ══════════════════════════════════════════════════════════════════════


@dataclass
class _Unit:
    """断行最小单元：一个 token + 它归属的 run 样式。"""
    text: str
    scale: float
    bold: bool
    italic: bool
    ws: bool = False


def _units(runs: Sequence[TextRun], lang: str) -> list[_Unit]:
    """把 runs 展开成断行单元（同一个 run 内的中英混排也会被切开）。"""
    out: list[_Unit] = []
    for run in runs:
        if not run.text:
            continue
        sc = float(run.size_scale or 1.0)
        for tok in tokenize(run.text, lang):
            if not tok:
                continue
            out.append(_Unit(tok, sc, bool(run.bold), bool(run.italic), _is_space(tok[0])))
    return out


def _u_width(unit: _Unit, font_of: FontOf | None, size: int) -> float:
    rs = max(1, int(round(size * unit.scale)))
    return token_width(unit.text, _font_for(font_of, rs), rs)


def _line_runs(units: Sequence[_Unit]) -> list[TextRun]:
    """把单元合并回 run（相邻同样式合并，保证输出干净）。"""
    runs: list[TextRun] = []
    for u in units:
        if runs and runs[-1].bold == u.bold and runs[-1].italic == u.italic \
                and abs(runs[-1].size_scale - u.scale) < 1e-6:
            runs[-1].text += u.text
        else:
            runs.append(TextRun(u.text, u.bold, u.italic, u.scale))
    return runs


def line_text(line: Sequence[TextRun]) -> str:
    """把一行 run 还原成字符串。"""
    return "".join(r.text for r in line)


def plain_text(lines: Sequence[Sequence[TextRun]]) -> str:
    """把多行 run 还原成 ``"\\n"`` 连接的纯文本（调 Linter / 落盘用）。"""
    return "\n".join(line_text(l) for l in lines)


def _trim_left(units: list[_Unit]) -> list[_Unit]:
    while units and units[0].ws:
        units.pop(0)
    return units


def _trim_right(units: list[_Unit]) -> list[_Unit]:
    while units and units[-1].ws:
        units.pop()
    return units


def _fix_line_start(cur: list[_Unit], rest: list[_Unit], bad: str
                    ) -> tuple[list[_Unit], list[_Unit]]:
    """把 ``rest`` 开头不允许起行的 token **拉回本行**（不丢字符）。

    本行宽度会因此超出 ``max_w`` 一个字符，正好由 :func:`fit` 的下一档字号或横压
    消化 —— 这也是 ``squeeze_x`` 存在的意义之一。最多拉 4 个字符，避免病态文本
    把整段吸到一行。
    """
    pulled = 0
    while rest and not rest[0].ws and rest[0].text and rest[0].text[0] in bad:
        tok = rest[0]
        if not any(u.text.strip() for u in cur):
            break                        # 本行只有空白，不值得再吸
        cur.append(_Unit(tok.text[0], tok.scale, tok.bold, tok.italic))
        if len(tok.text) > 1:
            rest = [_Unit(tok.text[1:], tok.scale, tok.bold, tok.italic)] + rest[1:]
        else:
            rest = rest[1:]
        pulled += 1
        if pulled > 4:
            break
    return cur, rest


def _break_line(cur: list[_Unit], rest: list[_Unit], lang: str, bad_end: str,
                bad_start: str) -> tuple[list[_Unit], list[_Unit], bool]:
    """行满时的禁则修补：先处理行尾（推走开括号），再处理行首（拉回句读点）。

    返回 ``(本行, 剩余序列, 本行是否结束了一个段落)``：第三项为真时，
    **下一行**属于段落起始，可以按自己的 ``①`` / ``1.`` 另起悬挂缩进。
    """
    carry: list[_Unit] = []
    while len(cur) > 1 and not cur[-1].ws and cur[-1].text and cur[-1].text[-1] in bad_end:
        carry.insert(0, cur.pop())
    line = _trim_right(cur)
    if not line:                          # 全被推走 → 至少留一个，不造空行
        line, carry = cur, []
    rest = carry + rest
    if line:
        line, rest = _fix_line_start(line, rest, bad_start)
    tail = line[-1].text[-1] if (line and line[-1].text) else ""
    return line, rest, (not line or tail in "。！？；\n")


def _wrap_units(units: list[_Unit], font_of: FontOf | None, max_w: float, size: int,
                lang: str, indent: float = 0.0) -> tuple[list[list[_Unit]], list[float]]:
    """核心断行：贪心 + 禁则 + 悬挂缩进，返回 ``(行, 每行绝对左缩进)``。

    ``indent`` 是**首句**的续行缩进（= 该句行首编号的宽度）。段落换行时，
    若下一句以 ``①`` / ``(1)`` 另起，则按它自己的编号宽重新对齐；否则回到顶格。
    于是官方卡文里连排的 ``①②③`` 每一段都与各自编号后的正文左对齐。
    """
    if max_w <= 1 or not units:
        return [], []
    bad_start = forbidden_line_start(lang)
    bad_end = forbidden_line_end(lang)
    lines: list[list[_Unit]] = []
    indents: list[float] = []                 # 每行的**绝对**左缩进
    pending = list(units)
    cur: list[_Unit] = []
    cur_w = 0.0
    cur_indent = 0.0
    para_indent = _indent_for_units(units, size, font_of, lang, True)
    avail = float(max_w) - para_indent
    para_start = True
    i = 0
    while i < len(pending):
        unit = pending[i]
        if unit.text == "\n":
            # 显式换行 = 强制断行（官方卡文的段落/说明行靠它表达）
            line = _trim_right(cur)
            if line:
                lines.append(line)
                indents.append(cur_indent)
            cur, cur_w = [], 0.0
            cur_indent = _HARD_BREAK
            para_indent = 0.0                     # 换行后是全新段落，重新判定编号
            avail = float(max_w)
            i += 1
            continue
        if unit.ws and not cur:
            i += 1                        # 行首空白直接丢弃
            continue
        w = _u_width(unit, font_of, size)
        if cur and cur_w + w > avail + 0.01:
            # 行满 → 交给禁则修补；换行后 pending/i 已重排，**不能**再自增 i
            line, rest, para_done = _break_line(cur, pending[i:], lang, bad_end,
                                                bad_start)
            lines.append(line)
            indents.append(cur_indent)
            cur, cur_w, pending, i = [], 0.0, rest, 0
            if para_done:
                # 新段落：以编号另起就按自己的编号宽缩进；不带编号的段落一律顶格
                para_indent = _indent_for_units(pending, size, font_of, lang, True) \
                    if pending else 0.0
            # 同一段落内的续行沿用该段落的缩进（这正是悬挂缩进）
            cur_indent = para_indent
            avail = float(max_w) - para_indent
        else:
            cur.append(unit)
            cur_w += w
            i += 1
    if cur:
        line = _trim_right(cur)
        if line:
            lines.append(line)
            indents.append(cur_indent)
    out: list[list[_Unit]] = []
    out_indents: list[float] = []
    for l, ind in zip(lines, indents):
        l = _trim_left(l)
        if l:
            out.append(l)
            out_indents.append(ind)
    return out, out_indents


def _wrap_impl(runs: list[TextRun], font_of: FontOf | None, max_w: float,
               lang: str, size: int) -> tuple[list[list[TextRun]], list[float]]:
    """:func:`wrap` / :func:`fit` 的共同实现，返回 ``(行, 每行左缩进)``。"""
    units = _units(runs, lang)
    if not units:
        return [], []
    indent = _indent_for_units(units, size, font_of, lang, True)
    raw, indents = _wrap_units(units, font_of, max_w, size, lang, indent)
    return [_line_runs(l) for l in raw], indents

def wrap(runs: list[TextRun], font_of: FontOf | None, max_w: float,
         lang: str) -> list[list[TextRun]]:
    """把 runs 断成若干行。

    * ``LANGS[lang].wrap == "cjk"`` 按**单字**断行，``"word"`` 按**词**断行；
    * 行首/行尾禁则见 :func:`forbidden_line_start` / :func:`forbidden_line_end`；
    * 行首若为 ``①``–``⑳`` / ``(1)`` / ``1.``，续行向右缩进一个编号宽（悬挂缩进）。

    本函数签名里没有字号（契约如此），因此内部按 :data:`REF_SIZE` 量宽度；
    断行点与字号无关（宽度随字号等比缩放），只有 ``max_w`` 需要与之一致。
    要看真实字号的断行请用 :func:`wrap_sized`（:func:`fit` 走的就是它）。

    返回的行**不含**行首空白；把各行 ``"".join`` 起来不等于原文（空白与换行点会变），
    要还原文本请用 :func:`plain_text` 或保留原始 ``runs``。
    """
    return _wrap_impl(runs, font_of, max_w, lang, REF_SIZE)[0]


def wrap_sized(runs: list[TextRun], font_of: FontOf | None, max_w: float,
               lang: str, size: int) -> list[list[TextRun]]:
    """同 :func:`wrap`，但显式给出基准字号（需要真实字宽/真实字号时用它）。"""
    return _wrap_impl(runs, font_of, max_w, lang, max(1, int(size)))[0]


def wrap_indents(runs: list[TextRun], font_of: FontOf | None, max_w: float,
                 lang: str, size: int) -> tuple[list[list[TextRun]], list[float]]:
    """同 :func:`wrap_sized`，另外返回**每行的左缩进**（悬挂缩进，px）。

    :func:`draw_fitted` 用它保证绘制与断行完全一致（``①②③`` 连排时每段各自对齐）。
    """
    return _wrap_impl(runs, font_of, max_w, lang, max(1, int(size)))


# ══════════════════════════════════════════════════════════════════════
#  两方向自适应
# ══════════════════════════════════════════════════════════════════════


def fit(runs: list[TextRun], font_of: FontOf | None, box: tuple[float, float],
        lang: str, profile: str = DEFAULT_PROFILE, *,
        max_lines: int | None = None, apply_inset: bool = True,
        min_size: int = 1, size_scale: float = 1.0) -> Fitted:
    """在 ``box``（可用宽 × 可用高）内把 runs 排好。

    搜索顺序（**字号优先、横压其次**）：

    1. 依次试 ``FIT_PROFILES[profile]`` 的字号档
       （``fontSize × font_scale(lang) × size_scale``，四舍五入到整数像素）；
       同一档位内先用 ``squeeze_x = 1.0``；
    2. 该档放不下才按 ``COMPRESS["autoScaleXQuantifier"]`` 递减横压，最多到
       ``1 - COMPRESS["maxAutoCompressionX"]``（默认 0.80）；横压时可用宽度按
       ``max_w / squeeze_x`` 放宽，所以**真的能多塞字**；
    3. 全部档位都不行 → 返回最小档 + 最小横压的结果并置 ``overflow=True``
       （**不抛异常**，给调用方画溢出提示）。

    ``font_of(size) -> ImageFont`` 由调用方提供；回调缺失/返回 ``None`` 时退化为
    估算字宽（断行仍然正确、只是行宽不精确）。

    ``apply_inset`` 为真时先按 :func:`geometry.text_inset` 把 ``box`` 收一圈
    （不同语言视觉密度不同，官方排版的左右留白不同）；调用方若已自行内缩，
    传 ``apply_inset=False`` 以免重复收。

    单位约定（**这条最容易踩坑**）：``box`` 与 ``Fitted.size`` / ``line_height`` /
    ``indents`` 一律是 ``FIT_PROFILES`` 那套 **REF 单位**（``Fitted.size`` 是
    ``font_of`` 收到的那个数）。两种接法都行，但**别把两者混起来**：

    * **首选**：``box`` 直接给画布像素（如 ``Frame.box("text_box")``），并把
      ``size_scale = 画布宽 / GEO['text_box'][2]``（即 ``Frame.k`` 一类），
      让 ``font_of`` 就按收到的磅数取字。此时 ``Fitted.size`` 就是画布磅数。
    * **另一种**：``box`` 给 REF 单位（``Frame.rect(...)`` 的 w/h）、``size_scale``
      保持 1.0，由 ``font_of`` 自己乘 ``Frame.k``（``render/layers.py`` 的写法）。
      此时断行/行数/行距都在 REF 密度下算（``FIT_PROFILES`` 标定的正是这个密度），
      ``Fitted.size`` 只是 REF 磅数，画布磅数 = ``size × k``；
      配合 :func:`draw_fitted` 时记得传 ``measure_size``。
    * **错误示范**：``box`` 给 REF 单位、又让 ``font_of`` 乘 ``Frame.k`` 且
      ``size_scale`` 也乘一遍 → 相对密度被放大，200 字中文会从 5 行涨到 10 行。
    """
    w0, h0 = float(box[0]), float(box[1])
    if apply_inset:
        left, top, right, bottom = text_inset(lang)
        w0 -= left + right
        h0 -= top + bottom
    max_w = max(1.0, w0)
    max_h = max(1.0, h0)
    lang_k = float(font_scale(lang) or 1.0)
    scale_k = max(1e-6, float(size_scale or 1.0))
    k = lang_k * scale_k
    # size_scale != 1 表示「字号已经换算到画布」，此时强制回调按磅数返回字体
    # （见 _strict_font_of：否则 layers 式回调会被二次放大，字高超过行距 → 叠字）
    strict = abs(scale_k - 1.0) > 1e-9
    probe_cb = font_of
    if strict:
        font_of = _strict_font_of(font_of)  # type: ignore[assignment]
    # 回调是否自己放大字号（layers 式）→ 记进 Fitted，draw_fitted 据此还原画布磅数
    cb_scales, _px0 = _probe_px(probe_cb, 30)
    tiers = _profile_tiers(profile)
    if not tiers:
        return Fitted([], max(1, min_size), 1.0, 1.0, overflow=bool(runs))
    units = _units(runs, lang)
    if not units:
        t0 = tiers[0]
        size = max(min_size, int(round(float(t0.get("fontSize", 24)) * k)))
        lh0 = float(t0["lineHeight"]) * k if t0.get("lineHeight") else float(size)
        f0 = Fitted([], size, lh0, 1.0, False)
        f0._px_hint, f0._px_size = cb_scales, _px_size_of(probe_cb, size)
        return f0
    steps = _compress_steps()
    floor = steps[-1]
    fallback: Fitted | None = None

    def _mk(lines: list, size: int, lh: float, sx: float, over: bool,
            inds: list[float]) -> Fitted:
        obj = Fitted(lines, size, lh, sx, over, inds)
        obj._px_hint = cb_scales
        obj._px_size = _px_size_of(probe_cb, size)
        return obj

    for tier in tiers:
        size = max(min_size, int(round(float(tier.get("fontSize", 24)) * k)))
        lh = float(tier.get("lineHeight", size)) * k
        tier_max = tier.get("maxLines")
        # 行数上限跟着字号一起缩放：它表达的是「这一档最多排几行」这个**相对**设计意图
        # （官方卡面 5 行＝150 px@REF）。若钉成绝对值，同一张卡在不同 dpi 出图会得到
        # 不同的断行；显式传 max_lines 时以调用方的为准（那是绝对行数）。
        cap = int(max_lines) if max_lines else (int(round(tier_max * scale_k))
                                                if tier_max else 0)
        if cap == 0 and lh > max_h + 1e-6:
            continue                              # 一行都放不下
        # ① 先试完全不横压
        lines, indents = _wrap_impl(list(runs), font_of, max_w, lang, size)
        if (not cap or len(lines) <= cap) and len(lines) * lh <= max_h + 0.01:
            return _mk(lines, size, lh, 1.0, False, indents)
        # ② 再试横压：横压时可用宽按 1/squeeze 放宽，必须重跑断行。
        #    从最松往最紧扫，取**第一个可行的**（= 压得最轻）那一档：
        #    既不会像旧版那样无脑压到 0.80，也不会为了少压一点而多留一行。
        for sx in reversed(steps[1:]):
            wide = max_w / sx
            cand, cinds = _wrap_impl(list(runs), font_of, wide, lang, size)
            if (not cap or len(cand) <= cap) and len(cand) * lh <= max_h + 0.01:
                return _mk(cand, size, lh, sx, False, cinds)
        if fallback is None:
            widest = max_w / floor
            fb_lines, fb_ind = _wrap_impl(list(runs), font_of, widest, lang, size)
            fallback = _mk(fb_lines, size, lh, floor, True, fb_ind)
    assert fallback is not None                   # tiers 非空时必然被赋值
    return fallback


# ══════════════════════════════════════════════════════════════════════
#  绘制
# ══════════════════════════════════════════════════════════════════════


def _draw_line(draw, line: Sequence[TextRun], x: float, y: float, size: int,
               font_of: FontOf | None, fill, spacing: int, bold_fill,
               ascent: float) -> None:
    """把一行 run 画到 ``draw`` 上。

    ``y`` = 该行**文本盒顶部**。用 ``anchor="lt"``（top）而不是 ``"la"``（ascender）：
    Pillow 的 ``la`` 会把墨迹再往下压 ~ (ink_top - ascender)，实测 ``永`` @51px
    会多下沉 5px，与「按 ascent 定位」叠加后就叠到上一行去了（叠字根因之一）。
    ``lt`` 则把字形顶（= ``_ink_top`` 校正后的 ascent）对齐到 ``y``，
    各 run 按其 ``size_scale`` 单独下移，保证基线与行距仍然一致。
    """
    cx = float(x)
    prev: str | None = None
    for run in line:
        if not run.text:
            continue
        rs = run.scaled(size)
        font = _font_for(font_of, rs)
        col = bold_fill if (run.bold and bold_fill is not None) else fill
        stroke = FAUX_BOLD if run.bold else 0
        # 各 run 共用一条基线：以基准字号的字形顶为基准，字号不同的 run 按
        # 「自身字形高 − 基准字形高」补一个正偏移（注音/精灵那种小字号不会浮起来）
        dy = y + max(0.0, _ink_top(font, rs) - ascent) if font is not None else y
        if font is None:                       # 无字体：画占位块，保证版面可见
            w = token_width(run.text, None, rs)
            if ImageDraw is not None:
                draw.rectangle([cx, dy + rs * 0.12, cx + w, dy + rs * 0.88], fill=col)
            cx += w
            prev = run.text[-1]
            continue
        if spacing:
            for ch in run.text:
                cx += _pair_gap(prev, ch) * rs
                w = _char_w(font, ch, rs)
                if unicodedata.category(ch).startswith("M"):   # 组合符号回退叠加
                    draw.text((cx - w, dy), ch, font=font, fill=col, anchor="lt")
                else:
                    draw.text((cx, dy), ch, font=font, fill=col, anchor="lt",
                              stroke_width=stroke, stroke_fill=col if stroke else None)
                    cx += w + spacing
                prev = ch
        else:
            if run.text:
                cx += _pair_gap(prev, run.text[0]) * rs
            draw.text((cx, dy), run.text, font=font, fill=col, anchor="lt",
                      stroke_width=stroke, stroke_fill=col if stroke else None)
            cx += token_width(run.text, font, rs)
            prev = run.text[-1]


def _target_image(draw):
    """从 ImageDraw 取真正的目标画布（用于横向压缩时贴回）。

    Pillow ≤ 11 里 ``ImageDraw.im`` 是 ``Image``；**Pillow 12 起 ``im`` 变成了
    ``ImagingCore``**（没有 ``paste``），真正的画布在 ``draw._image``。
    两个属性都试，且必须确认是 ``Image.Image`` 才用 —— 否则返回 ``None``，
    调用方退化为直接绘制（只是不做横压，不会崩）。
    """
    if Image is None:
        return None
    for attr in ("_image", "im"):
        cand = getattr(draw, attr, None)
        if isinstance(cand, Image.Image):
            return cand
    return None


def draw_fitted(draw, fitted: Fitted, xy: tuple[float, float], font_of: FontOf | None,
                fill, *, squeeze_x: float | None = None, spacing: int = 0,
                bold_fill=None, measure_size: int | None = None) -> None:
    """把 :class:`Fitted` 画到 ``draw`` 上（``xy`` = 文本框左上角）。

    * ``squeeze_x`` 覆盖 ``fitted.squeeze_x``（便于调用方临时放宽）；
      取 1.0 时**直接绘制**，否则每行先画到临时透明图再横向缩放粘贴。
    * ``spacing`` 为额外字距（px），给定时逐字符绘制。
    * ``bold_fill`` 给定时，``bold=True`` 的 run 换成该色（官方卡文里编号与关键词的
      墨色略有差异）；未给定时粗体只用描边加粗。
    * ``italic=True`` 的 run 用错切（shear）实现伪斜体。
    * 首行有 ①②③ 编号时，续行自动右缩进一个编号宽（与 :func:`fit` 的断行一致）。

    单位：``xy`` / ``spacing`` / ``fitted.line_height`` 都是**画布像素**。
    ``font_of`` 应当返回**画布像素磅**的字：

    * 用 ``fit(..., box=画布像素, font_scaled=True)`` 时 ``fitted.size`` 就是磅数，
      直接把同一个 ``font_of`` 传进来即可（最常见、最不容易错）；
    * 用 ``fit(..., box=REF 单位)`` 且 ``font_of`` 自己乘 ``Frame.k`` 时，
      请传 ``measure_size=`` 给出回调实际产出的磅数
      （例如 :mod:`cardforge.render.layers` 传 ``int(round(fitted.size * frame.k))``），
      本函数据此把 ``indents`` 从 REF 单位换算到画布像素；
      不传时按 REF 单位直接用（缩进会偏小，只有悬挂缩进受影响）。
    """
    if draw is None or fitted is None or not fitted.lines:
        return
    sx = float(fitted.squeeze_x if squeeze_x is None else squeeze_x)
    sx = max(0.05, min(1.0, sx))
    # 画布像素磅数：优先取 fit() 记下的探测结果，其次调用方给的 measure_size。
    # ``cb_hint`` 表示 font_of 会自己放大字号（layers 式），此时交给回调的仍是 REF 磅数。
    ref_size = max(1, int(fitted.size))
    cb_hint = bool(getattr(fitted, "_px_hint", False))
    px_size = int(getattr(fitted, "_px_size", 0) or 0) or \
        (max(1, int(measure_size)) if measure_size else ref_size)
    ind_k = px_size / float(ref_size)                      # REF 单位 → 画布像素
    size = ref_size if cb_hint else px_size
    lh = float(fitted.line_height or size)
    metrics = line_metrics(font_of, ref_size if cb_hint else px_size)
    ascent = metrics.ascent
    base_x, base_y = float(xy[0]), float(xy[1])
    target = _target_image(draw)
    # 悬挂缩进：优先用 fit() 记下的每行缩进（与 box 同单位），保证「绘制 == 断行」；
    # 手搓的 Fitted 没有 indents 时退回按首行编号启发式判定。
    # 注意：这里**不做单位换算** —— 交给 ``_draw_line`` 的 x 也必须与 box 同单位，
    # 由 ``font_of`` 负责它自己的换算（两边同时乘 k 就会得到 k² 的缩进）。
    indents = list(fitted.indents)
    if len(indents) != len(fitted.lines):
        fb = _hanging_indent(_line_prefix(fitted.lines[0]), ref_size, font_of, True) \
            if fitted.lines else 0.0
        indents = [0.0] + [fb] * (len(fitted.lines) - 1) if fitted.lines else []

    squeeze_ok = sx < 0.999 and target is not None and Image is not None
    for idx, line in enumerate(fitted.lines):
        if not line:
            continue
        x = base_x + (indents[idx] if idx < len(indents) else 0.0)
        y = base_y + idx * lh
        if not squeeze_ok:
            _draw_line(draw, line, x, y, size, font_of, fill, int(spacing),
                       bold_fill, ascent)
        else:
            _draw_squeezed(draw, target, line, x, y, px_size, metrics, font_of, fill,
                           int(spacing), bold_fill, ascent, sx)


def _draw_squeezed(draw, target, line: Sequence[TextRun], x: float, y: float,
                   size: int, metrics: LineMetrics, font_of: FontOf | None, fill,
                   spacing: int, bold_fill, ascent: float, sx: float) -> None:
    """横向压缩：整行先画到临时透明图，再横向缩放后粘贴到目标画布。

    Pillow 没有「横向字距缩放」这种绘制模式，所以只能走「离屏绘制 → 重采样」。
    临时图上下留出 ``ascent``/``descent`` 之外的余量，保证描边与溢出字形不被裁。
    """
    width = measure_runs(line, font_of, size) + 6.0
    w = max(1, int(round(width)))
    # 离屏画布按「画布像素字号」留上下余量：size 是交给回调的磅数，
    # 实际字形可能有 metrics 那么大，因此余量取 size 与 metrics 的较大者
    glyph_h = max(float(size), metrics.height)
    top_pad = max(3.0, glyph_h * 0.55 + FAUX_BOLD * 2)
    bot_pad = max(3.0, metrics.descent + glyph_h * 0.45 + FAUX_BOLD * 2)
    h = max(1, int(round(glyph_h + top_pad + bot_pad)))
    tmp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    _draw_line(td, line, 0.0, top_pad, size, font_of, fill, spacing, bold_fill, ascent)
    if any(r.italic for r in line):          # 伪斜体：错切后再缩放
        try:
            tmp = tmp.transform(tmp.size, Image.AFFINE,
                                (1, FAUX_ITALIC_SHEAR, -FAUX_ITALIC_SHEAR * h, 0, 1, 0),
                                resample=Image.BILINEAR)
        except Exception:
            pass
    new_w = max(1, int(round(w * sx)))
    if new_w != w:
        tmp = tmp.resize((new_w, h), Image.LANCZOS)
    px = int(round(x))
    py = int(round(y - top_pad))
    # 传 4 元组 box：Pillow 12 起 paste(im, (x,y), mask) 的二元位置会与 box 语义冲突
    target.paste(tmp, (px, py, px + tmp.width, py + tmp.height), tmp)


# ══════════════════════════════════════════════════════════════════════
#  PSCT 强调标记
# ══════════════════════════════════════════════════════════════════════

#: 需要强调的 PSCT 关键词（按语言）。取词原则：**宁可少标，不可乱标** ——
#: 只收「本身就有 PSCT 语义」的短语，不收「的」「场合」这类高频字。
PSCT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "zh_cn": (
        "1回合1次", "一回合一次", "回合1次", "各能使用1次", "各能发动1次", "只能发动1次",
        "才能发动", "才能使用", "可以发动", "不能发动", "不能使用", "不能作为",
        "这个卡名的", "这个卡名", "卡名", "场合才能", "时才能", "作为对象", "为对象",
        "取对象", "的效果", "时发动", "加入手卡", "送去墓地", "特殊召唤",
        "破坏", "除外", "回到", "抽1张", "抽2张", "放置", "攻击力", "守备力",
        "结束阶段", "准备阶段", "主要阶段", "战斗阶段", "对方回合", "自己回合",
    ),
    "zh_tw": (
        "1回合1次", "一回合一次", "回合1次", "各能使用1次", "各能發動1次", "只能發動1次",
        "才能發動", "才能使用", "可以發動", "不能發動", "不能使用", "不能作為",
        "這個卡名的", "這個卡名", "卡名", "場合才能", "時才能", "作為對象", "為對象",
        "取對象", "的效果", "時發動", "加入手牌", "送去墓地", "特殊召喚",
        "破壞", "除外", "回到", "抽1張", "抽2張", "放置", "攻擊力", "守備力",
        "結束階段", "準備階段", "主要階段", "戰鬥階段", "對方回合", "自己回合",
    ),
    "ja": (
        "1ターンに1度", "ターンに1度", "1度だけ", "発動できる", "発動できない",
        "発動した", "使用できる", "使用できない", "このカード名の", "カード名",
        "場合に発動", "時に発動", "対象として", "対象に", "対象の", "効果",
        "手札に加え", "墓地へ送", "特殊召喚", "破壊", "除外", "デッキ",
        "攻撃力", "守備力", "エンドフェイズ", "スタンバイフェイズ", "メインフェイズ",
    ),
    "en": (
        "once per turn", "once per Duel", "you can only use", "you can only activate",
        "cannot be activated", "you can activate", "activate this effect",
        "this card's name", "and if you do", "if you do", "instead",
        "banish", "destroy", "negate", "special summon", "add it to your hand",
        "add 1", "to your hand", "from your Deck", "from your GY", "from the GY",
        "face-up", "face-down", "ATK", "DEF", "until the end of this turn",
        "during the End Phase", "your opponent", "you control", "target",
    ),
}

#: 内联编号（①②③…）：只要出现就强调（官方卡文里它就是段落起始标记）
_RE_CIRCLED = re.compile(r"[①-⑳]+")
#: 「1.」「(1)」「1：」形式（是否算编号由 :func:`_at_para_start` 判定）
_RE_LABEL_ANY = re.compile(r"[（(]?\d{1,2}[)）.．、:：]")
#: 段落起始判定：行首，或句读点（。！？；/换行）之后
_RE_PARA_TAIL = re.compile(r"[。！？；\n]\s*$")
#: 「…」内的卡名 / 字段
_RE_QUOTED = re.compile(r"「[^「」\n]{1,60}」")
#: 卡名条（【…】如【魔法卡效果】）
_RE_BRACKET = re.compile(r"【[^【】\n]{1,40}】")

_SPAN_RE_CACHE: dict[str, re.Pattern] = {}
_WORD_SPAN_RE_CACHE: dict[str, tuple[re.Pattern, tuple[str, ...]]] = {}


def _at_para_start(text: str, i: int) -> bool:
    """位置 ``i`` 是否处于段落起始（行首，或句读点/换行之后，允许前置空白）。"""
    if i <= 0:
        return True
    j = i
    while j > 0 and text[j - 1] in " \t\u3000":
        j -= 1
    if j == 0:
        return True
    return bool(_RE_PARA_TAIL.search(text[max(0, j - 1):j]))


def _number_re(lang: str) -> re.Pattern:
    """编号检测正则。

    中日文：``[①-⑳]+`` **任何位置**都算编号（官方卡文里它就是段落起始标记）；
    按词语言：段首的 ``1.`` / ``(1)`` 形式（位置由 :func:`_at_para_start` 复核）。
    由于 ``[①-⑳]`` 的起点与普通字符不重叠，一个 ``finditer`` 扫描即覆盖两种情况。
    """
    key = _norm_lang(lang)
    hit = _SPAN_RE_CACHE.get(key)
    if hit is not None:
        return hit
    if _lang_wrap(lang) == "cjk":
        pat = re.compile(r"(?:[①-⑳]+)|(?:[（(]?\d{1,2}[)）.．、:：])")
    else:
        pat = re.compile(r"[（(]?\d{1,2}[)）.．、:：]")
    _SPAN_RE_CACHE[key] = pat
    return pat


def _keyword_re(lang: str) -> tuple[re.Pattern, tuple[str, ...]]:
    """该语言关键词的匹配正则（长词优先，避免短词先吃掉长词）。"""
    key = _norm_lang(lang)
    hit = _WORD_SPAN_RE_CACHE.get(key)
    if hit is not None:
        return hit
    words = tuple(sorted(set(PSCT_KEYWORDS.get(key, ())), key=len, reverse=True))
    pat = re.compile("|".join(re.escape(w) for w in words), re.IGNORECASE) if words \
        else re.compile(r"(?!x)x")
    _WORD_SPAN_RE_CACHE[key] = (pat, words)
    return pat, words


@dataclass(frozen=True)
class PsctSpan:
    """一个强调区间（``[start, end)``）与其类别：number / quote / keyword。"""
    start: int
    end: int
    kind: str


def psct_spans(text: str, lang: str) -> list[PsctSpan]:
    """算出所有需要强调的字符区间（已合并重叠），供 :func:`mark_psct` 或检查器使用。"""
    if not text:
        return []
    lg = _norm_lang(lang)
    cjk = _lang_wrap(lg) == "cjk"
    n = len(text)
    raw: list[PsctSpan] = []
    for m in _number_re(lg).finditer(text):
        s = text[m.start()]
        if s in _CIRCLED_NUM:
            raw.append(PsctSpan(m.start(), min(m.end(), n), "number"))
        elif _at_para_start(text, m.start()):
            raw.append(PsctSpan(m.start(), min(m.end(), n), "number"))
    for m in _RE_QUOTED.finditer(text):
        raw.append(PsctSpan(m.start(), min(m.end(), n), "quote"))
    for m in _RE_BRACKET.finditer(text):
        raw.append(PsctSpan(m.start(), min(m.end(), n), "quote"))
    pat, _words = _keyword_re(lg)
    for m in pat.finditer(text):
        if m.end() > m.start():
            raw.append(PsctSpan(m.start(), min(m.end(), n), "keyword"))
    # 合并重叠 / 相接
    raw = [s for s in raw if s.end > s.start]
    raw.sort(key=lambda s: (s.start, s.end))
    merged: list[PsctSpan] = []
    for s in raw:
        if merged and s.start <= merged[-1].end:
            last = merged[-1]
            if s.end > last.end:
                merged[-1] = PsctSpan(last.start, s.end,
                                      last.kind if last.kind == s.kind else "mixed")
        else:
            merged.append(s)
    return merged


def mark_psct(text: str, lang: str) -> list[TextRun]:
    """把效果编号、``「…」`` 内的卡名/字段、PSCT 关键词标记为 ``bold=True``。

    **不改变任何字符** —— ``"".join(r.text for r in mark_psct(t, lang)) == t``
    恒成立（模块自测里对三段真实卡文有断言）。标记策略：

    * 编号：``①``–``⑳``、``【①】``、段首的 ``(1)`` / ``1.`` / ``1：``；
    * ``「…」`` / ``【…】`` 整段（含括号本身，官方卡文里字段引用整体强调）；
    * 关键词：见 :data:`PSCT_KEYWORDS`（中日按字面、英文忽略大小写）。

    标记只影响观感：把 ``palette.text_ink`` 作 ``fill``、深一档的墨色作 ``bold_fill``
    传给 :func:`draw_fitted` 即可还原官方卡文里「编号/关键词略重」的观感。
    """
    if not text:
        return []
    spans = psct_spans(text, lang)
    if not spans:
        return [TextRun(text)]
    runs: list[TextRun] = []
    pos = 0
    for s in spans:
        if s.start > pos:
            runs.append(TextRun(text[pos:s.start]))
        runs.append(TextRun(text[s.start:s.end], True))
        pos = s.end
    if pos < len(text):
        runs.append(TextRun(text[pos:]))
    return runs


# ══════════════════════════════════════════════════════════════════════
#  便捷入口 / 缓存
# ══════════════════════════════════════════════════════════════════════


def render_lines(text: str, font_of: FontOf | None, box: tuple[float, float],
                 lang: str, profile: str = DEFAULT_PROFILE, *,
                 psct: bool = True, max_lines: int | None = None,
                 apply_inset: bool = True, size_scale: float = 1.0) -> Fitted:
    """``mark_psct`` + ``fit`` 的合并入口（渲染器最常用的一条路径）。

    参数含义见 :func:`fit`；``psct=False`` 时整段作为单个普通 run（不强调编号/关键词）。
    """
    runs = mark_psct(text, lang) if psct else ([TextRun(text)] if text else [])
    return fit(runs, font_of, box, lang, profile, max_lines=max_lines,
               apply_inset=apply_inset, size_scale=size_scale)


def clear_cache() -> None:
    """清空字宽 / 词宽 / 度量 / ``font_of`` memo 缓存（换字体或长时间运行后调用）。"""
    _char_cache.clear()
    _tok_cache.clear()
    _met_cache.clear()
    _font_cache.clear()
    _SPAN_RE_CACHE.clear()
    _WORD_SPAN_RE_CACHE.clear()
