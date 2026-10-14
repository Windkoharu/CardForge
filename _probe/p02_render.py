# -*- coding: utf-8 -*-
"""探针 2：渲染 7 种卡种 + 边界用例，存 _probe/。（用 cast 助手绕开 def 关键字）"""
import os, sys, json, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image, ImageDraw
from forge import compositor as C
from forge import template as T

OUT = r"D:\游戏王DIY设计\_probe"
os.makedirs(OUT, exist_ok=True)
CAN = C.CANVAS

L = lambda **kw: kw  # noqa


def S(name, frame, **kw):
    d = {"name": name, "frame": frame}
    d.update(kw)
    return d


def art_demo(w=1400, h=1400, seed=1):
    xx, yy = np.meshgrid(np.arange(w), np.arange(h))
    a = np.zeros((h, w, 3), np.uint8)
    a[..., 0] = (xx / w * 255).astype(np.uint8)
    a[..., 1] = (yy / h * 255).astype(np.uint8)
    a[..., 2] = (np.sin(xx / 40.0) * 60 + 128).astype(np.uint8)
    a[:, :40] = (255, 0, 0)
    a[:, -40:] = (0, 0, 255)
    a[:40, :] = (255, 255, 0)
    a[-40:, :] = (0, 255, 0)
    im = Image.fromarray(a)
    d = ImageDraw.Draw(im)
    d.line([(0, 0), (w, h)], fill=(255, 255, 255), width=6)
    d.line([(w, 0), (0, h)], fill=(0, 0, 0), width=6)
    for i in range(1, 8):
        d.line([(0, h * i / 8), (w, h * i / 8)], fill=(255, 255, 255), width=2)
        d.line([(w * i / 8, 0), (w * i / 8, h)], fill=(255, 255, 255), width=2)
    return im


LOREM = ("①：这张卡召唤成功时才能发动。从卡组把1张「测试」卡加入手卡。"
         "②：1回合1次，以自己场上1只怪兽为对象才能发动。那只怪兽的攻击力直到回合结束时上升1000。"
         "这个效果在对方回合也能发动。③：这张卡被送去墓地的场合才能发动。自己从卡组抽1张。")

