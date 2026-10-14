"""引擎常量表 —— ocgcore / EDOPro 的位定义单一真相源。

数值与 edo9300/ygopro-core 的 OCG_* 常量一致。
造卡数据、cdb 写入、Lua 生成、卡面渲染四方共用本表，避免各处硬编码漂移。
"""
from __future__ import annotations

# ══════════════════════════ 卡类型（type 位，可组合） ══════════════════════════
TYPE_MONSTER = 0x1
TYPE_SPELL = 0x2
TYPE_TRAP = 0x4
TYPE_NORMAL = 0x10
TYPE_EFFECT = 0x20
TYPE_FUSION = 0x40
TYPE_RITUAL = 0x80
TYPE_TRAPMONSTER = 0x100
TYPE_SPIRIT = 0x200
TYPE_UNION = 0x400
TYPE_DUAL = 0x800
TYPE_TUNER = 0x1000
TYPE_SYNCHRO = 0x2000
TYPE_TOKEN = 0x4000
TYPE_QUICKPLAY = 0x10000
TYPE_CONTINUOUS = 0x20000
TYPE_EQUIP = 0x40000
TYPE_FIELD = 0x80000
TYPE_COUNTER = 0x100000
TYPE_FLIP = 0x200000
TYPE_TOON = 0x400000
TYPE_XYZ = 0x800000
TYPE_PENDULUM = 0x1000000
TYPE_SPSUMMON = 0x2000000
TYPE_LINK = 0x4000000

# ══════════════════════════ 种族（race） ══════════════════════════
RACE_WARRIOR = 0x1
RACE_SPELLCASTER = 0x2
RACE_FAIRY = 0x4
RACE_FIEND = 0x8
RACE_ZOMBIE = 0x10
RACE_MACHINE = 0x20
RACE_AQUA = 0x40
RACE_PYRO = 0x80
RACE_ROCK = 0x100
RACE_WINGEDBEAST = 0x200
RACE_PLANT = 0x400
RACE_INSECT = 0x800
RACE_THUNDER = 0x1000
RACE_DRAGON = 0x2000
RACE_BEAST = 0x4000
RACE_BEASTWARRIOR = 0x8000
RACE_DINOSAUR = 0x10000
RACE_FISH = 0x20000
RACE_SEASERPENT = 0x40000
RACE_REPTILE = 0x80000
RACE_PSYCHIC = 0x100000
RACE_DIVINE = 0x200000
RACE_CREATORGOD = 0x400000
RACE_WYRM = 0x800000
RACE_DIVINEBEAST = 0x1000000
RACE_CYBERSE = 0x2000000
RACE_ILLUSION = 0x4000000
RACE_DRAGON_ROAD = 0x8000000  # Rush Duel 专用

# ══════════════════════════ 属性（attribute） ══════════════════════════
ATTRIBUTE_EARTH = 0x01
ATTRIBUTE_WATER = 0x02
ATTRIBUTE_FIRE = 0x04
ATTRIBUTE_WIND = 0x08
ATTRIBUTE_LIGHT = 0x10
ATTRIBUTE_DARK = 0x20
ATTRIBUTE_DIVINE = 0x40

# ══════════════════════════ 连接标记（Link 怪兽的 def 字段） ══════════════════════════
LINK_BOTTOM_LEFT = 0x001
LINK_BOTTOM = 0x002
LINK_BOTTOM_RIGHT = 0x004
LINK_LEFT = 0x008
LINK_RIGHT = 0x020
LINK_TOP_LEFT = 0x040
LINK_TOP = 0x080
LINK_TOP_RIGHT = 0x100

# ══════════════════════════ 中文界面字 ↔ 位值（数据表用中文，引擎用位值） ══════════════════════════
RACE_MAP: dict[str, int] = {
    "战士族": RACE_WARRIOR, "魔法师族": RACE_SPELLCASTER, "天使族": RACE_FAIRY,
    "恶魔族": RACE_FIEND, "不死族": RACE_ZOMBIE, "机械族": RACE_MACHINE,
    "水族": RACE_AQUA, "炎族": RACE_PYRO, "岩石族": RACE_ROCK,
    "鸟兽族": RACE_WINGEDBEAST, "植物族": RACE_PLANT, "昆虫族": RACE_INSECT,
    "雷族": RACE_THUNDER, "龙族": RACE_DRAGON, "兽族": RACE_BEAST,
    "兽战士族": RACE_BEASTWARRIOR, "恐龙族": RACE_DINOSAUR, "鱼族": RACE_FISH,
    "海龙族": RACE_SEASERPENT, "爬虫类族": RACE_REPTILE, "念动力族": RACE_PSYCHIC,
    "幻神兽族": RACE_DIVINEBEAST, "电子界族": RACE_CYBERSE, "幻想魔族": RACE_ILLUSION,
    "创造神族": RACE_CREATORGOD, "幻龙族": RACE_WYRM,
}
RACE_NAME: dict[int, str] = {v: k for k, v in RACE_MAP.items()}

ATTRIBUTE_MAP: dict[str, int] = {
    "地": ATTRIBUTE_EARTH, "水": ATTRIBUTE_WATER, "炎": ATTRIBUTE_FIRE,
    "风": ATTRIBUTE_WIND, "光": ATTRIBUTE_LIGHT, "暗": ATTRIBUTE_DARK, "神": ATTRIBUTE_DIVINE,
}
ATTRIBUTE_NAME: dict[int, str] = {v: k for k, v in ATTRIBUTE_MAP.items()}

LINK_MARKER_MAP: dict[str, int] = {
    "左下": LINK_BOTTOM_LEFT, "下": LINK_BOTTOM, "右下": LINK_BOTTOM_RIGHT,
    "左": LINK_LEFT, "右": LINK_RIGHT,
    "左上": LINK_TOP_LEFT, "上": LINK_TOP, "右上": LINK_TOP_RIGHT,
}
LINK_MARKER_NAME: dict[int, str] = {v: k for k, v in LINK_MARKER_MAP.items()}
# 引擎/资源文件用的英文键（连接箭头素材名）
LINK_MARKER_SLUG: dict[str, str] = {
    "左下": "left-down", "下": "down", "右下": "right-down",
    "左": "left", "右": "right",
    "左上": "left-up", "上": "up", "右上": "right-up",
}

# 星级图标位置（引擎按顺时针，渲染器按方位）
LINK_MARKER_ORDER = ["左上", "上", "右上", "左", "右", "左下", "下", "右下"]


def link_markers_bits(markers) -> int:
    """['左下','右'] -> 位掩码。未知键忽略。"""
    bits = 0
    for m in markers or []:
        bits |= LINK_MARKER_MAP.get(str(m).strip(), 0)
    return bits


def link_markers_from_bits(bits: int) -> list[str]:
    return [name for name, bit in LINK_MARKER_MAP.items() if bits & bit]


def link_rating_from_bits(bits: int) -> int:
    """连接数 = 箭头数量（引擎里 link rating 存于 level 字段）。"""
    return bin(bits).count("1")
