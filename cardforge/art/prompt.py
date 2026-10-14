"""提示词工程 —— 中文意图 → 可直接送进模型的英文提示词。

结构（槽位顺序即 CLIP 权重顺序，越靠前越强）
--------------------------------------------
``画质前缀（按 profile.prompt_style） + 主体 + 卡种氛围词（按 spec.frame） +
构图词（卡图窗比例 / 单主体居中 / 留白） + 风格词 + 光照词``

两条书写范式
------------
* **danbooru / pony / animagine**（SD1.5 / SDXL 系）：逗号分隔的标签堆叠，
  画质词必须放最前面（77-token 分块会让靠后内容衰减）。
* **natural**（krea2 / qwen / flux）：**自然语言长句**，不是标签堆叠。
  Krea 2 是流匹配 DiT + Qwen3-VL 文本编码器，稠密 caption（约 150–230 词）效果最好。

``cfg = 1.0`` 的特殊处理
------------------------
Krea 2 / Qwen-Image 是蒸馏少步模型，``cfg = 1.0`` 时**负向那一遍前向根本不跑**，
所以 ``negative`` 基本不生效。此时 :func:`build` 会把「要排除的东西」**改写成
正向描述**追加到末尾（例如「画面里没有任何文字与水印，背景干净」），
并在 ``notes`` 里说明；``negative`` 字段仍会返回（用户手动调高 cfg 时可用）。

系列一致性
----------
:data:`SERIES_STYLE_KEY` = ``"series_style"``：
同一 :class:`~cardforge.core.models.Archetype` 的多张卡**共享同一段冻结的风格前缀**，
只让主体部分变化。风格前缀由 ``Archetype`` 的 ``concept``/``binding``/``dialects``
+ 用户显式给的 ``style`` 一起确定性推导，保证「同一个系列名 → 同一段前缀」。
"""
from __future__ import annotations

import re

from ..core.models import Archetype, ArtRequest, CardSpec
from .profiles import ModelProfile

#: 系列一致性的冻结键名（写进 ArtRequest.series_context，跨卡共享同一段风格前缀）
SERIES_STYLE_KEY = "series_style"

__all__ = [
    "SERIES_STYLE_KEY", "build", "build_layers", "zh_to_tags", "series_style_prefix",
    "frame_atmosphere", "NEGATIVE_CARD", "ZH_TAGS", "normalize_negative",
]


# ══════════════════════════════════════════════════════════════════════
#  1. 卡图专用负向词
# ══════════════════════════════════════════════════════════════════════
#: 卡图场景的负向词（**与档案负向取并集**）。核心诉求：不要文字、不要边框、
#: 只要单主体 —— 因为卡图窗很小，出现文字/边框会直接毁掉成品。
NEGATIVE_CARD = (
    "text, watermark, signature, username, logo, artist name, copyright name, "
    "web address, url, speech bubble, caption, letterboxed, border, frame, "
    "card, card (medium), trading card, multiple views, character sheet, "
    "reference sheet, collage, split screen, 2girls, 2boys, multiple characters, "
    "cropped, out of frame, blurry, jpeg artifacts, lowres"
)

#: 按卡种追加的负向（例如灵摆卡要避免「两张画」的构图）
NEGATIVE_BY_FRAME: dict[str, str] = {
    "spell": "monster, creature, character, person",
    "trap": "monster, creature, character, person",
    "link": "duplicate subject, symmetry artifacts",
    "xyz": "duplicate subject",
    "token": "detailed background, complex scene",
}


