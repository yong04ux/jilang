"""店铺连接器（阶段 F1–F4）。

设计边界：

- **只有 Mock 连接器可用**。它用固定随机种子生成确定性的商品/订单，
  每条数据都带 ``is_mock=True``，不会冒充真实平台数据。
- **Live 连接器未实现**：构造时明确报"未配置/未接入"，不会静默降级成 Mock。
- **凭据只存引用**：``store_connections.credential_ref`` 指向
  ``store_credentials`` 里的密文；明文不写库、不进日志、不进 API 响应。

协议统一为 ``status/test/sync/list_products/list_orders``，
阶段 G 的真实 SP-API 实现只需实现同一协议。
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable

from ..demo.store_data import demo_catalog, demo_sync_summary, is_demo_shop
from ..market.platforms import ALL_CAPABILITIES, platform_spec
from ..persistence.db import Database
from ..tenancy import ROLE_WRITE, TenantContext, require_role

MOCK_PRODUCT_COUNT = 6
MOCK_ORDER_COUNT = 8


class ConnectorError(RuntimeError):
    """连接器操作失败（消息可直接展示）。"""


class StoreNotFound(ConnectorError):
    pass


class StoreConflict(ConnectorError):
    pass


@dataclass(frozen=True)
class ConnectorStatus:
    platform: str
    mode: str
    connected: bool
    detail: str
    scopes: tuple[str, ...] = ()


@runtime_checkable
class StoreConnector(Protocol):
    platform: str
    mode: str

    def status(self) -> ConnectorStatus: ...

    def test(self) -> ConnectorStatus: ...

    def sync(self) -> dict[str, Any]: ...

    def list_products(self) -> list[dict[str, Any]]: ...

    def list_orders(self) -> list[dict[str, Any]]: ...


def _seed_for(connection: dict[str, Any]) -> int:
    raw = f"{connection['tenant_id']}|{connection['platform']}|{connection['shop_name']}"
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8], 16)


class MockStoreConnector:
    """确定性 Mock 连接器：同一连接每次同步得到同一批数据。"""

    mode = "mock"

    def __init__(self, connection: dict[str, Any]):
        self.connection = connection
        self.platform = connection["platform"]
        self._rng = random.Random(_seed_for(connection))

    def status(self) -> ConnectorStatus:
        return ConnectorStatus(
            platform=self.platform,
            mode="mock",
            connected=True,
            detail="Mock 连接器：本地确定性示例数据，不代表真实店铺",
            scopes=("mock:read", "mock:sync"),
        )

    def test(self) -> ConnectorStatus:
        return self.status()

    def _products(self) -> list[dict[str, Any]]:
        rng = random.Random(_seed_for(self.connection))
        rows: list[dict[str, Any]] = []
        for index in range(1, MOCK_PRODUCT_COUNT + 1):
            price = round(rng.uniform(9.9, 59.9), 2)
            rows.append(
                {
                    "product_id": f"mock-{self.connection['platform']}-{index:03d}",
                    "asin": f"MOCK{index:07d}",
                    "name": f"Mock {self.platform.title()} Product {index}",
                    "price": price,
                    "currency": "USD",
                    "rating": round(rng.uniform(3.6, 4.9), 1),
                    "review_count": rng.randint(10, 5000),
                    "marketplace": self.connection["marketplace"],
                    "is_mock": True,
                    "source": "mock_connector",
                }
            )
        return rows

    def _orders(self) -> list[dict[str, Any]]:
        rng = random.Random(_seed_for(self.connection) + 1)
        base = datetime.now(timezone.utc) - timedelta(days=30)
        rows: list[dict[str, Any]] = []
        for index in range(1, MOCK_ORDER_COUNT + 1):
            rows.append(
                {
                    "order_id": f"MOCK-ORDER-{index:04d}",
                    "sku": f"mock-{self.connection['platform']}-{(index % MOCK_PRODUCT_COUNT) + 1:03d}",
                    "quantity": rng.randint(1, 3),
                    "amount": round(rng.uniform(15.0, 120.0), 2),
                    "currency": "USD",
                    "status": rng.choice(["shipped", "delivered", "pending"]),
                    "created_at": (base + timedelta(days=index)).isoformat(),
                    "is_mock": True,
                    "source": "mock_connector",
                }
            )
        return rows

    def list_products(self) -> list[dict[str, Any]]:
        demo = demo_catalog(self.connection.get("shop_name") or "")
        return demo[0] if demo is not None else self._products()

    def list_orders(self) -> list[dict[str, Any]]:
        demo = demo_catalog(self.connection.get("shop_name") or "")
        return demo[1] if demo is not None else self._orders()

    def sync(self) -> dict[str, Any]:
        demo = demo_catalog(self.connection.get("shop_name") or "")
        if demo is not None:
            # 演示店铺：返回有品牌感的目录数据，汇总里带转化/客单价等展示指标
            return demo_sync_summary(*demo)

        products = self._products()
        orders = self._orders()
        return {
            "mode": "mock",
            "is_mock": True,
            "products": len(products),
            "orders": len(orders),
            "revenue": round(sum(o["amount"] for o in orders), 2),
            "detail": "Mock 同步完成；数据为示例，不可用于真实经营决策",
        }


class LiveStoreConnector:
    """真实连接器占位：未配置时不降级、不伪造。"""

    mode = "live"

    def __init__(self, connection: dict[str, Any]):
        self.connection = connection
        self.platform = connection["platform"]

    def _fail(self) -> None:
        raise ConnectorError(
            "真实店铺连接尚未接入：需要 SP-API 应用注册、卖家授权与审核（阶段 G）。"
            "当前不会用 Mock 数据冒充真实数据。"
        )

    def status(self) -> ConnectorStatus:
        return ConnectorStatus(
            platform=self.platform,
            mode="live",
            connected=False,
            detail="真实 API 未接入（待审核）",
        )

    def test(self) -> ConnectorStatus:
        return self.status()

    def sync(self) -> dict[str, Any]:
        self._fail()

    def list_products(self) -> list[dict[str, Any]]:
        self._fail()

    def list_orders(self) -> list[dict[str, Any]]:
        self._fail()


def build_connector(connection: dict[str, Any]) -> StoreConnector:
    if connection.get("mode") == "live":
        return LiveStoreConnector(connection)
    return MockStoreConnector(connection)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------


def _decorate(connection: dict[str, Any]) -> dict[str, Any]:
    """给连接补充对外展示字段：Mock/演示标记、平台标签与能力。

    未知平台不报错（历史数据可能是任意字符串），只标 ``platform_known=False``。
    """
    spec = platform_spec(connection.get("platform"))
    connection["is_mock"] = connection.get("mode") == "mock"
    connection["is_demo"] = is_demo_shop(connection.get("shop_name") or "")
    connection["platform_label"] = spec.label if spec else (connection.get("platform") or "")
    connection["platform_known"] = spec is not None
    connection["capabilities"] = (
        [cap for cap in ALL_CAPABILITIES if cap in spec.capabilities] if spec else []
    )
    connection["can_sync"] = (
        connection.get("status") == "connected" and connection.get("mode") == "mock"
    )
    return connection


def list_connections(
    db: Database, ctx: TenantContext, *, connection: Any = None
) -> list[dict[str, Any]]:
    return [
        _decorate(item)
        for item in db.list_store_connections(ctx.tenant_id, connection=connection)
    ]


def get_connection(
    db: Database, ctx: TenantContext, connection_id: str
) -> dict[str, Any]:
    connection = db.get_store_connection(connection_id, ctx.tenant_id)
    if connection is None:
        raise StoreNotFound("店铺连接不存在")
    return _decorate(connection)


def create_mock_connection(
    db: Database,
    ctx: TenantContext,
    *,
    platform: str,
    marketplace: str,
    shop_name: str,
    mode: str = "mock",
) -> dict[str, Any]:
    require_role(ctx, ROLE_WRITE)
    mode = (mode or "mock").strip().lower()
    if mode != "mock":
        raise ConnectorError(
            "真实店铺连接尚未接入（阶段 G）；当前只能创建 Mock 连接，不会伪造真实授权"
        )
    platform = (platform or "").strip().lower()
    marketplace = (marketplace or "US").strip().upper()
    shop_name = (shop_name or "").strip()
    if not platform or not shop_name:
        raise ConnectorError("platform 与 shop_name 必填")

    existing = [
        item
        for item in db.list_store_connections(ctx.tenant_id)
        if item["platform"] == platform
        and item["marketplace"] == marketplace
        and item["shop_name"] == shop_name
    ]
    if existing:
        raise StoreConflict("该店铺连接已存在")

    connection = {
        "connection_id": uuid.uuid4().hex,
        "tenant_id": ctx.tenant_id,
        "platform": platform,
        "marketplace": marketplace,
        "shop_name": shop_name,
        "mode": "mock",
        "status": "connected",
        "scopes": ["mock:read", "mock:sync"],
        "credential_ref": None,
        "last_sync_at": None,
        "last_sync_status": None,
        "last_sync_error": None,
        "last_sync_summary": {},
        "created_at": _now(),
    }
    db.create_store_connection(connection)
    connector = build_connector(connection)
    connection["status"] = "connected" if connector.status().connected else "error"
    db.update_store_connection(connection["connection_id"], status=connection["status"])
    return _decorate(connection)


def test_connection(
    db: Database, ctx: TenantContext, connection_id: str
) -> dict[str, Any]:
    connection = get_connection(db, ctx, connection_id)
    status = build_connector(connection).test()
    db.update_store_connection(
        connection_id, status="connected" if status.connected else "error"
    )
    return {
        "connection_id": connection_id,
        "connected": status.connected,
        "mode": status.mode,
        "detail": status.detail,
        "scopes": list(status.scopes),
    }


def sync_connection(
    db: Database, ctx: TenantContext, connection_id: str
) -> dict[str, Any]:
    require_role(ctx, ROLE_WRITE)
    connection = get_connection(db, ctx, connection_id)
    if connection.get("mode") == "live":
        raise ConnectorError("真实 API 未接入，无法同步")
    if connection.get("status") != "connected":
        raise ConnectorError("连接未处于 connected 状态，请先测试连接")
    try:
        summary = build_connector(connection).sync()
    except ConnectorError as exc:
        db.update_store_connection(
            connection_id,
            last_sync_at=_now(),
            last_sync_status="error",
            last_sync_error=str(exc),
        )
        raise
    db.update_store_connection(
        connection_id,
        last_sync_at=_now(),
        last_sync_status="ok",
        last_sync_error=None,
        last_sync_summary=summary,
    )
    return {
        "connection_id": connection_id,
        "mode": "mock",
        "is_mock": True,
        "is_demo": is_demo_shop(connection.get("shop_name") or ""),
        **summary,
    }


def list_products(
    db: Database, ctx: TenantContext, connection_id: str
) -> list[dict[str, Any]]:
    connection = get_connection(db, ctx, connection_id)
    return build_connector(connection).list_products()


def list_orders(
    db: Database, ctx: TenantContext, connection_id: str
) -> list[dict[str, Any]]:
    connection = get_connection(db, ctx, connection_id)
    return build_connector(connection).list_orders()


def disconnect(
    db: Database, ctx: TenantContext, connection_id: str
) -> dict[str, Any]:
    require_role(ctx, ROLE_WRITE)
    connection = get_connection(db, ctx, connection_id)
    db.update_store_connection(connection_id, status="disconnected")
    connection["status"] = "disconnected"
    return _decorate(connection)


def attach_credential(
    db: Database, ctx: TenantContext, connection_id: str, credential_ref: str
) -> dict[str, Any]:
    """只保存引用；密文由调用方写入 ``store_credentials``。"""
    require_role(ctx, ROLE_WRITE)
    get_connection(db, ctx, connection_id)
    db.update_store_connection(connection_id, credential_ref=credential_ref)
    return get_connection(db, ctx, connection_id)


__all__ = [
    "ConnectorError",
    "ConnectorStatus",
    "LiveStoreConnector",
    "MockStoreConnector",
    "StoreConflict",
    "StoreConnector",
    "StoreNotFound",
    "attach_credential",
    "build_connector",
    "create_mock_connection",
    "disconnect",
    "get_connection",
    "list_connections",
    "list_orders",
    "list_products",
    "sync_connection",
    "test_connection",
]
