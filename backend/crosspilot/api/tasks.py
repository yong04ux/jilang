"""任务中心：列表、详情（含结果块）、取消、重试。

任务详情里的 ``result`` 是给前端"结果面板"用的：plan / summary / checks /
quality / report / listing 全在这里，前端不需要再发 N 个请求拼。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..agent import errors as agent_errors
from ..agent import workflows
from ..agent.contracts import SkillError
from ..agent.runtime import AgentRunError, create_agent_task, execute_agent
from ..agent.schemas import ConfirmRequest, RetryRequest
from ..market.competitor_provider import MODE_IMPORTED, build_competitor_provider
from ..services import audit, combined_runs, conversations
from ..services.tasks import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_WAITING_INPUT,
    STATUS_WAITING_REVIEW,
    TaskCancelled,
    TaskRecorder,
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
        "engine": output.get("engine"),
        "report": None,
        "listing": None,
        # 组合工作流额外字段：没有时是 None，不编空对象
        "report_id": output.get("report_id"),
        "listing_id": output.get("listing_id"),
        "analysis_outcome": output.get("analysis_outcome"),
        "provenance": output.get("provenance"),
        "message": output.get("message"),
        "decision": output.get("decision"),
    }
    if output.get("report_id"):
        result["report"] = api.db.get_report(
            output["report_id"], user_id=user["user_id"], tenant_id=tenant.tenant_id
        )
    if output.get("listing_id"):
        result["listing"] = api.db.get_listing(
            output["listing_id"], user_id=user["user_id"], tenant_id=tenant.tenant_id
        )
    if output.get("skill_key"):
        # 技能运行：渲染方式与示例数据标记随产出一起回传，页面据此选渲染器并挂横幅。
        # 大产出（报告 / 草稿）不进这里，完整数据仍从 result.report / result.listing 取。
        result["skill"] = {
            "skill_key": output.get("skill_key"),
            "renderer": output.get("renderer") or "",
            "is_demo": bool(output.get("is_demo")),
            "result_ref": output.get("result_ref"),
            "output": output.get("output"),
        }
    return {
        "task": task,
        "steps": api.db.list_task_steps(task_id, user["user_id"], tenant.tenant_id),
        "result": result,
        # 暂停中的待确认内容（缺什么、影响什么、确认令牌）。没有就是 None，
        # 而不是空对象——前端据此判断"要不要弹确认"。
        "pending": (task.get("output") or {}).get("pending"),
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
    resume: bool = True,
    body: RetryRequest | None = None,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """重试失败/取消/待补充的 Agent 任务：新建任务（``retry_of`` 指向原任务）并异步执行。

    - ``resume=true``（默认）：复用原任务**已成功步骤**的输出（含 LLM 生成的 Listing），
      只从失败点继续；命中复用的步骤在时间线上标注「复用上次成功步骤（未重跑）」。
      复用前会校验**输入指纹**与**工作流版本**，不匹配就整任务重跑。
    - ``resume=false``：整任务从头重跑。
    - 可选请求体 ``{"overrides": {...}}``：补充/修改资料类字段（如 ``own_specs``）。
      改了资料会导致指纹变化，因此不会复用旧中间结果。
    """
    require_role(tenant, ROLE_WRITE)
    overrides = dict(body.overrides) if body else {}
    task = api.db.get_task(task_id, user["user_id"], tenant.tenant_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    status = task["status"]
    if status not in {STATUS_FAILED, STATUS_CANCELLED, STATUS_WAITING_INPUT, STATUS_PARTIAL}:
        raise HTTPException(
            status_code=409,
            detail=f"只有失败、已取消、等待补充资料或待复核的任务可以重试（当前：{status}）",
        )
    if task.get("type") != "agent_workflow":
        raise HTTPException(
            status_code=409,
            detail="当前仅支持 Agent 工作流任务重试；其他任务请从对应页面重新发起",
        )
    payload = dict(task.get("input") or {})
    # 允许在重试时补充/修改资料类字段（例如"缺规格 → 补上再来"）。
    # 改了就等于换了输入，下面自然不会再复用旧中间结果。
    if overrides:
        payload.update(overrides)
    if not payload.get("product_name") or not payload.get("competitors"):
        raise HTTPException(
            status_code=422,
            detail="原任务缺商品名称或竞品，没法直接重跑；请回工作台重新填一次",
        )

    resume_from: dict[str, Any] = {}
    reuse_note = ""
    if resume:
        # 两道闸：输入指纹 + 工作流版本。任意一项对不上就不复用——
        # 用旧答案回答新问题比多算一次贵得多，而且界面上看不出来。
        allowed, reuse_note = workflows.can_reuse(
            stored_fingerprint=task.get("input_fingerprint"),
            stored_version=task.get("workflow_version"),
            payload=payload,
        )
        if allowed:
            # 落库与收尾节点**绝不复用**：复用它们等于重试时既不保存新结果、
            # 也不落任务状态，任务会停在 running。
            not_reusable = {"persist", "persist_result", "settle", "finalize"}
            resume_from = {
                node: out
                for node, out in api.db.step_outputs(task_id, tenant.tenant_id).items()
                if node and node not in not_reusable
            }

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
            execute_agent(
                recorder,
                db=api.db,
                provider=provider,
                payload=payload,
                resume_from=resume_from or None,
            )
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
        detail={
            "retry_of": task_id,
            "previous_status": status,
            "resumed_steps": sorted(resume_from),
        },
        trace_id=recorder.trace_id,
    )
    return {
        "ok": True,
        "task_id": recorder.task_id,
        "retry_of": task_id,
        "status": "queued",
        "resumed_steps": sorted(resume_from),
        # 没有复用时要说明原因，否则用户只会看到"重试了但没省事"
        "reuse_skipped_reason": "" if resume_from else reuse_note,
    }


@router.post("/api/tasks/{task_id}/confirm")
async def confirm_task_endpoint(
    task_id: str,
    payload: ConfirmRequest,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """组合工作流暂停点的确认。

    四道校验，顺序有讲究（**先校验、后抢占**，否则抢占完发现不能跑，
    任务就卡在 running 了）：

    1. 任务归属：``get_task`` 带 user + tenant，跨用户/跨租户一律 404；
    2. 任务状态：必须是 ``waiting_review``，重复提交自然被 409 挡掉；
    3. 确认内容：``confirmation_token`` 必须与暂停时一致，
       防止拿着过期的缺失清单确认另一次暂停；
    4. 可恢复性：checkpoint 真的在。内存 checkpointer 在进程重启后会丢，
       这时明确报错而不是让 LangGraph 从空状态重跑。

    最后用 ``claim_task_review`` 做原子抢占，双击确认只会成功一次。
    """
    require_role(tenant, ROLE_WRITE)
    if payload.decision not in {combined_runs.DECISION_CONTINUE, combined_runs.DECISION_CANCEL}:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_decision",
                "message": "decision 只能是 continue 或 cancel",
                "category": "validation_error",
            },
        )

    task = api.db.get_task(task_id, user["user_id"], tenant.tenant_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    if task.get("status") != STATUS_WAITING_REVIEW:
        # 已确认过一次、已取消、或本来就是终态：都不接受再次确认
        raise HTTPException(
            status_code=409,
            detail=f"任务当前状态（{task.get('status')}）不接受确认",
        )

    pending = (task.get("output") or {}).get("pending") or {}
    expected = str(pending.get("confirmation_token") or "")
    if not expected:
        raise HTTPException(status_code=409, detail="任务缺少待确认内容，无法确认")
    if payload.confirmation_token != expected:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "confirmation_stale",
                "message": "确认内容已变化（可能是任务被重跑过），请刷新后重新确认",
                "category": "validation_error",
            },
        )

    _active, _config, provider = api.build_user_provider(user)
    resumable = combined_runs.has_pending_checkpoint(
        tenant.tenant_id, task_id, provider=provider
    )
    if payload.decision == combined_runs.DECISION_CONTINUE and not resumable:
        raise HTTPException(
            status_code=409,
            detail="工作流状态已失效（服务可能重启过），无法从断点继续；请重新发起任务",
        )

    # 原子抢占：同一份 checkpoint 不能被两个请求同时恢复
    if not api.db.claim_task_review(task_id, tenant_id=tenant.tenant_id):
        raise HTTPException(status_code=409, detail="该任务已被处理")

    fresh = api.db.get_task(task_id, user["user_id"], tenant.tenant_id) or task
    recorder = TaskRecorder.resume(api.db, fresh)

    if not resumable:
        # 取消分支不依赖 checkpoint：状态直接落终态即可
        recorder.cancel(reason="工作流状态已失效，按取消处理")
        return {"task_id": task_id, "status": "cancelled", "decision": payload.decision}

    try:
        state = combined_runs.resume(
            api.db,
            tenant_id=tenant.tenant_id,
            user_id=user["user_id"],
            task_id=task_id,
            decision=payload.decision,
            provider=provider,
            competitor_provider=build_competitor_provider(
                MODE_IMPORTED, db=api.db, tenant_id=tenant.tenant_id
            ),
            persist=True,
            task=recorder,
        )
    except SkillError as exc:
        info = agent_errors.classify(exc)
        recorder.fail(code=info.task_code, message=info.message[:500])
        raise HTTPException(status_code=exc.status_code, detail=info.as_payload()) from exc
    except Exception as exc:  # noqa: BLE001 - 兜底也要有分类
        info = agent_errors.classify(exc)
        recorder.fail(code=info.task_code, message=info.message[:500])
        raise HTTPException(status_code=info.http_status, detail=info.as_payload()) from exc

    status = combined_runs.apply_result(recorder, state, api.db)
    api.audit_context(
        tenant,
        audit.ACTION_TASK_CONFIRM,
        target_type="task",
        target_id=task_id,
        detail={"decision": payload.decision, "status": status},
        trace_id=recorder.trace_id,
    )
    return {
        "task_id": task_id,
        "status": status,
        "decision": payload.decision,
        "analysis_outcome": state.get("analysis_outcome"),
        "message": state.get("message") or "",
    }


@router.get("/api/tasks/{task_id}/trace")
async def task_trace_endpoint(
    task_id: str,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """按任务 ID 还原执行链。

    一次返回三样东西，都从持久化数据里读，不额外埋点：

    - ``chain``：按 seq 排列的步骤，每步带耗时、状态、以及**这一步发生的模型调用**；
    - ``totals``：耗时、token、尝试次数、失败节点；
    - ``error``：任务级错误码与文案（能直接判断是限流、超时还是配置问题）。

    只返回元数据，不含 prompt / 响应正文——正文里可能有租户的商品资料。
    """
    task = api.db.get_task(task_id, user["user_id"], tenant.tenant_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    steps = api.db.list_task_steps(task_id, user["user_id"], tenant.tenant_id)
    calls = api.db.list_llm_calls(task_id, tenant.tenant_id)

    by_node: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        by_node.setdefault(call.get("node") or "", []).append(call)

    chain: list[dict[str, Any]] = []
    failed_node = ""
    for step in steps:
        node = step.get("node") or ""
        node_calls = by_node.get(node, [])
        if step.get("status") == "failed" and not failed_node:
            failed_node = node
        chain.append(
            {
                "seq": step.get("seq"),
                "node": node,
                "name": step.get("name"),
                "status": step.get("status"),
                "detail": step.get("detail"),
                "started_at": step.get("started_at"),
                "finished_at": step.get("finished_at"),
                "duration_ms": step.get("duration_ms"),
                # 模型调用明细：哪个模型、几秒、多少 token、重试几次、成败
                "llm_calls": [
                    {
                        "provider": call.get("provider"),
                        "model": call.get("model"),
                        "latency_ms": call.get("latency_ms"),
                        "prompt_tokens": call.get("prompt_tokens"),
                        "completion_tokens": call.get("completion_tokens"),
                        "attempts": call.get("attempts"),
                        "ok": bool(call.get("ok")),
                        "error_code": call.get("error_code") or "",
                    }
                    for call in node_calls
                ],
                "is_failed": step.get("status") == "failed",
            }
        )

    total_duration = sum(int(s.get("duration_ms") or 0) for s in steps)
    return {
        "task": {
            "task_id": task["task_id"],
            "type": task.get("type"),
            "status": task.get("status"),
            "title": task.get("title"),
            "trace_id": task.get("trace_id"),
            "created_at": task.get("created_at"),
            "started_at": task.get("started_at"),
            "finished_at": task.get("finished_at"),
            "retry_of": task.get("retry_of"),
        },
        "chain": chain,
        "totals": {
            "steps": len(chain),
            "duration_ms": total_duration,
            "llm_calls": len(calls),
            "llm_attempts": sum(int(c.get("attempts") or 0) for c in calls),
            "tokens": sum(
                int(c.get("prompt_tokens") or 0) + int(c.get("completion_tokens") or 0)
                for c in calls
            ),
            "failed_node": failed_node,
        },
        # 任务级错误：定位"是哪一类问题"靠这两个字段，不用去翻日志
        "error": (
            {
                "code": task.get("error_code"),
                "message": task.get("error_message"),
                "is_failed_step": bool(failed_node),
            }
            if task.get("error_code")
            else None
        ),
    }


__all__ = ["router"]
