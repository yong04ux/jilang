"""会话与消息测试（阶段 C4 / D7）。"""

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
    }
    payload.update(overrides)
    return payload


def wait_for_task(client, task_id: str, headers: dict, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        if detail["task"]["status"] in {"succeeded", "failed", "cancelled"}:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"任务未在 {timeout}s 内结束：{detail['task']['status']}")


def test_create_and_list_conversations(client):
    headers = register(client, "conv_owner")
    created = client.post("/api/conversations", json={}, headers=headers)
    assert created.status_code == 200, created.text
    conversation = created.json()["conversation"]
    assert conversation["title"] == "新会话"

    items = client.get("/api/conversations", headers=headers).json()["items"]
    assert [item["conversation_id"] for item in items] == [conversation["conversation_id"]]
    assert items[0]["message_count"] == 0


def test_agent_run_appends_messages_and_autotitles(client):
    headers = register(client, "conv_agent")
    conversation = client.post(
        "/api/conversations", json={}, headers=headers
    ).json()["conversation"]

    run = client.post(
        "/api/agent/runs",
        json=agent_payload(
            conversation_id=conversation["conversation_id"],
            goal="分析 EcoSip 保温杯的竞品",
        ),
        headers=headers,
    )
    assert run.status_code == 200, run.text
    assert run.json()["conversation_id"] == conversation["conversation_id"]

    detail = client.get(
        f"/api/conversations/{conversation['conversation_id']}", headers=headers
    ).json()
    messages = detail["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "分析 EcoSip 保温杯的竞品"
    assert messages[1]["content_type"] == "result_ref"
    assert messages[1]["task_id"] == run.json()["task_id"]
    assert detail["conversation"]["title"] != "新会话"
    assert len(detail["conversation"]["title"]) <= 29


def test_agent_run_without_conversation_creates_one(client):
    headers = register(client, "conv_auto")
    run = client.post("/api/agent/runs", json=agent_payload(), headers=headers)
    assert run.status_code == 200, run.text
    conversation_id = run.json()["conversation_id"]
    assert conversation_id

    items = client.get("/api/conversations", headers=headers).json()["items"]
    assert conversation_id in {item["conversation_id"] for item in items}


def test_async_run_writes_messages_when_done(client):
    headers = register(client, "conv_async")
    run = client.post(
        "/api/agent/runs",
        json=agent_payload(async_run=True),
        headers=headers,
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "queued"

    wait_for_task(client, body["task_id"], headers)
    detail = client.get(
        f"/api/conversations/{body['conversation_id']}", headers=headers
    ).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


def test_conversation_is_private_even_inside_tenant(client):
    owner = register(client, "conv_team_owner")
    member = register(client, "conv_team_member")
    tenant_id = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    client.post(
        "/api/tenants/members",
        json={"username": "conv_team_member", "role": "editor"},
        headers=owner,
    )
    member_headers = {**member, "X-Tenant-Id": tenant_id}

    conversation = client.post(
        "/api/conversations", json={}, headers=member_headers
    ).json()["conversation"]
    # 同租户的另一成员看不到别人的聊天记录
    assert (
        client.get(f"/api/conversations/{conversation['conversation_id']}", headers={**owner, "X-Tenant-Id": tenant_id}).status_code
        == 404
    )


def test_conversation_cross_tenant_404(client):
    alice = register(client, "conv_alice")
    bob = register(client, "conv_bob")
    conversation = client.post(
        "/api/conversations", json={}, headers=alice
    ).json()["conversation"]
    assert (
        client.get(
            f"/api/conversations/{conversation['conversation_id']}", headers=bob
        ).status_code
        == 404
    )


def test_viewer_cannot_create_conversation(client):
    owner = register(client, "conv_view_owner")
    viewer = register(client, "conv_viewer")
    tenant_id = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    client.post(
        "/api/tenants/members",
        json={"username": "conv_viewer", "role": "viewer"},
        headers=owner,
    )
    resp = client.post(
        "/api/conversations",
        json={},
        headers={**viewer, "X-Tenant-Id": tenant_id},
    )
    assert resp.status_code == 403


def test_archive_conversation_hides_it_from_list(client):
    headers = register(client, "conv_archive")
    conversation = client.post(
        "/api/conversations", json={}, headers=headers
    ).json()["conversation"]
    assert (
        client.delete(
            f"/api/conversations/{conversation['conversation_id']}", headers=headers
        ).status_code
        == 200
    )
    assert client.get("/api/conversations", headers=headers).json()["items"] == []
    assert (
        client.get(
            f"/api/conversations/{conversation['conversation_id']}", headers=headers
        ).status_code
        == 404
    )
