"""Mock 店铺连接器测试（阶段 F1–F4）。"""

from __future__ import annotations

from crosspilot.services.connectors import (
    ConnectorError,
    LiveStoreConnector,
    build_connector,
)


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def create_store(client, headers: dict, shop_name: str = "Demo Shop") -> dict:
    resp = client.post(
        "/api/stores",
        json={
            "platform": "amazon",
            "marketplace": "US",
            "shop_name": shop_name,
            "mode": "mock",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_mock_store_and_list(client):
    headers = register(client, "store_create")
    store = create_store(client, headers)
    assert store["mode"] == "mock"
    assert store["status"] == "connected"
    assert store["is_mock"] is True
    assert store["credential_ref"] is None

    listing = client.get("/api/stores", headers=headers).json()
    assert listing["capabilities"]["mock"] is True
    assert listing["capabilities"]["live"] is False
    assert [item["connection_id"] for item in listing["items"]] == [store["connection_id"]]

    detail = client.get(f"/api/stores/{store['connection_id']}", headers=headers).json()
    assert detail["shop_name"] == "Demo Shop"


def test_mock_sync_is_deterministic_and_marked(client):
    headers = register(client, "store_sync")
    store = create_store(client, headers, "Deterministic Shop")
    first = client.post(f"/api/stores/{store['connection_id']}/sync", headers=headers)
    assert first.status_code == 200, first.text
    second = client.post(f"/api/stores/{store['connection_id']}/sync", headers=headers)
    assert second.status_code == 200
    body = first.json()
    assert body["products"] == 6
    assert body["orders"] == 8
    assert body["is_mock"] is True
    assert second.json()["products"] == body["products"]
    assert second.json()["orders"] == body["orders"]
    assert second.json()["revenue"] == body["revenue"]

    products = client.get(
        f"/api/stores/{store['connection_id']}/products", headers=headers
    ).json()["items"]
    orders = client.get(
        f"/api/stores/{store['connection_id']}/orders", headers=headers
    ).json()["items"]
    assert len(products) == 6 and len(orders) == 8
    assert all(item["is_mock"] is True for item in products + orders)

    updated = client.get(f"/api/stores/{store['connection_id']}", headers=headers).json()
    assert updated["last_sync_status"] == "ok"
    assert updated["last_sync_summary"]["products"] == 6


def test_test_and_disconnect_lifecycle(client):
    headers = register(client, "store_life")
    store = create_store(client, headers)
    tested = client.post(f"/api/stores/{store['connection_id']}/test", headers=headers)
    assert tested.status_code == 200
    assert tested.json()["connected"] is True
    assert tested.json()["mode"] == "mock"

    disconnected = client.delete(f"/api/stores/{store['connection_id']}", headers=headers)
    assert disconnected.status_code == 200
    assert disconnected.json()["status"] == "disconnected"

    refused = client.post(f"/api/stores/{store['connection_id']}/sync", headers=headers)
    assert refused.status_code == 400
    assert "connected" in refused.json()["detail"]


def test_live_mode_is_rejected_not_faked(client):
    headers = register(client, "store_live")
    resp = client.post(
        "/api/stores",
        json={
            "platform": "amazon",
            "marketplace": "US",
            "shop_name": "Real Shop",
            "mode": "live",
        },
        headers=headers,
    )
    assert resp.status_code == 400
    assert "尚未接入" in resp.json()["detail"]


def test_live_connector_reports_not_connected_and_refuses_sync():
    connector = LiveStoreConnector(
        {"platform": "amazon", "marketplace": "US", "shop_name": "x", "tenant_id": "t", "mode": "live"}
    )
    assert connector.status().connected is False
    assert "未接入" in connector.status().detail
    try:
        connector.sync()
    except ConnectorError as exc:
        assert "阶段 G" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Live connector 不应返回数据")


def test_credential_is_encrypted_and_never_returned(client):
    headers = register(client, "store_secret")
    store = create_store(client, headers)
    secret = "amazon-refresh-token-should-never-leak"
    resp = client.post(
        f"/api/stores/{store['connection_id']}/credential",
        json={"secret": secret},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert secret not in resp.text
    assert body["credential_ref"]
    assert body["masked"].startswith("ama") and "****" in body["masked"]

    db = client.app.state.db
    tenant_id = client.get("/api/tenants/current", headers=headers).json()["tenant_id"]
    stored = db.get_store_credential(body["credential_ref"], tenant_id)
    assert stored is not None
    assert stored["ciphertext"] != secret
    assert secret not in stored["ciphertext"]

    connection = client.get(
        f"/api/stores/{store['connection_id']}", headers=headers
    ).json()
    assert connection["credential_ref"] == body["credential_ref"]
    assert secret not in str(connection)

    audits = client.get("/api/audit?limit=100", headers=headers).text
    assert secret not in audits


def test_editor_cannot_store_credential_and_viewer_cannot_create(client):
    owner = register(client, "store_perm_owner")
    editor = register(client, "store_perm_editor")
    viewer = register(client, "store_perm_viewer")
    tenant_id = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    for username, role in (("store_perm_editor", "editor"), ("store_perm_viewer", "viewer")):
        client.post(
            "/api/tenants/members",
            json={"username": username, "role": role},
            headers=owner,
        )
    editor_headers = {**editor, "X-Tenant-Id": tenant_id}
    viewer_headers = {**viewer, "X-Tenant-Id": tenant_id}

    store = create_store(client, editor_headers, "Editor Shop")
    assert (
        client.post(
            f"/api/stores/{store['connection_id']}/credential",
            json={"secret": "x"},
            headers=editor_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/stores",
            json={
                "platform": "amazon",
                "marketplace": "US",
                "shop_name": "Viewer Shop",
                "mode": "mock",
            },
            headers=viewer_headers,
        ).status_code
        == 403
    )


def test_store_is_tenant_scoped(client):
    alice = register(client, "store_alice")
    bob = register(client, "store_bob")
    store = create_store(client, alice)
    assert client.get(f"/api/stores/{store['connection_id']}", headers=bob).status_code == 404
    assert client.post(f"/api/stores/{store['connection_id']}/sync", headers=bob).status_code == 404
    assert client.get("/api/stores", headers=bob).json()["items"] == []


def test_duplicate_connection_is_rejected(client):
    headers = register(client, "store_dup")
    create_store(client, headers, "Same Shop")
    resp = client.post(
        "/api/stores",
        json={
            "platform": "amazon",
            "marketplace": "US",
            "shop_name": "Same Shop",
            "mode": "mock",
        },
        headers=headers,
    )
    assert resp.status_code == 409


def test_build_connector_selects_mock_for_mock_mode():
    connector = build_connector(
        {"platform": "amazon", "marketplace": "US", "shop_name": "s", "tenant_id": "t", "mode": "mock"}
    )
    assert connector.mode == "mock"