# ══════════════════════════════════════════════════════════════════════
#  2. 中文 → 英文标签词典（规则映射，≥60 词条）
# ══════════════════════════════════════════════════════════════════════
#: 中文风格/氛围词 → 英文标签。**多对多**：一个中文词可映射到多个标签。
ZH_TAGS: dict[str, list[str]] = {
    # ── 画面技法 ──
    "赛璐璐": ["cel shading", "flat colors", "clean lineart"],
    "赛璐璐上色": ["cel shading", "flat colors", "clean lineart"],
    "厚涂": ["thick painting", "impasto", "painterly"],
    "水彩": ["watercolor (medium)", "watercolor texture", "soft edges"],
    "淡彩": ["light watercolor", "pale colors"],
    "油画": ["oil painting (medium)", "painterly brushstrokes"],
    "水墨": ["ink wash painting", "sumi-e", "monochrome ink"],
    "国风": ["chinese style", "chinese clothes"],
    "和风": ["japanese style", "kimono", "traditional japanese"],
    "素描": ["sketch", "pencil (medium)", "rough lineart"],
    "线稿": ["lineart", "clean lines"],
    "像素": ["pixel art", "8-bit", "limited palette"],
    "扁平": ["flat design", "flat colors", "minimal shading"],
    "低多边形": ["low poly", "polygonal"],
    "3D渲染": ["3d", "3d render", "octane render"],
    "黏土": ["clay", "claymation"],
    "剪纸": ["paper cutout", "layered paper"],
    "浮世绘": ["ukiyo-e", "woodblock print"],
    "绘本": ["storybook illustration", "children's book style"],
    "蜡笔": ["crayon", "wax crayon"],
    "版画": ["woodcut", "engraving"],
    # ── 光线 ──
    "逆光": ["backlighting", "rim light", "silhouette edges"],
    "侧光": ["side lighting", "chiaroscuro"],
    "顶光": ["top-down lighting", "god rays"],
    "黄昏": ["golden hour", "sunset", "warm orange light"],
    "黎明": ["dawn", "pale blue light", "morning mist"],
    "夜景": ["night", "night sky", "dark blue palette"],
    "月光": ["moonlight", "moonlit", "cool blue light"],
    "霓虹": ["neon lights", "neon glow", "cyberpunk colors"],
    "烛光": ["candlelight", "warm flickering light"],
    "体积光": ["volumetric lighting", "light shafts", "god rays"],
    "柔光": ["soft lighting", "diffused light"],
    "硬光": ["hard light", "high contrast shadows"],
    "戏剧性光照": ["dramatic lighting", "cinematic lighting"],
    "发光": ["glowing", "emissive", "luminescent"],
    "荧光": ["fluorescent", "bioluminescence"],
    "闪电": ["lightning", "electric sparks"],
    # ── 题材/氛围 ──
    "蒸汽朋克": ["steampunk", "brass gears", "victorian machinery"],
    "赛博朋克": ["cyberpunk", "neon city", "holographic"],
    "机械": ["mechanical", "mecha", "metal plating"],
    "神圣": ["holy", "divine", "radiant", "halo"],
    "暗黑": ["dark", "ominous", "gothic horror"],
    "哥特": ["gothic", "gothic architecture", "rose window"],
    "恶魔": ["demonic", "fiend", "horns"],
    "天使": ["angelic", "wings", "feathers"],
    "奇幻": ["fantasy", "magical", "enchanted"],
    "科幻": ["science fiction", "futuristic", "spaceship"],
    "废土": ["post-apocalyptic", "wasteland", "ruins"],
    "克苏鲁": ["eldritch", "lovecraftian", "tentacles"],
    "东方幻想": ["eastern fantasy", "ornate patterns"],
    "魔法阵": ["magic circle", "magic sigil", "arcane runes"],
    "符文": ["runes", "glyphs", "glowing runes"],
    "炼金术": ["alchemy", "alchemical symbols", "transmutation circle"],
    "阴阳": ["yin yang", "dual opposing forces"],
    "星象": ["constellation", "astrology", "zodiac"],
    "宇宙": ["cosmic", "galaxy", "nebula", "stardust"],
    "深海": ["deep sea", "underwater", "bubbles"],
    "熔岩": ["lava", "molten rock", "magma"],
    "冰雪": ["ice", "frozen", "snowfield", "frost crystals"],
    "风暴": ["storm", "thunderclouds", "raging sky"],
    "森林": ["forest", "ancient trees", "sunbeams through leaves"],
    "沙漠": ["desert", "sand dunes", "heat haze"],
    "废墟": ["ruins", "overgrown rubble", "broken pillars"],
    "神殿": ["temple", "shrine", "sacred hall"],
    "城堡": ["castle", "fortress"],
    "战场": ["battlefield", "banners", "smoke"],
    # ── 气质 ──
    "霸气": ["imposing", "powerful", "epic", "overwhelming presence"],
    "神秘": ["mysterious", "mystical", "enigmatic"],
    "优雅": ["elegant", "graceful", "refined"],
    "可爱": ["cute", "kawaii", "chibi proportions"],
    "凶暴": ["ferocious", "savage", "snarling"],
    "威压": ["menacing", "intimidating", "looming"],
    "治愈": ["healing", "soothing", "warm and gentle"],
    "悲壮": ["tragic", "heroic sacrifice", "solemn"],
    "活泼": ["lively", "energetic", "cheerful"],
    "冷峻": ["cold", "aloof", "sharp gaze"],
    "空灵": ["ethereal", "otherworldly", "translucent"],
    "诡异": ["eerie", "uncanny", "unsettling"],
    "庄严": ["solemn", "majestic", "ceremonial"],
    "狂暴": ["berserk", "frenzied", "rampaging"],
    # ── 构图/技术 ──
    "全身": ["full body"],
    "半身": ["upper body", "portrait"],
    "大头": ["close-up", "face focus"],
    "居中": ["centered", "centered composition"],
    "仰视": ["from below", "low angle"],
    "俯视": ["from above", "high angle"],
    "动态": ["dynamic pose", "motion blur"],
    "景深": ["depth of field", "bokeh"],
    "留白": ["negative space", "simple background", "ample empty space"],
    "纯色背景": ["solid background", "plain background"],
    "渐变背景": ["gradient background"],
    "特写": ["close-up"],
    "对称": ["symmetrical composition"],
    "广角": ["wide shot", "wide angle"],

    # ── 幻想生物与种族 ──
    "龙": ["dragon"],
    "巨龙": ["dragon", "huge dragon", "imposing scale"],
    "古龙": ["elder dragon", "ancient dragon"],
    "幼龙": ["baby dragon", "small dragon"],
    "飞龙": ["wyvern", "two-legged dragon"],
    "蛇形龙": ["serpentine dragon", "long neck"],
    "多头龙": ["multi-headed dragon", "two heads"],
    "龙鳞": ["dragon scales", "scales"],
    "黑曜石鳞片": ["obsidian scales", "black scales", "glossy scales"],
    "翼膜": ["wing membrane", "membrane wings"],
    "龙角": ["dragon horns", "horns"],
    "龙爪": ["dragon claws", "sharp claws"],
    "龙尾": ["dragon tail", "long tail"],
    "竖瞳": ["vertical pupils", "slit pupils"],
    "红色瞳孔": ["red eyes", "glowing red eyes"],
    "金色瞳孔": ["golden eyes", "golden pupils"],
    "独角兽": ["unicorn", "single horn"],
    "狮鹫": ["griffin", "eagle wings", "lion body"],
    "凤凰": ["phoenix", "fire bird", "burning feathers"],
    "九尾狐": ["nine-tailed fox", "kitsune", "multiple tails"],
    "巨狼": ["giant wolf", "dire wolf", "feral"],
    "巨蛇": ["giant snake", "serpent", "coiled"],
    "海怪": ["sea monster", "kraken", "tentacles"],
    "史莱姆": ["slime (creature)", "gelatinous body"],
    "傀儡": ["golem", "puppet", "constructed body"],
    "石像鬼": ["gargoyle", "stone statue", "carved stone"],
    "精灵": ["elf", "pointed ears"],
    "矮人": ["dwarf", "short and stout", "beard"],
    "巨人": ["giant", "titan", "colossal"],
    "亡灵": ["undead", "risen dead"],
    "骷髅": ["skeleton", "skull", "bone"],
    "幽灵": ["ghost", "spectre", "translucent body"],
    "吸血鬼": ["vampire", "high collar", "fangs"],
    "狼人": ["werewolf", "wolf ears", "fur"],
    "半人马": ["centaur", "horse body"],
    "人鱼": ["mermaid", "fish tail", "scales"],
    "堕天使": ["fallen angel", "black wings", "broken halo"],
    "魔鬼": ["devil", "demon horns", "pointed tail"],
    "妖精": ["fairy", "fae", "small wings", "sparkles"],
    "树精": ["treant", "tree person", "bark skin"],
    "巨龙形态": ["draconic form", "dragonoid"],

    # ── 材质与质感 ──
    "黑曜石": ["obsidian", "black glassy surface"],
    "水晶": ["crystal", "crystalline", "faceted"],
    "冰晶": ["ice crystals", "frozen shards"],
    "钻石": ["diamond", "gemstone sparkle"],
    "黄金": ["gold", "golden", "gilded"],
    "白银": ["silver", "silvery metal"],
    "青铜": ["bronze", "patina"],
    "锈铁": ["rusted iron", "corroded metal"],
    "陶瓷": ["porcelain", "ceramic"],
    "玻璃": ["glass", "translucent"],
    "玉石": ["jade", "green stone"],
    "琥珀": ["amber", "fossil resin"],
    "骨骼": ["bone", "skeletal"],
    "象牙": ["ivory", "carved ivory"],
    "羽毛": ["feathers", "plumage"],
    "毛皮": ["fur", "fluffy"],
    "丝绸": ["silk", "silky fabric"],
    "皮革": ["leather", "worn leather"],
    "锁子甲": ["chainmail", "chain armor"],
    "板甲": ["plate armor", "armored"],
    "长袍": ["robe", "flowing robe"],
    "斗篷": ["cloak", "cape"],
    "绷带": ["bandages", "wrapped in bandages"],
    "液态金属": ["liquid metal", "molten chrome"],
    "发光纹路": ["glowing lines", "luminous patterns"],
    "熔岩裂纹": ["magma cracks", "lava cracks", "glowing fissures"],
    "能量脉络": ["energy veins", "glowing energy lines"],
    "金色火焰": ["golden flames", "gold fire"],
    "紫色光晕": ["violet aura", "purple glow"],
    "黑色光环": ["black aura", "dark miasma"],
    "青色电路": ["cyan circuitry", "circuit lines"],

    # ── 武器与装备 ──
    "剑": ["sword"],
    "巨剑": ["greatsword", "large sword"],
    "双剑": ["dual wielding", "two swords"],
    "长枪": ["spear", "lance"],
    "骑枪": ["jousting lance"],
    "斧": ["axe", "battle axe"],
    "战锤": ["warhammer", "hammer"],
    "镰刀": ["scythe", "curved blade"],
    "弓": ["bow (weapon)", "archery"],
    "弩": ["crossbow"],
    "法杖": ["staff", "magic staff"],
    "魔杖": ["wand"],
    "权杖": ["scepter", "royal scepter"],
    "匕首": ["dagger", "short blade"],
    "盾": ["shield"],
    "头盔": ["helmet", "visor"],
    "王冠": ["crown", "tiara"],
    "面具": ["mask", "face mask"],
    "披风": ["cape", "billowing cloak"],
    "护符": ["amulet", "talisman"],
    "项链": ["necklace", "pendant"],
    "戒指": ["ring (jewelry)"],
    "锁链": ["chains", "shackles"],
    "镣铐": ["manacles", "bound by chains"],
    "卷轴": ["scroll", "parchment"],
    "魔导书": ["grimoire", "floating book"],
    "水晶球": ["crystal ball", "scrying orb"],
    "提灯": ["lantern", "hanging lantern"],
    "旗帜": ["banner", "war flag"],
    "竖琴": ["harp"],
    "笛": ["flute"],

    # ── 姿态与动作 ──
    "站立": ["standing", "upright stance"],
    "悬停": ["hovering", "floating in place"],
    "飞翔": ["flying", "in flight"],
    "俯冲": ["diving", "swooping down"],
    "扑击": ["pouncing", "lunging"],
    "咆哮": ["roaring", "snarling"],
    "嘶吼": ["howling", "screaming"],
    "张嘴": ["open mouth", "mouth open"],
    "凝视": ["staring", "intense gaze"],
    "回望": ["looking back", "turned head"],
    "低头": ["head lowered", "looking down"],
    "抬头": ["looking up", "head raised"],
    "伸展": ["stretching", "outstretched limbs"],
    "张开双翼": ["spread wings", "wings spread wide"],
    "收拢翅膀": ["folded wings", "wings folded"],
    "单膝跪地": ["kneeling", "one knee down"],
    "举手": ["raised hand", "hand raised"],
    "挥手": ["waving hand"],
    "施法": ["casting spell", "channeling magic"],
    "结印": ["hand seal", "mudra"],
    "握剑": ["holding sword", "gripping weapon"],
    "举盾": ["raising shield"],
    "交叉双臂": ["crossed arms"],
    "抱胸": ["arms crossed over chest"],
    "背手": ["hands behind back"],
    "漫步": ["walking", "strolling"],
    "冲刺": ["charging forward", "dashing"],
    "后仰": ["leaning back", "arched back"],
    "前倾": ["leaning forward"],
    "转身": ["turning around", "mid-turn"],
    "蜷缩": ["curled up", "coiled"],
    "漂浮": ["floating", "weightless"],
    "破土而出": ["bursting from the ground", "erupting"],
    "从天而降": ["descending from the sky", "falling from above"],
    "踏在": ["standing on", "planted on"],
    "双翼张开": ["wings spread wide", "spread wings"],
    "踏在石台上": ["standing on a stone platform", "perched on rock"],

    # ── 场景与背景 ──
    "浮空岛": ["floating island", "sky island"],
    "浮空石台": ["floating stone platform", "shattered floating rock"],
    "崩塌": ["collapsing", "crumbling", "shattering"],
    "石台": ["stone platform", "rocky dais"],
    "祭坛": ["altar", "sacrificial altar"],
    "王座": ["throne", "ornate throne"],
    "断柱": ["broken pillars", "ruined columns"],
    "遗迹": ["ancient ruins", "ruins"],
    "地下城": ["dungeon", "underground hall"],
    "洞窟": ["cave", "cavern"],
    "熔岩池": ["lava pool", "molten lake"],
    "火山口": ["volcanic crater", "volcano"],
    "雪原": ["snowfield", "snowy plain"],
    "冰川": ["glacier", "ice field"],
    "冻湖": ["frozen lake", "ice sheet"],
    "绿洲": ["oasis", "palm trees"],
    "峡谷": ["canyon", "ravine"],
    "悬崖": ["cliff", "precipice"],
    "瀑布": ["waterfall", "cascading water"],
    "湖泊": ["lake", "still water"],
    "海洋": ["ocean", "open sea"],
    "珊瑚礁": ["coral reef", "underwater reef"],
    "沼泽": ["swamp", "marsh", "murky water"],
    "丛林": ["jungle", "dense foliage"],
    "古树": ["ancient tree", "giant tree"],
    "草原": ["grassland", "prairie"],
    "花田": ["flower field", "blooming meadow"],
    "麦田": ["wheat field"],
    "城墙": ["city wall", "fortification"],
    "城门": ["city gate", "gatehouse"],
    "塔楼": ["tower", "spire"],
    "大教堂": ["cathedral", "stained glass window"],
    "鸟居": ["torii gate", "shrine gate"],
    "庭院": ["courtyard", "garden"],
    "图书馆": ["library", "bookshelves"],
    "实验室": ["laboratory", "alchemical lab"],
    "工房": ["workshop", "forge"],
    "王宫": ["palace", "throne hall"],
    "市集": ["marketplace", "market street"],
    "小巷": ["alley", "narrow alleyway"],
    "屋顶": ["rooftop", "roof tiles"],
    "桥梁": ["bridge", "stone bridge"],
    "飞船": ["airship", "flying vessel"],
    "飞艇": ["zeppelin", "blimp"],
    "机械都市": ["mechanical city", "industrial skyline"],
    "霓虹街": ["neon street", "neon signs"],
    "荒原": ["wasteland", "barren plain"],
    "星海": ["sea of stars", "starfield"],
    "银河": ["galaxy", "milky way"],
    "星空": ["starry sky", "night sky"],
    "云端": ["above the clouds", "cloud top"],
    "天空之城": ["city in the sky", "sky citadel"],
    "漩涡": ["whirlpool", "vortex", "swirling energy"],
    "传送门": ["portal", "gateway of light"],
    "结界": ["barrier", "magical barrier"],
    "裂缝": ["rift", "crack in space"],
    "陨石": ["meteor", "falling meteorite"],
    "流星": ["shooting star", "meteor shower"],
    "极光": ["aurora", "northern lights"],
    "沙尘暴": ["sandstorm", "dust storm"],
    "暴风雪": ["blizzard", "snowstorm"],
    "雷云": ["thunderclouds", "storm clouds"],
    "浓雾": ["thick fog", "mist"],
    "烟尘": ["smoke", "dust in the air"],
    "灰烬": ["ash", "floating embers"],
    "火星": ["sparks", "flying embers"],
    "花瓣": ["falling petals", "floating petals"],
    "落叶": ["falling leaves", "autumn leaves"],
    "雨水": ["rain", "raindrops"],
    "涟漪": ["ripples", "water ripple"],

    # ── 人物外观 ──
    "长发": ["long hair", "flowing hair"],
    "短发": ["short hair"],
    "双马尾": ["twintails"],
    "单马尾": ["ponytail"],
    "卷发": ["curly hair", "wavy hair"],
    "银发": ["silver hair", "white hair"],
    "金发": ["blonde hair", "golden hair"],
    "黑发": ["black hair"],
    "红发": ["red hair"],
    "蓝发": ["blue hair"],
    "粉发": ["pink hair"],
    "渐变色头发": ["gradient hair", "two-tone hair"],
    "呆毛": ["ahoge", "single hair strand"],
    "刘海": ["bangs", "fringe"],
    "眼罩": ["eyepatch"],
    "异色瞳": ["heterochromia", "different colored eyes"],
    "发光眼睛": ["glowing eyes", "luminous eyes"],
    "猫耳": ["cat ears", "nekomimi"],
    "狐耳": ["fox ears"],
    "兽耳": ["animal ears", "kemonomimi"],
    "角": ["horns", "demon horns"],
    "翅膀": ["wings", "feathered wings"],
    "尾巴": ["tail"],
    "獠牙": ["fangs", "sharp teeth"],
    "尖耳": ["pointed ears", "elf ears"],
    "雀斑": ["freckles"],
    "伤疤": ["scar", "battle scar"],
    "纹身": ["tattoo"],
    "面纹": ["face markings", "war paint"],
    "斗笠": ["conical hat", "sedge hat"],
    "头巾": ["headscarf", "bandana"],
    "发饰": ["hair ornament", "hair ribbon"],
    "耳环": ["earrings"],

    # ── 服装风格 ──
    "校服": ["school uniform", "serafuku"],
    "水手服": ["sailor dress", "serafuku"],
    "西装": ["suit", "formal suit"],
    "礼服": ["formal dress", "evening gown"],
    "洋装": ["dress", "frilled dress"],
    "和服": ["kimono", "japanese clothes"],
    "浴衣": ["yukata", "summer kimono"],
    "汉服": ["hanfu", "chinese clothes"],
    "旗袍": ["qipao", "chinese dress"],
    "盔甲": ["armor", "full plate armor"],
    "法袍": ["mage robe", "wizard robe"],
    "僧袍": ["monk robe", "kasaya"],
    "修女服": ["nun habit", "religious habit"],
    "骑士装": ["knight armor", "knightly attire"],
    "军装": ["military uniform"],
    "大衣": ["coat", "long coat"],
    "毛衣": ["sweater", "knitwear"],
    "围巾": ["scarf", "muffler"],
    "手套": ["gloves"],
    "长靴": ["boots", "thigh boots"],
    "腰带": ["belt", "waist sash"],
    "披肩": ["shawl", "shoulder cape"],

    # ── 情绪与表情 ──
    "微笑": ["smile", "gentle smile"],
    "大笑": ["laughing", "open-mouth smile"],
    "冷笑": ["smirk", "cold smile"],
    "哭泣": ["crying", "teary eyes"],
    "流泪": ["tears", "streaming tears"],
    "愤怒": ["angry", "furious"],
    "皱眉": ["furrowed brow", "frown"],
    "惊讶": ["surprised", "wide-eyed"],
    "困惑": ["confused", "puzzled"],
    "悲伤": ["sad", "sorrowful"],
    "坚定": ["determined", "resolute expression"],
    "平静": ["calm", "serene expression"],
    "得意": ["smug", "confident smirk"],
    "温柔": ["gentle", "tender expression"],
    "害羞": ["blush", "shy"],
    "疲惫": ["tired", "exhausted"],
    "痛苦": ["in pain", "agonized"],
    "狰狞": ["ferocious expression", "bared teeth"],
    # ── 人物与日常 ──
    "少女": ["girl", "young woman"],
    "少年": ["boy", "young man"],
    "男子": ["man", "male"],
    "女子": ["woman", "female"],
    "女孩": ["girl"],
    "男孩": ["boy"],
    "老人": ["old person", "elder"],
    "骑士": ["knight"],
    "法师": ["mage", "wizard"],
    "巫女": ["shrine maiden", "miko"],
    "公主": ["princess"],
    "王子": ["prince"],
    "国王": ["king"],
    "女王": ["queen"],
    "武士": ["samurai", "bushi"],
    "忍者": ["ninja"],
    "剑士": ["swordsman", "sword wielder"],
    "弓手": ["archer", "bowman"],
    "祭司": ["priest", "priestess"],
    "学者": ["scholar"],
    "工匠": ["artisan", "craftsman"],
    "指挥官": ["commander", "officer"],

    # ── 颜色（常用单字，避免「白色/红色」被当残留） ──
    "白色": ["white"],
    "黑色": ["black"],
    "红色": ["red"],
    "蓝色": ["blue"],
    "绿色": ["green"],
    "黄色": ["yellow"],
    "紫色": ["purple"],
    "橙色": ["orange (color)"],
    "粉色": ["pink"],
    "灰色": ["grey"],
    "棕色": ["brown"],
    "青色": ["cyan", "teal"],
    "金色": ["golden", "gold"],
    "银色": ["silver"],
    "彩色": ["colorful", "multicolored"],
    "深色": ["dark colors"],
    "浅色": ["light colors"],

    # ── 高频动词短语 ──
    "穿着": ["wearing"],
    "披着": ["draped in", "wearing"],
    "戴着": ["wearing"],
    "手持": ["holding", "wielding"],
    "握着": ["gripping", "holding"],
    "举着": ["raising", "holding up"],
    "背着": ["carrying on the back"],
    "站在": ["standing"],
    "坐在": ["sitting"],
    "躺在": ["lying down"],
    "跪在": ["kneeling"],
    "悬停在": ["hovering over"],
    "飞在": ["flying over"],
    "漂浮在": ["floating over"],
    "走在": ["walking through"],
    "跑在": ["running through"],
    "上空": ["above", "in the sky over"],
    "面前": ["in front of"],
    "身后": ["behind"],
    "之中": ["inside", "within"],
    "之间": ["between"],
    "都市": ["city", "metropolis"],
    "城镇": ["town", "village"],
    "村庄": ["village"],
    "房间": ["room", "interior"],
    "街道": ["street"],
    "天空": ["sky"],
    "大地": ["ground", "earth"],
    "水面": ["water surface"],
    "地面": ["ground"],
    "墙面": ["wall"],
    "式": [],
    "里": [],
    "中": [],
    "有": [],

    # ── 视角 / 构图补充（长词优先，避免「视角」被拆成「视」+「角」）──
    "视角": [],
    "俯视视角": ["from above", "high angle"],
    "仰视视角": ["from below", "low angle"],
    "平视视角": ["eye level", "straight-on view"],
    "正面视角": ["front view", "facing viewer"],
    "侧面视角": ["side view", "profile"],
    "背面视角": ["back view", "seen from behind"],
    "俯瞰": ["bird's-eye view", "overhead shot"],
    "远景": ["wide shot", "long shot"],
    "中景": ["medium shot"],
    "近景": ["close shot"],
    "全身像": ["full body"],
    "半身像": ["upper body", "portrait"],

    # ── 常见残留词补充 ──
    "藤蔓": ["vines", "creeping vines"],
    "藤条": ["rattan", "vine"],
    "萤火": ["fireflies", "bioluminescent glow"],
    "腐化": ["corrupted", "tainted"],
    "腐蚀": ["corroded", "acid-eaten"],
    "枯萎": ["withered", "wilted"],
    "开花": ["blooming", "in blossom"],
    "影子": ["shadow", "cast shadow"],
    "倒影": ["reflection", "mirrored reflection"],
    "轨迹": ["motion trail", "streaking trail"],
    "残影": ["afterimage", "motion blur"],
    "旋涡": ["swirl", "spiral"],
    "螺旋": ["spiral", "helix"],
    "碎片": ["shards", "fragments"],
    "颗粒": ["particles", "floating motes"],
    "光点": ["light motes", "sparkles"],
    "气流": ["air current", "wind flow"],
    "蒸汽": ["steam", "vapor"],
    "雾霭": ["haze", "mist"],
    "烟幕": ["smokescreen", "thick smoke"],
    "血": ["blood"],
    "泪": ["tears"],
    "汗": ["sweat"],
    "伤口": ["wound", "injury"],
    "破碎的": ["shattered", "broken"],
    "残破的": ["battered", "battle-worn"],
    "华丽的": ["ornate", "elaborate"],
    "朴素的": ["plain", "simple"],
    "繁复的": ["intricate", "detailed"],
    "厚重的": ["heavy", "solid"],
    "纤细的": ["slender", "delicate"],
    "扭曲的": ["twisted", "distorted"],
    "笔直的": ["straight", "upright"],
    "弯曲的": ["curved", "bent"],

    # ── 高频修饰语 / 形容词 / 动词 ──
    "巨大": ["giant", "enormous", "massive"],
    "庞大": ["colossal", "towering"],
    "微小": ["tiny", "diminutive"],
    "细小": ["small", "delicate"],
    "锋利": ["sharp", "razor-sharp"],
    "尖锐": ["pointed", "spiked"],
    "厚重": ["heavy", "thick"],
    "轻盈": ["light", "weightless"],
    "光滑": ["smooth", "polished"],
    "粗糙": ["rough", "weathered"],
    "破碎": ["shattered", "broken"],
    "古老": ["ancient", "aged"],
    "崭新": ["pristine", "brand new"],
    "燃烧": ["burning", "ablaze"],
    "燃着": ["burning", "aflame"],
    "燃烧着": ["burning", "aflame"],
    "缠绕": ["wrapped around", "coiled around"],
    "环绕": ["surrounded by", "encircling"],
    "漂浮着": ["floating", "drifting"],
    "散落": ["scattered", "strewn"],
    "飞溅": ["splashing", "spraying"],
    "溢出": ["overflowing", "spilling"],
    "迸发": ["bursting", "erupting"],
    "裂纹": ["cracks", "fissures"],
    "胸口": ["chest", "on its chest"],
    "背部": ["back", "on its back"],
    "肩部": ["shoulders"],
    "颈部": ["neck"],
    "头部": ["head"],
    "双翼": ["both wings", "wings"],
    "全身": ["full body"],
    "红光": ["red glow", "crimson light"],
    "蓝光": ["blue glow", "azure light"],
    "金光": ["golden glow", "golden light"],
    "紫光": ["purple glow", "violet light"],
    "白光": ["white glow", "bright light"],
    "黑雾": ["black mist", "dark fog"],
    "竖直": ["vertical", "upright"],
    "水平": ["horizontal"],
    "淡": ["pale", "faint"],
    "浓": ["deep", "dense"],
    "厚": ["thick"],
    "薄": ["thin"],
    "透明": ["transparent", "see-through"],
    "半透明": ["semi-transparent", "translucent"],
    "金属质感": ["metallic sheen", "metal texture"],
    "磨砂": ["matte", "frosted"],
    "高光": ["specular highlight", "glossy highlight"],
    "反光": ["reflective", "reflections"],
    "阴影": ["shadows", "shadowed"],
    "轮廓": ["silhouette", "outline"],
    "边缘": ["edges", "rim"],
    "中央": ["center", "in the middle"],
    "四周": ["surrounding", "all around"],
    "远处": ["in the distance", "far away"],
    "近处": ["close to the viewer", "in the foreground"],
    "上方": ["above", "overhead"],
    "下方": ["below", "underneath"],
    "脚下": ["underfoot", "beneath the feet"],
    "背后": ["behind", "in the background"],
    "前方": ["in front", "ahead"],
    "两侧": ["on both sides", "flanking"],
    # ── 虚词 / 量词（值为空 = 丢弃，不污染提示词） ──
    "一条": [],
    "一只": [],
    "两位": [],
    "一个": [],
    "的": [],
    "着": [],
    "在": [],
    "与": [],
    "和": [],
    "并": [],
    "正": [],
    "上": [],
    "下": [],
    "了": [],
    "是": [],
    "把": [],
    "之": [],
    "地": [],
    "得": [],
}

