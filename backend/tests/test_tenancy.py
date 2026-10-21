"""多租户隔离测试。

覆盖：
1. 注册即获得个人租户，且是 owner；
2. 客户端传 X-Tenant-Id 必须校验成员关系（伪造 → 403）；
3. 跨租户读/写/删全部拒绝，且不泄漏资源是否存在；
4. 角色权限（viewer 只读）；
5. 成员邀请。
"""

from __future__ import annotations


from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST


def register(client, username: str) -> tuple[dict, dict]:
    resp = client.post("/api/auth/register", json={"username": username, "password": "password123"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["user"], {"Authorization": f"Bearer {body['token']}"}


def current_tenant(client, headers) -> dict:
    resp = client.get("/api/tenants/current", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 租户创建与解析
# ---------------------------------------------------------------------------


def test_register_creates_personal_tenant(client):
    user, headers = register(client, "tenant_alice")
    ctx = current_tenant(client, headers)
    assert ctx["tenant_id"]
    assert ctx["role"] == "owner"
    assert ctx["user_id"] == user["user_id"]
    assert "个人空间" in ctx["name"]

    memberships = client.get("/api/tenants", headers=headers).json()["items"]
    assert len(memberships) == 1
    assert memberships[0]["role"] == "owner"


def test_each_user_gets_isolated_tenant(client):
    _, alice = register(client, "tenant_a1")
    _, bob = register(client, "tenant_b1")
    assert current_tenant(client, alice)["tenant_id"] != current_tenant(client, bob)["tenant_id"]


def test_client_cannot_switch_to_foreign_tenant(client):
    _, alice = register(client, "tenant_a2")
    _, bob = register(client, "tenant_b2")
    bob_tenant = current_tenant(client, bob)["tenant_id"]

    resp = client.get("/api/tenants/current", headers={**alice, "X-Tenant-Id": bob_tenant})
    assert resp.status_code == 403
    assert "无权访问" in resp.json()["detail"]

    # 不存在的租户同样返回 403，不暴露是否存在
    fake = client.get("/api/tenants/current", headers={**alice, "X-Tenant-Id": "does-not-exist"})
    assert fake.status_code == 403


def test_can_switch_to_joined_tenant(client):
    _, owner = register(client, "tenant_owner")
    _, member = register(client, "tenant_member")
    owner_tenant = current_tenant(client, owner)["tenant_id"]

    added = client.post(
        "/api/tenants/members",
        json={"username": "tenant_member", "role": "editor"},
        headers=owner,
    )
    assert added.status_code == 200, added.text

    # 被邀请的人现在可以显式切到该租户
    switched = client.get(
        "/api/tenants/current", headers={**member, "X-Tenant-Id": owner_tenant}
    )
    assert switched.status_code == 200
    assert switched.json()["role"] == "editor"


# ---------------------------------------------------------------------------
# 数据隔离
# ---------------------------------------------------------------------------


def test_reports_are_isolated_between_tenants(client):
    _, alice = register(client, "tenant_a3")
    _, bob = register(client, "tenant_b3")

    created = client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST, headers=alice)
    assert created.status_code == 200, created.text
    report_id = created.json()["report"]["report_id"]

    assert client.get("/api/reports", headers=alice).json()["items"]
    assert client.get("/api/reports", headers=bob).json()["items"] == []
    # 直接按 ID 读取也要 404，不能泄漏存在性
    assert client.get(f"/api/reports/{report_id}", headers=bob).status_code == 404


def test_listings_are_isolated_between_tenants(client):
    _, alice = register(client, "tenant_a4")
    _, bob = register(client, "tenant_b4")

    analysis = client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST, headers=alice).json()
    listing_payload = {
        "product": {
            "name": "Isolation Bottle",
            "specifications": {"容量": "750ml"},
            "key_features": ["双层真空保温"],
        },
        "language": "en-US",
        "marketplace": "US",
        "analysis_report_id": analysis["report"]["report_id"],
    }
    created = client.post("/api/listings/generate", json=listing_payload, headers=alice)
    assert created.status_code == 200, created.text
    listing_id = created.json()["listing"]["listing_id"]

    assert client.get("/api/listings", headers=bob).json()["items"] == []
    assert client.get(f"/api/listings/{listing_id}", headers=bob).status_code == 404


def test_tasks_are_isolated_between_tenants(client):
    _, alice = register(client, "tenant_a5")
    _, bob = register(client, "tenant_b5")

    task_id = client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST, headers=alice).json()["task_id"]

    assert client.get("/api/tasks", headers=bob).json()["items"] == []
    assert client.get(f"/api/tasks/{task_id}", headers=bob).status_code == 404
    assert client.post(f"/api/tasks/{task_id}/cancel", headers=bob).status_code in (403, 404)


