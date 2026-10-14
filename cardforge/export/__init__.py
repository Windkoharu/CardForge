"""导出层 —— 把 ``CardSpec`` 变成 EDOPro 能直接读的东西。

分模块职责::

    strings.py     strings.conf 渲染/解析（!setname / !counter）
    expansions.py  expansions 打包（cdb + pics + script + strings.conf + README）+ G5 自检
    ydk.py         .ydk 卡组读写与合法性校验
    install.py     探测 EDOPro 安装目录、备份式安装、打成可分发 zip
    mdpro3.py      MDPro3 / MDPro4 的 .ypk 扩展卡包（Unity 客户端，布局与 EDOPro 不同）

本模块用 PEP 562 的 ``__getattr__`` **惰性**转出子模块与常用符号：``import
cardforge.export`` 本身不加载 sqlite3/Pillow 的活儿，只有真正访问
``cardforge.export.build`` / ``cardforge.export.expansions`` 时才付出代价。

三个名字与子模块同名（``install`` / ``ydk`` / ``strings``），所以子模块名走
:data:`_SUBMODULES` 优先返回**模块对象**，其余符号走 :data:`_LAZY` 取子模块属性。
"""
from __future__ import annotations

__all__ = [
    # 子模块
    "expansions", "strings", "ydk", "install", "mdpro3",
    # expansions
    "build", "verify", "file_tree", "pack_stats", "pack_layout", "needs_script",
    "pic_size_ok", "PIC_SIZE", "MANIFEST_NAME",
    # strings
    "render", "parse", "merge", "hexkey", "write_strings", "read_strings",
    # ydk
    "ydk_write", "ydk_read", "ydk_validate", "ydk_to_text", "ydk_from_text",
    # install
    "find_edopro", "find_candidates", "install_pack", "make_repo_pack",
    "repo_config_block", "is_edopro_dir",
    # mdpro3
    "mdpro3_build", "mdpro3_verify", "mdpro3_detect", "mdpro3_client_info",
    "mdpro3_import_hint", "MDPRO3_SIZE",
]

#: 子模块名 —— 直接返回模块对象
_SUBMODULES: tuple[str, ...] = ("expansions", "strings", "ydk", "install", "mdpro3")

#: 符号名 → 所在子模块
_LAZY: dict[str, str] = {
    # ── expansions ──
    "build": "expansions", "verify": "expansions", "file_tree": "expansions",
    "pack_stats": "expansions", "pack_layout": "expansions",
    "needs_script": "expansions", "pic_size_ok": "expansions",
    "PIC_SIZE": "expansions", "MANIFEST_NAME": "expansions",
    # ── strings ──
    "render": "strings", "parse": "strings", "merge": "strings",
    "hexkey": "strings", "write_strings": "strings", "read_strings": "strings",
    # ── ydk（避开与子模块同名的 write/read/validate）──
    "ydk_write": "ydk", "ydk_read": "ydk", "ydk_validate": "ydk",
    "ydk_to_text": "ydk", "ydk_from_text": "ydk",
    # ── install（避开与子模块同名的 install）──
    "find_edopro": "install", "find_candidates": "install",
    "install_pack": "install", "make_repo_pack": "install",
    "repo_config_block": "install", "is_edopro_dir": "install",
    # ── mdpro3（build/verify/detect 与 expansions/install 的同名，加前缀避开）──
    "mdpro3_build": "mdpro3", "mdpro3_verify": "mdpro3", "mdpro3_detect": "mdpro3",
    "mdpro3_client_info": "mdpro3", "mdpro3_import_hint": "mdpro3",
    "MDPRO3_SIZE": "mdpro3",
}


def __getattr__(name: str):
    """PEP 562 惰性转发。"""
    from importlib import import_module
    if name in _SUBMODULES:
        value = import_module(f".{name}", __name__)
    else:
        module = _LAZY.get(name)
        if module is None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        mod = import_module(f".{module}", __name__)
        value = getattr(mod, {
            "ydk_write": "write", "ydk_read": "read", "ydk_validate": "validate",
            "ydk_to_text": "to_text", "ydk_from_text": "from_text",
            "install_pack": "install", "write_strings": "write",
            "mdpro3_build": "build", "mdpro3_verify": "verify",
            "mdpro3_detect": "detect", "mdpro3_client_info": "client_info",
            "mdpro3_import_hint": "import_hint",
            "read_strings": "read",
        }.get(name, name))
    globals()[name] = value          # 转发后固定下来，后续访问不再走 __getattr__
    return value


def __dir__() -> list[str]:
    """让 ``dir(cardforge.export)`` 同时列出已转出与尚未加载的惰性符号。"""
    return sorted(set(globals()) | set(_LAZY) | set(_SUBMODULES))
