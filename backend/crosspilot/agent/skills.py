"""Skills：把已有业务能力包装成 Agent 可调用的确定性单元。

原则：
- 每个 Skill 只做一件事，输入输出都是普通 dict/Pydantic 模型；
- **不在这里写算法**，一律调用 `analysis` / `listing` / `importers` 里的既有实现，
  保证「AI 工作台」与「独立页面」走同一条代码路径；
- `market_summary` 是确定性归纳，不调用大模型，因此测试无需 LLM。
"""

from __future__ import annotations

from typing import Any

from ..models import AnalysisReport, CompetitorAnalysisRequest, ListingDraft, ListingGenerationRequest


def run_competitor_analysis(provider, request: CompetitorAnalysisRequest) -> AnalysisReport:
    """Skill: competitor_analysis → 调用 Provider 的 analyze。"""
    return provider.analyze(request)


def generate_listing(
    provider,
    request: ListingGenerationRequest,
    report_payload: dict[str, Any] | None,
) -> ListingDraft:
    """Skill: listing_generation → 调用 Provider 的 generate。"""
    return provider.generate(request, report_payload)


def mine_reviews(report: AnalysisReport) -> dict[str, Any]:
    """Skill: review_mining → 从报告里抽评论主题（不重新计算）。"""
    insights = report.review_insights
    return {
        "total_samples": insights.total_samples,
        "with_rating": insights.with_rating,
        "pain_points": [
            {"label": p.label, "frequency": p.frequency, "share": p.share}
            for p in insights.pain_points[:6]
        ],
        "needs": [{"label": p.label, "frequency": p.frequency} for p in insights.needs[:6]],
        "concerns": [
            {"label": p.label, "frequency": p.frequency} for p in insights.purchase_concerns[:6]
        ],
        "limitations": insights.limitations,
    }


def check_integrity(report: AnalysisReport) -> dict[str, Any]:
    """确定性数据完整性检查。任何结论都不能绕过这一步。"""
    prov = report.data_provenance
    issues: list[dict[str, str]] = []

    if prov.competitor_count < 3:
        issues.append(
            {
                "code": "few_competitors",
                "severity": "warning",
                "message": f"竞品只有 {prov.competitor_count} 个，价格与卖点结论的稳定性有限",
            }
        )
    if prov.review_sample_count == 0:
        issues.append(
            {
                "code": "no_reviews",
                "severity": "warning",
                "message": "没有评论样本，痛点与需求部分为空",
            }
        )
    priced = sum(1 for c in report.competitor_snapshots if c.price is not None)
    if priced == 0:
        issues.append(
            {"code": "no_price", "severity": "warning", "message": "没有竞品价格，价格定位不可用"}
        )
    if prov.fields_missing:
        issues.append(
            {
                "code": "missing_fields",
                "severity": "info",
                "message": "部分竞品字段缺失：" + "、".join(prov.fields_missing[:6]),
            }
        )
    if prov.is_demo:
        issues.append(
            {
                "code": "demo_data",
                "severity": "warning",
                "message": "当前数据为示例数据，不可用于真实经营决策",
            }
        )

    return {
        "ok": not any(i["severity"] == "error" for i in issues),
        "issues": issues,
        "metrics": {
            "competitors": prov.competitor_count,
            "reviews": prov.review_sample_count,
            "keywords": prov.keyword_count,
            "priced_competitors": priced,
            "is_demo": prov.is_demo,
        },
    }


def market_summary(report: AnalysisReport) -> dict[str, Any]:
    """Skill: market_summary。

    确定性归纳：只引用报告里已经算出来的结论，不新增任何数字，也不调用 LLM。
    这正是「LLM 负责措辞、代码负责数字」原则的落地。
    """
    points: list[dict[str, str]] = []

    price = report.price_analysis
    if price and price.compared_count:
        position = {
            "below_range": "低于竞品价格区间",
            "within_range": "落在竞品价格区间内",
            "above_range": "高于竞品价格区间",
            "unknown": "价格定位无法判断",
        }.get(price.own_position, "价格定位无法判断")
        points.append(
            {
                "text": (
                    f"自有价格{position}"
                    f"（竞品区间 {price.min_price}–{price.max_price}，中位 {price.median_price}）"
                ),
                "evidence_kind": "statistic",
            }
        )

    pains = report.review_insights.pain_points[:3]
    if pains:
        labels = "、".join(f"{p.label}（{p.frequency} 次）" for p in pains)
        points.append({"text": f"评论中最集中的问题是：{labels}", "evidence_kind": "statistic"})

    keyword = report.keyword_analysis
    if keyword.available and keyword.with_metrics:
        points.append(
            {
                "text": f"{keyword.with_metrics} 个关键词带可量化指标，可据此排序",
                "evidence_kind": "statistic",
            }
        )
    elif keyword.available:
        points.append(
            {
                "text": "关键词缺少搜索量与排名，未计算机会分，也未推断流量",
                "evidence_kind": "fact",
            }
        )

    if report.differentiation_opportunities:
        top = report.differentiation_opportunities[0]
        points.append(
            {
                "text": f"最优先的差异化方向：{top.angle}（置信度 {top.confidence}）",
                "evidence_kind": "inference",
            }
        )

    return {
        "headline": f"{report.product_name} 的市场机会判断",
        "points": points,
        "data_is_demo": report.data_provenance.is_demo,
        "limitations": report.limitations[:4],
    }


def quality_snapshot(listing: ListingDraft) -> dict[str, Any]:
    """Skill: 质量检查。直接读质检结果，不重复实现规则。"""
    qc = listing.quality_check
    return {
        "passed": qc.passed,
        "errors": [i.message for i in qc.issues if i.severity.value == "error"],
        "warnings": [i.message for i in qc.issues if i.severity.value == "warning"],
        "pending_confirmations": listing.pending_confirmations,
        "engine": listing.engine,
        "policy_disclaimer": qc.policy_disclaimer,
    }


__all__ = [
    "check_integrity",
    "generate_listing",
    "market_summary",
    "mine_reviews",
    "quality_snapshot",
    "run_competitor_analysis",
]
