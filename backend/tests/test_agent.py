"""Agent Runtime 与 Registry 测试。

全部走确定性路径：分析是规则引擎，Listing 在无 Key 时降级为事实直出，
因此**不需要任何真实模型调用**。
"""

from __future__ import annotations


from crosspilot.agent import registry, workflows
from crosspilot.agent.planner import plan_for
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST


def register(client, username: str) -> dict:
    resp = client.post("/api/auth/register", json={"username": username, "password": "password123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def agent_payload(**overrides) -> dict:
    payload = {
        "agent_key": "main",
        "product_name": "EcoSip Insulated Water Bottle",
        "platform": "amazon",
        "marketplace": "US",
        "own_specs": {"容量": "750ml", "材质": "304 不锈钢"},
        "own_key_features": ["双层真空保温"],
        "own_price": 22.9,
        "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
        "keywords": [],
        "with_listing": False,
        "data_source": "demo",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_is_seeded(client):
    headers = register(client, "agent_seed")
    agents = client.get("/api/agents", headers=headers).json()["items"]
    skills = client.get("/api/skills", headers=headers).json()["items"]
    tools = client.get("/api/tools", headers=headers).json()["items"]

    keys = {a["agent_key"] for a in agents}
    assert {"main", "competitor_expert", "listing_expert"} <= keys

    skill_keys = {s["skill_key"] for s in skills}
    assert {"competitor_analysis", "listing_generation", "market_summary"} <= skill_keys

    tool_keys = {t["tool_key"] for t in tools}
    assert "run_competitor_analysis" in tool_keys


def test_registry_definitions_have_schemas(client):
    headers = register(client, "agent_schema")
    agent = client.get("/api/agents/main", headers=headers).json()
    assert agent["name"]
    assert agent["input_schema"]["type"] == "object"
    assert agent["skill_keys"]
    assert agent["version"]


def test_unknown_agent_404(client):
    headers = register(client, "agent_404")
    assert client.get("/api/agents/nope", headers=headers).status_code == 404
    assert client.get("/api/skills/nope", headers=headers).status_code == 404


def test_seed_is_idempotent(client):
    """重复播种不应产生重复行。"""
    from crosspilot.app import create_app

    app = create_app()
    # 重建 app 会再次 seed；数量应保持不变
    db = app.state.db
    before = len(registry.list_agents(db, ""))
    registry.seed_registry(db)
    registry.seed_registry(db)
    after = len(registry.list_agents(db, ""))
    assert before == after == len(registry.AGENTS)


# ---------------------------------------------------------------------------
# Agent 运行
# ---------------------------------------------------------------------------


def test_agent_run_without_listing(client):
    headers = register(client, "agent_run1")
    resp = client.post("/api/agent/runs", json=agent_payload(), headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["task_id"]
    assert body["status"] == "succeeded"
    # 主图收敛为 validate → dispatch → 收尾，中间是竞品分析子图的步骤
    assert body["plan"] == plan_for(False)
    assert body["report"]["product_name"]
    assert body["listing"] is None
    assert body["summary"]["points"]
    assert body["checks"]["metrics"]["competitors"] >= 2


def test_agent_run_task_records_every_node(client):
    headers = register(client, "agent_run2")
    body = client.post("/api/agent/runs", json=agent_payload(), headers=headers).json()

    detail = client.get(f"/api/tasks/{body['task_id']}", headers=headers).json()
    # 用稳定的节点键断言，而不是展示文案——文案会改，键是契约
    nodes = [s["node"] for s in detail["steps"]]
    assert nodes == [
        "validate",
        "dispatch",
        "validate_input",
        "resolve_data_provider",
        "fetch_competitors",
        "normalize_data",
        "check_data_sufficiency",
        "analyze_market",
        "validate_analysis",
        "summarize_opportunities",
        "persist_result",
        "finalize",
    ]
    assert all(s["status"] == "succeeded" for s in detail["steps"])
    assert all(s["duration_ms"] is not None for s in detail["steps"])
    assert detail["task"]["type"] == "agent_workflow"


def test_agent_run_with_listing(client):
    headers = register(client, "agent_run3")
    resp = client.post(
        "/api/agent/runs", json=agent_payload(with_listing=True), headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["listing"] is not None
    assert body["plan"] == plan_for(True)
    assert body["quality"]["passed"] in (True, False)
    assert body["listing"]["analysis_report_id"] == body["report"]["report_id"]

    detail = client.get(f"/api/tasks/{body['task_id']}", headers=headers).json()
    nodes = [s["node"] for s in detail["steps"]]
    # 样本充足时不出现确认节点
    assert nodes == [
        "validate",
        "dispatch",
        "validate_request",
        "run_analysis",
        "check_listing_facts",
        "run_listing",
        "settle",
        "finalize",
    ]


def test_agent_run_persists_report_and_listing(client):
    headers = register(client, "agent_run4")
    body = client.post(
        "/api/agent/runs", json=agent_payload(with_listing=True), headers=headers
    ).json()

    reports = client.get("/api/reports", headers=headers).json()["items"]
    listings = client.get("/api/listings", headers=headers).json()["items"]
    assert any(r["report_id"] == body["report"]["report_id"] for r in reports)
    assert any(l["listing_id"] == body["listing"]["listing_id"] for l in listings)


def test_agent_run_rejects_empty_competitors(client):
    headers = register(client, "agent_run5")
    payload = agent_payload()
    payload["competitors"] = []
    assert client.post("/api/agent/runs", json=payload, headers=headers).status_code == 422


def test_agent_run_requires_write_role(client):
    owner = register(client, "agent_owner")
    viewer = register(client, "agent_viewer")
    owner_tenant = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    client.post(
        "/api/tenants/members",
        json={"username": "agent_viewer", "role": "viewer"},
        headers=owner,
    )
    resp = client.post(
        "/api/agent/runs",
        json=agent_payload(),
        headers={**viewer, "X-Tenant-Id": owner_tenant},
    )
    assert resp.status_code == 403


def test_agent_run_isolated_between_tenants(client):
    alice = register(client, "agent_a")
    bob = register(client, "agent_b")

    body = client.post("/api/agent/runs", json=agent_payload(), headers=alice).json()
    task_id = body["task_id"]

    assert client.get(f"/api/tasks/{task_id}", headers=bob).status_code == 404
    assert client.get("/api/tasks", headers=bob).json()["items"] == []


def test_market_summary_does_not_invent_numbers(client):
    """市场总结只能引用报告里的数字。"""
    headers = register(client, "agent_run6")
    body = client.post("/api/agent/runs", json=agent_payload(), headers=headers).json()
    summary = body["summary"]
    texts = " ".join(p["text"] for p in summary["points"])
    # 不允许出现销量/市场规模的断言
    for forbidden in ("销量", "市场规模", "增长率", "排名第一"):
        assert forbidden not in texts


def test_agent_run_failure_marks_task_failed(client, monkeypatch):
    """执行期异常必须落成 failed 任务，并保留失败步骤。

    状态码与错误码由统一分类决定：节点里的未知异常属于
    ``internal_error`` → 500（不是 502，502 是上游返回异常，这里是本进程出错）。
    """
    headers = register(client, "agent_run7")

    def boom(*args, **kwargs):
        raise RuntimeError("skill exploded")

    # 让图里的竞品分析节点失败（比 provider 构造失败更贴近真实故障）。
    #  起竞品子图直接调 engine.analysis.run_analysis，打桩点随之改变。
    monkeypatch.setattr("crosspilot.engine.analysis.run_analysis", boom)
    resp = client.post("/api/agent/runs", json=agent_payload(), headers=headers)
    assert resp.status_code == 500
    payload = resp.json()["detail"]
    assert payload["category"] == "internal_error"
    # 面向用户的文案里不能出现 Python 异常类名
    assert "RuntimeError" not in payload["message"]
    assert "skill exploded" not in payload["message"]

    tasks = client.get("/api/tasks", headers=headers).json()["items"]
    failed = [t for t in tasks if t["status"] == "failed"]
    assert failed
    detail = client.get(f"/api/tasks/{failed[0]['task_id']}", headers=headers).json()
    # 任务记录里的错误码是**分类**，不是异常类名
    assert detail["task"]["error_code"] == "internal_error"
    assert any(s["status"] == "failed" for s in detail["steps"])


# ---------------------------------------------------------------------------
# 只生成 Listing：不需要竞品数据
# ---------------------------------------------------------------------------


def test_listing_only_run_without_competitors(client):
    """选好商品就能出文案：这条路径不跑竞品分析，竞品为空是合法的。

    以前只要 competitors 为空就 422，用户想「给我的商品写个 Listing」
    会被要求先填竞品，这是不合理的。
    """
    headers = register(client, "agent_listing_only")
    resp = client.post(
        "/api/agent/runs",
        json={
            "agent_key": "main",
            "product_name": "EcoSip 保温杯",
            "platform": "amazon",
            "marketplace": "US",
            "competitors": [],
            "with_listing": True,
            "listing_only": True,
            "own_specs": {"容量": "750ml"},
            "own_key_features": ["双层真空保温"],
            "data_source": "manual",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    # 计划里没有竞品分析与市场总结
    assert body["plan"] == workflows.choose({"listing_only": True}).plan()
    assert body["report"] is None
    assert body["listing"]["listing_id"]
    assert body["listing"]["title"]


def test_listing_only_still_requires_product(client):
    """没有竞品可以，但没商品不行：要给出能照着做的提示，不是一句「缺少字段」。"""
    headers = register(client, "agent_listing_only_none")
    resp = client.post(
        "/api/agent/runs",
        json={"agent_key": "main", "competitors": [], "listing_only": True},
        headers=headers,
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    message = detail["message"] if isinstance(detail, dict) else str(detail)
    # 前端在发请求前就会拦「还没选商品」，这里只保证不会漏出技术报错
    assert message and "pydantic" not in message.lower() and "Traceback" not in message


def test_normal_run_still_requires_competitors(client):
    """反向保证：普通工作流没有竞品仍然要拦，不能被上一条放松。"""
    headers = register(client, "agent_listing_none")
    resp = client.post(
        "/api/agent/runs",
        json={"agent_key": "main", "product_name": "EcoSip", "competitors": []},
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["missing"] == ["competitors"]
