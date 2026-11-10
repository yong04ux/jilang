"""多租户上下文。

铁律：

1. **租户 ID 只能来自已认证用户的成员关系**。客户端可以传 ``X-Tenant-Id``
   表示"我想切到哪个租户"，但必须校验该用户确实属于它，否则 403。
2. 不传时使用用户最早加入的租户（个人空间），因此单用户场景无感知。
3. 所有业务查询都必须带上 ``tenant_id``，与 ``user_id`` 一起构成双重过滤。

角色：

| 角色 | 权限 |
|---|---|
| owner  | 全部，含删除租户 |
| admin  | 成员管理、数据源、店铺、模型配置 |
| editor | 创建/运行任务、编辑 Listing、上传数据 |
| viewer | 只读 |
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .persistence.db import Database

ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3, "owner": 4}

# 不同操作要求的最低角色
ROLE_READ = "viewer"
ROLE_WRITE = "editor"
ROLE_MANAGE = "admin"


class TenantError(PermissionError):
    """租户解析或权限校验失败，消息可直接展示给用户。"""


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    tenant_name: str
    user_id: str
    role: str

    @property
    def rank(self) -> int:
        return ROLE_RANK.get(self.role, 0)

    def can(self, minimum: str) -> bool:
        return self.rank >= ROLE_RANK.get(minimum, 99)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_personal_tenant(db: Database, user_id: str, username: str) -> str:
    """为新用户创建个人空间并设为 owner，返回 tenant_id。"""
    tenant_id = uuid.uuid4().hex
    slug = f"personal-{user_id[:12]}"
    db.create_tenant(tenant_id, f"{username} 的个人空间", slug)
    db.add_member(tenant_id, user_id, "owner")
    return tenant_id


def resolve_tenant(db: Database, user: dict, requested: str | None = None) -> TenantContext:
    """把已认证用户解析成租户上下文。

    ``requested`` 为空时取最早加入的租户；不为空时必须校验成员关系。
    """
    user_id = user["user_id"]
    if requested:
        membership = db.get_membership_with_tenant(user_id, requested)
        if membership is None:
            # 不区分"租户不存在"与"你不是成员"，避免探测他人租户
            raise TenantError("无权访问该租户")
        return TenantContext(
            tenant_id=requested,
            tenant_name=membership.get("tenant_name") or "",
            user_id=user_id,
            role=membership["role"],
        )

    membership = db.get_membership_with_tenant(user_id)
    if membership is None:
        # 兜底：历史用户可能在迁移后仍无租户，这里补建而不是报错
        tenant_id = create_personal_tenant(db, user_id, user.get("username") or user_id)
        return TenantContext(
            tenant_id=tenant_id,
            tenant_name=f"{user.get('username') or user_id} 的个人空间",
            user_id=user_id,
            role="owner",
        )
    return TenantContext(
        tenant_id=membership["tenant_id"],
        tenant_name=membership.get("tenant_name") or "",
        user_id=user_id,
        role=membership["role"],
    )


def require_role(ctx: TenantContext, minimum: str) -> None:
    if not ctx.can(minimum):
        raise TenantError(f"当前角色（{ctx.role}）无权执行此操作，需要 {minimum} 及以上")


def invite_member(db: Database, ctx: TenantContext, user_id: str, role: str) -> None:
    """把已有用户加入当前租户。仅 admin/owner 可操作。"""
    require_role(ctx, ROLE_MANAGE)
    if role not in ROLE_RANK:
        raise TenantError(f"未知角色：{role}")
    existing = db.get_membership(user_id, ctx.tenant_id)
    if existing is not None:
        raise TenantError("该用户已是本租户成员")
    db.add_member(ctx.tenant_id, user_id, role)


__all__ = [
    "ROLE_MANAGE",
    "ROLE_RANK",
    "ROLE_READ",
    "ROLE_WRITE",
    "TenantContext",
    "TenantError",
    "create_personal_tenant",
    "invite_member",
    "require_role",
    "resolve_tenant",
]
