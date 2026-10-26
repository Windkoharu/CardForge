"""卡图**提示词模板** —— 12 套正统类型母题，点一下就填好表单。

为什么要有这个文件
------------------
「主体（画什么）」是一个空文本框，从零开始写对不画画的人最难。模板把
**官方卡图长期沉淀下来的类型惯例**做成可选项：只借结构（单主体、一个视点、
一个光源、一处最亮、环境为角色服务），**不自创设定**（不替你编名字、阵营、世界观）。

三条硬规定
----------
1. **每套模板都自带中文版与英文版**（``subject_zh`` / ``subject_en``）。
   哪一版进表单，由档案的 ``bilingual_text_encoder`` 决定 ——
   Krea 2 / Qwen-Image 用中文（原话直送），animagine / pony 一类英文词表 CLIP
   用英文标签。这是上一轮「提示词不符合输入」教训的直接产物。
2. **每套只讲一个视点、一个主光源、一处最亮**。信息堆在一张画里就会变成
   「无聊的设定图」，卡图窗只有那么大。
3. 模板**不锁死任何数值**：填进表单后所有字段仍可自由改，
   「预览工作流」仍然逐字对账（模板给的话和你说出去的话是同一条链）。

``recommend(spec)`` 按卡面规格（卡种 / 属性 / 种族）打分排序，
把最贴合的母题顶到下拉框最前面 —— 但**只是排序，不是替你决定**。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

__all__ = ["PromptTemplate", "TEMPLATES", "BY_KEY", "list_all", "get",
           "recommend", "as_form", "user_path", "load_user", "save_user",
           "delete_user"]


@dataclass(frozen=True)
class PromptTemplate:
    """一套可直接填进出图表单的提示词模板。"""

    key: str
    zh: str
    #: 分组（界面按组折叠）：怪兽 / 魔陷 / 通用
    group: str = "怪兽"
    #: 一句话说明这套母题在画什么（给下拉框的提示）
    use: str = ""
    subject_zh: str = ""
    subject_en: str = ""
    style_zh: str = ""
    style_en: str = ""
    background_zh: str = ""
    background_en: str = ""
    extra_positive: str = ""
    extra_negative: str = ""
    #: 建议工作流：t2i_single / t2i_layers（要出框的选分层）
    preset: str = "t2i_single"
    #: 建议主体纯色底（分层出图用；亮色主体别用白底）
    cutout_bg: str = "grey"
    #: recommend() 打分用：命中卡种/属性/种族关键词各加分
    match_frames: tuple[str, ...] = ()
    match_attributes: tuple[str, ...] = ()
    match_races: tuple[str, ...] = ()
    #: 为什么这么写（界面「详情」里给一句人话）
    note: str = ""
    tags: tuple[str, ...] = ()
    custom: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════
#  12 套正统母题
# ══════════════════════════════════════════════════════════════════════
# 说明：中文版写给 Qwen 系编码器（原话直送），英文版写给 CLIP（标签堆叠）。
# 两边语义**一一对应**，不是互不相同的两套画。
TEMPLATES: tuple[PromptTemplate, ...] = (
    # ── 1. 持械骑士（战士族正统）──
    PromptTemplate(
        key="knight",
        zh="持械骑士 · 正面登场",
        group="怪兽",
        use="战士族最正统的一张画：单人、正面向镜头、武器是唯一的亮处。",
        subject_zh="一名全身白银铠甲的骑士，正面朝向镜头站立，右手斜持长枪，"
                   "铠甲胸口有一处十字形纹章，披风被风向右后方掀起，"
                   "神情沉静，视线正对观者",
        subject_en="a single knight in full silver plate armour, standing facing the "
                   "camera, holding a lance diagonally across the body, cross crest on "
                   "the breastplate, cape blown back to the right, calm expression, "
                   "eyes meeting the viewer",
        style_zh="赛璐璐上色，干净硬边线条，金属高光集中在胸甲一处",
        style_en="cel shading, clean hard lineart, one concentrated metallic highlight "
                 "on the breastplate",
        background_zh="黄昏的石桥与远处城堡剪影，天空有大片暖色云，人物背后留干净空间",
        background_en="stone bridge and distant castle silhouette at golden hour, "
                      "broad warm clouds, clean space behind the figure",
        extra_positive="", extra_negative="",
        preset="t2i_single", cutout_bg="grey",
        match_frames=("effect", "fusion", "synchro", "xyz", "normal"),
        match_attributes=("光", "炎", "地"),
        match_races=("战士族",),
        note="一个视点（正对镜头）、一个光源（侧后暖阳）、一处最亮（胸甲高光）——"
             "骑士题材最稳的读法；武器斜置能带出纵深，不会挡脸。",
        tags=("单主体", "正面", "武器"),
    ),

    # ── 2. 巨龙（龙族正统）──
    PromptTemplate(
        key="dragon",
        zh="巨龙 · 盘踞吐息",
        group="怪兽",
        use="龙族卡图的经典三态之一：盘踞 + 张口蓄能，亮处在喉腔。",
        subject_zh="一头巨大的红鳞西方龙，双翼完全展开，长颈向下扭转，"
                   "张口朝镜头蓄聚一团炽白光球，牙齿与口腔内部是画面最亮处，"
                   "鳞片边缘被自身的光映出暖色反光",
        subject_en="an enormous red-scaled western dragon, wings fully spread, long neck "
                   "twisted downward, jaws open toward the camera gathering a blazing "
                   "white orb of breath, teeth and the inside of the mouth as the "
                   "brightest point, scale rims lit warm by its own glow",
        style_zh="厚涂与硬边结合，鳞片层次清晰，暖色高对比",
        style_en="painterly with crisp edges, clearly layered scales, warm high contrast",
        background_zh="火山岩柱与熔岩裂缝的暗色洞窟，光只从龙口一处来，背景压暗",
        background_en="dark volcanic cavern with basalt columns and lava cracks, "
                      "light coming only from the dragon's maw, background kept dark",
        preset="t2i_layers", cutout_bg="grey",
        match_frames=("effect", "fusion", "synchro", "ritual", "link"),
        match_attributes=("炎", "暗", "光"),
        match_races=("龙族", "幻龙族"),
        note="把唯一光源放在龙口，观众视线必然落到吐息上；背景压暗是官方龙族卡图"
             "最常用的手法（对比之下主体自然破框）。选「分层出图」方便后续主体出框。",
        tags=("单主体", "自发光", "出框友好"),
    ),

    # ── 3. 咒术师（魔法师族）──
    PromptTemplate(
        key="spellcaster",
        zh="咒术师 · 法阵咏唱",
        group="怪兽",
        use="魔法师族正统：施法姿态 + 一个法阵，亮处在法阵核心。",
        subject_zh="一位身着深蓝长袍的咒术师，侧身四分之三角度，单手高举过头，"
                   "指尖下方悬浮一枚发光的圆形魔法阵，法阵中心是画面唯一强光源，"
                   "袍角与头发被魔力向上扬起",
        subject_en="a mage in a deep blue robe seen from three quarters, one arm raised "
                   "overhead, a glowing circular magic sigil floating below the "
                   "fingertips, the centre of the sigil as the single strong light "
                   "source, robe hems and hair lifted upward by magic",
        style_zh="赛璐璐上色，冷色底 + 单一暖色光源，光晕柔和",
        style_en="cel shading, cool base palette with one warm light source, soft bloom",
        background_zh="废弃图书馆与漂浮的书页，暗部保留细节但不抢主体",
        background_en="ruined library with floating pages, shadows keep detail but "
                      "never compete with the subject",
        preset="t2i_single", cutout_bg="black",
        match_frames=("effect", "ritual", "link", "fusion"),
        match_attributes=("暗", "光", "水"),
        match_races=("魔法师族",),
        note="法阵是「一个亮点」的最好载体；人物用四分之三侧身比正面更有动势。"
             "深色袍子配黑底更利于抠底。",
        tags=("单主体", "法阵", "施法"),
    ),

    # ── 4. 天使 / 光属性 ──
    PromptTemplate(
        key="angel",
        zh="天使 · 逆光降临",
        group="怪兽",
        use="光属性正统：从上方来的一束光 + 白翼，亮处在头部光环。",
        subject_zh="一位白色长裙的天使，六片羽翼向上收拢，身体微微悬浮离开地面，"
                   "仰头望向正上方落下的一道光柱，头顶光环是画面最亮处，"
                   "面部被光半遮",
        subject_en="an angel in a long white dress, six wings drawn upward, body "
                   "floating slightly off the ground, head tilted toward a single shaft "
                   "of light falling from above, the halo above the head as the "
                   "brightest point, face half lit",
        style_zh="柔和体积光，浅色低饱和，边缘干净",
        style_en="soft volumetric light, pale desaturated palette, clean edges",
        background_zh="破碎的石质神殿与漂浮的碎石，背景整体偏冷灰，只有光柱是暖白",
        background_en="broken stone temple with floating debris, cold grey background, "
                      "only the light shaft is warm white",
        preset="t2i_layers", cutout_bg="grey",
        match_frames=("effect", "fusion", "synchro", "xyz"),
        match_attributes=("光",),
        match_races=("天使族",),
        note="白色主体**不要**用白底（抠底会抠空），灰底最稳。光柱给出唯一视点，"
             "顺带把「降临」这个动作交代清楚。",
        tags=("悬浮", "逆光", "出框友好"),
    ),

    # ── 5. 恶魔 / 暗属性 ──
    PromptTemplate(
        key="fiend",
        zh="恶魔 · 王座俯视",
        group="怪兽",
        use="暗属性正统：俯视镜头 + 单一红色点光源。",
        subject_zh="一名生有弯曲双角、皮肤暗红的恶魔领主，坐于黑石王座上，"
                   "身体前倾，一只手肘支在膝上，掌心浮着一团暗红火苗，"
                   "镜头从低处仰拍使其显得巨大，火苗是唯一光源",
        subject_en="a horned fiend lord with dark red skin seated on a black stone "
                   "throne, leaning forward, one elbow on the knee, a small dark-red "
                   "flame floating in the palm, low camera angle looking up to make the "
                   "figure loom, the flame as the only light source",
        style_zh="厚涂暗调，强明暗对照，边缘有细微体积雾",
        style_en="dark painterly rendering, strong chiaroscuro, faint volumetric haze",
        background_zh="几乎全黑的大殿，只有几根柱子的轮廓被火光擦过",
        background_en="near-black hall, firelight grazing only the outline of a few columns",
        preset="t2i_single", cutout_bg="black",
        match_frames=("effect", "fusion", "xyz", "link"),
        match_attributes=("暗",),
        match_races=("恶魔族",),
        note="仰拍 + 单点光是「压迫感」最省 token 的写法；背景越暗主体越跳。"
             "暗色主体配黑底抠底最稳。",
        tags=("仰视", "暗调", "单光源"),
    ),

    # ── 6. 机械族 ──
    PromptTemplate(
        key="machine",
        zh="机械巨人 · 启动瞬间",
        group="怪兽",
        use="机械族正统：硬表面 + 一处发光核心，冷色底。",
        subject_zh="一台白色与钢灰配色的巨型人型机械，胸口的圆形反应堆发出青蓝色光，"
                   "是画面唯一亮处，装甲板正在向两侧滑开露出内部结构，"
                   "镜头略低于胸部平视，双臂自然下垂",
        subject_en="a colossal humanoid machine in white and steel grey, a circular "
                   "reactor in the chest glowing cyan-blue as the only bright point, "
                   "armour panels sliding open to reveal inner structure, camera just "
                   "below chest height, arms relaxed at the sides",
        style_zh="硬表面机械结构，干净线条，金属反射克制，青蓝单色光",
        style_en="hard-surface mechanical detail, clean lines, restrained metal "
                 "reflections, single cyan light",
        background_zh="简洁的机库或轨道平台背景，虚化，不出现文字与标识",
        background_en="clean hangar or orbital platform backdrop, defocused, "
                      "no text and no markings",
        preset="t2i_layers", cutout_bg="grey",
        match_frames=("effect", "fusion", "synchro", "link", "xyz"),
        match_attributes=("光", "地", "风"),
        match_races=("机械族",),
        note="机械题材最容易画成「设定图」——所以只留一处发光核心、只讲一个动作"
             "（装甲滑开）。背景虚化且明确不要标识文字。",
        tags=("硬表面", "单色光", "出框友好"),
    ),

    # ── 7. 不死族 ──
    PromptTemplate(
        key="undead",
        zh="不死军团 · 破土而出",
        group="怪兽",
        use="不死族正统：一个主体 + 少量陪衬，冷绿单光源。",
        subject_zh="一具披残破铠甲的骷髅战士从泥地中向上伸出骨手，镜头贴近地面仰拍，"
                   "背景雾气中隐约另有数只手臂但**不清晰**，"
                   "唯一的青绿色冷光打在伸出的骨手上，它是画面唯一亮处",
        subject_en="an armoured skeleton clawing upward out of muddy ground, camera at "
                   "ground level looking up, several more arms blurred in the fog behind "
                   "but not in focus, a single cold green light falling on the raised "
                   "bone hand as the only bright point",
        style_zh="厚涂，低饱和冷色，泥土与骨白质感对比",
        style_en="painterly, desaturated cold palette, contrast between mud and bone white",
        background_zh="荒坟与枯树剪影，浓雾，远处无细节",
        background_en="barren graves and leafless tree silhouettes in dense fog, "
                      "no detail in the distance",
        preset="t2i_single", cutout_bg="black",
        match_frames=("effect", "fusion", "xyz"),
        match_attributes=("暗",),
        match_races=("不死族",),
        note="官方不死族卡图常见「一主多次」，陪衬必须虚化，否则卡图窗里会读成乱。",
        tags=("低机位", "冷光", "雾气"),
    ),

    # ── 8. 水族 ──
    PromptTemplate(
        key="aqua",
        zh="深海巨兽 · 上浮逼近",
        group="怪兽",
        use="水族正统：水下纵深 + 上方天光，亮处在眼部或生物光。",
        subject_zh="一头巨大的深海海兽正向上浮向镜头，身体斜向穿过画面，"
                   "体表有数点青蓝色生物发光，眼睛是画面最亮处，"
                   "上方有微弱的天光透下来形成光柱",
        subject_en="a vast deep-sea leviathan rising toward the camera, body cutting "
                   "diagonally across the frame, several cyan bioluminescent spots on "
                   "its skin, the eye as the brightest point, faint daylight from far "
                   "above forming light shafts",
        style_zh="水下体积光，蓝绿单色渐变，悬浮颗粒细节",
        style_en="underwater volumetric light, blue-green gradient, suspended particles",
        background_zh="下方是深不见底的暗蓝，无任何文字与标识",
        background_en="bottomless dark blue below, no text and no markings",
        preset="t2i_layers", cutout_bg="black",
        match_frames=("effect", "fusion", "link", "xyz"),
        match_attributes=("水",),
        match_races=("水族", "鱼族"),
        note="斜向穿框能造出纵深，是水族/龙类共用的构图套路；"
             "深色主体配黑底抠底最稳。",
        tags=("水下", "斜向构图", "出框友好"),
    ),

    # ── 9. 雷族 ──
    PromptTemplate(
        key="thunder",
        zh="雷兽 · 落雷瞬间",
        group="怪兽",
        use="雷族正统：一道闪电作为唯一光源与唯一动势。",
        subject_zh="一头覆盖钢毛的雷兽四足踏在碎裂岩石上，身体弓起，鬃毛因静电根根竖起，"
                   "一道白色闪电从其背后劈落，是整个画面的唯一光源，"
                   "镜头略仰，主体边缘被电光勾出亮边",
        subject_en="a beast of metallic fur planted on shattered rock, back arched, "
                   "mane standing on end from static, a single white lightning bolt "
                   "striking behind it as the only light source, slightly low camera "
                   "angle, rim lit by the discharge",
        style_zh="高对比硬光，冷紫底色 + 白色电光，动感线条",
        style_en="high contrast hard light, cold violet base with white electricity, "
                 "dynamic lines",
        background_zh="暴风雨中的黑色岩山，雨丝被电光照亮",
        background_en="black rocky mountains in a storm, rain streaks lit by the flash",
        preset="t2i_single", cutout_bg="black",
        match_frames=("effect", "synchro", "link"),
        match_attributes=("雷",),
        match_races=("雷族", "雷"),
        note="雷族只有「落雷的瞬间」最好读；把闪电写成唯一光源，避免整画面糊成一片白。",
        tags=("硬光", "静帧动势", "兽四足"),
    ),

    # ── 10. 幻龙族 / 兽族荒野 ──
    PromptTemplate(
        key="beast",
        zh="荒野巨兽 · 侧影巡视",
        group="怪兽",
        use="兽族/幻龙族正统：宽景 + 单一主体剪影，暖色低太阳。",
        subject_zh="一头长角的大型荒野巨兽以完整侧影站在崖边，头转向镜头方向，"
                   "身体大面积处于逆光剪影中，只有背部轮廓与角的边缘被落日勾亮，"
                   "画面下方留出草原与雾的呼吸空间",
        subject_en="a large horned beast of the wilds in full profile on a cliff edge, "
                   "head turned toward the viewer, body mostly in backlit silhouette "
                   "with only the spine and horn edges rim-lit by the low sun, "
                   "grassland and mist left open below",
        style_zh="电影感宽画幅，暖橙逆光，轮廓清晰",
        style_en="cinematic wide framing, warm orange backlight, crisp silhouette",
        background_zh="层叠远山与低云，太阳贴近地平线，无任何文字",
        background_en="layered distant ridges under low clouds, sun near the horizon, "
                      "no text",
        preset="t2i_layers", cutout_bg="grey",
        match_frames=("effect", "fusion", "ritual"),
        match_attributes=("地", "风"),
        match_races=("兽族", "兽战士族", "幻龙族", "恐龙族"),
        note="逆光剪影是「气势」最稳的做法：细节少但形状强，缩小到卡图窗里仍读得清。",
        tags=("宽景", "剪影", "出框友好"),
    ),

    # ── 11. 魔法卡场景 ──
    PromptTemplate(
        key="spell_scene",
        zh="魔法卡 · 无人场景",
        group="魔陷",
        use="魔法卡正统：**画面里没有人**，一个发光物承担叙事。",
        subject_zh="一张空无一人的场景：石质祭坛中央悬浮一枚缓慢旋转的水晶，"
                   "地面刻有同心圆法阵，光是从水晶这一处发出的，它是画面唯一亮处，"
                   "空气中漂浮细小光点，没有任何人物与生物",
        subject_en="an unoccupied scene: a crystal slowly rotating above a stone altar, "
                   "concentric magic circles engraved on the floor, light coming only "
                   "from the crystal as the single bright point, tiny motes drifting in "
                   "the air, no people and no creatures",
        style_zh="环境概念图，宽景，冷暖对置，细节集中在祭坛",
        style_en="environment concept art, wide establishing shot, warm/cool contrast, "
                 "detail concentrated on the altar",
        background_zh="周围是暗色遗迹与断柱，远处雾化，无任何文字与符号说明",
        background_en="dark ruins and broken columns around, distance dissolving into "
                      "mist, no text and no labels",
        extra_positive="", extra_negative="character, person, creature, silhouette",
        preset="t2i_single", cutout_bg="grey",
        match_frames=("spell",),
        match_attributes=(), match_races=(),
        note="魔法卡的负向里内核已经自动排除了「monster, character, person」"
             "（按卡种追加），这里再补一层是双保险：cfg≤1 的档案负向不生效，"
             "必须靠正向说清「这是张没有人的空场景」。",
        tags=("无人", "环境", "单光源"),
    ),

    # ── 12. 陷阱卡场景 ──
    PromptTemplate(
        key="trap_scene",
        zh="陷阱卡 · 伏击瞬间",
        group="魔陷",
        use="陷阱卡正统：一个动作的瞬间，暗部占大半画面。",
        subject_zh="一张没有主要人物的伏击瞬间：画面前景是骤然绷紧的锁链与机关齿轮，"
                   "中景一名模糊的对手剪影正被缠住并向后失衡，"
                   "光只照亮锁链的金属边缘，其余部分沉在暗部",
        subject_en="an ambush caught mid-instant: taut chains and trap gears filling the "
                   "foreground, a blurred opposing silhouette bound and losing balance in "
                   "the middle ground, light only on the metal edges of the chains, "
                   "everything else sunk in shadow",
        style_zh="强明暗对照，冷灰主调 + 一处锈红，边缘锐利",
        style_en="strong chiaroscuro, cold grey with one rust accent, sharp edges",
        background_zh="昏暗石室与散落的碎石，无文字与标识",
        background_en="dim stone chamber with scattered rubble, no text and no markings",
        preset="t2i_single", cutout_bg="grey",
        match_frames=("trap",),
        match_attributes=(), match_races=(),
        note="陷阱卡要画「瞬间」而不是「场景」：前景机关 + 中景反应，视线一次走完。"
             "注意别把主体写成一个人 —— 内核会给陷阱卡追加排除人物的负向。",
        tags=("无人", "瞬间", "暗调"),
    ),
)

BY_KEY: dict[str, PromptTemplate] = {t.key: t for t in TEMPLATES}

#: 用户自定义模板落盘位置（workspace 内，跟着项目走，不进代码库）
USER_FILE = "art_templates.json"


# ══════════════════════════════════════════════════════════════════════
#  查询与推荐
# ══════════════════════════════════════════════════════════════════════
def get(key: str) -> Optional[PromptTemplate]:
    """按 key 取模板（含用户自存模板）。"""
    k = str(key or "").strip()
    if not k:
        return None
    if k in BY_KEY:
        return BY_KEY[k]
    for t in load_user():
        if t.key == k:
            return t
    return None


def list_all(root: Path | str = "") -> list[PromptTemplate]:
    """内置 12 套 + 用户自存（同名时用户版在后，界面上分组显示）。"""
    return list(TEMPLATES) + load_user(root)


def recommend(spec: Any) -> list[tuple[str, int]]:
    """按卡面规格给模板打分排序，返回 ``[(key, score), ...]``（分高的在前）。

    加分项（确定性，不看心情）：卡种命中 +6、属性命中 +3、种族命中 +5、
    「分层出图」友好再加 +1。分数为 0 的模板**仍然返回**（排在后面）——
    推荐只是排序，不是替他删选项。

    两个坑本轮踩过：
    * **种族不能做子串匹配** —— ``"战士族" in "兽战士族"`` 为真，
      于是战士族的卡会把「荒野巨兽」顶到「持械骑士」前面；
    * **魔法 / 陷阱卡没有种族与属性** —— ``CardSpec`` 的字段默认值是
      ``战士族 / 暗``，魔陷卡照它打分纯属噪声，必须先排除掉。
    """
    frame = str(getattr(spec, "frame", "") or "")
    has_race_attr = frame not in ("spell", "trap")
    attr = str(getattr(spec, "attribute", "") or "") if has_race_attr else ""
    race = str(getattr(spec, "race", "") or "") if has_race_attr else ""
    rows: list[tuple[str, int]] = []
    for t in list_all():
        s = 0
        if frame and frame in t.match_frames:
            s += 6
        if attr and attr in t.match_attributes:
            s += 3
        if race and any(str(r).strip() == race.strip() for r in t.match_races):
            s += 5
        if s == 0 and frame in ("spell", "trap") and t.group == "魔陷":
            s += 2                      # 魔陷至少把魔陷模板排在前面
        if s and t.preset == "t2i_layers":
            s += 1                      # 有戏的模板里，出框友好的再抬半格
        rows.append((t.key, s))
    rows.sort(key=lambda x: (-x[1], x[0]))
    return rows


def as_form(tpl: PromptTemplate, *, bilingual: bool = True,
            name: str = "") -> dict:
    """把模板摊平成出图表单的字段值。

    :param bilingual: True（Krea 2 / Qwen-Image）取中文版 —— **原话直送**；
        False（英文词表 CLIP）取英文版标签。
    :param name: 卡名。给了就把它并进主体开头，避免模板与卡名两张皮。
    """
    def pick(zh: str, en: str) -> str:
        return (zh if bilingual else en) or ""

    subject = pick(tpl.subject_zh, tpl.subject_en)
    if name and name not in subject:
        subject = f"{name}：{subject}" if bilingual else f"{name}, {subject}"
    return {
        "subject": subject,
        "style": pick(tpl.style_zh, tpl.style_en),
        "background": pick(tpl.background_zh, tpl.background_en),
        "extra_positive": tpl.extra_positive,
        "extra_negative": tpl.extra_negative,
        "preset": tpl.preset,
        "cutout_bg": tpl.cutout_bg,
        "layers": tpl.preset == "t2i_layers",
        "key": tpl.key,
        "zh": tpl.zh,
        "bilingual": bool(bilingual),
        "note": tpl.note,
    }


# ══════════════════════════════════════════════════════════════════════
#  用户自存模板（workspace/art_templates/art_templates.json）
# ══════════════════════════════════════════════════════════════════════
def user_path(root: Path | str = "") -> Path:
    try:
        from ..core import paths
        base = Path(root) if root else Path(paths.WORKSPACE)
    except Exception:                                   # noqa: BLE001
        base = Path(root) if root else Path("workspace")
    return base / "art_templates" / USER_FILE


#: 只清掉**路径与 URL 不安全**的字符；中文名一律保留 ——
#: 早先用 `[^a-z0-9_-]` 做白名单，结果「圣痕·龙骑士」和「星奏·前哨」
#: 都被压成同一个 key `template`，第二个会把第一个**静默覆盖**。
_UNSAFE_RE = re.compile(r"""[\s/\\:*?"<>|'`~!@#$%^&()+=\[\]{};，。、]+""")


