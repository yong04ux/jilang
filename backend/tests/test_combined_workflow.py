"""组合工作流测试：partial 暂停、确认、恢复。

覆盖需求列的 7 个场景 + 三条约束：

1. success → 直接进入 Listing
2. partial → 暂停（interrupt）+ checkpoint
3. 确认继续 → 恢复且**不重复执行竞品分析**
4. 用户取消 → 任务 cancelled
5. 必需商品事实缺失 → 即使确认也不生成
6. failed → 统一错误处理，不进入 Listing
7. 重复确认 / 令牌失效 / 跨租户恢复 → 拒绝
"""

from __future__ import annotations

import pytest

from crosspilot.agent.checkpoint import reset_checkpointer
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST


@pytest.fixture(autouse=True)
def _fresh_checkpointer():
    """每个用例一份干净的 checkpoint 池，避免用例之间互相"恢复"到别人的线程。"""
    reset_checkpointer()
    yield
    reset_checkpointer()


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def body(**overrides) -> dict:
    payload = {
        "product_name": "EcoSip Insulated Water Bottle",
        "platform": "amazon",
        "marketplace": "US",
        "own_specs": {"容量": "750ml", "材质": "304 不锈钢"},
        "own_key_features": ["双层真空保温"],
        "own_price": 22.9,
        "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
        "data_source": "demo",
    }
    payload.update(overrides)
    return payload


FEW_COMPETITORS = [DEMO_ANALYSIS_REQUEST["competitors"][0]]
NO_FACTS_PRODUCT = {"product_name": "只有名字的杯子", "own_specs": {}, "own_key_features": []}


def run_combined(client, headers, **overrides):
    resp = client.post("/api/agent/combined/runs", json=body(**overrides), headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def confirm(client, headers, task_id: str, decision: str, token: str):
    return client.post(
        f"/api/tasks/{task_id}/confirm",
        json={"decision": decision, "confirmation_token": token},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# 1. success：不暂停，直接进 Listing
# ---------------------------------------------------------------------------


def test_success_runs_straight_through(client):
    headers = register(client, "cw_ok")
    out = run_combined(client, headers)

    assert out["status"] == "succeeded"
    assert out["analysis_outcome"] == "succeeded"
    assert out["pending"] is None

    detail = client.get(f"/api/tasks/{out['task_id']}", headers=headers).json()
    nodes = [s.get("node") for s in detail["steps"]]
    assert "run_analysis" in nodes and "run_listing" in nodes
    assert "confirm_partial" not in nodes  # 没暂停就不该有确认步骤
    assert detail["result"]["listing_id"]
    assert detail["pending"] is None


# ---------------------------------------------------------------------------
# 2/3. partial：暂停 → 确认继续 → 恢复且不重跑分析
# ---------------------------------------------------------------------------


def test_partial_pauses_with_confirmable_payload(client):
    headers = register(client, "cw_partial")
    out = run_combined(client, headers, competitors=FEW_COMPETITORS)

    assert out["status"] == "waiting_for_review"
    assert out["analysis_outcome"] == "partial"
    pending = out["pending"]
    assert pending["reasons"], "必须说明缺什么"
    assert pending["affected_conclusions"], "必须说明影响哪些结论"
    assert pending["risks"], "必须说明继续的风险"
    assert pending["confirmation_token"]
    assert pending["options"] == ["continue", "cancel"]

    detail = client.get(f"/api/tasks/{out['task_id']}", headers=headers).json()
    assert detail["task"]["status"] == "waiting_for_review"
    # 暂停不等于结束：不应该有 finished_at
    assert detail["task"]["finished_at"] is None
    assert detail["pending"]["confirmation_token"] == pending["confirmation_token"]
    # 暂停时还没有 Listing
    assert not detail["result"]["listing_id"]


def test_confirm_continue_resumes_without_rerunning_analysis(client):
    headers = register(client, "cw_resume")
    out = run_combined(client, headers, competitors=FEW_COMPETITORS)
    task_id = out["task_id"]

    resp = confirm(client, headers, task_id, "continue", out["pending"]["confirmation_token"])
    assert resp.status_code == 200, resp.text
    resumed = resp.json()
    assert resumed["decision"] == "continue"
    # partial 不得因确认而变成 success
    assert resumed["status"] == "partial"
    assert resumed["analysis_outcome"] == "partial"

    detail = client.get(f"/api/tasks/{task_id}", headers=headers).json()
    nodes = [s.get("node") for s in detail["steps"]]
    # 竞品分析只跑过一次：恢复不能重算
    assert nodes.count("run_analysis") == 1
    assert detail["result"]["listing_id"]
    assert detail["result"]["quality"] is not None  # 质检结果必须在
    # 步骤序号不能因为恢复而从 1 重新开始
    seqs = [s["seq"] for s in detail["steps"]]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))


