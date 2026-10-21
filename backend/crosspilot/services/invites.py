"""租户邀请（阶段 C3）。

背景：原来的注册是开放的，任何人都能建账号。B2B 场景下这不可接受，
但直接关掉注册又会让第一个管理员无法初始化。因此：

- ``CROSSPILOT_ALLOW_OPEN_REGISTRATION``（默认 ``true``）控制自助注册；
- 关闭后，除**首个用户**外，注册必须携带邀请令牌；
- 邀请令牌只存 SHA-256，明文只在创建时返回一次（与登录会话同一策略）；
- 被邀请者注册后自动加入邀请所属租户，同时仍拥有自己的个人空间。

没有做邮件发送：项目没有 SMTP 配置，凭空写一个"发送成功"是假的。
管理员拿到令牌后自行通过 IM/邮件转交，界面上如实说明。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..persistence.db import Database
from ..tenancy import ROLE_RANK, TenantContext, require_role

INVITE_TTL_HOURS = 24 * 7


class InviteError(ValueError):
    """邀请相关的可预期错误（消息可直接展示）。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_invite(
    db: Database, ctx: TenantContext, role: str, ttl_hours: int = INVITE_TTL_HOURS
) -> tuple[dict[str, Any], str]:
    """创建邀请，返回 (记录, 明文令牌)。令牌不会被写入数据库。"""
    require_role(ctx, "admin")
    role = (role or "editor").strip().lower()
    if role not in ROLE_RANK:
        raise InviteError(f"未知角色：{role}")
    if role == "owner":
        raise InviteError("邀请不能授予 owner；所有权只能通过转移获得")
    token = secrets.token_urlsafe(24)
    invite = {
        "invite_id": uuid.uuid4().hex,
        "tenant_id": ctx.tenant_id,
        "role": role,
        "token_hash": _hash_token(token),
        "created_by": ctx.user_id,
        "created_at": _now(),
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(hours=max(1, ttl_hours))
        ).isoformat(),
        "accepted_at": None,
        "accepted_by": None,
    }
    db.create_invite(invite)
    public = {
        "invite_id": invite["invite_id"],
        "role": role,
        "expires_at": invite["expires_at"],
        "created_at": invite["created_at"],
        "note": "令牌只显示一次；项目未接入邮件，请自行通过 IM/邮件转交。",
    }
    return public, token


def resolve_invite(db: Database, token: str) -> dict[str, Any]:
    """校验令牌并返回邀请记录。无效/过期/已用一律同一错误。"""
    if not token:
        raise InviteError("需要邀请令牌才能注册")
    invite = db.get_invite_by_token_hash(_hash_token(token))
    if invite is None:
        raise InviteError("邀请令牌无效")
    if invite.get("accepted_at"):
        raise InviteError("邀请令牌已被使用")
    try:
        expires = datetime.fromisoformat(invite["expires_at"])
    except (ValueError, TypeError) as exc:
        raise InviteError("邀请令牌已损坏") from exc
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise InviteError("邀请令牌已过期")
    return invite


def accept_invite(db: Database, invite: dict[str, Any], user_id: str) -> None:
    """把新用户加入邀请所属租户，并标记令牌已用。"""
    existing = db.get_membership(user_id, invite["tenant_id"])
    if existing is None:
        db.add_member(invite["tenant_id"], user_id, invite["role"])
    db.mark_invite_accepted(invite["invite_id"], user_id)


__all__ = [
    "INVITE_TTL_HOURS",
    "InviteError",
    "accept_invite",
    "create_invite",
    "resolve_invite",
]