#: 这些中文词是「虚词/量词」，翻译后会变成噪声，直接丢弃（值为空列表）
STOPWORDS_ZH: frozenset[str] = frozenset(
    k for k, v in ZH_TAGS.items() if not v
) or frozenset({"的", "着", "在", "与", "和", "并", "正", "上", "下",
                "一条", "一只", "一个", "两位"})

#: 未命中词典的**中文残留**会被丢弃并记 note（绝不让中文原文漏进英文提示词）
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff]")

#: 未命中的中文里，这些「纯虚词碎片」不值得提示用户
_TRIVIAL_RESIDUE = frozenset({
    "的", "着", "在", "与", "和", "并", "正", "上", "下", "了", "是", "一",
    "条", "只", "个", "位", "把", "之", "地", "得", "",
})


def has_cjk(text: str) -> bool:
    """字符串里有没有中日文字符。"""
    return bool(_CJK_RE.search(str(text or "")))

#: 反向索引：英文标签 → 中文词（用于 note 里说明「这个标签是哪来的」）
_TAG_ORIGIN: dict[str, str] = {}
for _zh, _tags in ZH_TAGS.items():
    for _t in _tags:
        _TAG_ORIGIN.setdefault(_t.lower(), _zh)

#: 需要拆词的分隔符（中文风格描述常见写法）
_SPLIT_RE = re.compile(r"[，,、;；/／|｜+\-—\s]+")


