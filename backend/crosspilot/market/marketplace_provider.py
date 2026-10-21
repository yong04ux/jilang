"""市场数据 Provider（阶段：真实接口预留）。

核心约定：**数据可以假，接口必须真**。

- ``MarketplaceDataProvider`` 是唯一被应用层依赖的协议；
- ``MockMarketplaceProvider`` 用固定种子生成确定性数据，每条记录带
  ``is_mock=True``，不会被误认为真实经营数据；
- ``LiveMarketplaceProvider`` 本期只有骨架：构造时校验凭据，缺失即抛
  ``ProviderNotConfigured``，**绝不降级为 Mock**；
- 工厂 ``build_marketplace_provider(connection)`` 按 ``connection["mode"]`` 选择实现。

将来接入真实平台时，只需新增一个实现并注册，页面与接口都不用改。
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Protocol, runtime_checkable

MODE_MOCK = "mock"
MODE_LIVE = "live"

PRODUCT_COUNT = 8
ORDER_COUNT = 12
AD_COUNT = 4

#: 数据域 -> 展示名与真实接入点（设置页与 /api/data-sources 用）
DATA_DOMAINS: tuple[dict[str, Any], ...] = (
    {
        "domain": "stores",
        "label": "店铺连接",
        "detail": "店铺授权与同步状态",
        "live_target": "LiveStoreConnector / SP-API 应用审核",
    },
    {
        "domain": "products",
        "label": "商品",
        "detail": "ASIN / SKU 级商品档案",
        "live_target": "SP-API list_products",
    },
    {
        "domain": "orders",
        "label": "订单",
        "detail": "订单明细与履约状态",
        "live_target": "SP-API Orders",
    },
    {
        "domain": "ads",
        "label": "广告活动",
        "detail": "广告活动与花费",
        "live_target": "SP-API Advertising",
    },
    {
        "domain": "metrics",
        "label": "销量与收益指标",
        "detail": "按周期聚合的销量/收入",
        "live_target": "由真实订单聚合",
    },
    {
        "domain": "competitors",
        "label": "竞品数据",
        "detail": "用户上传或示例数据集",
        "live_target": "第三方数据供应商",
    },
)


class ProviderNotConfigured(RuntimeError):
    """Live Provider 缺少凭据或尚未接入（消息可直接展示）。"""


@runtime_checkable
class MarketplaceDataProvider(Protocol):
    """每个数据域唯一依赖的接口。"""

    mode: str
    name: str
    configured: bool

    def list_stores(self) -> list[dict[str, Any]]: ...

    def list_products(self, store_id: str, *, limit: int = PRODUCT_COUNT) -> list[dict[str, Any]]: ...

    def list_orders(self, store_id: str, *, since: str) -> list[dict[str, Any]]: ...

    def list_ads(self, store_id: str) -> list[dict[str, Any]]: ...

    def metrics(self, store_id: str, *, range: str = "30d") -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Mock
# ---------------------------------------------------------------------------


def _seed(*parts: str) -> int:
    raw = "|".join(parts)
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8], 16)


def _store_seed(connection: dict[str, Any]) -> int:
    return _seed(
        connection.get("tenant_id", ""),
        connection.get("platform", ""),
        connection.get("marketplace", ""),
        connection.get("shop_name", ""),
    )


@dataclass
class MockMarketplaceProvider:
    """确定性模拟数据源。

    同一连接每次读到的数据完全一致（按连接信息做种子），
    这样"刷新页面数据变了"不会被误认为是真实波动。
    """

    connection: dict[str, Any]
    mode: str = MODE_MOCK
    configured: bool = True

    @property
    def name(self) -> str:
        return "模拟数据源（Mock）"

    @property
    def store_id(self) -> str:
        return str(self.connection.get("connection_id") or "mock-store")

    # -- 店铺 -----------------------------------------------------------
    def list_stores(self) -> list[dict[str, Any]]:
        connection = self.connection
        return [
            {
                "store_id": self.store_id,
                "platform": connection.get("platform", ""),
                "marketplace": connection.get("marketplace", ""),
                "shop_name": connection.get("shop_name", ""),
                "status": connection.get("status", "connected"),
                "mode": MODE_MOCK,
                "is_mock": True,
            }
        ]

    # -- 商品 -----------------------------------------------------------
    def list_products(self, store_id: str, *, limit: int = PRODUCT_COUNT) -> list[dict[str, Any]]:
        rng = random.Random(_store_seed(self.connection))
        platform = (self.connection.get("platform") or "amazon").lower()
        marketplace = self.connection.get("marketplace") or "US"
        rows: list[dict[str, Any]] = []
        for index in range(1, max(1, limit) + 1):
            price = round(rng.uniform(9.9, 79.9), 2)
            rows.append(
                {
                    "product_id": f"mock-{platform}-{index:03d}",
                    "store_id": store_id or self.store_id,
                    "asin": f"MOCK{index:07d}",
                    "sku": f"SKU-{index:04d}",
                    "name": f"模拟商品 {index}（{platform}）",
                    "price": price,
                    "currency": "USD",
                    "rating": round(rng.uniform(3.5, 4.9), 1),
                    "review_count": rng.randint(12, 4200),
                    "stock": rng.randint(0, 480),
                    "marketplace": marketplace,
                    "is_mock": True,
                    "source": "mock_provider",
                }
            )
        return rows

    # -- 订单 -----------------------------------------------------------
    def list_orders(self, store_id: str, *, since: str) -> list[dict[str, Any]]:
        rng = random.Random(_store_seed(self.connection) + 1)
        platform = (self.connection.get("platform") or "amazon").lower()
        try:
            start = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            start = datetime.now(timezone.utc) - timedelta(days=30)
        rows: list[dict[str, Any]] = []
        for index in range(1, ORDER_COUNT + 1):
            quantity = rng.randint(1, 3)
            unit = round(rng.uniform(12.0, 68.0), 2)
            rows.append(
                {
                    "order_id": f"MOCK-ORDER-{index:04d}",
                    "store_id": store_id or self.store_id,
                    "sku": f"SKU-{(index % PRODUCT_COUNT) + 1:04d}",
                    "quantity": quantity,
                    "amount": round(unit * quantity, 2),
                    "currency": "USD",
                    "status": rng.choice(["shipped", "delivered", "pending"]),
                    "created_at": (start + timedelta(hours=index * 7)).isoformat(),
                    "platform": platform,
                    "is_mock": True,
                    "source": "mock_provider",
                }
            )
        return rows

    # -- 广告 -----------------------------------------------------------
    def list_ads(self, store_id: str) -> list[dict[str, Any]]:
        rng = random.Random(_store_seed(self.connection) + 2)
        rows: list[dict[str, Any]] = []
        for index in range(1, AD_COUNT + 1):
            impressions = rng.randint(800, 42000)
            clicks = max(1, int(impressions * rng.uniform(0.002, 0.012)))
            spend = round(clicks * rng.uniform(0.4, 1.6), 2)
            rows.append(
                {
                    "campaign_id": f"MOCK-AD-{index:03d}",
                    "store_id": store_id or self.store_id,
                    "name": f"模拟广告活动 {index}",
                    "status": rng.choice(["active", "paused"]),
                    "impressions": impressions,
                    "clicks": clicks,
                    "spend": spend,
                    "sales": round(spend * rng.uniform(1.2, 4.8), 2),
                    "currency": "USD",
                    "is_mock": True,
                    "source": "mock_provider",
                }
            )
        return rows

    # -- 指标 -----------------------------------------------------------
    def metrics(self, store_id: str, *, range: str = "30d") -> dict[str, Any]:
        days = _parse_range_days(range)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        orders = self.list_orders(store_id, since=since)
        revenue = round(sum(float(o["amount"]) for o in orders), 2)
        units = sum(int(o["quantity"]) for o in orders)
        return {
            "store_id": store_id or self.store_id,
            "range": range,
            "days": days,
            "orders": len(orders),
            "units": units,
            "revenue": revenue,
            "currency": "USD",
            "aov": round(revenue / len(orders), 2) if orders else 0.0,
            "is_mock": True,
            "source": "mock_provider",
            "note": "由 Mock 订单聚合，仅用于演示；不代表真实经营数据",
        }


def _parse_range_days(range_value: str) -> int:
    text = (range_value or "30d").strip().lower()
    if text.endswith("d") and text[:-1].isdigit():
        return max(1, min(int(text[:-1]), 365))
    if text == "today":
        return 1
    if text == "week":
        return 7
    if text == "month":
        return 30
    if text == "quarter":
        return 90
    return 30


# ---------------------------------------------------------------------------
# Live（骨架）
# ---------------------------------------------------------------------------


@dataclass
class LiveMarketplaceProvider:
    """真实平台 Provider 骨架。

    本期不实现任何网络调用：构造时若没有凭据直接抛
    ``ProviderNotConfigured``，调用任何方法都显式失败。
    """

    connection: dict[str, Any]
    credentials: dict[str, Any] | None = None
    mode: str = MODE_LIVE

    def __post_init__(self) -> None:
        if not self._has_credentials():
            raise ProviderNotConfigured(
                "真实平台 API 尚未接入（需要平台应用注册、卖家授权与审核）。"
                "当前不会用模拟数据冒充真实数据；请在店铺设置中选择 Mock 连接器，"
                "或等待平台审核通过后配置凭据。"
            )

    def _has_credentials(self) -> bool:
        creds = self.credentials or {}
        return bool(creds.get("refresh_token") or creds.get("access_token"))

    @property
    def name(self) -> str:
        return "真实平台 API"

    @property
    def configured(self) -> bool:
        return self._has_credentials()

    def _fail(self) -> None:
        raise ProviderNotConfigured(
            "真实平台 API 尚未接入：本期只提供协议与骨架，不发起真实请求。"
        )

    def list_stores(self) -> list[dict[str, Any]]:
        self._fail()

    def list_products(self, store_id: str, *, limit: int = PRODUCT_COUNT) -> list[dict[str, Any]]:
        self._fail()

    def list_orders(self, store_id: str, *, since: str) -> list[dict[str, Any]]:
        self._fail()

    def list_ads(self, store_id: str) -> list[dict[str, Any]]:
        self._fail()

    def metrics(self, store_id: str, *, range: str = "30d") -> dict[str, Any]:
        self._fail()


# ---------------------------------------------------------------------------
# 工厂与注册表
# ---------------------------------------------------------------------------

#: 已知实现：新增真实 Provider 时只在这里注册，不改页面与接口。
PROVIDER_REGISTRY: dict[str, type] = {
    MODE_MOCK: MockMarketplaceProvider,
    MODE_LIVE: LiveMarketplaceProvider,
}


class UnknownProviderMode(RuntimeError):
    pass


def provider_for_mode(mode: str) -> type:
    return PROVIDER_REGISTRY.get((mode or MODE_MOCK).lower(), MockMarketplaceProvider)


# ---------------------------------------------------------------------------
# 数据源状态（设置页 / 工作台用）
# ---------------------------------------------------------------------------


@dataclass
class DataSourceStatus:
    domain: str
    label: str
    detail: str
    live_target: str
    mode: str
    configured: bool
    last_sync_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "label": self.label,
            "detail": self.detail,
            "live_target": self.live_target,
            "mode": self.mode,
            "configured": self.configured,
            "last_sync_at": self.last_sync_at,
            "is_mock": self.mode == MODE_MOCK,
            **(self.extra or {}),
        }


def describe_data_sources(connections: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """把当前租户的店铺连接汇总成"每个数据域用哪个 Provider"。

    Mock 连接存在时，商品/订单/广告/指标都标注为 mock；Live 连接的数据域
    永远标注为「未接入」，因为本期没有真实实现。
    """
    items = list(connections or [])
    mock_conns = [c for c in items if (c.get("mode") or MODE_MOCK) == MODE_MOCK]
    live_conns = [c for c in items if c.get("mode") == MODE_LIVE]
    last_sync = None
    if mock_conns:
        stamps = [c.get("last_sync_at") for c in mock_conns if c.get("last_sync_at")]
        last_sync = max(stamps) if stamps else None

    statuses: list[dict[str, Any]] = []
    for domain in DATA_DOMAINS:
        key = domain["domain"]
        if key == "stores":
            mode = MODE_LIVE if live_conns else MODE_MOCK
            configured = bool(mock_conns)
        elif key == "competitors":
            # 竞品数据来自用户上传或示例数据集，不由 Provider 提供
            statuses.append(
                DataSourceStatus(
                    domain=key,
                    label=domain["label"],
                    detail=domain["detail"],
                    live_target=domain["live_target"],
                    mode="upload",
                    configured=True,
                    extra={"note": "来自用户上传或示例数据集，带「示例」标记"},
                ).as_dict()
            )
            continue
        else:
            mode = MODE_MOCK if mock_conns else MODE_LIVE
            configured = bool(mock_conns)

        statuses.append(
            DataSourceStatus(
                domain=key,
                label=domain["label"],
                detail=domain["detail"],
                live_target=domain["live_target"],
                mode=mode,
                configured=configured,
                last_sync_at=last_sync,
                extra={"connection_count": len(mock_conns) if mode == MODE_MOCK else len(live_conns)},
            ).as_dict()
        )
    return statuses


def build_marketplace_provider(
    connection: dict[str, Any],
    *,
    credentials: dict[str, Any] | None = None,
) -> MarketplaceDataProvider:
    """按 ``connection["mode"]`` 选择实现；未知模式明确报错，不静默回退。"""
    mode = (connection.get("mode") or MODE_MOCK).strip().lower()
    factory = PROVIDER_REGISTRY.get(mode)
    if factory is None:
        raise UnknownProviderMode(
            f"未知的数据源模式 {mode!r}，可选：{', '.join(sorted(PROVIDER_REGISTRY))}"
        )
    if factory is LiveMarketplaceProvider:
        return LiveMarketplaceProvider(connection, credentials=credentials)
    return factory(connection)


__all__ = [
    "DATA_DOMAINS",
    "DataSourceStatus",
    "LiveMarketplaceProvider",
    "MODE_LIVE",
    "MODE_MOCK",
    "MarketplaceDataProvider",
    "MockMarketplaceProvider",
    "PROVIDER_REGISTRY",
    "ProviderNotConfigured",
    "UnknownProviderMode",
    "build_marketplace_provider",
    "describe_data_sources",
    "provider_for_mode",
]
