"""报告导出测试（阶段 E3）。"""

from __future__ import annotations

import json

from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def analyze(client, headers: dict) -> dict:
    resp = client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["report"]


def test_report_is_written_to_v2_table(client):
    headers = register(client, "export_dual")
    report = analyze(client, headers)
    db = client.app.state.db
    with db.connect() as connection:
        row = connection.execute(
            "SELECT payload, product_name FROM competitor_reports WHERE report_id = ?",
            (report["report_id"],),
        ).fetchone()
    assert row is not None
    assert row["product_name"] == report["product_name"]
    assert json.loads(row["payload"])["report_id"] == report["report_id"]


def test_export_report_markdown_json_csv(client):
    headers = register(client, "export_formats")
    report = analyze(client, headers)
    report_id = report["report_id"]

    markdown = client.get(f"/api/reports/{report_id}/export?format=md", headers=headers)
    assert markdown.status_code == 200
    assert "attachment" in markdown.headers["content-disposition"]
    assert report["product_name"] in markdown.text
    assert "## 竞品对比" in markdown.text
    assert "## 评论痛点" in markdown.text

    as_json = client.get(f"/api/reports/{report_id}/export?format=json", headers=headers)
    assert as_json.status_code == 200
    assert json.loads(as_json.text)["report_id"] == report_id

    as_csv = client.get(f"/api/reports/{report_id}/export?format=csv", headers=headers)
    assert as_csv.status_code == 200
    assert "review_samples" in as_csv.text
    assert report["competitor_snapshots"][0]["name"] in as_csv.text


def test_export_rejects_unknown_format(client):
    headers = register(client, "export_bad")
    report = analyze(client, headers)
    resp = client.get(
        f"/api/reports/{report['report_id']}/export?format=pdf", headers=headers
    )
    assert resp.status_code == 400
    assert "不支持" in resp.json()["detail"]


def test_export_is_tenant_scoped(client):
    alice = register(client, "export_alice")
    bob = register(client, "export_bob")
    report = analyze(client, alice)
    assert (
        client.get(f"/api/reports/{report['report_id']}/export", headers=bob).status_code
        == 404
    )


def test_export_is_audited(client):
    headers = register(client, "export_audit")
    report = analyze(client, headers)
    client.get(f"/api/reports/{report['report_id']}/export?format=md", headers=headers)
    actions = [
        item["action"]
        for item in client.get("/api/audit?limit=100", headers=headers).json()["items"]
    ]
    assert "report.export" in actions