def _tokenize_cjk(text: str) -> list[tuple[str, bool]]:
    """把一段中文/英文混合描述切成 ``[(片段, 是否中文), ...]``。

    * **英文片段按空格整块保留** —— 这样 ``"frost dragon"`` 会作为**一个**片段
      进入提示词（否则会被切成两个互不相关的词，破坏语义）。
    * 中文按字符流处理，由 :func:`_greedy_match` 做最长匹配切分。
    """
    out: list[tuple[str, bool]] = []
    for raw in re.split(r"([\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff]+)",
                        str(text or "")):
        if not raw:
            continue
        if _CJK_RE.search(raw):
            out.append((raw, True))
        else:
            for piece in _SPLIT_RE.split(raw):
                p = piece.strip()
                if p:
                    out.append((p, False))
    return out


def _greedy_match(chunk: str, keys: list[str]) -> tuple[list[str], str]:
    """对一段**纯中文**做最长匹配优先的词典切分。

    :return: ``(命中的英文标签列表, 未命中的中文残留)``
    """
    tags: list[str] = []
    residue: list[str] = []
    i = 0
    n = len(chunk)
    while i < n:
        hit = ""
        for key in keys:
            if chunk.startswith(key, i):
                hit = key
                break
        if hit:
            for t in ZH_TAGS.get(hit, []):
                tags.append(t)
            i += len(hit)
            continue
        # 没命中：吃掉一个字符，攒进残留
        j = i + 1
        while j < n and not any(chunk.startswith(k, j) for k in keys):
            j += 1
        residue.append(chunk[i:j])
        i = j
    return tags, "".join(residue)


