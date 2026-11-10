"""市场数据（Provider 协议：默认 Mock，全部带 is_mock）。

设计约束：**数据可以模拟，标记必须真实**。
应用层只依赖 ``MarketplaceDataProvider`` 协议，不 import 具体实现；Live 未配置时
明确 501，不降级成 Mock。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import perf
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
            raise HTTPException(status_code=404, detail="没有找到这个店铺，可能已被移除")
        return match
    mock = next((c for c in connections if c.get("mode") == "mock"), None)
    if mock is None:
        raise HTTPException(
            status_code=409,
            detail="还没有添加店铺。先到「店铺与渠道」添加一个店铺，商品与订单就会同步过来。",
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
    }


@router.get("/api/marketplace/overview")
def marketplace_overview(
    connection_id: str | None = None,
    range: str = "30d",
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    connection = _marketplace_connection(api, ctx, connection_id)
    provider = _provider_for(connection)
    store_id = connection["connection_id"]
    with perf.timed("marketplace.products"):
        products = provider.list_products(store_id, limit=8)
    with perf.timed("marketplace.orders"):
        orders = provider.list_orders(store_id, since="30d")
    with perf.timed("marketplace.ads"):
        ads = provider.list_ads(store_id)
    with perf.timed("marketplace.metrics"):
        metrics = provider.metrics(store_id, range=range)
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
        "products": products,
        "orders": orders,
        "ads": ads,
        "metrics": metrics,
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
def marketplace_metrics(
    connection_id: str | None = None,
    range: str = "30d",
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    connection = _marketplace_connection(api, ctx, connection_id)
    provider = _provider_for(connection)
    with perf.timed("marketplace.metrics"):
        payload = provider.metrics(connection["connection_id"], range=range)
    return {
        **payload,
        "mode": provider.mode,
        "provider": provider.name,
    }


# ---------------------------------------------------------------------------
# 店铺经营助手（看板 / 单品 / 明细）
# ---------------------------------------------------------------------------


def _store_brief(connection: dict[str, Any]) -> dict[str, Any]:
    return {
        "connection_id": connection["connection_id"],
        "platform": connection["platform"],
        "marketplace": connection["marketplace"],
        "shop_name": connection["shop_name"],
        "mode": connection["mode"],
        "is_demo": bool(connection.get("is_demo")),
    }


@router.get("/api/marketplace/dashboard")
async def marketplace_dashboard(
    connection_id: str | None = None,
    range: str = "30d",
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """经营看板的全部数据，一次返回。

    五个分段（概览/订单/广告/库存/售后）在页面上是秒切的，如果每切一次
    打一个接口，0.1 CPU 的实例上体感会明显卡顿；这里先一次取全，
    前端本地切换，滑动时间范围时才重新请求。
    """
    require_role(ctx, ROLE_READ)
    connection = _marketplace_connection(api, ctx, connection_id)
    provider = _provider_for(connection)
    store_id = connection["connection_id"]
    metrics = provider.metrics(store_id, range=range)
    inventory = provider.inventory_aging(store_id)
    return {
        "store": _store_brief(connection),
        "range": range,
        "days": metrics["days"],
        "currency": metrics["currency"],
        "metrics": metrics,
        # 订单分段要出列表，一并带上；上限 200 行，够看也够小
        "orders": provider.list_orders(store_id, since=f"{metrics['days']}d")[:200],
        "ads": provider.ads_summary(store_id),
        "inventory": inventory,
        "returns": provider.list_returns(store_id),
        "health": provider.account_health(store_id),
        "mode": provider.mode,
        "provider": provider.name,
        "is_mock": True,
    }


@router.get("/api/marketplace/products/{asin}/detail")
async def marketplace_product_detail(
    asin: str,
    connection_id: str | None = None,
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    connection = _marketplace_connection(api, ctx, connection_id)
    provider = _provider_for(connection)
    payload = provider.product_detail(connection["connection_id"], asin)
    if payload is None:
        raise HTTPException(status_code=404, detail="这个 ASIN 不在当前店铺里")
    return {
        **payload,
        "store": _store_brief(connection),
        "mode": provider.mode,
        "provider": provider.name,
    }


#: 经营明细支持的四类表
LEDGER_KINDS: tuple[str, ...] = ("listing", "orders", "aftersales", "fba")


@router.get("/api/marketplace/ledger")
async def marketplace_ledger(
    kind: str = "listing",
    connection_id: str | None = None,
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """经营明细：Listing / 订单列表 / 售后订单 / FBA 库存明细。"""
    require_role(ctx, ROLE_READ)
    if kind not in LEDGER_KINDS:
        raise HTTPException(status_code=422, detail="不支持的明细类型")
    connection = _marketplace_connection(api, ctx, connection_id)
    provider = _provider_for(connection)
    store_id = connection["connection_id"]

    if kind == "listing":
        items = provider.list_products(store_id, limit=100)
    elif kind == "orders":
        items = provider.list_orders(store_id, since="30d")[:200]
    elif kind == "aftersales":
        items = provider.list_returns(store_id)
    else:
        items = provider.inventory_aging(store_id)["items"]

    return {
        "kind": kind,
        "items": items,
        "total": len(items),
        "store": _store_brief(connection),
        "mode": provider.mode,
        "provider": provider.name,
        "is_mock": True,
    }


__all__ = ["router"]
