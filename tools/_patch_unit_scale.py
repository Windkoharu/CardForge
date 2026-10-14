"""修正 layers.py 的单位双重放大 bug（由 text.py 子代理发现并报告）。

问题
----
``fit()`` 内部把**档位字号交给 font_of 回调**，但**行距自己算**。于是两种接法都不对：

  A) box 用 REF 单位 + font_of 不缩放
       → 字宽是 REF 尺度、box 也是 REF 尺度 ✓，但 fit 内部的 max_h 检查用的是
         REF 行距（30），而调用方传的 h 是画布像素（291）→ 允许 9 行，实际只放得下 5 行。
  B) box 用画布像素 + font_of 乘 f.k （**我原来的写法**）
       → max_h 检查正确 ✓，但字宽被放大 1.714 倍而 box 宽度没放大
         → 每行只能塞 13 个字（应 22 个）→ **同一段文字从 5 行变 9 行，后两段被裁掉**。

正确接法
--------
text.py 新增了可选参数 ``size_scale``：它让 ``fit()`` 把**字号与行距一起**乘上该系数。
于是：box 传画布像素，``size_scale = f.k × 用户缩放``，``font_of`` 用**像素字号直取字体**。
三项单位全部落在画布像素上，不再有任何一个维度错位。

`Fitted.size` 此时就是最终像素字号，成为唯一真相源（原先我在调用方又乘了一次
``lang_scale`` 算展示字号，zh_cn/ja 会差 3%，一并修掉）。
"""
import ast
import pathlib

P = (pathlib.Path(__file__).resolve().parents[1]
     / "cardforge" / "render" / "layers.py")
s = P.read_text(encoding="utf-8")
orig = s
applied = []


def sub(a: str, b: str, tag: str) -> None:
    global s
    if a not in s:
        print(f"  [SKIP] {tag}")
        return
    s = s.replace(a, b, 1)
    applied.append(tag)
    print(f"  [ OK ] {tag}")


# ── ① fit 的单位：改用画布像素 + size_scale ──────────────────────────
sub(
    """    # ⚠ 单位必须统一：``text.fit()`` 内部把档位字号与行距都当同一套单位算
    #   （`len(lines) * lineHeight <= max_h`），而我们的 ``font_of`` 才负责把它换算到
    #   画布像素。因此**传给 fit 的框宽高也要用 REF 单位**，否则行数上限会被放大
    #   f.k 倍，长卡文会一路画出文本框、压到数值行上（实测踩过）。
    fit_w = max(10.0, w / f.kx)
    fit_h = max(10.0, h / f.ky)""",
    """    # ⚠ 单位三件套必须落在同一个刻度上，否则行数会算错（实测踩过两次，见文件末尾注记）：
    #     · box 宽高      → **画布像素**（w / h 本来就是）
    #     · 字号          → ``size_scale`` 让 fit 内部把档位字号乘成画布像素
    #     · 行距          → fit 内部的 lh 同样被 size_scale 放大，与我们用的 lh_px 一致
    #   三者统一之后 ``font_of`` 只需按像素字号直取字体，不再自己缩放。
    fit_w = max(10.0, w)
    fit_h = max(10.0, h)
    px_scale = f.k * user_scale""",
    "fit 的单位口径",
)

# ── ② _fit_at：用像素字号钉死档位 + 传 size_scale ────────────────────
sub(
    """        px = max(8, int(round(tier_fs * f.k * user_scale)))

        def pinned(_size, _px=px):
            return font_of(_px)

        runs = (T.mark_psct(para, lang) if spec.render.psct_bold
                else [T.TextRun(para)])
        fit = T.fit(runs, pinned, (fit_w, max(10.0, avail_h_ref)), lang,
                    profile=profile, max_lines=None, min_size=1, apply_inset=False)
        fit.size = int(round(tier_fs * lang_scale))
        return fit""",
    """        # 该档在画布上的真实像素字号
        px = max(8, int(round(tier_fs * lang_scale * f.k * user_scale)))

        def pinned(_size, _px=px):
            return font_of(_px)

        runs = (T.mark_psct(para, lang) if spec.render.psct_bold
                else [T.TextRun(para)])
        fit = T.fit(runs, pinned, (fit_w, max(10.0, avail_h)), lang,
                    profile=profile, max_lines=None, min_size=1, apply_inset=False,
                    size_scale=px_scale)
        # fit.size 作为唯一真相源：此时它就是画布像素字号
        fit.size = px
        return fit""",
    "_fit_at 单位",
)

sub("    def _fit_at(para: str, tier_fs: float, avail_h_ref: float):",
    "    def _fit_at(para: str, tier_fs: float, avail_h: float):",
    "_fit_at 参数名")

