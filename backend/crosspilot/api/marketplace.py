"""市场数据（Provider 协议：默认 Mock，全部带 is_mock）。

设计约束：**数据可以模拟，标记必须真实**。
应用层只依赖 ``MarketplaceDataProvider`` 协议，不 import 具体实现；Live 未配置时
明确 501，不降级成 Mock。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..market.marketplace_provider import (
    MockMarketplaceProvider,
    ProviderNotConfigured,
    build_marketplace_provider,
    describe_data_sources,
)
from ..services import connectors as connector_service
from ..tenancy import ROLE_READ, TenantContext, require_role
from .deps import ApiContext, get_ctx, require_tenant

router = APIRouter(tags=["市场数据"])


def _marketplace_connection(
    api: ApiContext, ctx: TenantContext, connection_id: str | None
) -> dict[str, Any]:
    """取一个连接作为数据源；未指定时取本租户第一个 Mock 连接。"""
    connections = connector_service.list_connections(api.db, ctx)
    if connection_id:
        match = next(
            (c for c in connections if c["connection_id"] == connection_id), None
        )
        if match is None:
            raise HTTPException(status_code=404, detail=f"店铺连接不存在: {connection_id}")
        return match
    mock = next((c for c in connections if c.get("mode") == "mock"), None)
    if mock is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "还没有可用的数据源连接。请先在「店铺与渠道」创建一个 Mock 连接，"
                "或配置真实平台凭据（本期未接入）。"
            ),
        )
    return mock


def _provider_for(connection: dict[str, Any]) -> MockMarketplaceProvider:
    try:
        return build_marketplace_provider(connection)
    except ProviderNotConfigured as exc:
        # Live 未配置：明确 501，不降级成 Mock
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get("/api/marketplace/sources")
async def data_source_status(
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """每个数据域当前使用哪个 Provider、模式、最后同步时间。

    注意：路径故意不放在 ``/api/data-sources/`` 下——那里已有
    ``/api/data-sources/{data_source_id}``，通配会吞掉同前缀的静态路径。
    """
    require_role(ctx, ROLE_READ)
    connections = connector_service.list_connections(api.db, ctx)
    return {
        "items": describe_data_sources(connections),
        "marketplace_mode": api.settings.marketplace_mode,
        "note": (
            "数据可以模拟，标记必须真实：Mock 数据全部带 is_mock=true，"
            "Live 未配置时明确显示「未接入」，不会伪装成已连接。"
        ),
    }


@router.get("/api/marketplace/overview")
async def marketplace_overview(
    connection_id: str | None = None,
    range: str = "30d",
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    connection = _marketplace_connection(api, ctx, connection_id)
    provider = _provider_for(connection)
    store_id = connection["connection_id"]
    return {
        "connection": {
            "connection_id": store_id,
            "platform": connection["platform"],
            "marketplace": connection["marketplace"],
            "shop_name": connection["shop_name"],
            "mode": connection["mode"],
            "is_mock": connection.get("is_mock", connection["mode"] == "mock"),
        },
        "provider": {"name": provider.name, "mode": provider.mode},
        "products": provider.list_products(store_id, limit=8),
        "orders": provider.list_orders(store_id, since="30d"),
        "ads": provider.list_ads(store_id),
        "metrics": provider.metrics(store_id, range=range),
    }


@router.get("/api/marketplace/products")
async def marketplace_products(
    connection_id: str | None = None,
    limit: int = 20,
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    connection = _marketplace_connection(api, ctx, connection_id)
    provider = _provider_for(connection)
    items = provider.list_products(
        connection["connection_id"], limit=min(max(limit, 1), 100)
    )
    return {
        "items": items,
        "mode": provider.mode,
        "is_mock": provider.mode == "mock",
        "provider": provider.name,
    }


@router.get("/api/marketplace/orders")
async def marketplace_orders(
    connection_id: str | None = None,
    since: str = "30d",
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    connection = _marketplace_connection(api, ctx, connection_id)
    provider = _provider_for(connection)
    items = provider.list_orders(connection["connection_id"], since=since)
    return {
        "items": items,
        "mode": provider.mode,
        "is_mock": provider.mode == "mock",
        "provider": provider.name,
    }


@router.get("/api/marketplace/ads")
async def marketplace_ads(
    connection_id: str | None = None,
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    connection = _marketplace_connection(api, ctx, connection_id)
    provider = _provider_for(connection)
    items = provider.list_ads(connection["connection_id"])
    return {
        "items": items,
        "mode": provider.mode,
        "is_mock": provider.mode == "mock",
        "provider": provider.name,
    }


@router.get("/api/marketplace/metrics")
async def marketplace_metrics(
    connection_id: str | None = None,
    range: str = "30d",
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    connection = _marketplace_connection(api, ctx, connection_id)
    provider = _provider_for(connection)
    payload = provider.metrics(connection["connection_id"], range=range)
    return {
        **payload,
        "mode": provider.mode,
        "provider": provider.name,
    }


__all__ = ["router"]
