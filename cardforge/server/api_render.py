"""``/api/render/*`` —— 卡面预览、导出、能力分层。

预览有**两条通道**，界面按 ``/api/render/capabilities`` 自动选：

* ``preview.png``  —— Pillow 真渲染（L1）。所见即最终产物。
* ``preview.svg``  —— 浏览器矢量（L0）。没装 Pillow 也能看到版面，
  但它是**近似**，所以界面会明确标注「矢量预览，非最终出图」。
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Optional

from ..core import errors, paths
from ..core.enums import FULL_ART_MODES, LANGS, RARITIES
from ..core.models import CardSpec, FullArtOptions
from . import kernel as K
from .api_card import _spec_of
from .http import Request, Response

__all__ = ["register"]


def register(app) -> None:

    @app.get("/api/render/capabilities")
    def render_capabilities(req: Request) -> dict:
        comp = K.try_import("cardforge.render.compositor")
        if comp is None:
            return {"ok": False, "L1_render": False,
                    "reason": "cardforge.render 导入失败",
                    "hint": "界面会退回矢量预览", "levels": _levels_fallback()}
        try:
            caps = comp.capabilities()
        except Exception as e:
            return {"ok": False, "L1_render": False, "error": str(e),
                    "hint": "渲染层出问题，界面会用矢量通道",
                    "levels": _levels_fallback()}
        caps = dict(caps or {})
        caps.setdefault("ok", True)
        caps["raster_preview"] = bool(caps.get("L1_render") or caps.get("pillow"))
        caps["levels"] = _levels_fallback()
        return caps

    @app.get("/api/render/preview")
    def preview_get(req: Request) -> Response:
        """``?card=<id>&width=480`` —— 给 ``<img src>`` 直接用。"""
        data, ctype = _preview(req)
        return Response(data, content_type=ctype, headers={
            "Cache-Control": "no-store", "X-CardForge-Preview": "raster"})

    @app.post("/api/render/preview")
    def preview_post(req: Request) -> Response:
        data, ctype = _preview(req)
        return Response(data, content_type=ctype, headers={
            "Cache-Control": "no-store", "X-CardForge-Preview": "raster"})

    @app.get("/api/render/svg")
    def preview_svg(req: Request) -> Response:
        spec = _view_spec(req)
        comp = K.require("cardforge.render.compositor", "矢量预览")
        try:
            svg = comp.render_svg(spec, art_uri=_art_uri(spec) if req.bool_arg("art", True)
                                  else None, width=req.int_arg("width", 813))
        except Exception as e:
            raise errors.CardForgeError(f"矢量预览生成失败：{e}",
                                         "把这张卡的 spec.json 反馈出来") from e
        return Response(svg, content_type="image/svg+xml; charset=utf-8",
                        headers={"Cache-Control": "no-store",
                                 "X-CardForge-Preview": "vector"})

    @app.post("/api/render/export")
    def render_export(req: Request) -> dict:
        """出成品图。``sizes`` 可给多个：edopro / compat / share / print / native。"""
        spec = _view_spec(req)
        comp = K.require("cardforge.render.compositor", "卡面导出")
        sizes = req.arg("sizes") or ["edopro"]
        if isinstance(sizes, str):
            sizes = [s.strip() for s in sizes.split(",") if s.strip()]
        fmt = req.str_arg("fmt", "jpg")
        out_dir = Path(req.str_arg("out_dir") or paths.OUT)
        out_dir.mkdir(parents=True, exist_ok=True)
        art = _load_art(spec) if req.bool_arg("use_art", True) else None
        layers = _load_layers(spec) if spec.render.fullart.mode == "subject_bleed" else {}
        try:
            files = comp.export_card(spec, art, out_dir, sizes=tuple(sizes),
                                     fmt=fmt, quality=req.int_arg("quality", 92),
                                     name=req.str_arg("name") or None, layers=layers)
        except Exception as e:
            raise errors.CardForgeError(f"导出失败：{e}",
                                        "确认输出目录可写、磁盘空间充足") from e
        # 顺手把 edopro 尺寸的图放_progress pics/<id>.jpg，导出包才带得上图
        copied = _sync_pic(spec, files)
        return {"ok": True, "files": [paths.rel(Path(f)) for f in files],
                "pic": copied, "sizes": sizes, "format": fmt}

    @app.get("/api/render/card-image")
    def card_image(req: Request) -> Response:
        """**直接导出卡面** —— 一次性返回成品图字节流，浏览器就地下载。

        与 ``POST /api/render/export`` 的区别：那个是写进工作区 ``out/`` 并回
        相对路径（给导出包用），用户还得自己去文件夹里翻。这里是「我要这张
        图」这条路径 —— 直接以附件形式吐给浏览器。

        参数：``card`` 或 ``spec``（未落盘的草稿也能导）、``size``（默认 edopro）、
        ``fmt``（jpg/png/webp）、``sizes``（多个则打包成 zip）、``scale``（放大倍数）。
        """
        spec = _view_spec(req)
        comp = K.require("cardforge.render.compositor", "卡面导出")
        art = _load_art(spec) if req.bool_arg("use_art", True) else None
        layers = _load_layers(spec) if spec.render.fullart.mode == "subject_bleed" else {}

        sizes = _sizes_arg(req)
        fmt = (req.str_arg("fmt", "jpg") or "jpg").lower()
        if fmt not in ("jpg", "jpeg", "png", "webp"):
            raise errors.SpecError(f"不支持的图片格式：{fmt}",
                                   "可用 jpg / png / webp")
        fmt = "jpg" if fmt == "jpeg" else fmt
        scale = float(req.arg("scale", 1) or 1)
        scale = max(0.25, min(scale, 8.0))
        stamp = req.bool_arg("stamp", False)

        def render_one(size: str) -> bytes:
            try:
                out_size = None
                if scale != 1.0:
                    from ..render import geometry as G
                    base = G.OUTPUT_SIZES.get(size, G.OUTPUT_SIZES[G.DEFAULT_OUTPUT])
                    out_size = (int(round(base[0] * scale)), int(round(base[1] * scale)))
                img = comp.render_card(spec, art, size=(out_size or size), layers=layers)
                buf = io.BytesIO()
                if fmt == "jpg":
                    img.save(buf, "JPEG", quality=int(req.int_arg("quality", 95) or 95),
                             subsampling=1, optimize=True)
                elif fmt == "webp":
                    img.save(buf, "WEBP", quality=int(req.int_arg("quality", 95) or 95),
                             method=5)
                else:
                    img.save(buf, "PNG", optimize=True)
                return buf.getvalue()
            except Exception as e:
                raise errors.CardForgeError(
                    f"卡面渲染失败：{e}",
                    "运行 python -m cardforge doctor 看渲染层缺什么") from e

        # 多个尺寸 → 一个 zip，省得下载一串文件
        if len(sizes) > 1:
            import zipfile
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for s in sizes:
                    zf.writestr(f"{spec.id}_{s}.{fmt}", render_one(s))
            name = f"{_safe_name(spec)}_{fmt}.zip"
            return Response(buf.getvalue(), content_type="application/zip", headers={
                "Content-Disposition": _attachment(name),
                "Cache-Control": "no-store",
                "X-CardForge-Export": ",".join(sizes)})

        size = sizes[0]
        data = render_one(size)
        ctype = {"jpg": "image/jpeg", "png": "image/png",
                 "webp": "image/webp"}[fmt]
        name = f"{_safe_name(spec)}"
        if size not in ("edopro", "compat"):
            name += f"_{size}"
        if scale != 1.0:
            name += f"@{scale:g}x"
        name += f".{fmt}"
        # 顺手同步一份到 pics/<id>.jpg，导出包按这个位置找图
        if size in ("edopro", "compat") and fmt == "jpg" and not stamp:
            _write_pic(spec, data)
        return Response(data, content_type=ctype, headers={
            "Content-Disposition": _attachment(name),
            "Cache-Control": "no-store",
            "X-CardForge-Export": size})

    @app.get("/api/render/stages")
    def render_stages(req: Request) -> dict:
        """逐层输出（排查「哪一层画歪了」用）。返回每层的文件路径。"""
        spec = _view_spec(req)
        comp = K.require("cardforge.render.compositor", "分层调试图")
        out_dir = Path(paths.OUT) / "stages" / str(spec.id)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            stages = comp.render_stages(spec, _load_art(spec),
                                        size=req.str_arg("size", "share"))
        except Exception as e:
            raise errors.CardForgeError(f"分层渲染失败：{e}", "先看 capabilities 报告") from e
        written: dict[str, str] = {}
        for name, img in (stages or {}).items():
            try:
                p = out_dir / f"{name}.png"
                img.save(p, "PNG")
                written[str(name)] = paths.rel(p)
            except Exception as e:
                written[str(name)] = f"(保存失败 {e})"
        return {"ok": True, "stages": written, "dir": paths.rel(out_dir)}

    @app.post("/api/render/upload-art")
    def upload_art(req: Request) -> dict:
        """用户上传自己的卡图 → 存进卡图资产库。

        「本地出图不可用时还能用自己的图」这条通路必须一直开着。
        """
        cid = req.int_arg("card")
        if not cid:
            raise errors.SpecError("要指定 card=<卡号>", "先选中一张卡再上传卡图")
        raw = req.arg("image")
        if not raw:
            raise errors.SpecError("没有收到图片数据",
                                   "前端把文件读成 base64 放到 image 字段")
        if isinstance(raw, str) and "," in raw and raw.startswith("data:"):
            raw = raw.split(",", 1)[1]
        import base64
        try:
            data = base64.b64decode(raw)
        except Exception as e:
            raise errors.SpecError(f"图片数据解码失败：{e}", "确认是 data:image 或纯 base64") from e
        spec = K.load_spec(cid)
        lib = K.require("cardforge.art.library", "卡图资产库")
        try:
            rec = lib.save(cid, data, {"source": "upload", "card": cid,
                                        "archetype": spec.archetype},
                           archetype=spec.archetype or "")
        except Exception as e:
            raise errors.CardForgeError(f"卡图入库失败：{e}", "检查 pics/ 目录可写") from e
        return {"ok": True, "saved": rec,
                "preview": _art_url(spec)}


# ══════════════════════════════════════════════════════════════════════
#  内部
# ══════════════════════════════════════════════════════════════════════
#: 允许直接导出的成品尺寸（顺序即界面上的常见顺序）。
EXPORT_SIZES: tuple[str, ...] = ("edopro", "mdpro3", "share", "print300",
                                 "print", "native", "compat", "archive")


def _sizes_arg(req: Request) -> list[str]:
    """解析 ``size`` / ``sizes``，去重并对白名单校验。"""
    from ..render import geometry as G
    raw: list[str] = []
    for key in ("size", "sizes"):
        v = req.arg(key)
        if v is None or v == "":
            continue
        raw.extend(v if isinstance(v, (list, tuple)) else str(v).split(","))
    got = [s.strip() for s in raw if str(s).strip()]
    if not got:
        got = [G.DEFAULT_OUTPUT]
    out: list[str] = []
    for s in got:
        if s not in G.OUTPUT_SIZES:
            raise errors.SpecError(
                f"未知尺寸：{s}", "可用：" + "、".join(G.OUTPUT_SIZES))
        if s not in out:
            out.append(s)
    return out


def _safe_name(spec: CardSpec) -> str:
    """文件名：卡号（唯一、无非法字符）+ 卡名便于人认。

    卡名可能为空、也可能只由非法字符组成 —— 那样拼出来会得到
    ``210000011_.jpg`` 这种带尾下划线的丑名字，所以先判空再拼。
    """
    import re
    zh = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", str(getattr(spec, "name", "") or "")).strip()
    base = str(spec.id)
    return f"{base}_{zh}" if zh else base


def _attachment(filename: str) -> str:
    """RFC 5987 附件头 —— 中文文件名必须给 ``filename*``，否则浏览器乱码。

    ``filename=`` 只作老浏览器降级：中文会被剔掉，所以顺手把留下的
    分隔符（连续/尾部下划线）收干净，别导出成 ``210000011_.jpg``。
    """
    import os
    import re
    from urllib.parse import quote
    stem, ext = os.path.splitext(filename)
    ascii_fallback = stem.encode("ascii", "ignore").decode("ascii")
    ascii_fallback = re.sub(r"_+", "_", ascii_fallback).strip("_") + ext
    if ascii_fallback in ("", ext) or ascii_fallback.startswith("."):
        ascii_fallback = "card" + ext
    return (f'attachment; filename="{ascii_fallback}"; '
            f"filename*=UTF-8''{quote(filename)}")


def _write_pic(spec: CardSpec, data: bytes) -> str:
    """把成品写一份到 ``pics/<id>.jpg``，供导出包与 ygopro 客户端直接取用。"""
    try:
        dst = paths.pic_path(spec.id)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        return paths.rel(dst)
    except Exception:
        return ""


def _preview(req: Request) -> tuple[bytes, str]:
    """渲染预览。Pillow 不可用时**自动回落 SVG**，界面无感。"""
    spec = _view_spec(req)
    comp = K.try_import("cardforge.render.compositor")
    if comp is None:
        return _svg_bytes(spec, req), "image/svg+xml; charset=utf-8"
    width = max(120, min(int(req.int_arg("width", 480) or 480), 1394))
    try:
        art = _load_art(spec) if req.bool_arg("use_art", True) else None
        layers = _load_layers(spec) if spec.render.fullart.mode == "subject_bleed" else {}
        data = comp.preview_png(spec, art, width=width, layers=layers)
        return data, "image/jpeg"
    except Exception as e:
        # 预览绝不能让界面白屏：记下原因，退回矢量通道
        spec_note = f"{type(e).__name__}: {e}"
        body = _svg_bytes(spec, req)
        return body, "image/svg+xml"


def _svg_bytes(spec: CardSpec, req: Request) -> bytes:
    comp = K.require("cardforge.render.compositor", "矢量预览")
    try:
        return comp.render_svg(spec, art_uri=_art_uri(spec),
                               width=req.int_arg("width", 480)).encode("utf-8")
    except Exception as e:
        # 连 SVG 都画不出来时给一张写实的占位图，而不是一张空白卡骗人
        return _placeholder_svg(f"预览生成失败：{type(e).__name__}: {e}",
                               spec.display_name or "未命名卡")


def _view_spec(req: Request) -> CardSpec:
    """取规格 + 应用界面上的即时渲染参数（**不落盘**，只影响本次预览）。"""
    spec = _spec_of(req)
    r = spec.render
    for key in ("rarity", "lang_name", "lang_text", "lang_flavor", "art_fit",
                "text_align", "output_size", "copyright_lang", "set_number"):
        v = req.arg(key)
        if v is not None and str(v) != "":
            setattr(r, key, str(v))
    for key in ("art_scale", "art_offset_y", "font_scale_name", "font_scale_text",
                "art_ring", "bezel"):
        v = req.arg(key)
        if v is not None and str(v) != "":
            try:
                setattr(r, key, float(v))
            except Exception:
                pass
    for key in ("psct_bold", "show_password", "show_copyright", "show_stamp20",
                "show_laser"):
        v = req.arg(key)
        if v is not None:
            if isinstance(v, bool):
                setattr(r, key, v)
            else:
                setattr(r, key, str(v).lower() in ("1", "true", "yes", "on"))
    if req.arg("preview_width") is not None:
        try:
            r.preview_width = int(req.arg("preview_width"))
        except Exception:
            pass
    fa = req.arg("fullart")
    if fa is not None and str(fa) != "":
        mode = str(fa)
        if mode not in FULL_ART_MODES:
            raise errors.SpecError(f"未知的出框档位：{mode}",
                                   f"可用：{'、'.join(FULL_ART_MODES)}")
        opts = FullArtOptions(mode=mode)
        defaults = _fullart_default(mode)
        opts.bleed_top = float(req.arg("bleed_top", defaults.get("bleed_top", 0.0)))
        opts.bleed_bottom = float(req.arg("bleed_bottom",
                                          defaults.get("bleed_bottom", 0.0)))
        opts.panel_opacity = float(req.arg("panel_opacity",
                                           defaults.get("panel_opacity", 0.86)))
        opts.name_stroke = float(req.arg("name_stroke",
                                         defaults.get("name_stroke", 1.6)))
        opts.fade_px = float(req.arg("fade_px", defaults.get("fade_px", 0.0)))
        # 主体出框档专用：主体放大倍率与垂直偏移
        opts.subject_scale = float(req.arg("subject_scale",
                                           defaults.get("subject_scale", 0.0)))
        opts.subject_offset_y = float(req.arg("subject_offset_y",
                                              defaults.get("subject_offset_y", 0.0)))
        r.fullart = opts
    if r.rarity not in RARITIES:
        r.rarity = "common"
    return spec


def _fullart_default(mode: str) -> dict:
    try:
        from ..render import geometry as G
        return dict((G.FULLART_DEFAULTS or {}).get(mode, {}) or {})
    except Exception:
        return {}


def _art_path(spec: CardSpec) -> Optional[Path]:
    """当前卡图（用户自己的或本地生成的）。"""
    lib = K.try_import("cardforge.art.library")
    if lib is not None:
        try:
            cur = lib.current(spec.id, spec.archetype or "")
            if cur and cur.get("file"):
                p = Path(lib.dir_for(spec.id, spec.archetype or "")) / cur["file"]
                if p.exists():
                    return p
        except Exception:
            pass
    for cand in (paths.pic_path(spec.id), paths.pic_path(spec.id, "png")):
        if Path(cand).exists():
            return Path(cand)
    return None


def _load_art(spec: CardSpec):
    p = _art_path(spec)
    if p is None:
        return None
    try:
        from PIL import Image
        img = Image.open(p)
        img.load()
        return img.convert("RGB")
    except Exception:
        return None


def _load_layers(spec: CardSpec) -> dict:
    """分层卡图（背景 + 带 alpha 的主体）。没有分层就返回 ``{}``。

    只有 ``fullart.mode == "subject_bleed"``（主体出框）用得上；这里保留 RGBA，
    压平件走的是 :func:`_load_art`，两条路互不影响。
    """
    lib = K.try_import("cardforge.art.library")
    if lib is None:
        return {}
    try:
        got = lib.load_for_render(spec.id, spec.archetype or "") or {}
    except Exception:
        return {}
    out = {}
    for role in ("background", "subject"):
        im = got.get(role)
        if im is not None:
            try:
                out[role] = im.convert("RGBA")
            except Exception:
                pass
    return out


def _art_uri(spec: CardSpec) -> Optional[str]:
    """把卡图编成 data URI 给 SVG 通道嵌入。"""
    p = _art_path(spec)
    if p is None:
        return None
    try:
        import base64
        data = p.read_bytes()
        if len(data) > 6 * 1024 * 1024:
            return None
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    except Exception:
        return None


def _art_url(spec: CardSpec) -> str:
    p = _art_path(spec)
    if p is None:
        return ""
    try:
        return "/api/files/" + paths.rel(p).replace("\\", "/")
    except Exception:
        return ""


def _sync_pic(spec: CardSpec, files: list[str]) -> str:
    """把 edopro 尺寸的成品放到 ``pics/<id>.jpg`` —— 导出包按这个位置找图。"""
    src = None
    for f in files:
        p = Path(f)
        if p.stem == str(spec.id) and p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            src = p
            break
    if src is None:
        return ""
    dst = paths.pic_path(spec.id)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        return paths.rel(dst)
    except Exception:
        return ""


def _levels_fallback() -> dict:
    return {"L0-data": True}


def _placeholder_svg(why: str, name: str) -> bytes:
    def esc(s: str) -> str:
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="421" height="614"
 viewBox="0 0 421 614"><rect width="421" height="614" fill="#3b3a37"/>
<rect x="10" y="10" width="401" height="594" fill="none" stroke="#8b7a55"/>
<text x="210" y="40" fill="#e8dcc0" font-size="20" text-anchor="middle"
 font-family="serif">{esc(name)}</text>
<text x="210" y="300" fill="#ffb4b4" font-size="13" text-anchor="middle">卡面渲染失败</text>
<text x="210" y="330" fill="#ddd" font-size="10" text-anchor="middle">{esc(why)[:90]}</text>
<text x="210" y="360" fill="#aaa" font-size="10" text-anchor="middle">
运行 python -m cardforge doctor 看缺什么</text></svg>"""
    return svg.encode("utf-8")
