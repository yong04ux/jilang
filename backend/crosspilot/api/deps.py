"""HTTP 层共享依赖：所有 router 的公共接缝。

为什么要有这一层
================

原来 88 个端点是 ``create_app()`` 里的嵌套函数，共享 15 个闭包变量
（``db`` / ``require_user`` / ``audit_user`` / ``require_llm_provider``…）。
闭包让「拆分文件」不可能：端点一旦搬出函数体，就再也看不到那些变量。

这里的做法：把闭包变成**一个显式的依赖对象**（``ApiContext``），
由 ``create_app()`` 构造一次，通过 ``app.state.ctx`` 交给各 router。
端点只依赖 ``ApiContext`` 这一个接口，不再依赖外层函数的词法作用域。

这样做的收益（不是"拆文件好看"）：
- 端点可以被独立导入、独立测试，不需要先跑 ``create_app()``；
- 新增端点只需 ``ctx: ApiContext = Depends(get_ctx)``，不用改 ``create_app()``；
- ``create_app()`` 收敛成"装配 + 挂载"，不再是一千行闭包。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request

from ..config import Settings, get_settings
from ..persistence.db import Database
from ..auth import extract_token, resolve_session
from ..demo.demo_mode import (
    DemoAccountError,
    RateLimited,
    assert_can_store_key,
    check_rate_limit,
    rate_limit_headers,
)
from ..llm.model_settings import ModelSettingsService
from ..llm.provider_configs import ProviderConfigService
from ..llm.providers import RuleProvider, build_provider
from ..persistence.secrets import SecretBox, SecretError
from ..services import audit
from ..persistence.storage import ObjectStorage
from ..tenancy import TenantContext, TenantError, resolve_tenant

#: 需要真实模型调用时缺 Key 的 428 载荷（前端据此跳设置页）
API_KEY_REQUIRED = {
    "code": "api_key_required",
    "action": "open_settings",
}


@dataclass
class ApiContext:
    """所有 router 共享的一次性装配结果。

    字段都是有明确职责的协作者；端点只通过它们工作，不直接摸 ``app``。
    认证依赖（``require_user`` / ``require_admin`` / ``require_tenant``）**不在
    这里**——它们是 FastAPI 依赖，由本模块直接提供，端点用 ``Depends(...)`` 取。

    ``settings`` 刻意**不做快照**：原 ``create_app()`` 里的 ``current_settings()``
    每次都走 ``get_settings()``（lru 缓存，``cache_clear`` 后刷新），运行中改
    ``.env`` 立即生效，测试也依赖这个语义。因此这里用 property 保持同一行为，
    避免"装配时拷一份设置"把动态配置能力悄悄改掉。
    """

    db: Database
    storage: ObjectStorage
    task_queue: Any
    secret_box_factory: Callable[[], SecretBox]

    @property
    def settings(self) -> Settings:
        return get_settings()

    # -- 装配后的服务 -----------------------------------------------------
    def model_service(self) -> ModelSettingsService:
        return ModelSettingsService(self.db, self.secret_box_factory())

    def provider_service(self) -> ProviderConfigService:
        service = self.model_service()
        return ProviderConfigService(
            db=self.db, secrets=service.secrets, settings=self.settings
        )

    # -- 租户 -------------------------------------------------------------
    def tenant_of(self, request: Request, user: dict[str, Any]) -> TenantContext:
        """解析租户上下文；无权访问统一 403，不区分"不存在"与"不是成员"。"""
        requested = request.headers.get("X-Tenant-Id")
        try:
            ctx = resolve_tenant(self.db, user, requested)
        except TenantError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        request.state.tenant = ctx
        return ctx

    def primary_tenant(self, user: dict[str, Any]) -> str:
        membership = self.db.get_membership(user["user_id"])
        return membership["tenant_id"] if membership else ""

    # -- 模型 Provider ----------------------------------------------------
    def build_user_provider(self, user: dict[str, Any]):
        """按用户配置构造 Provider（不发网络请求）。

        优先级：激活的 Provider 配置 > 旧的单套 user_model_settings > 进程默认值。
        """
        active = get_settings()
        config = self.provider_service().effective(user["user_id"], active)
        if config is None:
            config = self.model_service().effective(user["user_id"], active)
        return active, config, build_provider(active, config)

    def build_step_providers(self, user: dict[str, Any]):
        """按图节点构造 Provider：``{node: (provider, 说明)}``。

        只有 ``analyze`` / ``listing`` 会真正调模型；解析顺序是
        配置级 ``task_overrides`` > 激活配置 > 旧单套设置 > 进程默认。
        """
        from ..llm.step_providers import build_step_providers

        return build_step_providers(self.db, get_settings(), user["user_id"])

    def require_llm_provider(self, user: dict[str, Any]):
        """BYOK 强制：没有可用 Key 时 428，不静默降级成规则引擎。"""
        active, config, provider = self.build_user_provider(user)
        if not active.require_api_key:
            return active, config, provider
        if config.provider == "rule":
            raise HTTPException(
                status_code=428,
                detail={
                    "message": "需要先配置 API Key（BYOK）：平台不提供模型额度。",
                    **API_KEY_REQUIRED,
                },
            )
        if not config.api_key:
            raise HTTPException(
                status_code=428,
                detail={
                    "message": (
                        "还没有配置 API Key（BYOK）。请在「设置 → 模型与密钥」中"
                        "添加一个厂商配置并激活后再运行。"
                    ),
                    **API_KEY_REQUIRED,
                },
            )
        if isinstance(provider, RuleProvider):
            # 有 Key 却被降级 = Provider 构造失败；明确报错，不假装在用模型
            raise HTTPException(
                status_code=428,
                detail={
                    "message": getattr(provider, "fallback_reason", "")
                    or "当前没有可用的模型 Provider，请检查设置。",
                    **API_KEY_REQUIRED,
                },
            )
        return active, config, provider

    # -- 演示账号与限流 ---------------------------------------------------
    def guard_demo_key_write(self, user: dict[str, Any]) -> None:
        """固定 demo 账号是共享的，禁止写入任何 Provider 配置。"""
        try:
            assert_can_store_key(user, demo_username=get_settings().demo_username)
        except DemoAccountError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def rate_limit(self, user: dict[str, Any], scope: str, limit: int) -> dict[str, str]:
        active = get_settings()
        try:
            used, remaining = check_rate_limit(
                self.db,
                scope=scope,
                identity=user["user_id"],
                limit=limit,
                enabled=active.rate_limit_enabled,
            )
        except RateLimited as exc:
            raise HTTPException(
                status_code=429,
                detail=str(exc),
                headers={"Retry-After": str(exc.retry_after)},
            ) from exc
        return rate_limit_headers(used, remaining, limit)

    # -- 审计 -------------------------------------------------------------
    def audit_user(
        self,
        user: dict[str, Any],
        action: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> None:
        audit.record(
            self.db,
            tenant_id=tenant_id if tenant_id is not None else self.primary_tenant(user),
            actor_id=user["user_id"],
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )

    def audit_context(
        self,
        ctx: TenantContext,
        action: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> None:
        audit.record_for_context(
            self.db,
            ctx,
            action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            trace_id=trace_id,
        )


# ---------------------------------------------------------------------------
# FastAPI 依赖：router 只依赖这四个
# ---------------------------------------------------------------------------


def get_ctx(request: Request) -> ApiContext:
    """从 ``app.state`` 取出装配好的上下文（router 的唯一入口）。"""
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:  # pragma: no cover - 只有装配错误才会发生
        raise RuntimeError("ApiContext 未装配：create_app() 未挂载 routers")
    return ctx


def require_user(
    request: Request,
    ctx: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """解析会话得到当前用户；未登录 401。"""
    token = extract_token(request)
    user = resolve_session(ctx.db, token) if token else None
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="未登录或会话已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.user = user
    return user


def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_tenant(
    request: Request,
    ctx: ApiContext = Depends(get_ctx),
    user: dict[str, Any] = Depends(require_user),
) -> TenantContext:
    """解析租户上下文；无权访问统一 403。"""
    return ctx.tenant_of(request, user)


def optional_user(
    request: Request,
    ctx: ApiContext = Depends(get_ctx),
) -> dict[str, Any] | None:
    """公开接口用：有会话就返回用户，没有就返回 None。"""
    token = extract_token(request)
    return resolve_session(ctx.db, token) if token else None


def make_secret_box(settings: Settings) -> Callable[[], SecretBox]:
    """懒加载 SecretBox：密钥损坏时给出可操作提示，而不是静默失败。"""
    cache: dict[str, SecretBox] = {}

    def factory() -> SecretBox:
        if "box" in cache:
            return cache["box"]
        try:
            box = SecretBox(settings.resolve_path(settings.data_dir) / ".secret_key")
        except SecretError as exc:
            raise HTTPException(status_code=500, detail=f"加密密钥不可用：{exc}") from exc
        cache["box"] = box
        return box

    return factory


__all__ = [
    "API_KEY_REQUIRED",
    "ApiContext",
    "get_ctx",
    "make_secret_box",
    "optional_user",
    "require_admin",
    "require_tenant",
    "require_user",
]
