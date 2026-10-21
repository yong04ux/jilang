"""演示种子（M5/M8）：幂等、全部带 is_demo/seed_demo 标记。"""

from __future__ import annotations

import pytest


@pytest.fixture()
def seeded(client):
    from crosspilot.demo.seed import seed_demo

    db = client.app.state.db
    summary = seed_demo(db, demo_username="demo", demo_password="demo-pass-1234")
    return db, summary


def test_seed_creates_reports_listings_and_tasks(seeded):
    _db, summary = seeded
    assert summary["reports"] == 3
    assert summary["listings"] == 3
    assert summary["tasks"] == 6
    assert summary["user"] == "demo"


def test_seed_is_idempotent(seeded):
    from crosspilot.demo.seed import seed_demo

    db, _ = seeded
    again = seed_demo(db, demo_username="demo", demo_password="demo-pass-1234")
    assert again["reports"] == 0
    assert again["listings"] == 0
    assert again["tasks"] == 0


def test_seeded_reports_are_flagged_as_demo(seeded):
    db, summary = seeded
    reports = db.list_reports(limit=10, tenant_id=summary["tenant_id"])
    assert len(reports) == 3
    for report in reports:
        assert report["report_id"].startswith("seed-")
        # PG 里布尔列是 INTEGER，1 即 True
        assert bool(report["is_demo"]) is True

    payload = db.get_report(reports[0]["report_id"], tenant_id=summary["tenant_id"])
    assert payload["data_provenance"]["is_demo"] is True


def test_seeded_tasks_are_visible_on_dashboard(seeded, client):
    _db, summary = seeded
    login = client.post(
        "/api/auth/login", json={"username": "demo", "password": "demo-pass-1234"}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['token']}"}

    dashboard = client.get("/api/dashboard", headers=headers).json()
    assert dashboard["stats"]["reports"] == 3
    assert dashboard["stats"]["listings"] == 3
    assert len(dashboard["daily_tasks"]) == 14
    assert any(item["count"] > 0 for item in dashboard["daily_tasks"])

    tasks = client.get("/api/tasks", headers=headers).json()["items"]
    assert len(tasks) == 6
    assert all(task["origin"] == "seed" for task in tasks)


def test_seeded_listings_pass_their_own_quality_check(seeded, client):
    """种子草稿必须能通过复检 —— 否则演示站一打开就显示"质检有问题"。"""
    _db, summary = seeded
    login = client.post(
        "/api/auth/login", json={"username": "demo", "password": "demo-pass-1234"}
    )
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    for index in (1, 2, 3):
        resp = client.post(f"/api/listings/seed-listing-{index}/check", headers=headers)
        assert resp.status_code == 200, resp.text
        qc = resp.json()["quality_check"]
        assert qc["passed"] is True, f"seed-listing-{index} 质检未通过：{qc.get('issues')}"


def test_seeded_tasks_have_real_looking_steps(seeded, client):
    _db, summary = seeded
    login = client.post(
        "/api/auth/login", json={"username": "demo", "password": "demo-pass-1234"}
    )
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    detail = client.get("/api/tasks/seed-task-report-1", headers=headers).json()
    names = [step["name"] for step in detail["steps"]]
    assert names == [
        "生成执行计划",
        "竞品分析",
        "数据完整性检查",
        "生成市场机会总结",
        "保存报告与任务记录",
    ]
    assert detail["result"]["report"]["report_id"] == "seed-report-1"
