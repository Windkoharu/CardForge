"""``.cdb``（SQLite）读写 —— EDOPro / YGOPro 的卡池文件格式。

表结构（**2026-07 对 ``vendor/data/cards_zh.cdb`` 实测确认**，非凭记忆）::

    -- PRAGMA table_info(datas)  共 11 列，id 为主键
    cid name       type      notnull dflt  pk
      0 id         INTEGER         0   None   1
      1 ot         INTEGER         0   None   0
      2 alias      INTEGER         0   None   0
      3 setcode    INTEGER         0   None   0
      4 type       INTEGER         0   None   0
      5 atk        INTEGER         0   None   0
      6 def        INTEGER         0   None   0
      7 level      INTEGER         0   None   0
      8 race       INTEGER         0   None   0
      9 attribute  INTEGER         0   None   0
     10 category   INTEGER         0   None   0

    -- PRAGMA table_info(texts)  共 19 列，id 为主键
    cid name   type    pk
      0 id     INTEGER   1
      1 name   TEXT      0
      2 desc   TEXT      0
      3 str1   TEXT      0
      ...    （str1..str16 连续，共 16 列）
     18 str16  TEXT      0

其他实测结论（写本模块时的依据）：

* ``datas.id`` / ``texts.id`` 都是 **PRIMARY KEY** → 一个 .cdb 里**一个卡号只能有一行文本**。
  因此**多语言不能写在同一个 cdb 里**，必须「每种语言一个 ``cards-<suffix>.cdb``」，
  这正是 ``export_multilang()`` 的做法（文件名后缀取自 ``core.enums.LANGS[*].cdb_suffix``）。
* **连接怪兽**：``def`` 存箭头掩码、``level`` 存连接数。实测 ``def=0x22(34) level=2``、
  ``def=0x2a(42) level=3``，与 ``CardSpec.def_value`` / ``effective_level`` 完全吻合。
* **攻击力/守备力为「?」的卡**：写 ``-2``（实测官方池 117 张 atk=-2、79 张 def=-2，
  且不存在 NULL）。本模块的 ``UNKNOWN_NUM`` 即此约定。
* **魔法/陷阱**：``atk=def=level=race=attribute=0``（实测 type&0x2 的行全为 0）。
  ``CardSpec`` 的 level/race/attribute 默认值是怪兽向的，**必须清零**，否则 EDOPro 会当怪兽处理。
* **卡文换行**：官方多行卡文一律 ``\\r\\n``（实测 9113 张 CRLF、0 张纯 LF）。本模块沿用 CRLF。
* **灵摆卡 `level` 列是打包的**（本模块最关键的一条实测）：::

      level 列 = (左刻度 << 24) | (右刻度 << 16) | (等级 / 阶级 / 连接数)

  官方池 399 张灵摆卡，其中 398 张的 ``desc`` 头能解析出 ``←L 【灵摆】 R→``，
  **398/398 都与该公式完全吻合**（例：``DD 魔导贤者 托马斯`` 刻度 6、等级 8 →
  ``0x06060008``；超量灵摆 ``威风妖怪·龙`` 刻度 5、阶级 4 → ``0x05050004``，
  低位放的是**阶级**）。非灵摆怪兽的 ``level`` 列就是纯等级（官方实测最大值 13）。
  不按这个公式写，DIY 灵摆卡上桌后刻度会是 0、灵摆区不能用 —— :func:`level_column` 负责兜住。
* **灵摆卡卡文**：``desc`` 拼成 ``←6 【灵摆】 6→\\r\\n<灵摆效果>\\r\\n【怪兽效果】\\r\\n<怪兽效果>``
  （实测 id=41546 / 368382 / 645794 三张真实卡）。没有灵摆效果文本时只保留 ``←s 【灵摆】 s→`` 行。
* **通常怪兽**：``desc`` 放 flavor（实测 id=32864 / 549481 / 732302）。
* **setcode**：4 个 16 位值打包进一个整数，低 16 位是第一个字段（实测 0x006E00AF → 槽位
  ``['0xaf','0x6e','0x0','0x0']``）。所以 ``"0x1001"`` 直接 ``int(...,16)`` 写入即可。
* ``ot``：官方池取值分布为 ``11(8384) / 3(6186) / 1(233) / 9(191) / 2(25)``。
  自造卡统一写 ``ot=3``（= OCG+TCG，社区通行做法，两种规则开关下都可见）。
* ``category``：官方只有约一半的卡非 0；DIY 默认写 ``0``，效果分类由 Lua 在运行时声明。
* 写文件编码：SQLite 的 TEXT 一律以 **UTF-8** 落盘，Python ``str`` 直接绑定即为 UTF-8，无需额外处理。

**硬约束**：绝不写入官方卡池 ``vendor/data/cards_zh.cdb``。DIY 卡只能进
``expansions/*.cdb``，否则 EDOPro 自动更新时会覆盖掉用户的卡。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..core import constants as C
from ..core.enums import DEFAULT_LANG, LANGS
from ..core.errors import EnvError, SpecError
from ..core.models import CardSpec

__all__ = [
    "DATAS_COLS", "TEXTS_COLS", "N_STRINGS", "DEFAULT_OT", "UNKNOWN_NUM",
    "ensure_schema", "open_cdb", "open_cdb_ro", "upsert_card", "upsert_many",
    "delete_card_row", "count_cards", "read_card", "list_cards", "iter_cards",
    "write_strings_conf", "export_multilang",
    "card_name", "card_desc", "card_strings", "spec_to_rows", "num_of",
    "setcode_int", "parse_setcode", "pack_setcodes",
    "engine_type_bits", "level_column", "parse_level_column",
]

#: ``datas`` 的列顺序 —— 与官方 cdb 实测一致，禁止改动顺序。
DATAS_COLS: tuple[str, ...] = (
    "id", "ot", "alias", "setcode", "type", "atk", "def",
    "level", "race", "attribute", "category",
)

#: ``texts`` 的列顺序 —— id, name, desc, str1..str16。
TEXTS_COLS: tuple[str, ...] = ("id", "name", "desc", *(f"str{i}" for i in range(1, 17)))

#: ``texts`` 里 str 列的数量（Lua 的 ``aux.Stringid(id, 0)`` 读 str1）。
N_STRINGS = 16

#: 自造卡默认 ``ot``：OCG(1) | TCG(2)。官方池里 3 也是最常见的取值之一。
DEFAULT_OT = 3

#: ``atk``/``def`` 为「?」时的引擎编码（官方池实测值）。
UNKNOWN_NUM = -2

_CREATE_DATAS = """CREATE TABLE IF NOT EXISTS datas (
    id integer primary key, ot integer, alias integer, setcode integer,
    type integer, atk integer, def integer, level integer,
    race integer, attribute integer, category integer)"""

_CREATE_TEXTS = """CREATE TABLE IF NOT EXISTS texts (
    id integer primary key, name text, desc text,
    str1 text, str2 text, str3 text, str4 text, str5 text, str6 text, str7 text, str8 text,
    str9 text, str10 text, str11 text, str12 text, str13 text, str14 text, str15 text, str16 text)"""


# ══════════════════════════════════════════════════════════════════════
#  连接与建表
# ══════════════════════════════════════════════════════════════════════
def ensure_schema(con: sqlite3.Connection) -> None:
    """建表 + 补列，使 ``con`` 满足 EDOPro 的 ``datas``/``texts`` 结构。

    幂等：已存在的表与列不动。若传入的是**手工建的不完整 cdb**（缺 str9 之类），
    会用 ``ALTER TABLE ADD COLUMN`` 补齐，而不是重建 —— 保住已有数据。

    .. note::
       ``ALTER TABLE ADD COLUMN`` 只能把新列**追加到末尾**，所以「被补过的」表列顺序
       可能与官方规范顺序不同（列**名字**一定齐全）。EDOPro 的 SQLite 读取器是按
       ``SELECT id, ot, alias, …`` 逐列取值的，不看顺序，因此不影响使用。
       本模块自己 ``CREATE TABLE`` 出来的新 cdb 列顺序与官方**完全一致**。
       ``expansions.verify()`` 的 ``G5_CDB_SCHEMA`` 也只查列名，不查顺序。
    """
    con.execute(_CREATE_DATAS)
    con.execute(_CREATE_TEXTS)
    for table, cols in (("datas", DATAS_COLS), ("texts", TEXTS_COLS)):
        have = {str(r[1]) for r in con.execute(f"PRAGMA table_info({table})")}
        kind = "integer" if table == "datas" else "text"
        for col in cols:
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
    con.commit()


def open_cdb(path: str | os.PathLike[str], create: bool = True) -> sqlite3.Connection:
    """打开（并按需创建）一个 .cdb，返回**可写**连接。

    :param path: .cdb 路径，父目录不存在时会自动创建。
    :param create: True 时建表补列；False 时要求文件已存在，否则抛 ``EnvError``。
    :raises EnvError: ``create=False`` 且文件不存在。
    """
    p = Path(path)
    if not create and not p.is_file():
        raise EnvError(
            f"卡池文件不存在：{p}",
            hint="确认路径，或改用 open_cdb(path, create=True) 新建一个空卡池。",
            detail={"path": str(p)},
        )
    if create:
        p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    if create:
        ensure_schema(con)
    return con


def open_cdb_ro(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """**只读**打开一个 .cdb（校验/查询别人产物时用，绝不改写）。

    先用 ``file:...?mode=ro`` URI 打开；若平台/路径不支持 URI，退化为普通连接 +
    ``PRAGMA query_only=ON``（双保险，后者会拒绝任何写语句）。

    :raises EnvError: 文件不存在 —— 绝不因为「读一个不存在的 cdb」而把它建出来。
    """
    p = Path(path)
    if not p.is_file():
        raise EnvError(f"卡池文件不存在：{p}",
                       hint="检查路径；只读打开不会创建文件。",
                       detail={"path": str(p)})
    raw = p.as_posix()
    # 路径里出现 ? 或 # 会破坏 URI 语义，这时才做百分号编码
    if "?" in raw or "#" in raw:
        from urllib.parse import quote
        raw = quote(raw, safe="/:")
    try:
        con = sqlite3.connect(f"file:{raw}?mode=ro", uri=True)
        con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.Error:
        con = sqlite3.connect(str(p))
        con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row
    return con


# ══════════════════════════════════════════════════════════════════════
#  取值转换
# ══════════════════════════════════════════════════════════════════════
def num_of(value: Any) -> int:
    """把 ``atk``/``dfd`` 这类「int 或 ``"?"``」字段转成引擎整数。

    ``"?"``/``"？"``/``None``/``""`` → ``UNKNOWN_NUM``(-2) 或 0，无法解析的字符串按 0 处理。
    """
    if value is None:
        return UNKNOWN_NUM
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return 0
    if s in ("?", "？", "-", "—"):
        return UNKNOWN_NUM
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return 0


def setcode_int(value: Any) -> int:
    """``"0x1001"`` / ``"1001"`` / ``4097`` → 引擎整数。

    字符串一律按**十六进制**解析（setcode 的官方书写惯例就是 0x 前缀的 16 位值）。
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    s = str(value).strip().lower()
    if not s or s in ("0x", "0x0", "none", "null"):
        return 0
    if s.startswith("0x"):
        s = s[2:]
    try:
        return int(s, 16)
    except ValueError:
        try:
            return int(s, 10)
        except ValueError:
            return 0


