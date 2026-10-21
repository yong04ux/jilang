"""两步导入（M6）：preview → remap → commit，以及错误定位。"""

from __future__ import annotations

import io


def register(client, username="alice") -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def csv_bytes(rows: list[str]) -> bytes:
    return ("\n".join(rows) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------


def test_preview_recognizes_columns_and_returns_rows(client):
    headers = register(client, "imp_preview")
    data = csv_bytes([
        "name,brand,price,rating,review_text",
        "Bottle A,Acme,19.99,4.5,leaks a bit",
        "Bottle B,Beta,29.99,4.1,great grip",
    ])
    resp = client.post(
        "/api/import/preview",
        files={"file": ("test.csv", data, "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "validated"
    assert body["can_commit"] is True
    assert body["valid_rows"] == 2
    assert body["data_source_id"]

    by_source = {c["source"]: c for c in body["columns"]}
    assert by_source["name"]["field"] == "name"
    assert by_source["name"]["required"] is True
    assert by_source["price"]["field"] == "price"
    assert len(body["preview"]) == 2


def test_preview_does_not_write_business_data(client):
    headers = register(client, "imp_nowrite")
    data = csv_bytes(["name,price", "X,1.0"])
    client.post(
        "/api/import/preview",
        files={"file": ("a.csv", data, "text/csv")},
        headers=headers,
    )
    # 预览只写 data_sources，不产生导入批次
    sources = client.get("/api/data-sources", headers=headers).json()["items"]
    assert len(sources) == 1
    assert sources[0]["status"] in {"validated", "needs_mapping"}


def test_preview_flags_row_errors_with_row_and_field(client):
    headers = register(client, "imp_errors")
    data = csv_bytes([
        "name,price",
        "Good,10.0",
        ",15.0",          # 缺 name
        "BadPrice,abc",   # 价格非法
    ])
    resp = client.post(
        "/api/import/preview",
        files={"file": ("bad.csv", data, "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["can_commit"] is False
    assert len(body["errors"]) == 2
    fields = {e["field"] for e in body["errors"]}
    assert "name" in fields
    assert "price" in fields
    assert all(e["row"] >= 2 for e in body["errors"])


def test_preview_rejects_empty_file(client):
    headers = register(client, "imp_empty")
    resp = client.post(
        "/api/import/preview",
        files={"file": ("empty.csv", b"", "text/csv")},
        headers=headers,
    )
    assert resp.status_code in {422, 400}


def test_preview_requires_auth(client):
    resp = client.post(
        "/api/import/preview",
        files={"file": ("x.csv", b"name\nA\n", "text/csv")},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# remap
# ---------------------------------------------------------------------------


def test_remap_fixes_unrecognized_column(client):
    headers = register(client, "imp_remap")
    # 表头是中文别名里没有的写法，需要手动映射
    data = "商品标题,售价\nBottle A,19.99\n".encode("utf-8")
    preview = client.post(
        "/api/import/preview",
        files={"file": ("odd.csv", data, "text/csv")},
        headers=headers,
    ).json()
    assert preview["status"] == "needs_mapping"

    remapped = client.post(
        "/api/import/remap",
        json={
            "data_source_id": preview["data_source_id"],
            "field_mapping": {"商品标题": "name", "售价": "price"},
        },
        headers=headers,
    )
    assert remapped.status_code == 200, remapped.text
    body = remapped.json()
    assert body["status"] == "validated"
    assert body["valid_rows"] == 1
    assert body["field_mapping"] == {"商品标题": "name", "售价": "price"}


def test_remap_requires_non_empty_mapping(client):
    headers = register(client, "imp_remap_empty")
    preview = client.post(
        "/api/import/preview",
        files={"file": ("a.csv", b"name\nA\n", "text/csv")},
        headers=headers,
    ).json()
    resp = client.post(
        "/api/import/remap",
        json={"data_source_id": preview["data_source_id"], "field_mapping": {}},
        headers=headers,
    )
    assert resp.status_code == 422


def test_remap_unknown_source_is_404(client):
    headers = register(client, "imp_remap_404")
    resp = client.post(
        "/api/import/remap",
        json={"data_source_id": "nope", "field_mapping": {"a": "name"}},
        headers=headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


def test_commit_writes_batch_and_is_not_repeatable(client):
    headers = register(client, "imp_commit")
    data = csv_bytes(["name,price", "Bottle A,19.99", "Bottle B,29.99"])
    preview = client.post(
        "/api/import/preview",
        files={"file": ("ok.csv", data, "text/csv")},
        headers=headers,
    ).json()

    committed = client.post(
        "/api/import/commit",
        json={"data_source_id": preview["data_source_id"]},
        headers=headers,
    )
    assert committed.status_code == 200, committed.text
    body = committed.json()
    assert body["total_rows"] == 2
    assert len(body["competitors"]) == 2
    assert body["task_id"]

    again = client.post(
        "/api/import/commit",
        json={"data_source_id": preview["data_source_id"]},
        headers=headers,
    )
    assert again.status_code == 409
    assert "已提交" in again.json()["detail"]

    sources = client.get("/api/data-sources", headers=headers).json()["items"]
    assert sources[0]["status"] == "imported"


def test_commit_refuses_when_row_errors_remain(client):
    headers = register(client, "imp_commit_bad")
    data = csv_bytes(["name,price", ",1.0"])
    preview = client.post(
        "/api/import/preview",
        files={"file": ("bad.csv", data, "text/csv")},
        headers=headers,
    ).json()
    resp = client.post(
        "/api/import/commit",
        json={"data_source_id": preview["data_source_id"]},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "错误" in resp.json()["detail"]


def test_error_csv_contains_row_and_field(client):
    headers = register(client, "imp_err_csv")
    data = csv_bytes(["name,price", ",2.0"])
    preview = client.post(
        "/api/import/preview",
        files={"file": ("bad.csv", data, "text/csv")},
        headers=headers,
    ).json()
    resp = client.get(
        f"/api/data-sources/{preview['data_source_id']}/errors.csv", headers=headers
    )
    assert resp.status_code == 200
    text = resp.content.decode("utf-8-sig")
    assert "row,field,message,value" in text
    assert "name" in text


def test_import_is_tenant_scoped(client):
    alice = register(client, "imp_alice")
    bob = register(client, "imp_bob")
    preview = client.post(
        "/api/import/preview",
        files={"file": ("a.csv", b"name,price\nA,1.0\n", "text/csv")},
        headers=alice,
    ).json()
    resp = client.post(
        "/api/import/commit",
        json={"data_source_id": preview["data_source_id"]},
        headers=bob,
    )
    assert resp.status_code == 404
