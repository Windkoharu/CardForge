# 模板 → 表单 → 真机出图：验证「点一套正统母题就能出图」这条链是通的。
# 只落盘不入库（store=False），不动用户的卡图资产库。
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cardforge.art import run as RUN
from cardforge.art import templates as TP
from cardforge.core.models import ArtRequest, CardSpec

spec = CardSpec(id=210000021, name="圣痕的龙骑士 露米艾尔", frame="fusion",
                race="战士族", attribute="炎", level=8, atk=3000, dfd=2500,
                archetype="圣痕")
form = TP.as_form(TP.BY_KEY["dragon"], bilingual=True, name=spec.display_name)
print("套用模板:", form["zh"], "| 口径: 中文原话直送")
req = ArtRequest(subject=form["subject"], style=form["style"],
                 background=form["background"], preset=form["preset"],
                 profile="krea2", seed=20261027, card_id=0,
                 width=832, height=832, steps=8, cfg=1.0)
t = time.time()
res = RUN.generate(req, spec, host="http://127.0.0.1:8188", store=False)
print("ok =", res.ok, "| 用时", round(time.time() - t, 1), "s")
if not res.ok:
    print("error:", res.error, "|", res.hint)
    sys.exit(1)
for p in res.images:
    print("IMAGE", p)
m = res.meta or {}
Path("_probe/template_render_meta.json").write_text(json.dumps(
    {k: m.get(k) for k in ("positive", "negative", "prompt_mode", "untranslated",
                           "user_input", "model", "clip", "seed", "width", "height",
                           "steps", "cfg", "sampler", "scheduler", "prompt_id")},
    ensure_ascii=False, indent=2), encoding="utf-8")
print("prompt_mode =", m.get("prompt_mode"), "| 模板原话进了提示词:",
      form["subject"] in m.get("positive", ""))
