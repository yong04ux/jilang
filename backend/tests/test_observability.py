"""Phase 7：可观测性测试（执行链追踪、模型调用遥测、敏感信息）。

覆盖计划 §11 Phase 7 的验收：
- 可从任务 ID 追踪执行链；
- 能定位失败节点与错误类型；
- 遥测只记元数据，不含 prompt / 响应正文，不含凭据。
"""

from __future__ import annotations

import json

import pytest

from crosspilot.agent.steps import StepRunner
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST
from crosspilot.llm import telemetry


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
        "own_specs": {"容量": "750ml"},
        "own_key_features": ["双层真空保温"],
        "own_price": 22.9,
        "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
        "data_source": "demo",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 执行链追踪
# ---------------------------------------------------------------------------


def test_trace_reconstructs_execution_chain(client):
    headers = register(client, "obs_chain")
    run = client.post("/api/agent/combined/runs", json=body(), headers=headers).json()
    assert run["status"] == "succeeded"

    resp = client.get(f"/api/tasks/{run['task_id']}/trace", headers=headers)
    assert resp.status_code == 200, resp.text
    trace = resp.json()

    assert trace["task"]["task_id"] == run["task_id"]
    assert trace["task"]["trace_id"]
    nodes = [step["node"] for step in trace["chain"]]
    assert nodes[0] == "validate"
    assert nodes[-1] == "finalize"
    # 顺序稳定、耗时齐全
    seqs = [step["seq"] for step in trace["chain"]]
    assert seqs == sorted(seqs)
    assert all(step["duration_ms"] is not None for step in trace["chain"])

    assert trace["totals"]["steps"] == len(trace["chain"])
    assert trace["totals"]["failed_node"] == ""
    assert trace["error"] is None


def test_trace_points_at_failed_node(client, monkeypatch):
    """能定位失败节点与错误类型——排查时最需要的两件事。

    注意：组合工作流把竞品子图当成自己的一步来跑（Phase 5 的决定），
    所以失败节点记在**外层步骤** ``run_analysis`` 上，而不是子图内部的
    ``analyze_market``。时间线因此是"粗一档"的，但不会出现两套重复步骤。
    """

    def boom(*args, **kwargs):
        raise RuntimeError("统计炸了")

    monkeypatch.setattr("crosspilot.engine.analysis.run_analysis", boom)
    headers = register(client, "obs_fail")
    resp = client.post("/api/agent/runs", json=body(), headers=headers)
    assert resp.status_code >= 500

    tasks = client.get("/api/tasks", headers=headers).json()["items"]
    failed = next(t for t in tasks if t["status"] == "failed")

    trace = client.get(f"/api/tasks/{failed['task_id']}/trace", headers=headers).json()
    assert trace["totals"]["failed_node"] == "run_analysis"
    assert trace["error"]["code"]
    assert trace["error"]["is_failed_step"] is True
    failed_steps = [s for s in trace["chain"] if s["is_failed"]]
    assert len(failed_steps) == 1
    # 步骤描述是面向用户的文案，不暴露异常类名
    assert "RuntimeError" not in (failed_steps[0]["detail"] or "")


def test_trace_is_tenant_scoped(client):
    alice = register(client, "obs_alice")
    bob = register(client, "obs_bob")
    run = client.post("/api/agent/combined/runs", json=body(), headers=alice).json()

    resp = client.get(f"/api/tasks/{run['task_id']}/trace", headers=bob)
    assert resp.status_code == 404  # 不泄露任务是否存在


# ---------------------------------------------------------------------------
# 模型调用遥测
# ---------------------------------------------------------------------------


def test_telemetry_collects_and_summarizes():
    with telemetry.scope("generate_listing"):
        telemetry.record(
            provider="deepseek",
            model="deepseek-flash",
            started=0.0,
            prompt_tokens=120,
            completion_tokens=80,
            attempts=2,
        )
        telemetry.record(
            provider="deepseek",
            model="deepseek-flash",
            started=0.0,
            attempts=3,
            ok=False,
            error_code="rate_limit",
        )
        records = telemetry.drain()

    assert [r.node for r in records] == ["generate_listing", "generate_listing"]
    summary = telemetry.summarize(records)
    assert summary["calls"] == 2
    assert summary["attempts"] == 5  # 重试次数是真实发起的请求数
    assert summary["tokens"] == 200
    assert summary["failures"] == 1


def test_telemetry_outside_scope_is_noop():
    telemetry.record(provider="x", model="y", started=0.0)
    assert telemetry.drain() == []


