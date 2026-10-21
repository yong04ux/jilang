"""竞品分析核心逻辑测试。"""

from __future__ import annotations

import pytest

from crosspilot.engine.analysis import (
    analyze_keywords,
    analyze_prices,
    normalize,
    run_analysis,
    validate_request,
)
from crosspilot.models import (
    CompetitorAnalysisRequest,
    CompetitorProduct,
    EvidenceKind,
    KeywordMetric,
    Platform,
    ReviewSample,
)


def _request(**overrides) -> CompetitorAnalysisRequest:
    base = {
        "product_name": "Test Bottle",
        "platform": Platform.AMAZON,
        "marketplace": "US",
        "own_specs": {"容量": "500ml"},
        "own_key_features": ["双层真空保温"],
        "own_price": 20.0,
        "competitors": [
            CompetitorProduct(
                name="Comp A",
                price=25.0,
                rating=4.2,
                review_count=100,
                key_features=["Leak-proof lid", "Dishwasher safe"],
                specifications={"容量": "600ml"},
                reviews=[
                    ReviewSample(rating=1, text="The lid leaked in my bag, very disappointed."),
                    ReviewSample(rating=5, text="Keeps water cold all day, great insulation."),
                    ReviewSample(rating=2, text="Cheap plastic lid cracked after a month."),
                ],
            )
        ],
        "keywords": [],
    }
    base.update(overrides)
    return CompetitorAnalysisRequest(**base)


def test_validate_request_reports_warnings_for_missing_fields():
    request = _request(
        competitors=[
            CompetitorProduct(name="No Data Comp", key_features=[], reviews=[])
        ],
        own_specs={},
    )
    outcome = validate_request(request)
    assert outcome.ok
    joined = " ".join(outcome.warnings)
    assert "缺少价格" in joined
    assert "评论样本" in joined
    assert "未填写规格" in joined


def test_validate_request_rejects_empty_competitors():
    with pytest.raises(Exception):
        CompetitorAnalysisRequest(product_name="x", competitors=[])


def test_normalize_deduplicates_keywords():
    request = _request(
        keywords=[
            KeywordMetric(keyword="bottle"),
            KeywordMetric(keyword="Bottle"),
            KeywordMetric(keyword="tumbler"),
        ]
    )
    data = normalize(request)
    assert [k.keyword for k in data.keywords] == ["bottle", "tumbler"]
    assert any("重复关键词" in w for w in data.warnings)


def test_run_analysis_produces_structured_report_with_evidence():
    report = run_analysis(_request())

    assert report.report_id
    assert report.data_provenance.competitor_count == 1
    assert report.data_provenance.review_sample_count == 3
    # 痛点命中应带回原文证据
    assert report.review_insights.pain_points, "应识别出评论痛点"
    leak = next(p for p in report.review_insights.pain_points if "渗漏" in p.label)
    assert leak.frequency >= 1
    assert leak.samples and leak.samples[0].quote
    assert "leaked" in leak.samples[0].quote.lower()
    # 统计类结论必须带 evidence
    assert all(
        claim.evidence
        for claim in [p.claim for p in report.review_insights.pain_points if p.claim]
        if claim.evidence_kind in (EvidenceKind.FACT, EvidenceKind.STATISTIC)
    )
    # 价格统计
    assert report.price_analysis is not None
    assert report.price_analysis.min_price == 25.0
    assert report.price_analysis.own_position == "below_range"


def test_analysis_does_not_invent_price_when_missing():
    request = _request(
        competitors=[CompetitorProduct(name="No Price", key_features=["x"], reviews=[])],
        own_price=None,
    )
    report = run_analysis(request)
    assert report.price_analysis.compared_count == 0
    assert report.price_analysis.min_price is None
    assert report.price_analysis.median_price is None
    assert report.price_analysis.own_position == "unknown"
    assert any("价格" in w for w in report.warnings)