def _slug(text: str) -> str:
    s = _UNSAFE_RE.sub("-", str(text or "").strip()).strip("-.")
    return (s or "模板")[:48]


def _unique_key(base: str, rows: list, zh: str) -> str:
    """同名同内容 → 覆盖；**不同内容 → 加序号**，绝不顶掉别人的模板。"""
    for r in rows:
        if str(r.get("key")) == base and str(r.get("zh")) == zh:
            return base                        # 覆盖自己
    if not any(str(r.get("key")) == base for r in rows):
        return base
    n = 2
    while any(str(r.get("key")) == f"{base}-{n}" for r in rows):
        n += 1
    return f"{base}-{n}"


def load_user(root: Path | str = "") -> list[PromptTemplate]:
    """读用户自存模板；文件不存在/坏掉一律返回空表（**不抛异常**）。"""
    p = user_path(root)
    if not p.exists():
        return []
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001
        return []
    out: list[PromptTemplate] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not r.get("key"):
            continue
        try:
            out.append(PromptTemplate(
                key=str(r["key"]), zh=str(r.get("zh") or r["key"]),
                group="我的模板", use=str(r.get("use") or "自己存的模板"),
                subject_zh=str(r.get("subject") or ""),
                subject_en=str(r.get("subject_en") or r.get("subject") or ""),
                style_zh=str(r.get("style") or ""),
                style_en=str(r.get("style_en") or r.get("style") or ""),
                background_zh=str(r.get("background") or ""),
                background_en=str(r.get("background_en") or r.get("background") or ""),
                extra_positive=str(r.get("extra_positive") or ""),
                extra_negative=str(r.get("extra_negative") or ""),
                preset=str(r.get("preset") or "t2i_single"),
                cutout_bg=str(r.get("cutout_bg") or "grey"),
                note=str(r.get("note") or ""),
                tags=tuple(r.get("tags") or ()),
                custom=True))
        except Exception:                               # noqa: BLE001
            continue
    return out


