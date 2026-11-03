"""本轮缺陷修复的离线回归测试。

用法：python tools/selfcheck_regressions.py
所有产物只写 workspace/.cache/selfcheck-regressions-*/，不启动本地服务。
"""
from __future__ import annotations

import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from cardforge.art import library, run as art_run
from cardforge.core import errors, update
from cardforge.core.models import ArtRequest, CardSpec
from cardforge.export import expansions, mdpro3
from cardforge.pipeline import gates
from cardforge.pool import cdb
from cardforge.server import api_export, api_render
from cardforge.server import app as server_app
from cardforge.server.http import Request, read_body

TMP_ROOT = ROOT / "workspace" / ".cache"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.mkdtemp(prefix="selfcheck-regressions-", dir=TMP_ROOT))

PASS: list[str] = []
FAIL: list[tuple[str, str]] = []


def check(name: str, fn) -> None:
    try:
        fn()
    except Exception as e:
        FAIL.append((name, f"{type(e).__name__}: {e}"))
        print(f"[FAIL] {name}")
        traceback.print_exc(limit=4)
    else:
        PASS.append(name)
        print(f"[ OK ] {name}")


def card(cid: int, frame: str = "normal", **over) -> CardSpec:
    base = dict(id=cid, name=f"测试卡{cid}", frame=frame,
                attribute="光", race="战士族", level=4, atk=1000, dfd=800,
                flavor="用于导出回归测试。")
    base.update(over)
    return CardSpec(**base)


def request(method: str, path: str, **payload) -> Request:
    return Request(method, path, body=json.dumps(payload).encode("utf-8"),
                   headers={"content-type": "application/json"})


def api_routes() -> dict[tuple[str, str], object]:
    class Router:
        def __init__(self):
            self.handlers = {}

        def _on(self, method, path):
            def deco(fn):
                self.handlers[(method, path)] = fn
                return fn
            return deco

        def get(self, path):
            return self._on("GET", path)

        def post(self, path):
            return self._on("POST", path)

    router = Router()
    api_export.register(router)
    return router.handlers


def cdb_ids(path: str) -> set[int]:
    con = sqlite3.connect(path)
    try:
        return {int(r[0]) for r in con.execute("SELECT id FROM datas")}
    finally:
        con.close()


def test_reexport_sync() -> None:
    a, b = card(210100001), card(210100002)
    pack = TMP / "reexport"
    expansions.build([a, b], pack, name="sync", copy_pics=False)
    res = expansions.build([a], pack, name="sync", copy_pics=False)
    for path in res["cdbs"].values():
        assert cdb_ids(path) == {a.id}, (path, cdb_ids(path))
    errs = [i for i in expansions.verify(pack, check_official=False) if i.level == "ERROR"]
    assert not errs, [i.to_dict() for i in errs]


def test_g5_extra_card() -> None:
    a, b = card(210100011), card(210100012)
    pack = TMP / "extra"
    res = expansions.build([a], pack, name="extra", copy_pics=False)
    target = next(iter(res["cdbs"].values()))
    con = cdb.open_cdb(target)
    try:
        cdb.upsert_card(con, b)
    finally:
        con.close()
    issues = expansions.verify(pack, check_official=False)
    extra = [i for i in issues if i.code == "G5_CDB_ROW_EXTRA"]
    assert extra and all(i.level == "ERROR" for i in extra), [i.to_dict() for i in issues]


def test_g2_empty_script() -> None:
    for frame in ("effect", "spell", "trap"):
        rep = gates.g2_script(card(210100020, frame), "")
        assert rep.status == "warn" and rep.issues[0].code == "G2_NO_SCRIPT", (frame, rep.status)
    for frame in ("normal", "normal_pendulum", "token"):
        rep = gates.g2_script(card(210100021, frame), "")
        assert rep.status == "pass", (frame, rep.status, rep.issues)


def test_mdpro_collision_status() -> None:
    c = card(210100030)
    client = TMP / "md-client"
    official = client / "Data" / "locales" / "zh-CN" / "cards.cdb"
    con = cdb.open_cdb(official)
    try:
        cdb.upsert_card(con, c)
    finally:
        con.close()
    original = mdpro3.detect
    mdpro3.detect = lambda *a, **kw: [{"path": str(client)}]
    try:
        res = mdpro3.build([c], TMP / "collision.ypk", render_pics=False)
    finally:
        mdpro3.detect = original
    assert res["ok"] is False, res
    assert any(i["code"] == "MD_ID_COLLISION" for i in res["issues"]), res["issues"]


