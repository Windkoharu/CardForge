"""本轮缺陷修复的离线回归测试。

用法：python tools/selfcheck_regressions.py
所有产物只写 workspace/.cache/selfcheck-regressions/，不启动本地服务。
"""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import sys
import traceback
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from cardforge.art import run as art_run
from cardforge.core import errors
from cardforge.core.models import ArtRequest, CardSpec
from cardforge.export import expansions, mdpro3
from cardforge.pipeline import gates
from cardforge.pool import cdb
from cardforge.server import api_export
from cardforge.server.http import Request

TMP = ROOT / "workspace" / ".cache" / "selfcheck-regressions"
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True)

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
):
    check(name, fn)

print(f"\nPASS={len(PASS)} FAIL={len(FAIL)}")
if FAIL:
    for name, detail in FAIL:
        print(f"  {name}: {detail}")
    raise SystemExit(1)
