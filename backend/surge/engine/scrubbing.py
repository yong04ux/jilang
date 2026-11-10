"""敏感字段脱敏（审计日志与模型上下文共用）。

规则只有一条：**按字段名 + 明显凭据形态识别，绝不把凭据原样写进日志、
审计明细或 Prompt**。这里不做"猜密码"，而是：

1. 字段名命中敏感词（token / secret / password / api key / authorization /
   credential）→ 值替换为 ``***``；
2. 自由文本中形如 ``sk-xxxx``、``Bearer xxxx`` 的片段 → 替换为 ``***``；
3. 其余结构原样保留，避免脱敏过度导致审计失去意义。
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "***"

_SENSITIVE_WORDS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
    "access_key",
)

_KEY_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
)


def is_sensitive_key(key: str) -> bool:
    normalized = (key or "").strip().lower().replace("-", "_").replace(" ", "_")
    return any(word in normalized for word in _SENSITIVE_WORDS)


def scrub_text(text: str) -> str:
    cleaned = text
    for pattern in _KEY_PATTERNS:
        cleaned = pattern.sub(REDACTED, cleaned)
    return cleaned


def scrub(value: Any) -> Any:
    """递归脱敏 dict/list，返回新对象（不修改入参）。"""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if is_sensitive_key(str(key)):
                result[key] = REDACTED
            else:
                result[key] = scrub(item)
        return result
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value


# 语义别名：模型上下文与审计明细使用同一套规则
scrub_for_llm = scrub


__all__ = [
    "REDACTED",
    "is_sensitive_key",
    "scrub",
    "scrub_for_llm",
    "scrub_text",
]