def zh_to_tags(style_zh: str) -> list[str]:
    """中文风格/主体描述 → 英文标签列表（**规则映射**，零依赖、零网络）。

    * **最长匹配优先**：``"黑曜石鳞片"`` 命中整词，而不是拆成「黑曜石」+「鳞片」；
      也保证 ``"俯视视角"`` 不会因为匹配到「角」而凭空多出一个 ``horns``；
    * 命中词典 → 展开成英文标签（一个中文词可出多个标签，去重保序）；
    * **虚词/量词**（的、着、一条、视角…）值为空列表 → 直接丢弃，不污染提示词；
    * **未命中的中文残留会被丢弃**（绝不把中文原文漏进英文提示词），
      要提示用户时用 :func:`unmatched_terms` 取回；
    * 非中文片段按分隔符（``,``/空格/``/``…）切分后原样保留，
      所以 ``"frost dragon"`` → ``['frost', 'dragon']``（都是有效的 Danbooru 标签），
      而带连字符的 ``"8-bit"`` 不会被拆开。

    >>> zh_to_tags("赛璐璐，逆光，蒸汽朋克")[:4]
    ['cel shading', 'flat colors', 'clean lineart', 'backlighting']
    >>> zh_to_tags("frost dragon")
    ['frost', 'dragon']
    >>> zh_to_tags("俯视视角")               # 不会多出 horns
    ['from above', 'high angle']
    """
    text = str(style_zh or "").strip()
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def push(tag: str) -> None:
        t = tag.strip().strip(",")
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)

    keys = sorted(ZH_TAGS, key=len, reverse=True)
    for piece, is_cjk in _tokenize_cjk(text):
        if not is_cjk:
            push(piece)
            continue
        tags, _residue = _greedy_match(piece, keys)
        for t in tags:
            push(t)
    return out


def unmatched_terms(text: str, *, keep_trivial: bool = False) -> list[str]:
    """描述里**没被词典命中**的中文词（英文片段不算）。

    这些词**不会**进提示词（会被丢弃），所以调用方应该提示用户改用更常见的词，
    或者把它们写成英文。

    :param keep_trivial: ``True`` 时连「的/着/一条」这类虚词也返回（默认过滤掉）。
    """
    s = str(text or "").strip()
    if not s:
        return []
    keys = sorted(ZH_TAGS, key=len, reverse=True)
    rest: list[str] = []
    for piece, is_cjk in _tokenize_cjk(s):
        if not is_cjk:
            continue
        _tags, residue = _greedy_match(piece, keys)
        residue = residue.strip()
        if not residue:
            continue
        if not keep_trivial and residue in _TRIVIAL_RESIDUE:
            continue
        rest.append(residue)
    return rest


