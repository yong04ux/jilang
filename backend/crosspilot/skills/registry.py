"""``SKILL_REGISTRY``：由目录扫描得到的平台能力清单。

唯一真源是 ``skills/catalog/<key>/SKILL.md``，不是这份文件：

- 新增内置技能 = 新增一个目录（``SKILL.md`` + 可选的产出结构）；
- ``load_builtin_catalog`` 启动时扫描，解析头部并懒加载执行器；
- ``GET /api/skills`` 用 ``list_skill_views`` 生成，前端不再硬编码；
- 租户导入的技能存在 ``skill_definitions`` 表里，与内置技能合并展示，
  但**没有执行器**，``runnable`` 如实为 ``False``。

``keyword_layout`` 仍然不上架：没有实现的能力不摆空壳。
"""

from __future__ import annotations

import json
from typing import Any

from .base import SkillSpec
from .importer import read_content
from .loader import load_builtin_catalog

#: 技能定义版本（与 Agent 定义版本分开演进）
VERSION = "1.0.0"

#: 启动时扫描一次；``reload`` 会原地更新这个字典，不替换对象，
#: 因为 ``api/skills.py`` 按值持有了它。
SKILL_REGISTRY: dict[str, SkillSpec] = load_builtin_catalog()


def reload() -> None:
    """重新扫描内置目录（开发期改完 SKILL.md 不用重启进程）。"""
    SKILL_REGISTRY.clear()
    SKILL_REGISTRY.update(load_builtin_catalog())


def get_skill_spec(key: str) -> SkillSpec | None:
    return SKILL_REGISTRY.get((key or "").strip())


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
        "source": "builtin",
        "executor_type": spec.executor_type,
        # 只有绑定执行器的目录技能才可执行
        "runnable": spec.executable,
    }


def _imported_doc(row: dict[str, Any]) -> tuple[str, str]:
    """从库里的原始 SKILL.md 取正文与分类；坏数据不让列表整页崩。"""
    parsed = read_content(row.get("content") or "")
    if parsed is None:
        return "", ""
    return parsed.instructions, parsed.category


def _custom_view(row: dict[str, Any], *, with_body: bool = False) -> dict[str, Any]:
    body, category = _imported_doc(row)
    view = {
        "skill_key": row.get("skill_key", ""),
        "tenant_id": row.get("tenant_id", ""),
        "name": row.get("name", ""),
        "summary": row.get("summary", ""),
        "category": category or "自定义",
        "renderer": "",
        "requires": [],
        "credits": 0,
        "status": row.get("status", ""),
        "version": row.get("version", ""),
        "input_schema": row.get("input_schema") or {},
        "output_schema": row.get("output_schema") or {},
        "builtin": False,
        "source": "imported" if row.get("content") else "custom",
        "executor_type": None,
        # 导入技能只有说明，没有执行器；不能假装能直接运行
        "runnable": False,
    }
    if with_body:
        view["instructions"] = body
    return view


def list_skill_views(db: Any, tenant_id: str) -> list[dict[str, Any]]:
    """内置技能在前，租户导入技能在后。

    库里遗留的**内置行**若已不在目录中（例如下线的 ``keyword_layout``），
    这里不返回——下线必须真的看不见。
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
        view = _spec_view(spec, tenant_id)
        # 正文只在详情里返回：列表带上全文会让响应无谓变大
        view["instructions"] = spec.instructions
        return view
    row = db.get_skill_definition(key, tenant_id)
    if row is None and tenant_id:
        row = db.get_skill_definition(key, "")
    if row is None:
        return None
    if row.get("tenant_id") == "":
        # 平台内置但已不在目录 = 已下线
        return None
    return _custom_view(row, with_body=True)


def seed_rows() -> list[dict[str, Any]]:
    """给 ``agent/registry.seed_registry`` 用的扁平行（保持原有字段名与形状）。

    ``input`` / ``output`` 必须是**序列化后的 JSON 文本**，不是 dict。
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
    "get_skill_spec",
    "get_skill_view",
    "list_skill_views",
    "reload",
    "seed_rows",
]
