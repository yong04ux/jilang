"""任务记录测试：真实执行步骤、失败追踪、取消语义、用户隔离。"""

from __future__ import annotations

from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST, DEMO_LISTING_REQUEST


def test_analyze_creates_task_with_real_steps(auth_client):
    resp = auth_client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    task_id = body["task_id"]
    assert task_id

    detail = auth_client.get(f"/api/tasks/{task_id}").json()
    task = detail["task"]
    assert task["status"] == "succeeded"
    assert task["type"] == "competitor_analysis"
    assert task["result_ref"] == body["report"]["report_id"]
    assert task["trace_id"]

    steps = detail["steps"]
    assert [s["name"] for s in steps] == ["校验输入", "执行分析", "保存报告"]
    assert all(s["status"] == "succeeded" for s in steps)
    assert all(s["duration_ms"] is not None for s in steps)
    # 步骤序号必须连续，时间线才能正确渲染
    assert [s["seq"] for s in steps] == [1, 2, 3]


def test_failed_execution_creates_failed_task(auth_client, monkeypatch):
    """执行期失败必须留下 failed 任务与失败步骤（Pydantic 层 422 进不了端点，另测）。"""
    import crosspilot.api.analyses as analyses_mod
    from crosspilot.llm.providers import ProviderError

    def boom(*args, **kwargs):
        raise ProviderError("模型不可用（测试注入）")

    monkeypatch.setattr(analyses_mod, "build_provider", boom)
    resp = auth_client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST)
    assert resp.status_code == 503

    items = auth_client.get("/api/tasks").json()["items"]
    failed = [t for t in items if t["status"] == "failed"]
    assert failed, "执行失败也必须留下可追踪的任务记录"
    task = failed[0]
    assert task["error_code"] == "http_503"
    detail = auth_client.get(f"/api/tasks/{task['task_id']}").json()
    assert detail["steps"][0]["status"] == "succeeded"      # 校验输入通过
    assert detail["steps"][-1]["status"] == "failed"        # 执行分析失败


def test_request_schema_error_is_not_recorded_as_task(auth_client):
    """Pydantic 校验阶段就失败的请求不会进入端点，因此不应产生任务记录。"""
    payload = dict(DEMO_ANALYSIS_REQUEST)
    payload["competitors"] = []
    assert auth_client.post("/api/analyze", json=payload).status_code == 422
    assert auth_client.get("/api/tasks").json()["items"] == []


def test_listing_task_records_quality_result(auth_client):
    resp = auth_client.post("/api/listings/generate", json=DEMO_LISTING_REQUEST)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    detail = auth_client.get(f"/api/tasks/{task_id}").json()
    names = [s["name"] for s in detail["steps"]]
    assert names == ["读取关联报告", "生成文案", "质量检查", "保存草稿"]
    output = detail["task"]["output"]
    assert "quality_passed" in output
    assert output["listing_id"] == resp.json()["listing"]["listing_id"]


def test_task_filters_and_search(auth_client):
    auth_client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST)
    auth_client.post("/api/listings/generate", json=DEMO_LISTING_REQUEST)

    only_listing = auth_client.get("/api/tasks?status=succeeded&q=Listing").json()["items"]
    assert only_listing and all(t["type"] == "listing_generation" for t in only_listing)

    stats = auth_client.get("/api/tasks").json()["stats"]
    assert stats.get("succeeded", 0) >= 2


def test_cancel_rejects_finished_task(auth_client):
    task_id = auth_client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST).json()["task_id"]
    resp = auth_client.post(f"/api/tasks/{task_id}/cancel")
    assert resp.status_code == 409
    assert "无法取消" in resp.json()["detail"]


def test_tasks_are_isolated_between_users(client):
    first = client.post("/api/auth/register", json={"username": "task_a", "password": "password123"}).json()
    second = client.post("/api/auth/register", json={"username": "task_b", "password": "password123"}).json()

    created = client.post(
        "/api/analyze",
        json=DEMO_ANALYSIS_REQUEST,
        headers={"Authorization": f"Bearer {first['token']}"},
    )
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    # 另一个用户既看不到任务列表，也不能直接读任务
    other_headers = {"Authorization": f"Bearer {second['token']}"}
    assert client.get("/api/tasks", headers=other_headers).json()["items"] == []
    assert client.get(f"/api/tasks/{task_id}", headers=other_headers).status_code == 404
    assert client.post(f"/api/tasks/{task_id}/cancel", headers=other_headers).status_code == 404


def test_dashboard_uses_real_counts(auth_client):
    auth_client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST)
    data = auth_client.get("/api/dashboard").json()
    assert data["stats"]["succeeded"] >= 1
    assert data["recent_tasks"]
    assert data["recent_reports"]
