# 真机保真验证：中文原话直送后，画面到底听不听用户的话。
# 只落盘、不入库（store=False），不动用户的卡图资产库。
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cardforge.art import run as RUN
from cardforge.core.models import ArtRequest, CardSpec

SUB = ("一位少女骑士，银白色长直发，深红色眼睛，身穿白银铠甲，右手持骑枪，"
       "背后展开一对发光的白色羽翼，半身特写，柔和的晨光")
STYLE = "赛璐璐上色，画面干净"

spec = CardSpec(id=210000021, name="圣痕的龙骑士 露米艾尔", frame="fusion",
                race="战士族", attribute="炎", level=8, atk=3000, dfd=2500,
                archetype="圣痕")
req = ArtRequest(subject=SUB, style=STYLE, seed=20261026, profile="krea2",
                 card_id=0, width=832, height=832, steps=8, cfg=1.0)

t = time.time()
res = RUN.generate(req, spec, host="http://127.0.0.1:8188", store=False)
print("ok =", res.ok, "| 用时", round(time.time() - t, 1), "s")
if not res.ok:
    print("error:", res.error, "|", res.hint)
    sys.exit(1)
for p in res.images:
    print("IMAGE", p)
meta = res.meta or {}
Path("_probe/render_fidelity_meta.json").write_text(
    json.dumps({k: meta.get(k) for k in ("positive", "negative", "seed", "model",
                                         "clip", "width", "height", "steps", "cfg",
                                         "sampler", "scheduler", "prompt_mode",
                                         "untranslated", "user_input", "prompt_id",
                                         "workflow_fingerprint")},
               ensure_ascii=False, indent=2), encoding="utf-8")
print("prompt_mode =", meta.get("prompt_mode"), "| untranslated =", meta.get("untranslated"))
print("META -> _probe/render_fidelity_meta.json")
