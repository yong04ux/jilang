"""审计日志测试（阶段 C7）。"""

from __future__ import annotations

from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def actions(client, headers: dict) -> list[str]:
    items = client.get("/api/audit?limit=200", headers=headers).json()["items"]
    return [item["action"] for item in items]


def test_register_and_login_are_audited(client):
    headers = register(client, "audit_login")
    client.post(
        "/api/auth/login",
        json={"username": "audit_login", "password": "password123"},
    )
    recorded = actions(client, headers)
    assert "auth.register" in recorded
    assert "auth.login" in recorded


def test_model_settings_audit_is_scrubbed(client):
    headers = register(client, "audit_model")
    secret = "sk-test-should-never-appear-12345"
    resp = client.put(
        "/api/settings/model",
        json={
            "provider": "deepseek",
            "model": "deepseek-flash",
            "api_key": secret,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    items = client.get("/api/audit?action=model.update", headers=headers).json()["items"]
    assert items
    detail = items[0]["detail"]
    assert detail["api_key"] == "***"
    assert secret not in str(items[0])
    # 审计接口本身也不能把 Key 带出来
    assert secret not in client.get("/api/audit?limit=200", headers=headers).text


def test_task_cancel_is_audited(client, monkeypatch):
    headers = register(client, "audit_cancel")
    # 让任务停在 queued，便于立即取消
    monkeypatch.setattr(
        client.app.state.task_queue, "submit", lambda task_id, job: None
    )
    run = client.post(
        "/api/agent/runs",
        json={
            "product_name": "Audit Bottle",
            "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
            "with_listing": False,
            "data_source": "demo",
            "async_run": True,
        },
        headers=headers,
    ).json()
    cancel = client.post(f"/api/tasks/{run['task_id']}/cancel", json={}, headers=headers)
    assert cancel.status_code == 200, cancel.text
    assert "task.cancel" in actions(client, headers)


def test_viewer_cannot_read_audit_logs(client):
    owner = register(client, "audit_owner")
    viewer = register(client, "audit_viewer")
    tenant_id = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    client.post(
        "/api/tenants/members",
        json={"username": "audit_viewer", "role": "viewer"},
        headers=owner,
    )
    resp = client.get("/api/audit", headers={**viewer, "X-Tenant-Id": tenant_id})
    assert resp.status_code == 403


def test_audit_is_tenant_scoped(client):
    alice = register(client, "audit_alice")
    bob = register(client, "audit_bob")
    client.post(
        "/api/settings/model",
        json={"provider": "rule", "model": "rule"},
        headers=alice,
    )
    bob_actions = actions(client, bob)
    # bob 看不到 alice 的模型变更
    assert "model.update" not in bob_actions
    assert "auth.register" in bob_actions
