"""工作台聚合数据与演示数据集。

dashboard 的所有数字都来自真实记录；没有数据时是 0，不是推测值。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import perf
from ..demo.demo_data import get_demo_dataset
from ..market.marketplace_provider import describe_data_sources
from ..services import connectors as connector_service
from ..services.tasks import STATUS_QUEUED, STATUS_RUNNING
from ..tenancy import TenantContext
from .deps import ApiContext, get_ctx, require_tenant, require_user

router = APIRouter(tags=["工作台"])


@router.get("/api/dashboard")
def dashboard(
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """任务统计、近期记录、14 天趋势、数据源状态。

    一次请求的所有读取共用一个连接：首屏慢的根因不是 SQL，而是
    「每个 db 方法各建一条连接」——远端数据库上建连成本远高于查询本身。
    """
    with api.db.connect() as connection:
        with perf.timed("dashboard.stats"):
            stats = api.db.task_stats(
                user["user_id"], tenant_id=tenant.tenant_id, connection=connection
            )
        with perf.timed("dashboard.counts"):
            counts = api.db.count_records(
                user["user_id"], tenant_id=tenant.tenant_id, connection=connection
            )
        with perf.timed("dashboard.connections"):
            store_links = connector_service.list_connections(
                api.db, tenant, connection=connection
            )
        with perf.timed("dashboard.recent_tasks"):
            recent_tasks = api.db.list_tasks(
                user["user_id"],
                limit=6,
                tenant_id=tenant.tenant_id,
                connection=connection,
            )
        with perf.timed("dashboard.recent_reports"):
            recent_reports = api.db.list_reports(
                limit=5,
                user_id=user["user_id"],
                tenant_id=tenant.tenant_id,
                connection=connection,
            )
        with perf.timed("dashboard.recent_listings"):
            recent_listings = api.db.list_listings(
                limit=5,
                user_id=user["user_id"],
                tenant_id=tenant.tenant_id,
                connection=connection,
            )
        with perf.timed("dashboard.daily"):
            daily_tasks = api.db.daily_task_counts(
                user["user_id"], days=14, tenant_id=tenant.tenant_id, connection=connection
            )
    with perf.timed("dashboard.assemble"):
        return {
            "stats": {
                "running": stats.get(STATUS_RUNNING, 0) + stats.get(STATUS_QUEUED, 0),
                "awaiting_approval": stats.get("awaiting_approval", 0),
                "succeeded": stats.get("succeeded", 0),
                "failed": stats.get("failed", 0),
                "total": sum(stats.values()),
                "reports": counts.get("reports", 0),
                "listings": counts.get("listings", 0),
                "stores": counts.get("stores", 0),
                "approvals": counts.get("approvals", 0),
            },
            "recent_tasks": recent_tasks,
            "recent_reports": recent_reports,
            "recent_listings": recent_listings,
            "daily_tasks": daily_tasks,
            "data_sources": describe_data_sources(store_links),
        }


@router.get("/api/demo/dataset")
async def demo_dataset() -> dict[str, Any]:
    """内置虚构数据集，用于体验流程（全部带 is_demo 标记）。"""
    return get_demo_dataset()


__all__ = ["router"]
