"""竞品分析的前置判定（计划 §6.1 的确定性节点，Service 层）。

为什么单独一层
==============

跟 ``listing_facts.py`` 同一个理由：节点只做编排，判断必须是可单测的纯函数。

三个函数都不调模型、不访问数据库：

- ``summarize_normalized``：归一化后有多少竞品/评论/价格/关键词
- ``assess_sufficiency``：够不够支撑"稳定"的结论
- ``validate_report``：报告结构是否完整到可以交付

「数据不足」与「系统失败」的边界
================================

这是计划 §6.1 点名要求区分的两件事，也是本模块存在的核心原因：

- **数据不足** = 有数据但样本少 → ``sufficient=False``，结论标 partial，
  仍然把算得出来的东西交给用户。**这不是故障**。
- **系统失败** = 取数抛异常、报告结构残缺 → 由错误分类处理成 5xx / 4xx。

改造前两者都会被压成一句"分析失败"，用户无法判断是"再去多导几条竞品"
还是"服务挂了"。
"""

from __future__ import annotations

from typing import Any

#: 结论稳定所需的最低样本量。低于它就标 partial，**不是**拒绝分析。
MIN_COMPETITORS = 3
MIN_REVIEWS = 1
MIN_PRICED = 1


def summarize_normalized(normalized: dict[str, Any]) -> dict[str, Any]:
    """归一化结果的可计数摘要。

    ``normalized`` 由子图从 ``engine.analysis.normalize`` 的返回值填充，
    这里不重新计算，只做计数——避免"同一件事两处实现"。
    """
    competitors = normalized.get("competitors") or []
    reviews = normalized.get("reviews") or []
    keywords = normalized.get("keywords") or []
    priced = [c for c in competitors if isinstance(c, dict) and c.get("price") is not None]
    return {
        "competitor_count": len(competitors),
        "review_count": len(reviews),
        "priced_count": len(priced),
        "keyword_count": len(keywords),
        "warnings": list(normalized.get("warnings") or []),
    }


def assess_sufficiency(summary: dict[str, Any]) -> dict[str, Any]:
    """判断样本量是否够撑起「稳定」的价格与卖点结论。

    返回 ``reasons`` 说明**哪些指标不够**，前端可以据此提示"再导入几条竞品"，
    而不是只给一句"数据不足"。
    """
    reasons: list[str] = []
    if int(summary.get("competitor_count") or 0) < MIN_COMPETITORS:
        reasons.append(
            f"竞品只有 {int(summary.get('competitor_count') or 0)} 个，"
            f"少于 {MIN_COMPETITORS} 个，价格与卖点结论稳定性有限"
        )
    if int(summary.get("review_count") or 0) < MIN_REVIEWS:
        reasons.append("没有评论样本，痛点与需求部分为空")
    if int(summary.get("priced_count") or 0) < MIN_PRICED:
        reasons.append("没有竞品价格，价格定位不可用")

    return {
        "sufficient": not reasons,
        "reasons": reasons,
        "thresholds": {
            "min_competitors": MIN_COMPETITORS,
            "min_reviews": MIN_REVIEWS,
            "min_priced": MIN_PRICED,
        },
    }


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    """报告结构完整性检查（**不含**业务判断，业务判断在 ``check_integrity``）。

    只回答"这份报告能不能交付"：必填块在不在、竞品快照是否非空。
    结构残缺属于系统问题（不该发生），要抛出去而不是标 partial。
    """
    issues: list[str] = []
    for field in ("product_name", "data_provenance", "review_insights", "keyword_analysis"):
        if not report.get(field):
            issues.append(f"报告缺少「{field}」")
    if not report.get("competitor_snapshots"):
        issues.append("报告没有竞品快照")
    return {"ok": not issues, "issues": issues}


__all__ = [
    "MIN_COMPETITORS",
    "MIN_PRICED",
    "MIN_REVIEWS",
    "assess_sufficiency",
    "summarize_normalized",
    "validate_report",
]
