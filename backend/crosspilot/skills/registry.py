"""``SKILL_REGISTRY``：平台能力的唯一真源。

改造前同一件能力存在三份互不相关的描述（``agent/skills.py`` 的函数、
``agent/registry.py`` 的静态 JSON、``frontend/js/catalog.js`` 的硬编码数组），
点「运行」只能把一句 prompt 填进对话框——这就是 PRD §5.1 要解决的根因。

现在：

- ``SKILL_REGISTRY`` 是代码里唯一的能力清单，``executor`` 就是可执行的那个函数；
- ``agent/registry.seed_registry`` 从它派生写入 ``skill_definitions``（租户自定义仍走那张表）；
- ``GET /api/skills`` 用 ``list_skill_views`` 生成，前端不再硬编码；
- ``keyword_layout`` **不进注册表**：没有实现的能力不上架，也不摆空壳。
"""

from __future__ import annotations

import json
from typing import Any

from ..engine.profit import ProfitRequest
from . import executors
from .base import REQUIRE_LLM, SkillSpec
from .inputs import (
    CompetitorAnalysisInput,
    DataValidationInput,
    ListingGenerationInput,
    ListingQualityInput,
    MarketSummaryInput,
    ReviewMiningInput,
)

#: 技能定义版本（与 Agent 定义版本分开演进）
VERSION = "0.4.0"

_CATEGORY_COMPETITOR = "竞品与Listing"
_CATEGORY_OPERATION = "产品运营"
_CATEGORY_DATA = "数据分析"
_CATEGORY_FINANCE = "财务核算"


def _specs() -> tuple[SkillSpec, ...]:
    return (
        SkillSpec(
            key="competitor_analysis",
            name="竞品分析",
            category=_CATEGORY_COMPETITOR,
            summary="按竞品价格、评分与评论算价格定位和差异化机会，每条结论都挂出处。",
            inputs=CompetitorAnalysisInput,
            output_schema={
                "type": "object",
                "properties": {
                    "product_name": {"type": "string"},
                    "price_analysis": {"type": "object"},
                    "review_insights": {"type": "object"},
                    "differentiation_opportunities": {"type": "array"},
                    "data_provenance": {"type": "object"},
                },
            },
            executor=executors.competitor_analysis,
            renderer="report",
            credits=1,
        ),
        SkillSpec(
            key="review_mining",
            name="评论痛点挖掘",
            category=_CATEGORY_OPERATION,
            summary="从已有分析报告里归纳评论主题、频次与占比，只读不重算。",
            inputs=ReviewMiningInput,
            output_schema={
                "type": "object",
                "properties": {
                    "total_samples": {"type": "integer"},
                    "pain_points": {"type": "array"},
                    "needs": {"type": "array"},
                    "concerns": {"type": "array"},
                },
            },
            executor=executors.review_mining,
            renderer="table",
            credits=1,
        ),
        SkillSpec(
            key="listing_generation",
            name="Listing 生成",
            category=_CATEGORY_COMPETITOR,
            summary="按商品事实生成标题、五点、描述与 Search Terms，并做事实对齐质检。",
            inputs=ListingGenerationInput,
            output_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "bullets": {"type": "array"},
                    "description": {"type": "string"},
                    "fact_ledger": {"type": "array"},
                    "quality_check": {"type": "object"},
                },
            },
            executor=executors.listing_generation,
            renderer="listing",
            requires=(REQUIRE_LLM,),
            credits=2,
        ),
        SkillSpec(
            key="listing_quality",
            name="Listing 质检",
            category=_CATEGORY_COMPETITOR,
            summary="对已有草稿核对数字与卖点的出处，指出必须改和待确认的地方。",
            inputs=ListingQualityInput,
            output_schema={
                "type": "object",
                "properties": {
                    "passed": {"type": "boolean"},
                    "errors": {"type": "array"},
                    "warnings": {"type": "array"},
                    "pending_confirmations": {"type": "array"},
                },
            },
            executor=executors.listing_quality,
            renderer="table",
            credits=1,
        ),
        SkillSpec(
            key="data_validation",
            name="数据校验",
            category=_CATEGORY_DATA,
            summary="解析 CSV / JSON / Excel，逐行校验字段并定位到具体行与列。",
            inputs=DataValidationInput,
            output_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "total_rows": {"type": "integer"},
                    "valid_rows": {"type": "integer"},
                    "errors": {"type": "array"},
                },
            },
            executor=executors.data_validation,
            renderer="table",
            credits=1,
        ),
        SkillSpec(
            key="profit_calc",
            name="成本与利润测算",
            category=_CATEGORY_FINANCE,
            summary="拆成本、算盈亏平衡与回本销量，给出三档定价和敏感性。",
            inputs=ProfitRequest,
            output_schema={
                "type": "object",
                "properties": {
                    "cost_breakdown": {"type": "array"},
                    "break_even": {"type": "object"},
                    "pricing_tiers": {"type": "array"},
                    "sensitivity": {"type": "array"},
                },
            },
            executor=executors.profit_calc,
            renderer="chart",
            credits=1,
        ),
        SkillSpec(
            key="market_summary",
            name="市场机会总结",
            category=_CATEGORY_COMPETITOR,
            summary="把报告里已经算出来的结论归纳成机会判断，不调用模型、不加新数字。",
            inputs=MarketSummaryInput,
            output_schema={
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "points": {"type": "array"},
                    "data_is_demo": {"type": "boolean"},
                    "limitations": {"type": "array"},
                },
            },
            executor=executors.market_summary,
            renderer="report",
            credits=1,
        ),
    )


