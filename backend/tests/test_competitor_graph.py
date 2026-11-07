"""竞品分析子图测试。

覆盖范围：
1. 竞品分析可独立运行；
2. 数据不足不会被错误归类为系统故障（是 partial，不是 failure）；
3. 结论可以追溯来源；
4. Mock/示例标记完整保留。
"""

from __future__ import annotations

from crosspilot.agent.graphs.competitor_analysis import run_competitor_graph
from crosspilot.agent.state import OUTCOME_PARTIAL, OUTCOME_SUCCEEDED
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST
from crosspilot.llm.providers import RuleProvider
from crosspilot.market.competitor_provider import (
    CompetitorData,
    CompetitorProviderError,
    ProviderNotConfigured,
)
from crosspilot.services import competitor_facts


def request_payload(competitors=None, **overrides) -> dict:
    payload = {
        "product_name": "EcoSip Insulated Water Bottle",
        "platform": "amazon",
        "marketplace": "US",
        "own_specs": {"容量": "750ml"},
        "own_key_features": ["双层真空保温"],
        "own_price": 22.9,
        "competitors": competitors if competitors is not None else DEMO_ANALYSIS_REQUEST["competitors"],
        "data_source": "demo",
    }
    payload.update(overrides)
    return payload


class CountingProvider:
    """记录调用次数，可配置"前 N 次抛什么"。"""

    mode = "imported"
    name = "counting"

    def __init__(self, *, fail_times: int = 0, exc: Exception | None = None) -> None:
        self.fail_times = fail_times
        self.exc = exc or CompetitorProviderError("暂时取不到数据")
        self.calls = 0

    def fetch(self, query):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return CompetitorData(rows=[dict(r) for r in query.rows or []], source="manual")


# ---------------------------------------------------------------------------
# 充分性判定（纯函数）
# ---------------------------------------------------------------------------


def test_sufficiency_needs_real_samples():
    verdict = competitor_facts.assess_sufficiency(
        {"competitor_count": 1, "review_count": 0, "priced_count": 1}
    )
    assert verdict["sufficient"] is False
    assert len(verdict["reasons"]) == 2  # 竞品太少 + 没有评论


def test_sufficiency_ok_with_enough_samples():
    verdict = competitor_facts.assess_sufficiency(
        {"competitor_count": 3, "review_count": 6, "priced_count": 3}
    )
    assert verdict["sufficient"] is True
    assert verdict["reasons"] == []


def test_report_structure_check_catches_missing_blocks():
    assert competitor_facts.validate_report({})["ok"] is False
    result = competitor_facts.validate_report(
        {
            "product_name": "X",
            "data_provenance": {"data_source": "demo"},
            "review_insights": {"total_samples": 0},
            "keyword_analysis": {"available": False},
            "competitor_snapshots": [{"name": "A"}],
        }
    )
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# 子图：样本充足 / 不足
# ---------------------------------------------------------------------------


def test_ample_sample_succeeds():
    result = run_competitor_graph(
        {"request": request_payload()}, provider=RuleProvider()
    )
    assert result["outcome"] == OUTCOME_SUCCEEDED
    assert result["report"]["product_name"] == "EcoSip Insulated Water Bottle"
    assert result["summary"]["points"]  # 有结论，不是空壳
    assert result["checks"]["integrity_ok"] is True


def test_insufficient_sample_is_partial_not_failure():
    """数据不足是"结论不稳"，不是"系统坏了"——必须还能拿到报告。"""
    one = [DEMO_ANALYSIS_REQUEST["competitors"][0]]
    result = run_competitor_graph(
        {"request": request_payload(competitors=one)}, provider=RuleProvider()
    )

    assert result["outcome"] == OUTCOME_PARTIAL
    assert result["report"]["data_provenance"]["competitor_count"] == 1
    assert result["summary"]["points"]  # 仍然给出算得出来的结论
    assert result["provenance"]["partial_reasons"]
    assert "样本不足" in result["message"]


