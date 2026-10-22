"""成本与利润测算接口：即时计算 + 方案保存/列表/删除。

关注两件事：
1. 计算接口**不写库**（它是高频交互，不能污染数据）；
2. 方案是按租户隔离的——`business_reports` 是新的公共表，隔离写错就是数据越界。
"""

from __future__ import annotations

import pytest

PAYLOAD = {
    "product_name": "折叠收纳箱",
    "marketplace": "US",
    "currency": "USD",
    "fulfillment": "fba",
    "selling_price": 30,
    "purchase_cost": 8,
    "shipping_cost": 2,
    "fulfillment_fee": 4,
    "ad_cost_per_order": 3,
    "commission_rate": 0.15,
    "return_rate": 0.0,
    "fixed_cost": 1000,
    "target_margin": 0.2,
}


def test_presets_expose_commission_reference(auth_client):
    response = auth_client.get("/api/profit/presets")

    assert response.status_code == 200
    body = response.json()
    assert body["commission_presets"]["US"] == 0.15
    # 必须写明这是参考值，不能让人当成真实费率
    assert "参考值" in body["note"]


def test_calc_returns_estimate_without_touching_storage(auth_client):
    response = auth_client.post("/api/profit/calc", json=PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["is_estimate"] is True
    assert body["total_cost"] == pytest.approx(21.5)
    assert body["unit_profit"] == pytest.approx(8.5)
    assert body["break_even_price"] == pytest.approx(20.0)
    assert len(body["sensitivity"]) == 8
    # 计算不应落库
    assert auth_client.get("/api/profit/plans").json()["total"] == 0


def test_calc_rejects_impossible_rate_combination(auth_client):
    response = auth_client.post(
        "/api/profit/calc", json={**PAYLOAD, "commission_rate": 0.6, "target_margin": 0.5}
    )

    assert response.status_code == 422


def test_save_plan_then_read_it_back(auth_client):
    saved = auth_client.post(
        "/api/profit/plans", params={"title": "收纳箱 · 美国站"}, json=PAYLOAD
    )
    assert saved.status_code == 200, saved.text
    report_id = saved.json()["report_id"]

    listing = auth_client.get("/api/profit/plans").json()
    assert listing["total"] == 1
    assert listing["items"][0]["title"] == "收纳箱 · 美国站"
    # 列表只带摘要，不把整份结果塞进去
    assert "payload" not in listing["items"][0]
    assert listing["items"][0]["summary"]["unit_profit"] == pytest.approx(8.5)

    detail = auth_client.get(f"/api/profit/plans/{report_id}").json()
    assert detail["input"]["selling_price"] == 30
    assert detail["payload"]["margin"] == pytest.approx(0.2833, abs=1e-4)


def test_delete_plan_removes_it(auth_client):
    report_id = auth_client.post("/api/profit/plans", json=PAYLOAD).json()["report_id"]

    assert auth_client.delete(f"/api/profit/plans/{report_id}").status_code == 200
    assert auth_client.get(f"/api/profit/plans/{report_id}").status_code == 404


def test_unknown_plan_id_is_404_not_403(auth_client):
    assert auth_client.get("/api/profit/plans/does-not-exist").status_code == 404


def test_plans_require_login(client):
    assert client.get("/api/profit/plans").status_code == 401