def test_api_build_failure_status() -> None:
    routes = api_routes()
    handler = routes[("POST", "/api/export/build")]
    original_cards = api_export._cards_of
    original_verify = api_export._verify
    api_export._cards_of = lambda req: [card(210100040)]
    api_export._verify = lambda *a, **kw: [{
        "gate": "G5", "code": "G5_TEST_ERROR", "level": "ERROR", "message": "测试拦截"}]
    try:
        res = handler(request("POST", "/api/export/build", name="status",
                              out_dir=str(TMP / "api-build"), gate5=False))
    finally:
        api_export._cards_of = original_cards
        api_export._verify = original_verify
    assert res["ok"] is False, res


def test_api_install_gate() -> None:
    routes = api_routes()
    handler = routes[("POST", "/api/export/install")]
    original = api_export._verify
    api_export._verify = lambda *a, **kw: [{
        "gate": "G5", "code": "G5_TEST_ERROR", "level": "ERROR", "message": "测试拦截"}]
    try:
        try:
            handler(request("POST", "/api/export/install", pack_dir=str(TMP), dry_run=False))
        except errors.ValidationError as e:
            assert e.detail["issues"][0]["code"] == "G5_TEST_ERROR"
        else:
            raise AssertionError("带 G5 ERROR 的包没有被安装接口拦截")
    finally:
        api_export._verify = original


def test_api_package_layout() -> None:
    routes = api_routes()
    handler = routes[("GET", "/api/export/packages")]
    exports = TMP / "exports"
    pack = exports / "demo"
    c = card(210100050, "effect", lua="-- test\n")
    res = expansions.build([c], pack, name="demo", copy_pics=False)
    exp = Path(res["expansions_dir"])
    (exp / "pics").mkdir(exist_ok=True)
    (exp / "pics" / f"{c.id}.jpg").write_bytes(b"\xff\xd8test")
    (exp / "strings.conf").write_text("!setname 0x1 测试\n", encoding="utf-8")
    original = api_export.paths.EXPORT_DIR
    api_export.paths.EXPORT_DIR = exports
    try:
        listed = handler(request("GET", "/api/export/packages"))
    finally:
        api_export.paths.EXPORT_DIR = original
    row = next(p for p in listed["packages"] if p["name"] == "demo")
    assert row["cdb"] and row["n_scripts"] == 1 and row["n_pics"] == 1, row
    assert row["strings_conf"] is True, row


def test_image_conversion_failures() -> None:
    c = card(210100060)
    bad = TMP / f"{c.id}.png"
    bad.write_bytes(b"not an image")
    edo_pack = TMP / "bad-edo"
    edo = expansions.build([c], edo_pack, name="bad", pic_dir=TMP)
    edo_jpg = Path(edo["expansions_dir"]) / "pics" / f"{c.id}.jpg"
    assert not edo_jpg.exists(), "EDOPro 转换失败后留下了假 JPG"
    assert any(i["code"] == "G5_PIC_COPY" for i in edo["issues"]), edo["issues"]
    ok, detail = expansions.pic_size_ok(bad)
    assert not ok and "JPEG" in str(detail), (ok, detail)

    original = mdpro3.detect
    mdpro3.detect = lambda *a, **kw: []
    try:
        md = mdpro3.build([c], TMP / "bad-image.ypk", render_pics=False,
                          pic_source={c.id: bad})
    finally:
        mdpro3.detect = original
    assert md["ok"] is False and any(i["code"] == "MD_PIC_CONVERT" for i in md["issues"]), md
    with zipfile.ZipFile(md["path"]) as z:
        assert f"pics/{c.id}.jpg" not in z.namelist(), z.namelist()


class OfflineClient:
    def alive(self):
        return False

    def models(self):
        raise AssertionError("离线 dry-run 不应读取在线模型")

    def object_info(self):
        raise AssertionError("离线 dry-run 不应读取在线节点")


def test_offline_dry_run() -> None:
    req = ArtRequest(card_id=210100070, profile="krea2", seed=7,
                     subject="银白龙在石塔上展开双翼")
    spec = card(210100070, "effect")
    res = art_run.generate(req, spec, client=OfflineClient(), dry_run=True)
    assert res.ok and res.workflow, res.error
    assert req.subject in res.meta["positive"], res.meta
    assert any("离线" in str(x) for x in res.meta["notes"]), res.meta["notes"]
    layered = art_run.generate_layers(req, spec, client=OfflineClient(), dry_run=True)
    assert layered.ok and layered.meta["mode"] == "layers", layered.error
    real = art_run.generate(req, spec, client=OfflineClient(), dry_run=False)
    assert not real.ok, "非 dry-run 在离线时不应伪装成功"


