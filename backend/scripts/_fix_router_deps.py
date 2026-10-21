"""把 router 文件里的占位依赖替换成标准依赖。

用法（从仓库根部 crosspilot/ 执行）：
    python scripts/_fix_router_deps.py
"""

from __future__ import annotations

import re
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "crosspilot" / "api"

REPLACEMENTS = (
    ("user: dict[str, Any] = Depends(lambda: None),", "user: dict[str, Any] = Depends(require_user),"),
    ("_: dict[str, Any] = Depends(lambda: None),", "_: dict[str, Any] = Depends(require_admin),"),
    ("admin: dict[str, Any] = Depends(lambda: None),", "admin: dict[str, Any] = Depends(require_admin),"),
    ("Depends(_require_tenant)", "Depends(require_tenant)"),
    ("Depends(_ctx_tenant)", "Depends(require_tenant)"),
)

IMPORT_LINE = "from .deps import ApiContext, get_ctx"
NEW_IMPORT = (
    "from .deps import (\n"
    "    ApiContext,\n"
    "    get_ctx,\n"
    "    optional_user,\n"
    "    require_admin,\n"
    "    require_tenant,\n"
    "    require_user,\n"
    ")"
)


def main() -> int:
    changed = 0
    for path in sorted(API_DIR.glob("*.py")):
        if path.name in {"__init__.py", "deps.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)
        if IMPORT_LINE in text:
            text = text.replace(IMPORT_LINE, NEW_IMPORT)
        # 删掉占位 _require_tenant 定义
        text = re.sub(
            r"\ndef _require_tenant\(\n(?:.*\n)*?    raise NotImplementedError\n",
            "\n",
            text,
        )
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed += 1
            print(f"fixed {path.name}")
        remaining = [
            line.strip()
            for line in text.splitlines()
            if "lambda: None" in line or "_require_tenant" in line
        ]
        if remaining:
            print(f"  !! {path.name} 仍有占位：{remaining}")
    print(f"done, {changed} files changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
