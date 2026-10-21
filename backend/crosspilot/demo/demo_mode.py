"""演示站机制：BYOK 强制、一键体验临时账号、限流。

三条铁律：

1. **BYOK**：平台不提供 Key。没有配置可用 Key 时，需要调模型的接口返回
   ``428 api_key_required``，前端据此跳转设置页。**不静默降级成规则引擎后
   显示"成功"**——那会让访客误以为真实调用了模型。
2. **固定 demo 账号**：共享、只读示例数据、**禁止保存任何 Key**。
3. **一键体验**：创建 24h 临时账号，独立租户，可以存自己的 Key；
   过期由 ``cleanup-guests`` 命令清理。
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..persistence.db import Database
from ..tenancy import create_personal_tenant

GUEST_USERNAME_PREFIX = "guest_"
GUEST_PASSWORD_BYTES = 18

#: 需要真实模型调用的接口（缺 Key 时返回 428）
KEY_REQUIRED_ACTIONS = {"agent.run", "listing.generate", "provider.test"}


class ApiKeyRequired(RuntimeError):
    """没有可用的 LLM Key；映射为 HTTP 428。"""

    code = "api_key_required"


class DemoAccountError(RuntimeError):
    """演示账号相关操作失败（消息可直接展示）。"""


class RateLimited(RuntimeError):
    """超出限流阈值。"""

    def __init__(self, message: str, *, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 固定 demo 账号
# ---------------------------------------------------------------------------


def ensure_demo_account(
    db: Database, *, username: str, password: str
) -> dict[str, Any] | None:
    """按配置确保 demo 账号存在；未配置密码时视为未启用，返回 None。"""
    if not username or not password:
        return None
    from ..auth import hash_password

    existing = db.get_user_by_username(username)
    if existing is not None:
        return existing
    user_id = uuid.uuid4().hex
    db.create_user(
        user_id,
        username,
        hash_password(password),
        display_name="演示账号",
        is_admin=False,
    )
    create_personal_tenant(db, user_id, username)
    return db.get_user(user_id)


DEMO_USERNAME_RE = re.compile(r"^demo$", re.IGNORECASE)


def is_demo_account(user: dict[str, Any] | None, *, demo_username: str) -> bool:
    if not user:
        return False
    return (user.get("username") or "").lower() == (demo_username or "demo").lower()


def assert_can_store_key(user: dict[str, Any], *, demo_username: str) -> None:
    """固定 demo 账号禁止写入任何 Provider 配置。"""
    if is_demo_account(user, demo_username=demo_username):
        raise DemoAccountError(
            "固定演示账号是共享的，不能保存 API Key。"
            "请使用「一键体验」创建自己的临时账号后再配置。"
        )


# ---------------------------------------------------------------------------
# 一键体验（临时账号）
# ---------------------------------------------------------------------------


def create_guest_account(
    db: Database, *, ttl_hours: int = 24
) -> tuple[dict[str, Any], str, str]:
    """创建临时账号，返回 (user, username, password)。

    用户名带随机后缀，避免与他人冲突；密码随机生成，只在本次响应里出现一次。
    """
    from ..auth import hash_password, issue_session

    token_suffix = secrets.token_hex(4)
    username = f"{GUEST_USERNAME_PREFIX}{token_suffix}"
    password = secrets.token_urlsafe(GUEST_PASSWORD_BYTES)
    expires = datetime.now(timezone.utc) + timedelta(hours=max(1, ttl_hours))

    user_id = uuid.uuid4().hex
    db.create_user(
        user_id,
        username,
        hash_password(password),
        display_name=f"体验账号 {token_suffix}",
        is_admin=False,
    )
    db.mark_guest(user_id, expires.isoformat())
    tenant_id = create_personal_tenant(db, user_id, username)

    # 预置演示店铺：体验账号进来就能在「店铺与渠道」看到带数据的三家店
    from .store_seed import seed_demo_stores

    try:
        seed_demo_stores(db, tenant_id, user_id=user_id)
    except Exception:  # noqa: BLE001 - 店铺预置失败不该挡住登录
        pass

    user = db.get_user(user_id) or {"user_id": user_id, "username": username}
    return user, username, password


def is_guest_expired(user: dict[str, Any]) -> bool:
    if not user.get("is_guest"):
        return False
    raw = user.get("guest_expires_at")
    if not raw:
        return True
    try:
        expires = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires < datetime.now(timezone.utc)


def cleanup_guests(db: Database) -> dict[str, int]:
    """删除过期的临时账号及其数据，返回删除统计。"""
    expired = db.list_expired_guests(_now())
    removed = 0
    for user in expired:
        db.delete_user_cascade(user["user_id"])
        removed += 1
    return {"guests_removed": removed}


# ---------------------------------------------------------------------------
# 限流
# ---------------------------------------------------------------------------

WINDOW_SECONDS = 3600


def _bucket_key(scope: str, identity: str) -> str:
    return f"{scope}:{identity}"


def _window_start(now: datetime) -> str:
    aligned = now.replace(minute=0, second=0, microsecond=0)
    return aligned.isoformat()


def check_rate_limit(
    db: Database,
    *,
    scope: str,
    identity: str,
    limit: int,
    enabled: bool = True,
) -> tuple[int, int]:
    """自增并检查限流；返回 (已用次数, 剩余次数)。超限抛 RateLimited。"""
    if not enabled or limit <= 0:
        return 0, 0
    now = datetime.now(timezone.utc)
    window_start = _window_start(now)
    used = db.bump_rate_limit(_bucket_key(scope, identity), window_start)
    if used > limit:
        retry_after = int((now + timedelta(hours=1)).timestamp()) % 3600 or WINDOW_SECONDS
        raise RateLimited(
            f"已达到每小时上限（{limit} 次），请在下一个整点后重试。",
            retry_after=WINDOW_SECONDS,
        )
    return used, max(0, limit - used)


def rate_limit_headers(used: int, remaining: int, limit: int) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Used": str(used),
    }


__all__ = [
    "ApiKeyRequired",
    "DemoAccountError",
    "GUEST_USERNAME_PREFIX",
    "RateLimited",
    "assert_can_store_key",
    "check_rate_limit",
    "cleanup_guests",
    "create_guest_account",
    "ensure_demo_account",
    "is_demo_account",
    "is_guest_expired",
    "rate_limit_headers",
]
