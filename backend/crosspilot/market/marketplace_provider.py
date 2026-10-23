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

PRODUCT_COUNT = 12
AD_COUNT = 6

#: 每个店铺每天的基础订单量区间。日销波动感来自这两条线，
#: 不写死成「每天固定几单」——那样趋势图会是一条直线。
ORDER_DAILY_MIN = 3
ORDER_DAILY_MAX = 9

#: 单次 list_orders 最多返回多少行，防止窗口开太大把响应撑爆
ORDER_MAX_ROWS = 600

#: 约每 N 单产生一笔售后单
RETURN_EVERY = 12

#: 下单时段权重（0-23 点）：午间与晚间各一个峰，凌晨最低
_HOUR_WEIGHTS: tuple[int, ...] = (
    1, 1, 1, 1, 2, 3, 5, 8, 11, 13, 14, 13,
    12, 12, 11, 11, 12, 14, 16, 18, 16, 12, 7, 3,
)

#: 目的国分布权重；站点所在国额外加权，其余是常见的联程配送国家
_REGION_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("US", 58), ("CA", 11), ("GB", 8), ("AU", 6), ("DE", 5),
    ("JP", 4), ("FR", 3), ("MX", 3), ("IT", 2),
)

#: 退款原因（覆盖最常见的几类，用于售后单）
RETURN_REASONS: tuple[str, ...] = (
    "商品与描述不符",
    "运输破损",
    "尺寸不合适",
    "不再需要",
    "发错货",
    "质量问题",
)

#: 库龄分档：列表顺序即展示顺序
AGING_BUCKETS: tuple[str, ...] = ("0-30", "31-60", "61-90", "91-180", "180+")

#: 库龄分布模板：新货型 / 常规型 / 积压型
_AGING_PROFILES: dict[str, tuple[int, ...]] = {
    "fresh": (70, 20, 7, 2, 1),
    "normal": (40, 30, 16, 9, 5),
    "slow": (10, 15, 20, 25, 30),
}

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

    # -- 经营看板扩展（店铺经营助手三页要用）---------------------------
    def list_returns(self, store_id: str) -> list[dict[str, Any]]: ...

    def inventory_aging(self, store_id: str) -> dict[str, Any]: ...

    def ads_summary(self, store_id: str) -> dict[str, Any]: ...

    def account_health(self, store_id: str) -> dict[str, Any]: ...

    def product_detail(self, store_id: str, asin: str) -> dict[str, Any] | None: ...


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


def _store_key(connection: dict[str, Any]) -> str:
    """按店铺维度做种子的字符串键（天级种子在此基础上再拼日期）。"""
    return "|".join(
        (
            str(connection.get("tenant_id", "")),
            str(connection.get("shop_name", "")),
            str(connection.get("marketplace", "")),
        )
    )


def _day_start(moment: datetime | None = None) -> datetime:
    """把时间对齐到当天 00:00（UTC）。

    所有模拟数据都以「天」为单位做种子：同一天内反复刷新读到同一份数据，
    窗口滑动只是加一天、减一天，不会把昨天已经看过的数字重算一遍。
    """
    base = moment or datetime.now(timezone.utc)
    return base.replace(hour=0, minute=0, second=0, microsecond=0)


def _order_status(day_offset: int, rng: random.Random) -> str:
    """按「距今多少天」推履约状态——昨天下的单不可能已经妥投。"""
    if day_offset <= 0:
        return "pending" if rng.random() < 0.55 else "shipped"
    if day_offset <= 2:
        return rng.choices(("shipped", "delivered"), weights=(4, 6), k=1)[0]
    return rng.choices(("delivered", "cancelled"), weights=(97, 3), k=1)[0]