SKILL_REGISTRY: dict[str, SkillSpec] = {spec.key: spec for spec in _specs()}


def _spec_view(spec: SkillSpec, tenant_id: str) -> dict[str, Any]:
    return {
        "skill_key": spec.key,
        "tenant_id": "",
        "name": spec.name,
        "summary": spec.summary,
        "category": spec.category,
        "renderer": spec.renderer,
        "requires": list(spec.requires),
        "credits": spec.credits,
        "status": spec.status,
        "version": VERSION,
        "input_schema": spec.inputs.model_json_schema(),
        "output_schema": spec.output_schema,
        "builtin": True,
        # 只有登记在注册表里的能力才可执行；租户自定义定义是纯元数据
        "runnable": True,
    }


def _custom_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "skill_key": row.get("skill_key", ""),
        "tenant_id": row.get("tenant_id", ""),
        "name": row.get("name", ""),
        "summary": row.get("summary", ""),
        "category": "自定义",
        "renderer": "",
        "requires": [],
        "credits": 0,
        "status": row.get("status", ""),
        "version": row.get("version", ""),
        "input_schema": row.get("input_schema") or {},
        "output_schema": row.get("output_schema") or {},
        "builtin": False,
        "runnable": False,
    }


def list_skill_views(db: Any, tenant_id: str) -> list[dict[str, Any]]:
    """内置技能在前，租户自定义在后。

    库里遗留的**内置行**若已不在注册表（例如下线的 ``keyword_layout``），
    这里不返回——下线必须真的看不见，不能只是「新代码不写它了」。
    """
    items = [_spec_view(spec, tenant_id) for spec in SKILL_REGISTRY.values()]
    for row in db.list_skill_definitions(tenant_id):
        if row.get("tenant_id") == "":
            continue
        items.append(_custom_view(row))
    return items


def get_skill_view(db: Any, tenant_id: str, key: str) -> dict[str, Any] | None:
    spec = SKILL_REGISTRY.get(key)
    if spec is not None:
        return _spec_view(spec, tenant_id)
    row = db.get_skill_definition(key, tenant_id)
    if row is None and tenant_id:
        row = db.get_skill_definition(key, "")
    if row is None:
        return None
    if row.get("tenant_id") == "":
        # 平台内置但不在注册表 = 已下线
        return None
    return _custom_view(row)


def seed_rows() -> list[dict[str, Any]]:
    """给 ``agent/registry.seed_registry`` 用的扁平行（保持原有字段名与形状）。

    ``input`` / ``output`` 必须是**序列化后的 JSON 文本**，不是 dict：
    库里的列是文本列（``_definition_row`` 读的时候会 ``json.loads``），
    直接塞 dict 会在写库时被驱动拒掉（``cannot adapt type 'dict'``）。
    """
    rows: list[dict[str, Any]] = []
    for spec in SKILL_REGISTRY.values():
        rows.append(
            {
                "key": spec.key,
                "name": spec.name,
                "summary": spec.summary,
                "input": json.dumps(spec.inputs.model_json_schema(), ensure_ascii=False),
                "output": json.dumps(spec.output_schema, ensure_ascii=False),
                "status": spec.status,
            }
        )
    return rows


__all__ = [
    "SKILL_REGISTRY",
    "VERSION",
    "get_skill_view",
    "list_skill_views",
    "seed_rows",
]
