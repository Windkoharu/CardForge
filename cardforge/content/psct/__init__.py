"""PSCT 卡文生成与校验引擎（本项目差异化能力之一）。

模块分工
--------
``rules.py``
    **规则唯一来源**：标点三段式、连接词四象限、HOPT 六种写法、编号、时点词、
    效果句式模板、校验规则清单。生成器与校验器都从这里取规则。
``lexicon.py``
    多语言术语与句式词库（``data/lexicons/*.json`` 的访问层，内置兜底表，
    文件缺失也能工作）。**永不返回 None**。
``gen.py``
    结构化效果 IR → 多语言 PSCT 卡文（``①：条件…才能发动。处理。`` 版式）。
``lint.py``
    **确定性**校验器（G-text 门）：标点、编号、HOPT、时点、代价位置、取对象、
    字段引用、连接词、术语、版式长度。

快速上手
--------
::

    from cardforge.content.psct import compose_all, lint, fill_spec

    texts = compose_all(spec, ["zh_cn", "ja", "en"])   # 生成
    fill_spec(spec, ["zh_cn", "ja", "en"])             # 写回 text_i18n
    for issue in lint(spec):                           # 校验
        print(issue.level, issue.code, issue.message)

已知边界（诚实声明）
--------------------
* 原生句式模板只覆盖 **zh_cn / ja / en**；ko / zh_tw / 西欧语言**降级到 en**
  并在 :func:`compose_with_meta` 的返回值里标注（不硬造）。
* 卡文长度是**版面估算**（见 ``rules.TEXT_BOX``），不是官方规定。
* 「日文分号」在调研报告里标注为未找到明文规定（F1 第 12 项），本项目按
  「不使用」处理（``LANGS[*].uses_semicolon``）。
"""
from __future__ import annotations

from . import gen, lexicon, lint, rules
from .gen import (
    compose, compose_all, compose_all_meta, compose_all_pendulum,
    compose_pendulum, compose_with_meta, effect_count_lines, effect_to_text,
    fill_spec, flavor, st_label, type_line,
)
from .lexicon import (
    by_category, conjunction, coverage_report, hopt, hopt_single, patterns,
    punctuation, reload, term, term_or_fallback, terms,
)
from .lint import RULES, lint_text

__all__ = [
    # 契约要求的 8 个入口
    "compose", "compose_all", "type_line", "st_label", "flavor",
    "lint", "lint_text", "lexicon",
    # 生成器补充
    "effect_to_text", "compose_pendulum", "compose_all_pendulum",
    "compose_with_meta", "compose_all_meta", "fill_spec", "effect_count_lines",
    # 词库补充
    "terms", "term", "term_or_fallback", "by_category", "patterns",
    "punctuation", "conjunction", "hopt", "hopt_single", "reload",
    "coverage_report",
    # 规则与子模块
    "rules", "gen", "RULES",
]
