"""router 共享的小工具。

放在单独模块，避免各 router 互相 import（那会形成环）。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from pydantic import ValidationError


def attachment_headers(filename: str) -> dict[str, str]:
    """同时给出 ASCII 回退名与 RFC 5987 文件名，兼容中文与旧客户端。"""
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "download"
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
    }


def validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "field": ".".join(str(p) for p in err.get("loc", ())) or "body",
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]


__all__ = ["attachment_headers", "validation_errors"]
