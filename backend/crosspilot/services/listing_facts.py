"""Listing 生成的前置资料整理。

为什么单独一层
==============

要把 Listing 流程拆成子图，节点应该**只做编排**：
取资料、判缺失、调模型、校验、落库，每一步的判断都该是可单测的纯函数。

这些判断若埋在 ``engine/listing_llm.generate_listing`` 里，「缺哪些必填属性」
这种确定性事实就只能靠"跑一遍生成"才知道。

这里的四个函数**都不调模型、不访问数据库**：

- ``resolve_product_facts``：把商品资料抽成事实摘要（fact_id / 缺失项 / 台账）
- ``load_brand_rules``：站点规则、禁用词、长度上限
- ``load_market_insights``：从竞品报告取差异化方向与关键词（可选）
- ``check_required_facts``：判断"能不能开始写"，不能就说明缺什么

``resolve_product_facts`` 与 ``generate_listing`` 都会调用 ``build_fact_sheet``。
这是刻意的重复计算：``build_fact_sheet`` 是纯函数且便宜，而把 FactSheet 塞进
图状态会破坏"状态必须可序列化"。
"""

from __future__ import annotations

from typing import Any

from ..engine.facts import CRITICAL_ATTRIBUTES, FactKind, build_fact_sheet
from ..engine.rules import get_rules
from ..market.marketplaces import get_marketplace
from ..models import OwnProduct


class ListingFactsError(ValueError):
    """商品资料无法解析成事实（属于输入问题）。"""


#: 缺失项的中文名，用于面向用户的提示。与 engine 的 MISSING_LABELS 同源意图，
#: 但那一个是生成期的私有常量，这里需要独立给出（避免 import 私有符号）。
_MISSING_LABELS = {
    "size": "尺寸",
    "material": "材质",
    "capacity": "容量",
    "color": "颜色",
    "weight": "重量",
    "quantity": "数量",
}


def resolve_product_facts(product_payload: dict[str, Any]) -> dict[str, Any]:
    """把商品资料整理成事实摘要。**不编造任何字段**：缺什么就报什么。"""
    try:
        product = OwnProduct(**product_payload)
    except Exception as exc:  # noqa: BLE001 - pydantic 细节由分类层处理
        raise ListingFactsError("商品资料不完整，无法整理事实") from exc

    sheet = build_fact_sheet(product)
    return {
        "product": product.model_dump(mode="json"),
        "facts": sheet.ledger(),
        "fact_count": sheet.count,
        "missing_critical": list(sheet.missing_critical),
        "warnings": list(sheet.warnings),
        # 台账之外的"有没有事实可写"判据：属性 + 卖点都为空就等于没有素材
        "has_attribute_facts": bool(sheet.of_kind(FactKind.ATTRIBUTE)),
        "has_feature_facts": bool(sheet.of_kind(FactKind.FEATURE)),
    }


def load_brand_rules(marketplace: str, banned_terms: list[str] | None = None) -> dict[str, Any]:
    """加载站点规则与禁用词。纯配置读取，不涉及模型。"""
    profile = get_marketplace(marketplace)
    ruleset = get_rules()
    banned = ruleset.banned_terms(banned_terms or [])
    return {
        "marketplace": profile.code,
        "language": profile.language,
        "label": profile.label,
        "title_max_chars": profile.title_max_chars,
        "bullet_max_chars": profile.bullet_max_chars,
        "bullet_count": profile.bullet_count,
        "description_max_chars": profile.description_max_chars,
        "search_terms_max_bytes": profile.search_terms_max_bytes,
        "compliance_notes": list(profile.compliance_notes),
        # 禁用词条数够用就行，不把整张规则表塞进状态
        "banned_term_count": len(getattr(banned, "terms", []) or []),
    }


def load_market_insights(report: dict[str, Any] | None) -> dict[str, Any]:
    """从竞品报告取可用的差异化方向。没有报告就返回空，不猜。"""
    if not report:
        return {"report_id": None, "differentiation": [], "keywords": [], "notes": ["没有可用的竞品分析"]}

    differentiation: list[str] = []
    for item in report.get("differentiation_opportunities", []) or []:
        angle = item.get("angle") if isinstance(item, dict) else None
        if angle:
            differentiation.append(str(angle))

    keywords = [
        str(k.get("keyword"))
        for k in (report.get("keywords") or [])
        if isinstance(k, dict) and k.get("keyword")
    ]
    notes: list[str] = []
    provenance = report.get("data_provenance") or {}
    if provenance.get("is_demo"):
        notes.append("竞品结论基于示例数据")

    return {
        "report_id": report.get("report_id"),
        "differentiation": differentiation[:6],
        "keywords": keywords[:15],
        "notes": notes,
    }


def check_required_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """能不能开始写？

    判定刻意**保守**：只有"一条属性事实和一条卖点事实都没有"时才阻塞。
    部分必填属性缺失（例如有容量但没颜色）不阻塞——它会进 ``pending_confirmations``
    与质量警告，让人看到"这里没写"，而不是把整个任务停掉。
    这条边界很重要：以前的行为对缺失项一律放行并标注，若改成"缺一项就停"，
    演示流程和既有 458 项测试里的正常路径会全部变成待补充。
    """
    missing = list(facts.get("missing_critical") or [])
    has_any = bool(facts.get("has_attribute_facts") or facts.get("has_feature_facts"))

    blocking = not has_any
    return {
        "can_generate": not blocking,
        "blocking": blocking,
        "missing": missing,
        "missing_labels": [_MISSING_LABELS.get(item, item) for item in missing],
        "reason": (
            "商品资料里没有可引用的属性或卖点，无法在不编造的前提下撰写文案"
            if blocking
            else ""
        ),
    }


def critical_attribute_names() -> list[str]:
    """面向前端提示：这套系统认为哪些属性是必填的。"""
    return [_MISSING_LABELS.get(key, key) for key in CRITICAL_ATTRIBUTES]


__all__ = [
    "ListingFactsError",
    "check_required_facts",
    "critical_attribute_names",
    "load_brand_rules",
    "load_market_insights",
    "resolve_product_facts",
]