# ══════════════════════════════════════════════════════════════════════
#  3. 卡种氛围词
# ══════════════════════════════════════════════════════════════════════
#: 卡种 → (标签式氛围词, 自然语言氛围句)
FRAME_ATMOSPHERE: dict[str, tuple[str, str]] = {
    "normal": (
        "duel monster, natural pose, serene atmosphere, plain backdrop",
        "The creature is rendered as a calm, iconic duel monster portrait, "
        "set against a simple uncluttered backdrop with nothing written on it.",
    ),
    "effect": (
        "duel monster, glowing aura, magical energy, dramatic lighting",
        "The creature radiates a visible magical aura with drifting energy motes, "
        "and the whole frame is filled with dramatic spell-driven light.",
    ),
    "ritual": (
        "ritual monster, ceremonial circle, runes, blue ritual flame",
        "The creature rises out of a glowing ceremonial ritual circle ringed with "
        "arcane runes and cold blue ritual flame.",
    ),
    "fusion": (
        "fusion monster, purple aura, swirling fusion energy, two forces merging",
        "The creature is a fusion monster wreathed in a violet aura, with two "
        "distinct energies visibly merging and spiralling around its body.",
    ),
    "synchro": (
        "synchro monster, white rings, bright rings of light, radial light burst",
        "The creature is a synchro monster surrounded by concentric rings of "
        "brilliant white light radiating outward from its core.",
    ),
    "xyz": (
        "xyz monster, black and red aura, orbiting energy orbs, cosmic overlay",
        "The creature is an xyz monster with a black-and-crimson aura and glowing "
        "orbs of energy orbiting around it like satellites.",
    ),
    "link": (
        "link monster, circuit lines, cyan circuitry, digital arrows of light",
        "The creature is a link monster traced with luminous cyan circuit lines "
        "and arrows of light, as if it were assembled from data.",
    ),
    "pendulum": (
        "pendulum monster, dual aura, arcane scales, oscillating light",
        "The creature is a pendulum monster, its body split between two opposed "
        "auras that swing back and forth like the arms of a scale.",
    ),
    "normal_pendulum": (
        "pendulum monster, dual aura, arcane scales",
        "The creature is a pendulum monster, its body split between two opposed "
        "auras that swing back and forth like the arms of a scale.",
    ),
    "ritual_pendulum": (
        "pendulum monster, ritual circle, dual aura",
        "The creature is a ritual pendulum monster, standing inside a glowing "
        "ritual circle while two opposed auras swing around it.",
    ),
    "fusion_pendulum": (
        "pendulum monster, fusion energy, violet aura, arcane scales",
        "The creature is a fusion pendulum monster, wrapped in a violet aura of "
        "merging energies and two opposed auras swinging like a scale.",
    ),
    "synchro_pendulum": (
        "pendulum monster, rings of light, dual aura",
        "The creature is a synchro pendulum monster inside concentric rings of "
        "white light, with two opposed auras swinging around it.",
    ),
    "xyz_pendulum": (
        "pendulum monster, black and red aura, orbiting orbs",
        "The creature is an xyz pendulum monster with orbiting orbs of energy and "
        "two opposed auras swinging around it.",
    ),
    "spell": (
        "spell card art, no creature, magical phenomenon, symbolic object, "
        "arcane light, glowing sigil, no characters",
        "This is the illustration for a spell card: a purely magical scene with no "
        "creature and no people — only an enchanted object, glowing sigils and "
        "floating runes suspended in arcane light.",
    ),
    "trap": (
        "trap card art, no creature, ominous mechanism, snares, dark light, "
        "no characters",
        "This is the illustration for a trap card: a menacing mechanism or snare "
        "scene with no creature and no people, lit from a single harsh source.",
    ),
    "token": (
        "token monster, simple design, flat background, mascot-like",
        "A small token creature presented plainly on a flat background, drawn "
        "with a simple readable silhouette.",
    ),
    "skill": (
        "skill card art, symbolic emblem, clean graphic",
        "A clean graphic emblem for a skill card, drawn as a flat symbol.",
    ),
}

#: 属性 → 色彩氛围（让「炎属性」的卡真的偏暖）
ATTRIBUTE_MOOD: dict[str, tuple[str, str]] = {
    "地": ("earth tones, brown and green palette",
           "earth-toned palette of browns and greens"),
    "水": ("cool blue palette, water reflections",
           "cool blue palette with water reflections"),
    "炎": ("warm red and orange palette, embers, heat haze",
           "warm red and orange palette with drifting embers and heat haze"),
    "风": ("fresh green and white palette, wind streaks",
           "fresh green and white palette with visible wind streaks"),
    "光": ("bright white and gold palette, radiant glow",
           "bright white and gold palette with a radiant glow"),
    "暗": ("deep purple and black palette, violet shadows",
           "deep purple and black palette with violet-edged shadows"),
    "神": ("divine gold and white palette, overwhelming radiance",
           "divine gold and white palette with an overwhelming radiance"),
}

#: 种族 → 主体提示（英文标签）
RACE_HINT: dict[str, str] = {
    "战士族": "warrior, armored, weapon",
    "魔法师族": "spellcaster, robe, staff",
    "天使族": "angel, feathered wings, halo",
    "恶魔族": "fiend, horns, bat wings",
    "不死族": "zombie, undead, tattered",
    "机械族": "machine, mechanical, metallic",
    "水族": "aquatic creature, water",
    "炎族": "flame creature, fire",
    "岩石族": "rock creature, stone body",
    "鸟兽族": "winged beast, feathers, talons",
    "植物族": "plant creature, vines, petals",
    "昆虫族": "insect, chitin, mandibles",
    "雷族": "thunder creature, lightning",
    "龙族": "dragon, scales, large wings",
    "兽族": "beast, fur, claws",
    "兽战士族": "beast-warrior, fur and armor",
    "恐龙族": "dinosaur, reptilian, powerful legs",
    "鱼族": "fish creature, fins",
    "海龙族": "sea serpent, fins, coils",
    "爬虫类族": "reptile, scales, cold gaze",
    "念动力族": "psychic, floating objects, psychic aura",
    "幻神兽族": "divine beast, sacred beast",
    "电子界族": "cyberse, digital, circuitry",
    "幻想魔族": "illusion fiend, phantasmal",
    "创造神族": "creator god, cosmic deity",
    "幻龙族": "wyrm, serpentine dragon",
}


def frame_atmosphere(frame: str) -> tuple[str, str]:
    """取卡种的 ``(标签式氛围词, 自然语言氛围句)``。"""
    return FRAME_ATMOSPHERE.get(str(frame or ""), FRAME_ATMOSPHERE["effect"])


# ══════════════════════════════════════════════════════════════════════
#  4. 系列风格前缀（冻结，跨卡共享）
# ══════════════════════════════════════════════════════════════════════
def series_style_prefix(arch: Archetype | None, profile: ModelProfile,
                        style_zh: str = "") -> str:
    """推导**系列风格前缀** —— 同一系列的多张卡共用这一段，一个字都不改。

    来源（确定性的组合，保证「同系列名 → 同前缀」）：

    1. 档案自带的 ``prompt_prefix``（模型专属画质词）；
    2. ``Archetype.concept`` 里的中文风格词（走 :func:`zh_to_tags`）；
    3. 调用方显式给的 ``style_zh``；
    4. ``Archetype.binding.attribute`` 决定的色温氛围。

    >>> from cardforge.art.profiles import PROFILES            # doctest: +SKIP
    >>> series_style_prefix(None, PROFILES[0], "赛璐璐，逆光")  # doctest: +SKIP
    """
    parts: list[str] = []
    if profile.prompt_prefix:
        parts.append(profile.prompt_prefix.strip())
    tags: list[str] = []
    if arch is not None:
        tags += zh_to_tags(getattr(arch, "concept", "") or "")
        binding = getattr(arch, "binding", None) or {}
        attr = str(binding.get("attribute") or "")
        if attr in ATTRIBUTE_MOOD:
            tags.append(ATTRIBUTE_MOOD[attr][0])
    if style_zh:
        tags += zh_to_tags(style_zh)
    for t in tags:
        if t.lower() not in {p.lower() for p in parts}:
            parts.append(t)
    return ", ".join(p for p in parts if p)


# ══════════════════════════════════════════════════════════════════════
#  5. 负向词
# ══════════════════════════════════════════════════════════════════════
def normalize_negative(profile: ModelProfile, spec: CardSpec | None = None,
                       extra: str = "") -> str:
    """把「档案负向 ∪ 卡图负向 ∪ 卡种负向 ∪ 用户补充」去重后拼成一条。"""
    seen: set[str] = set()
    out: list[str] = []

    def push(blob: str) -> None:
        for item in str(blob or "").split(","):
            t = item.strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)

    push(profile.negative)
    push(NEGATIVE_CARD)
    if spec is not None:
        push(NEGATIVE_BY_FRAME.get(spec.frame, ""))
    push(extra)
    return ", ".join(out)


#: cfg<=1 时**改写进正向**的「排除意图」（因为负向不生效）
_EXCLUSION_POSITIVE = (
    "The frame contains absolutely no text, no lettering, no numbers, no signature, "
    "no watermark and no logo; there is no card border, no frame and no UI overlay; "
    "only one single subject is shown, centred, with clean empty space around it."
)