def save_user(fields: dict, *, root: Path | str = "", name: str = "") -> dict:
    """把表单当前内容存成「我的模板」。同名同标题才覆盖，否则自动加序号。"""
    fields = dict(fields or {})
    zh = str(name or fields.get("zh") or fields.get("subject") or "").strip()
    if not zh:
        raise ValueError("要给模板一个名字（name=…）")
    p = user_path(root)
    rows: list = []
    if p.exists():
        try:
            rows = [r for r in (json.loads(p.read_text(encoding="utf-8")) or [])
                    if isinstance(r, dict)]
        except Exception:                               # noqa: BLE001
            rows = []
    key = _unique_key(_slug(name or zh), rows, zh[:40])
    rows = [r for r in rows if str(r.get("key")) != key]
    rows.append({
        "key": key, "zh": zh[:40],
        "use": str(fields.get("use") or "")[:120],
        "subject": str(fields.get("subject") or ""),
        "style": str(fields.get("style") or ""),
        "background": str(fields.get("background") or ""),
        "extra_positive": str(fields.get("extra_positive") or ""),
        "extra_negative": str(fields.get("extra_negative") or ""),
        "preset": str(fields.get("preset") or "t2i_single"),
        "cutout_bg": str(fields.get("cutout_bg") or "grey"),
        "note": str(fields.get("note") or "自己存的模板"),
    })
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "key": key, "zh": zh[:40], "replaced": len(rows) > 1,
            "path": str(p), "count": len(rows)}


def delete_user(key: str, *, root: Path | str = "") -> dict:
    p = user_path(root)
    if not p.exists():
        return {"ok": False, "error": "还没有任何自存模板"}
    rows = [r for r in (json.loads(p.read_text(encoding="utf-8")) or [])
            if isinstance(r, dict)]
    keep = [r for r in rows if str(r.get("key")) != str(key or "").strip()]
    if len(keep) == len(rows):
        return {"ok": False, "error": f"没有名为「{key}」的自存模板",
                "hint": "内置的 12 套不能删，只能删「我的模板」里的"}
    p.write_text(json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "count": len(keep)}