def parse_setcode(value: Any) -> list[int]:
    """把打包后的 setcode 拆成 4 个 16 位字段（官方池实测：低 16 位是第一个字段）。"""
    v = setcode_int(value)
    return [(v >> (16 * i)) & 0xFFFF for i in range(4)]


def pack_setcodes(*codes: Any) -> int:
    """把最多 4 个 16 位字段打包成一个 setcode 整数。"""
    out = 0
    for i, c in enumerate(codes[:4]):
        out |= (setcode_int(c) & 0xFFFF) << (16 * i)
    return out


# ══════════════════════════════════════════════════════════════════════
#  两个必须由本层兜住的引擎编码（core 不负责）
# ══════════════════════════════════════════════════════════════════════
def engine_type_bits(spec: CardSpec) -> int:
    """``datas.type`` 位 —— 修正 ``CardSpec.type_bits`` 的两个已知偏差。

    实测 ``core.enums.FRAMES``：

    * ``FRAMES["normal"].base == "effect"``（**实测**，疑似 core/enums.py 漏写
      ``base="normal"``），于是 ``CardSpec.type_bits`` 给通常怪兽算出
      ``MONSTER|EFFECT = 0x21``。引擎按 type 位决定卡框与「效果怪兽」标识，
      通常怪兽必须是 ``MONSTER|NORMAL = 0x11``，否则上桌后显示成效果怪兽。
    * ``FRAMES["token"].base == "token"`` 且 ``MONSTER_TAGS`` 里没有 token 位 →
      ``type_bits`` 给衍生物算出 ``0x21``，丢了 ``TYPE_TOKEN(0x4000)``。

    这两处**不改 core**（本层无权改），在写入 cdb 时兜住。其余 frame 与
    ``type_bits`` 完全一致。
    """
    bits = int(spec.type_bits)
    if spec.frame == "normal":
        bits = (bits & ~C.TYPE_EFFECT) | C.TYPE_NORMAL
    elif spec.frame == "token":
        bits = (bits & ~C.TYPE_EFFECT) | C.TYPE_NORMAL | C.TYPE_TOKEN
    return bits


