"""用户认证：密码哈希、会话令牌、请求级依赖。

设计要点：
1. **密码**用 ``hashlib.scrypt`` 加盐哈希（标准库），从不存明文，也不可逆。
2. **会话令牌**是随机 32 字节，库里只存其 SHA-256，**即使数据库泄露也无法直接冒用**。
3. 令牌通过 ``Authorization: Bearer <token>`` 传递，也接受 ``Cookie: cp_session``
   （HTML 页面用 HttpOnly Cookie 更安全）。
4. 第一个注册的用户自动成为管理员（用于认领历史数据、管理用户）。
5. 会话有过期时间，过期即失效；登出会删除对应会话。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, status

from .persistence.db import Database

SESSION_COOKIE = "cp_session"
SESSION_TTL_HOURS = 24 * 7
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
# scrypt 成本：约 50ms/次，兼顾安全与登录体验
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_HASH_LEN = 32


class AuthError(ValueError):
    """认证相关的可预期错误（消息可直接展示给用户）。"""


# ---------------------------------------------------------------------------
# 密码
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise AuthError("密码至少 8 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_HASH_LEN,
    )
    return "scrypt$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$", 2)
    except (ValueError, AttributeError):
        return False
    if scheme != "scrypt":
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    expected = bytes.fromhex(digest_hex)
    candidate = hashlib.scrypt(
        (password or "").encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=len(expected),
    )
    return hmac.compare_digest(candidate, expected)


def validate_username(username: str) -> str:
    text = (username or "").strip()
    if not _USERNAME_RE.match(text):
        raise AuthError("用户名需为 3-32 位字母、数字、下划线、点或短横线")
    return text.lower()


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(db: Database, user_id: str, ttl_hours: int = SESSION_TTL_HOURS) -> str:
    """创建会话，返回**明文令牌**（只在此刻出现一次，库里只存哈希）。"""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    db.create_session(_hash_token(token), user_id, expires.isoformat())
    return token


#: 会话表字段；JOIN 查回后要把这些从"用户"字典里剔除
_SESSION_FIELDS = ("token_hash", "expires_at", "last_seen_at", "session_created_at")

#: ``last_seen_at`` 的更新间隔。每次请求都写一次会让只读页面也产生写入，
#: 并且多一次数据库往返；60 秒粒度对"最后活跃"语义足够。
TOUCH_INTERVAL_SECONDS = 60


def _should_touch(last_seen_at: Any) -> bool:
    if not last_seen_at:
        return True
    try:
        seen = datetime.fromisoformat(str(last_seen_at))
    except (ValueError, TypeError):
        return True
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - seen).total_seconds() >= TOUCH_INTERVAL_SECONDS


def resolve_session(db: Database, token: str) -> dict[str, Any] | None:
    """令牌 -> 用户。过期、无效、用户不存在都返回 None。"""
    if not token:
        return None
    record = db.get_session_user(_hash_token(token))
    if record is None:
        return None
    try:
        expires = datetime.fromisoformat(record["expires_at"])
    except (ValueError, TypeError):
        return None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete_session(record["token_hash"])
        return None
    user = {key: value for key, value in record.items() if key not in _SESSION_FIELDS}
    if not user.get("user_id"):
        return None
    if _should_touch(record.get("last_seen_at")):
        db.touch_session(record["token_hash"])
    return user


def extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    cookie = request.cookies.get(SESSION_COOKIE)
    return cookie or None


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    """只暴露安全的字段，绝不返回 password_hash。"""
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "is_admin": bool(user.get("is_admin")),
        "is_guest": bool(user.get("is_guest")),
        "guest_expires_at": user.get("guest_expires_at"),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


# ---------------------------------------------------------------------------
# 注册 / 登录
# ---------------------------------------------------------------------------


@dataclass
class AuthResult:
    user: dict[str, Any]
    token: str


def register_user(
    db: Database, username: str, password: str, display_name: str | None = None
) -> AuthResult:
    name = validate_username(username)
    if db.get_user_by_username(name) is not None:
        raise AuthError("该用户名已被使用")
    is_first = db.count_users() == 0
    user_id = uuid.uuid4().hex
    password_hash = hash_password(password)
    created = db.create_user(
        user_id,
        name,
        password_hash,
        display_name=display_name or name,
        is_admin=is_first,
    )
    db.touch_last_login(user_id)
    # 每个新用户自动拥有一个个人租户，保证多租户改造后新账号立即可用
    from .tenancy import create_personal_tenant

    create_personal_tenant(db, user_id, name)
    created["created_at"] = None
    stored = db.get_user(user_id) or created
    return AuthResult(user=public_user(stored), token=issue_session(db, user_id))


def login_user(db: Database, username: str, password: str) -> AuthResult:
    record = db.get_user_by_username(username)
    # 无论用户是否存在都做一次哈希校验，避免通过响应时间枚举用户名
    stored_hash = record["password_hash"] if record else hash_password("dummy-password-for-timing")
    if not verify_password(password, stored_hash) or record is None:
        raise AuthError("用户名或密码不正确")
    db.touch_last_login(record["user_id"])
    return AuthResult(user=public_user(db.get_user(record["user_id"]) or record), token=issue_session(db, record["user_id"]))


# ---------------------------------------------------------------------------
# FastAPI 依赖
# ---------------------------------------------------------------------------


def make_require_user(db: Database):
    """构造一个 FastAPI 依赖，从请求中解析当前用户。"""

    def require_user(request: Request) -> dict[str, Any]:
        token = extract_token(request)
        user = resolve_session(db, token) if token else None
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未登录或会话已过期，请重新登录",
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.user = user
        return user

    return require_user


def make_require_admin(db: Database):
    require_user = make_require_user(db)

    def require_admin(request: Request) -> dict[str, Any]:
        user = require_user(request)
        if not user.get("is_admin"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
        return user

    return require_admin


__all__ = [
    "AuthError",
    "AuthResult",
    "SESSION_COOKIE",
    "SESSION_TTL_HOURS",
    "extract_token",
    "hash_password",
    "issue_session",
    "login_user",
    "make_require_admin",
    "make_require_user",
    "public_user",
    "register_user",
    "resolve_session",
    "validate_username",
    "verify_password",
]
