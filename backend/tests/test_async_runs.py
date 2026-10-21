"""异步执行器与取消测试（阶段 C6 / D6）。"""

from __future__ import annotations

import time


from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def agent_payload(**overrides) -> dict:
    payload = {
        "agent_key": "main",
        "product_name": "EcoSip Insulated Water Bottle",
        "platform": "amazon",
        "marketplace": "US",
        "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
        "with_listing": False,
        "data_source": "demo",
        "async_run": True,
    }
    payload.update(overrides)
    return payload


def wait_status(client, task_id: str, headers: dict, statuses: set[str], timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    detail = {}
    while time.time() < deadline:
        detail = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        if detail["task"]["status"] in statuses:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"任务未进入 {statuses}，当前 {detail.get('task', {}).get('status')}")


def test_async_run_completes_and_exposes_result(client):
    headers = register(client, "async_ok")
    resp = client.post("/api/agent/runs", json=agent_payload(), headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["plan"] == ["analyze", "integrity", "summary", "persist"]

    detail = wait_status(client, body["task_id"], headers, {"succeeded", "failed"})
    assert detail["task"]["status"] == "succeeded"
    assert detail["result"]["report"]["product_name"] == "EcoSip Insulated Water Bottle"
    assert detail["result"]["summary"]["points"]
    assert detail["result"]["checks"]["metrics"]["competitors"] >= 2
    names = [s["name"] for s in detail["steps"]]
    assert names == [
        "生成执行计划",
        "竞品分析",
        "数据完整性检查",
        "生成市场机会总结",
        "保存报告与任务记录",
    ]


def test_cancel_running_task_takes_effect_at_checkpoint(client, monkeypatch):
    headers = register(client, "async_cancel")
    from crosspilot.agent import tools

    original = tools.run_competitor_analysis

    def slow_analysis(*args, **kwargs):
        time.sleep(1.0)
        return original(*args, **kwargs)

    monkeypatch.setattr("crosspilot.agent.tools.run_competitor_analysis", slow_analysis)

    resp = client.post(
        "/api/agent/runs",
        json=agent_payload(conversation_id=None),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]

    # 等竞品分析节点真正开始，确保取消发生在执行中而不是排队阶段
    deadline = time.time() + 5
    while time.time() < deadline:
        detail = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        if any(step["name"] == "竞品分析" and step["status"] == "running" for step in detail["steps"]):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("竞品分析步骤未开始")

    started = time.time()
    cancel = client.post(f"/api/tasks/{task_id}/cancel", json={}, headers=headers)
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["detail"].startswith("已请求取消")

    detail = wait_status(client, task_id, headers, {"cancelled", "failed", "succeeded"}, timeout=5)
    elapsed = time.time() - started
    assert detail["task"]["status"] == "cancelled"
    assert elapsed < 3.0, f"取消耗时 {elapsed:.2f}s，超过 3s 验收线"
    assert any(step["name"] == "任务已取消" for step in detail["steps"])

    # 取消后不再产生报告或草稿
    assert detail["result"]["report"] is None
    reports = client.get("/api/reports", headers=headers).json()["items"]
    assert reports == []


def test_cancelled_task_cannot_be_cancelled_again(client):
    headers = register(client, "async_cancel_twice")
    resp = client.post("/api/agent/runs", json=agent_payload(), headers=headers)
    task_id = resp.json()["task_id"]
    wait_status(client, task_id, headers, {"succeeded"})
    cancel = client.post(f"/api/tasks/{task_id}/cancel", json={}, headers=headers)
    assert cancel.status_code == 409


def test_async_run_requires_write_role(client):
    owner = register(client, "async_owner")
    viewer = register(client, "async_viewer")
    tenant_id = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    client.post(
        "/api/tenants/members",
        json={"username": "async_viewer", "role": "viewer"},
        headers=owner,
    )
    resp = client.post(
        "/api/agent/runs",
        json=agent_payload(),
        headers={**viewer, "X-Tenant-Id": tenant_id},
    )
    assert resp.status_code == 403