CASES = [
    ("c01_normal", S("测试 通常怪兽", "normal", level=3, attribute="光",
                     race="魔法师族", atk=1200, **{"def": 1000},
                     text="在星海尽头练习演奏的见习乐师。她始终相信，总有一天自己的旋律能传遍整片星空。"), True),
    ("c02_effect", S("测试 效果怪兽 长名测试测试测试", "effect", level=4,
                     attribute="炎", race="战士族", atk=1700, **{"def": 1000}, text=LOREM), True),
    ("c03_pendulum", S("测试 灵摆怪兽", "pendulum", pendulum_base="effect",
                       level=7, attribute="水", race="魔法师族", atk=2200, **{"def": 1800},
                       pendulum=3,
                       pendulum_text="①：1回合1次，以自己场上1只怪兽为对象才能发动。那只怪兽的等级上升1。",
                       text="①：这张卡召唤成功时才能发动。从卡组把1张「测试」卡加入手卡。"), True),
    ("c04_link", S("测试 连接怪兽", "link", level=3, attribute="暗",
                   race="电子界族", atk=2300, link_markers=["上", "左下", "右下"],
                   text=LOREM), True),
    ("c05_spell", S("测试 速攻魔法", "spell", type_flags=["速攻"], text=LOREM), True),
    ("c06_trap", S("测试 反击陷阱", "trap", type_flags=["反击"], text=LOREM), True),
    ("c07_xyz", S("测试 超量怪兽", "xyz", level=4, attribute="暗",
                  race="龙族", atk=2500, **{"def": 2000}, text=LOREM), True),
    ("c08_synchro", S("测试 同调调整", "synchro", level=8, attribute="光",
                      race="天使族", atk=2800, **{"def": 2400}, type_flags=["调整"], text=LOREM), True),
    ("c09_fusion", S("测试 融合怪兽", "fusion", level=6, attribute="光",
                     race="天使族", atk=2200, **{"def": 1800}, text=LOREM), True),
    ("c10_ritual", S("测试 仪式怪兽", "ritual", level=7, attribute="水",
                     race="战士族", atk=2600, **{"def": 2000}, text=LOREM), True),
    ("x01_noart_effect", S("无插画 效果怪兽", "effect", level=4, attribute="光",
                           race="战士族", atk=1800, **{"def": 1200}, text=LOREM), False),
    ("x02_noart_pend", S("无插画 灵摆", "pendulum", pendulum_base="effect",
                         level=4, attribute="光", race="战士族", atk=1800, **{"def": 1200},
                         pendulum=5, pendulum_text="①：无插画灵摆效果测试。",
                         text="①：无插画怪兽效果测试。"), False),
    ("x03_noart_link", S("无插画 连接", "link", level=2, attribute="暗",
                         race="电子界族", atk=1500, link_markers=["上", "下"],
                         text="①：无插画连接测试。"), False),
    ("x04_tallart", S("超长插画 1:4", "effect", level=4, attribute="光",
                      race="战士族", atk=1800, **{"def": 1200}, text=LOREM), "tall"),
    ("x05_wideart", S("超宽插画 4:1", "effect", level=4, attribute="光",
                      race="战士族", atk=1800, **{"def": 1200}, text=LOREM), "wide"),
    ("x06_longtext", S("超长卡文溢出测试", "effect", level=4, attribute="光",
                       race="战士族", atk=1800, **{"def": 1200}, text=LOREM * 4), True),
    ("x07_jpmix", S("星奏の見習いソル／テスト", "effect", level=3, attribute="光",
                    race="魔法师族", atk=1200, **{"def": 1000},
                    text="①：このカードが召喚に成功した時に発動できる。"
                         "デッキから「星奏」モンスター1体を手札に加える。"
                         "②：1ターンに1度、自分フィールドのモンスター1体を対象として発動できる。"), True),
    ("x08_question", S("问号数值测试", "effect", level=4, attribute="光",
                       race="战士族", atk=-1, **{"def": -1}, text="①：ATK/DEF 都是问号的卡。"), True),
    ("x09_numeric_edge", S("零攻零守", "effect", level=1, attribute="暗",
                           race="恶魔族", atk=0, **{"def": 0}, text="①：0/0 数值测试。"), True),
    ("x10_13star", S("13星压力测试", "xyz", level=13, attribute="神",
                     race="幻神兽族", atk=5000, **{"def": 5000}, text="①：13 个阶级星测试。"), True),
    ("x11_eightlink", S("LINK-8 全箭头", "link", level=8, attribute="光",
                        race="电子界族", atk=5000,
                        link_markers=["上", "下", "左", "右", "左上", "右上", "左下", "右下"],
                        text="①：8 个箭头全亮测试。"), True),
    ("x12_longname", S("超长卡名测试" * 6, "effect", level=4, attribute="光",
                       race="战士族", atk=1800, **{"def": 1200}, text=LOREM), True),
    ("x13_noattr", S("无属性字段", "effect", level=4, attribute="",
                     race="", atk=1800, **{"def": 1200}, text=LOREM), True),
    ("x14_token", S("衍生物 Token", "token", level=1, attribute="光",
                    race="天使族", atk=0, **{"def": 0}, text="衍生物测试。"), True),
    ("x15_procedural", S("程序画基座", "effect", level=4, attribute="炎",
                         race="战士族", atk=1700, **{"def": 1000}, text=LOREM), True),
]

art_std = art_demo(1400, 1400, 1)
art_tall = art_demo(600, 2400, 2)
art_wide = art_demo(2400, 600, 3)

manifest = {}
for name, spec, use in CASES:
    a = {True: art_std, False: None, "tall": art_tall, "wide": art_wide}[use]
    mode = "procedural" if name == "x15_procedural" else "official"
    t0 = time.time()
    try:
        img = C.render_card(spec, a, CAN, frame_mode=mode)
        dt = time.time() - t0
        p = os.path.join(OUT, name + ".png")
        img.convert("RGB").save(p)
        manifest[name] = dict(ms=round(dt * 1000, 1), path=p, ok=True)
        print(f"{name:<20} {dt*1000:8.1f} ms  {img.size}")
    except Exception as e:
        import traceback
        print(f"{name:<20} FAIL {type(e).__name__}: {e}")
        traceback.print_exc()
        manifest[name] = dict(ok=False, err=str(e))

json.dump(manifest, open(os.path.join(OUT, "_manifest_render.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("done")
