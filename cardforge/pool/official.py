"""官方卡池查询（**只读**）—— 字段查重、卡号占用、setcode 占用的单一真相源。

设计要点
--------
1. **绝不写入官方卡池。** 连接一律用 ``file:...?mode=ro`` URI 打开，失败时退化为
   普通连接 + ``PRAGMA query_only=ON``。``vendor/data/cards_zh.cdb`` 是只读资产。
2. **全部方法不抛异常。** cdb 缺失/损坏/没有 FTS5 时返回空结果并往
   :attr:`OfficialPool.warnings` 记一条中文警告 —— 这是「可降级的能力失败」。
3. **FTS5 优先、LIKE 兜底**，但两者的语义差别是实测出来的，不是猜的：

   ``vendor/data/cards_zh.cdb`` 里有一张外部内容表::

       CREATE VIRTUAL TABLE card_fts USING fts5(name, desc,
           content='texts', content_rowid='id', tokenize='unicode61')

   实测 ``unicode61`` 对中文是**整段成词**（CJK 连续串 = 一个 token），所以
   ``MATCH`` 只能命中「整段正好等于查询串」的文本，召回率远低于子串匹配：

   ============  ==========  ==========  ==========
   查询          name LIKE   desc LIKE   FTS MATCH
   ============  ==========  ==========  ==========
   ``青眼``      44          61          27
   ``青眼白龙``  20          42          60
   ``水精鳞``    20          27          31
   ``密码``      4           1           0
   ============  ==========  ==========  ==========

   且实测 ``FTS 命中集 ⊆ (name LIKE ∪ desc LIKE)`` 对以上每个查询都成立。
   因此：

   * :meth:`OfficialPool.search` —— **FTS5 + LIKE 取并集**（FTS 命中排前面，它是精确
     词命中、相关度最高；LIKE 补召回）。没有 FTS5 时纯 LIKE。
   * :meth:`OfficialPool.archetype_hits` —— 走 LIKE。这是「字段名查重」（防 Cipher
     Soldier 事件），**召回率优先**：少报一个字段引用，用户就会做出一张和官方撞字段的卡。
     LIKE 是子串匹配，是 FTS token 匹配的超集，所以这一步不用 FTS 反而更安全。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..core import paths
from .cdb import DATAS_COLS, TEXTS_COLS, parse_setcode, setcode_int

__all__ = ["OfficialPool", "load", "official_cdb_path", "DEFAULT_ID_START"]

#: 自造卡卡号起点 —— 官方池最大 id 为 99995595，取 2.1 亿留出安全余量。
DEFAULT_ID_START = 210000000

#: 卡池文件名候选（按优先级）。``vendor/data`` 里只放了 cards_zh.cdb。
_CDB_CANDIDATES = ("cards_zh.cdb", "cards.cdb", "cards-zh-CN.cdb", "cards-ja.cdb")


def official_cdb_path() -> Path | None:
    """定位官方卡池 .cdb（``core.paths.OFFICIAL_CDB`` 下的第一个候选）；找不到返回 None。"""
    base = Path(paths.OFFICIAL_CDB)
    for name in _CDB_CANDIDATES:
        p = base / name
        if p.is_file():
            return p
    if base.is_dir():
        found = sorted(p for p in base.glob("*.cdb") if p.is_file())
        if found:
            return found[0]
    return None


def _ro_uri(p: Path) -> str:
    raw = Path(p).as_posix()
    if "?" in raw or "#" in raw:
        from urllib.parse import quote
        raw = quote(raw, safe="/:")
    return f"file:{raw}?mode=ro"


def _like_escape(s: str) -> str:
    """转义 LIKE 的通配符，让用户输入的 ``%``/``_`` 按字面匹配。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fts_phrase(q: str) -> str:
    """把任意用户输入变成合法的 FTS5 短语查询，避免语法错误导致整次检索失败。"""
    return '"' + str(q).replace('"', '""') + '"'


