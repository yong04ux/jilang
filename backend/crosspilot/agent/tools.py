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

    优先级：显式传入的行 > 导入批次。批次必须属于当前租户，否则当作不存在。
    没有数据时返回空列表，由调用方决定是报错还是询问——这里不编造数据。
    """
    if competitors:
        return competitors
    if not batch_id:
        return []
    batch = db.get_import_batch(batch_id, tenant_id)
    if batch is None:
        return []
    rows = batch.get("competitors")
    if isinstance(rows, list):
        return rows
    # 兼容旧批次结构：payload 直接是行数组
    return batch if isinstance(batch, list) else []


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
