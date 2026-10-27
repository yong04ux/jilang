"""Pydantic 数据模型：输入、规范化实体、分析报告与 Listing 输出。

约定：
1. 所有"模型推断"与"事实/统计"在类型层面分开：``Claim.evidence_kind`` 只能是
   ``fact`` / ``statistic`` / ``inference`` / ``assumption`` 之一。
2. 缺失的商品属性用 ``None`` 表示，并进入 ``ListingDraft.pending_confirmations``，
   **绝不**由流程自动补全成事实。
3. 关键词的 ``search_volume`` / ``rank`` 等指标默认 ``None``；缺数据时报告只输出
   "无数据"，不会生成数字。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# 基础枚举
# ---------------------------------------------------------------------------


class Platform(str, Enum):
    """商品销售的平台。

    这段 docstring 会随 ``model_json_schema()`` 直接出现在对外接口文档和表单提示里，
    所以只写用户能看懂的语义，不写排期与实现说明。
    """

    AMAZON = "amazon"
    EBAY = "ebay"
    WALMART = "walmart"
    SHOPEE = "shopee"
    MERCADOLIBRE = "mercadolibre"


class EvidenceKind(str, Enum):
    """结论的证据性质。"""

    FACT = "fact"  # 直接来自输入数据
    STATISTIC = "statistic"  # 由输入数据计算出的统计量（附样本量/方法）
    INFERENCE = "inference"  # 模型/规则基于证据做出的推断
    ASSUMPTION = "assumption"  # 假设，需要人工确认


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class IssueCode(str, Enum):
    """Listing 质检问题代码。"""

    BANNED_TERM = "banned_term"
    UNSUPPORTED_NUMBER = "unsupported_number"
    UNSUPPORTED_SUPERLATIVE = "unsupported_superlative"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    UNVERIFIED_CERTIFICATION = "unverified_certification"
    UNVERIFIED_EFFICACY = "unverified_efficacy"
    KEYWORD_STUFFING = "keyword_stuffing"
    MISSING_FACT = "missing_fact"
    OVER_LENGTH = "over_length"
    EMPTY_SECTION = "empty_section"
    PLACEHOLDER_TEXT = "placeholder_text"


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def normalize_text(value: str | None) -> str | None:
    """去首尾空白并折叠内部空白；空字符串归一为 None。"""
    if value is None:
        return None
    cleaned = _WS_RE.sub(" ", value).strip()
    return cleaned or None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 输入：商品与竞品
# ---------------------------------------------------------------------------


class ReviewSample(BaseModel):
    """单条评论样本。``text`` 必填，其余字段可选且缺失时不推断。"""

    model_config = ConfigDict(extra="ignore")

    rating: float | None = Field(default=None, ge=1, le=5)
    title: str | None = None
    text: str
    date: str | None = None
    verified_purchase: bool | None = None
    source: str | None = None
    language: str | None = None

    @field_validator("text")
    @classmethod
    def _text_required(cls, value: str) -> str:
        cleaned = normalize_text(value)
        if not cleaned:
            raise ValueError("评论内容不能为空")
        return cleaned

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str | None) -> str | None:
        return normalize_text(value)


class CompetitorProduct(BaseModel):
    """竞品商品。未提供的字段保持 None，报告中不会补全。"""

    model_config = ConfigDict(extra="ignore")

    name: str
    brand: str | None = None
    asin: str | None = None
    price: float | None = Field(default=None, ge=0)
    currency: str = "USD"
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = Field(default=None, ge=0)
    category: str | None = None
    key_features: list[str] = Field(default_factory=list)
    specifications: dict[str, str] = Field(default_factory=dict)
    reviews: list[ReviewSample] = Field(default_factory=list)
    is_demo: bool = True
    source_ref: str | None = Field(
        default=None, description="原始数据出处，例如导入文件名或 API 批次号"
    )

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        cleaned = normalize_text(value)
        if not cleaned:
            raise ValueError("竞品名称不能为空")
        return cleaned

    @field_validator("key_features", mode="before")
    @classmethod
    def _split_features(cls, value: Any) -> list[str]:
        """CSV 中用 | 或换行分隔的卖点会作为字符串传入。"""
        if value is None:
            return []
        if isinstance(value, str):
            parts = re.split(r"[|\n]", value)
            return [p.strip() for p in parts if p.strip()]
        return value

    @field_validator("brand", "asin", "category", "source_ref")
    @classmethod
    def _clean_optional(cls, value: str | None) -> str | None:
        return normalize_text(value)


class KeywordMetric(BaseModel):
    """关键词数据。指标全部可选：没有数据就是 None，绝不编造。"""

    model_config = ConfigDict(extra="ignore")

    keyword: str
    search_volume: int | None = Field(default=None, ge=0)
    rank: int | None = Field(default=None, ge=1)
    relevance: float | None = Field(default=None, ge=0, le=1)
    competition: Literal["low", "medium", "high"] | None = None
    conversion_share: float | None = Field(default=None, ge=0, le=1)
    source: str | None = Field(
        default=None, description="指标来源，如 卖家后台导出 / 第三方工具 / demo"
    )

    @field_validator("keyword")
    @classmethod
    def _keyword_required(cls, value: str) -> str:
        cleaned = normalize_text(value)
        if not cleaned:
            raise ValueError("关键词不能为空")
        return cleaned

    @property
    def has_metrics(self) -> bool:
        return any(
            v is not None
            for v in (self.search_volume, self.rank, self.relevance, self.competition)
        )


class OwnProduct(BaseModel):
    """自有商品资料。``specifications`` 与 ``certifications`` 缺失即视为待确认。

    这里的 ``title`` 不只是文档：技能的输入契约直接复用这个模型，
    ``title`` 会印在技能页的表单标签上。所以每个字段都必须有中文名，
    否则界面上就会出现 ``Brand`` / ``Key Features`` 这种英文字段名。
    """

    model_config = ConfigDict(extra="ignore")

    name: str = Field(title="商品名称")
    brand: str | None = Field(default=None, title="品牌")
    category: str | None = Field(default=None, title="类目")
    specifications: dict[str, str] = Field(
        default_factory=dict, title="规格参数", json_schema_extra={"x-ui": "kv-lines"}
    )
    key_features: list[str] = Field(
        default_factory=list, title="核心卖点", json_schema_extra={"x-ui": "lines"}
    )
    materials: list[str] = Field(
        default_factory=list, title="材质", json_schema_extra={"x-ui": "lines"}
    )
    certifications: list[str] = Field(
        default_factory=list, title="认证资质", json_schema_extra={"x-ui": "lines"}
    )
    target_platform: Platform = Field(default=Platform.AMAZON, title="目标平台")
    marketplace: str = Field(default="US", title="站点", description="站点，例如 US / DE / JP")
    price: float | None = Field(default=None, ge=0, title="售价")
    currency: str = Field(default="USD", title="币种")
    target_audience: str | None = Field(default=None, title="目标人群")
    brand_voice: str | None = Field(default=None, title="品牌语气")
    banned_terms: list[str] = Field(
        default_factory=list, title="禁用词", json_schema_extra={"x-ui": "lines"}
    )
    differentiators: list[str] = Field(
        default_factory=list, title="差异化点", json_schema_extra={"x-ui": "lines"}
    )

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        cleaned = normalize_text(value)
        if not cleaned:
            raise ValueError("商品名称不能为空")
        return cleaned

    @field_validator("key_features", "materials", "certifications", "banned_terms", "differentiators", mode="before")
    @classmethod
    def _split_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [p.strip() for p in re.split(r"[|\n,，;；]", value) if p.strip()]
        return value

    @field_validator("brand", "category", "target_audience", "brand_voice")
    @classmethod
    def _clean_optional(cls, value: str | None) -> str | None:
        return normalize_text(value)


# ---------------------------------------------------------------------------
# 请求
# ---------------------------------------------------------------------------


class CompetitorAnalysisRequest(BaseModel):
    """竞品分析请求。"""

    model_config = ConfigDict(extra="forbid")

    product_name: str
    platform: Platform = Platform.AMAZON
    marketplace: str = "US"
    category: str | None = None
    own_specs: dict[str, str] = Field(default_factory=dict)
    own_key_features: list[str] = Field(default_factory=list)
    own_price: float | None = Field(default=None, ge=0)
    competitors: list[CompetitorProduct] = Field(min_length=1)
    keywords: list[KeywordMetric] = Field(default_factory=list)
    data_source: str = Field(default="user_input", description="manual / csv / json / demo")
    locale: Literal["zh-CN", "en-US"] = "zh-CN"

    @field_validator("product_name")
    @classmethod
    def _product_name_required(cls, value: str) -> str:
        cleaned = normalize_text(value)
        if not cleaned:
            raise ValueError("商品名称不能为空")
        return cleaned

    @field_validator("marketplace")
    @classmethod
    def _marketplace_upper(cls, value: str) -> str:
        return (normalize_text(value) or "US").upper()

    def total_review_count(self) -> int:
        return sum(len(c.reviews) for c in self.competitors)


class ListingGenerationRequest(BaseModel):
    """Listing 生成请求。

    ``analysis_report`` 可以是竞品分析接口返回的完整报告对象，也可以只传
    ``analysis_report_id``，由服务层从数据库读取。
    """

    model_config = ConfigDict(extra="forbid")

    product: OwnProduct
    language: str = "en-US"
    marketplace: str = "US"
    analysis_report: dict[str, Any] | None = None
    analysis_report_id: str | None = None
    keywords: list[KeywordMetric] = Field(default_factory=list)
    tone: str | None = Field(default=None, description="品牌语气，例如 专业可靠 / 轻松活泼")
    banned_terms: list[str] = Field(default_factory=list)
    target_length_hint: Literal["short", "medium", "long"] = "medium"
    data_source: str = "manual"
    #: 质检修订用的附加约束（Phase 3 的质量修订循环）。
    #: 由子图在重试生成时填入上一版的具体问题，**不是**给外部调用方的常规参数；
    #: 留成普通字段而不是单开一个方法，是因为它最终只影响提示词，不改变产出结构。
    revision_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_analysis(self) -> "ListingGenerationRequest":
        if self.analysis_report is None and not self.analysis_report_id:
            # 竞品报告是差异化依据，但不是硬性事实来源；允许缺省，但必须在输出中说明。
            self.analysis_report = None
        if self.marketplace:
            self.marketplace = (normalize_text(self.marketplace) or "US").upper()
        return self


# ---------------------------------------------------------------------------
# 输出：竞品分析
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    """一条结论的证据锚点：指向具体竞品、评论或字段。"""

    competitor: str | None = None
    field: str | None = None
    quote: str | None = None
    review_index: int | None = None
    data_source: str | None = None


class Claim(BaseModel):
    """带证据性质的结构化结论。"""

    statement: str
    evidence_kind: EvidenceKind
    evidence: list[EvidenceRef] = Field(default_factory=list)
    sample_size: int | None = None

    @model_validator(mode="after")
    def _inference_needs_basis(self) -> "Claim":
        if self.evidence_kind in (EvidenceKind.FACT, EvidenceKind.STATISTIC) and not self.evidence:
            kind = "事实" if self.evidence_kind is EvidenceKind.FACT else "统计"
            raise ValueError(f"{kind}类结论需要附上来源依据")
        return self


class ProductSnapshot(BaseModel):
    """竞品基本信息对比中的一行。"""

    name: str
    brand: str | None = None
    price: float | None = None
    currency: str = "USD"
    rating: float | None = None
    review_count: int | None = None
    review_samples: int = 0
    key_features: list[str] = Field(default_factory=list)
    is_demo: bool = True
    data_completeness: float = Field(ge=0, le=1, description="核心字段填充率")
    missing_fields: list[str] = Field(default_factory=list)


class PriceAnalysis(BaseModel):
    min_price: float | None = None
    max_price: float | None = None
    mean_price: float | None = None
    median_price: float | None = None
    own_price: float | None = None
    own_position: Literal["below_range", "within_range", "above_range", "unknown"] = "unknown"
    position_percentile: float | None = None
    compared_count: int = 0
    currency: str = "USD"
    claims: list[Claim] = Field(default_factory=list)


class FeatureComparison(BaseModel):
    feature: str
    mentioned_by: list[str] = Field(default_factory=list)
    mention_count: int = 0
    coverage_ratio: float = 0.0
    evidence_kind: EvidenceKind = EvidenceKind.STATISTIC


class PainPoint(BaseModel):
    label: str
    description: str
    frequency: int
    share: float
    sentiment: Literal["negative", "mixed", "neutral"] = "negative"
    competitor_breakdown: dict[str, int] = Field(default_factory=dict)
    samples: list[EvidenceRef] = Field(default_factory=list)
    claim: Claim | None = None


class ReviewInsights(BaseModel):
    total_samples: int = 0
    with_rating: int = 0
    rating_distribution: dict[str, int] = Field(default_factory=dict)
    low_rating_count: int = 0
    pain_points: list[PainPoint] = Field(default_factory=list)
    low_rating_themes: list[PainPoint] = Field(default_factory=list)
    needs: list[PainPoint] = Field(default_factory=list)
    purchase_concerns: list[PainPoint] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class KeywordOpportunity(BaseModel):
    keyword: str
    has_metrics: bool
    search_volume: int | None = None
    rank: int | None = None
    relevance: float | None = None
    competition: str | None = None
    opportunity_score: float | None = Field(
        default=None, description="仅当存在可量化指标时计算；无指标时为 None"
    )
    basis: str = ""

    @model_validator(mode="after")
    def _no_fabricated_metrics(self) -> "KeywordOpportunity":
        if not self.has_metrics and any(
            v is not None for v in (self.search_volume, self.rank, self.relevance, self.competition, self.opportunity_score)
        ):
            raise ValueError("无指标数据的关键词不得携带搜索量/排名/机会分")
        return self


class KeywordAnalysis(BaseModel):
    available: bool = False
    total_keywords: int = 0
    with_metrics: int = 0
    opportunities: list[KeywordOpportunity] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DifferentiationOpportunity(BaseModel):
    angle: str
    rationale: str
    supporting_evidence: list[Claim] = Field(default_factory=list)
    priority: Literal["high", "medium", "low"] = "medium"
    confidence: Literal["high", "medium", "low"] = "medium"
    requires_confirmation: bool = False


class ContentRecommendation(BaseModel):
    area: Literal["title", "bullet", "description", "a_plus", "image", "pricing", "positioning"]
    recommendation: str
    evidence_kind: EvidenceKind
    rationale: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class DataProvenance(BaseModel):
    data_source: str
    is_demo: bool
    competitor_count: int
    review_sample_count: int
    keyword_count: int
    fields_missing: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    """竞品分析报告（结构化输出）。"""

    report_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    product_name: str
    platform: Platform
    marketplace: str
    category: str | None = None
    locale: str = "zh-CN"
    data_provenance: DataProvenance
    competitor_snapshots: list[ProductSnapshot] = Field(default_factory=list)
    price_analysis: PriceAnalysis | None = None
    feature_comparison: list[FeatureComparison] = Field(default_factory=list)
    own_vs_competitors: list[Claim] = Field(default_factory=list)
    review_insights: ReviewInsights
    keyword_analysis: KeywordAnalysis
    differentiation_opportunities: list[DifferentiationOpportunity] = Field(default_factory=list)
    content_recommendations: list[ContentRecommendation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    engine: str = "rule"
    engine_version: str = "0.1.0"


# ---------------------------------------------------------------------------
# 输出：Listing
# ---------------------------------------------------------------------------


class BulletPoint(BaseModel):
    headline: str
    body: str
    character_count: int
    supporting_facts: list[str] = Field(default_factory=list)


class APlusModule(BaseModel):
    module_type: Literal[
        "hero_banner", "benefit_icons", "comparison_chart", "lifestyle_image", "spec_table", "brand_story"
    ]
    title: str
    purpose: str
    content_outline: list[str] = Field(default_factory=list)
    assets_needed: list[str] = Field(default_factory=list)


class QualityIssue(BaseModel):
    code: IssueCode
    severity: Severity
    message: str
    location: str | None = None
    excerpt: str | None = None
    suggestion: str | None = None


class SectionLength(BaseModel):
    section: str
    length: int
    limit: int | None = None
    within_limit: bool = True


class QualityCheck(BaseModel):
    passed: bool
    issues: list[QualityIssue] = Field(default_factory=list)
    section_lengths: list[SectionLength] = Field(default_factory=list)
    rules_applied: list[str] = Field(default_factory=list)
    policy_disclaimer: str = ""


class ListingProvenance(BaseModel):
    """Listing 的来源标记：与报告保持一致，示例数据不会被当作真实业务资料。"""

    data_source: str = "manual"
    is_demo: bool = False
    notes: list[str] = Field(default_factory=list)


class ListingDraft(BaseModel):
    """Listing 生成结果。所有商品事实必须能追溯到 ``fact_ledger``。"""

    listing_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    product_name: str
    platform: Platform
    marketplace: str
    language: str
    title: str
    bullets: list[BulletPoint] = Field(default_factory=list)
    description: str
    a_plus_outline: list[APlusModule] = Field(default_factory=list)
    search_terms: str = ""
    keywords_used: list[str] = Field(default_factory=list)
    keyword_layout_notes: list[str] = Field(default_factory=list)
    fact_ledger: list[dict[str, str]] = Field(
        default_factory=list, description="事实来源台账：statement -> 输入字段"
    )
    pending_confirmations: list[str] = Field(default_factory=list)
    quality_check: QualityCheck
    differentiation_used: list[str] = Field(default_factory=list)
    analysis_report_id: str | None = None
    limitations: list[str] = Field(default_factory=list)
    data_provenance: ListingProvenance = Field(default_factory=ListingProvenance)
    engine: str = "rule"
    engine_version: str = "0.1.0"


class AnalysisResponse(BaseModel):
    report: AnalysisReport
    persisted: bool = False
    duration_ms: int = 0
    task_id: str | None = None


class ListingResponse(BaseModel):
    listing: ListingDraft
    persisted: bool = False
    duration_ms: int = 0
    task_id: str | None = None


__all__ = [
    "APlusModule",
    "AnalysisReport",
    "AnalysisResponse",
    "BulletPoint",
    "Claim",
    "CompetitorAnalysisRequest",
    "CompetitorProduct",
    "ContentRecommendation",
    "DataProvenance",
    "DifferentiationOpportunity",
    "EvidenceKind",
    "EvidenceRef",
    "FeatureComparison",
    "IssueCode",
    "KeywordAnalysis",
    "KeywordMetric",
    "KeywordOpportunity",
    "ListingDraft",
    "ListingGenerationRequest",
    "ListingResponse",
    "OwnProduct",
    "PainPoint",
    "Platform",
    "PriceAnalysis",
    "ProductSnapshot",
    "QualityCheck",
    "QualityIssue",
    "ReviewInsights",
    "ReviewSample",
    "SectionLength",
    "Severity",
    "normalize_text",
    "utcnow",
]
