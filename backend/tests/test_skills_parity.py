"""七个能力包成技能后，产出必须与既有产出**逐字段一致**。

这是整个 P0 最重要的一组断言。协议层只是外壳——一旦某个 executor 顺手
「优化」了算法，技能页出的数就会和分析页/工作台出的数不一样，而用户完全
看不出来哪个是对的。所以这里一律拿既有产出当基准逐字段比对。

不需要数据库：七个 executor 在被显式喂数据时都不触库。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from crosspilot.agent import skills as agent_skills
from crosspilot.agent import tools
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST, DEMO_LISTING_REQUEST
from crosspilot.engine.profit import ProfitRequest, calculate
from crosspilot.ingest import importers
from crosspilot.llm.providers import RuleProvider
from crosspilot.models import AnalysisReport, CompetitorAnalysisRequest, ListingDraft, ListingGenerationRequest
from crosspilot.services import listing_service
from crosspilot.skills import SKILL_REGISTRY
from crosspilot.skills.base import SkillContext

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

#: 每次运行都会重新生成的字段，不参与比对
VOLATILE = {"report_id", "listing_id", "created_at"}


def ctx(provider: Any = None) -> SkillContext:
    return SkillContext(
        db=None,
        user_id="u1",
        tenant_id="t1",
        provider=provider or RuleProvider(),
    )


def drop_volatile(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: drop_volatile(v) for k, v in payload.items() if k not in VOLATILE}
    if isinstance(payload, list):
        return [drop_volatile(item) for item in payload]
    return payload


def run(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    spec = SKILL_REGISTRY[key]
    inputs = spec.inputs.model_validate(payload)
    return spec.executor(ctx(), inputs)


# ---------------------------------------------------------------------------
# 1. 竞品分析
# ---------------------------------------------------------------------------


def test_competitor_analysis_matches_legacy_path():
    expected = (
        RuleProvider()
        .analyze(CompetitorAnalysisRequest(**DEMO_ANALYSIS_REQUEST))
        .model_dump(mode="json")
    )
    assert drop_volatile(run("competitor_analysis", DEMO_ANALYSIS_REQUEST)) == drop_volatile(
        expected
    )


def test_competitor_analysis_requires_a_source():
    spec = SKILL_REGISTRY["competitor_analysis"]
    with pytest.raises(Exception):
        spec.inputs.model_validate({"product_name": "杯子", "competitors": []})


# ---------------------------------------------------------------------------
# 2/3. 评论挖掘与市场总结（都读报告，不重算）
# ---------------------------------------------------------------------------


def _report_payload() -> dict[str, Any]:
    report = RuleProvider().analyze(CompetitorAnalysisRequest(**DEMO_ANALYSIS_REQUEST))
    return report.model_dump(mode="json")


def test_review_mining_matches_legacy_path():
    payload = _report_payload()
    expected = agent_skills.mine_reviews(AnalysisReport(**payload))
    assert run("review_mining", {"report": payload}) == expected


def test_market_summary_matches_legacy_path():
    payload = _report_payload()
    expected = agent_skills.market_summary(AnalysisReport(**payload))
    assert run("market_summary", {"report": payload}) == expected


# ---------------------------------------------------------------------------
# 4. Listing 生成
# ---------------------------------------------------------------------------


def test_listing_generation_matches_legacy_path():
    request = ListingGenerationRequest(**DEMO_LISTING_REQUEST)
    legacy = listing_service.dump_for_storage(
        tools.generate_listing(RuleProvider(), request, None), request
    )
    assert drop_volatile(run("listing_generation", DEMO_LISTING_REQUEST)) == drop_volatile(legacy)


def test_listing_generation_keeps_product_snapshot():
    """快照丢了会让「重新质检」直接报错，属于改造中最容易掉的一环。"""
    output = run("listing_generation", DEMO_LISTING_REQUEST)
    assert output["product_snapshot"]["name"] == DEMO_LISTING_REQUEST["product"]["name"]


# ---------------------------------------------------------------------------
# 5. Listing 质检
# ---------------------------------------------------------------------------


def test_listing_quality_matches_legacy_path():
    request = ListingGenerationRequest(**DEMO_LISTING_REQUEST)
    draft = listing_service.dump_for_storage(
        tools.generate_listing(RuleProvider(), request, None), request
    )
    expected = tools.run_quality_check(ListingDraft(**draft))
    assert run("listing_quality", {"listing": draft}) == expected


# ---------------------------------------------------------------------------
# 6. 数据校验
# ---------------------------------------------------------------------------


def _csv_base64() -> str:
    raw = (EXAMPLES / "competitors_sample.csv").read_bytes()
    return base64.b64encode(raw).decode("ascii")


def test_data_validation_matches_legacy_path():
    content = _csv_base64()
    raw = base64.b64decode(content)
    expected = importers.import_competitor_data(raw, "competitors_sample.csv")

    output = run(
        "data_validation",
        {"filename": "competitors_sample.csv", "content_base64": content},
    )

    assert output["ok"] == expected.ok
    assert output["total_rows"] == expected.total_rows
    assert output["valid_rows"] == len(expected.competitors)
    assert output["source_format"] == expected.source_format
    assert len(output["errors"]) == min(len(expected.errors), 50)
    # 落库用的完整结果留在内部字段里，出接口前会被剥掉
    assert output["_batch"]["competitors"] == [
        c.model_dump(mode="json") for c in expected.competitors
    ]


def test_data_validation_rejects_broken_file_content():
    with pytest.raises(Exception):
        run("data_validation", {"filename": "x.csv", "content_base64": "not base64!!"})


# ---------------------------------------------------------------------------
# 7. 成本与利润测算
# ---------------------------------------------------------------------------


def test_profit_calc_matches_legacy_path():
    payload = {
        "product_name": "EcoSip 保温杯",
        "marketplace": "US",
        "selling_price": 22.9,
        "purchase_cost": 6.4,
        "shipping_cost": 2.1,
        "fulfillment_fee": 3.2,
        "commission_rate": 0.15,
        "target_margin": 0.25,
    }
    expected = calculate(ProfitRequest(**payload)).model_dump(mode="json")
    assert run("profit_calc", payload) == expected
