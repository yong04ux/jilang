"""跨境平台目录（预留接口）与演示店铺数据。

覆盖两件事：
1. 平台目录是"真实可用的元数据"——URL 能拼、能力能查、未知平台不炸；
2. 演示账户进去就有三家带数据的店铺，且数据来源可区分（演示 vs 自建随机 Mock）。
"""

from __future__ import annotations

import pytest

from crosspilot.demo.store_data import DEMO_STORES, demo_catalog
from crosspilot.demo.store_seed import seed_demo_stores
from crosspilot.market.platforms import (
    ALL_CAPABILITIES,
    PLATFORMS,
    PlatformNotConnected,
    UnknownPlatform,
    build_authorize_url,
    exchange_code,
    is_known,
    platform_spec,
)


def register(client, username: str) -> dict[str, str]:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def identity(client, headers: dict[str, str]) -> dict[str, str]:
    body = client.get("/api/tenants/current", headers=headers).json()
    return {"user_id": body["user_id"], "tenant_id": body["tenant_id"]}


# ---------------------------------------------------------------------------
# 平台目录
# ---------------------------------------------------------------------------


def test_catalog_covers_major_cross_border_platforms():
    keys = [spec.key for spec in PLATFORMS]
    assert len(keys) == len(set(keys)), "平台 key 必须唯一"
    for expected in ("amazon", "temu", "tiktok", "shopee", "ebay", "shopify"):
        assert expected in keys, expected
    for spec in PLATFORMS:
        assert spec.capabilities, f"{spec.key} 没有声明任何能力"
        assert set(spec.capabilities) <= set(ALL_CAPABILITIES)
        assert spec.marketplaces, f"{spec.key} 没有声明站点"
        # 本期全部未接入，不能有任何平台声称可用
        assert spec.live_status == "not_configured", spec.key


def test_unknown_platform_is_none_not_error():
    """未知平台不能抛错：历史数据与自建店铺可能带任意 platform。"""
    assert platform_spec("no-such-marketplace") is None
    assert platform_spec("") is None
    assert platform_spec(None) is None
    assert is_known("amazon") is True
    assert is_known("no-such-marketplace") is False


def test_authorize_url_contains_required_params():
    url = build_authorize_url(
        "amazon",
        client_id="amzn1.application-oa2-client.demo",
        redirect_uri="https://example.com/callback",
        state="state-123",
    )
    assert url.startswith("https://sellercentral.amazon.com/apps/authorize/consent?")
    assert "client_id=amzn1.application-oa2-client.demo" in url
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in url
    assert "state=state-123" in url
    assert "response_type=code" in url
    assert "version=beta" in url  # 平台特有参数


def test_authorize_url_requires_credentials():
    with pytest.raises(PlatformNotConnected):
        build_authorize_url(
            "amazon", client_id="", redirect_uri="https://example.com/cb", state="s"
        )


def test_shopify_url_needs_shop_domain():
    with pytest.raises(PlatformNotConnected):
        build_authorize_url(
            "shopify",
            client_id="cid",
            redirect_uri="https://example.com/cb",
            state="s",
            shop="",
        )
    url = build_authorize_url(
        "shopify",
        client_id="cid",
        redirect_uri="https://example.com/cb",
        state="s",
        shop="demo-store.myshopify.com",
    )
    assert url.startswith("https://demo-store.myshopify.com/admin/oauth/authorize?")


def test_authorize_url_rejects_unknown_platform():
    with pytest.raises(UnknownPlatform):
        build_authorize_url(
            "myspace", client_id="c", redirect_uri="https://e.com/cb", state="s"
        )


def test_platforms_without_user_consent_cannot_build_authorize_url():
    """Walmart 走 client_credentials、自定义站走自有接口，都不该给出授权跳转。"""
    for key in ("walmart", "custom"):
        with pytest.raises(PlatformNotConnected):
            build_authorize_url(
                key, client_id="c", redirect_uri="https://e.com/cb", state="s"
            )


def test_exchange_code_reports_not_connected():
    """换 token 未实现必须显式报错，不能返回假 token。"""
    with pytest.raises(PlatformNotConnected) as info:
        exchange_code("amazon", code="abc")
    assert "尚未接入" in str(info.value)


