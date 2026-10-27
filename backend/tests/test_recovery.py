"""Phase 6：Checkpoint 持久化、幂等与恢复测试。

覆盖计划 §11 Phase 6 的验收：
1. 中断后可以按设计恢复，或明确失败；
2. 输入变化后不错误复用旧结果；
3. 重试不重复写入产物；
4. 取消后状态最终一致。
"""

from __future__ import annotations

import pytest

from crosspilot.agent import checkpoint as checkpoint_mod
from crosspilot.agent import steps as steps_mod
from crosspilot.agent import workflows
from crosspilot.agent.graphs.combined_operations import build_combined_graph
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST
from crosspilot.llm.providers import RuleProvider


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


# ---------------------------------------------------------------------------
# 1. Checkpoint 落库：跨 saver 实例（≈ 进程重启）仍能恢复
# ---------------------------------------------------------------------------


def test_checkpoint_survives_process_restart(temp_settings):
    """暂停状态存在数据库里，不是进程内存里。

    做法：暂停后**丢掉整个 saver 实例**（连接关掉、缓存清空），
    再用全新 saver 恢复。如果状态只在内存里，这一步拿不到任何东西。
    """
    config = checkpoint_mod.thread_config("tenant-restart", "task-restart")
    payload = {"request": body(competitors=FEW_COMPETITORS), "task_id": "task-restart"}

    graph = build_combined_graph(provider=RuleProvider())
    paused = graph.start(payload, config)
    assert paused.get("__interrupt__"), "应当停在确认点"
    assert checkpoint_mod.pending_interrupts(graph._graph, config), "应能读到待确认载荷"

    # —— 模拟进程重启：连接关掉、模块缓存清空 ——
    checkpoint_mod.reset_checkpointer()
    checkpoint_mod.setup_checkpointer()

    fresh = build_combined_graph(provider=RuleProvider())
    assert checkpoint_mod.pending_interrupts(fresh._graph, config), "新进程应能读到同一个暂停点"

    final = fresh.resume("continue", config)
    assert final.get("outcome") in {"partial", "succeeded"}
    assert final.get("listing"), "恢复后应产出草稿"


def test_backend_is_postgres_in_tests(temp_settings):
    """测试环境连的是真数据库，所以这里必须是 postgres 后端。

    如果哪天退化回内存，上面的持久化测试会静默变成"内存之间传递"，
    这条断言就是为了防止那种假绿。
    """
    assert checkpoint_mod.backend_name() == "postgres"


def test_checkpoint_cleaned_up_after_task_finishes(client):
    """终态任务的 checkpoint 会被清掉（清理策略）。"""
    headers = register(client, "ck_cleanup")
    out = client.post(
        "/api/agent/combined/runs", json=body(), headers=headers
    ).json()
    assert out["status"] == "succeeded"

    graph = build_combined_graph(provider=RuleProvider())
    config = checkpoint_mod.thread_config(
        client.get("/api/tenants/current", headers=headers).json()["tenant_id"],
        out["task_id"],
    )
    # 任务已经结束，线程里不该再有可恢复的中断点
    assert not checkpoint_mod.pending_interrupts(graph._graph, config)


# ---------------------------------------------------------------------------
# 2. 输入指纹 / 工作流版本：输入变了不复用
# ---------------------------------------------------------------------------


def test_fingerprint_ignores_volatile_fields():
    base = body()
    same = {**base, "goal": "换个说法", "conversation_id": "c-1", "async_run": True}
    assert workflows.fingerprint(base) == workflows.fingerprint(same)

    changed = {**base, "own_specs": {"容量": "500ml"}}
    assert workflows.fingerprint(base) != workflows.fingerprint(changed)


def test_can_reuse_requires_matching_fingerprint_and_version():
    payload = body()
    good = workflows.fingerprint(payload)

    ok, _ = workflows.can_reuse(
        stored_fingerprint=good,
        stored_version=workflows.WORKFLOW_VERSION,
        payload=payload,
    )
    assert ok is True

    bad_input, reason = workflows.can_reuse(
        stored_fingerprint=good,
        stored_version=workflows.WORKFLOW_VERSION,
        payload={**payload, "own_key_features": ["改了卖点"]},
    )
    assert bad_input is False
    assert "输入" in reason

    bad_version, reason = workflows.can_reuse(
        stored_fingerprint=good, stored_version="2000-01-01.1", payload=payload
    )
    assert bad_version is False
    assert "版本" in reason

    missing, reason = workflows.can_reuse(
        stored_fingerprint=None, stored_version=None, payload=payload
    )
    assert missing is False  # 历史任务：宁可重算


def test_retry_with_new_specs_does_not_reuse_old_outputs(client):
    """补了资料再重试：指纹变了，不复用旧中间结果。"""
    headers = register(client, "ck_retry_over")
    # 先造一条"缺事实"的待补充任务
    no_facts = body(competitors=FEW_COMPETITORS, own_specs={}, own_key_features=[])
    resp = client.post("/api/agent/combined/runs", json=no_facts, headers=headers)
    assert resp.status_code == 422
    tasks = client.get("/api/tasks", headers=headers).json()["items"]
    waiting = next(t for t in tasks if t["status"] == "waiting_for_input")

    # 带上资料重试
    retry = client.post(
        f"/api/tasks/{waiting['task_id']}/retry",
        json={"overrides": {"own_specs": {"容量": "750ml"}}},
        headers=headers,
    )
    assert retry.status_code == 200, retry.text
    result = retry.json()
    assert result["resumed_steps"] == []
    assert result["reuse_skipped_reason"]


