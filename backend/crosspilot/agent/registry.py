"""Agent / Skill / Tool 注册表。

定义分两类：
- **平台内置**（``tenant_id = ""``）：随代码发布，启动时幂等写入；
- **租户自定义**（``tenant_id = <id>``）：留给后续版本，当前只读。

用空字符串而不是 NULL 表示内置，因为复合主键里的 NULL 互不相等，
会导致每次启动重复插入。
"""

from __future__ import annotations

import json
import re
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


# ---------------------------------------------------------------------------
# 租户自定义 Agent / Skill（写入）
#
# 边界（诚实说明）：
# - 只允许写当前租户空间（tenant_id=当前租户），**不能改/停用平台内置**（tenant_id=""）；
# - 自定义定义是**元数据**：列表/详情可见、可管理；但 Agent 运行仍走固定的
#   7 节点 LangGraph（skill_keys/tool_keys 目前是展示信息，不是自定义执行图）。
# - 删除采用软删（status="disabled"），保留审计与历史引用。
# ---------------------------------------------------------------------------

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_DEF_STATUSES = {"available", "beta", "dev", "disabled"}


class RegistryError(RuntimeError):
    """注册表写入错误；``status_code`` 可直接交给 HTTP 层。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _bump_version(version: str) -> str:
    parts = (version or "1.0.0").split(".")
    if parts and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return f"{version}.1"


def _pick(data: dict[str, Any], key: str, default: Any) -> Any:
    value = data.get(key)
    return default if value is None else value


def _validate_common(
    key: str,
    name: Any,
    summary: Any,
    status: Any,
    input_schema: Any,
    output_schema: Any,
) -> None:
    if not _KEY_RE.match(str(key or "")):
        raise RegistryError("key 必须以小写字母开头，只含小写字母/数字/下划线（2–64 位）")
    if not str(name or "").strip():
        raise RegistryError("name 不能为空")
    if not str(summary or "").strip():
        raise RegistryError("summary 不能为空")
    if status not in _DEF_STATUSES:
        raise RegistryError(f"status 只能是 {sorted(_DEF_STATUSES)} 之一")
    if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
        raise RegistryError("input_schema / output_schema 必须是 JSON 对象")


def _agent_row(
    *,
    key: str,
    tenant_id: str,
    name: str,
    summary: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    skill_keys: list[str],
    tool_keys: list[str],
    version: str,
    status: str,
) -> dict[str, Any]:
    return {
        "agent_key": key,
        "tenant_id": tenant_id,
        "name": name,
        "summary": summary,
        "description": description or "",
        "input_schema": json.dumps(input_schema or {}, ensure_ascii=False),
        "output_schema": json.dumps(output_schema or {}, ensure_ascii=False),
        "skill_keys": json.dumps(list(skill_keys or []), ensure_ascii=False),
        "tool_keys": json.dumps(list(tool_keys or []), ensure_ascii=False),
        "version": version,
        "status": status,
        "updated_at": _now(),
    }


def _skill_row(
    *,
    key: str,
    tenant_id: str,
    name: str,
    summary: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    version: str,
    status: str,
) -> dict[str, Any]:
    return {
        "skill_key": key,
        "tenant_id": tenant_id,
        "name": name,
        "summary": summary,
        "input_schema": json.dumps(input_schema or {}, ensure_ascii=False),
        "output_schema": json.dumps(output_schema or {}, ensure_ascii=False),
        "version": version,
        "status": status,
        "updated_at": _now(),
    }


def _require_tenant_space(tenant_id: str) -> None:
    if not tenant_id or tenant_id == BUILTIN:
        raise RegistryError("缺少租户上下文，不能写入平台内置空间")


def _validate_key_lists(data: dict[str, Any]) -> None:
    for field in ("skill_keys", "tool_keys"):
        value = data.get(field)
        if value is not None and not isinstance(value, list):
            raise RegistryError(f"{field} 必须是字符串数组")


def create_agent(db: Database, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
    _require_tenant_space(tenant_id)
    key = str(_pick(data, "key", data.get("agent_key")) or "").strip()
    status = str(_pick(data, "status", "available"))
    _validate_common(
        key,
        data.get("name"),
        data.get("summary"),
        status,
        data.get("input_schema") or {},
        data.get("output_schema") or {},
    )
    _validate_key_lists(data)
    if db.get_agent_definition(key, BUILTIN) is not None:
        raise RegistryError(f"不能覆盖平台内置 Agent：{key}", 409)
    if db.get_agent_definition(key, tenant_id) is not None:
        raise RegistryError(f"Agent 已存在：{key}（请用 PUT 更新）", 409)
    db.upsert_agent(
        _agent_row(
            key=key,
            tenant_id=tenant_id,
            name=str(data["name"]).strip(),
            summary=str(data["summary"]).strip(),
            description=str(_pick(data, "description", "") or ""),
            input_schema=data.get("input_schema") or {},
            output_schema=data.get("output_schema") or {},
            skill_keys=data.get("skill_keys") or [],
            tool_keys=data.get("tool_keys") or [],
            version=str(_pick(data, "version", "1.0.0")),
            status=status,
        )
    )
    return db.get_agent_definition(key, tenant_id) or {}


def update_agent(db: Database, tenant_id: str, key: str, data: dict[str, Any]) -> dict[str, Any]:
    _require_tenant_space(tenant_id)
    existing = db.get_agent_definition(key, tenant_id)
    if existing is None:
        if db.get_agent_definition(key, BUILTIN) is not None:
            raise RegistryError(f"平台内置 Agent 不可修改：{key}", 403)
        raise RegistryError(f"Agent 不存在：{key}", 404)
    _validate_key_lists(data)
    merged = {
        "name": str(_pick(data, "name", existing.get("name"))).strip(),
        "summary": str(_pick(data, "summary", existing.get("summary"))).strip(),
        "description": _pick(data, "description", existing.get("description")) or "",
        "input_schema": _pick(data, "input_schema", existing.get("input_schema")) or {},
        "output_schema": _pick(data, "output_schema", existing.get("output_schema")) or {},
        "skill_keys": _pick(data, "skill_keys", existing.get("skill_keys")) or [],
        "tool_keys": _pick(data, "tool_keys", existing.get("tool_keys")) or [],
        "status": _pick(data, "status", existing.get("status")) or "available",
    }
    _validate_common(
        key,
        merged["name"],
        merged["summary"],
        merged["status"],
        merged["input_schema"],
        merged["output_schema"],
    )
    version = str(_pick(data, "version", _bump_version(existing.get("version") or "1.0.0")))
    db.upsert_agent(_agent_row(key=key, tenant_id=tenant_id, version=version, **merged))
    return db.get_agent_definition(key, tenant_id) or {}


def disable_agent(db: Database, tenant_id: str, key: str) -> dict[str, Any]:
    _require_tenant_space(tenant_id)
    existing = db.get_agent_definition(key, tenant_id)
    if existing is None:
        if db.get_agent_definition(key, BUILTIN) is not None:
            raise RegistryError(f"平台内置 Agent 不可停用：{key}", 403)
        raise RegistryError(f"Agent 不存在：{key}", 404)
    db.upsert_agent(
        _agent_row(
            key=key,
            tenant_id=tenant_id,
            name=existing.get("name") or key,
            summary=existing.get("summary") or "",
            description=existing.get("description") or "",
            input_schema=existing.get("input_schema") or {},
            output_schema=existing.get("output_schema") or {},
            skill_keys=existing.get("skill_keys") or [],
            tool_keys=existing.get("tool_keys") or [],
            version=existing.get("version") or "1.0.0",
            status="disabled",
        )
    )
    return db.get_agent_definition(key, tenant_id) or {}


def create_skill(db: Database, tenant_id: str, data: dict[str, Any]) -> dict[str, Any]:
    _require_tenant_space(tenant_id)
    key = str(_pick(data, "key", data.get("skill_key")) or "").strip()
    status = str(_pick(data, "status", "available"))
    _validate_common(
        key,
        data.get("name"),
        data.get("summary"),
        status,
        data.get("input_schema") or {},
        data.get("output_schema") or {},
    )
    if db.get_skill_definition(key, BUILTIN) is not None:
        raise RegistryError(f"不能覆盖平台内置技能：{key}", 409)
    if db.get_skill_definition(key, tenant_id) is not None:
        raise RegistryError(f"技能已存在：{key}（请用 PUT 更新）", 409)
    db.upsert_skill(
        _skill_row(
            key=key,
            tenant_id=tenant_id,
            name=str(data["name"]).strip(),
            summary=str(data["summary"]).strip(),
            input_schema=data.get("input_schema") or {},
            output_schema=data.get("output_schema") or {},
            version=str(_pick(data, "version", "1.0.0")),
            status=status,
        )
    )
    return db.get_skill_definition(key, tenant_id) or {}


def update_skill(db: Database, tenant_id: str, key: str, data: dict[str, Any]) -> dict[str, Any]:
    _require_tenant_space(tenant_id)
    existing = db.get_skill_definition(key, tenant_id)
    if existing is None:
        if db.get_skill_definition(key, BUILTIN) is not None:
            raise RegistryError(f"平台内置技能不可修改：{key}", 403)
        raise RegistryError(f"技能不存在：{key}", 404)
    merged = {
        "name": str(_pick(data, "name", existing.get("name"))).strip(),
        "summary": str(_pick(data, "summary", existing.get("summary"))).strip(),
        "input_schema": _pick(data, "input_schema", existing.get("input_schema")) or {},
        "output_schema": _pick(data, "output_schema", existing.get("output_schema")) or {},
        "status": _pick(data, "status", existing.get("status")) or "available",
    }
    _validate_common(
        key,
        merged["name"],
        merged["summary"],
        merged["status"],
        merged["input_schema"],
        merged["output_schema"],
    )
    version = str(_pick(data, "version", _bump_version(existing.get("version") or "1.0.0")))
    db.upsert_skill(
        _skill_row(key=key, tenant_id=tenant_id, version=version, **merged)
    )
    return db.get_skill_definition(key, tenant_id) or {}


def disable_skill(db: Database, tenant_id: str, key: str) -> dict[str, Any]:
    _require_tenant_space(tenant_id)
    existing = db.get_skill_definition(key, tenant_id)
    if existing is None:
        if db.get_skill_definition(key, BUILTIN) is not None:
            raise RegistryError(f"平台内置技能不可停用：{key}", 403)
        raise RegistryError(f"技能不存在：{key}", 404)
    db.upsert_skill(
        _skill_row(
            key=key,
            tenant_id=tenant_id,
            name=existing.get("name") or key,
            summary=existing.get("summary") or "",
            input_schema=existing.get("input_schema") or {},
            output_schema=existing.get("output_schema") or {},
            version=existing.get("version") or "1.0.0",
            status="disabled",
        )
    )
    return db.get_skill_definition(key, tenant_id) or {}


__all__ = [
    "AGENTS",
    "BUILTIN",
    "SKILLS",
    "TOOLS",
    "VERSION",
    "RegistryError",
    "create_agent",
    "create_skill",
    "disable_agent",
    "disable_skill",
    "get_agent",
    "get_skill",
    "list_agents",
    "list_skills",
    "list_tools",
    "seed_registry",
    "update_agent",
    "update_skill",
]