def test_task_list_scoped_to_selected_tenant(client):
    """同一用户加入两个租户时，切换租户只看到对应数据。"""
    _, owner = register(client, "tenant_a6")
    _, member = register(client, "tenant_b6")
    owner_tenant = current_tenant(client, owner)["tenant_id"]
    member_tenant = current_tenant(client, member)["tenant_id"]

    client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST, headers=owner)
    client.post(
        "/api/tenants/members",
        json={"username": "tenant_b6", "role": "editor"},
        headers=owner,
    )

    # 在 owner 的租户里能看到任务
    in_owner = client.get("/api/tasks", headers={**member, "X-Tenant-Id": owner_tenant})
    assert in_owner.status_code == 200
    assert len(in_owner.json()["items"]) == 1

    # 切回自己的租户就看不到
    in_own = client.get("/api/tasks", headers={**member, "X-Tenant-Id": member_tenant})
    assert in_own.status_code == 200
    assert in_own.json()["items"] == []


# ---------------------------------------------------------------------------
# 角色
# ---------------------------------------------------------------------------


def test_viewer_cannot_create_tasks(client):
    _, owner = register(client, "tenant_owner7")
    _, viewer = register(client, "tenant_viewer7")
    owner_tenant = current_tenant(client, owner)["tenant_id"]

    added = client.post(
        "/api/tenants/members",
        json={"username": "tenant_viewer7", "role": "viewer"},
        headers=owner,
    )
    assert added.status_code == 200
    viewer_headers = {**viewer, "X-Tenant-Id": owner_tenant}

    resp = client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST, headers=viewer_headers)
    assert resp.status_code == 403
    assert "无权" in resp.json()["detail"]

    # 只读操作仍然允许
    assert client.get("/api/reports", headers=viewer_headers).status_code == 200


def test_editor_cannot_invite_members(client):
    _, owner = register(client, "tenant_owner8")
    _, editor = register(client, "tenant_editor8")
    owner_tenant = current_tenant(client, owner)["tenant_id"]
    client.post(
        "/api/tenants/members",
        json={"username": "tenant_editor8", "role": "editor"},
        headers=owner,
    )

    resp = client.post(
        "/api/tenants/members",
        json={"username": "tenant_owner8", "role": "viewer"},
        headers={**editor, "X-Tenant-Id": owner_tenant},
    )
    assert resp.status_code == 400
    assert "无权" in resp.json()["detail"]


def test_invite_unknown_user_404(client):
    _, owner = register(client, "tenant_owner9")
    resp = client.post(
        "/api/tenants/members",
        json={"username": "nobody-here", "role": "viewer"},
        headers=owner,
    )
    assert resp.status_code == 404


def test_duplicate_member_rejected(client):
    _, owner = register(client, "tenant_owner10")
    _, other = register(client, "tenant_other10")
    client.post(
        "/api/tenants/members",
        json={"username": "tenant_other10", "role": "viewer"},
        headers=owner,
    )
    again = client.post(
        "/api/tenants/members",
        json={"username": "tenant_other10", "role": "editor"},
        headers=owner,
    )
    assert again.status_code == 400
    assert "已是本租户成员" in again.json()["detail"]


def test_tenant_stats_are_scoped(client):
    _, alice = register(client, "tenant_a11")
    client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST, headers=alice)
    stats = current_tenant(client, alice)["stats"]
    assert stats["reports"] == 1
    assert stats["tasks"] == 1