def test_art_current_fallback() -> None:
    root = TMP / "art-current-fallback"
    root.mkdir(parents=True)
    (root / "v2.png").write_bytes(b"placeholder")
    with mock.patch.object(library.P, "art_dir", return_value=root):
        rows = library.versions(210100080)
        cur = library.current(210100080)
    assert len(rows) == 1 and rows[0]["version"] == 2, rows
    assert cur and cur["version"] == 2 and cur["fallback"] is True, cur


def _png_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (20, 40, 60)).save(buf, "PNG")
    return buf.getvalue()


def test_art_bytes_prune_and_concurrency() -> None:
    from PIL import Image
    root = TMP / "art-save"
    jpeg = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 10, 10)).save(jpeg, "JPEG")
    with mock.patch.object(library.P, "art_dir", return_value=root):
        library.save(210100081, jpeg.getvalue(), {"case": "jpeg"})
        with Image.open(root / "v1.png") as im:
            assert im.format == "PNG", im.format
        for i in range(2, 6):
            library.save(210100081, _png_bytes(), {"case": i})
        (root / "v2_subject.png").write_bytes(_png_bytes())
        library.rollback(210100081, 1)
        res = library.prune(210100081, keep=3)
        assert res["removed"] == [2] and res["kept"] == [1, 3, 4, 5], res
        assert (root / "v1.png").is_file(), "清理删除了当前回退版本"
        assert not (root / "v2_subject.png").exists(), "分层孤儿文件没有被清理"

    concurrent = TMP / "art-concurrent"
    with mock.patch.object(library.P, "art_dir", return_value=concurrent):
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda i: library.save(210100082, _png_bytes(), {"i": i}), range(8)))
        got = [v["version"] for v in library.versions(210100082)]
    assert got == list(range(1, 9)), got


def test_http_method_host_and_head() -> None:
    import http.client
    app = server_app.App()
    app.get("/probe")(lambda req: {"ok": True})
    resp = app.handle(Request("POST", "/probe"))
    assert resp.status == 405 and resp.headers.get("Allow") == "GET, HEAD", resp.headers
    assert server_app._host_name("[::1]:8790") == "::1"
    assert server_app._host_name("LOCALHOST:8790") == "localhost"
    server, url, stop = server_app.serve_once(app)
    try:
        con = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        con.request("HEAD", "/probe")
        head = con.getresponse()
        assert head.status == 200 and head.read() == b"", head.status
        con.close()
    finally:
        stop()


def test_read_body_boundaries() -> None:
    for raw in ("abc", "-1"):
        try:
            read_body(io.BytesIO(b""), {"content-length": raw})
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法 Content-Length 被接受：{raw}")
    try:
        read_body(io.BytesIO(b"{}"), {"content-length": "3"})
    except ValueError as e:
        assert "提前结束" in str(e), e
    else:
        raise AssertionError("截断请求体被接受")
    assert read_body(io.BytesIO(b"{}"), {"content-length": "2"}) == b"{}"


def test_update_version_order() -> None:
    assert update._vkey("2.0.0.dev1") < update._vkey("2.0.0-alpha.1")
    assert update._vkey("2.0.0-alpha.1") < update._vkey("2.0.0-beta.1")
    assert update._vkey("2.0.0-beta.1") < update._vkey("2.0.0rc1")
    assert update._vkey("2.0.0rc1") < update._vkey("2.0.0rc2") < update._vkey("2.0.0")


def test_sync_pic_converts_png() -> None:
    from PIL import Image
    spec = card(210100090)
    src = TMP / f"{spec.id}.png"
    Image.new("RGB", (4, 4), (1, 2, 3)).save(src, "PNG")
    dst = TMP / "sync-target.jpg"
    with mock.patch.object(api_render.paths, "pic_path", return_value=dst):
        assert api_render._sync_pic(spec, [str(src)]), "PNG 同步失败"
    with Image.open(dst) as im:
        assert im.format == "JPEG", im.format


def test_cdb_connection_cleanup() -> None:
    class FakeConn:
        def __init__(self, fail=False):
            self.fail = fail
            self.closed = False
            self.row_factory = None

        def execute(self, *args):
            if self.fail:
                raise sqlite3.Error("forced")
            return self

        def fetchone(self):
            return None

        def close(self):
            self.closed = True

    first = FakeConn()
    with mock.patch.object(cdb.sqlite3, "connect", return_value=first), \
            mock.patch.object(cdb, "ensure_schema", side_effect=sqlite3.Error("forced")):
        try:
            cdb.open_cdb(TMP / "open-fail.cdb")
        except sqlite3.Error:
            pass
        else:
            raise AssertionError("建表失败没有抛出")
    assert first.closed, "建表失败泄漏连接"

    path = TMP / "ro-fallback.cdb"
    path.touch()
    broken, fallback = FakeConn(fail=True), FakeConn()
    with mock.patch.object(cdb.sqlite3, "connect", side_effect=[broken, fallback]):
        got = cdb.open_cdb_ro(path)
    assert got is fallback and broken.closed, "只读 URI 回退泄漏旧连接"
    fallback.close()


