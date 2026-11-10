"""给租户预置演示店铺（幂等），供 demo 账号与一键体验账号使用。

幂等策略：

- 店铺名是幂等键（与 ``store_connections`` 的唯一索引一致），已存在就跳过创建；
- **已存在但没同步过**的店铺会补一次同步，修掉"店铺在、但没有数据"的半成品状态。

数据从哪来：``demo/store_data.py`` 的目录数据，经 ``MockStoreConnector`` 输出。
同步汇总（GMV / 订单数 / 客单价）会写进 ``last_sync_summary``，列表页据此展示。
商品与订单本身不落库——它们由连接器按需生成，与其余 Mock 行为一致。
"""

from __future__ import annotations

from typing import Any

from ..persistence.db import Database
from ..services import connectors
from ..tenancy import TenantContext
from .store_data import DEMO_STORES


def seed_demo_stores(
    db: Database, tenant_id: str, *, user_id: str = ""
) -> dict[str, Any]:
    """确保该租户拥有全部演示店铺，返回 ``{created, synced, total}``。"""
    if not tenant_id:
        return {"created": 0, "synced": 0, "total": 0}

    ctx = TenantContext(
        tenant_id=tenant_id, tenant_name="", user_id=user_id, role="owner"
    )
    existing = {
        conn["shop_name"]: conn for conn in db.list_store_connections(tenant_id)
    }
    created = 0
    synced = 0

    for store in DEMO_STORES:
        connection = existing.get(store["shop_name"])
        if connection is None:
            try:
                connection = connectors.create_mock_connection(
                    db,
                    ctx,
                    platform=store["platform"],
                    marketplace=store["marketplace"],
                    shop_name=store["shop_name"],
                )
                created += 1
            except connectors.StoreConflict:
                # 并发或历史数据：重新取一次，别让 seed 整体失败
                connection = next(
                    (
                        item
                        for item in db.list_store_connections(tenant_id)
                        if item["shop_name"] == store["shop_name"]
                    ),
                    None,
                )
                if connection is None:
                    continue

        if not connection.get("last_sync_at"):
            try:
                connectors.sync_connection(db, ctx, connection["connection_id"])
                synced += 1
            except connectors.ConnectorError:
                # 同步失败不影响其他店铺；连接状态已由 sync_connection 记录
                pass

    return {"created": created, "synced": synced, "total": len(DEMO_STORES)}


__all__ = ["seed_demo_stores"]
