"""账号、认证与会话。

包含：注册 / 登录 / 登出 / 一键体验 / 改密 / 头像 / 管理员用户列表 / 租户与成员。
"""

from __future__ import annotations

import re
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
from .helpers import client_ip

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
def auth_status(
    request: Request, ctx: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    """前端启动时调用：是否需要初始化、当前是否已登录。"""
    token = extract_token(request)
    user = resolve_session(ctx.db, token) if token else None
    settings = ctx.settings
    # 只查一次：needs_setup 与 user_count 都需要同一份统计
    user_count = ctx.db.count_users()
    return {
        "needs_setup": user_count == 0,
        "authenticated": user is not None,
        "user": public_user(user) if user else None,
        "user_count": user_count,
        "allow_registration": settings.allow_open_registration,
        "demo_account": settings.is_demo_account_enabled,
        "guest_ttl_hours": settings.guest_ttl_hours,
    }


@router.post("/api/auth/demo")
async def auth_demo(
    request: Request,
    response: Response,
    payload: dict[str, Any] | None = None,
    ctx: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """一键体验：创建 24h 临时账号（独立租户，可存自己的 Key）。

    这个入口不需要任何凭据，公网部署后是最容易被刷的地方：按 IP 限流，
    避免有人写个循环把账号表灌满（每个账号还会带租户与演示店铺）。
    """
    ctx.rate_limit_identity(
        client_ip(request), "auth.demo", ctx.settings.rate_limit_guest_per_hour
    )
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
def auth_me(
    ctx: ApiContext = Depends(get_ctx),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"user": public_user(user)}


_AVATAR_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=]+$")
_AVATAR_MAX_CHARS = 400_000


def _reject_shared_demo(ctx: ApiContext, user: dict[str, Any]) -> None:
    """共享体验账号是所有访客共用的，改了用户名/密码就等于把入口锁死。"""
    if str(user.get("username") or "").lower() == (ctx.settings.demo_username or "demo").lower():
        raise HTTPException(
            status_code=403,
            detail="共享体验账号不能修改用户名或密码；请用「一键体验」创建你自己的临时账号",
        )


@router.put("/api/auth/display-name")
def update_display_name(
    payload: dict[str, Any],
    ctx: ApiContext = Depends(get_ctx),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """昵称可改，用户名不可改：用户名登录时要对，改名只会让人登不上。"""
    _reject_shared_demo(ctx, user)
    nickname = str(payload.get("display_name") or "").strip()
    if not nickname or len(nickname) > 32:
        raise HTTPException(status_code=422, detail="昵称需要 1-32 个字符")
    ctx.db.update_display_name(user["user_id"], nickname)
    updated = ctx.db.get_user(user["user_id"]) or {**user, "display_name": nickname}
    return {"ok": True, "user": public_user(updated)}


_PHONE_RE = re.compile(r"^\+?[0-9]{6,20}$")


def _normalize_phone(raw: Any) -> str | None:
    """去掉空格与短横线，并把大陆号码统一成 11 位（+86 / 0086 视为同一号码）。

    不猜国家码：只有明确带 86 前缀时才剥掉，其它号码保留原样。
    """
    text = re.sub(r"[\s-]", "", str(raw or ""))
    if not text:
        return None
    if text.startswith("0086"):
        text = text[4:]
    elif text.startswith("+86"):
        text = text[3:]
    if not _PHONE_RE.match(text):
        raise HTTPException(status_code=422, detail="手机号格式不正确，请填 6-20 位数字，可带国际区号")
    return text


@router.put("/api/auth/phone")
def update_phone(
    payload: dict[str, Any],
    ctx: ApiContext = Depends(get_ctx),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    _reject_shared_demo(ctx, user)
    phone = _normalize_phone(payload.get("phone"))
    if phone is not None:
        occupied = ctx.db.get_user_by_phone(phone)
        if occupied is not None and occupied["user_id"] != user["user_id"]:
            raise HTTPException(status_code=409, detail="这个手机号已经绑定了其它账号")
    try:
        ctx.db.update_phone(user["user_id"], phone)
    except Exception as exc:  # noqa: BLE001 - 并发写入会撞唯一索引
        raise HTTPException(status_code=409, detail="这个手机号已经绑定了其它账号") from exc
    updated = ctx.db.get_user(user["user_id"]) or {**user, "phone": phone}
    return {"ok": True, "user": public_user(updated)}


@router.put("/api/auth/avatar")
def update_avatar(
    payload: dict[str, Any],
    ctx: ApiContext = Depends(get_ctx),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """设置或清除头像。``avatar`` 传 null / 空串表示清除。

    只收 data URL：客户端先把图压到 128px JPEG 再传。
    校验失败一律 422，不做"尽力保存"——存进去一张裂开的图比报错更难查。
    """
    raw = payload.get("avatar")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        ctx.db.update_avatar(user["user_id"], None)
        return {"ok": True, "avatar": None}
    if not isinstance(raw, str) or len(raw) > _AVATAR_MAX_CHARS or not _AVATAR_RE.match(raw):
        raise HTTPException(status_code=422, detail="头像格式不正确，请重新选择图片")
    ctx.db.update_avatar(user["user_id"], raw)
    return {"ok": True, "avatar": raw}


@router.post("/api/auth/password")
async def change_password(
    payload: dict[str, Any],
    ctx: ApiContext = Depends(get_ctx),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    _reject_shared_demo(ctx, user)
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