def test_mdpro_bad_cdb() -> None:
    path = TMP / "not-sqlite.ypk"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("bad.cdb", b"not sqlite")
    issues = mdpro3.verify(path)
    assert any(i.code == "MD_CDB_BAD" and i.level == "ERROR" for i in issues), issues


def test_font_cache_cap() -> None:
    from cardforge.render import fonts
    old_cap = fonts._RESOLVE_CACHE_CAP
    with mock.patch.object(fonts, "_pick", return_value={"path": None}):
        try:
            fonts._RESOLVE_CACHE_CAP = 2
            fonts._resolve_cache.clear()
            for text in ("甲", "乙", "丙"):
                fonts.resolve("sc", "zh_cn", text)
            assert len(fonts._resolve_cache) <= 2, len(fonts._resolve_cache)
        finally:
            fonts._RESOLVE_CACHE_CAP = old_cap
            fonts._resolve_cache.clear()


def test_vector_preview_without_pillow() -> None:
    code = r'''
import builtins
real_import = builtins.__import__
def no_pil(name, *args, **kwargs):
    if name == "PIL" or name.startswith("PIL."):
        raise ImportError("Pillow intentionally blocked by regression test")
    return real_import(name, *args, **kwargs)
builtins.__import__ = no_pil
from cardforge.core import errors
from cardforge.core.models import CardSpec
from cardforge.render import compositor
spec = CardSpec(id=210100100, name="无 Pillow 矢量预览", text_i18n={"zh_cn": "①：测试。"})
svg = compositor.render_svg(spec)
assert "<svg" in svg and "无 Pillow 矢量预览" in svg
assert compositor.capabilities()["L1_render"] is False
try:
    compositor.render_card(spec)
except errors.EnvError:
    pass
else:
    raise AssertionError("无 Pillow 的光栅调用没有明确降级")
from cardforge.server.app import App
from cardforge.server import api_render
from cardforge.server.http import Request
api_render._view_spec = lambda req: spec
app = App()
api_render.register(app)
resp = app.handle(Request("GET", "/api/render/preview", query={"card": "1"}))
assert resp.status == 200 and resp.content_type.startswith("image/svg+xml")
assert resp.headers.get("X-CardForge-Preview") == "vector"
'''
    res = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=30)
    assert res.returncode == 0, res.stderr[-2000:]


for name, fn in (
    ("重复导出同步删除旧卡", test_reexport_sync),
    ("G5 检出清单外多余卡", test_g5_extra_card),
    ("G2 空脚本按卡种判定", test_g2_empty_script),
    ("MDPro3 撞号时返回失败", test_mdpro_collision_status),
    ("导出 API 传播 G5 失败状态", test_api_build_failure_status),
    ("安装 API 强制拦截 G5 ERROR", test_api_install_gate),
    ("已有包列表读取 expansions 布局", test_api_package_layout),
    ("图片转换失败不生成假 JPG", test_image_conversion_failures),
    ("ComfyUI 离线可预览 dry-run", test_offline_dry_run),
    ("卡图当前指针缺失时安全回退", test_art_current_fallback),
    ("卡图格式转换、当前版本清理与并发入库", test_art_bytes_prune_and_concurrency),
    ("HTTP 405、IPv6 Host 与 HEAD 语义", test_http_method_host_and_head),
    ("请求体长度与截断边界", test_read_body_boundaries),
    ("预发布版本排序", test_update_version_order),
    ("PNG 同步为真 JPEG", test_sync_pic_converts_png),
    ("cdb 失败路径关闭连接", test_cdb_connection_cleanup),
    ("MDPro3 拒绝非 SQLite 数据库", test_mdpro_bad_cdb),
    ("字体解析缓存有上限", test_font_cache_cap),
    ("无 Pillow 时 SVG 预览仍可用", test_vector_preview_without_pillow),
):
    check(name, fn)

print(f"\nPASS={len(PASS)} FAIL={len(FAIL)}")
if FAIL:
    for name, detail in FAIL:
        print(f"  {name}: {detail}")
    raise SystemExit(1)
