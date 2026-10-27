"""卡种 / 罕贵 / 语言 三大枚举 —— 每种都自带多语言标签。

设计要点：
  * ``key`` 是内部稳定标识（写进 JSON、永不改），``label`` 是展示名（可改）。
  * 每一档都带 zh_cn / ja / en 三语标签，供卡面渲染与多语言卡文共用。
  * 新增卡种或罕贵**只改数据不改代码**。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ══════════════════════════════════════════════════════════════════════
#  卡种（frame）—— 决定卡框、卡组归属、类型行文本
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FrameType:
    key: str
    zh_cn: str
    ja: str
    en: str
    # 类型行在卡面上的固定后缀（官方格式）
    type_suffix_zh: str = ""
    type_suffix_ja: str = ""
    type_suffix_en: str = ""
    extra_deck: bool = False        # 是否进额外卡组
    is_monster: bool = True
    has_level: bool = True          # 显示等级/阶级星
    level_is_rank: bool = False     # 超量：显示阶级（黑星、左起）
    has_atk: bool = True
    has_def: bool = True            # 连接怪兽无守备力
    base: str = "effect"            # 对应 assets/frame/<base>.png
    default_attribute: str = "暗"
    #: 卡图窗宽高比。**实测值**：标准框 1051×1051 → 1.0004（正方形），
    #: 灵摆合并窗 1205×1548 → 0.7788。曾经整表写成 0.68567（那是**整卡**的宽高比
    #: 813/1185），导致按竖构图出图、再被 cover 裁掉上下约 31%。见 geometry 实测。
    art_ratio: float = 1.0004

    @property
    def label(self) -> dict[str, str]:
        return {"zh_cn": self.zh_cn, "ja": self.ja, "en": self.en}


#: 灵摆合并窗实测比例（1394×2031 素材上 1205×1548）
PENDULUM_ART_RATIO = 0.7788

FRAMES: dict[str, FrameType] = {
    f.key: f for f in [
        # ⚠ base 必须显式给 "normal"：默认值是 "effect"，漏了会导致通常怪兽
        #   用橙色效果框渲染、type 位算成 0x21（应为 0x11）。这是实测抓到的 bug。
        FrameType("normal", "通常", "通常", "Normal",
                  "通常", "通常", "Normal", base="normal"),
        FrameType("effect", "效果", "効果", "Effect",
                  "效果", "効果", "Effect"),
        FrameType("ritual", "仪式", "儀式", "Ritual",
                  "仪式", "儀式", "Ritual", base="ritual"),
        FrameType("fusion", "融合", "融合", "Fusion",
                  "融合", "融合", "Fusion", extra_deck=True, base="fusion"),
        FrameType("synchro", "同步", "シンクロ", "Synchro",
                  "同步", "シンクロ", "Synchro", extra_deck=True, base="synchro"),
        FrameType("xyz", "超量", "エクシーズ", "Xyz",
                  "超量", "エクシーズ", "Xyz", extra_deck=True,
                  level_is_rank=True, base="xyz"),
        FrameType("link", "连接", "リンク", "Link",
                  "连接", "リンク", "Link", extra_deck=True,
                  has_level=False, has_def=False, base="link"),
        FrameType("pendulum", "灵摆", "ペンデュラム", "Pendulum",
                  "灵摆", "ペンデュラム", "Pendulum", base="effect",
                  art_ratio=PENDULUM_ART_RATIO),
        FrameType("normal_pendulum", "通常灵摆", "通常ペンデュラム", "Normal Pendulum",
                  "灵摆／通常", "ペンデュラム／通常", "Pendulum / Normal", base="normal",
                  art_ratio=PENDULUM_ART_RATIO),
        FrameType("ritual_pendulum", "仪式灵摆", "儀式ペンデュラム", "Ritual Pendulum",
                  "灵摆／仪式", "ペンデュラム／儀式", "Pendulum / Ritual", base="ritual",
                  art_ratio=PENDULUM_ART_RATIO),
        FrameType("fusion_pendulum", "融合灵摆", "融合ペンデュラム", "Fusion Pendulum",
                  "灵摆／融合", "ペンデュラム／融合", "Pendulum / Fusion",
                  extra_deck=True, base="fusion", art_ratio=PENDULUM_ART_RATIO),
        FrameType("synchro_pendulum", "同步灵摆", "シンクロペンデュラム", "Synchro Pendulum",
                  "灵摆／同步", "ペンデュラム／シンクロ", "Pendulum / Synchro",
                  extra_deck=True, base="synchro", art_ratio=PENDULUM_ART_RATIO),
        FrameType("xyz_pendulum", "超量灵摆", "エクシーズペンデュラム", "Xyz Pendulum",
                  "灵摆／超量", "ペンデュラム／エクシーズ", "Pendulum / Xyz",
                  extra_deck=True, level_is_rank=True, base="xyz",
                  art_ratio=PENDULUM_ART_RATIO),
        FrameType("spell", "魔法", "魔法", "Spell",
                  "魔法", "魔法", "Spell", is_monster=False,
                  has_level=False, has_atk=False, has_def=False, base="spell"),
        FrameType("trap", "陷阱", "罠", "Trap",
                  "陷阱", "罠", "Trap", is_monster=False,
                  has_level=False, has_atk=False, has_def=False, base="trap"),
        FrameType("token", "衍生物", "トークン", "Token",
                  "衍生物", "トークン", "Token", is_monster=True,
                  extra_deck=False, base="token", default_attribute="地"),
        FrameType("skill", "技能卡", "スキルカード", "Skill Card",
                  "技能卡", "スキルカード", "Skill Card", is_monster=False,
                  has_level=False, has_atk=False, has_def=False, base="skill"),
    ]
}
FRAME_KEYS = list(FRAMES)

# 魔法/陷阱的种类徽记（对应 assets/icon/*.png 与 type 位）
SPELL_KINDS: dict[str, dict] = {
    "normal": {"zh_cn": "通常魔法", "ja": "通常魔法", "en": "Normal Spell", "bit": 0, "icon": None},
    "ritual": {"zh_cn": "仪式魔法", "ja": "儀式魔法", "en": "Ritual Spell",
               "bit": 0x80, "icon": "ritual"},
    "quick": {"zh_cn": "速攻魔法", "ja": "速攻魔法", "en": "Quick-Play Spell",
              "bit": 0x10000, "icon": "quick"},
    "continuous": {"zh_cn": "永续魔法", "ja": "永続魔法", "en": "Continuous Spell",
                   "bit": 0x20000, "icon": "continuous"},
    "equip": {"zh_cn": "装备魔法", "ja": "装備魔法", "en": "Equip Spell",
              "bit": 0x40000, "icon": "equip"},
    "field": {"zh_cn": "场地魔法", "ja": "フィールド魔法", "en": "Field Spell",
              "bit": 0x80000, "icon": "field"},
}
TRAP_KINDS: dict[str, dict] = {
    "normal": {"zh_cn": "通常陷阱", "ja": "通常罠", "en": "Normal Trap", "bit": 0, "icon": None},
    "continuous": {"zh_cn": "永续陷阱", "ja": "永続罠", "en": "Continuous Trap",
                   "bit": 0x20000, "icon": "continuous"},
    "counter": {"zh_cn": "反击陷阱", "ja": "カウンター罠", "en": "Counter Trap",
                "bit": 0x100000, "icon": "counter"},
}

# 怪兽属性标记（决定类型行里附加的文字，如「协调」「特殊召唤」）
MONSTER_TAGS: dict[str, dict] = {
    "tuner": {"zh_cn": "协调", "ja": "チューナー", "en": "Tuner", "bit": 0x1000},
    "spirit": {"zh_cn": "灵魂", "ja": "スピリット", "en": "Spirit", "bit": 0x200},
    "union": {"zh_cn": "联合", "ja": "ユニオン", "en": "Union", "bit": 0x400},
    "gemini": {"zh_cn": "二重", "ja": "デュアル", "en": "Gemini", "bit": 0x800},
    "flip": {"zh_cn": "反转", "ja": "リバース", "en": "Flip", "bit": 0x200000},
    "toon": {"zh_cn": "卡通", "ja": "トゥーン", "en": "Toon", "bit": 0x400000},
    "special_summon": {"zh_cn": "特殊召唤", "ja": "特殊召喚", "en": "Special Summon",
                       "bit": 0x2000000},
}

# ══════════════════════════════════════════════════════════════════════
#  罕贵度（rarity）—— 只声明标签与视觉手法键，具体渲染在 render/rarities.py
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RaritySpec:
    key: str
    zh_cn: str
    ja: str
    en: str
    tier: int = 0            # 档次（用于 UI 排序与"稀有度感"）
    abbr: str = ""           # 引擎/素材常用的短代码
    note: str = ""


RARITIES: dict[str, RaritySpec] = {
    r.key: r for r in [
        RaritySpec("common", "平卡", "ノーマル", "Common", 0, "n"),
        RaritySpec("rare", "银字", "レア", "Rare", 1, "r"),
        RaritySpec("super", "面闪", "スーパーレア", "Super Rare", 2, "sr"),
        RaritySpec("ultra", "金闪", "ウルトラレア", "Ultra Rare", 3, "ur"),
        RaritySpec("ultimate", "浮雕", "アルティメットレア", "Ultimate Rare", 4, "utr"),
        RaritySpec("secret", "银碎", "シークレットレア", "Secret Rare", 4, "ser"),
        RaritySpec("ultra_secret", "金碎", "ウルトラシークレットレア", "Ultra Secret Rare", 5, "user"),
        RaritySpec("extra_secret", "额外银碎", "エクストラシークレット", "Extra Secret Rare", 5, "esr"),
        RaritySpec("prismatic_secret", "棱镜碎", "プリズマティックシークレット", "Prismatic Secret Rare", 6, "pser"),
        RaritySpec("platinum_secret", "铂金碎", "プラチナシークレット", "Platinum Secret Rare", 6, "plsr"),
        RaritySpec("gold", "金字", "ゴールドレア", "Gold Rare", 5, "gr"),
        RaritySpec("gold_secret", "金碎（GSR）", "ゴールドシークレット", "Gold Secret Rare", 6, "gser"),
        RaritySpec("holographic", "全息", "ホログラフィックレア", "Holographic Rare", 7, "hr"),
        RaritySpec("parallel", "爆闪", "パラレルレア", "Parallel Rare", 3, "pr"),
        RaritySpec("normal_parallel", "平爆", "ノーマルパラレル", "Normal Parallel Rare", 2, "npr"),
        RaritySpec("rare_parallel", "面爆", "レアパラレル", "Rare Parallel Rare", 3, "rpr"),
        RaritySpec("collector", "典藏", "コレクターズレア", "Collector's Rare", 7, "cr"),
        RaritySpec("starlight", "星光", "スターライトレア", "Starlight Rare", 8, "slr"),
        RaritySpec("quarter_century", "四分之一世纪", "クォーターセンチュリー", "Quarter Century Secret Rare", 9, "qcscr"),
        RaritySpec("20th_secret", "20 周年版", "20thシークレットレア", "20th Secret Rare", 8, "20ser"),
        RaritySpec("millennium", "千年", "ミレニアムレア", "Millennium Rare", 8, "mlr"),
        RaritySpec("ghost", "幽灵", "ゴーストレア", "Ghost Rare", 9, "ghr"),
        RaritySpec("dt", "DT 碎钻", "デュエルターミナル", "Duel Terminal Rare", 4, "dt"),
        RaritySpec("normal_rare", "罕有平卡", "ノーマルレア", "Normal Rare", 2, "nr"),
        RaritySpec("full_art", "全画", "フルアート", "Full Art", 9, "fa",
                   note="出框/全画类，与覆膜正交，可叠加"),
    ]
}

# ══════════════════════════════════════════════════════════════════════
#  语言
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LangSpec:
    key: str
    zh_cn: str
    native: str
    # 断行策略：cjk=按字断（含禁则）；word=按词断
    wrap: str = "word"
    # 卡文是否使用「；」分隔代价/取对象与效果处理（中日官方卡文不用）
    uses_semicolon: bool = True
    # EDOPro 语言目录/文件后缀（用于 cards-<suffix>.cdb 命名）
    cdb_suffix: str = ""
    font_hint: str = "sans"


LANGS: dict[str, LangSpec] = {
    l.key: l for l in [
        LangSpec("zh_cn", "简体中文", "简体中文", "cjk", False, "zh-CN", "sc"),
        LangSpec("zh_tw", "繁体中文", "繁體中文", "cjk", False, "zh-TW", "tc"),
        LangSpec("ja", "日文", "日本語", "cjk", False, "ja", "jp"),
        LangSpec("en", "英文", "English", "word", True, "en", "en"),
        LangSpec("ko", "韩文", "한국어", "word", False, "ko", "kr"),
        LangSpec("de", "德文", "Deutsch", "word", True, "de", "de"),
        LangSpec("fr", "法文", "Français", "word", True, "fr", "fr"),
        LangSpec("it", "意大利文", "Italiano", "word", True, "it", "it"),
        LangSpec("pt", "葡萄牙文", "Português", "word", True, "pt", "pt"),
        LangSpec("es", "西班牙文", "Español", "word", True, "es", "es"),
    ]
}
DEFAULT_LANG = "zh_cn"


# ══════════════════════════════════════════════════════════════════════
#  出框档位（正交于罕贵，可叠加）
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FullArtMode:
    key: str
    zh_cn: str
    ja: str
    en: str
    note: str = ""


FULL_ART_MODES: dict[str, FullArtMode] = {
    m.key: m for m in [
        FullArtMode("none", "标准", "通常", "Standard", "插画严格限制在卡图窗内"),
        FullArtMode("overframe", "官方超框", "オーバーフレーム", "Overframe",
                    "官方 2026 超框卡：插画铺满内框、外框保留；名/星/属性浮于画上，"
                    "面板半透明含类型行；密码隐藏（中文官方商品名「超框卡」）"),
        FullArtMode("art_bleed", "出血出框", "出血出框", "Art Bleed",
                    "插画上下溢出卡图窗，压住类型行/文本框边缘"),
        FullArtMode("art_over", "超框（旧·并入官方）", "オーバーフレーム（旧）", "Overframe (legacy)",
                    "兼容别名：历史卡按官方超框几何渲染，界面不再单列这一档"),
        FullArtMode("full_bleed", "全画", "フルアート", "Full Art",
                    "除必要信息条外无框，插画铺满整卡"),
        FullArtMode("pendulum_full", "灵摆出框", "ペンデュラム出框", "Pendulum Full Art",
                    "灵摆框双区分别溢出"),
        FullArtMode("subject_bleed", "主体出框", "主体オーバーフレーム", "Subject Overframe",
                    "背景严格留在卡图窗内，只有主体越出窗沿压到框上（需分层卡图）"),
    ]
}


def label_of(table: dict, key: str, lang: str = "zh_cn", default: str = "") -> str:
    """从 FRAMES / RARITIES / FULL_ART_MODES 等表里取某语言的标签。"""
    item = table.get(key)
    if item is None:
        return default or key
    return getattr(item, lang, None) or getattr(item, "zh_cn", default) or key
