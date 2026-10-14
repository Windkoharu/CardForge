"""静态自查：未使用的 import / 未使用的模块级私有函数 / TODO 残留。"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
FILES = sorted((ROOT / "cardforge" / "pool").glob("*.py")) + \
    sorted((ROOT / "cardforge" / "export").glob("*.py"))

problems: list[str] = []
for f in FILES:
    src = f.read_text(encoding="utf-8")
    tree = ast.parse(src, str(f))
    imported: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                name = (a.asname or a.name).split(".")[0]
                imported[name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "*":
                    continue
                imported[a.asname or a.name] = node.lineno
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            pass
    # 属性访问的根名字也算用到
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            n = node
            while isinstance(n, ast.Attribute):
                n = n.value
            if isinstance(n, ast.Name):
                used.add(n.id)
    # 字符串里的注解（from __future__ annotations 下注解也是 AST，会被 Name 覆盖）
    text_used = set()
    for name in imported:
        if name in used or f'"{name}"' in src or f"'{name}'" in src or f"{name}." in src:
            text_used.add(name)
    unused = sorted(set(imported) - text_used - {"annotations"})
    if unused:
        problems.append(f"{f.relative_to(ROOT)}: 没用到 {unused}")
    if "TODO" in src or "FIXME" in src:
        problems.append(f"{f.relative_to(ROOT)}: 残留 TODO/FIXME")
    # 模块级私有函数是否被引用（双下划线魔法方法与 PEP 562 钩子不算）
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_") \
                and not node.name.startswith("__"):
            refs = sum(1 for n in ast.walk(tree)
                       if isinstance(n, ast.Name) and n.id == node.name)
            refs += src.count(f"self.{node.name}") + src.count(f"'{node.name}'")
            if refs == 0:
                problems.append(f"{f.relative_to(ROOT)}:{node.lineno}: 私有函数 "
                                f"{node.name}() 从未被引用")

print(f"检查了 {len(FILES)} 个文件")
if problems:
    print("发现问题：")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("没有未使用的 import，也没有残留 TODO / 死代码")
