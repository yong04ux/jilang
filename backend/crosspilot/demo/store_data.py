"""演示店铺数据（纯数据 + 纯函数，不依赖 services，避免循环导入）。

用途：给演示站（demo 账号与一键体验的临时账号）预置几家"看起来像真的"店铺，
让访问者进来就有东西可看。**所有记录都带 ``is_mock=True`` / ``is_demo=True``**，
不会与真实平台数据混淆。

为什么不用 ``MockStoreConnector`` 的随机数据：那边生成的是
``"Mock Amazon Product 1"``，能证明"链路通"，但没法用来演示。这里给的是
有品牌、有价格带、有评分分布的目录数据，与 ``seed.py`` 的报告/Listing 保持同一批品牌
（EcoSip / PeakTrail / LumiGlow），故事线连贯。

约定：

- 店铺名是幂等键（与 ``store_connections`` 的唯一索引一致）；
- 订单时间相对"今天"生成（近 30 天），每次 seed 的日期会顺延，但**同一天内确定**；
- 命中本目录的店铺由 ``MockStoreConnector`` 直接返回这批数据；没命中的自建店铺
  仍走原随机逻辑，行为不变。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# 店铺
# ---------------------------------------------------------------------------

DEMO_STORES: tuple[dict[str, Any], ...] = (
    {
        "platform": "amazon",
        "marketplace": "US",
        "shop_name": "EcoSip Official Store",
        "profile": "ecosip",
        "currency": "USD",
        "note": "饮水器具自营店，主力 SKU 为不锈钢保温杯",
    },
    {
        "platform": "amazon",
        "marketplace": "US",
        "shop_name": "PeakTrail Outdoors",
        "profile": "peaktrail",
        "currency": "USD",
        "note": "户外装备店，季节性强，背包为流量款",
    },
    {
        "platform": "tiktok",
        "marketplace": "US",
        "shop_name": "LumiGlow Home",
        "profile": "lumiglow",
        "currency": "USD",
        "note": "TikTok Shop 家居店，短视频带货为主",
    },
)

#: shop_name → 店铺定义
_STORE_BY_NAME: dict[str, dict[str, Any]] = {
    store["shop_name"]: store for store in DEMO_STORES
}


# ---------------------------------------------------------------------------
# 商品目录（每个店铺一组）
# ---------------------------------------------------------------------------

_CATALOGS: dict[str, tuple[dict[str, Any], ...]] = {
    "ecosip": (
        {
            "product_id": "demo-ecosip-b07x1",
            "asin": "B07X1MOCK1",
            "sku": "ECO-BTL-750-BLK",
            "name": "EcoSip Insulated Water Bottle 750ml - Matte Black",
            "price": 28.99,
            "rating": 4.6,
            "review_count": 12480,
            "stock": 386,
            "status": "active",
        },
        {
            "product_id": "demo-ecosip-b07x2",
            "asin": "B07X2MOCK2",
            "sku": "ECO-BTL-500-SGE",
            "name": "EcoSip Insulated Water Bottle 500ml - Sage Green",
            "price": 24.99,
            "rating": 4.5,
            "review_count": 5310,
            "stock": 214,
            "status": "active",
        },
        {
            "product_id": "demo-ecosip-b07x3",
            "asin": "B07X3MOCK3",
            "sku": "ECO-LID-SPORT",
            "name": "EcoSip Sport Lid Replacement (2-Pack)",
            "price": 9.99,
            "rating": 4.3,
            "review_count": 1870,
            "stock": 902,
            "status": "active",
        },
        {
            "product_id": "demo-ecosip-b07x4",
            "asin": "B07X4MOCK4",
            "sku": "ECO-BTL-1000-NAV",
            "name": "EcoSip Insulated Water Bottle 1L - Navy",
            "price": 32.99,
            "rating": 4.7,
            "review_count": 3125,
            "stock": 0,
            "status": "paused",
        },
    ),
    "peaktrail": (
        {
            "product_id": "demo-peak-p40l",
            "asin": "B08P1MOCK1",
            "sku": "PT-BP-40L-OLV",
            "name": "PeakTrail Hiking Backpack 40L - Olive",
            "price": 79.0,
            "rating": 4.4,
            "review_count": 7620,
            "stock": 132,
            "status": "active",
        },
        {
            "product_id": "demo-peak-p25l",
            "asin": "B08P2MOCK2",
            "sku": "PT-BP-25L-BLK",
            "name": "PeakTrail Daypack 25L - Black",
            "price": 54.0,
            "rating": 4.2,
            "review_count": 3180,
            "stock": 268,
            "status": "active",
        },
        {
            "product_id": "demo-peak-rain",
            "asin": "B08P3MOCK3",
            "sku": "PT-RC-UNI",
            "name": "PeakTrail Packable Rain Cover",
            "price": 16.5,
            "rating": 4.1,
            "review_count": 940,
            "stock": 610,
            "status": "active",
        },
    ),
    "lumiglow": (
        {
            "product_id": "demo-lumi-desk",
            "asin": "B09L1MOCK1",
            "sku": "LG-DESK-PRO-WHT",
            "name": "LumiGlow Desk Lamp Pro - Warm White",
            "price": 45.99,
            "rating": 4.5,
            "review_count": 2260,
            "stock": 175,
            "status": "active",
        },
        {
            "product_id": "demo-lumi-strip",
            "asin": "B09L2MOCK2",
            "sku": "LG-STRIP-3M",
            "name": "LumiGlow LED Strip Light 3m - RGB",
            "price": 21.99,
            "rating": 4.3,
            "review_count": 4890,
            "stock": 430,
            "status": "active",
        },
        {
            "product_id": "demo-lumi-clip",
            "asin": "B09L3MOCK3",
            "sku": "LG-CLIP-MINI",
            "name": "LumiGlow Clip Reading Light (USB-C)",
            "price": 14.99,
            "rating": 4.0,
            "review_count": 1120,
            "stock": 0,
            "status": "paused",
        },
    ),
}

#: 订单状态分布：演示里让"已完成 / 已发货 / 待发货"都有，看起来像真在运营
_ORDER_STATUSES = ("delivered", "delivered", "shipped", "shipped", "pending")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def demo_catalog(shop_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """按店铺名取演示目录，返回 ``(products, orders)``；非演示店铺返回 ``None``。"""
    store = _STORE_BY_NAME.get(shop_name)
    if store is None:
        return None
    profile = store["profile"]
    templates = _CATALOGS.get(profile)
    if not templates:
        return None

    rng = random.Random(f"demo-catalog|{profile}")
    # 对齐到"今天 00:00"再回退 30 天：同一天内反复刷新数据必须一致，
    # 否则列表页的金额与时间每次都在变，看起来像在抖。
    today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    base = today - timedelta(days=30)
    currency = store["currency"]

    products: list[dict[str, Any]] = [
        {
            **item,
            "currency": currency,
            "marketplace": store["marketplace"],
            "is_mock": True,
            "is_demo": True,
            "source": "demo_catalog",
        }
        for item in templates
    ]

    orders: list[dict[str, Any]] = []
    for index in range(1, 9):
        item = templates[index % len(templates)]
        quantity = rng.randint(1, 3)
        created = base + timedelta(days=index * 3, hours=rng.randint(0, 12))
        orders.append(
            {
                "order_id": f"DEMO-{profile.upper()}-{index:04d}",
                "sku": item["sku"],
                "product_name": item["name"],
                "quantity": quantity,
                "amount": round(item["price"] * quantity, 2),
                "currency": currency,
                "status": _ORDER_STATUSES[index % len(_ORDER_STATUSES)],
                "created_at": created.isoformat(),
                "is_mock": True,
                "is_demo": True,
                "source": "demo_catalog",
            }
        )
    orders.sort(key=lambda row: row["created_at"], reverse=True)
    return products, orders


def demo_sync_summary(products: list[dict[str, Any]], orders: list[dict[str, Any]]) -> dict[str, Any]:
    """与 ``MockStoreConnector.sync()`` 同形状的汇总，另加演示展示需要的指标。"""
    revenue = round(sum(order["amount"] for order in orders), 2)
    units = sum(order["quantity"] for order in orders)
    order_count = len(orders)
    return {
        "mode": "mock",
        "is_mock": True,
        "is_demo": True,
        "products": len(products),
        "orders": order_count,
        "units": units,
        "revenue": revenue,
        "currency": orders[0]["currency"] if orders else "USD",
        "avg_order_value": round(revenue / order_count, 2) if order_count else 0.0,
        "active_products": sum(1 for p in products if p.get("status") == "active"),
        "detail": "演示店铺数据；用于功能展示，不可用于真实经营决策",
    }


def is_demo_shop(shop_name: str) -> bool:
    return shop_name in _STORE_BY_NAME


__all__ = [
    "DEMO_STORES",
    "demo_catalog",
    "demo_sync_summary",
    "is_demo_shop",
]
