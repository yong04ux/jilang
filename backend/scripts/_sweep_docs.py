"""docs/ 与 README 的路径/命令清扫（monorepo 重组后）。

替换规则：
- ``python -m cli ``            -> ``python -m crosspilot ``
- ``uvicorn app:app``           -> ``uvicorn crosspilot.app:app``
- ``uvicorn worker_service:app``-> ``uvicorn crosspilot.worker_service:app``
- ``web/v2``                    -> ``frontend``
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
TARGETS = [REPO / "README.md"] + sorted((REPO / "docs").glob("*.md"))

RULES = [
    ("python -m cli ", "python -m crosspilot "),
    ("uvicorn app:app", "uvicorn crosspilot.app:app"),
    ("uvicorn worker_service:app", "uvicorn crosspilot.worker_service:app"),
    ("web/v2", "frontend"),
]

total = 0
for path in TARGETS:
    text = path.read_text(encoding="utf-8")
    original = text
    counts = {}
    for old, new in RULES:
        n = text.count(old)
        if n:
            text = text.replace(old, new)
            counts[old] = n
    if text != original:
        path.write_text(text, encoding="utf-8")
        detail = ", ".join(f"{old!r} x{n}" for old, n in counts.items())
        print(f"{path.relative_to(REPO).as_posix()}: {detail}")
        total += sum(counts.values())

print(f"\n共替换 {total} 处")
sys.exit(0)