def level_column(spec: CardSpec) -> int:
    """``datas.level`` 列的值。

    **实测结论（399 张官方灵摆卡，398/398 与卡文里的 ``←L 【灵摆】 R→`` 完全吻合）**：
    灵摆怪兽的 ``level`` 列是**打包**的 ——::

        level 列 = (左刻度 << 24) | (右刻度 << 16) | (等级 / 阶级 / 连接数)

    例：``DD 魔导贤者 托马斯`` 刻度 6、等级 8 → ``0x06060008``；
    ``威风妖怪·蛤蟆`` 刻度 5、等级 4 → ``0x05050004``；
    超量灵摆 ``威风妖怪·龙`` 刻度 5、阶级 4 → ``0x05050004``（低位放的是**阶级**）。

    非灵摆怪兽的 ``level`` 列就是纯等级（官方池实测最大值 13，没有被污染）。
    ``CardSpec`` 只有一个 ``pendulum_scale``（没有分左右），所以左右填同一个值 ——
    官方池 399 张灵摆卡的左右刻度**全部相同**，这个假设成立。
    """
    lvl = int(spec.effective_level or 0) & 0xFFFF
    if spec.is_pendulum:
        scale = int(spec.pendulum_scale or 0) & 0xFF
        return (scale << 24) | (scale << 16) | lvl
    return lvl


