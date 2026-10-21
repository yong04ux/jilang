"""任务重试：retry_of 血缘 + 异步整任务重跑。"""

from __future__ import annotations

import time
import uuid

from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST


def register(client, username: str) -> dict[str, str]:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def current_identity(client, headers: dict[str, str]) -> dict[str, str]:
    resp = client.get("/api/tenants/current", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {"user_id": body["user_id"], "tenant_id": body["tenant_id"]}


def create_failed_agent_task(
    client, user_id: str, tenant_id: str, with_listing: bool = False
) -> str:
    """直接落一条 failed 的 Agent 任务（模拟执行中途失败），用于验证重试。"""
    db = client.app.state.db
    task_id = uuid.uuid4().hex
    db.create_task(
        {
            "task_id": task_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "origin": "chat",
            "type": "agent_workflow",
            "title": "失败任务",
            "status": "failed",
            "input": {
                "product_name": "EcoSip Insulated Water Bottle",
                "platform": "amazon",
                "marketplace": "US",
                "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
                "with_listing": with_listing,
                "data_source": "demo",
            },
            "output": None,
            "error_code": "agent_step_failed",
            "error_message": "boom",
            "result_ref": None,
            "trace_id": uuid.uuid4().hex[:12],
            "created_at": "2026-10-21T00:00:00+00:00",
            "started_at": None,
            "finished_at": "2026-10-21T00:00:01+00:00",
            "degraded": 0,
        }
    )
    return task_id


RESUMABLE_NODES = ("plan", "analyze", "integrity", "summary")


def run_reference_task(client, headers: dict[str, str]) -> str:
    """跑一个完整成功的任务，作为"上次跑到一半"的真实步骤来源。"""
    resp = client.post(
        "/api/agent/runs",
        json={
            "agent_key": "main",
            "product_name": "EcoSip Insulated Water Bottle",
            "platform": "amazon",
            "marketplace": "US",
            "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
            "with_listing": True,
            "data_source": "demo",
            "async_run": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]
    wait_status(client, task_id, headers, {"succeeded", "failed"})
    return task_id


def seed_partial_steps(
    client, task_id: str, user_id: str, tenant_id: str, outputs: dict
) -> None:
    """给失败任务补上「已成功的 4 个步骤」，模拟在 listing 一步挂掉。"""
    db = client.app.state.db
    for seq, node in enumerate(RESUMABLE_NODES, start=1):
        db.add_task_step(
            {
                "step_id": uuid.uuid4().hex,
                "task_id": task_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "seq": seq,
                "name": node,
                "node": node,
                "status": "succeeded",
                "detail": "历史成功步骤",
                "started_at": "2026-10-21T00:00:00+00:00",
                "finished_at": "2026-10-21T00:00:01+00:00",
                "duration_ms": 7,
                "output": outputs[node],
            }
        )


def wait_status(
    client, task_id: str, headers: dict[str, str], statuses: set[str], timeout: float = 10.0
) -> dict:
    deadline = time.time() + timeout
    detail: dict = {}
    while time.time() < deadline:
        detail = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        if detail["task"]["status"] in statuses:
            return detail
        time.sleep(0.05)
    raise AssertionError(
        f"任务未进入 {statuses}，当前 {detail.get('task', {}).get('status')}"
    )


def test_retry_failed_agent_task_runs_and_links(client):
    headers = register(client, "retry_ok")
    ident = current_identity(client, headers)
    failed_id = create_failed_agent_task(client, ident["user_id"], ident["tenant_id"])

    resp = client.post(f"/api/tasks/{failed_id}/retry", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["retry_of"] == failed_id
    assert body["status"] == "queued"
    # 原任务没有任何成功步骤，无可复用断点
    assert body["resumed_steps"] == []

    detail = wait_status(client, body["task_id"], headers, {"succeeded", "failed"})
    assert detail["task"]["status"] == "succeeded"
    assert detail["task"]["retry_of"] == failed_id
    assert detail["task"]["title"].startswith("重试：")


def test_retry_rejects_succeeded_task(client):
    headers = register(client, "retry_reject")
    resp = client.post(
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
    task_id = resp.json()["task_id"]
    wait_status(client, task_id, headers, {"succeeded", "failed"})

    retry = client.post(f"/api/tasks/{task_id}/retry", headers=headers)
    assert retry.status_code == 409, retry.text


def test_retry_cross_tenant_is_404(client):
    headers_a = register(client, "retry_owner")
    ident_a = current_identity(client, headers_a)
    failed_id = create_failed_agent_task(client, ident_a["user_id"], ident_a["tenant_id"])

    headers_b = register(client, "retry_other")
    resp = client.post(f"/api/tasks/{failed_id}/retry", headers=headers_b)
    assert resp.status_code == 404, resp.text


def test_retry_resumes_from_last_successful_step(client):
    """默认续跑：已成功的 4 步复用输出，只从失败点继续。"""
    headers = register(client, "retry_resume")
    ident = current_identity(client, headers)
    db = client.app.state.db

    src_id = run_reference_task(client, headers)
    outputs = db.step_outputs(src_id, ident["tenant_id"])
    assert set(RESUMABLE_NODES) <= set(outputs), outputs.keys()

    failed_id = create_failed_agent_task(
        client, ident["user_id"], ident["tenant_id"], with_listing=True
    )
    seed_partial_steps(client, failed_id, ident["user_id"], ident["tenant_id"], outputs)

    resp = client.post(f"/api/tasks/{failed_id}/retry", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resumed_steps"] == sorted(RESUMABLE_NODES)

    detail = wait_status(client, body["task_id"], headers, {"succeeded", "failed"})
    assert detail["task"]["status"] == "succeeded"

    reused = {
        step["node"]: step
        for step in detail["steps"]
        if step.get("node") in RESUMABLE_NODES
    }
    assert set(reused) == set(RESUMABLE_NODES)
    for node in RESUMABLE_NODES:
        assert reused[node]["duration_ms"] == 0, reused[node]
        assert "未重跑" in (reused[node]["detail"] or ""), reused[node]


def test_retry_without_resume_reruns_all_steps(client):
    """``?resume=false``：不复用断点，整任务从头重跑。"""
    headers = register(client, "retry_full")
    ident = current_identity(client, headers)
    db = client.app.state.db

    src_id = run_reference_task(client, headers)
    outputs = db.step_outputs(src_id, ident["tenant_id"])

    failed_id = create_failed_agent_task(
        client, ident["user_id"], ident["tenant_id"], with_listing=True
    )
    seed_partial_steps(client, failed_id, ident["user_id"], ident["tenant_id"], outputs)

    resp = client.post(f"/api/tasks/{failed_id}/retry?resume=false", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resumed_steps"] == []

    detail = wait_status(client, body["task_id"], headers, {"succeeded", "failed"})
    assert detail["task"]["status"] == "succeeded"
    for step in detail["steps"]:
        if step.get("node") in RESUMABLE_NODES:
            assert "未重跑" not in (step["detail"] or ""), step
