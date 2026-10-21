"""扁平化 import 改写：把 crosspilot 包的所有导入改成扁平布局。

规则（按文件位置分三类）：
  A. 子包内（crosspilot/{api,agent,services}/*.py）：
       from ..X import ...   -> from X import ...      （X 可带点，如 api.deps）
       from .. import X      -> import X              （__version__ 特判 -> from version import __version__）
       from .X import ...    -> 不动（子包内相对导入仍然合法）
  B. 顶层模块（crosspilot/*.py，将搬到工程根）：
       from .X import ...    -> from X import ...
       from . import X       -> import X              （__version__ 特判同上）
  C. tests/ 与 scripts/：
       from X import ... -> from X import ...
  另：测试里的字符串引用 "crosspilot.agent.x" -> "agent.x"、__import__("crosspilot.x") -> __import__("x")
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent  # scripts/ 的上级即仓库根
PKG = REPO / "crosspilot"
SUBPKG_DIRS = ("api", "agent", "services")

# (编译后的正则, 替换串)；按顺序应用，__version__ 特判放前面
RE_SUB_DOTDOT_NAME = re.compile(r"^(\s*)from \.\.(\w[\w.]*) import")
RE_SUB_DOTDOT_BARE = re.compile(r"^(\s*)from \.\. import\s+(\w+)")
RE_TOP_DOT_NAME = re.compile(r"^(\s*)from \.(\w[\w.]*) import")
RE_TOP_DOT_BARE = re.compile(r"^(\s*)from \. import\s+(\w+)")
RE_ABS = re.compile(r"^(\s*)from crosspilot\.(\w[\w.]*) import")

changes: list[tuple[Path, str, str]] = []


def sub_version(m: re.Match) -> str:
    indent, name = m.group(1), m.group(2)
    if name == "__version__":
        return f"{indent}from version import __version__"
    return f"{indent}import {name}"


def rewrite(path: Path, text: str) -> str:
    rel = path.relative_to(REPO)
    parts = rel.parts
    in_subpkg = len(parts) >= 3 and parts[0] == "crosspilot" and parts[1] in SUBPKG_DIRS
    in_pkg_top = len(parts) == 2 and parts[0] == "crosspilot" and parts[1] != "__init__.py"
    in_tests_scripts = parts[0] in ("tests", "scripts")

    out = []
    for line in text.splitlines(keepends=True):
        nl = "\n" if line.endswith("\n") else ""
        body = line.rstrip("\n")
        if in_subpkg:
            new = RE_SUB_DOTDOT_NAME.sub(lambda m: f"{m.group(1)}from {m.group(2)} import", body)
            if new != body:
                out.append(new + nl)
                changes.append((path, body, new))
                continue
            new = RE_SUB_DOTDOT_BARE.sub(sub_version, body)
        elif in_pkg_top:
            new = RE_TOP_DOT_NAME.sub(lambda m: f"{m.group(1)}from {m.group(2)} import", body)
            if new != body:
                out.append(new + nl)
                changes.append((path, body, new))
                continue
            new = RE_TOP_DOT_BARE.sub(sub_version, body)
        elif in_tests_scripts:
            new = RE_ABS.sub(lambda m: f"{m.group(1)}from {m.group(2)} import", body)
        else:
            new = body
        if new != body:
            changes.append((path, body, new))
        out.append(new + nl)
    return "".join(out)


def main() -> int:
    targets: list[Path] = []
    targets += sorted(PKG.glob("*.py"))
    for d in SUBPKG_DIRS:
        targets += sorted((PKG / d).glob("*.py"))
    targets += sorted((REPO / "tests").glob("*.py"))
    targets += sorted((REPO / "scripts").rglob("*.py"))
    # 去掉一次性脚本自身（其路径引用单独处理）与包 __init__（将删除）
    skip = {PKG / "__init__.py"}
    targets = [t for t in targets if t not in skip and "__pycache__" not in t.parts]

    for path in targets:
        text = path.read_text(encoding="utf-8")
        new_text = rewrite(path, text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")

    # ---- 字符串引用（测试 patch 目标 / __import__ / 一次性脚本路径）----
    string_targets = {
        REPO / "tests" / "test_agent.py": [('"crosspilot.agent.', '"agent.')],
        REPO / "tests" / "test_async_runs.py": [('"crosspilot.agent.', '"agent.')],
        REPO / "tests" / "test_listing.py": [
            ('__import__("crosspilot.listing"', '__import__("listing"'),
            ('__import__("crosspilot.demo_data"', '__import__("demo_data"'),
        ],
        REPO / "scripts" / "_fix_router_deps.py": [
            ('/ "crosspilot" / "api"', '/ "api"'),
        ],
        REPO / "scripts" / "_split_app.py": [
            ('/ "crosspilot" / "app.py"', '/ "app.py"'),
            ('/ "crosspilot" / "api"', '/ "api"'),
        ],
    }
    for path, pairs in string_targets.items():
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for old, new in pairs:
            if old in text:
                text = text.replace(old, new)
                changes.append((path, old, new))
        path.write_text(text, encoding="utf-8")

    print(f"共修改 {len({c[0] for c in changes})} 个文件，{len(changes)} 处：")
    for path, old, new in changes:
        print(f"  {path.relative_to(REPO)}: {old.strip()[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