def parse_level_column(value: Any, type_bits: int = 0) -> dict:
    """:func:`level_column` 的逆运算，供读取/校验用。

    :returns: ``{"raw","level","lscale","rscale","pendulum"}``；
        非灵摆的 ``lscale``/``rscale`` 固定为 0。
    """
    v = int(value or 0)
    pend = bool(int(type_bits or 0) & C.TYPE_PENDULUM)
    return {
        "raw": v,
        "level": v & 0xFFFF,
        "lscale": ((v >> 24) & 0xFF) if pend else 0,
        "rscale": ((v >> 16) & 0xFF) if pend else 0,
        "pendulum": pend,
    }


# ══════════════════════════════════════════════════════════════════════
#  CardSpec → 行
# ══════════════════════════════════════════════════════════════════════
def card_name(spec: CardSpec, lang: str = DEFAULT_LANG) -> str:
    """该语言的卡名（缺失时回落主卡名）。"""
    return spec.name_in(lang) or spec.name


def card_strings(spec: CardSpec) -> list[str]:
    """``spec.strings`` → 定长 16 项，喂给 ``texts.str1..str16``。"""
    out = [str(s) if s is not None else "" for s in (spec.strings or [])][:N_STRINGS]
    out += [""] * (N_STRINGS - len(out))
    return out


def _monster_box_text(spec: CardSpec, lang: str) -> str:
    """「怪兽效果」框的文本（通常怪兽回落 flavor）。

    注意：这里按 **frame 键**判通常怪兽，不能用 ``frame_def.base`` ——
    实测 ``FRAMES["normal"].base`` 是 ``"effect"``（core 疑似漏写），
    照 base 判会把通常怪兽的 flavor 吞掉。
    """
    t = spec.text_in(lang)
    if t:
        return t
    if spec.frame in _VANILLA_FRAMES:
        return spec.flavor_in(lang)
    return ""


#: 卡文位置放 flavor 的卡种（通常怪兽 / 通常灵摆 / 衍生物）
_VANILLA_FRAMES: tuple[str, ...] = ("normal", "normal_pendulum", "token")


