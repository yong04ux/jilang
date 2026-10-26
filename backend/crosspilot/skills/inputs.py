"""七个技能的输入契约。

这些模型有两个用途，共用**一份**定义（PRD §5.1 要消灭的正是「同一件能力三处各写一份」）：

1. ``POST /api/skills/{key}/run`` 用它校验参数，非法即 422 并指出字段；
2. ``GET /api/skills`` 输出它的 ``model_json_schema()``，前端据此生成参数表单。

因此字段上的 ``title`` 是**用户可见文案**，不是注释——它会直接印在表单标签上。
``x-ui`` 是给前端选控件用的提示（``hidden`` / ``file`` / ``lines`` / ``report-picker`` …），
不属于业务语义。

几个刻意的取舍：

- ``report_id | report``、``listing_id | listing`` 成对出现：**id 给页面用**（列表页
  只有 id），**对象给图内节点用**（节点手里是内存 dict，persist 之前无法按 id 读）。
- ``data_validation`` 收文件内容而不是批次 id：``/api/import`` 的两步上传已经做完整了，
  通用 runner 再开一条上传路径就是「同一件事两处实现」。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import (
    CompetitorAnalysisRequest,
    CompetitorProduct,
    KeywordMetric,
    ListingGenerationRequest,
    OwnProduct,
    Platform,
)


class CompetitorAnalysisInput(BaseModel):
    """竞品分析：竞品明细可以来自表单，也可以来自一批已导入的数据。"""

    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(title="商品名称", max_length=200)
    platform: Platform = Field(default=Platform.AMAZON, title="平台")
    marketplace: str = Field(default="US", title="站点", max_length=16)
    category: str | None = Field(default=None, title="类目", max_length=120)
    own_specs: dict[str, str] = Field(
        default_factory=dict, title="你的规格", json_schema_extra={"x-ui": "kv-lines"}
    )
    own_key_features: list[str] = Field(
        default_factory=list, title="你的卖点", json_schema_extra={"x-ui": "lines"}
    )
    own_price: float | None = Field(default=None, ge=0, title="你的价格")
    competitors: list[CompetitorProduct] = Field(
        default_factory=list,
        title="竞品",
        json_schema_extra={"x-ui": "competitor-lines"},
    )
    keywords: list[KeywordMetric] = Field(default_factory=list, title="关键词")
    # 用枚举而不是自由文本：这个值会直接渲染成下拉框，
    # 自由文本会把 "manual" 这种内部码印在界面上。
    data_source: Literal["manual", "demo", "import"] = Field(
        default="manual", title="数据来源"
    )
    locale: Literal["zh-CN", "en-US"] = Field(default="zh-CN", title="站点语言")
    import_batch_id: str | None = Field(
        default=None, title="已导入的数据批次", json_schema_extra={"x-ui": "hidden"}
    )

    @model_validator(mode="after")
    def _need_source(self) -> "CompetitorAnalysisInput":
        if not self.competitors and not (self.import_batch_id or "").strip():
            raise ValueError("至少提供 1 个竞品，或指定一批已导入的数据")
        return self

    def to_request(self, competitors: list[CompetitorProduct]) -> CompetitorAnalysisRequest:
        """拼装既有的分析请求。字段一一对应，不做任何补全或改写。"""
        return CompetitorAnalysisRequest(
            product_name=self.product_name,
            platform=self.platform,
            marketplace=self.marketplace,
            category=self.category,
            own_specs=self.own_specs,
            own_key_features=self.own_key_features,
            own_price=self.own_price,
            competitors=competitors,
            keywords=self.keywords,
            data_source=self.data_source,
            locale=self.locale,
        )


class ReportRefInput(BaseModel):
    """引用一份已有的竞品分析报告。"""

    model_config = ConfigDict(extra="forbid")

    report_id: str | None = Field(
        default=None, title="分析报告", json_schema_extra={"x-ui": "report-picker"}
    )
    report: dict[str, Any] | None = Field(
        default=None, title="分析报告", json_schema_extra={"x-ui": "hidden"}
    )

    @model_validator(mode="after")
    def _need_one(self) -> "ReportRefInput":
        if not self.report and not (self.report_id or "").strip():
            raise ValueError("请先选择一份分析报告")
        return self


class ReviewMiningInput(ReportRefInput):
    """评论痛点挖掘：从报告里已有的评论样本归纳主题。"""


class MarketSummaryInput(ReportRefInput):
    """市场机会总结：只引用报告已有结论，不调用模型。"""


class ListingQualityInput(BaseModel):
    """Listing 质检：对一份已有草稿跑事实对齐检查。"""

    model_config = ConfigDict(extra="forbid")

    listing_id: str | None = Field(
        default=None, title="Listing 草稿", json_schema_extra={"x-ui": "listing-picker"}
    )
    listing: dict[str, Any] | None = Field(
        default=None, title="Listing 草稿", json_schema_extra={"x-ui": "hidden"}
    )

    @model_validator(mode="after")
    def _need_one(self) -> "ListingQualityInput":
        if not self.listing and not (self.listing_id or "").strip():
            raise ValueError("请先选择一份 Listing 草稿")
        return self


class ListingGenerationInput(BaseModel):
    """Listing 生成：商品事实必填，竞品报告可选（没有就只按事实写）。"""

    model_config = ConfigDict(extra="forbid")

    product: OwnProduct = Field(title="商品事实")
    language: Literal["zh-CN", "en-US"] = Field(default="en-US", title="目标语言")
    marketplace: str = Field(default="US", title="站点", max_length=16)
    report_id: str | None = Field(
        default=None, title="关联的竞品报告", json_schema_extra={"x-ui": "report-picker"}
    )
    analysis_report: dict[str, Any] | None = Field(
        default=None, title="关联的竞品报告", json_schema_extra={"x-ui": "hidden"}
    )
    keywords: list[KeywordMetric] = Field(default_factory=list, title="关键词")
    tone: str | None = Field(default=None, title="语气", max_length=60)
    banned_terms: list[str] = Field(
        default_factory=list, title="禁用词", json_schema_extra={"x-ui": "lines"}
    )
    target_length_hint: Literal["short", "medium", "long"] = Field(
        default="medium", title="篇幅要求"
    )
    # 用枚举而不是自由文本：这个值会直接渲染成下拉框，
    # 自由文本会把 "manual" 这种内部码印在界面上。
    data_source: Literal["manual", "demo", "import"] = Field(
        default="manual", title="数据来源"
    )

    def to_request(self) -> ListingGenerationRequest:
        return ListingGenerationRequest(
            product=self.product,
            language=self.language,
            marketplace=self.marketplace,
            analysis_report=self.analysis_report,
            analysis_report_id=self.report_id,
            keywords=self.keywords,
            tone=self.tone,
            banned_terms=self.banned_terms,
            target_length_hint=self.target_length_hint,
            data_source=self.data_source,
        )


class DataValidationInput(BaseModel):
    """数据校验：一次性校验一份竞品数据文件，不是「重放已有批次」。"""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(title="文件名", max_length=255)
    content_base64: str = Field(title="文件", json_schema_extra={"x-ui": "file"})
    allow_partial_rows: bool = Field(default=True, title="允许部分行出错")


__all__ = [
    "CompetitorAnalysisInput",
    "DataValidationInput",
    "ListingGenerationInput",
    "ListingQualityInput",
    "MarketSummaryInput",
    "ReportRefInput",
    "ReviewMiningInput",
]
