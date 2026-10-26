"""F-04：统一执行入口 ``POST /api/skills/{key}/run`` 的契约。

判定顺序是这一组测试的重点（登录 → 角色 → 技能存在 → 参数 → 依赖 → 限流 → 执行）：
顺序错了不会报错，只会让用户多撞几次墙，所以必须钉住。
"""

from __future__ import annotations

import base64
import time

import pytest

from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST, DEMO_LISTING_REQUEST
from crosspilot.skills import SKILL_REGISTRY


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def run_skill(client, headers: dict, key: str, payload: dict, query: str = ""):
    return client.post(f"/api/skills/{key}/run{query}", json=payload, headers=headers)


def wait_status(client, task_id: str, headers: dict, statuses: set[str], timeout: float = 15.0):
    deadline = time.time() + timeout
    detail = {}
    while time.time() < deadline:
        detail = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        if detail["task"]["status"] in statuses:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"任务未进入 {statuses}，当前 {detail.get('task', {}).get('status')}")


@pytest.fixture()
def byok_client(client, monkeypatch):
    """打开 BYOK 强制的客户端（conftest 默认关掉它，便于确定性流程）。"""
    from crosspilot.config import get_settings

    monkeypatch.setenv("CROSSPILOT_REQUIRE_API_KEY", "true")
    get_settings.cache_clear()
    try:
        yield client
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 同步执行
# ---------------------------------------------------------------------------


def test_sync_run_returns_output_and_persists_report(client):
    headers = register(client, "skill_run_sync")
    resp = run_skill(client, headers, "competitor_analysis", DEMO_ANALYSIS_REQUEST)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] == "succeeded"
    assert body["renderer"] == "report"
    assert body["result_ref"]
    assert body["output"]["product_name"] == DEMO_ANALYSIS_REQUEST["product_name"]

    # 真的落库了：报告能按 id 取回
    report = client.get(f"/api/reports/{body['result_ref']}", headers=headers)
    assert report.status_code == 200
    assert report.json()["product_name"] == DEMO_ANALYSIS_REQUEST["product_name"]

    # 任务也留痕，且步骤名是中文
    detail = client.get(f"/api/tasks/{body['task_id']}", headers=headers).json()
    assert detail["task"]["type"] == "skill_run"
    assert [s["name"] for s in detail["steps"]] == ["竞品分析"]


def test_sync_run_exposes_is_demo(client):
    headers = register(client, "skill_run_demo")
    body = run_skill(client, headers, "competitor_analysis", DEMO_ANALYSIS_REQUEST).json()
    assert body["is_demo"] is True
    detail = client.get(f"/api/tasks/{body['task_id']}", headers=headers).json()
    assert detail["result"]["skill"]["is_demo"] is True


