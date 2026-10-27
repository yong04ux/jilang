"""Listing 生成子图（Phase 3）测试。

覆盖计划 §11 Phase 3 的验收：
1. Listing 可独立运行；
2. 不会自行编造缺失的产品参数（没事实就停，不是硬写）；
3. 质量失败后只做有限修订；
4. 重试不重复创建草稿；
5. 旧 API 核心行为通过回归。
"""

from __future__ import annotations

from crosspilot.agent.definitions import ListingGenerationInput
from crosspilot.agent.graphs.listing_generation import run_listing_graph
from crosspilot.agent.state import (
    OUTCOME_NEEDS_INPUT,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_SUCCEEDED,
)
from crosspilot.llm.providers import RuleProvider
from crosspilot.models import QualityCheck
from crosspilot.services import listing_facts


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def request_payload(**overrides) -> dict:
    """一个"资料够用"的商品：有属性、有卖点，因此不该被拦。"""
    payload = {
        "product": {
            "name": "EcoSip Insulated Water Bottle",
            "brand": "EcoSip",
            "marketplace": "US",
            "specifications": {"容量": "750ml", "材质": "304 不锈钢"},
            "key_features": ["双层真空保温", "防漏杯盖"],
        },
        "language": "en-US",
        "marketplace": "US",
        "data_source": "demo",
    }
    payload.update(overrides)
    return payload


class FlakyModelProvider:
    """前 N 次返回"质检不通过"的草稿，之后返回通过的。

    内部仍用规则引擎产出真实草稿，只是改写质检块——
    这样不触网也能验证"修订循环"这条分支。
    """

    name = "fake-model"

    def __init__(self, fail_times: int = 1) -> None:
        self.inner = RuleProvider()
        self.fail_times = fail_times
        self.calls: list[list[str]] = []

    def chat_client(self):
        return object()  # 非 None 即"有可用模型"

    def generate(self, request, report_payload=None):
        self.calls.append(list(getattr(request, "revision_notes", []) or []))
        draft = self.inner.generate(request, report_payload)
        if len(self.calls) <= self.fail_times:
            return draft.model_copy(
                update={
                    "quality_check": QualityCheck(
                        passed=False,
                        issues=[
                            {
                                "code": "over_length",
                                "severity": "error",
                                "message": "标题超过站点上限",
                            }
                        ],
                    )
                }
            )
        return draft.model_copy(
            update={"quality_check": QualityCheck(passed=True, issues=[])}
        )


# ---------------------------------------------------------------------------
# 事实判定（确定性，不涉及模型）
# ---------------------------------------------------------------------------


def test_no_facts_blocks_generation():
    facts = listing_facts.resolve_product_facts({"name": "只有名字的杯子"})
    verdict = listing_facts.check_required_facts(facts)

    assert verdict["blocking"] is True
    assert verdict["can_generate"] is False
    assert verdict["reason"]


def test_partial_missing_attributes_do_not_block():
    """有容量没颜色不该把任务停掉：缺的项进提示，不是拦路。"""
    facts = listing_facts.resolve_product_facts(request_payload()["product"])
    verdict = listing_facts.check_required_facts(facts)

    assert verdict["can_generate"] is True
    assert verdict["blocking"] is False
    # 颜色/尺寸等确实没给，仍然要如实列出来
    assert verdict["missing_labels"]


def test_brand_rules_expose_real_limits():
    rules = listing_facts.load_brand_rules("US", ["最好", "第一"])
    assert rules["marketplace"] == "US"
    assert rules["title_max_chars"] > 0
    assert rules["banned_term_count"] >= 0


def test_market_insights_are_optional_and_never_invented():
    empty = listing_facts.load_market_insights(None)
    assert empty["differentiation"] == []
    assert empty["notes"]  # 要说清"没有竞品分析"，而不是静默空

    with_report = listing_facts.load_market_insights(
        {"report_id": "r1", "differentiation_opportunities": [{"angle": "静音开合"}]}
    )
    assert with_report["differentiation"] == ["静音开合"]
    assert with_report["report_id"] == "r1"


# ---------------------------------------------------------------------------
# 子图：缺事实时停下，不编造
# ---------------------------------------------------------------------------


def test_subgraph_stops_at_needs_input():
    result = run_listing_graph(
        {"request": {"product": {"name": "只有名字的杯子"}}},
        provider=RuleProvider(),
    )
    assert result["outcome"] == OUTCOME_NEEDS_INPUT
    assert "listing" not in result or not result.get("listing")
    assert result["artifact"]["missing"] is not None


def test_subgraph_generates_when_facts_are_enough():
    result = run_listing_graph(
        {"request": request_payload()}, provider=RuleProvider()
    )
    assert result["outcome"] in {OUTCOME_SUCCEEDED, OUTCOME_NEEDS_REVIEW}
    listing = result["listing"]
    assert listing["title"]
    # 事实快照必须留着，否则后续版本复检会失效
    assert listing["product_snapshot"]["name"]


