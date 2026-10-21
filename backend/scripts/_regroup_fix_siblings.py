"""修正 6 个新子包内的单点相对导入（恢复脚本 v2 的遗留问题）。

背景：``_regroup_v2.py`` 按「快照里的位置」判断文件是包根文件，对所有
``from .X import ...`` 应用包根规则（``.X`` -> ``.<组>.X``）。但 engine/llm/
market/persistence/ingest/demo 下的文件实际已搬进子包，正确的相对导入是：

- 同组兄弟模块（如 persistence/db.py 导入 migrations）：
  ``from .persistence.migrations import`` -> ``from .migrations import``
- 跨组 / 包根模块（如 engine/listing_llm.py 导入 llm）：
  ``from .llm.llm import`` -> ``from ..llm.llm import``
  ``from .config import``（demo/ 内）-> ``from ..config import``

注意：当前文件里的 dotted 路径**已经是映射后的形态**（.llm.llm /
.persistence.migrations / .config），所以只做「剥组前缀 / 加一点」两种变换，
绝不二次映射（否则会出现 .llm.llm.llm 这种三重路径）。

api/agent/services 三个子包的文件由 v2 的 dest_subpkg 分支正确处理，不在本脚本范围。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "crosspilot"
GROUPS = ("engine", "llm", "market", "persistence", "ingest", "demo")

RE_SINGLE = re.compile(r"^(\s*)from \.([\w.]+) import (.*)$")

changes: list[tuple[Path, str, str]] = []


def fix_line(line: str, group: str) -> str:
    m = RE_SINGLE.match(line)
    if not m:
        return line
    indent, dotted, names = m.groups()
    if dotted.startswith(group + "."):
        new = f"{indent}from .{dotted[len(group) + 1:]} import {names}"
    else:
        new = f"{indent}from ..{dotted} import {names}"
    return new


def main() -> int:
    targets: list[Path] = []
    for group in GROUPS:
        targets += sorted(p for p in (PKG / group).glob("*.py") if p.name != "__init__.py")

    for path in targets:
        group = path.parent.name
        text = path.read_text(encoding="utf-8")
        out_lines = []
        touched = False
        for line in text.splitlines(keepends=True):
            nl = "\n" if line.endswith("\n") else ""
            body = line.rstrip("\n")
            new = fix_line(body, group)
            if new != body:
                changes.append((path, body, new))
                touched = True
            out_lines.append(new + nl)
        if touched:
            path.write_text("".join(out_lines), encoding="utf-8")

    print(f"修正 {len({c[0] for c in changes})} 个文件，{len(changes)} 处导入：")
    for path, old, new in changes[:40]:
        print(f"  {path.relative_to(PKG.parent)}: {old.strip()[:60]}  =>  {new.strip()[:60]}")
    if len(changes) > 40:
        print(f"  ……另 {len(changes) - 40} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