def test_market_summary_runs_from_a_report_id(client):
    headers = register(client, "skill_run_summary")
    report = run_skill(client, headers, "competitor_analysis", DEMO_ANALYSIS_REQUEST).json()

    resp = run_skill(
        client, headers, "market_summary", {"report_id": report["result_ref"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["output"]["headline"]
    assert resp.json()["output"]["points"]


def test_profit_calc_runs_without_any_key(client):
    headers = register(client, "skill_run_profit")
    resp = run_skill(
        client,
        headers,
        "profit_calc",
        {"selling_price": 22.9, "purchase_cost": 6.4, "commission_rate": 0.15},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["renderer"] == "chart"


# ---------------------------------------------------------------------------
# 参数与依赖
# ---------------------------------------------------------------------------


def test_invalid_params_point_at_the_field(client):
    headers = register(client, "skill_run_422")
    resp = run_skill(
        client,
        headers,
        "competitor_analysis",
        {**DEMO_ANALYSIS_REQUEST, "product_name": ""},
    )
    assert resp.status_code == 422, resp.text
    errors = resp.json()["detail"]["errors"]
    assert any("商品名称" in e["field"] for e in errors)


def test_missing_source_is_rejected_with_a_readable_message(client):
    headers = register(client, "skill_run_422b")
    resp = run_skill(
        client, headers, "competitor_analysis", {"product_name": "杯子", "competitors": []}
    )
    assert resp.status_code == 422
    message = resp.json()["detail"]["errors"][0]["message"]
    assert "竞品" in message


def test_unknown_skill_is_404(client):
    headers = register(client, "skill_run_404")
    resp = run_skill(client, headers, "not_a_skill", {})
    assert resp.status_code == 404
    # 不把技能 key 回显给用户
    assert "not_a_skill" not in resp.text


def test_expected_422_before_missing_key(byok_client):
    """参数错必须先于「没配 Key」暴露，否则用户配完 Key 还会再撞一次。"""
    headers = register(byok_client, "skill_run_order")
    resp = run_skill(
        byok_client, headers, "listing_generation", {"product": {"name": ""}}
    )
    assert resp.status_code == 422, resp.text


def test_llm_skill_falls_back_to_rules_and_reports_engine(byok_client):
    """没有 Key 也要能跑，但返回里必须写清用的是规则引擎。"""
    headers = register(byok_client, "skill_run_engine")

    listing = run_skill(byok_client, headers, "listing_generation", DEMO_LISTING_REQUEST)
    assert listing.status_code == 200, listing.text
    assert listing.json()["engine"]["kind"] == "rule"

    analysis = run_skill(byok_client, headers, "competitor_analysis", DEMO_ANALYSIS_REQUEST)
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["engine"]["kind"] == "rule"


def test_low_role_user_cannot_run_skills(client):
    """viewer 不能跑技能：会写库、会消耗额度。"""
    owner = register(client, "skill_run_owner")
    viewer = register(client, "skill_viewer")
    owner_tenant = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    added = client.post(
        "/api/tenants/members",
        json={"username": "skill_viewer", "role": "viewer"},
        headers=owner,
    )
    assert added.status_code == 200, added.text

    # 注册时会为每个账号建独立租户（本人是 owner），
    # 要验证「在别人租户里只是 viewer」，必须显式带上目标租户。
    resp = run_skill(
        client,
        {**viewer, "X-Tenant-Id": owner_tenant},
        "competitor_analysis",
        DEMO_ANALYSIS_REQUEST,
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 异步执行
# ---------------------------------------------------------------------------


def test_async_run_queues_and_exposes_result(client):
    headers = register(client, "skill_run_async")
    resp = run_skill(
        client, headers, "competitor_analysis", DEMO_ANALYSIS_REQUEST, "?async_run=true"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["plan"] == ["竞品分析"]

    detail = wait_status(client, body["task_id"], headers, {"succeeded", "failed"})
    assert detail["task"]["status"] == "succeeded"
    # 大产出不进任务载荷，完整报告走 result.report
    assert detail["result"]["skill"]["renderer"] == "report"
    assert detail["result"]["skill"]["output"] is None
    assert detail["result"]["report"]["product_name"] == DEMO_ANALYSIS_REQUEST["product_name"]


# ---------------------------------------------------------------------------
# 数据校验
# ---------------------------------------------------------------------------


def _csv_payload(content: str) -> dict:
    return {
        "filename": "rows.csv",
        "content_base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }


def test_data_validation_returns_row_errors_as_a_result(client):
    """脏数据是常态：行级错误是正常结果，不是 500，也不是 422。"""
    headers = register(client, "skill_run_validate")
    resp = run_skill(
        client,
        headers,
        "data_validation",
        _csv_payload("name,price\nDemo A,19.99\n,12.5\n"),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["output"]["total_rows"] >= 1
    assert body["output"]["ok"] is False
    assert body["output"]["errors"]
    # 完整结果不外泄，但批次已落库，可被竞品分析复用
    assert "_batch" not in body["output"]
    assert body["output"]["batch_id"]


def test_data_validation_rejects_unreadable_content(client):
    headers = register(client, "skill_run_validate_bad")
    resp = run_skill(
        client, headers, "data_validation", {"filename": "x.csv", "content_base64": "%%%"}
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 隔离与审计
# ---------------------------------------------------------------------------


def test_cross_tenant_report_is_404(client):
    owner = register(client, "skill_iso_a")
    report = run_skill(client, owner, "competitor_analysis", DEMO_ANALYSIS_REQUEST).json()

    other = register(client, "skill_iso_b")
    resp = run_skill(client, other, "market_summary", {"report_id": report["result_ref"]})
    assert resp.status_code == 404, resp.text


def test_cross_tenant_task_is_404(client):
    owner = register(client, "skill_iso_task_a")
    body = run_skill(
        client, owner, "competitor_analysis", DEMO_ANALYSIS_REQUEST, "?async_run=true"
    ).json()
    wait_status(client, body["task_id"], owner, {"succeeded", "failed"})

    other = register(client, "skill_iso_task_b")
    assert client.get(f"/api/tasks/{body['task_id']}", headers=other).status_code == 404


def test_run_is_audited(client):
    headers = register(client, "skill_audit")
    run_skill(client, headers, "competitor_analysis", DEMO_ANALYSIS_REQUEST)
    items = client.get("/api/audit?action=skill.run", headers=headers).json()["items"]
    assert items
    assert items[0]["action"] == "skill.run"


def test_registry_matches_api_surface(client):
    """接口暴露的技能必须与注册表一致：多了就是空壳，少了就是藏了能力。"""
    headers = register(client, "skill_surface")
    keys = {item["skill_key"] for item in client.get("/api/skills", headers=headers).json()["items"]}
    assert keys == set(SKILL_REGISTRY)
