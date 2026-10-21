"""跨租户与角色隔离矩阵（阶段 F5）。

一个租户内共享任务/报告/Listing/数据源/店铺连接；租户之间一律 404。
写操作要求 editor，成员管理/审批/审计要求 admin，凭据写入要求 admin。
"""

from __future__ import annotations

import json

from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def make_listing(client, headers: dict) -> dict:
    payload = client.get("/api/demo/dataset").json()["listing_request"]
    resp = client.post("/api/listings/generate", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["listing"]


def make_store(client, headers: dict, name: str) -> dict:
    resp = client.post(
        "/api/stores",
        json={"platform": "amazon", "marketplace": "US", "shop_name": name, "mode": "mock"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def make_preview(client, headers: dict) -> dict:
    resp = client.post(
        "/api/import/preview",
        files={"file": ("matrix.csv", b"name,price\nMatrix Bottle,10\n", "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_cross_tenant_reads_and_lists(client):
    alice = register(client, "mx_alice")
    bob = register(client, "mx_bob")

    report = client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST, headers=alice).json()
    report_id = report["report"]["report_id"]
    task_id = report["task_id"]
    listing = make_listing(client, alice)
    conversation = client.post("/api/conversations", json={}, headers=alice).json()["conversation"]
    data_source = make_preview(client, alice)
    approval = client.post(
        "/api/approvals",
        json={"kind": "publish_listing", "listing_id": listing["listing_id"]},
        headers=alice,
    ).json()
    store = make_store(client, alice, "Alice Shop")

    urls = {
        "report": f"/api/reports/{report_id}",
        "task": f"/api/tasks/{task_id}",
        "listing": f"/api/listings/{listing['listing_id']}",
        "conversation": f"/api/conversations/{conversation['conversation_id']}",
        "data_source": f"/api/data-sources/{data_source['data_source_id']}",
        "approval": f"/api/approvals/{approval['approval_id']}",
        "store": f"/api/stores/{store['connection_id']}",
    }
    for name, url in urls.items():
        response = client.get(url, headers=bob)
        assert response.status_code == 404, f"{name} 跨租户应为 404，实际 {response.status_code}"

    lists = {
        "reports": ("/api/reports", "report_id", report_id),
        "listings": ("/api/listings", "listing_id", listing["listing_id"]),
        "tasks": ("/api/tasks", "task_id", task_id),
        "conversations": ("/api/conversations", "conversation_id", conversation["conversation_id"]),
        "data_sources": ("/api/data-sources", "data_source_id", data_source["data_source_id"]),
        "approvals": ("/api/approvals", "approval_id", approval["approval_id"]),
        "stores": ("/api/stores", "connection_id", store["connection_id"]),
    }
    for name, (url, key, identifier) in lists.items():
        items = client.get(url, headers=bob).json()["items"]
        assert identifier not in {item[key] for item in items}, f"{name} 列表泄漏跨租户数据"


def test_role_matrix(client):
    owner = register(client, "mx_owner")
    viewer = register(client, "mx_viewer")
    editor = register(client, "mx_editor")
    admin = register(client, "mx_admin")
    tenant_id = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    for username, role in (
        ("mx_viewer", "viewer"),
        ("mx_editor", "editor"),
        ("mx_admin", "admin"),
    ):
        resp = client.post(
            "/api/tenants/members",
            json={"username": username, "role": role},
            headers=owner,
        )
        assert resp.status_code == 200, resp.text

    viewer_h = {**viewer, "X-Tenant-Id": tenant_id}
    editor_h = {**editor, "X-Tenant-Id": tenant_id}
    admin_h = {**admin, "X-Tenant-Id": tenant_id}

    listing = make_listing(client, owner)
    store = make_store(client, owner, "Role Shop")

    analysis_body = json.dumps(DEMO_ANALYSIS_REQUEST, ensure_ascii=False)
    cases = [
        (
            "viewer 发起分析",
            lambda: client.post(
                "/api/analyze",
                content=analysis_body.encode("utf-8"),
                headers={**viewer_h, "Content-Type": "application/json"},
            ),
            403,
        ),
        (
            "editor 发起分析",
            lambda: client.post(
                "/api/analyze",
                content=analysis_body.encode("utf-8"),
                headers={**editor_h, "Content-Type": "application/json"},
            ),
            200,
        ),
        (
            "viewer 上传预览",
            lambda: client.post(
                "/api/import/preview",
                files={"file": ("v.csv", b"name\nX\n", "text/csv")},
                headers=viewer_h,
            ),
            403,
        ),
        (
            "editor 上传预览",
            lambda: client.post(
                "/api/import/preview",
                files={"file": ("e.csv", b"name\nX\n", "text/csv")},
                headers=editor_h,
            ),
            200,
        ),
        (
            "viewer 创建店铺",
            lambda: client.post(
                "/api/stores",
                json={"platform": "amazon", "marketplace": "US", "shop_name": "V", "mode": "mock"},
                headers=viewer_h,
            ),
            403,
        ),
        (
            "editor 创建店铺",
            lambda: client.post(
                "/api/stores",
                json={"platform": "amazon", "marketplace": "US", "shop_name": "E", "mode": "mock"},
                headers=editor_h,
            ),
            200,
        ),
        (
            "viewer 派生版本",
            lambda: client.post(
                f"/api/listings/{listing['listing_id']}/versions",
                json={"title": "Viewer edit attempt"},
                headers=viewer_h,
            ),
            403,
        ),
        (
            "editor 派生版本",
            lambda: client.post(
                f"/api/listings/{listing['listing_id']}/versions",
                json={"title": "Editor approved revision"},
                headers=editor_h,
            ),
            200,
        ),
        (
            "editor 审批",
            lambda: client.get("/api/approvals", headers=editor_h),
            200,
        ),
        (
            "editor 读审计",
            lambda: client.get("/api/audit", headers=editor_h),
            403,
        ),
        (
            "admin 读审计",
            lambda: client.get("/api/audit", headers=admin_h),
            200,
        ),
        (
            "editor 创建邀请",
            lambda: client.post("/api/tenants/invites", json={"role": "viewer"}, headers=editor_h),
            403,
        ),
        (
            "admin 创建邀请",
            lambda: client.post("/api/tenants/invites", json={"role": "viewer"}, headers=admin_h),
            200,
        ),
        (
            "editor 写凭据",
            lambda: client.post(
                f"/api/stores/{store['connection_id']}/credential",
                json={"secret": "editor-token"},
                headers=editor_h,
            ),
            403,
        ),
        (
            "admin 写凭据",
            lambda: client.post(
                f"/api/stores/{store['connection_id']}/credential",
                json={"secret": "admin-token"},
                headers=admin_h,
            ),
            200,
        ),
    ]
    for name, action, expected in cases:
        response = action()
        assert response.status_code == expected, (
            f"{name} 期望 {expected}，实际 {response.status_code}: {response.text[:200]}"
        )

    # viewer 可以只读（报告/Listing/店铺）
    assert client.get("/api/listings", headers=viewer_h).status_code == 200
    assert client.get("/api/reports", headers=viewer_h).status_code == 200
    assert client.get("/api/stores", headers=viewer_h).status_code == 200
