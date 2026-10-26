"""技能执行与产出落库。

分成两个入口，用途不同，不能混：

- ``execute``：**只执行**。旧 7 节点图用它 —— 图里 ``persist`` 节点统一落库，
  若 analyze 节点自己先存一份报告，失败的任务也会留下半份数据，改变既有语义。
- ``execute_and_persist``：执行 + 落库，供 ``POST /api/skills/{key}/run`` 使用。
  写库路径与 ``/api/analyze``、``/api/listings/generate``、``/api/import`` 完全一致。

产出统一约定：**以下划线开头的键是内部字段**（例如 ``_batch`` 里的完整导入结果），
出接口前由 ``public`` 剥掉，避免把落库用的载荷塞进响应。
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from ..labels import humanize_error
from .base import SkillContext, SkillSpec


# ---------------------------------------------------------------------------
# 产出整形
# ---------------------------------------------------------------------------


def strip_internal(value: Any) -> Any:
    """递归去掉下划线开头的键（只处理 dict / list，其它原样返回）。"""
    if isinstance(value, dict):
        return {
            key: strip_internal(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [strip_internal(item) for item in value]
    return value


def resolve_is_demo(output: Any, depth: int = 0) -> bool:
    """递归判断产出是否基于示例数据。

    三个来源都要看：报告用 ``data_provenance.is_demo``，市场总结用
    ``data_is_demo``，Listing 用 ``data_provenance.is_demo``。任何一层为真即为真。
    """
    if depth > 3 or not isinstance(output, dict):
        return False
    if output.get("is_demo") is True or output.get("data_is_demo") is True:
        return True
    provenance = output.get("data_provenance")
    if isinstance(provenance, dict) and provenance.get("is_demo") is True:
        return True
    for key in ("report", "listing"):
        nested = output.get(key)
        if isinstance(nested, dict) and resolve_is_demo(nested, depth + 1):
            return True
    return False


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------


def _save_report(ctx: SkillContext, output: dict[str, Any]) -> str:
    report_id = output.get("report_id") or uuid.uuid4().hex
    output["report_id"] = report_id
    ctx.db.save_report(
        output,
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        task_id=getattr(ctx.task, "task_id", None),
    )
    return report_id


def _save_listing(ctx: SkillContext, output: dict[str, Any]) -> str:
    listing_id = output.get("listing_id") or uuid.uuid4().hex
    output["listing_id"] = listing_id
    ctx.db.save_listing(
        output,
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        task_id=getattr(ctx.task, "task_id", None),
    )
    return listing_id


def _save_batch(ctx: SkillContext, output: dict[str, Any]) -> str:
    """把校验结果存成可复用的数据批次，供竞品分析按批次取数。"""
    batch = output.get("_batch") or {}
    batch_id = uuid.uuid4().hex
    ctx.db.save_import_batch(
        {
            "batch_id": batch_id,
            "filename": output.get("source_name") or "上传文件",
            "source_format": output.get("source_format") or "",
            "total_rows": output.get("total_rows") or 0,
            "valid_rows": output.get("valid_rows") or 0,
            "errors": [humanize_error(e) for e in (batch.get("errors") or [])],
            "payload": {"batch_id": batch_id, **batch},
        },
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
    )
    output["batch_id"] = batch_id
    return batch_id


#: 需要落库的技能。没有登记的技能产出只存在于响应里（例如利润测算，纯计算不落库）。
ARTIFACT_SAVERS: dict[str, Callable[[SkillContext, dict[str, Any]], str]] = {
    "competitor_analysis": _save_report,
    "listing_generation": _save_listing,
    "data_validation": _save_batch,
}


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------


def execute(spec: SkillSpec, inputs: Any, ctx: SkillContext) -> Any:
    """只执行，不落库。"""
    return spec.executor(ctx, inputs)


def execute_and_persist(
    spec: SkillSpec, inputs: Any, ctx: SkillContext
) -> tuple[Any, str | None]:
    """执行并按技能类型落库，返回 ``(产出, 产物 id)``。"""
    output = execute(spec, inputs, ctx)
    saver = ARTIFACT_SAVERS.get(spec.key)
    if saver is None or not isinstance(output, dict):
        return output, None
    return output, saver(ctx, output)


__all__ = [
    "ARTIFACT_SAVERS",
    "execute",
    "execute_and_persist",
    "resolve_is_demo",
    "strip_internal",
]
