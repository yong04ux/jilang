"""账号、认证与会话。

包含：注册 / 登录 / 登出 / 一键体验 / 改密 / 管理员用户列表 / 租户与成员。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth import (
    SESSION_COOKIE,
    AuthError,
    extract_token,
    hash_password,
    issue_session,
    login_user,
    public_user,
    register_user,
    resolve_session,
    verify_password,
)
from ..demo.demo_mode import create_guest_account
from ..services import audit
from ..services import invites as invite_service
from ..tenancy import ROLE_MANAGE, TenantContext, TenantError, invite_member, require_role
from .deps import ApiContext, get_ctx, require_admin, require_tenant, require_user

router = APIRouter(tags=["账号"])


def _set_session_cookie(ctx: ApiContext, response: Response, token: str) -> None:
    """会话 Cookie。生产（HTTPS）必须 ``cookie_secure=true``。"""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=7 * 24 * 3600,
        httponly=True,
        secure=bool(ctx.settings.cookie_secure),
        samesite="lax",
        path="/",
    )


# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------


@router.get("/api/auth/status")
async def auth_status(
    request: Request, ctx: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    """前端启动时调用：是否需要初始化、当前是否已登录。"""
    token = extract_token(request)
    user = resolve_session(ctx.db, token) if token else None
    settings = ctx.settings
    return {
        "needs_setup": ctx.db.count_users() == 0,
        "authenticated": user is not None,
        "user": public_user(user) if user else None,
        "user_count": ctx.db.count_users(),
        "allow_registration": settings.allow_open_registration,
        "demo_account": settings.is_demo_account_enabled,
        "guest_ttl_hours": settings.guest_ttl_hours,
    }


@router.post("/api/auth/demo")
async def auth_demo(
    response: Response,
    payload: dict[str, Any] | None = None,
    ctx: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """一键体验：创建 24h 临时账号（独立租户，可存自己的 Key）。"""
    ttl = ctx.settings.guest_ttl_hours
    try:
        user, username, password = create_guest_account(ctx.db, ttl_hours=ttl)
    except Exception as exc:  # noqa: BLE001 - 创建失败要给出可读原因
        raise HTTPException(status_code=500, detail=f"创建临时账号失败：{exc}") from exc

    # 直接签约会话，前端无需再走登录
    _set_session_cookie(ctx, response, issue_session(ctx.db, user["user_id"]))
    audit.record(
        ctx.db,
        tenant_id="",
        actor_id=user["user_id"],
        action="auth.demo",
        target_type="user",
        target_id=user["user_id"],
        detail={"username": username, "ttl_hours": ttl},
    )
    return {
        "user": public_user(ctx.db.get_user(user["user_id"]) or user),
        "username": username,
        "password": password,
        "expires_in_hours": ttl,
        "note": "临时账号数据会在过期后被自动清理；请及时保存需要保留的内容。",
    }


@router.post("/api/auth/register")
async def auth_register(
    payload: dict[str, Any],
    response: Response,
    ctx: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))
    display_name = payload.get("display_name")
    invite_token = str(payload.get("invite_token") or "").strip()
    settings = ctx.settings

    invite: dict[str, Any] | None = None
    if ctx.db.count_users() > 0 and not settings.allow_open_registration:
        # 关闭自助注册后，除首个用户外必须持邀请令牌
        try:
            invite = invite_service.resolve_invite(ctx.db, invite_token)
        except invite_service.InviteError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    elif invite_token:
        try:
            invite = invite_service.resolve_invite(ctx.db, invite_token)
        except invite_service.InviteError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = register_user(ctx.db, username, password, display_name)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if invite is not None:
        invite_service.accept_invite(ctx.db, invite, result.user["user_id"])
    _set_session_cookie(ctx, response, result.token)
    ctx.audit_user(
        {"user_id": result.user["user_id"]},
        audit.ACTION_REGISTER,
        target_type="user",
        target_id=result.user["user_id"],
        detail={"username": result.user["username"], "invited": invite is not None},
        tenant_id=invite["tenant_id"] if invite else None,
    )
    return {
        "user": result.user,
        "token": result.token,
        "invited_to": invite["tenant_id"] if invite else None,
    }


@router.post("/api/auth/login")
async def auth_login(
    payload: dict[str, Any],
    response: Response,
    ctx: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    try:
        result = login_user(
            ctx.db,
            str(payload.get("username", "")),
            str(payload.get("password", "")),
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_session_cookie(ctx, response, result.token)
    ctx.audit_user(
        {"user_id": result.user["user_id"]},
        audit.ACTION_LOGIN,
        target_type="user",
        target_id=result.user["user_id"],
        detail={"username": result.user["username"]},
    )
    return {"user": result.user, "token": result.token}


@router.post("/api/auth/logout")
async def auth_logout(
    request: Request, response: Response, ctx: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    from ..auth import _hash_token

    token = extract_token(request)
    if token:
        session_user = resolve_session(ctx.db, token)
        if session_user is not None:
            ctx.audit_user(
                session_user,
                audit.ACTION_LOGOUT,
                target_type="user",
                target_id=session_user["user_id"],
            )
        ctx.db.delete_session(_hash_token(token))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/api/auth/me")
async def auth_me(
    ctx: ApiContext = Depends(get_ctx),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"user": public_user(user)}


@router.post("/api/auth/password")
async def change_password(
    payload: dict[str, Any],
    ctx: ApiContext = Depends(get_ctx),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    current = str(payload.get("current_password", ""))
    new = str(payload.get("new_password", ""))
    if not verify_password(current, user["password_hash"]):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    try:
        ctx.db.update_password_hash(user["user_id"], hash_password(new))
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ctx.audit_user(
        user,
        audit.ACTION_PASSWORD_CHANGE,
        target_type="user",
        target_id=user["user_id"],
    )
    # 改密后让其它会话失效；当前会话也要重新登录
    ctx.db.delete_user_sessions(user["user_id"])
    return {"ok": True, "detail": "密码已更新，请重新登录"}


# ---------------------------------------------------------------------------
# 管理员
# ---------------------------------------------------------------------------


@router.get("/api/admin/users")
async def admin_list_users(
    ctx: ApiContext = Depends(get_ctx),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return {"users": ctx.db.list_users(), "legacy": ctx.db.count_legacy_records()}


@router.post("/api/admin/claim-legacy")
async def admin_claim_legacy(
    ctx: ApiContext = Depends(get_ctx),
    user: dict[str, Any] = Depends(require_admin),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """把启用账号前产生的历史记录认领给当前管理员（显式操作）。"""
    claimed = ctx.db.claim_legacy_records(user["user_id"], tenant.tenant_id)
    return {"ok": True, "claimed": claimed}


# ---------------------------------------------------------------------------
# 租户与成员
# ---------------------------------------------------------------------------


@router.get("/api/tenants")
async def list_tenants(
    ctx: ApiContext = Depends(get_ctx),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """当前用户可访问的租户列表（来自成员关系，不接受客户端伪造）。"""
    return {"items": ctx.db.list_memberships(user["user_id"])}


@router.get("/api/tenants/current")
async def current_tenant(
    ctx: ApiContext = Depends(get_ctx),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return {
        "tenant_id": tenant.tenant_id,
        "name": tenant.tenant_name,
        "role": tenant.role,
        "user_id": tenant.user_id,
        "stats": ctx.db.tenant_stats(tenant.tenant_id),
    }


@router.get("/api/tenants/members")
async def tenant_members(
    ctx: ApiContext = Depends(get_ctx),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return {"items": ctx.db.list_tenant_members(tenant.tenant_id)}


@router.post("/api/tenants/members")
async def add_tenant_member(
    payload: dict[str, Any],
    ctx: ApiContext = Depends(get_ctx),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    username = str(payload.get("username", "")).strip().lower()
    role = str(payload.get("role", "editor")).strip().lower()
    target = ctx.db.get_user_by_username(username)
    if target is None:
        raise HTTPException(status_code=404, detail=f"用户不存在: {username}")
    try:
        invite_member(ctx.db, tenant, target["user_id"], role)
    except TenantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ctx.audit_context(
        tenant,
        audit.ACTION_MEMBER_INVITE,
        target_type="user",
        target_id=target["user_id"],
        detail={"role": role, "username": username},
    )
    return {"ok": True, "items": ctx.db.list_tenant_members(tenant.tenant_id)}


@router.get("/api/tenants/invites")
async def list_tenant_invites(
    ctx: ApiContext = Depends(get_ctx),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(tenant, ROLE_MANAGE)
    return {"items": ctx.db.list_invites(tenant.tenant_id)}


@router.post("/api/tenants/invites")
async def create_tenant_invite(
    payload: dict[str, Any],
    ctx: ApiContext = Depends(get_ctx),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """创建邀请令牌。令牌明文只返回一次，项目未接入邮件发送。"""
    try:
        invite, token = invite_service.create_invite(
            ctx.db, tenant, str(payload.get("role", "editor"))
        )
    except invite_service.InviteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TenantError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    ctx.audit_context(
        tenant,
        audit.ACTION_INVITE_CREATE,
        target_type="invite",
        target_id=invite["invite_id"],
        detail={"role": invite["role"]},
    )
    return {"invite": invite, "token": token}


__all__ = ["router"]