def test_call_record_has_no_text_fields():
    """结构性保证：遥测**不存** prompt / 响应正文。

    正文里可能有租户的商品资料，落库即扩散。这条断言把"只记元数据"
    钉成契约，避免以后有人顺手加一个 ``content`` 字段。
    """
    fields = set(telemetry.CallRecord().as_dict())
    forbidden = {"content", "prompt", "response", "messages", "completion_text"}
    assert not (fields & forbidden)
    assert fields == {
        "node",
        "provider",
        "model",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "attempts",
        "ok",
        "error_code",
    }


def test_step_runner_persists_llm_calls(client):
    """步骤里发生的模型调用会落到 llm_calls，并能从 trace 读回来。"""
    from crosspilot.agent.runtime import create_agent_task

    headers = register(client, "obs_calls")
    ident = client.get("/api/tenants/current", headers=headers).json()
    db = client.app.state.db

    recorder = create_agent_task(
        db=db,
        user_id=ident["user_id"],
        tenant_id=ident["tenant_id"],
        payload=body(),
        title="遥测落库",
    )

    runner = StepRunner(task=recorder, labels={"fake": "假模型步骤"})

    def fake_call() -> str:
        with telemetry.scope("generate_listing"):
            telemetry.record(
                provider="deepseek",
                model="deepseek-flash",
                started=0.0,
                prompt_tokens=50,
                completion_tokens=30,
                attempts=1,
            )
        return "ok"

    runner.run("fake", "调用一次模型", fake_call)
    recorder.succeed(output={"plan": []})

    rows = db.list_llm_calls(recorder.task_id, ident["tenant_id"])
    assert len(rows) == 1
    assert rows[0]["provider"] == "deepseek"
    assert rows[0]["prompt_tokens"] == 50
    # 节点名由**最外层**（即 StepRunner 记的那个步骤）决定：
    # 内层再开 scope 不会改名，否则这次调用在时间线上会挂到不存在的步骤上
    assert rows[0]["node"] == "fake"

    trace = client.get(f"/api/tasks/{recorder.task_id}/trace", headers=headers).json()
    assert trace["totals"]["llm_calls"] == 1
    assert trace["totals"]["tokens"] == 80
    step = next(s for s in trace["chain"] if s["node"] == "fake")
    assert step["llm_calls"][0]["model"] == "deepseek-flash"


def test_client_chat_records_attempts_without_text(client):
    """底层 ``chat()`` 的埋点：成功一次记 1 次尝试，且不落任何文本。"""
    from crosspilot.llm.llm import DeepSeekClient

    llm = DeepSeekClient(api_key="sk-test", model="deepseek-flash", max_retries=0)

    class _FakeCompletions:
        def create(self, **kwargs):
            class _Msg:
                content = "hello"

            class _Choice:
                message = _Msg()
                finish_reason = "stop"

            class _Usage:
                prompt_tokens = 7
                completion_tokens = 3

            class _Resp:
                choices = [_Choice()]
                usage = _Usage()
                model = "deepseek-flash"

            return _Resp()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeSdk:
        chat = _FakeChat()

    llm._client = _FakeSdk()

    with telemetry.scope("generate_listing"):
        llm.chat([{"role": "user", "content": "hi"}])
        records = telemetry.drain()

    assert len(records) == 1
    assert records[0].attempts == 1
    assert records[0].prompt_tokens == 7
    assert records[0].completion_tokens == 3
    # 记录里没有任何正文
    assert "hi" not in json.dumps(records[0].as_dict(), ensure_ascii=False)
    assert "hello" not in json.dumps(records[0].as_dict(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# 敏感信息
# ---------------------------------------------------------------------------


def test_trace_never_exposes_credentials(client):
    """执行链里不该出现任何凭据。"""
    headers = register(client, "obs_secret")
    run = client.post("/api/agent/combined/runs", json=body(), headers=headers).json()
    raw = client.get(f"/api/tasks/{run['task_id']}/trace", headers=headers).text
    for marker in ("sk-", "api_key", "Authorization", "Bearer "):
        assert marker not in raw


def test_scrub_masks_keys_in_audit_detail():
    from crosspilot.engine.scrubbing import scrub

    cleaned = scrub(
        {
            "api_key": "sk-abcdef1234567890",
            "note": "调用时用了 sk-abcdef1234567890 这个 key",
            "nested": [{"token": "secret-value"}],
        }
    )
    dumped = json.dumps(cleaned, ensure_ascii=False)
    assert "sk-abcdef1234567890" not in dumped
    assert "secret-value" not in dumped