# ---------------------------------------------------------------------------
# 有限修订
# ---------------------------------------------------------------------------


def test_revision_is_attempted_once_then_stops():
    """规则引擎的草稿质检不通过；有模型时会带问题重跑一次，然后停下。"""
    provider = FlakyModelProvider(fail_times=2)  # 两次都不通过
    result = run_listing_graph(
        {"request": request_payload()},
        provider=provider,
        max_revisions=1,
    )

    assert len(provider.calls) == 2  # 首次 + 修订一次
    assert provider.calls[0] == []  # 首次没有修订约束
    assert provider.calls[1]  # 修订时带上了具体问题
    assert result["outcome"] == OUTCOME_NEEDS_REVIEW
    assert result["revision"] == 1


def test_revision_recovers_and_succeeds():
    provider = FlakyModelProvider(fail_times=1)
    result = run_listing_graph(
        {"request": request_payload()},
        provider=provider,
        max_revisions=1,
    )
    assert len(provider.calls) == 2
    assert result["outcome"] == OUTCOME_SUCCEEDED
    assert result["quality"]["passed"] is True


def test_no_revision_without_a_model():
    """没有可调用模型就不假装修订：直接进人工复核。"""
    provider = RuleProvider()  # chat_client() 返回 None
    result = run_listing_graph({"request": request_payload()}, provider=provider)

    assert result["outcome"] == OUTCOME_NEEDS_REVIEW
    assert result["revision"] == 0
    assert "没有可用模型" in result["message"]


# ---------------------------------------------------------------------------
# 落库幂等
# ---------------------------------------------------------------------------


def test_persist_is_idempotent_per_task(temp_settings):
    from crosspilot.persistence.db import Database

    db = Database(temp_settings.database_url)
    db.create_user("u-idem", "idem_user", "hash")
    # 只有通过质检才会落库（计划 §6.2 的 passed -> persist_draft），
    # 所以这里用一个"首次就通过"的 Provider，专门验幂等而不是质检分支。
    provider = FlakyModelProvider(fail_times=0)

    first = run_listing_graph(
        {"request": request_payload(), "task_id": "task-1", "persist": True},
        provider=provider,
        db=db,
        tenant_id="tenant-idem",
        user_id="u-idem",
        persist=True,
    )
    first_id = first["artifact"]["listing_id"]
    assert first_id

    second = run_listing_graph(
        {"request": request_payload(), "task_id": "task-1", "persist": True},
        provider=provider,
        db=db,
        tenant_id="tenant-idem",
        user_id="u-idem",
        persist=True,
    )
    # 同一任务再跑一次不该产生第二份草稿
    assert second["artifact"]["listing_id"] == first_id

    with db.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS n FROM listing_drafts WHERE task_id = ?", ("task-1",)
        ).fetchone()["n"]
    assert count == 1


# ---------------------------------------------------------------------------
# 接回主图与旧 API
# ---------------------------------------------------------------------------


def test_agent_run_stops_at_waiting_input_when_facts_missing(client):
    headers = register(client, "graph_input")
    resp = client.post(
        "/api/agent/runs",
        json={
            "agent_key": "main",
            "product_name": "只有名字的杯子",
            "competitors": [{"name": "Rival", "price": 19.9}],
            "with_listing": True,
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["category"] == "missing_input"
    assert detail["code"] == "product_facts_missing"

    tasks = client.get("/api/tasks", headers=headers).json()["items"]
    waiting = [t for t in tasks if t["status"] == "waiting_for_input"]
    assert waiting, f"任务状态应落成等待补充资料，实际：{[t['status'] for t in tasks]}"
    # 不是失败：不该有错误码
    assert waiting[0]["error_code"] is None
    # 等待补充资料的任务可以重试
    retry = client.post(f"/api/tasks/{waiting[0]['task_id']}/retry", headers=headers)
    assert retry.status_code == 200, retry.text


def test_degraded_listing_still_succeeds(client):
    """回归：没有模型时草稿质检不通过是既有行为，不能把任务改成"待复核"。"""
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    headers = register(client, "graph_degraded")
    resp = client.post(
        "/api/agent/runs",
        json={
            "agent_key": "main",
            "product_name": "EcoSip Insulated Water Bottle",
            "marketplace": "US",
            "own_specs": {"容量": "750ml", "材质": "304 不锈钢"},
            "own_key_features": ["双层真空保温"],
            "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
            "with_listing": True,
            "data_source": "demo",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    # 质检结论如实保留（passed=False），只是没被升级成任务状态
    assert body["quality"]["passed"] is False


def test_listing_skill_contract_is_a_graph():
    from crosspilot.agent import definitions

    definition = definitions.get_definition("listing_generation")
    assert definition.executor_type == "graph"
    assert definition.executable is True
    # 输入契约仍可独立校验（对外承诺不变）
    assert ListingGenerationInput(**request_payload()).product.name
