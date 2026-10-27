"""异步执行器与取消测试（阶段 C6 / D6）。"""

from __future__ import annotations

import time


from crosspilot.agent.planner import plan_for
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
    assert body["plan"] == plan_for(False)

    detail = wait_status(client, body["task_id"], headers, {"succeeded", "failed"})
    assert detail["task"]["status"] == "succeeded"
    assert detail["result"]["report"]["product_name"] == "EcoSip Insulated Water Bottle"
    assert detail["result"]["summary"]["points"]
    assert detail["result"]["checks"]["metrics"]["competitors"] >= 2
    nodes = [s["node"] for s in detail["steps"]]
    assert nodes[0] == "validate" and nodes[1] == "dispatch"
    assert nodes[-1] == "finalize"


def test_cancel_running_task_takes_effect_at_checkpoint(client, monkeypatch):
    headers = register(client, "async_cancel")
    from crosspilot.engine import analysis as engine_analysis

    original = engine_analysis.run_analysis

    def slow_analysis(*args, **kwargs):
        time.sleep(1.0)
        return original(*args, **kwargs)

    # 打桩在引擎层：竞品子图通过 engine.analysis.run_analysis 做统计
    monkeypatch.setattr("crosspilot.engine.analysis.run_analysis", slow_analysis)

    resp = client.post(
        "/api/agent/runs",
        json=agent_payload(conversation_id=None),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]

    # 等统计节点真正开始，确保取消发生在执行中而不是排队阶段
    deadline = time.time() + 5
    while time.time() < deadline:
        detail = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        if any(
            step["node"] == "analyze_market" and step["status"] == "running"
            for step in detail["steps"]
        ):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("竞品统计步骤未开始")

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


def test_force_sync_tasks_runs_inline_for_serverless(client, monkeypatch):
    """``CROSSPILOT_FORCE_SYNC_TASKS``：Serverless 部署必须走同步。

    Vercel 这类平台在响应返回后冻结实例，进程内线程队列的后台任务会就地停摆，
    任务永远停在 queued。打开开关后即使前端传 ``async_run=true``，
    也要在本次请求内跑完并返回结果。
    """
    from crosspilot.config import get_settings

    monkeypatch.setenv("CROSSPILOT_FORCE_SYNC_TASKS", "true")
    get_settings.cache_clear()
    try:
        headers = register(client, "force_sync")
        resp = client.post(
            "/api/analyze?async_run=true",
            json=DEMO_ANALYSIS_REQUEST,
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 同步路径：直接带回报告，而不是只给一个 task_id
        assert "report" in body and body["report"], body
        assert body.get("async") is not True
        assert body.get("status") != "queued"

        # 任务照样落库，而且是终态，不是排队的空壳
        detail = client.get(f"/api/tasks/{body['task_id']}", headers=headers).json()
        assert detail["task"]["status"] == "succeeded"
    finally:
        get_settings.cache_clear()
