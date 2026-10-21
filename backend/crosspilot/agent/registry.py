"""Agent / Skill / Tool 注册表。

定义分两类：
- **平台内置**（``tenant_id = ""``）：随代码发布，启动时幂等写入；
- **租户自定义**（``tenant_id = <id>``）：留给后续版本，当前只读。

用空字符串而不是 NULL 表示内置，因为复合主键里的 NULL 互不相等，
会导致每次启动重复插入。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..persistence.db import Database

BUILTIN = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _schema(properties: dict[str, str], required: list[str] | None = None) -> str:
    return json.dumps(
        {
            "type": "object",
            "properties": {k: {"type": v} for k, v in properties.items()},
            "required": required or [],
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 定义数据（与代码里的真实能力一一对应）
# ---------------------------------------------------------------------------

SKILLS: list[dict[str, Any]] = [
    {
        "key": "data_validation",
        "name": "数据校验与导入",
        "summary": "解析 CSV/JSON/Excel，逐行校验字段并定位错误。",
        "input": _schema({"file": "string", "format": "string"}, ["file"]),
        "output": _schema({"rows": "integer", "valid": "integer", "errors": "array"}),
        "status": "available",
    },
    {
        "key": "competitor_analysis",
        "name": "竞品分析",
        "summary": "价格统计、卖点覆盖、评论主题与差异化机会，全部为确定性计算。",
        "input": _schema({"product_name": "string", "competitors": "array"}, ["product_name", "competitors"]),
        "output": _schema({"report": "object"}),
        "status": "available",
    },
    {
        "key": "review_mining",
        "name": "评论痛点挖掘",
        "summary": "从评论样本识别痛点、低星主题、需求与购买顾虑，附原文引用。",
        "input": _schema({"reviews": "array"}),
        "output": _schema({"pain_points": "array", "needs": "array"}),
        "status": "available",
    },
    {
        "key": "market_summary",
        "name": "市场机会总结",
        "summary": "把报告里的结构化结论归纳成机会判断，只引用已有证据，不推断销量。",
        "input": _schema({"report": "object"}, ["report"]),
        "output": _schema({"summary": "object"}),
        "status": "available",
    },
    {
        "key": "listing_generation",
        "name": "Listing 生成",
        "summary": "基于事实台账生成标题/五点/描述/Search Terms，并做事实对齐质检。",
        "input": _schema({"product": "object", "report_id": "string"}, ["product"]),
        "output": _schema({"listing": "object"}),
        "status": "available",
    },
    {
        "key": "keyword_layout",
        "name": "关键词布局",
        "summary": "无搜索量数据时只做词表整理与布局建议，不计算机会分。",
        "input": _schema({"keywords": "array"}),
        "output": _schema({"search_terms": "string"}),
        "status": "dev",
    },
]

TOOLS: list[dict[str, Any]] = [
    {
        "key": "read_data_asset",
        "name": "读取数据资产",
        "summary": "读取显式传入的竞品行，或按 batch_id 读取本租户的导入批次；不编造数据。",
        "input": _schema({"batch_id": "string", "competitors": "array"}),
        "output": _schema({"competitors": "array"}),
    },
    {
        "key": "run_competitor_analysis",
        "name": "运行竞品分析",
        "summary": "调用 analysis.run_analysis，返回结构化报告。",
        "input": _schema({"request": "object"}),
        "output": _schema({"report": "object"}),
    },
    {
        "key": "generate_listing",
        "name": "生成 Listing",
        "summary": "调用 listing_llm.generate_listing，返回草稿与质检结果。",
        "input": _schema({"request": "object", "report": "object"}),
        "output": _schema({"listing": "object"}),
    },
    {
        "key": "run_quality_check",
        "name": "质量检查",
        "summary": "汇总质检问题、区块长度与待确认项。",
        "input": _schema({"listing": "object"}),
        "output": _schema({"passed": "boolean", "issues": "array"}),
    },
]

AGENTS: list[dict[str, Any]] = [
    {
        "key": "main",
        "name": "激浪主控 Agent",
        "summary": "解析目标、编排 Skills、交付结构化结果。",
        "description": (
            "目标解析优先调用模型（失败或未配置时降级为规则解析，并在任务上标 degraded）。"
            "执行节点由确定性规则决定，因此质检不会被跳过；报告与草稿会落库并可追溯。"
        ),
        "input": _schema(
            {"product_name": "string", "competitors": "array", "with_listing": "boolean", "goal": "string"},
            ["product_name", "competitors"],
        ),
        "output": _schema({"report": "object", "listing": "object", "summary": "object"}),
        "skills": ["data_validation", "competitor_analysis", "review_mining", "market_summary", "listing_generation"],
        "tools": ["read_data_asset", "run_competitor_analysis", "generate_listing", "run_quality_check"],
        "status": "available",
    },
    {
        "key": "competitor_expert",
        "name": "竞品分析专家",
        "summary": "只做竞品与评论洞察，输出证据分级报告。",
        "description": "适合只想要市场判断、不生成文案的场景；运行时不生成 Listing。",
        "input": _schema({"product_name": "string", "competitors": "array"}, ["product_name", "competitors"]),
        "output": _schema({"report": "object"}),
        "skills": ["competitor_analysis", "review_mining", "market_summary"],
        "tools": ["run_competitor_analysis"],
        "status": "available",
    },
    {
        "key": "listing_expert",
        "name": "Listing 专家",
        "summary": "基于事实台账撰写文案，并做事实对齐质检。",
        "description": "需要已确认的商品事实；缺少规格时会进入待确认，不会编造。",
        "input": _schema({"product": "object", "report_id": "string"}, ["product"]),
        "output": _schema({"listing": "object"}),
        "skills": ["listing_generation"],
        "tools": ["generate_listing", "run_quality_check"],
        "status": "beta",
    },
]

VERSION = "0.3.0"


def seed_registry(db: Database) -> None:
    """幂等写入平台内置定义。"""
    now = _now()
    for skill in SKILLS:
        db.upsert_skill(
            {
                "skill_key": skill["key"],
                "tenant_id": BUILTIN,
                "name": skill["name"],
                "summary": skill["summary"],
                "input_schema": skill["input"],
                "output_schema": skill["output"],
                "version": VERSION,
                "status": skill["status"],
                "updated_at": now,
            }
        )
    for tool in TOOLS:
        db.upsert_tool(
            {
                "tool_key": tool["key"],
                "tenant_id": BUILTIN,
                "name": tool["name"],
                "summary": tool["summary"],
                "input_schema": tool["input"],
                "output_schema": tool["output"],
                "version": VERSION,
                "status": "available",
                "updated_at": now,
            }
        )
    for agent in AGENTS:
        db.upsert_agent(
            {
                "agent_key": agent["key"],
                "tenant_id": BUILTIN,
                "name": agent["name"],
                "summary": agent["summary"],
                "description": agent["description"],
                "input_schema": agent["input"],
                "output_schema": agent["output"],
                "skill_keys": json.dumps(agent["skills"]),
                "tool_keys": json.dumps(agent["tools"]),
                "version": VERSION,
                "status": agent["status"],
                "updated_at": now,
            }
        )


def get_agent(db: Database, key: str, tenant_id: str = BUILTIN) -> dict[str, Any] | None:
    row = db.get_agent_definition(key, tenant_id)
    if row is None and tenant_id:
        row = db.get_agent_definition(key, BUILTIN)
    return row


def list_agents(db: Database, tenant_id: str = BUILTIN) -> list[dict[str, Any]]:
    return db.list_agent_definitions(tenant_id)


def get_skill(db: Database, key: str, tenant_id: str = BUILTIN) -> dict[str, Any] | None:
    row = db.get_skill_definition(key, tenant_id)
    if row is None and tenant_id:
        row = db.get_skill_definition(key, BUILTIN)
    return row


def list_skills(db: Database, tenant_id: str = BUILTIN) -> list[dict[str, Any]]:
    return db.list_skill_definitions(tenant_id)


def list_tools(db: Database, tenant_id: str = BUILTIN) -> list[dict[str, Any]]:
    return db.list_tool_definitions(tenant_id)


__all__ = [
    "AGENTS",
    "BUILTIN",
    "SKILLS",
    "TOOLS",
    "VERSION",
    "get_agent",
    "get_skill",
    "list_agents",
    "list_skills",
    "list_tools",
    "seed_registry",
]
