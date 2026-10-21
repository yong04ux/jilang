"""任务中心：列表、详情（含结果块）、取消。

任务详情里的 ``result`` 是给前端"结果面板"用的：plan / summary / checks /
quality / report / listing 全在这里，前端不需要再发 N 个请求拼。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..services import audit
from ..services.tasks import cancel_task
from ..tenancy import ROLE_WRITE, TenantContext, require_role
from .deps import ApiContext, get_ctx, require_tenant, require_user

router = APIRouter(tags=["任务中心"])


@router.get("/api/tasks")
async def list_tasks(
    status: str | None = None,
    q: str | None = None,
    limit: int = 50,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    return {
        "items": api.db.list_tasks(
            user["user_id"],
            status=(status or "").strip() or None,
            query=(q or "").strip() or None,
            limit=min(max(limit, 1), 200),
            tenant_id=tenant.tenant_id,
        ),
        "stats": api.db.task_stats(user["user_id"], tenant_id=tenant.tenant_id),
    }


@router.get("/api/tasks/{task_id}")
async def get_task(
    task_id: str,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    task = api.db.get_task(task_id, user["user_id"], tenant.tenant_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    output = task.get("output") or {}
    result: dict[str, Any] = {
        "plan": output.get("plan") or [],
        "summary": output.get("summary"),
        "checks": output.get("checks"),
        "quality": output.get("quality"),
        "degraded": bool(output.get("degraded") or task.get("degraded")),
        "degraded_reason": output.get("degraded_reason") or "",
        "report": None,
        "listing": None,
    }
    if output.get("report_id"):
        result["report"] = api.db.get_report(
            output["report_id"], user_id=user["user_id"], tenant_id=tenant.tenant_id
        )
    if output.get("listing_id"):
        result["listing"] = api.db.get_listing(
            output["listing_id"], user_id=user["user_id"], tenant_id=tenant.tenant_id
        )
    return {
        "task": task,
        "steps": api.db.list_task_steps(task_id, user["user_id"], tenant.tenant_id),
        "result": result,
    }


@router.post("/api/tasks/{task_id}/cancel")
async def cancel_task_endpoint(
    task_id: str,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """取消是异步的：running 任务先进入 cancelling，下一个检查点落终态。"""
    require_role(tenant, ROLE_WRITE)
    result, message = cancel_task(
        api.db,
        user["user_id"],
        task_id,
        tenant.tenant_id,
        queue=api.task_queue,
    )
    if result == "not_found":
        raise HTTPException(status_code=404, detail=message)
    if result == "conflict":
        raise HTTPException(status_code=409, detail=message)
    api.audit_context(
        tenant,
        audit.ACTION_TASK_CANCEL,
        target_type="task",
        target_id=task_id,
        detail={"message": message},
    )
    return {
        "ok": True,
        "detail": message,
        "task": api.db.get_task(task_id, user["user_id"], tenant.tenant_id),
    }


__all__ = ["router"]