def _crlf(text: str) -> str:
    """把任意换行统一成 ``\\r\\n``。

    依据：官方池 15019 张卡里 **9113 张含换行、全部是 CRLF，纯 LF 的 0 张**。
    卡文/灵摆卡文来自用户输入或 LLM，常常是 ``\\n``；这里统一成官方写法，
    保证 EDOPro 的卡文折行表现与官方卡一致。
    """
    if not text:
        return ""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def card_desc(spec: CardSpec, lang: str = DEFAULT_LANG) -> str:
    """拼出写进 ``texts.desc`` 的卡文（换行统一成官方用的 ``\\r\\n``）。

    * 灵摆卡按官方版式拼 ``←s 【灵摆】 s→`` + 灵摆效果 + ``【怪兽效果】`` + 怪兽效果。
    * 通常怪兽写 flavor。
    * 魔法/陷阱写效果文本。
    """
    if spec.is_pendulum:
        scale = spec.pendulum_scale
        scale_txt = "" if scale is None else str(int(scale))
        parts = [f"←{scale_txt} 【灵摆】 {scale_txt}→"]
        ptext = spec.pendulum_text_in(lang)
        if ptext:
            parts.append(ptext)
        parts.append("【怪兽效果】")
        body = _monster_box_text(spec, lang)
        if body:
            parts.append(body)
        return _crlf("\r\n".join(parts))
    if spec.is_monster:
        return _crlf(_monster_box_text(spec, lang))
    t = spec.text_in(lang)
    if t:
        return _crlf(t)
    return _crlf(spec.flavor_in(lang)) if spec.flavor else ""


def spec_to_rows(
    spec: CardSpec,
    lang: str = DEFAULT_LANG,
    texts: Mapping[str, Any] | None = None,
    *,
    ot: int = DEFAULT_OT,
    alias: int = 0,
    category: int = 0,
    setcode: Any = None,
) -> tuple[tuple, tuple]:
    """``CardSpec`` → ``(datas 行, texts 行)`` 两个元组，列序与官方 cdb 一致。

    ``texts`` 可整体覆盖 ``name``/``desc``/``str1..str16`` 中的任意列（缺的列走 spec 推导）。
    """
    if not int(spec.id or 0):
        raise SpecError("卡号为 0，无法写入卡池", hint="先给 CardSpec 分配一个卡号（pool.official.next_free_id）。")

    is_monster = bool(spec.is_monster)
    if is_monster:
        atk = num_of(spec.atk)
        dfn = num_of(spec.def_value)          # 连接怪兽 = 箭头掩码
        level = level_column(spec)            # 灵摆卡 = 刻度打包
        race = int(spec.race_bits)
        attribute = int(spec.attr_bits)
    else:
        # 实测：官方魔陷行的 atk/def/level/race/attribute 全为 0
        atk = dfn = level = race = attribute = 0

    sc = setcode_int(spec.setcode if setcode is None else setcode)

    datas = (
        int(spec.id), int(ot), int(alias), sc, engine_type_bits(spec),
        atk, dfn, level, race, attribute, int(category),
    )

    over = dict(texts or {})
    name = str(over.pop("name", None) or card_name(spec, lang))
    desc = str(over.pop("desc", None) or card_desc(spec, lang))
    strs = card_strings(spec)
    for i in range(N_STRINGS):
        key = f"str{i + 1}"
        if key in over:
            value = over.pop(key)
            strs[i] = "" if value is None else str(value)
    trow = [int(spec.id), name, desc, *strs]
    return datas, tuple(trow)