def test_keywords_without_metrics_have_no_score_or_volume():
    keywords = [KeywordMetric(keyword="insulated bottle"), KeywordMetric(keyword="tumbler")]
    analysis = analyze_keywords(keywords, "Insulated Bottle")
    assert analysis.available is True
    assert analysis.with_metrics == 0
    for opportunity in analysis.opportunities:
        assert opportunity.has_metrics is False
        assert opportunity.opportunity_score is None
        assert opportunity.search_volume is None
        assert opportunity.rank is None
    assert any("不计算机会分" in note for note in analysis.notes)


def test_keywords_with_metrics_compute_score_without_fabricating_missing_fields():
    keywords = [
        KeywordMetric(keyword="a", search_volume=1000, rank=5),
        KeywordMetric(keyword="b", search_volume=None, rank=None, relevance=None),
    ]
    analysis = analyze_keywords(keywords, "bottle")
    scored = [o for o in analysis.opportunities if o.has_metrics]
    assert scored and scored[0].opportunity_score is not None
    unscored = [o for o in analysis.opportunities if not o.has_metrics]
    assert unscored and unscored[0].opportunity_score is None


def test_keyword_opportunity_cannot_carry_metrics_without_data():
    from crosspilot.models import KeywordOpportunity

    with pytest.raises(ValueError):
        KeywordOpportunity(keyword="x", has_metrics=False, search_volume=500)


def test_price_analysis_statistics_are_correct():
    data = normalize(
        _request(
            own_price=30.0,
            competitors=[
                CompetitorProduct(name="A", price=10.0, reviews=[]),
                CompetitorProduct(name="B", price=20.0, reviews=[]),
                CompetitorProduct(name="C", price=30.0, reviews=[]),
            ],
        )
    )
    price = analyze_prices(data, 30.0)
    assert price.min_price == 10.0
    assert price.max_price == 30.0
    assert price.median_price == 20.0
    assert price.mean_price == 20.0
    assert price.own_position == "within_range"
    assert price.position_percentile == pytest.approx(2 / 3)


def test_negated_pain_phrase_not_counted_as_negative():
    """'does not leak' 不应被统计成渗漏痛点。"""
    request = _request(
        competitors=[
            CompetitorProduct(
                name="NoLeak",
                reviews=[ReviewSample(rating=5, text="This bottle does not leak at all.")],
            )
        ]
    )
    report = run_analysis(request)
    labels = [p.label for p in report.review_insights.pain_points]
    assert "密封/渗漏问题" not in labels


def test_demo_mode_is_flagged_and_disclaimed():
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    report = run_analysis(CompetitorAnalysisRequest(**DEMO_ANALYSIS_REQUEST))
    assert report.data_provenance.is_demo is True
    assert any("demo" in w.lower() or "模拟" in w for w in report.warnings)
    assert report.data_provenance.review_sample_count == 17


def test_report_can_be_serialized_roundtrip():
    from crosspilot.models import AnalysisReport

    report = run_analysis(_request())
    dumped = report.model_dump(mode="json")
    restored = AnalysisReport(**dumped)
    assert restored.report_id == report.report_id
    assert len(restored.competitor_snapshots) == len(report.competitor_snapshots)


def test_cross_language_feature_comparison_is_flagged_in_limitations():
    """中文自有卖点 vs 英文竞品卖点的匹配不可靠，必须在限制中说明。"""
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    report = run_analysis(CompetitorAnalysisRequest(**DEMO_ANALYSIS_REQUEST))
    joined = " ".join(report.limitations)
    assert "无法做词级匹配" in joined


def test_single_competitor_price_position_still_computed():
    request = _request(
        own_price=30.0,
        competitors=[CompetitorProduct(name="Only", price=25.0, reviews=[])],
    )
    report = run_analysis(request)
    assert report.price_analysis.own_position == "above_range"
    assert report.price_analysis.position_percentile == 1.0