# ── ③ 试档循环里的高度口径 ──────────────────────────────────────────
sub(
    """    for tier in tiers:
        fs = float(tier["fontSize"])
        lh_ref = max(float(tier["lineHeight"]), fs * MIN_LINE_RATIO)
        total_h = 0.0
        fits: list = []
        ok = True
        for para in paragraphs:
            fit = _fit_at(para, fs, fit_h - total_h)
            if fit.overflow:
                ok = False
                break
            total_h += len(fit.lines) * lh_ref + lh_ref * 0.28
            if total_h > fit_h + 0.5:
                ok = False
                break
            fits.append(fit)""",
    """    for tier in tiers:
        fs = float(tier["fontSize"])
        lh_tier = lh_px(tier)          # 画布像素，与 fit_h 同刻度
        total_h = 0.0
        fits: list = []
        ok = True
        for para in paragraphs:
            fit = _fit_at(para, fs, fit_h - total_h)
            if fit.overflow:
                ok = False
                break
            total_h += len(fit.lines) * lh_tier + lh_tier * 0.28
            if total_h > fit_h + 0.5:
                ok = False
                break
            fits.append(fit)""",
    "试档高度口径",
)

# ── ④ 兜底分支（连最小档都放不下）的高度口径 ────────────────────────
sub(
    """        best_tier = tiers[-1]
        fs_min = float(best_tier["fontSize"])
        lh_floor = max(float(best_tier["lineHeight"]), fs_min * MIN_LINE_RATIO)
        trial = []
        used = 0.0
        for para in paragraphs:
            avail = fit_h - used
            if avail <= lh_floor:
                break
            fit = _fit_at(para, fs_min, avail)
            keep = max(0, int(avail // lh_floor))""",
    """        best_tier = tiers[-1]
        fs_min = float(best_tier["fontSize"])
        lh_floor = lh_px(best_tier)     # 画布像素
        trial = []
        used = 0.0
        for para in paragraphs:
            avail = fit_h - used
            if avail <= lh_floor:
                break
            fit = _fit_at(para, fs_min, avail)
            keep = max(0, int(avail // lh_floor))""",
    "兜底分支高度口径",
)

# ── ⑤ 正式排版：draw_fitted 用像素字号直取字体；展示字号取 fit.size ──
sub(
    """        fit = (trial[i] if i < len(trial)
               else _fit_at(para, pin_fs, remain / f.ky))
        fit.line_height = lh          # 行距钉到画布像素（fit 内部给的是 REF 单位）""",
    """        fit = (trial[i] if i < len(trial)
               else _fit_at(para, pin_fs, remain))
        fit.line_height = lh          # 行距钉到画布像素（与 fit_h 同刻度）""",
    "正式排版 remain 口径",
)

sub(
    """        T.draw_fitted(d, fit, (x, cy), font_of_scaled, pal.text_ink,
                      squeeze_x=fit.squeeze_x,
                      bold_fill=(darken(pal.text_ink, 0.25)
                                 if spec.render.psct_bold else None))
        total_lines += len(fit.lines)
        cy += len(fit.lines) * lh + lh * (0.28 if i < len(paragraphs) - 1 else 0.0)
        if fit.overflow:
            overflow = True
            if i < len(paragraphs) - 1:
                break""",
    """        # fit.size 已是画布像素字号 → 这里用 font_of（按像素直取），不再二次缩放
        T.draw_fitted(d, fit, (x, cy), font_of, pal.text_ink,
                      squeeze_x=fit.squeeze_x,
                      bold_fill=(darken(pal.text_ink, 0.25)
                                 if spec.render.psct_bold else None))
        total_lines += len(fit.lines)
        cy += len(fit.lines) * lh + lh * (0.28 if i < len(paragraphs) - 1 else 0.0)
        if fit.overflow:
            overflow = True
            if i < len(paragraphs) - 1:
                break""",
    "draw_fitted 字体回调",
)

# ── ⑥ 返回值：字号单一来源 ──────────────────────────────────────────
sub(
    """    eff_size = float(best_tier["fontSize"]) * lang_scale * f.k * user_scale
    return {"lines": total_lines, "size": round(eff_size, 1),""",
    """    # 字号单一来源：与 draw_fitted 用的完全一致，避免调用方再乘一次导致 3% 偏差
    eff_size = float(best_tier["fontSize"]) * lang_scale * f.k * user_scale
    return {"lines": total_lines, "size": round(eff_size, 1),
            "size_px": int(round(eff_size)),""",
    "返回值字号",
)

if not applied:
    print("[X] 没有任何改动，请检查 layers.py 是否已被其他改动覆盖")
    raise SystemExit(1)

ast.parse(s)
P.write_text(s, encoding="utf-8", newline="")
print(f"\n已应用 {len(applied)} 处改动，语法检查通过")