def test_retry_rejects_unknown_override_fields(client):
    headers = register(client, "ck_retry_bad")
    # 先造一条失败任务，才有东西可重试
    resp = client.post(
        "/api/agent/combined/runs",
        json=body(competitors=FEW_COMPETITORS, own_specs={}, own_key_features=[]),
        headers=headers,
    )
    assert resp.status_code == 422
    tasks = client.get("/api/tasks", headers=headers).json()["items"]
    task_id = next(t["task_id"] for t in tasks if t["status"] == "waiting_for_input")

    resp = client.post(
        f"/api/tasks/{task_id}/retry",
        json={"overrides": {"product_name": "换商品"}},
        headers=headers,
    )
    assert resp.status_code == 422  # 换商品应新建任务，不许改题


# ---------------------------------------------------------------------------
# 3. 幂等：重试不重复写入产物
# ---------------------------------------------------------------------------


def test_retry_does_not_duplicate_artifacts(client):
    headers = register(client, "ck_idem")
    first = client.post("/api/agent/combined/runs", json=body(), headers=headers).json()
    assert first["status"] == "succeeded"

    detail = client.get(f"/api/tasks/{first['task_id']}", headers=headers).json()
    report_id = detail["result"]["report_id"]
    listing_id = detail["result"]["listing_id"]

    reports_before = client.get("/api/reports", headers=headers).json()["items"]
    listings_before = client.get("/api/listings", headers=headers).json()["items"]

    # 直接对同一个任务再落一次产物（等价于"重跑后重新保存"）
    from crosspilot.services.artifacts import save_run_artifacts

    db = client.app.state.db
    ident = client.get("/api/tenants/current", headers=headers).json()
    saved = save_run_artifacts(
        db,
        tenant_id=ident["tenant_id"],
        user_id=ident["user_id"],
        task_id=first["task_id"],
        report={"report_id": "brand-new-report", "product_name": "同一任务"},
        listing={"listing_id": "brand-new-listing", "product_name": "同一任务"},
    )

    # 沿用原 id，而不是插一条新的
    assert saved["report_id"] == report_id
    assert saved["listing_id"] == listing_id
    assert len(client.get("/api/reports", headers=headers).json()["items"]) == len(
        reports_before
    )
    assert len(client.get("/api/listings", headers=headers).json()["items"]) == len(
        listings_before
    )


# ---------------------------------------------------------------------------
# 4. 超时
# ---------------------------------------------------------------------------


def test_step_timeout_is_enforced_at_node_boundary():
    from crosspilot.agent.contracts import SkillTimeout
    from crosspilot.agent.steps import StepRunner

    runner = StepRunner()
    token = steps_mod.begin_deadline(0.001)
    try:
        import time

        time.sleep(0.01)
        with pytest.raises(SkillTimeout):
            runner.run("any", "会被超时拦下", lambda: "never")
    finally:
        steps_mod.end_deadline(token)


def test_timeout_maps_to_retryable_504():
    from crosspilot.agent import errors as agent_errors
    from crosspilot.agent.contracts import SkillTimeout

    info = agent_errors.classify(SkillTimeout("工作流执行超时"))
    assert info.http_status == 504
    assert info.retryable is True


# ---------------------------------------------------------------------------
# 5. 取消后状态最终一致
# ---------------------------------------------------------------------------


def test_cancelled_paused_task_cleans_checkpoint(client):
    headers = register(client, "ck_cancel")
    out = client.post(
        "/api/agent/combined/runs", json=body(competitors=FEW_COMPETITORS), headers=headers
    ).json()
    assert out["status"] == "waiting_for_review"

    cancel = client.post(f"/api/tasks/{out['task_id']}/cancel", json={}, headers=headers)
    assert cancel.status_code == 200, cancel.text

    detail = client.get(f"/api/tasks/{out['task_id']}", headers=headers).json()
    assert detail["task"]["status"] == "cancelled"
    assert detail["task"]["finished_at"]

    # 取消之后不能还能被"确认唤醒"
    again = client.post(
        f"/api/tasks/{out['task_id']}/confirm",
        json={
            "decision": "continue",
            "confirmation_token": out["pending"]["confirmation_token"],
        },
        headers=headers,
    )
    assert again.status_code == 409


def test_confirm_after_checkpoint_loss_reports_clearly(client):
    """checkpoint 被清掉后确认要给明确 409，不是 500 也不是静默重跑。"""
    headers = register(client, "ck_lost")
    out = client.post(
        "/api/agent/combined/runs", json=body(competitors=FEW_COMPETITORS), headers=headers
    ).json()
    assert out["status"] == "waiting_for_review"

    tenant_id = client.get("/api/tenants/current", headers=headers).json()["tenant_id"]
    checkpoint_mod.cleanup_thread(tenant_id, out["task_id"])

    resp = client.post(
        f"/api/tasks/{out['task_id']}/confirm",
        json={
            "decision": "continue",
            "confirmation_token": out["pending"]["confirmation_token"],
        },
        headers=headers,
    )
    assert resp.status_code == 409
    assert "已失效" in resp.text
