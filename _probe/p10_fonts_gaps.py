# -*- coding: utf-8 -*-
"""探针 10：字体字形覆盖（「?」「-」缺字导致 fallback）+ 缺失能力盘点。"""
import os, sys, glob
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
from fontTools.ttLib import TTFont
import numpy as np
from PIL import Image, ImageDraw
from forge import template as T
from forge import compositor as C

print("=" * 104)
print("① 卡面字体的字形覆盖")
print("=" * 104)
FONTS = {
    "sc (ygo-sc)": "ygo-sc.woff2",
    "atk_def (ygo-atk-def)": "ygo-atk-def.woff2",
    "en (ygo-en)": "ygo-en.woff2",
    "en_name (ygo-en-name)": "ygo-en-name.woff2",
    "en_race (ygo-en-race)": "ygo-en-race.woff2",
    "link (ygo-link)": "ygo-link.woff2",
}
PROBE = {
    "ASCII 0123456789": "0123456789",
    "ATK/DEF 标点": "ATK/DEF-?",
    "繁中常用": "攻擊守備魔法陷阱怪獸龍族",
    "日文假名": "モンスターのこうげき",
    "日文汉字": "攻撃守備魔法罠融合",
    "韩文": "공격수비마법",
    "简中常用": "攻击守备龙兽组",
}
for label, fn in FONTS.items():
    p = T.asset_path(fn)
    ttf = os.path.splitext(p)[0] + ".ttf"
    if not os.path.isfile(ttf):
        print(f"  {label:<24} 无 .ttf"); continue
    f = TTFont(ttf, fontNumber=0, lazy=True)
    cmap = f.getBestCmap()
    n = len(cmap)
    miss = []
    for pl, chars in PROBE.items():
        m = [c for c in chars if ord(c) not in cmap]
        if m:
            miss.append(f"{pl} 缺{''.join(m)}")
    print(f"  {label:<24} 字形 {n:>6}  upem={f['head'].unitsPerEm}")
    print(f"      {'; '.join(miss) if miss else '全部探针字符齐备'}")
    f.close()

print()
print("  外部字体（默认不参与渲染）:")
for k, fn in T.EXTERNAL_FONTS.items():
    p = T.external_font_path(k)
    if not p:
        print(f"    {k:<10} 缺失"); continue
    f = TTFont(p, fontNumber=0, lazy=True)
    cmap = f.getBestCmap()
    miss = []
    for pl, chars in PROBE.items():
        m = [c for c in chars if ord(c) not in cmap]
        if m:
            miss.append(f"{pl} 缺{''.join(m)}")
    print(f"    {k:<10} {fn:<28} 字形 {len(cmap):>6}  {'; '.join(miss) if miss else '齐备'}")

print()
print("=" * 104)
print("② 「ATK/? 」实际渲染用的字体")
print("=" * 104)
f = C.font("num", 52)
print(f"  C.font('num',52) -> {getattr(f,'path','?')}  .size={f.size}")
d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
for ch in ("/", "?", "-", "A", "0", "L", "I", "N", "K"):
    print(f"    textlength('{ch}') = {d.textlength(ch, font=f):6.2f}   "
          f"bbox={d.textbbox((0,0), ch, font=f)}")
lf = C.font("link", 36)
print(f"  C.font('link',36) -> {getattr(lf,'path','?')}  .size={lf.size}")
for ch in ("L", "I", "N", "K", "-", "0", "8"):
    print(f"    textlength('{ch}') = {d.textlength(ch, font=lf):6.2f}")

print()
print("=" * 104)
print("③ 缺失能力盘点：卡框/素材层面")
print("=" * 104)
print("  FRAME_IMG 现有键：", sorted(T.FRAME_IMG.keys()))
print("  FRAME_IMG_PENDULUM：", sorted(T.FRAME_IMG_PENDULUM.keys()))
print("  FRAMES（程序画配色）：", sorted(C.FRAMES.keys()))
need = {
    "出框/全画幅 (Full Art / オーバーフレーム)": "无 art_overflow / full_art / 出血插画 spec 字段；_official_base 恒为矩形粘贴",
    "衍生物 Token": "frame/token.png 有素材，FRAME_IMG 有 'token'；但 _FRAME_TYPETEXT 无 'token' → 类型行退化为「效果」",
    "技能卡 (Skill Card)": "无素材、无 frame 键",
    "高速咒文 (Speed Spell)": "无素材、无 frame 键",
    "暗黑同调 (Dark Synchro)": "无素材、无 frame 键（负等级也不支持）",
    "二重怪兽 (Gemini)": "type_flags 白名单只有 调整/速攻/永续/装备/场地/反击/仪式 → 无「二重」",
    "灵魂怪兽 (Spirit)": "同上，无「灵魂」",
    "同盟怪兽 (Union)": "同上，无「同盟」",
    "卡通怪兽 (Toon)": "同上，无「卡通」",
    "反转怪兽 (Flip)": "同上，无「反转」",
    "特殊召唤怪兽 (Nomi)": "同上，无「特殊召唤」",
    "仪式/融合/同调/超量 的「效果」与否不可控": "_type_line 对 ritual..link 无条件追加「效果」→ 无法表达纯仪式/纯融合",
    "灵摆 + 融合/同调/超量 的类型行": "frame='pendulum' 时 tags 恒为 ['灵摆','效果'] → 丢失融合/同调/超量标签",
    "多语言卡面 (日/英/韩)": "FONT_FILES 只有 sc/atk_def/en/en_name/en_race/link；无日文/韩文卡面正文与卡名字体",
    "日文卡名艺术字": "ygo-sc 是简中字；spec 里写日文只能靠 sc 字体里碰巧有的汉字/假名",
    "英文类型行/英文卡名": "只有字体文件，compositor._type_line 输出恒为中文；无英文版类型行渲染路径",
    "卡号 (card_code)": "GEO 有 card_code=(727,870) 但 render_card 从未绘制",
    "防伪标贴位以外的激光标": "只有 sticker 一个位置",
    "20 周年标之外的其他纪念标": "STAMP 只有 20th",
}
for k, v in need.items():
    print(f"  ✗ {k}\n      {v}")

print()
print("=" * 104)
print("④ spec 字段：compositor 真正读取了哪些")
print("=" * 104)
import inspect, re
src = inspect.getsource(C)
used = sorted(set(re.findall(r'spec\.get\(\s*["\']([\w]+)["\']', src)) |
              set(re.findall(r'spec\[\s*["\']([\w]+)["\']\s*\]', src)))
print(f"  compositor 读取的 spec 键 ({len(used)})：{used}")
# forge.py normalize_spec 产出
import forge.forge as FG
ns = inspect.getsource(FG.normalize_spec)
prod = sorted(set(re.findall(r's\[\s*["\']([\w]+)["\']\s*\]', ns)))
print(f"  normalize_spec 写入/清洗的键 ({len(prod)})：{prod}")
only_in_norm = [k for k in prod if k not in used]
print(f"  只在 normalize_spec 里、compositor 不读的键：{only_in_norm}")
only_in_comp = [k for k in used if k not in prod]
print(f"  只在 compositor 里读、项目 21 张卡 JSON 没有的键：{only_in_comp}")