def test_resume_keeps_partial_marker_in_provenance(client):
    headers = register(client, "cw_prov")
    out = run_combined(client, headers, competitors=FEW_COMPETITORS)
    confirm(client, headers, out["task_id"], "continue", out["pending"]["confirmation_token"])

    detail = client.get(f"/api/tasks/{out['task_id']}", headers=headers).json()
    provenance = detail["result"]["provenance"]
    assert provenance["analysis_outcome"] == "partial"
    assert provenance["data_provider"] == "manual"


# ---------------------------------------------------------------------------
# 4. 用户取消
# ---------------------------------------------------------------------------


def test_confirm_cancel_ends_without_listing(client):
    headers = register(client, "cw_cancel")
    out = run_combined(client, headers, competitors=FEW_COMPETITORS)

    resp = confirm(client, headers, out["task_id"], "cancel", out["pending"]["confirmation_token"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"

    detail = client.get(f"/api/tasks/{out['task_id']}", headers=headers).json()
    assert detail["task"]["status"] == "cancelled"
    assert detail["task"]["finished_at"]
    nodes = [s.get("node") for s in detail["steps"]]
    assert "cancel_flow" in nodes
    assert "run_listing" not in nodes  # 取消后绝不生成


# ---------------------------------------------------------------------------
# 5. 必需商品事实缺失：确认了也不能写
# ---------------------------------------------------------------------------


def test_missing_product_facts_block_before_confirmation(client):
    """商品事实缺失时**直接拦住**，不会白问一次"要不要继续"。

     收敛后把事实检查提到了确认之前：事实缺了必然生成不了，
    这时候再弹确认只是浪费用户一次点击。
    """
    headers = register(client, "cw_nofacts")
    resp = client.post(
        "/api/agent/combined/runs",
        json=body(competitors=FEW_COMPETITORS, **NO_FACTS_PRODUCT),
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["category"] == "missing_input"
    assert detail["code"] == "product_facts_missing"

    tasks = client.get("/api/tasks", headers=headers).json()["items"]
    waiting = [t for t in tasks if t["status"] == "waiting_for_input"]
    assert waiting, f"应落成等待补充资料，实际：{[t['status'] for t in tasks]}"
    # 既然没问过，就不该有待确认载荷
    assert not (waiting[0].get("output") or {}).get("pending")
    # 也没有 Listing
    detail_task = client.get(f"/api/tasks/{waiting[0]['task_id']}", headers=headers).json()
    assert detail_task["result"]["listing_id"] is None
    nodes = [s.get("node") for s in detail_task["steps"]]
    assert "run_listing" not in nodes
    assert "confirm_partial" not in nodes


# ---------------------------------------------------------------------------
# 6. failed：统一错误处理，不进入 Listing
# ---------------------------------------------------------------------------


def test_analysis_failure_stops_before_listing(client, monkeypatch):
    from crosspilot.market.competitor_provider import CompetitorProviderError

    def boom(*args, **kwargs):
        raise CompetitorProviderError("取数服务异常")

    monkeypatch.setattr(
        "crosspilot.agent.graphs.combined_operations.run_competitor_graph", boom
    )
    headers = register(client, "cw_failed")
    resp = client.post("/api/agent/combined/runs", json=body(), headers=headers)

    # 数据源故障 → 503（provider_unavailable），不是 500
    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["category"] == "provider_unavailable"

    tasks = client.get("/api/tasks", headers=headers).json()["items"]
    failed = next(t for t in tasks if t["status"] == "failed")
    detail = client.get(f"/api/tasks/{failed['task_id']}", headers=headers).json()
    nodes = [s.get("node") for s in detail["steps"]]
    assert "run_listing" not in nodes
    assert detail["result"]["listing_id"] is None


# ---------------------------------------------------------------------------
# 7. 重复确认 / 令牌失效 / 跨租户
# ---------------------------------------------------------------------------


def test_second_confirm_is_rejected(client):
    headers = register(client, "cw_dup")
    out = run_combined(client, headers, competitors=FEW_COMPETITORS)
    token = out["pending"]["confirmation_token"]

    first = confirm(client, headers, out["task_id"], "continue", token)
    assert first.status_code == 200
    second = confirm(client, headers, out["task_id"], "continue", token)
    assert second.status_code == 409  # 状态已不是 waiting_for_review


def test_stale_confirmation_token_is_rejected(client):
    headers = register(client, "cw_stale")
    out = run_combined(client, headers, competitors=FEW_COMPETITORS)

    resp = confirm(client, headers, out["task_id"], "continue", "0000000000000000")
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "confirmation_stale"
    # 令牌不对时不能把任务改成 running 卡住
    detail = client.get(f"/api/tasks/{out['task_id']}", headers=headers).json()
    assert detail["task"]["status"] == "waiting_for_review"


def test_invalid_decision_is_rejected(client):
    headers = register(client, "cw_bad")
    out = run_combined(client, headers, competitors=FEW_COMPETITORS)
    resp = confirm(client, headers, out["task_id"], "maybe", out["pending"]["confirmation_token"])
    assert resp.status_code == 422


def test_cross_tenant_confirm_is_404(client):
    alice = register(client, "cw_alice")
    bob = register(client, "cw_bob")
    out = run_combined(client, alice, competitors=FEW_COMPETITORS)

    resp = confirm(client, bob, out["task_id"], "continue", out["pending"]["confirmation_token"])
    assert resp.status_code == 404  # 不泄露任务是否存在


def test_paused_task_survives_saver_restart(client):
    """ 起 checkpoint 落库：丢掉 saver 实例（≈ 进程重启）仍能恢复。

     时这条用例断言的是"重启后 409 无法恢复"；现在状态在数据库里，
    正确行为反过来了——真正"状态丢了"的场景由
    ``test_recovery.test_confirm_after_checkpoint_loss_reports_clearly`` 覆盖
    （显式删掉线程），那里仍然必须给 409。
    """
    headers = register(client, "cw_lost")
    out = run_combined(client, headers, competitors=FEW_COMPETITORS)
    assert out["status"] == "waiting_for_review"

    reset_checkpointer()  # 模拟进程重启：缓存与连接全丢
    from crosspilot.agent import checkpoint as checkpoint_mod

    checkpoint_mod.setup_checkpointer()

    resp = confirm(
        client, headers, out["task_id"], "continue", out["pending"]["confirmation_token"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "partial"


def test_paused_task_detail_exposes_everything_the_ui_needs(client):
    """界面确认卡片读的就是这份数据，字段缺一个按钮就没法用。

    前端在 ``/api/tasks/{id}`` **顶层**的 ``pending`` 上渲染：问题、原因、
    受影响结论、以及提交确认用的 token。这里把它们钉成契约。
    """
    headers = register(client, "cw_ui_pending")
    out = run_combined(client, headers, competitors=FEW_COMPETITORS)
    assert out["status"] == "waiting_for_review"

    detail = client.get(f"/api/tasks/{out['task_id']}", headers=headers).json()
    pending = detail["pending"]
    assert pending["question"]
    assert pending["reasons"], "确认卡片要说明为什么停"
    assert pending["affected_conclusions"]
    assert pending["confirmation_token"]

    # 界面上点「继续生成」走的就是这条链路
    resp = confirm(client, headers, out["task_id"], "continue", pending["confirmation_token"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "partial"

    after = client.get(f"/api/tasks/{out['task_id']}", headers=headers).json()
    assert after["task"]["status"] == "partial"
    # 确认过后不该再有待确认内容，否则界面会一直弹
    assert after["pending"] is None


def test_checkpoint_loss_still_allows_cancel(client):
    """真丢掉 checkpoint 也要能收尾：取消分支不依赖它。"""
    headers = register(client, "cw_lost_cancel")
    out = run_combined(client, headers, competitors=FEW_COMPETITORS)

    from crosspilot.agent import checkpoint as checkpoint_mod

    tenant_id = client.get("/api/tenants/current", headers=headers).json()["tenant_id"]
    checkpoint_mod.cleanup_thread(tenant_id, out["task_id"])

    resp = confirm(client, headers, out["task_id"], "cancel", out["pending"]["confirmation_token"])
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# 图级：确认不能跳过质检
# ---------------------------------------------------------------------------


def test_confirmation_does_not_bypass_quality_check():
    """确认继续 ≠ 免检：Listing 质检一定执行，结论如实保留。"""
    from crosspilot.agent.checkpoint import thread_config
    from crosspilot.agent.graphs.combined_operations import build_combined_graph
    from crosspilot.llm.providers import RuleProvider
    from crosspilot.market.competitor_provider import CompetitorData

    class Counting:
        mode = "imported"
        name = "counting"

        def __init__(self) -> None:
            self.calls = 0

        def fetch(self, query):
            self.calls += 1
            return CompetitorData(rows=[dict(r) for r in query.rows or []], source="manual")

    provider = Counting()
    graph = build_combined_graph(provider=RuleProvider(), competitor_provider=provider)
    config = thread_config("tenant-x", "task-x")

    paused = graph.start({"request": body(competitors=FEW_COMPETITORS)}, config)
    assert paused["analysis_outcome"] == "partial"
    final = graph.resume("continue", config)

    # 分析只跑一次
    assert provider.calls == 1
    # 质检存在且如实（规则引擎降级 >> passed=False），没被确认流程跳过
    assert final["listing"]["quality_check"]["passed"] is False
    assert final["outcome"] == "partial"
