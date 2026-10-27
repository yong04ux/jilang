"""Skill 契约与统一执行入口（Phase 1）测试。

覆盖计划 §11 Phase 1 的三条验收口径：

1. 至少一个简单技能与一个复杂技能通过**统一入口**执行；
2. 无执行器的技能**不会被误认为可运行**；
3. 迁移期间旧调用方（``/api/agent/runs``）仍可工作。

全部走确定性路径：分析是规则引擎，不需要真实模型。
"""

from __future__ import annotations

import time

import pytest

from crosspilot.agent import definitions
from crosspilot.agent import dispatcher as skill_dispatcher
from crosspilot.agent.contracts import (
    SkillContext,
    SkillDependencyMissing,
    SkillNotExecutable,
    SkillTimeout,
)
from crosspilot.agent.dispatcher import _run_with_timeout
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def analysis_params(**overrides) -> dict:
    payload = {
        "product_name": "EcoSip Insulated Water Bottle",
        "platform": "amazon",
        "marketplace": "US",
        "own_specs": {"容量": "750ml", "材质": "304 不锈钢"},
        "own_key_features": ["双层真空保温"],
        "own_price": 22.9,
        "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
        "keywords": [],
        "data_source": "demo",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 契约层：注册成功 ≠ 可以执行
# ---------------------------------------------------------------------------


def test_every_definition_is_explicit_about_executor():
    """每个技能都必须能回答"有没有执行器"，不能靠调用方去猜。"""
    for definition in definitions.SKILL_DEFINITIONS:
        assert definition.executor_type in {"function", "graph"}
        assert definition.timeout_seconds > 0
        assert definition.status in {"available", "beta", "dev", "disabled"}
        # executable 必须由「已启用 + 有执行器」派生，不允许自相矛盾
        assert definition.executable == (
            definition.enabled and definition.executor is not None
        )


def test_unimplemented_skill_is_marked_not_executable():
    definition = definitions.get_definition("keyword_layout")
    assert definition is not None
    assert definition.enabled is True  # 没有停用，只是没实现
    assert definition.executable is False
    assert definition.note  # 必须给出面向用户的说明


def test_simple_and_complex_skills_are_both_executable():
    """Phase 1 验收：一个简单技能 + 一个复杂技能都通过统一入口。"""
    keys = {item.key for item in definitions.executable_definitions()}
    assert {"market_summary", "competitor_analysis"} <= keys


def test_registry_derives_from_definitions():
    """注册表不再是手写清单，避免与代码里的能力对不上。"""
    from crosspilot.agent import registry

    assert [row["key"] for row in registry.SKILLS] == [
        item.key for item in definitions.SKILL_DEFINITIONS
    ]


# ---------------------------------------------------------------------------
# 执行入口
# ---------------------------------------------------------------------------


def test_analysis_then_summary_through_dispatcher():
    """复杂技能 → 简单技能串起来跑，两次都不碰网络。"""
    from crosspilot.llm.providers import RuleProvider

    # Provider 必须显式传入：缺了就是缺依赖，dispatcher 不会偷偷换成规则引擎
    ctx = SkillContext(provider=RuleProvider(), timeout_seconds=30)

    analysis = skill_dispatcher.dispatch("competitor_analysis", analysis_params(), ctx=ctx)
    assert analysis.status == "succeeded"
    # Phase 4 起分析走子图，结果里带 report / summary / checks / outcome
    report = analysis.result["report"]
    assert report["product_name"] == "EcoSip Insulated Water Bottle"
    assert report["data_provenance"]["competitor_count"] >= 1
    assert analysis.result["outcome"] in {"succeeded", "partial"}
    # 来源标记必须随结果走，不能被吞掉
    assert analysis.provenance["data_source"] == "demo"
    assert analysis.provenance["is_demo"] is True
    assert analysis.provenance["provider"] == "rule"

    summary = skill_dispatcher.dispatch("market_summary", {"report": report}, ctx=ctx)
    assert summary.status == "succeeded"
    assert summary.result["points"]
    # 确定性归纳：不产生任何新数字
    assert summary.quality is None  # 不是草稿，没有质检块，不伪造空壳


def test_provider_is_not_silently_substituted():
    """缺 Provider 就报缺依赖，不允许悄悄换成规则引擎（计划 §2.3-8）。"""
    ctx = SkillContext(timeout_seconds=30)
    with pytest.raises(SkillDependencyMissing) as exc:
        skill_dispatcher.dispatch("competitor_analysis", analysis_params(), ctx=ctx)
    assert "provider" in exc.value.detail.get("missing", [])


def test_listing_skill_requires_a_real_model():
    """声明了需要模型就必须真的能调模型；规则引擎不算满足。"""
    from crosspilot.llm.providers import RuleProvider

    ctx = SkillContext(provider=RuleProvider(), timeout_seconds=30)
    with pytest.raises(SkillDependencyMissing) as exc:
        skill_dispatcher.dispatch(
            "listing_generation",
            {"product": {"name": "EcoSip 保温杯", "marketplace": "US"}},
            ctx=ctx,
        )
    assert exc.value.status_code == 409
    assert "llm" in exc.value.detail.get("missing", [])


def test_missing_executor_is_rejected_before_validation():
    """检查顺序：有元数据没执行器时，先报"不可执行"，不要先报参数错。"""
    ctx = SkillContext(timeout_seconds=30)
    with pytest.raises(SkillNotExecutable) as exc:
        skill_dispatcher.dispatch("keyword_layout", {}, ctx=ctx)
    assert exc.value.status_code == 409
    assert exc.value.code == "skill_not_executable"


def test_unknown_skill_is_404_not_500():
    from crosspilot.agent.contracts import SkillNotFound

    ctx = SkillContext(timeout_seconds=30)
    with pytest.raises(SkillNotFound) as exc:
        skill_dispatcher.dispatch("does_not_exist", {}, ctx=ctx)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 超时守卫
# ---------------------------------------------------------------------------


def test_timeout_guard_raises_skill_timeout():
    def slow() -> str:
        time.sleep(1.5)
        return "never seen"

    with pytest.raises(SkillTimeout) as exc:
        _run_with_timeout(slow, 0.1)
    assert exc.value.status_code == 504


def test_timeout_guard_returns_fast_result():
    assert _run_with_timeout(lambda: 42, 5) == 42


# ---------------------------------------------------------------------------
# HTTP 层
# ---------------------------------------------------------------------------


def test_skill_list_exposes_executable_flag(client):
    headers = register(client, "skill_list")
    items = client.get("/api/skills", headers=headers).json()["items"]
    by_key = {item["skill_key"]: item for item in items}

    assert by_key["competitor_analysis"]["executable"] is True
    assert by_key["keyword_layout"]["executable"] is False
    # 旧字段必须保留，前端和既有测试都靠它们
    for item in items:
        assert item["name"] and item["version"]
        assert item["input_schema"]["type"] == "object"


def test_skill_detail_marks_note_for_unimplemented(client):
    headers = register(client, "skill_detail")
    detail = client.get("/api/skills/keyword_layout", headers=headers).json()
    assert detail["executable"] is False
    assert detail["note"]


def test_run_endpoint_executes_competitor_analysis(client):
    headers = register(client, "skill_run_ok")
    resp = client.post(
        "/api/skills/competitor_analysis/run", json=analysis_params(), headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["skill_key"] == "competitor_analysis"
    assert body["skill_version"]
    # Phase 1 不落库：result_ref 明确为空，而不是编一个 id
    assert body["result_ref"] is None
    assert body["task_id"] is None


def test_run_endpoint_rejects_missing_competitors(client):
    headers = register(client, "skill_run_422")
    params = analysis_params()
    params.pop("competitors")
    resp = client.post("/api/skills/competitor_analysis/run", json=params, headers=headers)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "skill_input_invalid"
    # 扁平化：errors 在顶层，前端才能直接取字段名（见 js/api.js 的 describe）
    assert any(e["field"] == "competitors" for e in detail["errors"])


def test_run_endpoint_reports_missing_executor(client):
    headers = register(client, "skill_run_409")
    resp = client.post("/api/skills/keyword_layout/run", json={}, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "skill_not_executable"


def test_run_endpoint_requires_write_role(client):
    """只读成员不能跑技能（技能会消耗模型额度）。"""
    owner = register(client, "skill_owner")
    register(client, "skill_reader")
    owner_tenant = client.get("/api/tenants/current", headers=owner).json()["tenant_id"]
    client.post(
        "/api/tenants/members",
        json={"username": "skill_reader", "role": "viewer"},
        headers=owner,
    )
    reader = client.post(
        "/api/auth/login",
        json={"username": "skill_reader", "password": "password123"},
    ).json()
    read_headers = {
        "Authorization": f"Bearer {reader['token']}",
        "X-Tenant-Id": owner_tenant,
    }
    resp = client.post(
        "/api/skills/competitor_analysis/run",
        json=analysis_params(),
        headers=read_headers,
    )
    assert resp.status_code == 403


def test_legacy_agent_run_still_works(client):
    """迁移期间旧入口不能被破坏（计划 §11 Phase 1 验收）。"""
    from crosspilot.agent.planner import plan_for

    headers = register(client, "skill_legacy")
    payload = analysis_params()
    payload.update({"agent_key": "main", "with_listing": False})
    resp = client.post("/api/agent/runs", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    # Phase 5 起计划来自分派结果，不再是一张固定主图
    assert body["plan"] == plan_for(False)
