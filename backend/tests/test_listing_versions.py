"""Listing 版本、差异、复检与导出测试（阶段 E4/E5/E3）。"""

from __future__ import annotations

import uuid


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


def test_generated_listing_stores_product_snapshot(client):
    headers = register(client, "ver_snapshot")
    listing = make_listing(client, headers)
    stored = client.get(f"/api/listings/{listing['listing_id']}", headers=headers).json()
    assert stored["product_snapshot"]["name"] == listing["product_name"]
    assert stored["version"] == 1
    assert stored["parent_listing_id"] is None


def test_create_version_and_list_chain(client):
    headers = register(client, "ver_create")
    listing = make_listing(client, headers)
    created = client.post(
        f"/api/listings/{listing['listing_id']}/versions",
        json={"title": "A revised title for the insulated bottle"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    version = created.json()["listing"]
    assert version["listing_id"] != listing["listing_id"]
    assert version["version"] == 2
    assert version["parent_listing_id"] == listing["listing_id"]
    assert version["analysis_report_id"] == listing["analysis_report_id"]

    chain = client.get(
        f"/api/listings/{version['listing_id']}/versions", headers=headers
    ).json()["items"]
    assert [item["version"] for item in chain] == [1, 2]
    assert chain[0]["listing_id"] == listing["listing_id"]
    assert chain[1]["listing_id"] == version["listing_id"]


def test_edit_cannot_bypass_quality_check(client):
    headers = register(client, "ver_quality")
    listing = make_listing(client, headers)
    created = client.post(
        f"/api/listings/{listing['listing_id']}/versions",
        json={"title": "FDA certified leak proof bottle"},
        headers=headers,
    )
    quality = created.json()["listing"]["quality_check"]
    assert quality["passed"] is False
    assert any(
        issue["code"] in {"unauthorized_claim", "unverified_certification", "unsupported_number"}
        or "认证" in issue["message"]
        for issue in quality["issues"]
    )


def test_diff_against_parent(client):
    headers = register(client, "ver_diff")
    listing = make_listing(client, headers)
    version = client.post(
        f"/api/listings/{listing['listing_id']}/versions",
        json={"title": "Short revised title", "description": "A new description."},
        headers=headers,
    ).json()["listing"]

    diff = client.get(
        f"/api/listings/{version['listing_id']}/diff", headers=headers
    ).json()
    assert diff["base"]["listing_id"] == listing["listing_id"]
    assert diff["target"]["listing_id"] == version["listing_id"]
    assert {"title", "description"} <= set(diff["changed_fields"])
    assert diff["unified_diff"]


def test_version_requires_to_be_generated_from_existing(client):
    headers = register(client, "ver_missing")
    assert (
        client.post("/api/listings/nope/versions", json={"title": "x"}, headers=headers).status_code
        == 404
    )


def test_version_rejects_unknown_field_and_noop(client):
    headers = register(client, "ver_invalid")
    listing = make_listing(client, headers)
    resp = client.post(
        f"/api/listings/{listing['listing_id']}/versions",
        json={"product_name": "hacked"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "不支持修改" in resp.json()["detail"]

    resp = client.post(
        f"/api/listings/{listing['listing_id']}/versions",
        json={"title": listing["title"]},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "没有实际修改" in resp.json()["detail"]


def test_recheck_reuses_quality_pipeline(client):
    headers = register(client, "ver_recheck")
    listing = make_listing(client, headers)
    resp = client.post(f"/api/listings/{listing['listing_id']}/check", headers=headers)
    assert resp.status_code == 200, resp.text
    quality = resp.json()["quality_check"]
    assert "issues" in quality and "passed" in quality

    stored = client.get(f"/api/listings/{listing['listing_id']}", headers=headers).json()
    assert stored["quality_check"]["passed"] == quality["passed"]


def test_recheck_without_snapshot_explains_why(client):
    headers = register(client, "ver_nosnap")
    tenant = client.get("/api/tenants/current", headers=headers).json()
    db = client.app.state.db
    listing_id = uuid.uuid4().hex
    db.save_listing(
        {
            "listing_id": listing_id,
            "product_name": "Legacy Bottle",
            "platform": "amazon",
            "marketplace": "US",
            "language": "en-US",
            "title": "Legacy",
            "bullets": [],
            "description": "",
            "search_terms": "",
            "quality_check": {"passed": True, "issues": []},
            "data_provenance": {"data_source": "manual", "is_demo": False},
        },
        user_id=tenant["user_id"],
        tenant_id=tenant["tenant_id"],
    )
    resp = client.post(f"/api/listings/{listing_id}/check", headers=headers)
    assert resp.status_code == 409
    assert "商品事实快照" in resp.json()["detail"]


def test_export_listing_formats(client):
    headers = register(client, "ver_export")
    listing = make_listing(client, headers)
    md = client.get(f"/api/listings/{listing['listing_id']}/export?format=md", headers=headers)
    assert md.status_code == 200
    assert listing["title"] in md.text
    assert "## 五点描述" in md.text

    as_json = client.get(
        f"/api/listings/{listing['listing_id']}/export?format=json", headers=headers
    )
    assert as_json.status_code == 200
    assert as_json.json()["listing_id"] == listing["listing_id"]

    txt = client.get(
        f"/api/listings/{listing['listing_id']}/export?format=txt", headers=headers
    )
    assert txt.status_code == 200
    assert listing["title"] in txt.text


def test_version_and_export_are_tenant_scoped(client):
    alice = register(client, "ver_alice")
    bob = register(client, "ver_bob")
    listing = make_listing(client, alice)
    assert (
        client.post(
            f"/api/listings/{listing['listing_id']}/versions",
            json={"title": "hijacked title"},
            headers=bob,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/listings/{listing['listing_id']}/export", headers=bob
        ).status_code
        == 404
    )
