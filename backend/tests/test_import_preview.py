"""导入两步流程测试（阶段 E6）。"""

from __future__ import annotations

import json


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


CUSTOM_CSV = "商品名,售价,品牌\nEcoSip Bottle,25.99,EcoSip\nTrailMug,18.50,TrailMate\n"


def preview(client, headers: dict, content: bytes, filename: str = "custom.csv", mapping=None):
    data = {}
    if mapping is not None:
        data["field_mapping"] = json.dumps(mapping, ensure_ascii=False)
    return client.post(
        "/api/import/preview",
        files={"file": (filename, content, "text/csv")},
        data=data,
        headers=headers,
    )


def test_preview_detects_unmapped_columns(client):
    headers = register(client, "imp_detect")
    resp = preview(client, headers, CUSTOM_CSV.encode("utf-8"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "needs_mapping"
    assert body["can_commit"] is False
    sources = {column["source"]: column for column in body["columns"]}
    assert "商品名" in sources
    assert body["errors"]


def test_preview_with_mapping_then_commit(client):
    headers = register(client, "imp_commit")
    resp = preview(
        client,
        headers,
        CUSTOM_CSV.encode("utf-8"),
        mapping={"商品名": "name", "售价": "price", "品牌": "brand"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "validated"
    assert body["can_commit"] is True
    assert body["total_rows"] == 2
    assert body["valid_rows"] == 2
    assert len(body["preview"]) == 2
    assert body["preview"][0]["price"] == 25.99
    data_source_id = body["data_source_id"]

    committed = client.post(
        "/api/import/commit",
        json={"data_source_id": data_source_id},
        headers=headers,
    )
    assert committed.status_code == 200, committed.text
    result = committed.json()
    assert result["batch_id"]
    assert result["task_id"]
    assert len(result["competitors"]) == 2
    assert result["data_source_id"] == data_source_id

    source = client.get(f"/api/data-sources/{data_source_id}", headers=headers).json()
    assert source["status"] == "imported"
    assert source["validation"]["errors"] == []

    # 不允许重复提交
    again = client.post(
        "/api/import/commit",
        json={"data_source_id": data_source_id},
        headers=headers,
    )
    assert again.status_code == 409


def test_row_errors_block_commit_and_can_be_downloaded(client):
    headers = register(client, "imp_errors")
    content = "name,price\n,9\nGood Bottle,12.5\nBad Price,abc\n".encode("utf-8")
    resp = preview(client, headers, content, "errors.csv")
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["can_commit"] is False
    assert len(body["errors"]) >= 2

    commit = client.post(
        "/api/import/commit",
        json={"data_source_id": body["data_source_id"]},
        headers=headers,
    )
    assert commit.status_code == 422
    assert "行级错误" in commit.json()["detail"]

    csv_resp = client.get(
        f"/api/data-sources/{body['data_source_id']}/errors.csv", headers=headers
    )
    assert csv_resp.status_code == 200
    assert "row,field,message,value" in csv_resp.text
    assert "name" in csv_resp.text


def test_preview_survives_supplying_mapping_at_commit(client):
    headers = register(client, "imp_late_map")
    body = preview(client, headers, CUSTOM_CSV.encode("utf-8")).json()
    assert body["status"] == "needs_mapping"

    commit = client.post(
        "/api/import/commit",
        json={
            "data_source_id": body["data_source_id"],
            "field_mapping": {"商品名": "name", "售价": "price"},
        },
        headers=headers,
    )
    assert commit.status_code == 200, commit.text
    assert len(commit.json()["competitors"]) == 2
    source = client.get(
        f"/api/data-sources/{body['data_source_id']}", headers=headers
    ).json()
    assert source["status"] == "imported"
    assert source["field_mapping"]["商品名"] == "name"


def test_data_source_and_commit_are_tenant_scoped(client):
    alice = register(client, "imp_alice")
    bob = register(client, "imp_bob")
    body = preview(
        client,
        alice,
        CUSTOM_CSV.encode("utf-8"),
        mapping={"商品名": "name", "售价": "price"},
    ).json()
    assert (
        client.get(f"/api/data-sources/{body['data_source_id']}", headers=bob).status_code
        == 404
    )
    assert (
        client.post(
            "/api/import/commit",
            json={"data_source_id": body["data_source_id"]},
            headers=bob,
        ).status_code
        == 404
    )
    assert client.get("/api/data-sources", headers=bob).json()["items"] == []


def test_viewer_cannot_preview(client):
    owner = register(client, "imp_owner")
    viewer = register(client, "imp_viewer")
    tenant_id = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    client.post(
        "/api/tenants/members",
        json={"username": "imp_viewer", "role": "viewer"},
        headers=owner,
    )
    resp = preview(
        client,
        {**viewer, "X-Tenant-Id": tenant_id},
        CUSTOM_CSV.encode("utf-8"),
    )
    assert resp.status_code == 403


def test_one_step_import_still_works(client):
    headers = register(client, "imp_legacy")
    resp = client.post(
        "/api/import",
        files={"file": ("legacy.csv", b"name,price\nLegacy Bottle,10\n", "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["competitors"]) == 1
    assert resp.json()["total_rows"] == 1
