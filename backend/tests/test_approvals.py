"""发布审批测试（阶段 D8）。"""

from __future__ import annotations


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def make_listing(client, headers: dict) -> str:
    payload = client.get("/api/demo/dataset").json()["listing_request"]
    resp = client.post("/api/listings/generate", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["listing"]["listing_id"]


def request_approval(client, headers: dict, listing_id: str) -> dict:
    resp = client.post(
        "/api/approvals",
        json={"kind": "publish_listing", "listing_id": listing_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_request_publish_creates_awaiting_approval_task(client):
    headers = register(client, "approval_req")
    listing_id = make_listing(client, headers)
    approval = request_approval(client, headers, listing_id)

    assert approval["status"] == "pending"
    assert approval["kind"] == "publish_listing"
    assert approval["payload"]["listing_id"] == listing_id

    detail = client.get(f"/api/tasks/{approval['task_id']}", headers=headers).json()
    assert detail["task"]["status"] == "awaiting_approval"
    assert detail["task"]["type"] == "publish_listing"
    assert detail["task"]["output"]["published"] is False
    assert detail["steps"][0]["status"] == "pending"

    pending = client.get("/api/approvals?status=pending", headers=headers).json()["items"]
    assert [item["approval_id"] for item in pending] == [approval["approval_id"]]


def test_admin_approval_unblocks_task_but_never_claims_publish(client):
    headers = register(client, "approval_ok")
    listing_id = make_listing(client, headers)
    approval = request_approval(client, headers, listing_id)

    decided = client.post(
        f"/api/approvals/{approval['approval_id']}/decide",
        json={"decision": "approved", "note": "同意"},
        headers=headers,
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["status"] == "approved"
    assert body["decided_by"]

    detail = client.get(f"/api/tasks/{approval['task_id']}", headers=headers).json()
    assert detail["task"]["status"] == "succeeded"
    assert detail["task"]["output"]["published"] is False
    assert detail["task"]["output"]["publish_not_connected"] is True
    assert detail["steps"][0]["status"] == "succeeded"
    assert "未实际发布" in detail["steps"][0]["detail"]


def test_rejection_fails_task_with_reason(client):
    headers = register(client, "approval_reject")
    listing_id = make_listing(client, headers)
    approval = request_approval(client, headers, listing_id)

    body = client.post(
        f"/api/approvals/{approval['approval_id']}/decide",
        json={"decision": "rejected", "note": "图片不合规"},
        headers=headers,
    ).json()
    assert body["status"] == "rejected"

    detail = client.get(f"/api/tasks/{approval['task_id']}", headers=headers).json()
    assert detail["task"]["status"] == "failed"
    assert detail["task"]["error_code"] == "approval_rejected"
    assert "图片不合规" in detail["task"]["error_message"]


def test_approval_cannot_be_decided_twice(client):
    headers = register(client, "approval_twice")
    listing_id = make_listing(client, headers)
    approval = request_approval(client, headers, listing_id)
    first = client.post(
        f"/api/approvals/{approval['approval_id']}/decide",
        json={"decision": "approved"},
        headers=headers,
    )
    assert first.status_code == 200
    second = client.post(
        f"/api/approvals/{approval['approval_id']}/decide",
        json={"decision": "rejected"},
        headers=headers,
    )
    assert second.status_code == 409


def test_editor_cannot_decide_and_viewer_cannot_request(client):
    owner = register(client, "approval_owner")
    member = register(client, "approval_member")
    viewer = register(client, "approval_viewer")
    tenant_id = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    client.post(
        "/api/tenants/members",
        json={"username": "approval_member", "role": "editor"},
        headers=owner,
    )
    client.post(
        "/api/tenants/members",
        json={"username": "approval_viewer", "role": "viewer"},
        headers=owner,
    )
    member_headers = {**member, "X-Tenant-Id": tenant_id}
    viewer_headers = {**viewer, "X-Tenant-Id": tenant_id}
    listing_id = make_listing(client, owner)
    approval = request_approval(client, member_headers, listing_id)

    assert (
        client.post(
            f"/api/approvals/{approval['approval_id']}/decide",
            json={"decision": "approved"},
            headers=member_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/approvals",
            json={"kind": "publish_listing", "listing_id": listing_id},
            headers=viewer_headers,
        ).status_code
        == 403
    )


def test_approval_is_tenant_scoped(client):
    alice = register(client, "approval_alice")
    bob = register(client, "approval_bob")
    listing_id = make_listing(client, alice)
    approval = request_approval(client, alice, listing_id)

    assert client.get(f"/api/approvals/{approval['approval_id']}", headers=bob).status_code == 404
    assert (
        client.post(
            f"/api/approvals/{approval['approval_id']}/decide",
            json={"decision": "approved"},
            headers=bob,
        ).status_code
        == 404
    )
    assert client.get("/api/approvals", headers=bob).json()["items"] == []


def test_request_for_unknown_listing_is_404(client):
    headers = register(client, "approval_missing")
    resp = client.post(
        "/api/approvals",
        json={"kind": "publish_listing", "listing_id": "does-not-exist"},
        headers=headers,
    )
    assert resp.status_code == 404


def test_unknown_approval_kind_is_rejected(client):
    headers = register(client, "approval_kind")
    resp = client.post(
        "/api/approvals",
        json={"kind": "delete_everything", "listing_id": "x"},
        headers=headers,
    )
    assert resp.status_code == 400
