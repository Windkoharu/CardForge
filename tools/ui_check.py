# -*- coding: utf-8 -*-
"""Real-browser UI regression checks; starts and stops an isolated local service."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_WORKSPACE = ROOT / "workspace" / ".cache" / "ui-workspace"
shutil.rmtree(TEST_WORKSPACE, ignore_errors=True)
os.environ["CARDFORGE_WORKSPACE"] = str(TEST_WORKSPACE)
sys.path.insert(0, str(ROOT))
from cardforge.core import paths as core_paths  # noqa: E402
from cardforge.server.app import create_app, serve_once  # noqa: E402

if core_paths.WORKSPACE != TEST_WORKSPACE:
    raise RuntimeError("页面测试必须只在隔离工作区运行，已终止以保护真实卡片")


def capture_screenshots(edge: Path, url: str, out: Path) -> int:
    """用独立浏览器进程截图；示例卡只写入隔离的测试工作区。"""
    fixture = {
        "id": 0, "name": "星奏的见习指挥", "frame": "effect", "attribute": "光",
        "race": "魔法师族", "level": 4, "atk": 1600, "dfd": 1200,
        "setcode": "0x0", "archetype": "星奏", "name_i18n": {},
        "text_i18n": {}, "pendulum_text_i18n": {}, "flavor": "", "tags": [],
        "link_markers": [], "pendulum_effect_indices": [],
        "summon": {"materials": [], "methods": [], "limit": "", "cannot_be_material": []},
        "effects": [{"kind": "draw", "trigger": "IGNITION", "limit": "once_per_turn",
                     "params": {"count": 1},
                     "target": {"filter_kind": "any", "count": 1, "controller": "self"},
                     "cost": {"kind": "none"}, "source": "manual"}],
        "render": {"rarity": "common", "lang_name": "zh_cn", "lang_text": "zh_cn",
                   "lang_flavor": "zh_cn", "fullart": {"mode": "none"},
                   "art_fit": "cover", "art_scale": 1, "art_offset_y": 0},
    }
    request = urllib.request.Request(
        url + "/api/cards", data=json.dumps(fixture).encode("utf-8"),
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        card_id = json.load(response)["spec"]["id"]
    plan = [
        ("spec-desktop", "spec", "1680,960"),
        ("text-desktop", "text", "1680,960"),
        ("art-desktop", "art", "1680,960"),
        ("pack-desktop", "pack", "1680,960"),
        ("spec-narrow", "spec", "390,844"),
    ]
    for name, stage, size in plan:
        target = out / f"{name}.png"
        profile = out / f"profile-{name}"
        shutil.rmtree(profile, ignore_errors=True)
        target.unlink(missing_ok=True)
        args = [
            str(edge), "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--disable-extensions", f"--window-size={size}",
            "--virtual-time-budget=12000", f"--user-data-dir={profile}",
            f"--screenshot={target}", f"{url}/?stage={stage}&card={card_id}",
        ]
        try:
            result = subprocess.run(args, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=90)
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        if result.returncode or not target.is_file():
            print(f"FAIL 截图 {name}: {result.stderr[-1200:]}")
            return 1
        print(f"SCREENSHOT {name} {target.stat().st_size} bytes")
    return 0


def main() -> int:
    edge = next((Path(p) for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/microsoft-edge",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ) if Path(p).exists()), None)
    if not edge:
        print("FAIL: 没找到 Edge / Chromium，无法跑真实页面验收")
        return 1
    node = shutil.which("node") or shutil.which("node.cmd")
    if not node:
        print("FAIL: 没找到 Node.js，无法跑真实页面验收")
        return 1
    out = ROOT / "workspace" / ".cache" / "ui-check"
    out.mkdir(parents=True, exist_ok=True)
    server, url, stop = serve_once(create_app(), port=8790)
    try:
        deadline = time.time() + 10
        while True:
            try:
                with urllib.request.urlopen(url + "/", timeout=2) as response:
                    response.read(64)
                break
            except Exception:
                if time.time() >= deadline:
                    raise
                time.sleep(0.1)
        result = subprocess.run([
            node, str(ROOT / "tools" / "ui_regression.mjs"),
            "--url", url, "--edge", str(edge), "--out", str(out),
        ], cwd=ROOT, timeout=240)
        if result.returncode:
            return result.returncode
        return capture_screenshots(edge, url, out)
    finally:
        stop()
        print("TEMP_SERVER_STOPPED")


if __name__ == "__main__":
    raise SystemExit(main())
