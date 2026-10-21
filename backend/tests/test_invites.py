"""租户邀请与注册开关测试（阶段 C3）。"""

from __future__ import annotations


def register(client, username: str, **extra) -> dict:
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123", **extra},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def close_registration(monkeypatch):
    from crosspilot.config import get_settings

    monkeypatch.setenv("CROSSPILOT_ALLOW_OPEN_REGISTRATION", "false")
    get_settings.cache_clear()


def test_open_registration_can_be_closed(client, monkeypatch):
    owner = register(client, "invite_owner")
    close_registration(monkeypatch)

    resp = client.post(
        "/api/auth/register",
        json={"username": "invite_stranger", "password": "password123"},
    )
    assert resp.status_code == 403
    assert "邀请" in resp.json()["detail"]

    # 已有管理员不受影响
    assert client.get("/api/tenants", headers=owner).status_code == 200


def test_invited_user_joins_tenant(client, monkeypatch):
    owner = register(client, "invite_admin")
    tenant_id = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]

    invite = client.post(
        "/api/tenants/invites", json={"role": "editor"}, headers=owner
    ).json()
    token = invite["token"]
    assert token
    assert invite["invite"]["role"] == "editor"

    close_registration(monkeypatch)
    newcomer = register(client, "invite_newbie", invite_token=token)

    members = client.get("/api/tenants/members", headers=owner).json()["items"]
    assert "invite_newbie" in {item["username"] for item in members}

    tenants = client.get("/api/tenants", headers=newcomer).json()["items"]
    memberships = {item["tenant_id"]: item["role"] for item in tenants}
    assert memberships[tenant_id] == "editor"
    # 同时保留个人空间
    assert len(memberships) == 2

    # 同一令牌不能用第二次
    resp = client.post(
        "/api/auth/register",
        json={
            "username": "invite_second",
            "password": "password123",
            "invite_token": token,
        },
    )
    assert resp.status_code == 403
    assert "已被使用" in resp.json()["detail"]


def test_invalid_invite_is_rejected(client, monkeypatch):
    register(client, "invite_valid_owner")
    close_registration(monkeypatch)
    resp = client.post(
        "/api/auth/register",
        json={
            "username": "invite_bad",
            "password": "password123",
            "invite_token": "not-a-real-token",
        },
    )
    assert resp.status_code == 403
    assert "无效" in resp.json()["detail"]


def test_owner_role_cannot_be_invited(client):
    headers = register(client, "invite_role_owner")
    resp = client.post(
        "/api/tenants/invites", json={"role": "owner"}, headers=headers
    )
    assert resp.status_code == 400


def test_only_admins_can_create_or_list_invites(client):
    owner = register(client, "invite_perm_owner")
    editor = register(client, "invite_perm_editor")
    tenant_id = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    client.post(
        "/api/tenants/members",
        json={"username": "invite_perm_editor", "role": "editor"},
        headers=owner,
    )
    headers = {**editor, "X-Tenant-Id": tenant_id}
    assert client.get("/api/tenants/invites", headers=headers).status_code == 403
    assert (
        client.post("/api/tenants/invites", json={"role": "viewer"}, headers=headers).status_code
        == 403
    )


def test_invite_list_never_exposes_token_hash(client):
    headers = register(client, "invite_hash")
    client.post("/api/tenants/invites", json={"role": "viewer"}, headers=headers)
    items = client.get("/api/tenants/invites", headers=headers).json()["items"]
    assert items
    assert all("token_hash" not in item for item in items)
