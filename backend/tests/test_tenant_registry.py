"""租户自定义 Agent / Skill 注册表写入。"""

from __future__ import annotations


def register(client, username: str) -> dict[str, str]:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def agent_body(**overrides) -> dict:
    body = {
        "key": "my_researcher",
        "name": "我的研究 Agent",
        "summary": "自定义研究代理",
        "description": "用于测试",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object"},
        "skill_keys": ["competitor_analysis"],
        "tool_keys": ["run_competitor_analysis"],
        "status": "beta",
    }
    body.update(overrides)
    return body


def test_create_list_get_custom_agent(client):
    headers = register(client, "reg_owner")
    resp = client.post("/api/agents", json=agent_body(), headers=headers)
    assert resp.status_code == 201, resp.text
    item = resp.json()
    assert item["agent_key"] == "my_researcher"
    assert item["version"] == "1.0.0"

    items = client.get("/api/agents", headers=headers).json()["items"]
    assert any(i["agent_key"] == "my_researcher" for i in items)

    got = client.get("/api/agents/my_researcher", headers=headers).json()
    assert got["name"] == "我的研究 Agent"
    assert got["skill_keys"] == ["competitor_analysis"]


def test_cannot_override_builtin_agent(client):
    headers = register(client, "reg_builtin")
    resp = client.post("/api/agents", json=agent_body(key="main"), headers=headers)
    assert resp.status_code == 409, resp.text


def test_update_bumps_version_and_disable(client):
    headers = register(client, "reg_update")
    created = client.post("/api/agents", json=agent_body(key="tmp_agent"), headers=headers)
    assert created.status_code == 201, created.text

    resp = client.put("/api/agents/tmp_agent", json={"name": "改名"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "改名"
    assert body["version"] == "1.0.1"

    resp = client.delete("/api/agents/tmp_agent", headers=headers)
    assert resp.status_code == 200, resp.text
    got = client.get("/api/agents/tmp_agent", headers=headers).json()
    assert got["status"] == "disabled"


def test_cannot_modify_builtin(client):
    headers = register(client, "reg_mod_builtin")
    assert (
        client.put("/api/agents/main", json={"name": "hacked"}, headers=headers).status_code
        == 403
    )
    assert client.delete("/api/agents/main", headers=headers).status_code == 403
    assert (
        client.put(
            "/api/skills/competitor_analysis", json={"name": "x"}, headers=headers
        ).status_code
        == 403
    )


def test_cross_tenant_isolation(client):
    headers_a = register(client, "reg_a")
    created = client.post("/api/agents", json=agent_body(key="a_only"), headers=headers_a)
    assert created.status_code == 201, created.text

    headers_b = register(client, "reg_b")
    items_b = client.get("/api/agents", headers=headers_b).json()["items"]
    assert not any(i["agent_key"] == "a_only" for i in items_b)
    assert (
        client.put("/api/agents/a_only", json={"name": "x"}, headers=headers_b).status_code
        == 404
    )


def test_invalid_payload(client):
    headers = register(client, "reg_invalid")
    assert (
        client.post("/api/agents", json=agent_body(key="Bad Key"), headers=headers).status_code
        == 400
    )
    assert (
        client.post("/api/agents", json=agent_body(key="ok_key", name=""), headers=headers).status_code
        == 400
    )
    assert (
        client.post(
            "/api/agents", json=agent_body(key="ok_key2", status="bogus"), headers=headers
        ).status_code
        == 400
    )


def test_skill_create_update_disable(client):
    headers = register(client, "reg_skill")
    resp = client.post(
        "/api/skills",
        json={"key": "my_skill", "name": "自定义技能", "summary": "s"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["version"] == "1.0.0"

    resp = client.put("/api/skills/my_skill", json={"summary": "updated"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["summary"] == "updated"
    assert resp.json()["version"] == "1.0.1"

    assert client.delete("/api/skills/my_skill", headers=headers).status_code == 200
    assert client.get("/api/skills/my_skill", headers=headers).json()["status"] == "disabled"
