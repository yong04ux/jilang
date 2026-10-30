"""``SKILL_DEFINITIONS``：平台内置技能的**唯一真源**。

与 ``agent/registry.py`` 的分工
==============================

- 本模块是**代码里的**真源：有哪些技能、各自的输入契约、执行器、依赖、预算；
- ``skill_definitions`` 表仍由 ``registry.seed_registry`` 写入（本模块 → 表），
  租户自定义技能继续走那张表；
- ``GET /api/skills`` 把两者合并后返回，并补上 ``executable``。

这样避免了「同一件能力三处各写一份」：改这里一处，表、接口、执行入口同时生效。

纪律
====

1. **executor 只做参数拼装与调用**，算数一律在 ``agent/skills.py`` / ``engine``；
2. **没有实现的能力不上架**：``keyword_layout`` 只保留声明、``executor=None``，
   接口会明确返回"不可执行"，不摆空壳；
3. ``dependencies`` 是**声明式的**，由 dispatcher 检查后才执行，
   executor 内部不做二次降级判断。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..ingest import importers
from ..models import (
    AnalysisReport,
    CompetitorProduct,
    KeywordMetric,
    ListingDraft,
    OwnProduct,
    Platform,
)
from . import skills
from .contracts import (
    DEP_LLM,
    DEP_PROVIDER,
    STATUS_AVAILABLE,
    STATUS_DEV,
    SkillContext,
    SkillDefinition,
    SkillInputInvalid,
    SkillMissingInput,
)
from .graphs.listing_generation import run_listing_graph
from .state import OUTCOME_NEEDS_INPUT

#: 内置技能版本（与 Agent 定义版本分开演进）
VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# 输入契约
#
# 用 Pydantic 模型而不是 JSON Schema 字符串：校验与 schema 生成共用一份定义。
# ``extra="forbid"`` 是刻意的——多传字段说明调用方理解错了契约，
# 静默忽略会让它一直错下去。
# ---------------------------------------------------------------------------


class CompetitorAnalysisInput(BaseModel):
    """竞品分析：竞品必须由调用方给出，缺了直接 422，不会凭空生成。"""

    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(min_length=1, max_length=200)
    platform: Platform = Platform.AMAZON
    marketplace: str = Field(default="US", max_length=16)
    category: str | None = Field(default=None, max_length=120)
    own_specs: dict[str, str] = Field(default_factory=dict)
    own_key_features: list[str] = Field(default_factory=list)
    own_price: float | None = Field(default=None, ge=0)
    competitors: list[CompetitorProduct] = Field(min_length=1)
    keywords: list[KeywordMetric] = Field(default_factory=list)
    data_source: str = Field(default="manual", max_length=32)


class ListingGenerationInput(BaseModel):
    """Listing 生成：商品事实来自结构化输入，不从报告里猜。"""

    model_config = ConfigDict(extra="forbid")

    product: OwnProduct
    language: str = Field(default="en-US", max_length=16)
    marketplace: str = Field(default="US", max_length=16)
    analysis_report: dict[str, Any] | None = None
    data_source: str = Field(default="manual", max_length=32)


class ReportInput(BaseModel):
    """以报告为输入的技能（市场总结、评论挖掘）。"""

    model_config = ConfigDict(extra="forbid")

    report: dict[str, Any]


class QualityCheckInput(BaseModel):
    """质量检查：读草稿已有的质检结果，不重新实现规则。"""

    model_config = ConfigDict(extra="forbid")

    listing: dict[str, Any]


class DataValidationInput(BaseModel):
    """数据校验：收文件内容本身（扩展名决定解析器），不收批次 id。"""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content: str
    allow_single_failed_rows: bool = True


# ---------------------------------------------------------------------------
# executors
# ---------------------------------------------------------------------------


def _report_from(payload: ReportInput) -> AnalysisReport:
    """把 dict 还原成报告模型；结构不对时抛 422 而不是 500。"""
    try:
        return AnalysisReport(**payload.report)
    except ValidationError as exc:
        raise SkillInputInvalid(
            "报告结构不完整，无法作为该技能的输入",
            detail={"field": "report", "errors": exc.errors()[:5]},
        ) from exc


def _exec_competitor_analysis(ctx: SkillContext, payload: BaseModel) -> Any:
    """竞品分析走**子图**。

    子图：校验 → 选数据源 → 取数（有限重试）→ 归一化 → 充分性检查 →
    统计 → 校验 → 归纳（样本不足时标 partial）。

    注意：分析本身**不调模型**，``ctx.provider`` 只用来标注引擎名。
    ``persist=False``：技能入口不落库。
    """
    assert isinstance(payload, CompetitorAnalysisInput)
    from ..market.competitor_provider import MODE_IMPORTED, build_competitor_provider
    from .graphs.competitor_analysis import run_competitor_graph

    result = run_competitor_graph(
        {"request": payload.model_dump(mode="json"), "persist": False},
        provider=ctx.provider,
        competitor_provider=build_competitor_provider(
            MODE_IMPORTED, db=ctx.db, tenant_id=ctx.tenant_id
        ),
        db=ctx.db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        persist=False,
    )
    return {
        "report": result["report"],
        "summary": result["summary"],
        "checks": result["checks"],
        "outcome": result["outcome"],
        "message": result["message"],
        "provenance": result["provenance"],
    }


def _exec_listing_generation(ctx: SkillContext, payload: BaseModel) -> Any:
    """Listing 生成走**子图**，不再是单次函数调用。

    子图包含：事实整理 → 站点规则 → 竞品洞察 → 关键事实检查 → 生成 →
    质检 →（有限修订）。因此 ``executor_type`` 是 ``graph``。

    这里 ``persist=False``：技能入口不落库，产物由调用方决定。
    缺事实时抛 ``SkillMissingInput``，让界面引导用户补资料，而不是报"参数错误"。
    """
    assert isinstance(payload, ListingGenerationInput)
    result = run_listing_graph(
        {
            "request": payload.model_dump(mode="json"),
            "analysis_report": payload.analysis_report,
            "persist": False,
        },
        provider=ctx.provider,
        db=ctx.db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        persist=False,
    )
    if result.get("outcome") == OUTCOME_NEEDS_INPUT:
        raise SkillMissingInput(
            result.get("message") or "缺少商品资料，无法在不编造的前提下撰写文案",
            detail={"missing": (result.get("artifact") or {}).get("missing") or []},
        )
    return {
        "listing": result.get("listing"),
        "outcome": result.get("outcome"),
        "revisions": int(result.get("revision") or 0),
        "message": result.get("message") or "",
    }


def _exec_market_summary(ctx: SkillContext, payload: BaseModel) -> Any:
    assert isinstance(payload, ReportInput)
    return skills.market_summary(_report_from(payload))


def _exec_review_mining(ctx: SkillContext, payload: BaseModel) -> Any:
    assert isinstance(payload, ReportInput)
    return skills.mine_reviews(_report_from(payload))


def _exec_quality_check(ctx: SkillContext, payload: BaseModel) -> Any:
    assert isinstance(payload, QualityCheckInput)
    try:
        listing = ListingDraft(**payload.listing)
    except ValidationError as exc:
        raise SkillInputInvalid(
            "草稿结构不完整，无法检查",
            detail={"field": "listing", "errors": exc.errors()[:5]},
        ) from exc
    return skills.quality_snapshot(listing)


def _exec_data_validation(ctx: SkillContext, payload: BaseModel) -> Any:
    assert isinstance(payload, DataValidationInput)
    try:
        result = importers.import_competitor_data(
            payload.content,
            payload.filename,
            allow_single_failed_rows=payload.allow_single_failed_rows,
        )
    except importers.ImportValidationError as exc:
        raise SkillInputInvalid(
            str(exc),
            detail={
                "field": "content",
                "errors": [e.as_dict() for e in getattr(exc, "errors", [])[:5]],
            },
        ) from exc
    return result.as_dict()


# ---------------------------------------------------------------------------
# 定义清单
# ---------------------------------------------------------------------------

_ANALYSIS_OUTPUT = {
    "type": "object",
    "properties": {
        "report": {"type": "object", "description": "结构化竞品分析报告（含 data_provenance）"}
    },
}

_LISTING_OUTPUT = {
    "type": "object",
    "properties": {
        "listing": {"type": "object", "description": "草稿（含语块、质检结果与来源标记）"}
    },
}


SKILL_DEFINITIONS: tuple[SkillDefinition, ...] = (
    SkillDefinition(
        key="competitor_analysis",
        name="竞品分析",
        summary="价格统计、卖点覆盖、评论主题与差异化机会，全部为确定性计算。",
        version=VERSION,
        input_model=CompetitorAnalysisInput,
        output_schema=_ANALYSIS_OUTPUT,
        executor=_exec_competitor_analysis,
        # 走子图（取数 → 归一化 → 充分性 → 统计 → 校验 → 归纳）
        executor_type="graph",
        dependencies=(DEP_PROVIDER,),
        # 纯统计，不含模型调用；预算给足以覆盖未来真实取数的网络往返
        timeout_seconds=120.0,
        note="样本不足时仍会给出结论，但会标注为部分结果并说明原因。",
    ),
    SkillDefinition(
        key="listing_generation",
        name="Listing 生成",
        summary="基于事实台账生成标题/五点/描述/Search Terms，并做事实对齐质检。",
        version=VERSION,
        input_model=ListingGenerationInput,
        output_schema=_LISTING_OUTPUT,
        executor=_exec_listing_generation,
        # 走子图（事实 → 规则 → 洞察 → 生成 → 质检 → 有限修订）
        executor_type="graph",
        dependencies=(DEP_PROVIDER, DEP_LLM),
        # 生成要过模型，且可能修订一次（重跑一遍），预算按两轮留
        timeout_seconds=180.0,
        note="缺少可引用的商品事实时会停止并提示补充，不会编造参数。",
    ),
    SkillDefinition(
        key="market_summary",
        name="市场机会总结",
        summary="把报告里的结构化结论归纳成机会判断，只引用已有证据，不推断销量。",
        version=VERSION,
        input_model=ReportInput,
        output_schema={"type": "object", "properties": {"summary": {"type": "object"}}},
        executor=_exec_market_summary,
        # 纯确定性归纳，不依赖模型
        timeout_seconds=15.0,
    ),
    SkillDefinition(
        key="review_mining",
        name="评论痛点挖掘",
        summary="从报告的评论样本里抽出痛点、需求与购买顾虑，不重新计算统计。",
        version=VERSION,
        input_model=ReportInput,
        output_schema={
            "type": "object",
            "properties": {"pain_points": {"type": "array"}, "needs": {"type": "array"}},
        },
        executor=_exec_review_mining,
        timeout_seconds=15.0,
    ),
    SkillDefinition(
        key="quality_check",
        name="文案质检",
        summary="读草稿已有的质检结果，汇总错误、警告与待确认项。",
        version=VERSION,
        input_model=QualityCheckInput,
        output_schema={
            "type": "object",
            "properties": {"passed": {"type": "boolean"}, "issues": {"type": "array"}},
        },
        executor=_exec_quality_check,
        timeout_seconds=15.0,
    ),
    SkillDefinition(
        key="data_validation",
        name="数据校验与导入",
        summary="解析 CSV/JSON 文件，逐行校验竞品字段并定位错误。",
        version=VERSION,
        input_model=DataValidationInput,
        output_schema={
            "type": "object",
            "properties": {
                "competitors": {"type": "array"},
                "errors": {"type": "array"},
                "warnings": {"type": "array"},
            },
        },
        executor=_exec_data_validation,
        timeout_seconds=60.0,
    ),
    SkillDefinition(
        key="keyword_layout",
        name="关键词布局",
        summary="无搜索量数据时只做词表整理与布局建议，不计算机会分。",
        version=VERSION,
        # 没有实现：只留声明，明确不可执行
        input_model=None,
        input_schema={
            "type": "object",
            "properties": {"keywords": {"type": "array"}},
            "required": [],
        },
        output_schema={"type": "object", "properties": {"search_terms": {"type": "string"}}},
        executor=None,
        status=STATUS_DEV,
        note="尚未实现执行器，当前只能在报告中给出关键词清单，不能单独运行。",
    ),
)


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

_BY_KEY: dict[str, SkillDefinition] = {item.key: item for item in SKILL_DEFINITIONS}


def get_definition(key: str) -> SkillDefinition | None:
    """按 key 取定义（只含内置；租户自定义技能的元数据在表里，没有执行器）。"""
    return _BY_KEY.get((key or "").strip())


def executable_definitions() -> tuple[SkillDefinition, ...]:
    return tuple(item for item in SKILL_DEFINITIONS if item.executable)


def list_views() -> list[dict[str, Any]]:
    return [item.as_view() for item in SKILL_DEFINITIONS]


__all__ = [
    "SKILL_DEFINITIONS",
    "VERSION",
    "CompetitorAnalysisInput",
    "DataValidationInput",
    "ListingGenerationInput",
    "QualityCheckInput",
    "ReportInput",
    "executable_definitions",
    "get_definition",
    "list_views",
]
