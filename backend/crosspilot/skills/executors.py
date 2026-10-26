"""七个技能的 executor：**只做参数拼装与调用，不写算法**。

这条纪律不是洁癖：一旦在这里加一句统计或排序，技能页的产出就会和
「竞品分析页」「工作台」「旧 7 节点图」慢慢分叉，而 PRD 的验收口径是
「同一输入产出逐字段一致」。所以本文件里允许出现的操作只有三种：

1. 从 ``SkillContext`` / ``inputs`` 取值；
2. 调用既有实现（``agent.tools`` / ``agent.skills`` / ``engine`` / ``ingest``）；
3. ``model_dump(mode="json")`` 或做一次键名搬运。

**调用点一律走模块属性**（``tools.run_competitor_analysis(...)``，不是
``from ..agent.tools import run_competitor_analysis``）：既有测试用
``monkeypatch.setattr("crosspilot.agent.tools.run_competitor_analysis", ...)``
替换实现，只有延迟到调用时才做属性查找，补丁才吃得到。
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from ..agent import skills as agent_skills
from ..agent import tools
from ..ingest import importers
from ..labels import humanize_error
from ..models import AnalysisReport, CompetitorProduct, ListingDraft
from ..services import listing_service
from .base import (
    SkillContext,
    SkillInputError,
    SkillPayloadTooLarge,
    SkillResourceMissing,
)
from .inputs import (
    CompetitorAnalysisInput,
    DataValidationInput,
    ListingGenerationInput,
    ListingQualityInput,
    MarketSummaryInput,
    ReviewMiningInput,
    ReportRefInput,
)

#: 未配置上限时的兜底（与 ``Settings.max_upload_bytes`` 默认值一致）
_DEFAULT_MAX_UPLOAD = 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# 取数小工具（只读，不写库）
# ---------------------------------------------------------------------------


def _load_report(ctx: SkillContext, ref: ReportRefInput) -> AnalysisReport:
    """报告要么由调用方直接给出（图内节点），要么按 id 从库里读。"""
    if ref.report:
        return AnalysisReport(**ref.report)
    payload = ctx.db.get_report(
        ref.report_id or "", user_id=ctx.user_id, tenant_id=ctx.tenant_id
    )
    if payload is None:
        raise SkillResourceMissing("分析报告", ref.report_id)
    return AnalysisReport(**payload)


def _load_listing(ctx: SkillContext, ref: ListingQualityInput) -> ListingDraft:
    if ref.listing:
        return ListingDraft(**ref.listing)
    payload = ctx.db.get_listing(
        ref.listing_id or "", user_id=ctx.user_id, tenant_id=ctx.tenant_id
    )
    if payload is None:
        raise SkillResourceMissing("Listing 草稿", ref.listing_id)
    return ListingDraft(**payload)


# ---------------------------------------------------------------------------
# 1. 竞品分析
# ---------------------------------------------------------------------------


def competitor_analysis(ctx: SkillContext, inputs: CompetitorAnalysisInput) -> dict[str, Any]:
    competitors: list[CompetitorProduct] = list(inputs.competitors)
    if not competitors and inputs.import_batch_id:
        rows = tools.read_data_asset(
            ctx.db, ctx.tenant_id, batch_id=inputs.import_batch_id
        )
        if not rows:
            raise SkillResourceMissing("竞品数据批次", inputs.import_batch_id)
        try:
            competitors = [CompetitorProduct(**row) for row in rows]
        except Exception as exc:  # noqa: BLE001 - 批次数据不合法属于输入问题
            raise SkillInputError(
                "这批导入的数据里有无法识别的行，请回到数据资产修正后重试"
            ) from exc
    report = tools.run_competitor_analysis(ctx.provider, inputs.to_request(competitors))
    return report.model_dump(mode="json")


# ---------------------------------------------------------------------------
# 2. 评论痛点挖掘
# ---------------------------------------------------------------------------


def review_mining(ctx: SkillContext, inputs: ReviewMiningInput) -> dict[str, Any]:
    return agent_skills.mine_reviews(_load_report(ctx, inputs))


# ---------------------------------------------------------------------------
# 3. 市场机会总结
# ---------------------------------------------------------------------------


def market_summary(ctx: SkillContext, inputs: MarketSummaryInput) -> dict[str, Any]:
    return agent_skills.market_summary(_load_report(ctx, inputs))


# ---------------------------------------------------------------------------
# 4. Listing 生成
# ---------------------------------------------------------------------------


def listing_generation(ctx: SkillContext, inputs: ListingGenerationInput) -> dict[str, Any]:
    request = inputs.to_request()
    report_payload = inputs.analysis_report
    if report_payload is None and inputs.report_id:
        report_payload = ctx.db.get_report(
            inputs.report_id, user_id=ctx.user_id, tenant_id=ctx.tenant_id
        )
        if report_payload is None:
            raise SkillResourceMissing("分析报告", inputs.report_id)
    listing = tools.generate_listing(ctx.provider, request, report_payload)
    # 与 /api/listings/generate 同一条落库形态：附带商品事实快照，供后续复检
    return listing_service.dump_for_storage(listing, request)


# ---------------------------------------------------------------------------
# 5. Listing 质检
# ---------------------------------------------------------------------------


def listing_quality(ctx: SkillContext, inputs: ListingQualityInput) -> dict[str, Any]:
    return tools.run_quality_check(_load_listing(ctx, inputs))


# ---------------------------------------------------------------------------
# 6. 数据校验
# ---------------------------------------------------------------------------


def data_validation(ctx: SkillContext, inputs: DataValidationInput) -> dict[str, Any]:
    try:
        raw = base64.b64decode(inputs.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SkillInputError("文件内容读不出来，请重新选择文件") from exc

    limit = getattr(ctx.settings, "max_upload_bytes", _DEFAULT_MAX_UPLOAD) or _DEFAULT_MAX_UPLOAD
    if len(raw) > limit:
        raise SkillPayloadTooLarge(limit)

    try:
        result = importers.import_competitor_data(
            raw,
            inputs.filename,
            allow_single_failed_rows=inputs.allow_partial_rows,
        )
    except importers.ImportValidationError as exc:
        # 文件根本读不了（编码/类型不对）才算参数错误；行级错误是正常结果
        raise SkillInputError(str(exc)) from exc

    return {
        "ok": result.ok,
        "source_format": result.source_format,
        "source_name": result.source_name,
        "total_rows": result.total_rows,
        "valid_rows": len(result.competitors),
        "error_count": len(result.errors),
        "errors": [humanize_error(e.as_dict()) for e in result.errors[:50]],
        "warnings": result.warnings,
        "preview": [c.model_dump(mode="json") for c in result.competitors[:5]],
        # 仅供落库使用，出接口前会被剥掉（见 skills/runtime.py）
        "_batch": result.as_dict(),
    }


# ---------------------------------------------------------------------------
# 7. 成本与利润测算
# ---------------------------------------------------------------------------


def profit_calc(ctx: SkillContext, inputs: Any) -> dict[str, Any]:
    from ..engine.profit import calculate

    return calculate(inputs).model_dump(mode="json")


__all__ = [
    "competitor_analysis",
    "data_validation",
    "listing_generation",
    "listing_quality",
    "market_summary",
    "profit_calc",
    "review_mining",
]