class OfficialPool:
    """官方卡池的只读查询门面。任何一步失败都只记 :attr:`warnings`。"""

    def __init__(self, cdb_path: str | Path | None = None):
        self.path: Path | None = Path(cdb_path) if cdb_path else official_cdb_path()
        self.warnings: list[str] = []
        self._con: sqlite3.Connection | None = None
        self._fts: str | None = None
        self._fts_checked = False
        self._ids: set[int] | None = None
        if self.path is None:
            self._warn(f"未找到官方卡池 .cdb（查找目录 {paths.rel(paths.OFFICIAL_CDB)}）")
        elif not Path(self.path).is_file():
            self._warn(f"官方卡池文件不存在：{self.path}")

    # ── 基础设施 ────────────────────────────────────────────────────
    def _warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    @property
    def available(self) -> bool:
        """卡池是否可用（文件存在且能连上）。"""
        return self._conn() is not None

    def _conn(self) -> sqlite3.Connection | None:
        if self._con is not None:
            return self._con
        if self.path is None or not Path(self.path).is_file():
            return None
        try:
            con = sqlite3.connect(_ro_uri(Path(self.path)), uri=True)
            con.row_factory = sqlite3.Row
            con.execute("SELECT COUNT(*) FROM datas").fetchone()
            self._con = con
        except sqlite3.Error as e:
            try:  # URI 不被支持时的退路，再加 query_only 保证只读
                con = sqlite3.connect(str(self.path))
                con.row_factory = sqlite3.Row
                con.execute("PRAGMA query_only=ON")
                con.execute("SELECT COUNT(*) FROM datas").fetchone()
                self._con = con
                self._warn("只读 URI 打开官方卡池失败，已退化为普通连接 + query_only=ON")
            except sqlite3.Error as e2:
                self._warn(f"打开官方卡池失败：{e} / {e2}")
                return None
        return self._con

    def _fts_table(self) -> str | None:
        """探测 FTS5 虚拟表；只探一次，结果缓存。"""
        if self._fts_checked:
            return self._fts
        self._fts_checked = True
        con = self._conn()
        if con is None:
            return None
        try:
            rows = con.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' "
                "AND sql LIKE '%USING fts5%'").fetchall()
        except sqlite3.Error as e:
            self._warn(f"探测 FTS5 失败：{e}")
            return None
        if not rows:
            self._warn("官方卡池没有 FTS5 虚拟表，全文检索退化为 LIKE（召回不变，速度略慢）")
            return None
        self._fts = str(rows[0]["name"])
        return self._fts

    # ── 统计 ────────────────────────────────────────────────────────
    def count(self) -> int:
        """卡池总卡数；不可用时返回 0。"""
        con = self._conn()
        if con is None:
            return 0
        try:
            return int(con.execute("SELECT COUNT(*) FROM datas").fetchone()[0])
        except sqlite3.Error as e:
            self._warn(f"统计卡数失败：{e}")
            return 0

    def all_ids(self) -> set[int]:
        """全部已占用卡号（缓存）。不可用时返回空集合。"""
        if self._ids is not None:
            return self._ids
        con = self._conn()
        if con is None:
            self._ids = set()
            return self._ids
        try:
            self._ids = {int(r[0]) for r in con.execute("SELECT id FROM datas")}
            self._ids |= {int(r[0]) for r in con.execute("SELECT id FROM texts")}
        except sqlite3.Error as e:
            self._warn(f"读取卡号集合失败：{e}")
            self._ids = set()
        return self._ids

    # ── 查询 ────────────────────────────────────────────────────────
    def search(self, q: str, limit: int = 20) -> list[dict]:
        """全文检索卡名与卡文。FTS5 命中优先，LIKE 补召回；没有 FTS5 时纯 LIKE。

        返回 ``[{"id","name","desc","type","atk","def","level","race","attribute",
        "setcode","ot","matched":[...]}]``，去重后最多 ``limit`` 条。卡池缺失时返回 ``[]``。
        """
        q = str(q or "").strip()
        if not q or limit <= 0:
            return []
        con = self._conn()
        if con is None:
            return []
        matched: dict[int, list[str]] = {}
        order: list[int] = []

        def _note(cid: int, how: str) -> None:
            if cid not in matched:
                matched[cid] = []
                order.append(cid)
            if how not in matched[cid]:
                matched[cid].append(how)

        fts = self._fts_table()
        if fts:
            try:
                for r in con.execute(
                        f"SELECT rowid FROM {fts} WHERE {fts} MATCH ? ORDER BY rank LIMIT ?",
                        (_fts_phrase(q), int(limit))):
                    _note(int(r[0]), "fts")
            except sqlite3.Error as e:
                self._warn(f"FTS5 检索失败，本次退化为 LIKE：{e}")

        pat = f"%{_like_escape(q)}%"
        for col, how in (("name", "name"), ("desc", "desc")):
            try:
                for r in con.execute(
                        f"SELECT id FROM texts WHERE {col} LIKE ? ESCAPE '\\' LIMIT ?",
                        (pat, int(limit))):
                    _note(int(r[0]), how)
            except sqlite3.Error as e:
                self._warn(f"LIKE 检索 {col} 失败：{e}")
            if len(order) >= limit * 3:   # 已经够挑，不再多查
                break

        out: list[dict] = []
        for cid in order[: int(limit)]:
            rec = self.read(cid)
            if rec is None:
                continue
            rec["matched"] = matched[cid]
            out.append(rec)
        return out

    def read(self, card_id: int) -> dict | None:
        """读一张官方卡的全部 datas+texts 字段（``search`` 内部用，也可单独调）。"""
        con = self._conn()
        if con is None:
            return None
        try:
            d = con.execute(
                f"SELECT {','.join(DATAS_COLS)} FROM datas WHERE id=?",
                (int(card_id),)).fetchone()
            t = con.execute(
                f"SELECT {','.join(TEXTS_COLS)} FROM texts WHERE id=?",
                (int(card_id),)).fetchone()
        except sqlite3.Error as e:
            self._warn(f"读取卡 {card_id} 失败：{e}")
            return None
        if d is None and t is None:
            return None
        out: dict[str, Any] = dict(zip(DATAS_COLS, tuple(d))) if d is not None else {}
        if t is not None:
            out.update(zip(TEXTS_COLS, tuple(t)))
        return out

    def text_of(self, card_id: int) -> dict | None:
        """只取文本部分：``{"id","name","desc","str1".."str16","strings"}``。"""
        con = self._conn()
        if con is None:
            return None
        try:
            t = con.execute(
                f"SELECT {','.join(TEXTS_COLS)} FROM texts WHERE id=?",
                (int(card_id),)).fetchone()
        except sqlite3.Error as e:
            self._warn(f"读取卡文 {card_id} 失败：{e}")
            return None
        if t is None:
            return None
        row = tuple(t)
        out: dict[str, Any] = dict(zip(TEXTS_COLS, row))
        out["strings"] = [row[3 + i] or "" for i in range(16)]
        return out

    def name_exists(self, name: str) -> dict | None:
        """卡名**完全相同**是否已存在；命中返回 ``{"id","name","desc"}``，否则 None。

        用 ``=`` 而不是 LIKE —— 这是「重名」判定，不是「字段引用」判定。
        """
        name = str(name or "").strip()
        if not name:
            return None
        con = self._conn()
        if con is None:
            return None
        try:
            r = con.execute(
                "SELECT id, name, desc FROM texts WHERE name=? LIMIT 1", (name,)).fetchone()
        except sqlite3.Error as e:
            self._warn(f"卡名查重失败：{e}")
            return None
        return dict(r) if r is not None else None

    def archetype_hits(self, field: str, limit: int = 8) -> list[dict]:
        """**字段名查重**：在卡名与卡文里找「字段」引用（防 Cipher Soldier 事件）。

        官方 PSCT 用 ``「星奏」`` 这样的角括号引用字段，所以子串匹配即可。
        按实测结论走 LIKE 而非 FTS5 —— LIKE 是 token 匹配的超集，召回优先。
        返回 ``[{"id","name","where","excerpt"}]``，``where`` ∈ ``{"name","desc","name+desc"}``。
        """
        field = str(field or "").strip()
        if not field or limit <= 0:
            return []
        con = self._conn()
        if con is None:
            return []
        pat = f"%{_like_escape(field)}%"
        hits: dict[int, dict] = {}
        try:
            for r in con.execute(
                    "SELECT id, name FROM texts WHERE name LIKE ? ESCAPE '\\' LIMIT ?",
                    (pat, int(limit))):
                hits[int(r[0])] = {"id": int(r[0]), "name": r[1] or "",
                                   "where": "name", "excerpt": r[1] or ""}
            for r in con.execute(
                    "SELECT id, name, desc FROM texts WHERE desc LIKE ? ESCAPE '\\' LIMIT ?",
                    (pat, int(limit))):
                cid = int(r[0])
                excerpt = _excerpt(r[2] or "", field)
                if cid in hits:
                    hits[cid]["where"] = "name+desc"
                    hits[cid]["desc_excerpt"] = excerpt
                else:
                    hits[cid] = {"id": cid, "name": r[1] or "", "where": "desc",
                                 "excerpt": excerpt}
        except sqlite3.Error as e:
            self._warn(f"字段查重失败：{e}")
            return []
        return list(hits.values())[: int(limit)]

    def id_taken(self, card_id: int) -> bool:
        """卡号是否已被官方池占用。卡池不可用时返回 False（**不阻塞导出**）。"""
        try:
            return int(card_id) in self.all_ids()
        except (TypeError, ValueError):
            return False

    def next_free_id(self, start: int = DEFAULT_ID_START) -> int:
        """从 ``start`` 起找第一个未被官方池占用的卡号。

        批量分配用 :meth:`alloc_ids` —— 连续调 ``next_free_id`` 会一直返回同一个空位。
        """
        ids = self.all_ids()
        cid = int(start)
        while cid in ids:
            cid += 1
        return cid

    def alloc_ids(self, count: int, start: int = DEFAULT_ID_START) -> list[int]:
        """批量分配 ``count`` 个互不冲突的卡号（跳过官方池已占用的洞）。"""
        n = max(0, int(count))
        out: list[int] = []
        ids = self.all_ids()
        cid = int(start)
        while len(out) < n:
            if cid not in ids:
                out.append(cid)
            cid += 1
        return out

    def setcode_used(self, setcode: Any) -> list[dict]:
        """官方池里**用到该字段（setcode）**的卡。

        ``setcode`` 是 4 个 16 位值打包进一个整数（实测 ``0x006E00AF`` → 槽位
        ``['0xaf','0x6e','0x0','0x0']``），所以判定必须逐槽位比对，
        **不能**写 ``WHERE setcode=?`` —— 那会漏掉所有「副字段」引用。
        返回 ``[{"id","name","setcode","slot","slots"}]``。
        """
        if setcode is None or str(setcode).strip() in ("", "0", "0x0"):
            return []
        want = setcode_int(setcode) & 0xFFFF
        if want == 0:
            return []
        con = self._conn()
        if con is None:
            return []
        sql = ("SELECT d.id, t.name, d.setcode FROM datas d "
               "LEFT JOIN texts t ON t.id=d.id WHERE d.setcode!=0 AND ("
               + " OR ".join(f"((d.setcode>>{16 * i}) & 0xFFFF) = ?" for i in range(4))
               + ") ORDER BY d.id")
        try:
            rows = con.execute(sql, (want, want, want, want)).fetchall()
        except sqlite3.Error as e:
            self._warn(f"setcode 查询失败：{e}")
            return []
        out = []
        for r in rows:
            slots = parse_setcode(r[2])
            out.append({"id": int(r[0]), "name": r[1] or "", "setcode": int(r[2]),
                        "slot": slots.index(want), "slots": slots})
        return out

    def describe(self) -> dict:
        """doctor 用：卡池状态一览（永不抛异常）。"""
        return {
            "path": str(self.path) if self.path else "",
            "exists": bool(self.path and Path(self.path).is_file()),
            "available": self.available,
            "count": self.count(),
            "fts": self._fts_table() or "",
            "warnings": list(self.warnings),
        }

    def close(self) -> None:
        """关闭连接（幂等）。"""
        if self._con is not None:
            try:
                self._con.close()
            except sqlite3.Error:
                pass
            self._con = None

    # 上下文管理器：with load() as pool: ...
    def __enter__(self) -> "OfficialPool":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False


def _excerpt(desc: str, field: str, width: int = 48) -> str:
    """从卡文里截出字段引用附近的片段（给 UI 看，一眼判断是不是真字段）。"""
    i = desc.find(field)
    if i < 0:
        return desc[:width]
    lo = max(0, i - width // 2)
    hi = min(len(desc), i + len(field) + width // 2)
    piece = desc[lo:hi].replace("\r\n", " ").replace("\n", " ")
    return ("…" if lo > 0 else "") + piece + ("…" if hi < len(desc) else "")


def load(cdb_path: str | Path | None = None) -> OfficialPool:
    """打开官方卡池（只读）。**任何失败都不抛异常**，返回一个 ``available=False`` 的对象。"""
    return OfficialPool(cdb_path)
