"""任务中心：列表、详情（含结果块）、取消、重试。

任务详情里的 ``result`` 是给前端"结果面板"用的：plan / summary / checks /
quality / report / listing 全在这里，前端不需要再发 N 个请求拼。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..agent.runtime import AgentRunError, create_agent_task, execute_agent
from ..services import audit, conversations
from ..services.tasks import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    TaskCancelled,
    cancel_task,
)
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


@router.post("/api/tasks/{task_id}/retry")
async def retry_task_endpoint(
    task_id: str,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """重试失败/取消的 Agent 任务：新建任务（``retry_of`` 指向原任务）并异步重跑。

    语义边界（诚实说明）：这是**整任务重跑**，不重用未完成步骤的中间输出——
    步骤级续跑需要 ``task_steps`` 持久化每步 output，见 ``docs/11-backlog.md`` 的 P2。
    """
    require_role(tenant, ROLE_WRITE)
    task = api.db.get_task(task_id, user["user_id"], tenant.tenant_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    status = task["status"]
    if status not in {STATUS_FAILED, STATUS_CANCELLED}:
        raise HTTPException(
            status_code=409,
            detail=f"只有失败或取消的任务可以重试（当前：{status}）",
        )
    if task.get("type") != "agent_workflow":
        raise HTTPException(
            status_code=409,
            detail="当前仅支持 Agent 工作流任务重试；其他任务请从对应页面重新发起",
        )
    payload = dict(task.get("input") or {})
    if not payload.get("product_name") or not payload.get("competitors"):
        raise HTTPException(
            status_code=422,
            detail="原任务缺少重跑所需的 product_name 或 competitors",
        )

    _active, _config, provider = api.build_user_provider(user)
    conversation_id = task.get("conversation_id")
    degraded = bool(task.get("degraded"))
    title = f"重试：{task.get('title') or 'Agent 任务'}"[:120]

    recorder = create_agent_task(
        db=api.db,
        user_id=user["user_id"],
        tenant_id=tenant.tenant_id,
        payload=payload,
        title=title,
        conversation_id=conversation_id,
        degraded=degraded,
        queued=True,
        retry_of=task_id,
    )

    def job() -> None:
        try:
            execute_agent(recorder, db=api.db, provider=provider, payload=payload)
        except TaskCancelled:
            pass  # Runtime 已把任务落成 cancelled
        except AgentRunError:
            pass  # Runtime 已写 error_code / error_message
        except Exception as exc:  # noqa: BLE001 - 兜底，任务不能停在 running
            recorder.fail(
                code="worker_error",
                message=f"{type(exc).__name__}: {exc}"[:500],
            )
        finally:
            if conversation_id:
                conversations.record_task_result(
                    api.db,
                    tenant,
                    conversation_id,
                    recorder.task_id,
                    fallback_plan=None,
                    degraded=degraded,
                )

    api.task_queue.submit(recorder.task_id, job)
    api.audit_context(
        tenant,
        audit.ACTION_TASK_RETRY,
        target_type="task",
        target_id=recorder.task_id,
        detail={"retry_of": task_id, "previous_status": status},
        trace_id=recorder.trace_id,
    )
    return {
        "ok": True,
        "task_id": recorder.task_id,
        "retry_of": task_id,
        "status": "queued",
    }


__all__ = ["router"]