def _aggregate(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    units = sum(int(row.get("quantity") or 0) for row in rows)
    revenue = round(sum(float(row.get("amount") or 0) for row in rows), 2)
    return {"orders": len(rows), "units": units, "revenue": revenue}


def _change_pct(current: float, previous: float) -> float | None:
    """环比涨跌幅（%）。上一窗口为 0 时返回 None —— 除零不编成 0%。"""
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _trend(rows: Iterable[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """把订单按日聚合成走势序列，没有出单的日子补 0（不能断点）。"""
    today = _day_start().date()
    buckets: dict[str, dict[str, Any]] = {}
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        buckets[day] = {"date": day, "salesAmount": 0.0, "unitCount": 0, "orderCount": 0}
    for row in rows:
        key = str(row.get("created_at") or "")[:10]
        bucket = buckets.get(key)
        if bucket is None:
            continue
        bucket["salesAmount"] = round(bucket["salesAmount"] + float(row.get("amount") or 0), 2)
        bucket["unitCount"] += int(row.get("quantity") or 0)
        bucket["orderCount"] += 1
    return list(buckets.values())


def _hour_distribution(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = [0] * 24
    for row in rows:
        stamp = str(row.get("created_at") or "")
        try:
            counts[int(stamp[11:13])] += 1
        except (ValueError, IndexError):
            continue
    return [{"hour": hour, "orderCount": counts[hour]} for hour in range(24)]


def _region_distribution(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        code = str(row.get("country") or "未知")
        counts[code] = counts.get(code, 0) + 1
    total = sum(counts.values()) or 1
    items = [
        {"country": code, "orderCount": count, "share": round(count / total * 100, 1)}
        for code, count in counts.items()
    ]
    items.sort(key=lambda item: item["orderCount"], reverse=True)
    return items


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
        return self._catalog()[: max(1, limit)]

    def _catalog(self) -> list[dict[str, Any]]:
        """店铺的商品目录。

        演示店铺优先用带品牌的固定目录（真实 ASIN / SKU / 价格 / 库存），
        这样「店铺授权」里看到的商品名和「经营看板」里的商品名是同一套，
        不会出现列表里是 EcoSip、看板里变成「模拟商品 3」的情况。
        """
        shop_name = str(self.connection.get("shop_name") or "")
        try:  # 演示目录属于 demo 层，按需导入，避免 market 层强依赖
            from ..demo.store_data import demo_catalog
        except Exception:  # noqa: BLE001 - 拿不到演示目录就退回生成目录
            demo_catalog = None  # type: ignore[assignment]
        if demo_catalog is not None:
            demo = demo_catalog(shop_name)
            if demo is not None:
                return demo[0]
        return self._generated_products()

    def _generated_products(self) -> list[dict[str, Any]]:
        rng = random.Random(_store_seed(self.connection))
        platform = (self.connection.get("platform") or "amazon").lower()
        marketplace = self.connection.get("marketplace") or "US"
        rows: list[dict[str, Any]] = []
        for index in range(1, PRODUCT_COUNT + 1):
            price = round(rng.uniform(9.9, 79.9), 2)
            stock = rng.randint(0, 480)
            rows.append(
                {
                    "product_id": f"mock-{platform}-{index:03d}",
                    "store_id": self.store_id,
                    "asin": f"MOCK{index:07d}",
                    "sku": f"SKU-{index:04d}",
                    "name": f"模拟商品 {index}（{platform}）",
                    "price": price,
                    "currency": "USD",
                    "rating": round(rng.uniform(3.5, 4.9), 1),
                    "review_count": rng.randint(12, 4200),
                    "stock": stock,
                    "status": "active" if stock else "paused",
                    "marketplace": marketplace,
                    "is_mock": True,
                    "source": "mock_provider",
                }
            )
        return rows

    # -- 订单 -----------------------------------------------------------
    def list_orders(self, store_id: str, *, since: str) -> list[dict[str, Any]]:
        return self._orders_window(store_id, _parse_range_days(since))

    def _orders_window(
        self, store_id: str, days: int, *, end_offset: int = 0
    ) -> list[dict[str, Any]]:
        """生成某段时间窗口内的订单。

        窗口是 ``[今天 - end_offset - days + 1, 今天 - end_offset]``。
        ``end_offset`` 用来取「上一个等长窗口」做环比对比。
        """
        products = self._catalog()
        key = _store_key(self.connection)
        marketplace = str(self.connection.get("marketplace") or "US").upper()
        platform = str(self.connection.get("platform") or "amazon").lower()
        currency = str((products[0].get("currency") if products else "USD") or "USD")
        # 销量权重按评论数开方：评论多的老品确实卖得多，但不至于一家独大
        weights = [
            max(1, int(max(1, int(product.get("review_count") or 1)) ** 0.5))
            for product in products
        ] or [1]
        region_codes = [code for code, _ in _REGION_WEIGHTS]
        region_weights = [
            weight + (30 if code == marketplace else 0) for code, weight in _REGION_WEIGHTS
        ]

        today = _day_start()
        rows: list[dict[str, Any]] = []
        for offset in range(days + end_offset - 1, end_offset - 1, -1):
            day = today - timedelta(days=offset)
            rng = random.Random(_seed(key, day.date().isoformat()))
            count = rng.randint(ORDER_DAILY_MIN, ORDER_DAILY_MAX)
            if day.weekday() >= 5:  # 周末单量抬一档
                count = int(round(count * 1.35))
            for index in range(count):
                product = rng.choices(products or [{}], weights=weights, k=1)[0]
                quantity = rng.choices((1, 2, 3), weights=(7, 2, 1), k=1)[0]
                unit_price = float(product.get("price") or 0) or round(rng.uniform(12.0, 68.0), 2)
                hour = rng.choices(range(24), weights=_HOUR_WEIGHTS, k=1)[0]
                created = day + timedelta(
                    hours=hour, minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
                )
                rows.append(
                    {
                        "order_id": f"MOCK-{marketplace}-{created:%Y%m%d}-{index:03d}",
                        "store_id": store_id or self.store_id,
                        "asin": product.get("asin"),
                        "sku": product.get("sku"),
                        "product_name": product.get("name"),
                        "quantity": quantity,
                        "amount": round(unit_price * quantity, 2),
                        "currency": currency,
                        "status": _order_status(offset, rng),
                        "country": rng.choices(region_codes, weights=region_weights, k=1)[0],
                        "created_at": created.isoformat(),
                        "platform": platform,
                        "is_mock": True,
                        "source": "mock_provider",
                    }
                )
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return rows[:ORDER_MAX_ROWS]

    # -- 广告 -----------------------------------------------------------
    def list_ads(self, store_id: str) -> list[dict[str, Any]]:
        """广告活动按「近 30 天真实销售额」反推，保证口径自洽。

        不能独立随机：否则会出现「广告销售额 1 万、全店销售额 6 千」
        这种一眼假的数据。这里先定广告贡献占比，再拆花费与点击。
        """
        products = self._catalog()
        rng = random.Random(_store_seed(self.connection) + 2)
        currency = str((products[0].get("currency") if products else "USD") or "USD")
        window = _aggregate(self._orders_window(store_id, 30))
        revenue = window["revenue"]
        aov = revenue / window["orders"] if window["orders"] else 0.0

        # 广告带来的销售额占全店的比重（其余是自然流量）
        ad_share = rng.uniform(0.32, 0.58)
        ad_revenue = round(revenue * ad_share, 2)
        # 各活动分到的权重
        weights = [rng.uniform(0.6, 1.6) for _ in range(AD_COUNT)]
        total_weight = sum(weights) or 1.0

        rows: list[dict[str, Any]] = []
        for index in range(1, AD_COUNT + 1):
            product = products[(index - 1) % len(products)] if products else {}
            sales = round(ad_revenue * weights[index - 1] / total_weight, 2)
            acos = rng.uniform(0.14, 0.36)
            spend = round(sales * acos, 2)
            cpc = round(rng.uniform(0.62, 1.42), 2)
            clicks = max(1, int(round(spend / cpc)))
            ctr = rng.uniform(0.0032, 0.0105)
            impressions = max(clicks, int(round(clicks / ctr)))
            orders = max(1, int(round(sales / aov))) if aov else 1
            rows.append(
                {
                    "campaign_id": f"MOCK-AD-{index:03d}",
                    "store_id": store_id or self.store_id,
                    "asin": product.get("asin"),
                    "sku": product.get("sku"),
                    "name": f"{product.get('name') or '模拟商品'} · 手动精准",
                    "status": rng.choices(("active", "paused"), weights=(7, 3), k=1)[0],
                    "impressions": impressions,
                    "clicks": clicks,
                    "spend": spend,
                    "sales": sales,
                    "orders": orders,
                    "ctr": round(clicks / impressions * 100, 2),
                    "cpc": round(spend / clicks, 2),
                    "acos": round(spend / sales * 100, 2) if sales else 0.0,
                    "roas": round(sales / spend, 2) if spend else 0.0,
                    "currency": currency,
                    "is_mock": True,
                    "source": "mock_provider",
                }
            )
        return rows

    def ads_summary(self, store_id: str) -> dict[str, Any]:
        campaigns = self.list_ads(store_id)
        impressions = sum(item["impressions"] for item in campaigns)
        clicks = sum(item["clicks"] for item in campaigns)
        spend = round(sum(item["spend"] for item in campaigns), 2)
        sales = round(sum(item["sales"] for item in campaigns), 2)
        orders = sum(item["orders"] for item in campaigns)
        # 汇总口径的比率必须由汇总后的分子分母重算，不能把各行比率再平均
        metrics = {
            "impressions": impressions,
            "clicks": clicks,
            "spend": spend,
            "adSales": sales,
            "adOrders": orders,
            "ctr": round(clicks / impressions * 100, 2) if impressions else 0.0,
            "cpc": round(spend / clicks, 2) if clicks else 0.0,
            "acos": round(spend / sales * 100, 2) if sales else 0.0,
            "roas": round(sales / spend, 2) if spend else 0.0,
        }
        top = sorted(campaigns, key=lambda item: item["sales"], reverse=True)[:5]
        return {
            "metrics": metrics,
            "campaigns": campaigns,
            "topProducts": top,
            "currency": campaigns[0]["currency"] if campaigns else "USD",
            "is_mock": True,
            "source": "mock_provider",
        }

    # -- 指标 -----------------------------------------------------------
    def metrics(self, store_id: str, *, range: str = "30d") -> dict[str, Any]:
        days = _parse_range_days(range)
        current = self._orders_window(store_id, days)
        previous = self._orders_window(store_id, days, end_offset=days)
        now = _aggregate(current)
        before = _aggregate(previous)
        currency = str((current[0].get("currency") if current else "USD") or "USD")
        aov = round(now["revenue"] / now["orders"], 2) if now["orders"] else 0.0
        prev_aov = round(before["revenue"] / before["orders"], 2) if before["orders"] else 0.0
        return {
            "store_id": store_id or self.store_id,
            "range": range,
            "days": days,
            "orders": now["orders"],
            "units": now["units"],
            "revenue": now["revenue"],
            "currency": currency,
            "aov": aov,
            "salesTrend": _trend(current, days),
            "salesMetrics": {
                "salesAmount": {
                    "label": "销售额",
                    "value": now["revenue"],
                    "changePct": _change_pct(now["revenue"], before["revenue"]),
                },
                "unitCount": {
                    "label": "销量",
                    "value": now["units"],
                    "changePct": _change_pct(now["units"], before["units"]),
                },
                "orderCount": {
                    "label": "订单量",
                    "value": now["orders"],
                    "changePct": _change_pct(now["orders"], before["orders"]),
                },
                "aov": {
                    "label": "客单价",
                    "value": aov,
                    "changePct": _change_pct(aov, prev_aov),
                },
            },
            "hourDistribution": _hour_distribution(current),
            "regionDistribution": _region_distribution(current),
            "is_mock": True,
            "source": "mock_provider",
            "note": "由模拟订单聚合，仅用于演示；不代表真实经营数据",
        }

    # -- 售后 -----------------------------------------------------------
    def list_returns(self, store_id: str) -> list[dict[str, Any]]:
        """按固定间隔从订单里抽出一部分作为售后单（确定性，不随机跳）。"""
        orders = self._orders_window(store_id, 30)
        key = _store_key(self.connection)
        rows: list[dict[str, Any]] = []
        for index in range(0, len(orders), RETURN_EVERY):
            order = orders[index]
            rng = random.Random(_seed(key, "return", str(order["order_id"])))
            age_days = max(0, (_day_start() - _parse_day(str(order.get("created_at")))).days)
            status = "refunded" if age_days >= 5 else rng.choices(
                ("pending", "processing"), weights=(6, 4), k=1
            )[0]
            rows.append(
                {
                    "return_id": f"MOCK-RMA-{order['order_id'].split('-')[-2]}-{index // RETURN_EVERY + 1:03d}",
                    "order_id": order["order_id"],
                    "asin": order.get("asin"),
                    "sku": order.get("sku"),
                    "product_name": order.get("product_name"),
                    "quantity": 1,
                    "refund_amount": order["amount"],
                    "currency": order["currency"],
                    "reason": RETURN_REASONS[rng.randrange(len(RETURN_REASONS))],
                    "status": status,
                    "status_label": {"pending": "待审核", "processing": "处理中", "refunded": "已退款"}[
                        status
                    ],
                    "requested_at": order["created_at"],
                    "is_mock": True,
                    "source": "mock_provider",
                }
            )
        rows.sort(key=lambda row: row["requested_at"], reverse=True)
        return rows

    # -- 库存与库龄 -----------------------------------------------------
    def inventory_aging(self, store_id: str) -> dict[str, Any]:
        products = self._catalog()
        key = _store_key(self.connection)
        sold: dict[str, int] = {}
        for order in self._orders_window(store_id, 30):
            sku = str(order.get("sku") or "")
            sold[sku] = sold.get(sku, 0) + int(order.get("quantity") or 0)

        rows: list[dict[str, Any]] = []
        for product in products:
            sku = str(product.get("sku") or "")
            rng = random.Random(_seed(key, "inventory", sku))
            available = int(product.get("stock") or 0)
            reserved = rng.randint(0, 24) if available else 0
            inbound = rng.choices((0, rng.randint(30, 220)), weights=(6, 4), k=1)[0]
            profile = rng.choices(("fresh", "normal", "slow"), weights=(5, 3, 2), k=1)[0]
            shares = _AGING_PROFILES[profile]
            buckets: dict[str, int] = {}
            remaining = available
            for position, label in enumerate(AGING_BUCKETS):
                if position == len(AGING_BUCKETS) - 1:
                    buckets[label] = remaining
                else:
                    take = min(remaining, int(available * shares[position] / 100))
                    buckets[label] = take
                    remaining -= take

            sold_30d = sold.get(sku, 0)
            daily = sold_30d / 30 if sold_30d else 0.0
            turnover_days = round(available / daily, 1) if daily > 0 else None
            if available <= 0:
                flag, flag_label, level = "out_of_stock", "已断货", "danger"
            elif available < 15:
                flag, flag_label, level = "low_stock", "库存偏低", "warning"
            elif sold_30d == 0:
                flag, flag_label, level = "slow_moving", "滞销", "warning"
            else:
                flag, flag_label, level = "healthy", "正常", "ok"

            rows.append(
                {
                    "asin": product.get("asin"),
                    "sku": sku,
                    "name": product.get("name"),
                    "available": available,
                    "reserved": reserved,
                    "inbound": inbound,
                    "sold30d": sold_30d,
                    "turnoverDays": turnover_days,
                    "aging": buckets,
                    "flag": flag,
                    "flagLabel": flag_label,
                    "level": level,
                }
            )

        totals = {
            "available": sum(row["available"] for row in rows),
            "reserved": sum(row["reserved"] for row in rows),
            "inbound": sum(row["inbound"] for row in rows),
            "outOfStock": sum(1 for row in rows if row["flag"] == "out_of_stock"),
            "lowStock": sum(1 for row in rows if row["flag"] == "low_stock"),
            "slowMoving": sum(1 for row in rows if row["flag"] == "slow_moving"),
        }
        aging_totals = {
            label: sum(row["aging"][label] for row in rows) for label in AGING_BUCKETS
        }
        return {
            "items": rows,
            "totals": totals,
            "agingTotals": aging_totals,
            "is_mock": True,
            "source": "mock_provider",
        }

    # -- 店铺绩效 -------------------------------------------------------
    def account_health(self, store_id: str) -> dict[str, Any]:
        rng = random.Random(_store_seed(self.connection) + 7)
        score = rng.randint(620, 980)
        warnings = rng.choices((0, 1, 2), weights=(6, 3, 1), k=1)[0]
        violations = 0 if score >= 700 else 1
        healthy = score >= 700 and violations == 0
        return {
            "status": "healthy" if healthy else "at_risk",
            "statusLabel": "正常" if healthy else "需关注",
            "ahrScore": score,
            "ahrMax": 1000,
            "policyViolations": violations,
            "warnings": warnings,
            "items": [
                {"label": "账户状态", "value": "正常" if healthy else "需关注",
                 "level": "ok" if healthy else "warning"},
                {"label": "账户健康评分", "value": f"{score} / 1000",
                 "level": "ok" if healthy else "warning"},
                {"label": "政策违规", "value": f"{violations} 项",
                 "level": "ok" if violations == 0 else "danger"},
                {"label": "违规警告", "value": f"{warnings} 项",
                 "level": "ok" if warnings == 0 else "warning"},
            ],
            "sourceLabel": "平台账户状态",
            "is_mock": True,
        }

    # -- 单品 -----------------------------------------------------------
    def product_detail(self, store_id: str, asin: str) -> dict[str, Any] | None:
        products = self._catalog()
        product = next(
            (item for item in products if str(item.get("asin")) == str(asin)), None
        )
        if product is None:
            return None
        sku = str(product.get("sku") or "")
        days = 30
        current = [
            order for order in self._orders_window(store_id, days)
            if str(order.get("sku")) == sku
        ]
        previous = [
            order for order in self._orders_window(store_id, days, end_offset=days)
            if str(order.get("sku")) == sku
        ]
        now = _aggregate(current)
        before = _aggregate(previous)
        ads = [item for item in self.list_ads(store_id) if str(item.get("sku")) == sku]
        inventory = next(
            (
                row for row in self.inventory_aging(store_id)["items"]
                if str(row.get("sku")) == sku
            ),
            None,
        )

        warnings: list[dict[str, str]] = []
        stock = int(product.get("stock") or 0)
        if stock <= 0:
            warnings.append({"level": "danger", "text": "已断货，建议尽快补货"})
        elif stock < 15:
            warnings.append({"level": "warning", "text": "库存偏低，按当前销量不足一周"})
        if now["orders"] == 0:
            warnings.append({"level": "warning", "text": "近 30 天没有出单记录"})
        rating = float(product.get("rating") or 0)
        if rating and rating < 4.2:
            warnings.append({"level": "warning", "text": f"评分 {rating} 低于同类主流水平"})

        return {
            "product": product,
            "range": "30d",
            "days": days,
            "currency": str(product.get("currency") or "USD"),
            "metrics": {
                "salesAmount": {
                    "label": "销售额", "value": now["revenue"],
                    "changePct": _change_pct(now["revenue"], before["revenue"]),
                },
                "unitCount": {
                    "label": "销量", "value": now["units"],
                    "changePct": _change_pct(now["units"], before["units"]),
                },
                "orderCount": {
                    "label": "订单量", "value": now["orders"],
                    "changePct": _change_pct(now["orders"], before["orders"]),
                },
            },
            "trend": _trend(current, days),
            "ads": ads,
            "adsMetrics": {
                "impressions": sum(item["impressions"] for item in ads),
                "clicks": sum(item["clicks"] for item in ads),
                "spend": round(sum(item["spend"] for item in ads), 2),
                "adSales": round(sum(item["sales"] for item in ads), 2),
            },
            "inventory": inventory,
            "warnings": warnings,
            "is_mock": True,
            "source": "mock_provider",
        }


def _parse_day(value: str) -> datetime:
    """把 ISO 时间串解析成当天 00:00；解析不了就退回今天。"""
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return _day_start()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_range_days(range_value: str) -> int:
    """把时间范围解析成天数。

    支持三种写法：``30d`` / ``today|week|month|quarter`` / ISO 时间串。
    ISO 那条分支是给 ``list_orders(since=...)`` 复用的——历史上它收的是
    绝对时间，改成相对天数后不能把老调用方直接打死。
    """
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
    try:
        start = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 30
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    span = (_day_start() - start.replace(hour=0, minute=0, second=0, microsecond=0)).days + 1
    return max(1, min(span, 365))


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

    def list_returns(self, store_id: str) -> list[dict[str, Any]]:
        self._fail()

    def inventory_aging(self, store_id: str) -> dict[str, Any]:
        self._fail()

    def ads_summary(self, store_id: str) -> dict[str, Any]:
        self._fail()

    def account_health(self, store_id: str) -> dict[str, Any]:
        self._fail()

    def product_detail(self, store_id: str, asin: str) -> dict[str, Any] | None:
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