_EXCLUSION_POSITIVE_TAGS = (
    "no text, no watermark, no signature, no logo, no border, no frame, "
    "single subject only, centered, clean empty space"
)

#: **无主体**（背景 pass）用的版本：cfg<=1 时不能靠负向词排除人物，只能靠正向描述，
#: 而默认的「只有一个居中主体」会把人物又请回来 —— 背景 pass 必须换掉这句。
_EXCLUSION_POSITIVE_NOFIG = (
    "The frame contains absolutely no text, no lettering, no numbers, no signature, "
    "no watermark and no logo; there is no card border, no frame and no UI overlay; "
    "the scene is an empty environment with no characters and no creatures in it."
)

_EXCLUSION_NOFIG_TAGS = (
    "no text, no watermark, no signature, no logo, no border, no frame, "
    "empty scene, no characters, no creatures"
)


# ══════════════════════════════════════════════════════════════════════
#  6. 主入口
# ══════════════════════════════════════════════════════════════════════
def build(req: ArtRequest, spec: CardSpec | None, profile: ModelProfile,
          arch: Archetype | None = None, *, with_atmosphere: bool = True,
          with_composition: bool = True, head: str = "",
          subject_lead: str = "The subject of the artwork is:") -> dict:
    """把一次 :class:`ArtRequest` 编译成提示词。

    :param req: 出图请求（``subject`` / ``style`` / ``extra_positive`` /
        ``extra_negative`` / ``series_context``）。
    :param spec: 卡牌规格（决定卡种氛围词、属性色温、种族主体）；可为 ``None``。
    :param profile: 选中的模型档案（决定标签式还是自然语言）。
    :param arch: 系列圣经（提供系列风格前缀）。
    :param with_atmosphere: 关掉则不注入卡种氛围词。**背景 pass 必须关** ——
        氛围词是「这只生物如何发光」这类**主体导向**的句子，留着它背景图里
        就会自己长出个主体来。
    :param with_composition: 关掉则不注入「单主体居中、全身可见」的构图词。
    :param head: 放在**最前面**的一句。cfg<=1 的模型不吃负向词，而开头几个 token
        权重最高 —— 背景 pass 要靠它把「这是个没有人的空场景」钉住。
    :param subject_lead: 主体句的引导词。背景 pass 换成 "The setting of the
        artwork is:"，否则 "subject" 这个词本身就把人物请回来了。
    :return: ``{"positive": str, "negative": str, "style_tags": [...], "notes": str,
        "series_style": str, "structure": {...}}``

    返回的 ``positive`` 是**最终字符串**；``structure`` 是逐槽位拆解，
    便于 UI 展示「哪一段是哪来的」。
    """
    notes: list[str] = []
    natural = bool(profile.natural_language)

    # ── 风格前缀（系列冻结）──
    ctx = dict(getattr(req, "series_context", None) or {})
    frozen = str(ctx.get(SERIES_STYLE_KEY) or "")
    if frozen:
        style_prefix = frozen
        notes.append(f"使用系列冻结风格前缀（{SERIES_STYLE_KEY}）：{frozen}")
    else:
        style_prefix = series_style_prefix(arch, profile, req.style)
        if arch is not None:
            notes.append(f"由系列「{arch.name}」推导风格前缀；"
                         f"把它写进 ArtRequest.series_context['{SERIES_STYLE_KEY}'] "
                         "即可在后续卡上完全冻结。")

    # ── 主体 ──
    subject = str(req.subject or "").strip()
    if not subject and spec is not None:
        subject = spec.display_name or spec.name or ""
        notes.append("未给主体描述 → 回落到卡名当主体。")
    subj_tags: list[str] = []
    if spec is not None:
        hint = RACE_HINT.get(spec.race or "")
        if hint:
            subj_tags.append(hint)
        if spec.is_monster:
            subj_tags.append("solo, 1monster")
        mood = ATTRIBUTE_MOOD.get(spec.attribute or "")
        if mood:
            subj_tags.append(mood[0])
    subject_tags = zh_to_tags(subject) if subject else []
    un = unmatched_terms(subject) if subject else []
    if un:
        notes.append("主体描述里这些中文词没命中内置词典，**已被丢弃**（不会进提示词，"
                     "因为提示词必须是英文）。请把它们换成更常见的词，或直接写英文标签："
                     + "、".join(un))
    # 提示词里**绝不放中文原文**：中文只在 notes 里回显给用户看。
    # 要送进模型的主体一律用「词典命中的英文标签」拼出来。
    subject_en = ", ".join(subject_tags) if subject_tags else ""

    # ── 卡种氛围 ──
    frame_key = str(getattr(spec, "frame", "") or "effect") if spec is not None else "effect"
    atm_tags, atm_sentence = frame_atmosphere(frame_key)

    # ── 构图词（卡图窗比例、单主体居中、留白）──
    # 窗比例来自 FRAMES[...].art_ratio（实测：标准框=正方形 1.0004，灵摆合并窗=0.7788）
    ratio = 1.0004
    if spec is not None:
        try:
            ratio = float(spec.art_ratio) or 1.0004
        except Exception:
            ratio = 1.0004
    landscape = ratio >= 1.15          # 只有横窗才说 wide
    orient = ("wide" if landscape else
              "square" if 0.85 <= ratio <= 1.15 else "portrait")
    comp_tags = ("centered composition, single subject, full body visible, "
                 f"{orient} orientation {ratio:.4f} aspect ratio, "
                 "ample empty space around the subject")
    comp_sentence = (
        "The composition is a single centred subject framed for a "
        + ("wide" if landscape else "square" if orient == "square" else "tall")
        + f" trading-card artwork window (aspect ratio {ratio:.4f}), with the whole "
        "figure inside the frame and generous empty space around it so nothing is "
        "cut off by the window edge."
    )

    # ── 光照词 ──
    light_tags = "dramatic lighting, rim light, volumetric light, high contrast, vibrant colors"
    light_sentence = (
        "Lighting is dramatic and cinematic, with a strong rim light separating the "
        "subject from the background, volumetric haze in the air and a vibrant, "
        "high-contrast colour finish."
    )
    if not with_composition:
        # 背景底板没有主体，"把主体从背景里分离出来的轮廓光"这句会自己请出一个人来
        light_tags = ("dramatic atmospheric lighting, volumetric light shafts, "
                      "god rays, high contrast, vibrant colors")
        light_sentence = (
            "Lighting is dramatic and cinematic: volumetric light shafts falling "
            "through the empty space, haze in the air and a vibrant, high-contrast "
            "colour finish over the unoccupied scene."
        )

    # ── 组装 ──
    style_tags = [t for t in (style_prefix.split(", ") if style_prefix else []) if t]
    # 自然语言范式下前缀已经是首句，后面**不再重复一段 Style/Rendering notes** ——
    # 实测那样会把提示词从 ~230 词吹到 300+ 词，而调研结论是稠密 caption 的
    # 最佳区间约 150–230 词，超了只会稀释主体。style_tags 仍然返回给 UI 展示。
    technique_tags: list[str] = []
    if natural:
        chunks: list[str] = []
        if head:
            chunks.append(head.rstrip(".") + ".")
        if style_prefix:
            chunks.append(style_prefix.rstrip(".") + ".")
        if subject_en:
            chunks.append(f"{subject_lead} {subject_en}.")
        elif subject:
            # 词典完全没命中（例如写了纯生僻词）→ 明确告知，而不是把中文丢进去
            chunks.append("The subject of the artwork is a single fantasy creature "
                          "presented as a duel-monster card illustration.")
        if subj_tags:
            chunks.append("It is depicted as " + ", ".join(subj_tags) + ".")
        if with_atmosphere:
            chunks.append(atm_sentence)
        if with_composition:
            chunks.append(comp_sentence)
        chunks.append(light_sentence)
        positive_parts = [" ".join(chunks)]
    else:
        pos_items: list[str] = []
        if head:
            pos_items.append(head.rstrip(".") + ".")
        if style_prefix:
            pos_items.append(style_prefix)
        if subj_tags:
            pos_items.append(", ".join(subj_tags))
        if subject_en:
            pos_items.append(subject_en)
        if with_atmosphere:
            pos_items.append(atm_tags)
        if with_composition:
            pos_items.append(comp_tags)
        pos_items.append(light_tags)
        positive_parts = [", ".join(x for x in pos_items if x)]

    if req.extra_positive:
        positive_parts.append(str(req.extra_positive).strip())

    # ── cfg<=1：把「排除意图」改写进正向 ──
    if not profile.negative_effective:
        if with_composition:
            positive_parts.append(_EXCLUSION_POSITIVE if natural else _EXCLUSION_POSITIVE_TAGS)
        else:
            positive_parts.append(_EXCLUSION_POSITIVE_NOFIG if natural else _EXCLUSION_NOFIG_TAGS)
        notes.append(
            f"档案 {profile.key} 的 cfg={profile.cfg}（蒸馏少步模型）→ **负向提示词基本不生效**"
            "（那一遍前向不跑）。已把「不要文字/水印/边框、只要单主体居中」改写成**正向描述**"
            "追加到末尾；negative 字段仍返回，供你把 cfg 调高时使用。"
        )

    positive = ("" if natural else ", ".join(p for p in positive_parts if p))
    if natural:
        positive = " ".join(p for p in positive_parts if p)

    negative = normalize_negative(profile, spec, req.extra_negative)
    if not profile.negative_effective:
        notes.append(f"负向共 {len(negative.split(','))} 个词，但在 cfg={profile.cfg} 下不参与计算。")

    notes.append(f"提示词范式：{profile.prompt_style}"
                 + ("（自然语言长句）" if natural else "（标签堆叠，画质词在最前）"))
    if arch is not None and not frozen:
        notes.append(f"系列一致性：把下面这段写进 series_context['{SERIES_STYLE_KEY}'] "
                     "可以完全冻结整个系列的画风 —— 这是零额外模型、见效最快的一致性手段"
                     "（照调研结论约占 60% 效果）。")

    return {
        "positive": positive,
        "negative": negative,
        "style_tags": style_tags,
        "notes": "\n".join(notes),
        "series_style": style_prefix,
        "structure": {
            "style_prefix": style_prefix,
            "subject": subject,
            "subject_tags": subj_tags + subject_tags,
            "frame_atmosphere": atm_tags if not natural else atm_sentence,
            "composition": comp_tags if not natural else comp_sentence,
            "lighting": light_tags if not natural else light_sentence,
            "extra_positive": str(req.extra_positive or ""),
            "natural_language": natural,
        },
    }