# ══════════════════════════════════════════════════════════════════════
#  写入
# ══════════════════════════════════════════════════════════════════════
def upsert_card(
    con: sqlite3.Connection,
    spec: CardSpec,
    lang: str = DEFAULT_LANG,
    texts: Mapping[str, Any] | None = None,
    *,
    ot: int = DEFAULT_OT,
    alias: int = 0,
    category: int = 0,
) -> None:
    """写入（或覆盖）一张卡，幂等：同一卡号重复导入不会产生重复行。

    **多语言的处理依据**：``datas.id`` 与 ``texts.id`` 都是 ``PRIMARY KEY``（实测），
    所以一个 .cdb 内一个卡号只能有一行文本 —— 多语言**不能**写进同一个文件。
    ``lang`` 只决定这一次写入用哪种语言的卡名/卡文；要出多语言包请用
    :func:`export_multilang`，它会为每种语言生成独立的 ``cards-<suffix>.cdb``。

    :param texts: 覆盖 ``texts`` 表的任意列（``name`` / ``desc`` / ``str1``..``str16``）。
    :raises SpecError: ``spec.id`` 为 0。
    """
    datas, trow = spec_to_rows(spec, lang, texts, ot=ot, alias=alias, category=category)
    with con:  # 事务：两表要么都写，要么都不写
        con.execute(
            f"INSERT OR REPLACE INTO datas ({','.join(DATAS_COLS)}) "
            f"VALUES ({','.join('?' * len(DATAS_COLS))})",
            datas,
        )
        con.execute(
            f"INSERT OR REPLACE INTO texts ({','.join(TEXTS_COLS)}) "
            f"VALUES ({','.join('?' * len(TEXTS_COLS))})",
            trow,
        )


def upsert_many(
    con: sqlite3.Connection,
    specs: Iterable[CardSpec],
    lang: str = DEFAULT_LANG,
    *,
    ot: int = DEFAULT_OT,
    category: int = 0,
) -> int:
    """批量写入，返回写入条数。整体一个事务，中途出错全部回滚。"""
    rows = [spec_to_rows(s, lang, None, ot=ot, category=category) for s in specs]
    with con:
        for datas, trow in rows:
            con.execute(
                f"INSERT OR REPLACE INTO datas ({','.join(DATAS_COLS)}) "
                f"VALUES ({','.join('?' * len(DATAS_COLS))})", datas)
            con.execute(
                f"INSERT OR REPLACE INTO texts ({','.join(TEXTS_COLS)}) "
                f"VALUES ({','.join('?' * len(TEXTS_COLS))})", trow)
    return len(rows)


def delete_card_row(con: sqlite3.Connection, card_id: int) -> bool:
    """删掉一张卡的两表记录，返回是否真的删到了东西。"""
    cid = int(card_id)
    with con:
        a = con.execute("DELETE FROM datas WHERE id=?", (cid,)).rowcount
        b = con.execute("DELETE FROM texts WHERE id=?", (cid,)).rowcount
    return bool(a or b)


def count_cards(con: sqlite3.Connection) -> int:
    """卡池里的卡数（以 datas 为准；表不存在时返回 0）。"""
    try:
        return int(con.execute("SELECT COUNT(*) FROM datas").fetchone()[0])
    except sqlite3.Error:
        return 0


# ══════════════════════════════════════════════════════════════════════
#  读取
# ══════════════════════════════════════════════════════════════════════
def read_card(con: sqlite3.Connection, card_id: int) -> dict | None:
    """读一张卡，返回 ``datas`` + ``texts`` 全部列（外加 ``strings`` 定长列表）。

    两边都查不到时返回 ``None``。
    """
    cid = int(card_id)
    d = con.execute(
        f"SELECT {','.join(DATAS_COLS)} FROM datas WHERE id=?", (cid,)).fetchone()
    t = con.execute(
        f"SELECT {','.join(TEXTS_COLS)} FROM texts WHERE id=?", (cid,)).fetchone()
    if d is None and t is None:
        return None
    out: dict[str, Any] = dict(zip(DATAS_COLS, tuple(d))) if d is not None else {}
    if t is not None:
        trow = tuple(t)
        out.update(zip(TEXTS_COLS, trow))
        out["strings"] = [trow[3 + i] or "" for i in range(N_STRINGS)]
    return out


def list_cards(con: sqlite3.Connection, limit: int = 0) -> list[dict]:
    """列出卡池（``datas LEFT JOIN texts``，按卡号升序）。``limit<=0`` 表示不限。"""
    sql = ("SELECT d.id, d.ot, d.setcode, d.type, d.atk, d.def, d.level, d.race, "
           "d.attribute, d.category, t.name "
           "FROM datas d LEFT JOIN texts t ON t.id=d.id ORDER BY d.id")
    args: tuple = ()
    if limit and limit > 0:
        sql += " LIMIT ?"
        args = (int(limit),)
    try:
        rows = con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []
    return [{"id": r[0], "ot": r[1], "setcode": r[2], "type": r[3], "atk": r[4],
             "def": r[5], "level": r[6], "race": r[7], "attribute": r[8],
             "category": r[9], "name": r[10] or ""} for r in rows]


