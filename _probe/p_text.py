# -*- coding: utf-8 -*-
"""text.py 自测探针（临时脚本，不属于包）。

跑法::

    python _probe\\p_text.py

产出：
  * ``_probe/_text_selfcheck.txt``  UTF-8 报告（控制台可能乱码，以文件为准）
  * ``_probe/text/t_zh_long.png`` / ``t_zh_over.png`` / ``t_en_psct.png`` / ``t_ja.png``
"""
from __future__ import annotations

import io
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:                                   # 控制台可能不是 UTF-8，报告文件才是准的
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OUT_DIR = ROOT / "_probe" / "text"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "_probe" / "_text_selfcheck.txt"

buf = io.StringIO()


def out(*a) -> None:
    print(*a)
    print(*a, file=buf)


def head(title: str) -> None:
    out("")
    out("=" * 100)
    out(title)
    out("=" * 100)


FAILS: list[str] = []


def check(cond: bool, msg: str) -> bool:
    out(("  [PASS] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)
    return cond


# ══════════════════════════════════════════════════════════════════════
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from cardforge.render import text as T  # noqa: E402
from cardforge.render.geometry import Frame, text_inset  # noqa: E402
from cardforge.render.palettes import palette  # noqa: E402

try:
    from cardforge.render.fonts import load as font_load  # noqa: E402
    FONT_SRC = "cardforge.render.fonts.load"
except Exception as exc:  # pragma: no cover
    font_load = None
    FONT_SRC = f"fallback msyh.ttc ({exc!r})"

MSYH = r"C:\Windows\Fonts\msyh.ttc"
YU = r"C:\Windows\Fonts\YuGothM.ttc"
ARIAL = r"C:\Windows\Fonts\arial.ttf"


def make_font_of(path: str, label: str):
    index = 0
    if path.lower().endswith((".ttc", ".otc")):
        for i in range(4):
            try:
                ImageFont.truetype(path, 16, index=i)
                index = i
                break
            except Exception:
                continue
    cache: dict[int, ImageFont.FreeTypeFont] = {}

    def font_of(size: int):
        size = max(1, int(size))
        f = cache.get(size)
        if f is None:
            f = ImageFont.truetype(path, size, index=index)
            cache[size] = f
        return f

    font_of.label = label  # type: ignore[attr-defined]
    font_of.path = path    # type: ignore[attr-defined]
    return font_of


def pick_font(lang: str, role: str) -> str:
    """优先用 cardforge.render.fonts；不可用时退系统字体。"""
    if font_load is not None:
        try:
            f = font_load(role, 30, lang)
            if f is not None and getattr(f, "path", None):
                return str(f.path)
        except Exception:
            pass
    if lang == "ja" and Path(YU).is_file():
        return YU
    if lang == "en" and Path(ARIAL).is_file():
        return ARIAL
    return MSYH


head("0. 环境")
out(f"  python        : {sys.version.split()[0]}")
out(f"  Pillow        : {Image.__version__ if hasattr(Image, '__version__') else '?'}")
out(f"  字体来源      : {FONT_SRC}")
for lg, role in (("zh_cn", "sc"), ("ja", "sc"), ("en", "en")):
    out(f"  pick({lg:5s},{role:2s}) -> {pick_font(lg, role)}")

# ══════════════════════════════════════════════════════════════════════
head("1. mark_psct 不改变任何字符（3 段真实卡文）")

TEXTS_ZH = [
    "①：这张卡召唤成功时才能发动。从卡组把1张「青眼」卡加入手卡。"
    "②：1回合1次，以自己场上1只怪兽为对象才能发动。那只怪兽的攻击力直到回合结束时上升1000。"
    "这个效果在对方回合也能发动。",
    "这个卡名的①②的效果1回合各能使用1次。"
    "①：自己主要阶段才能发动。从手卡把1只「电子龙」特殊召唤。"
    "②：这张卡被送去墓地的场合才能发动。自己从卡组抽1张。",
    "①：1回合1次，可以从以下效果选择1个发动。●以场上1只表侧表示怪兽为对象才能发动。"
    "那只怪兽的守备力上升500。●对方场上的魔法·陷阱卡全部破坏。"
    "②：这张卡从场上离开的场合才能发动。从卡组把1张「融合」加入手卡。",
]
for i, t in enumerate(TEXTS_ZH, 1):
    runs = T.mark_psct(t, "zh_cn")
    ok = "".join(r.text for r in runs) == t
    check(ok, f"mark_psct 拼接等于原文 #{i}（{len(runs)} 个 run，{len(t)} 字）")
    if not ok:
        out("    原文: " + t)
        out("    拼接: " + "".join(r.text for r in runs))
    bold = "".join(r.text for r in runs if r.bold)
    out(f"    加粗片段({len(bold)}字): {bold[:120]}{'…' if len(bold) > 120 else ''}")

for lang, t in (
    ("en", "Once per turn: You can target 1 monster your opponent controls; "
           "banish it, and if you do, draw 1 card."),
    ("ja", "①：このカードが召喚に成功した時に発動できる。デッキから「青眼」1体を"
           "手札に加える。②：1ターンに1度、相手フィールドのモンスター1体を対象として"
           "発動できる。そのモンスターを破壊する。"),
):
    runs = T.mark_psct(t, lang)
    check("".join(r.text for r in runs) == t, f"mark_psct 拼接等于原文（{lang}）")
    out(f"    {lang} 加粗: {[r.text for r in runs if r.bold][:14]}")

head("1b. tokenize 保真 + 中英混排切分")
for lang, t in (
    ("zh_cn", "①：把「青眼の白龍」和Blue-Eyes White Dragon、ATK3000一起送去墓地。"),
    ("zh_cn", "攻击力500アップのモンスターを特殊召喚する。"),
    ("en", 'Add 1 "Blue-Eyes" monster, and if you do, draw 1 card.'),
):
    toks = T.tokenize(t, lang)
    check("".join(toks) == t, f"tokenize 拼接等于原文（{lang}）")
    out(f"    {lang}: {toks}")

# ══════════════════════════════════════════════════════════════════════
head("2. 断行 / 禁则 / 悬挂缩进（纯几何，用真字体量宽）")

frame_share = Frame(813, 1185)
frame_print = Frame(1394, 2031)


def scaled_box(frame: Frame, key: str, lang: str) -> tuple[float, float]:
    """目标画布上「已扣语言内缩」的可用文本尺寸。

    语言内缩（``text_inset``）是 REF 系的量，所以顺序必须是
    「REF 里扣 → 再按 Frame 缩放」，于是调用 ``fit(..., apply_inset=False)``。
    """
    _, _, w_ref, h_ref = frame.rect(key)
    l, t, r, b = text_inset(lang)
    return (w_ref - l - r) * frame.kx, (h_ref - t - b) * frame.ky


box_w, box_h = scaled_box(frame_share, "text_box", "zh_cn")
out(f"  Frame(813,1185) text_box 可用尺寸 = {box_w:.1f} × {box_h:.1f} px"
    f"（GEO 684×173 − zh_cn 内缩 16×6）")

zh_font = make_font_of(pick_font("zh_cn", "sc"), "zh")
en_font = make_font_of(pick_font("en", "en"), "en")
ja_font = make_font_of(pick_font("ja", "sc"), "ja")

# ── 2.1 禁则：行尾开括号、行首句读点 ──────────────────────────────
head("2.1 禁则：不留行首句读点 / 不留行尾开括号")
NARROW = 260.0
samples = [
    ("zh_cn", "这张卡召唤成功时，可以从卡组把1只「青眼」怪兽加入手卡，"
              "那之后（若墓地有卡）抽1张。"),
    ("ja", "このカードが召喚に成功した時、デッキから「青眼」モンスター1体を"
           "手札に加える。その後、（墓地にカードがある場合）1枚ドローする。"),
    ("en", "When this card is Normal Summoned: Add 1 \"Blue-Eyes\" monster "
           "from your Deck to your hand, and if you do, draw 1 card."),
]
for lang, s in samples:
    fo = {"zh_cn": zh_font, "ja": ja_font, "en": en_font}[lang]
    lines = T.wrap_sized(T.mark_psct(s, lang), fo, NARROW, lang, 20)
    texts = [T.line_text(l) for l in lines]
    bad_start = [t for t in texts if t and t[0] in T.forbidden_line_start(lang)]
    bad_end = [t for t in texts if t and t[-1] in T.forbidden_line_end(lang)]
    out(f"  [{lang}] max_w={NARROW:.0f} → {len(texts)} 行")
    for t in texts:
        out(f"      |{t}")
    check(not bad_start, f"{lang} 无行以禁则字符开头" + (f" ← {bad_start}" if bad_start else ""))
    check(not bad_end, f"{lang} 无行以开括号结尾" + (f" ← {bad_end}" if bad_end else ""))

# ── 2.2 悬挂缩进 ────────────────────────────────────────────────────
head("2.2 ①②③ 悬挂缩进（续行与编号后的正文对齐）")
hang_text = ("①：1回合1次，以自己场上1只怪兽为对象才能发动。那只怪兽的攻击力"
             "直到回合结束时上升1000。②：这张卡被送去墓地的场合才能发动。"
             "自己从卡组抽1张。")
h_lines, h_indents = T.wrap_indents(T.mark_psct(hang_text, "zh_cn"), zh_font,
                                    420.0, "zh_cn", 24)
texts = [T.line_text(l) for l in h_lines]
for i, (t, ind) in enumerate(zip(texts, h_indents), 1):
    out(f"      L{i} 缩进={ind:5.1f} |{t}")
w_marker = T.measure_runs([T.TextRun("①：")], zh_font, 24)
out(f"  「①：」宽度 = {w_marker:.2f}px；每行绝对缩进 = {[round(i, 1) for i in h_indents]}")
cont = [ind for t, ind in zip(texts, h_indents) if not t.startswith("①")]
check(bool(cont) and abs(cont[0] - w_marker) < 0.51,
      f"① 段落的续行缩进 = 「①：」宽度（{cont[0]:.2f} vs {w_marker:.2f}）")
check(abs(h_indents[0]) < 0.01, "以 ① 开头的首行顶格（缩进 0）")

# 「②」写在行首的那一行，其续行也要按 ② 重新对齐（官方卡文 ①②③ 连排）
new_para = [i for i, t in enumerate(texts) if t.startswith("②")]
if new_para:
    k = new_para[0]
    after = h_indents[k + 1] if k + 1 < len(h_indents) else None
    out(f"  「②」在第 {k + 1} 行行首；其后一行缩进 = {after}")
    check(after is None or abs(after - w_marker) < 0.51,
          "② 段落另起悬挂缩进（与 ① 段落一致）")

# 像素级验证：首行「正文」的 x 与续行的 x 必须一致
_pv = Image.new("RGB", (600, 260), (255, 255, 255))
T.draw_fitted(ImageDraw.Draw(_pv), T.Fitted(h_lines, 24, 32.0, 1.0, False, h_indents),
              (20, 20), zh_font, (0, 0, 0))
_px = _pv.load()
rows = []
for y0 in range(20, 260, 32):                       # 每行行盒起点
    cols = [x for x in range(_pv.width)
            if any(sum(_px[x, y]) < 384 for y in range(y0, min(y0 + 32, 260)))]
    rows.append(cols[0] if cols else None)
out(f"  每行墨迹起始 x = {rows}")
if rows[0] is not None and rows[1] is not None:
    check(abs(rows[1] - (rows[0] + w_marker)) <= 2.0,
          f"第 2 行 x={rows[1]} ≈ 第 1 行 x={rows[0]} + 编号宽 {w_marker:.0f}")

# ── 2.3 英文按词断行 ────────────────────────────────────────────────
head("2.3 英文按词断行（标点不落行首）")
en_text = ("Once per turn: You can target 1 monster your opponent controls; "
           "banish it, and if you do, Special Summon 1 \"Blue-Eyes White Dragon\" "
           "from your hand, but it cannot attack directly this turn.")
en_lines = T.wrap_sized(T.mark_psct(en_text, "en"), en_font, 300.0, "en", 18)
en_texts = [T.line_text(l) for l in en_lines]
for t in en_texts:
    out(f"      |{t}")
check(all(t[0] not in ",." for t in en_texts if t), "英文没有行以 , 或 . 开头")
check(len(en_texts) >= 4, "英文按词断行产生多行")

# ── 2.3b 集成：模拟 layers.py 的调用方式（REF 单位 box + font_of 里乘 Frame.k）──
head("2.3b 集成：box 用 REF 单位、font_of 里乘 Frame.k（= layers.py 的用法）")
frame_work = Frame(1394, 2031)
_w, _h = frame_work.rect("text_box")[2:]
_k = frame_work.k


def font_of_work(size):
    """layers.py 式回调：把 REF 磅换算到作业画布（1394）的像素。"""
    return zh_font(max(8, int(round(size * _k))))


fit_i = T.fit(T.mark_psct(hang_text, "zh_cn"), font_of_work, (_w, _h), "zh_cn",
              apply_inset=False)
out(f"  fit(size={fit_i.size} REF 单位, 行高={fit_i.line_height:.1f} REF, "
    f"行数={len(fit_i.lines)}, 横压={fit_i.squeeze_x:.2f})；"
    f"回调把 {fit_i.size} 磅放大成 {font_of_work(fit_i.size).size} 磅")
out(f"  每行 indents（REF 单位）= {[round(i, 1) for i in fit_i.indents]}")
out("  ⚠ 这个回调**不能**再被二次调用：draw_fitted 内部若要量度量/字宽，"
    "必须收到「回调实际产出的磅数」而不是 REF 磅数（否则得到 k² 那么大的字 → 叠字）。")
out(f"     line_metrics(font_of_work, {font_of_work(fit_i.size).size}) 的 ascent = "
    f"{T.line_metrics(font_of_work, font_of_work(fit_i.size).size).ascent:.1f}  ← 正确路径"
    f"（传 {fit_i.size} 是错的：那是 REF 磅数，会被回调再放大一次）")

_cv = Image.new("RGB", (int(_w * _k) + 40,
                        int(len(fit_i.lines) * fit_i.line_height * _k) + 60),
                (255, 255, 255))
_d = ImageDraw.Draw(_cv)
fit_i.line_height = fit_i.line_height * _k            # 与 layers 一样换算到画布像素
T.draw_fitted(_d, fit_i, (20, 20), font_of_work, (0, 0, 0))
_px = _cv.load()
# 逐扫描行找最左墨迹，再按「行间空白」切成行段 —— 比按行高硬切稳（不依赖基线估计）
_first: list[int | None] = []
for y in range(_cv.height):
    # 阈值 620：(0,0,0) 和≈0；抗锯齿边缘的淡像素不影响首列判定
    cols = [x for x in range(_cv.width) if sum(_px[x, y]) < 620]
    _first.append(cols[0] if cols else None)
_rows: list[int] = []
for _n in range(len(fit_i.lines)):
    _y0 = max(0, int(round(20 + _n * fit_i.line_height)))
    _y1 = min(_cv.height, int(round(20 + (_n + 1) * fit_i.line_height)))
    _xs = [x for x in range(_cv.width)
           if any(sum(_px[x, y]) < 620 for y in range(_y0, _y1))]
    _rows.append(_xs[0] if _xs else -1)
_hz = font_of_work(fit_i.size)                        # 实际绘制用的字体对象
_ch1 = fit_i.lines[0][0].text[:1]
_ch2 = next((r.text[:1] for r in fit_i.lines[1] if r.text), "")


def _bearing(ch: str) -> int:
    """字形的左侧留白（bbox[0]）—— 让像素比对不受字形设计影响。"""
    try:
        return int(_hz.getbbox(ch)[0])
    except Exception:
        return 0


_all_ink = [y for y in range(_cv.height)
            if any(sum(_px[x, y]) < 620 for x in range(_cv.width))]
_block_h = _all_ink[-1] - _all_ink[0] + 1 if _all_ink else 0
out(f"  整块墨迹：y {_all_ink[0]}-{_all_ink[-1]}（高 {_block_h}）"
    f"  行高 {fit_i.line_height:.1f}px × {len(fit_i.lines)} 行 = "
    f"{fit_i.line_height * len(fit_i.lines):.0f}px")
out(f"  每行墨迹起始 x = {_rows}")
out(f"  行首字符：L1={_ch1!r}（留白 {_bearing(_ch1)}）  "
    f"L2={_ch2!r}（留白 {_bearing(_ch2)}）")
check(_rows[0] >= 0 and _rows[1] >= 0, "前两行都能采到墨迹")
check(_block_h <= fit_i.line_height * len(fit_i.lines) + 6,
      f"整块墨迹高 {_block_h} ≤ 行高×行数（说明**没有串行叠字**）")
check(abs(_rows[0] - 20) <= 6,
      f"首行顶格（墨迹 x={_rows[0]} ≈ 20）")
if _rows[0] >= 0 and _rows[1] >= 0:
    _want = fit_i.indents[1] - _bearing(_ch1) + _bearing(_ch2)
    check(abs(_rows[1] - (20 + _want)) <= 3.0,
          f"续行 x={_rows[1]} ≈ 首行行首 20 + 编号宽 {fit_i.indents[1]:.1f}"
          f"（扣字形留白后 ±3px）")
_cv.save(OUT_DIR / "t_layers_units.png")
out(f"    写出 {OUT_DIR / 't_layers_units.png'}")

# 同一段文字改用「标准用法」（box 直接用画布像素、font_of 返回 size 磅）：
# 两种约定下的**行数**必须一致（说明断行与单位无关）
head("2.3c 两种单位约定行数一致（画布像素 box vs REF box）")
fit_px = T.render_lines(hang_text, zh_font, (box_w, box_h), "zh_cn",
                        apply_inset=False, size_scale=1.0)
out(f"  画布像素 box：size={fit_px.size} 行数={len(fit_px.lines)}  "
    f"行首={[T.line_text(l)[:6] for l in fit_px.lines]}")
out(f"  REF box     ：size={fit_i.size} 行数={len(fit_i.lines)}  "
    f"行首={[T.line_text(l)[:6] for l in fit_i.lines]}")
check(len(fit_px.lines) == len(fit_i.lines),
      f"两种单位约定下行数一致（{len(fit_px.lines)} vs {len(fit_i.lines)}）")

# ── 2.4 中英混排间距 ────────────────────────────────────────────────
head("2.4 中英混排自动补间距")
mixed = "装备怪兽的攻击力上升ATK500。"
w_gap = T.measure_runs([T.TextRun(mixed)], zh_font, 24)
# 期望补间距的位置：力|A 与 0|。 共 2 处
n_expected = 2
w_sum = w_gap - n_expected * 24 * T.CJK_LATIN_GAP
out(f"  含间距 = {w_gap:.2f}px；扣掉 {n_expected} 处间距后 = {w_sum:.2f}px")
check(w_gap > w_sum, "CJK↔拉丁 之间确实补了间距")
check(abs((w_gap - w_sum) - n_expected * 24 * T.CJK_LATIN_GAP) < 0.01,
      f"补了 {n_expected} 处间距（力|A 与 0|。 = {n_expected} 处 × "
      f"{24 * T.CJK_LATIN_GAP:.2f}px）")
_zf = zh_font(24)                       # font_of 是回调，_char_w 要的是字体对象
check(abs(T.measure_runs([T.TextRun("力A")], zh_font, 24)
          - (T._char_w(_zf, "力", 24) + T._char_w(_zf, "A", 24)
             + 24 * T.CJK_LATIN_GAP)) < 0.01,
      f"「力A」之间补了一处间距（实测 {T.measure_runs([T.TextRun('力A')], zh_font, 24):.2f} vs "
      f"{T._char_w(_zf, '力', 24) + T._char_w(_zf, 'A', 24) + 24 * T.CJK_LATIN_GAP:.2f}）")
# 悬挂缩进的量宽也必须走同一套间距规则
_w1 = T._char_w(_zf, "①", 24)
_w2 = T._char_w(_zf, "：", 24)
check(abs(T.measure_runs([T.TextRun("①：")], zh_font, 24) - (_w1 + _w2)) < 0.01,
      f"「①：」宽度 = 逐字宽之和（{_w1:.1f} + {_w2:.1f} = {_w1 + _w2:.1f}）")

# ══════════════════════════════════════════════════════════════════════
head("3. fit() 两方向自适应")

LONG_ZH = (
    "①：1回合1次，以自己场上1只「青眼」怪兽为对象才能发动。那只怪兽的攻击力"
    "直到回合结束时上升1000，这个效果在对方回合也能发动。"
    "②：这张卡被送去墓地的场合才能发动。从卡组把1只光属性·龙族怪兽加入手卡，"
    "那之后自己从卡组抽1张，这个效果发动后，直到回合结束时自己不能把怪兽特殊召唤。"
    "③：这张卡在墓地存在的场合，把这张卡除外才能发动。从自己墓地把1张「融合」"
    "加入手卡，那之后把1只融合怪兽融合召唤。这个效果在这张卡送去墓地的回合"
    "不能发动。"
)
SUPER_LONG_ZH = (
    "①：自己主要阶段，把自己场上1只怪兽解放才能发动。从卡组把1只光属性怪兽"
    "加入手卡，那之后自己从卡组抽1张，这个效果发动后，直到回合结束时"
    "自己不能把怪兽特殊召唤，也不能把魔法·陷阱卡发动。"
    "②：1回合1次，以对方场上1张卡为对象才能发动。那张卡破坏，"
    "那之后从自己墓地把1只「青眼」怪兽特殊召唤。"
    "③：这张卡被送去墓地的场合，以自己墓地1张「融合」为对象才能发动。"
    "那张卡加入手卡。这个效果在这张卡送去墓地的回合不能发动。"
    "④：自己场上有龙族怪兽存在的场合，把这张卡从手卡丢弃才能发动。"
    "从卡组把1张「融合」加入手卡，那之后自己从卡组抽1张。"
    "⑤：这张卡在墓地存在的场合，把自己墓地3只龙族怪兽除外才能发动。"
    "从卡组把1只「青眼」怪兽加入手卡，那之后自己从卡组抽1张。"
    "⑥：这张卡被除外的场合才能发动。这张卡回到墓地。"
    "⑦：这张卡的攻击力上升自己墓地的龙族怪兽数量×300。"
)
#: 真正「超长」的卡文：把上面这段展开 3 倍（≈1100 字），任何档位都塞不下
SUPER_LONG = SUPER_LONG_ZH * 3
EN_PSCT = (
    "Once per turn: You can target 1 monster your opponent controls; "
    "banish it, and if you do, Special Summon 1 \"Blue-Eyes White Dragon\" "
    "from your hand or Deck, and if you do that, it gains 1000 ATK until "
    "the end of this turn, also it cannot attack directly this turn. "
    "You can only use each of the following effects of \"Cardforge Dragon\" "
    "once per turn. If this card is sent to the GY: You can add 1 Spell "
    "from your Deck to your hand. You cannot Special Summon monsters "
    "the turn you activate this effect."
)
JA = (
    "①：１ターンに１度、自分フィールドのモンスター１体を対象として発動できる。"
    "そのモンスターの攻撃力はターン終了時まで１０００アップする。"
    "②：このカードが墓地へ送られた場合に発動できる。"
    "デッキから「青眼の白龍」１体を手札に加える。"
    "その後、自分はデッキから１枚ドローする。"
    "この効果を発動したターン、自分はモンスターを特殊召喚できない。"
)

TEXT_BOX_SHARE = scaled_box(frame_share, "text_box", "zh_cn")   # 813 画布：668×140


#: 题面要求的验证条件：排版在 **REF 单位**下做（FIT_PROFILES 标定的密度），
#: 等价于「Frame(1394,2031) 的 text_box 扣掉语言内缩后的可用区」（比例完全一致）。
_w_ref, _h_ref = frame_print.rect("text_box")[2:]
_l, _t, _r, _b = text_inset("zh_cn")
TEXT_BOX = (_w_ref - _l - _r, _h_ref - _t - _b)          # REF 单位的可用区
TEXT_SCALE = 1.0                                         # REF 单位 → font_of 收到 REF 磅
#: 同一块地方在 1394 画布上的像素尺寸与字号倍率（给「画布像素约定」用）
TEXT_BOX_PX = (TEXT_BOX[0] * frame_print.k, TEXT_BOX[1] * frame_print.ky)
TEXT_SCALE_PX = frame_print.k
out(f"  文本框（REF 单位，题面 Frame(1394,2031) 的 text_box 扣内缩）= "
    f"{TEXT_BOX[0]:.1f} × {TEXT_BOX[1]:.1f}")
out(f"  同一块地方在 1394 画布上 = {TEXT_BOX_PX[0]:.1f} × {TEXT_BOX_PX[1]:.1f} px，"
    f"字号倍率 Frame.k = {TEXT_SCALE_PX:.3f}")


def show_fit(title: str, text: str, lang: str, font_of, profile="description",
             box: tuple[float, float] | None = None, psct=True,
             size_scale: float | None = None) -> T.Fitted:
    box = box or TEXT_BOX
    sc = TEXT_SCALE if size_scale is None else size_scale
    out("")
    out(f"  ── {title} ──  box={box[0]:.0f}×{box[1]:.0f} size_scale={sc:.2f}")
    fit = T.render_lines(text, font_of, box, lang, profile, psct=psct,
                         apply_inset=False, size_scale=sc)
    out(f"     字号={fit.size}  行高={fit.line_height:.1f}  横压={fit.squeeze_x:.2f}  "
        f"行数={len(fit.lines)}  占高={fit.block_height:.1f}/{box[1]:.1f}  "
        f"overflow={fit.overflow}")
    for i, l in enumerate(fit.lines, 1):
        w = T.measure_runs(l, font_of, fit.size)
        ind = fit.indent_of(i - 1)
        out(f"       L{i} ind={ind:5.1f} w={w:7.1f} ({w / box[0] * 100:5.1f}%) "
            f"|{T.line_text(l)}")
    return fit


f_long = show_fit(f"中文 200+ 字（{len(LONG_ZH)} 字）", LONG_ZH, "zh_cn", zh_font)
check(not f_long.overflow, "200 字中文不 overflow")
check(len(f_long.lines) <= 5, f"200 字中文行数 ≤ 5（实际 {len(f_long.lines)}）")
check(0.80 - 1e-9 <= f_long.squeeze_x <= 1.0 + 1e-9, "squeeze_x 在 0.80~1.00")

f_over = show_fit(f"中文超长（{len(SUPER_LONG)} 字，≈7 张卡的正文）", SUPER_LONG,
                  "zh_cn", zh_font)
profile_sizes = [int(round(t["fontSize"])) for t in T._profile_tiers("description")]
out(f"     description 档位字号 = {profile_sizes}（最小档 = {min(profile_sizes)}）")
check(f_over.overflow or f_over.size == min(profile_sizes),
      f"超长卡文触发降档到最小档或 overflow（size={f_over.size}, "
      f"overflow={f_over.overflow}）")
check(f_over.overflow and f_over.size in profile_sizes,
      f"overflow 时仍返回合法档位（size={f_over.size} ∈ {profile_sizes}）")
_oob = [T.measure_runs(l, zh_font, f_over.size) * f_over.squeeze_x
        for l in f_over.lines]
check(max(_oob) <= TEXT_BOX[0] * 1.03,
      f"横压后每行基本落在框内（最宽 {max(_oob):.1f} vs {TEXT_BOX[0]:.1f}；"
      f"禁则拉回允许超出 1 个字符以内）")
check(1.0 - T._MAX_COMPRESS - 1e-9 <= f_over.squeeze_x <= 1.0 + 1e-9,
      f"横压比在下限内（{f_over.squeeze_x:.2f} ∈ [{1 - T._MAX_COMPRESS:.2f}, 1.00]）")
_oob5 = [T.measure_runs(l, zh_font, f_long.size) * f_long.squeeze_x
         for l in f_long.lines]
check(max(_oob5) <= TEXT_BOX[0] + 2,
      f"200 字那档横压后也在框内（最宽 {max(_oob5):.1f} ≤ {TEXT_BOX[0]:.1f}）")

# 同一段 200 字文本放在「官方排版真实密度」的小框里对照（FIT_PROFILES 的标定基准）
f_share = show_fit("同一段 200+ 字，放在 813 画布（官方密度）",
                   LONG_ZH, "zh_cn", zh_font, box=TEXT_BOX_SHARE, size_scale=1.0)
check(not f_share.overflow, "813 画布下 200 字不 overflow")
check(0.80 - 1e-9 <= f_share.squeeze_x <= 1.0 + 1e-9,
      f"813 画布下 squeeze_x 在合法区间（{f_share.squeeze_x:.2f}）")
out("")
out("  ── 单位约定对照：box 单位与 size_scale 必须**配套** ──")
_hybrid = T.render_lines(LONG_ZH, zh_font, TEXT_BOX, "zh_cn",
                         apply_inset=False, size_scale=TEXT_SCALE_PX)
out(f"     REF box(668×167) + size_scale=1.00   → size={f_share.size:3d} "
    f"行数={len(f_share.lines)}  （✅ FIT_PROFILES 标定的官方密度）")
out(f"     REF box 同上      + size_scale={TEXT_SCALE_PX:.2f}  → size={_hybrid.size:3d} "
    f"行数={len(_hybrid.lines)}  （❌ 画布倍率套在 REF box 上：字号被虚增）")
_canvas = T.render_lines(LONG_ZH, zh_font,
                         (TEXT_BOX_SHARE[0] * TEXT_SCALE_PX,
                          TEXT_BOX_SHARE[1] * TEXT_SCALE_PX), "zh_cn",
                         apply_inset=False, size_scale=TEXT_SCALE_PX)
out(f"     画布 box(×{TEXT_SCALE_PX:.2f}) + size_scale={TEXT_SCALE_PX:.2f} → "
    f"size={_canvas.size:3d} 行数={len(_canvas.lines)}  （✅ 同一块地方的画布写法）")
check(len(_canvas.lines) == len(f_share.lines),
      f"两种正确写法行数一致（{len(_canvas.lines)} vs {len(f_share.lines)}）")
check(abs(_canvas.size - f_share.size * TEXT_SCALE_PX) <= 2,
      f"画布写法字号 = REF 字号 × 倍率（{_canvas.size} ≈ {f_share.size}×{TEXT_SCALE_PX:.2f}"
      f"={f_share.size * TEXT_SCALE_PX:.0f}）")
check(_hybrid.size > f_share.size,
      f"错配 size_scale 会虚增字号（{_hybrid.size} > {f_share.size}）—— "
      f"把画布倍率与 REF box 混用就会得到「密度放大 k 倍」的排版")

f_en = show_fit(f"英文 PSCT（{len(EN_PSCT)} 字）", EN_PSCT, "en", en_font)
check(all(t[0] not in ",." for t in f_en.texts() if t), "英文没有行以 , 或 . 开头")
check(not f_en.overflow, "英文 PSCT 不 overflow")

f_ja = show_fit(f"日文（{len(JA)} 字）", JA, "ja", ja_font)
bad_ja = [t for t in f_ja.texts() if t and t[0] in "」。"]
check(not bad_ja, "日文没有行以 」 或 。 开头" + (f" ← {bad_ja}" if bad_ja else ""))
check(not f_ja.overflow, "日文不 overflow")

# 极端：极小框 → 必须 overflow 而不抛异常
try:
    f_tiny = T.render_lines(SUPER_LONG_ZH * 3, zh_font, (60.0, 30.0), "zh_cn")
    out(f"    极小框(60×30) → size={f_tiny.size} 行数={len(f_tiny.lines)} "
        f"overflow={f_tiny.overflow}")
    check(f_tiny.overflow, "极小框触发 overflow=True（不抛异常）")
except Exception:
    check(False, "极小框应当只置 overflow，不应抛异常：" + traceback.format_exc())

# ══════════════════════════════════════════════════════════════════════
head("4. 渲染 4 张验证图")

PAL = palette("effect", "光")
CANVAS_PAD = 24


def render_card(fit: T.Fitted, font_of, title: str, box=TEXT_BOX,
                path: Path | None = None) -> Path:
    W = int(box[0]) + CANVAS_PAD * 2
    H = int(box[1]) + CANVAS_PAD * 2
    img = Image.new("RGB", (W, H), PAL.text_panel)
    d = ImageDraw.Draw(img)
    d.rectangle([CANVAS_PAD - 1, CANVAS_PAD - 1, CANVAS_PAD + box[0], CANVAS_PAD + box[1]],
                outline=(200, 60, 40), width=1)
    T.draw_fitted(d, fit, (CANVAS_PAD, CANVAS_PAD), font_of, PAL.text_ink,
                  bold_fill=(150, 40, 10))
    path = path or (OUT_DIR / (title + ".png"))
    img.save(path)
    out(f"    写出 {path}  （{W}×{H}，字号 {fit.size}，横压 {fit.squeeze_x:.2f}）")
    return path


imgs = []
imgs.append(render_card(f_long, zh_font, "t_zh_long"))
imgs.append(render_card(f_over, zh_font, "t_zh_over"))
imgs.append(render_card(f_en, en_font, "t_en_psct"))
imgs.append(render_card(f_ja, ja_font, "t_ja"))

# 额外：横压对照图（同一段文字 squeeze_x=1.0 / 0.90 / 0.80）
head("4b. 横压对照（squeeze_x 1.00 / 0.90 / 0.80）")
panel_w, panel_h = TEXT_BOX_SHARE          # 668×140，方便一眼看清字形变形
demo_text = ("①：1回合1次，以自己场上1只「青眼」怪兽为对象才能发动。"
             "那只怪兽的攻击力直到回合结束时上升1000。")
fit_demo = T.render_lines(demo_text, zh_font, (panel_w, panel_h), "zh_cn",
                          apply_inset=False)
out(f"    demo 自动结果：size={fit_demo.size} 行数={len(fit_demo.lines)} "
    f"squeeze={fit_demo.squeeze_x:.2f}")
combo = Image.new("RGB", (int(panel_w) + 48, (int(panel_h) + 26) * 3 + 24),
                  (250, 246, 240))
for k, sx in enumerate((1.00, 0.90, 0.80)):
    dd = ImageDraw.Draw(combo)
    y0 = 24 + k * (panel_h + 26)
    dd.text((12, y0 - 18), f"squeeze_x = {sx:.2f}", fill=(90, 20, 10))
    dd.rectangle([11, y0 - 1, panel_w + 12, y0 + panel_h], outline=(200, 60, 40))
    T.draw_fitted(dd, fit_demo, (12, y0), zh_font, PAL.text_ink, squeeze_x=sx,
                  bold_fill=(150, 40, 10))
combo_path = OUT_DIR / "t_squeeze.png"
combo.save(combo_path)
out(f"    写出 {combo_path}")
imgs.append(combo_path)

# ══════════════════════════════════════════════════════════════════════
head("5.5 边界情况（不应抛异常）")
EDGE = [
    ("空串", "", "zh_cn"),
    ("只有空白", "   \u3000  ", "zh_cn"),
    ("单个字", "卡", "zh_cn"),
    ("超长无空格英文单词", "A" * 120, "en"),
    ("含换行", "第一行\n第二行", "zh_cn"),
    ("纯标点", "。，、！？", "zh_cn"),
    ("开头就是禁则字符", "）。这张卡", "zh_cn"),
    ("全角数字", "１２３４５", "zh_cn"),
    ("连排编号", "①②③", "zh_cn"),
    ("(1)(2) 形式", "(1)First effect. (2)Second effect.", "en"),
]
for title, txt, lg in EDGE:
    try:
        runs = T.mark_psct(txt, lg)
        assert "".join(r.text for r in runs) == txt, "mark_psct 改了字符"
        fo = {"zh_cn": zh_font, "en": en_font}.get(lg, zh_font)
        f = T.fit(runs, fo, (box_w, box_h), lg, apply_inset=False)
        lines = f.texts()
        check(True, f"{title}: {len(lines)} 行 size={f.size} overflow={f.overflow} "
                    f"texts={lines!r}")
    except Exception:
        check(False, f"{title} 抛异常：{traceback.format_exc().splitlines()[-1]}")

# 显式换行必须是**硬断行**（不能被当成空格吞掉）
_nl = T.fit([T.TextRun("第一行\n第二行\n\n第四行")], zh_font, (box_w, box_h), "zh_cn",
            apply_inset=False)
out(f"  含 \\n 文本 → {len(_nl.lines)} 行: {_nl.texts()!r}")
check(_nl.texts()[:2] == ["第一行", "第二行"], "显式 \\n 处硬断行")
check(all(ln.strip() for ln in _nl.texts()), "没有把空行当成有内容的行")

# ══════════════════════════════════════════════════════════════════════
head("6. 性能（旧版 476 字 2.7 s）")
import time  # noqa: E402

big = SUPER_LONG_ZH * 3
T.clear_cache()
t0 = time.perf_counter()
f_big = T.render_lines(big, zh_font, TEXT_BOX, "zh_cn", apply_inset=False)
t1 = time.perf_counter()
T.clear_cache()
t2 = time.perf_counter()
f_big2 = T.render_lines(big, zh_font, TEXT_BOX, "zh_cn", apply_inset=False)
t3 = time.perf_counter()
out(f"  {len(big)} 字：冷缓存 {(t1 - t0) * 1000:.1f} ms，热缓存 {(t3 - t2) * 1000:.1f} ms "
    f"（{len(f_big.lines)} 行, size={f_big.size}, overflow={f_big.overflow}）")
check((t1 - t0) < 0.6, f"冷缓存 1000+ 字排版 < 600 ms（实际 {(t1 - t0) * 1000:.0f} ms）")

# ══════════════════════════════════════════════════════════════════════
head("结论")
out(f"  失败断言 {len(FAILS)} 条")
for f in FAILS:
    out("   - " + f)
out(f"  图片: " + " , ".join(str(p) for p in imgs))

REPORT.write_text(buf.getvalue(), encoding="utf-8")
print(f"\n报告写入 {REPORT}")
sys.exit(1 if FAILS else 0)
