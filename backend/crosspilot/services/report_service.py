"""报告服务（阶段 E2/E3）：查询与导出。

导出的唯一实现放在这里，路由只做参数绑定；Markdown/JSON/CSV 三种格式
共享同一份结构化数据，不各自拼装。
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from ..persistence.db import Database
from ..tenancy import TenantContext

MEDIA_TYPES = {
    "md": "text/markdown; charset=utf-8",
    "markdown": "text/markdown; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
}


class ExportError(ValueError):
    """不支持的导出格式。"""


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def _escape_cell(value: Any) -> str:
    return _fmt(value).replace("|", "\\|").replace("\n", " ")


def to_markdown(report: dict[str, Any]) -> str:
    provenance = report.get("data_provenance") or {}
    lines: list[str] = []
    lines.append(f"# {report.get('product_name', '未命名商品')} · 竞品分析")
    lines.append("")
    lines.append(
        f"- 平台/站点：{report.get('platform', '—')} / {report.get('marketplace', '—')}"
    )
    lines.append(f"- 数据来源：{provenance.get('data_source', '—')}")
    lines.append(f"- 示例数据：{'是（不可用于真实经营决策）' if provenance.get('is_demo') else '否'}")
    lines.append(
        f"- 竞品数：{provenance.get('competitor_count', '—')} · "
        f"评论样本：{provenance.get('review_sample_count', '—')} · "
        f"关键词：{provenance.get('keyword_count', '—')}"
    )
    lines.append(f"- 生成引擎：{report.get('engine', '—')} {report.get('engine_version', '')}".rstrip())
    lines.append("")

    price = report.get("price_analysis")
    if price:
        lines.append("## 价格分析")
        lines.append("")
        lines.append(
            f"竞品区间 {_fmt(price.get('min_price'))}–{_fmt(price.get('max_price'))}，"
            f"中位 {_fmt(price.get('median_price'))}，"
            f"自有价格 {_fmt(price.get('own_price'))}（{_fmt(price.get('own_position'))}）"
        )
        lines.append("")

    snapshots = report.get("competitor_snapshots") or []
    if snapshots:
        lines.append("## 竞品对比")
        lines.append("")
        lines.append("| 竞品 | 品牌 | 价格 | 评分 | 评论数 | 样本 | 完整度 |")
        lines.append("|---|---|---|---|---|---|---|")
        for item in snapshots:
            lines.append(
                "| "
                + " | ".join(
                    _escape_cell(v)
                    for v in (
                        item.get("name"),
                        item.get("brand"),
                        item.get("price"),
                        item.get("rating"),
                        item.get("review_count"),
                        item.get("review_samples"),
                        item.get("data_completeness"),
                    )
                )
                + " |"
            )
        lines.append("")

    insights = report.get("review_insights") or {}
    pains = insights.get("pain_points") or []
    if pains:
        lines.append("## 评论痛点")
        lines.append("")
        lines.append("| 主题 | 频次 | 占比 | 说明 |")
        lines.append("|---|---|---|---|")
        for pain in pains:
            lines.append(
                "| "
                + " | ".join(
                    _escape_cell(v)
                    for v in (
                        pain.get("label"),
                        pain.get("frequency"),
                        pain.get("share"),
                        pain.get("description"),
                    )
                )
                + " |"
            )
        lines.append("")

    opportunities = report.get("differentiation_opportunities") or []
    if opportunities:
        lines.append("## 差异化机会")
        lines.append("")
        for item in opportunities:
            lines.append(
                f"- **{item.get('angle', '')}**（优先级 {_fmt(item.get('priority'))}，"
                f"置信度 {_fmt(item.get('confidence'))}）：{item.get('rationale', '')}"
            )
        lines.append("")

    keyword = report.get("keyword_analysis") or {}
    if keyword.get("available"):
        lines.append("## 关键词")
        lines.append("")
        for item in (keyword.get("opportunities") or [])[:20]:
            score = item.get("opportunity_score")
            lines.append(
                f"- {item.get('keyword')}：搜索量 {_fmt(item.get('search_volume'))}，"
                f"排名 {_fmt(item.get('rank'))}，机会分 {_fmt(score)}"
            )
        lines.append("")

    warnings = report.get("warnings") or []
    limitations = report.get("limitations") or []
    if warnings or limitations:
        lines.append("## 限制与提示")
        lines.append("")
        for item in warnings:
            lines.append(f"- 警告：{item}")
        for item in limitations:
            lines.append(f"- 限制：{item}")
        lines.append("")
    return "\n".join(lines)


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def to_csv(report: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "name",
            "brand",
            "price",
            "currency",
            "rating",
            "review_count",
            "review_samples",
            "data_completeness",
            "missing_fields",
            "key_features",
            "is_demo",
        ]
    )
    for item in report.get("competitor_snapshots") or []:
        writer.writerow(
            [
                item.get("name"),
                item.get("brand"),
                item.get("price"),
                item.get("currency"),
                item.get("rating"),
                item.get("review_count"),
                item.get("review_samples"),
                item.get("data_completeness"),
                "|".join(item.get("missing_fields") or []),
                "|".join(item.get("key_features") or []),
                item.get("is_demo"),
            ]
        )
    return "\ufeff" + output.getvalue()


def export_report(
    report: dict[str, Any], fmt: str = "md"
) -> tuple[str, str, str]:
    """返回 (filename, content, media_type)。"""
    normalized = (fmt or "md").lower()
    if normalized not in MEDIA_TYPES:
        raise ExportError(f"不支持的导出格式：{fmt}（可选 md / json / csv）")
    stem = (report.get("product_name") or "report").replace("/", "-")[:40]
    filename = f"{stem}-{report.get('report_id') or 'report'}.{normalized}"
    if normalized in {"md", "markdown"}:
        content = to_markdown(report)
    elif normalized == "json":
        content = to_json(report)
    else:
        content = to_csv(report)
    return filename, content, MEDIA_TYPES[normalized]


def get_report(
    db: Database, ctx: TenantContext, report_id: str
) -> dict[str, Any] | None:
    return db.get_report(report_id, user_id=ctx.user_id, tenant_id=ctx.tenant_id)


def list_reports(
    db: Database, ctx: TenantContext, limit: int = 50
) -> list[dict[str, Any]]:
    return db.list_reports(limit=limit, user_id=ctx.user_id, tenant_id=ctx.tenant_id)


__all__ = [
    "ExportError",
    "MEDIA_TYPES",
    "export_report",
    "get_report",
    "list_reports",
    "to_csv",
    "to_json",
    "to_markdown",
]