def iter_cards(con: sqlite3.Connection):
    """逐行迭代 ``datas``（内存友好，供大批量校验用）。"""
    cur = con.execute(f"SELECT {','.join(DATAS_COLS)} FROM datas ORDER BY id")
    for row in cur:
        yield dict(zip(DATAS_COLS, tuple(row)))


# ══════════════════════════════════════════════════════════════════════
#  strings.conf
# ══════════════════════════════════════════════════════════════════════
def write_strings_conf(
    path: str | os.PathLike[str],
    setnames: Mapping[Any, str] | None = None,
    counters: Mapping[Any, str] | None = None,
    counters_alias: Mapping[Any, str] | None = None,
) -> str:
    """写 ``strings.conf``（``!setname`` / ``!counter`` / ``!counter_alias``）。

    输出与 ``export.strings.render()`` **逐字节一致**（自测 p3 会比对，两边都不 import 对方，
    以免 pool ← export 的反向依赖）。

    格式::

        # CardForge 自动生成 —— DIY 系列名 / 计数器名
        !setname 0x1001 星奏
        !counter 0x1 星奏指示物

    :returns: 写入的路径字符串。
    """
    from ..export.strings import render as _render  # 函数内延迟 import，避免模块级反向依赖
    text = _render(setnames, counters, counters_alias)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    return str(p)


# ══════════════════════════════════════════════════════════════════════
#  多语言导出
# ══════════════════════════════════════════════════════════════════════
def cdb_filename(name: str, lang: str = "", *, suffix_map: Mapping[str, str] | None = None) -> str:
    """``("CardForge", "zh_cn")`` → ``"CardForge-zh-CN.cdb"``；``lang=""`` → ``"CardForge.cdb"``。

    后缀取自 ``core.enums.LANGS[lang].cdb_suffix``（可用 ``suffix_map`` 覆盖）。
    """
    if not lang:
        return f"{name}.cdb"
    suffix = (suffix_map or {}).get(lang)
    if not suffix:
        spec = LANGS.get(lang)
        suffix = spec.cdb_suffix if spec else lang
    return f"{name}-{suffix}.cdb"


def export_multilang(
    specs: Iterable[CardSpec],
    out_dir: str | os.PathLike[str],
    *,
    name: str = "cards",
    langs: Sequence[str] = (DEFAULT_LANG,),
    base: bool = True,
    suffix_map: Mapping[str, str] | None = None,
    ot: int = DEFAULT_OT,
    category: int = 0,
) -> dict:
    """把一批卡导出成**每种语言一个 .cdb**。

    文件名约定（依据见模块 docstring：``texts.id`` 是主键，一个文件装不下多语言）::

        <name>.cdb                 # 基础包，用 langs[0] 的语言；base=False 则不生成
        <name>-<suffix>.cdb        # 每种语言一份（suffix 来自 LANGS[*].cdb_suffix）

    :returns: ``{"ok","dir","files":{lang:path},"base","count","langs","bytes"}``
    """
    lang_list = [str(l) for l in (langs or (DEFAULT_LANG,))]
    for l in lang_list:
        if l not in LANGS:
            raise SpecError(f"未知语言键：{l}", hint=f"可用：{', '.join(LANGS)}")
    items = [s for s in specs if s is not None]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    rows: dict[str, int] = {}

    def _write(path: Path, lang: str, key: str) -> None:
        con = open_cdb(path, create=True)
        try:
            upsert_many(con, items, lang, ot=ot, category=category)
            rows[key] = count_cards(con)
        finally:
            con.close()
        files[key] = str(path)

    base_path = out / cdb_filename(name, "")
    if base and lang_list:
        # 基础包：不匹配任何语言文件的客户端也能看到卡（用 langs[0] 的文本）
        _write(base_path, lang_list[0], "")
    for lang in lang_list:
        # 每种语言都写一份带后缀的；langs[0] 会与基础包内容重复，这是有意的冗余
        _write(out / cdb_filename(name, lang, suffix_map=suffix_map), lang, lang)

    return {
        "ok": True,
        "dir": str(out),
        "name": name,
        "files": files,
        "base": str(base_path) if base else "",
        "count": len(items),
        "langs": lang_list,
        "rows": rows,
    }
