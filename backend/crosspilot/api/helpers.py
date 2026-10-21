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


def client_ip(request: Any) -> str:
    """取调用方 IP，仅用于限流分桶。

    部署在反向代理后（Render / Vercel）时对端是代理，必须读
    ``X-Forwarded-For`` 的第一段才是真实访客。注意这个头可以被客户端伪造，
    所以它只做「成本很低的滥用门槛」，不作为安全边界——真正的隔离靠租户与角色。
    """
    headers = getattr(request, "headers", None)
    if headers is not None:
        forwarded = headers.get("x-forwarded-for") or headers.get("x-real-ip") or ""
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    client = getattr(request, "client", None)
    host = getattr(client, "host", "") if client else ""
    return (host or "unknown")[:64]


__all__ = ["attachment_headers", "client_ip", "validation_errors"]