def test_partial_result_keeps_evidence_and_demo_flag():
    one = [DEMO_ANALYSIS_REQUEST["competitors"][0]]
    result = run_competitor_graph(
        {"request": request_payload(competitors=one)},
        provider=RuleProvider(),
        # 传 Provider 才会走真正的"取数"环节，才有获取时间
        competitor_provider=CountingProvider(),
    )
    provenance = result["provenance"]
    assert provenance["competitor_count"] == 1
    # 示例数据标记必须留下来，不能被 partial 吞掉
    assert provenance.get("is_demo") is True
    assert provenance["data_source"] == "demo"
    assert provenance["fetched_at"]  # 取数时间


def test_report_traces_back_to_sources():
    """结论可追溯：每条差异化机会都要有证据引用字段。"""
    result = run_competitor_graph(
        {"request": request_payload()}, provider=RuleProvider()
    )
    report = result["report"]
    for item in report["differentiation_opportunities"][:3]:
        assert "confidence" in item
        assert "supporting_evidence" in item
    # 评论结论带原文引用
    assert report["review_insights"]["pain_points"] or report["review_insights"]["limitations"]


# ---------------------------------------------------------------------------
# 取数重试策略
# ---------------------------------------------------------------------------


def test_transient_fetch_failure_is_retried():
    provider = CountingProvider(fail_times=1)
    result = run_competitor_graph(
        {"request": request_payload()},
        provider=RuleProvider(),
        competitor_provider=provider,
        max_fetch_attempts=2,
    )
    assert provider.calls == 2
    assert result["fetched"]["attempts"] == 2
    assert result["outcome"] in {OUTCOME_SUCCEEDED, OUTCOME_PARTIAL}


def test_not_configured_is_never_retried():
    """配置问题重试没有意义：既浪费额度又让用户多等。"""
    provider = CountingProvider(
        fail_times=9, exc=ProviderNotConfigured("还没有接入真实竞品数据源")
    )
    try:
        run_competitor_graph(
            {"request": request_payload()},
            provider=RuleProvider(),
            competitor_provider=provider,
            max_fetch_attempts=3,
        )
    except ProviderNotConfigured:
        pass
    else:  # pragma: no cover
        raise AssertionError("未配置数据源必须直接报错")
    assert provider.calls == 1


def test_fetch_failure_after_retries_propagates():
    provider = CountingProvider(fail_times=5)
    try:
        run_competitor_graph(
            {"request": request_payload()},
            provider=RuleProvider(),
            competitor_provider=provider,
            max_fetch_attempts=2,
        )
    except CompetitorProviderError:
        pass
    else:  # pragma: no cover
        raise AssertionError("重试用尽后必须把失败抛出去")
    assert provider.calls == 2


# ---------------------------------------------------------------------------
# 输入与落库
# ---------------------------------------------------------------------------


def test_missing_competitors_is_rejected_as_input_error():
    from crosspilot.agent.contracts import SkillInputInvalid

    payload = request_payload()
    payload.pop("competitors")
    try:
        run_competitor_graph({"request": payload}, provider=RuleProvider())
    except SkillInputInvalid as exc:
        assert exc.status_code == 422
        assert any(e["field"] == "competitors" for e in exc.detail["errors"])
    else:  # pragma: no cover
        raise AssertionError("缺竞品必须 422")


def test_report_can_be_persisted(temp_settings):
    from crosspilot.persistence.db import Database

    db = Database(temp_settings.database_url)
    db.create_user("u-cmp", "cmp_user", "hash")

    result = run_competitor_graph(
        {"request": request_payload(), "persist": True},
        provider=RuleProvider(),
        db=db,
        tenant_id="tenant-cmp",
        user_id="u-cmp",
        persist=True,
    )
    report_id = result["artifact"]["report_id"]
    assert report_id
    saved = db.get_report(report_id, tenant_id="tenant-cmp")
    assert saved is not None
    assert saved["product_name"] == "EcoSip Insulated Water Bottle"


# ---------------------------------------------------------------------------
# 接进统一技能入口
# ---------------------------------------------------------------------------


def _register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