def test_platforms_endpoint_is_public_and_lists_catalog(client):
    """平台目录是公开信息（不含凭据），与既有的平台规则共用 /api/platforms。"""
    resp = client.get("/api/platforms")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # 原有字段保持向后兼容
    assert "platforms" in body and "marketplaces" in body
    # 新增的数据接入目录
    assert body["default_platform"] == "amazon"
    assert body["capabilities"] == list(ALL_CAPABILITIES)
    assert "not_configured" in body["catalog_note"]

    catalog = {item["key"]: item for item in body["catalog"]}
    assert len(catalog) == len(PLATFORMS)
    amazon = catalog["amazon"]
    assert amazon["product_id_field"] == "asin"
    assert "orders" in amazon["capabilities"]
    assert amazon["live_status"] == "not_configured"


# ---------------------------------------------------------------------------
# 演示店铺
# ---------------------------------------------------------------------------


def test_demo_stores_are_seeded_with_data(client):
    headers = register(client, "demo_store")
    ident = identity(client, headers)
    db = client.app.state.db

    stats = seed_demo_stores(db, ident["tenant_id"], user_id=ident["user_id"])
    assert stats["created"] == len(DEMO_STORES)
    assert stats["synced"] == len(DEMO_STORES)

    body = client.get("/api/stores", headers=headers).json()
    assert len(body["items"]) == len(DEMO_STORES)
    assert all(item["is_demo"] is True for item in body["items"])
    assert all(item["is_mock"] is True for item in body["items"])
    assert all(item["last_sync_status"] == "ok" for item in body["items"])
    assert all(item["platform_known"] is True for item in body["items"])

    summary = body["items"][0]["last_sync_summary"]
    assert summary["products"] > 0 and summary["orders"] > 0
    assert summary["is_demo"] is True
    assert summary["revenue"] > 0
    assert summary["avg_order_value"] > 0


def test_demo_products_are_presentable_not_placeholder(client):
    """演示店铺的商品要能拿去展示：有品牌与价格，而不是 "Mock Amazon Product 1"。"""
    headers = register(client, "demo_products")
    ident = identity(client, headers)
    seed_demo_stores(client.app.state.db, ident["tenant_id"], user_id=ident["user_id"])

    body = client.get("/api/stores", headers=headers).json()
    ecosip = next(item for item in body["items"] if "EcoSip" in item["shop_name"])
    products = client.get(
        f"/api/stores/{ecosip['connection_id']}/products", headers=headers
    ).json()["items"]

    assert products
    for item in products:
        assert not item["name"].startswith("Mock "), item["name"]
        assert item["is_mock"] is True
        assert item["price"] > 0
        assert item["sku"]
    assert any("EcoSip" in item["name"] for item in products)

    orders = client.get(
        f"/api/stores/{ecosip['connection_id']}/orders", headers=headers
    ).json()["items"]
    assert orders
    assert all(order["amount"] > 0 for order in orders)
    assert {order["status"] for order in orders} <= {"delivered", "shipped", "pending"}


def test_demo_store_seed_is_idempotent(client):
    headers = register(client, "demo_idem")
    ident = identity(client, headers)
    db = client.app.state.db

    first = seed_demo_stores(db, ident["tenant_id"], user_id=ident["user_id"])
    second = seed_demo_stores(db, ident["tenant_id"], user_id=ident["user_id"])

    assert first["created"] == len(DEMO_STORES)
    assert second["created"] == 0
    assert second["synced"] == 0
    assert len(client.get("/api/stores", headers=headers).json()["items"]) == len(
        DEMO_STORES
    )


def test_custom_mock_store_keeps_random_mock_data(client):
    """自建店铺不受演示目录影响，仍走原来的随机 Mock（行为不变）。"""
    headers = register(client, "custom_store")
    resp = client.post(
        "/api/stores",
        json={
            "platform": "amazon",
            "marketplace": "US",
            "shop_name": "我的自建店",
            "mode": "mock",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    connection = resp.json()
    assert connection["is_demo"] is False
    assert connection["platform_known"] is True

    products = client.get(
        f"/api/stores/{connection['connection_id']}/products", headers=headers
    ).json()["items"]
    assert products
    assert all(item["name"].startswith("Mock ") for item in products)


def test_demo_catalog_is_deterministic():
    first = demo_catalog("EcoSip Official Store")
    second = demo_catalog("EcoSip Official Store")
    assert first == second, "同一店铺的演示数据必须稳定，否则每次刷新都在变"
    assert demo_catalog("不存在的店") is None


def test_guest_account_gets_demo_stores(client):
    """一键体验账号进来就该看到店铺，而不是空白页。"""
    resp = client.post("/api/auth/demo", json={})
    assert resp.status_code == 200, resp.text

    body = client.get("/api/stores").json()
    assert len(body["items"]) == len(DEMO_STORES)
    assert all(item["is_demo"] is True for item in body["items"])
