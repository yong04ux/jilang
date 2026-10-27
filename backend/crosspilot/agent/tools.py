"""Tool 层（阶段 D2）：Agent 可调用能力的最小封装。

每个 Tool 都是**薄壳**：只做参数校验、调用既有业务函数、返回结构化结果，
不在这里写算法，也不直接访问 HTTP。这样「工作台」与「独立页面」永远是
同一条代码路径。
"""

from __future__ import annotations

from typing import Any

from ..persistence.db import Database
from ..models import AnalysisReport, CompetitorAnalysisRequest, ListingDraft, ListingGenerationRequest
from . import skills


def read_data_asset(
    db: Database,
    tenant_id: str,
    *,
    competitors: list[dict[str, Any]] | None = None,
    batch_id: str | None = None,
) -> list[dict[str, Any]]:
    """读取竞品数据资产。

    实现已下沉到 ``market.competitor_provider``（计划 §9）：数据来源的判断
    （显式行 / 导入批次 / 租户归属）只应有一处。这里保留原签名与返回类型，
    因为既有调用方与测试按「返回行数组」编写。

    没有数据时返回空列表，由调用方决定是报错还是询问——这里不编造数据。
    """
    from ..market.competitor_provider import (
        MODE_IMPORTED,
        CompetitorQuery,
        build_competitor_provider,
    )

    provider = build_competitor_provider(MODE_IMPORTED, db=db, tenant_id=tenant_id)
    data = provider.fetch(
        CompetitorQuery(
            product_name="",
            batch_id=batch_id,
            rows=competitors or None,
        )
    )
    return data.rows


def run_competitor_analysis(provider, request: CompetitorAnalysisRequest) -> AnalysisReport:
    """Tool: run_competitor_analysis。"""
    return skills.run_competitor_analysis(provider, request)


def generate_listing(
    provider,
    request: ListingGenerationRequest,
    report_payload: dict[str, Any] | None,
) -> ListingDraft:
    """Tool: generate_listing。"""
    return skills.generate_listing(provider, request, report_payload)


def run_quality_check(listing: ListingDraft) -> dict[str, Any]:
    """Tool: run_quality_check。"""
    return skills.quality_snapshot(listing)


TOOLS = {
    "read_data_asset": read_data_asset,
    "run_competitor_analysis": run_competitor_analysis,
    "generate_listing": generate_listing,
    "run_quality_check": run_quality_check,
}


__all__ = [
    "TOOLS",
    "generate_listing",
    "read_data_asset",
    "run_competitor_analysis",
    "run_quality_check",
]