# ══════════════════════════════════════════════════════════════════════
#  7. 分层出图（背景 + 主体两次生成）
# ══════════════════════════════════════════════════════════════════════
#: 背景 pass 的**开场句**（放在最前面）。本机 Krea2 档案 cfg=1.0 → 负向词不参与
#: 计算，只靠末尾的 "no characters" 压不住模型"画个人"的默认倾向（实测真的又长出
#: 一个白发法师）。开头几个 token 权重最高，所以把「这是一张没有人的空场景底板」
#: 当成主题来陈述，而不是当成排除项来补充。
_BG_HEAD = ("This is an empty background plate: an unoccupied location with no people, "
            "no characters, no creatures and no figures of any kind anywhere in it")
#: 背景 pass：明确排除任何主体，并要"环境概念图"的观感
_BG_POS = ("empty scene, background art only, environment concept art, "
           "wide establishing shot, depth and atmosphere, no focal character")
_BG_NEG = ("character, creature, person, monster, humanoid, animal, figure, "
           "protagonist, crowd, silhouette, text, watermark, signature")
#: 主体 pass：纯色底 + 全身完整，方便抠底与"只让主体出框"
_SUBJ_POS_TMPL = ("solo, full body, entire body visible, head to feet, "
                  "isolated on a plain solid {bg} background, flat uniform backdrop, "
                  "no scenery, no environment, sharp clean silhouette, "
                  "generous margin around the subject")
_SUBJ_NEG = ("background, scenery, landscape, environment, room, sky, ground, "
             "shadow on background, reflection, cropped, out of frame, "
             "partial body, close-up, multiple subjects, text, watermark")


def build_layers(req: ArtRequest, spec: CardSpec | None, profile: ModelProfile,
                 arch: Archetype | None = None) -> dict:
    """把一次请求拆成**背景 pass** 与**主体 pass** 两套提示词。

    为什么要拆：出框时只想让**主体**越出卡图窗，背景仍然严实地留在窗内。
    一张扁平的整图做不到这件事 —— 必须让主体带 alpha 通道单独成层。

    * 背景 pass：``spec=None`` 走 :func:`build`，避免把种族/「solo, 1monster」
      这类主体标签带进去；卡种氛围词手工补回来。
    * 主体 pass：保留全部主体语义与风格前缀，追加"纯色底 + 全身 + 四周留白"，
      交给 :func:`cardforge.art.graph.build_t2i` 的 ``remove_bg`` 抠底。
      留白是必须的：抠完还要放大压出窗沿，主体贴边就没得溢出。

    :return: ``{"background": {...}, "subject": {...}, "cutout_bg": str,
        "positive": str, "negative": str, "style_tags": [...],
        "series_style": str, "notes": str, "structure": {...}}``
        —— 顶层的 ``positive``/``negative`` 是**背景 pass** 的，仅为兼容
        按单图读取的老调用方。
    """
    from dataclasses import replace as _replace

    frame_key = str(getattr(spec, "frame", "") or "effect") if spec is not None else "effect"
    cut_bg = str(getattr(req, "cutout_bg", "") or "").strip() or "grey"

    # ── 背景 pass：不带卡种氛围词与单主体构图词（那两句都是主体导向的）──
    bg_subject = str(getattr(req, "background", "") or "").strip()
    if not bg_subject:
        bg_subject = "fantasy environment"
    bg_pos = ", ".join(x for x in (_BG_POS, str(req.extra_positive or "")) if x)
    req_bg = _replace(req, subject=bg_subject, style=str(req.style or ""),
                      extra_positive=bg_pos,
                      extra_negative=", ".join(x for x in (_BG_NEG, str(req.extra_negative or "")) if x))
    pr_bg = build(req_bg, None, profile, arch,
                  with_atmosphere=False, with_composition=False,
                  head=_BG_HEAD, subject_lead="The setting of the artwork is:")

    # ── 主体 pass ──
    sub_pos = ", ".join(x for x in (_SUBJ_POS_TMPL.format(bg=cut_bg),
                                    str(req.extra_positive or "")) if x)
    req_sub = _replace(req, extra_positive=sub_pos,
                       extra_negative=", ".join(x for x in (_SUBJ_NEG, str(req.extra_negative or "")) if x))
    pr_sub = build(req_sub, spec, profile, arch)

    notes = [
        "分层出图：背景与主体分两次生成，主体抠底成带 alpha 的独立层；"
        "出框时只有主体越出卡图窗，背景严格留在窗内。",
        f"主体 pass 用「{cut_bg}」纯色底（抠底更稳）；背景 pass 已排除任何主体。",
    ]
    if str(req.style or "").strip():
        notes.append("两个 pass 共用同一风格前缀"
                     + ("（系列已冻结）" if pr_bg.get("series_style") else "")
                     + "，光照与笔触一致性靠它 + 同档案同 seed 家族保证。")
    notes.append(pr_bg["notes"])
    notes.append(pr_sub["notes"])

    return {
        "background": pr_bg,
        "subject": pr_sub,
        "cutout_bg": cut_bg,
        # 兼容按单图读的调用方
        "positive": pr_bg["positive"],
        "negative": pr_bg["negative"],
        "style_tags": pr_bg["style_tags"],
        "series_style": pr_bg["series_style"],
        "notes": "\n".join(x for x in notes if x),
        "structure": {"background": pr_bg["structure"], "subject": pr_sub["structure"]},
    }
