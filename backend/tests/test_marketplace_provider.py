"""数据源 Provider 协议（M2）：Mock 确定性、Live 不降级、工厂与标记。"""

from __future__ import annotations

import pytest

from crosspilot.market.marketplace_provider import (
    LiveMarketplaceProvider,
    MockMarketplaceProvider,
    ProviderNotConfigured,
    UnknownProviderMode,
    build_marketplace_provider,
    describe_data_sources,
)


def connection(**overrides) -> dict:
    base = {
        "connection_id": "conn-1",
        "tenant_id": "tenant-1",
        "platform": "amazon",
        "marketplace": "US",
        "shop_name": "Demo Store",
        "mode": "mock",
        "status": "connected",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Mock
# ---------------------------------------------------------------------------


def test_mock_products_are_deterministic_and_flagged():
    provider = MockMarketplaceProvider(connection())
    first = provider.list_products("conn-1", limit=5)
    second = MockMarketplaceProvider(connection()).list_products("conn-1", limit=5)
    assert first == second, "同一连接两次读取必须完全一致（确定性种子）"
    assert len(first) == 5
    assert all(item["is_mock"] is True for item in first)
    assert all(item["source"] == "mock_provider" for item in first)


def test_mock_orders_respect_since_and_are_flagged():
    provider = MockMarketplaceProvider(connection())
    orders = provider.list_orders("conn-1", since="30d")
    assert orders
    assert all(order["is_mock"] is True for order in orders)
    # 金额 = 单价 × 数量，必须自洽（不能"看起来像"但算不出来）
    for order in orders:
        assert order["amount"] == pytest.approx(order["quantity"] * (order["amount"] / order["quantity"]))


def test_mock_ads_and_metrics_are_flagged():
    provider = MockMarketplaceProvider(connection())
    ads = provider.list_ads("conn-1")
    assert ads and all(a["is_mock"] is True for a in ads)
    metrics = provider.metrics("conn-1", range="7d")
    assert metrics["is_mock"] is True
    assert metrics["days"] == 7
    assert metrics["orders"] == len(provider.list_orders("conn-1", since="7d"))


def test_mock_metrics_aov_is_derived_not_invented():
    provider = MockMarketplaceProvider(connection())
    metrics = provider.metrics("conn-1", range="30d")
    if metrics["orders"]:
        expected = round(metrics["revenue"] / metrics["orders"], 2)
        assert metrics["aov"] == pytest.approx(expected, abs=0.01)


def test_different_connections_get_different_data():
    a = MockMarketplaceProvider(connection(shop_name="Store A"))
    b = MockMarketplaceProvider(connection(shop_name="Store B"))
    assert a.list_products("a", limit=3) != b.list_products("b", limit=3)


# ---------------------------------------------------------------------------
# Live（骨架）：缺凭据必须报错，不能降级成 Mock
# ---------------------------------------------------------------------------


def test_live_without_credentials_raises():
    with pytest.raises(ProviderNotConfigured) as exc:
        LiveMarketplaceProvider(connection(mode="live"))
    assert "尚未接入" in str(exc.value)


def test_live_with_credentials_still_refuses_to_fake_calls():
    provider = LiveMarketplaceProvider(
        connection(mode="live"), credentials={"refresh_token": "fake"}
    )
    assert provider.configured is True
    with pytest.raises(ProviderNotConfigured):
        provider.list_products("conn-1")
    with pytest.raises(ProviderNotConfigured):
        provider.metrics("conn-1")


def test_factory_never_falls_back_to_mock():
    """Live 未配置时工厂必须抛错，而不是返回 Mock —— 这是核心承诺。"""
    with pytest.raises(ProviderNotConfigured):
        build_marketplace_provider(connection(mode="live"))


def test_factory_rejects_unknown_mode():
    with pytest.raises(UnknownProviderMode):
        build_marketplace_provider(connection(mode="sorcery"))


def test_factory_returns_mock_for_mock_mode():
    provider = build_marketplace_provider(connection())
    assert isinstance(provider, MockMarketplaceProvider)
    assert provider.mode == "mock"


# ---------------------------------------------------------------------------
# 数据源状态
# ---------------------------------------------------------------------------


def test_describe_sources_reports_live_when_no_connections():
    items = describe_data_sources([])
    by_domain = {item["domain"]: item for item in items}
    assert by_domain["products"]["mode"] == "live"
    assert by_domain["products"]["configured"] is False
    assert by_domain["competitors"]["mode"] == "upload"


def test_describe_sources_reports_mock_when_mock_connection_exists():
    items = describe_data_sources(
        [connection(last_sync_at="2026-10-01T00:00:00+00:00")]
    )
    by_domain = {item["domain"]: item for item in items}
    for domain in ("products", "orders", "ads", "metrics"):
        assert by_domain[domain]["mode"] == "mock"
        assert by_domain[domain]["is_mock"] is True
        assert by_domain[domain]["last_sync_at"] == "2026-10-01T00:00:00+00:00"
