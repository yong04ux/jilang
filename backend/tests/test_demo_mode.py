"""演示站机制（M5）：BYOK 428、一键体验、限流、临时账号清理。"""

from __future__ import annotations

import time

import pytest

from crosspilot.demo.demo_data import DEMO_LISTING_REQUEST


def register(client, username="alice") -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture()
def byok_client(client, monkeypatch):
    """打开 BYOK 强制的客户端（conftest 默认把它关掉，便于确定性流程）。"""
    from crosspilot.config import get_settings

    monkeypatch.setenv("CROSSPILOT_REQUIRE_API_KEY", "true")
    get_settings.cache_clear()
    try:
        yield client
    finally:
        get_settings.cache_clear()
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 没有 Key 也能跑完，但必须如实标出「这次是规则引擎」
# ---------------------------------------------------------------------------


def test_agent_run_without_key_runs_on_rules_and_says_so(byok_client):
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    headers = register(byok_client, "byok_agent")
    resp = byok_client.post(
        "/api/agent/runs",
        json={
            "agent_key": "main",
            "product_name": "EcoSip Insulated Water Bottle",
            "platform": "amazon",
            "marketplace": "US",
            "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
            "with_listing": False,
            "data_source": "demo",
            "async_run": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 没有 Key 不再拦：用规则引擎跑，但引擎必须如实回报
    assert body["engine"]["kind"] == "rule"
    assert body["engine"]["label"] == "规则引擎"
    assert body["degraded"] is True
    assert "大模型" in body["degraded_reason"]


def test_listing_async_without_key_runs_on_rules_and_says_so(byok_client):
    headers = register(byok_client, "byok_listing")
    resp = byok_client.post(
        "/api/listings/generate?async_run=true",
        json=DEMO_LISTING_REQUEST,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["engine"]["kind"] == "rule"


def test_analyze_still_works_without_key(byok_client):
    """竞品分析是本地确定性计算，不需要 Key —— 不该被 BYOK 拦掉。"""
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    headers = register(byok_client, "byok_analyze")
    resp = byok_client.post(
        "/api/analyze?async_run=true", json=DEMO_ANALYSIS_REQUEST, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"


def test_health_reports_requires_api_key(byok_client):
    body = byok_client.get("/api/health").json()
    assert body["requires_api_key"] is True
    assert body["worker"]["backend"] in {"thread", "arq"}


# ---------------------------------------------------------------------------
# 一键体验
# ---------------------------------------------------------------------------


def test_demo_endpoint_creates_guest_session(client):
    resp = client.post("/api/auth/demo", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["expires_in_hours"] == 24
    assert body["user"]["is_guest"] is True
    assert body["user"]["guest_expires_at"]
    assert body["username"].startswith("guest_")
    # 会话立刻生效
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["is_guest"] is True


def test_guest_can_run_tasks_in_own_tenant(client):
    client.post("/api/auth/demo", json={})
    tenant = client.get("/api/tenants/current").json()
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["stats"]["total"] == 0
    assert tenant["role"] == "owner"


def test_guest_expiry_is_detected():
    from datetime import datetime, timedelta, timezone

    from crosspilot.demo.demo_mode import is_guest_expired

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert is_guest_expired({"is_guest": True, "guest_expires_at": past}) is True
    assert is_guest_expired({"is_guest": True, "guest_expires_at": future}) is False
    assert is_guest_expired({"is_guest": False, "guest_expires_at": past}) is False
    assert is_guest_expired({"is_guest": True, "guest_expires_at": None}) is True


def test_cleanup_removes_expired_guests(client):
    from datetime import datetime, timedelta, timezone

    from crosspilot.demo.demo_mode import cleanup_guests
    from crosspilot.persistence.db import Database

    client.post("/api/auth/demo", json={})
    db = client.app.state.db
    with db.connect() as connection:
        row = connection.execute(
            "SELECT user_id FROM users WHERE is_guest = 1"
        ).fetchone()
    assert row is not None
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.mark_guest(row["user_id"], past)

    summary = cleanup_guests(db)
    assert summary["guests_removed"] == 1
    assert db.get_user(row["user_id"]) is None


def test_cleanup_keeps_active_guests(client):
    from crosspilot.demo.demo_mode import cleanup_guests

    client.post("/api/auth/demo", json={})
    db = client.app.state.db
    summary = cleanup_guests(db)
    assert summary["guests_removed"] == 0


# ---------------------------------------------------------------------------
# 限流
# ---------------------------------------------------------------------------


def test_rate_limit_blocks_after_threshold(client, monkeypatch):
    from crosspilot.config import get_settings
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    monkeypatch.setenv("CROSSPILOT_RATE_LIMIT_TASKS_PER_HOUR", "2")
    get_settings.cache_clear()
    try:
        headers = register(client, "ratelimit")
        statuses = []
        for _ in range(3):
            resp = client.post(
                "/api/analyze?async_run=true", json=DEMO_ANALYSIS_REQUEST, headers=headers
            )
            statuses.append(resp.status_code)
            time.sleep(0.05)
        assert statuses[:2] == [200, 200], statuses
        assert statuses[2] == 429, statuses
    finally:
        get_settings.cache_clear()


def test_guest_creation_is_rate_limited_per_ip(client, monkeypatch):
    """一键体验不需要任何凭据，公网部署后必须按 IP 限流。

    否则写个循环就能把 users / tenants / store_connections 全部灌满。
    """
    from crosspilot.config import get_settings

    monkeypatch.setenv("CROSSPILOT_RATE_LIMIT_GUEST_PER_HOUR", "2")
    get_settings.cache_clear()
    try:
        statuses = [client.post("/api/auth/demo", json={}).status_code for _ in range(3)]
        assert statuses[:2] == [200, 200], statuses
        assert statuses[2] == 429, statuses
    finally:
        get_settings.cache_clear()


def test_rate_limit_can_be_disabled(client, monkeypatch):
    from crosspilot.config import get_settings
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    monkeypatch.setenv("CROSSPILOT_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("CROSSPILOT_RATE_LIMIT_TASKS_PER_HOUR", "1")
    get_settings.cache_clear()
    try:
        headers = register(client, "ratelimit_off")
        for _ in range(3):
            resp = client.post(
                "/api/analyze?async_run=true", json=DEMO_ANALYSIS_REQUEST, headers=headers
            )
            assert resp.status_code == 200
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 异步竞品分析（M3）
# ---------------------------------------------------------------------------


def test_async_analyze_produces_real_steps(client):
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    headers = register(client, "async_analyze")
    resp = client.post(
        "/api/analyze?async_run=true", json=DEMO_ANALYSIS_REQUEST, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["plan"] == ["analyze", "persist"]

    deadline = time.time() + 10
    detail = {}
    while time.time() < deadline:
        detail = client.get(f"/api/tasks/{body['task_id']}", headers=headers).json()
        if detail["task"]["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    assert detail["task"]["status"] == "succeeded"
    names = [s["name"] for s in detail["steps"]]
    assert names == ["执行分析", "保存报告"]
    assert detail["result"]["report"]["product_name"] == DEMO_ANALYSIS_REQUEST["product_name"]


def test_async_analyze_validates_before_queueing(client):
    headers = register(client, "async_validate")
    resp = client.post("/api/analyze?async_run=true", json={"product_name": ""}, headers=headers)
    assert resp.status_code == 422
