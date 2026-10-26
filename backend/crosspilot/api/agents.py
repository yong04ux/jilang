"""会话、审计、审批与 Agent 运行。

三件事的共性：都只读/只写「谁做了什么」这类元数据，不直接产出业务内容。
Agent 运行是唯一的例外 —— 它编排真实业务，但对外仍表现为一个 task_id。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..agent import registry as agent_registry
from ..agent import tools as agent_tools
from ..agent.planner import plan_for, resolve_goal
from ..agent.runtime import AgentRunError, create_agent_task, execute_agent, run_agent
from ..agent.schemas import AgentRunRequest, AgentRunResponse, GoalResolveRequest, GoalResolveResponse
from ..llm.providers import engine_label
from ..services import approvals as approval_service
from ..services import audit
from ..services import conversations as conversation_service
from ..services.queue import TaskCancelled
from ..tenancy import (
    ROLE_MANAGE,
    ROLE_READ,
    ROLE_WRITE,
    TenantContext,
    TenantError,
    require_role,
)
from .deps import ApiContext, get_ctx, require_tenant, require_user

router = APIRouter(tags=["会话/审计/审批"])


# ---------------------------------------------------------------------------
# 会话与消息
# ---------------------------------------------------------------------------


@router.get("/api/conversations")
async def list_conversations(
    limit: int = 50,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_READ)
    return {
        "items": conversation_service.list_conversations(
            api.db, tenant, limit=min(max(limit, 1), 100)
        )
    }


@router.post("/api/conversations")
async def create_conversation(
    payload: dict[str, Any] | None = None,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_WRITE)
    conversation = conversation_service.create_conversation(
        api.db, tenant, (payload or {}).get("title")
    )
    return {"conversation": conversation}


@router.get("/api/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_READ)
    detail = conversation_service.conversation_detail(api.db, tenant, conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return detail


@router.delete("/api/conversations/{conversation_id}")
async def archive_conversation(
    conversation_id: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_WRITE)
    if not conversation_service.archive_conversation(api.db, tenant, conversation_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    api.audit_context(
        tenant,
        audit.ACTION_CONVERSATION_ARCHIVE,
        target_type="conversation",
        target_id=conversation_id,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------


@router.get("/api/audit")
async def list_audit(
    action: str | None = None,
    actor_id: str | None = None,
    limit: int = 100,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """审计日志只追加；仅 admin/owner 可见。"""
    require_role(tenant, ROLE_MANAGE)
    return {
        "items": audit.list_logs(
            api.db,
            tenant.tenant_id,
            limit=min(max(limit, 1), 200),
            action=(action or "").strip() or None,
            actor_id=(actor_id or "").strip() or None,
        )
    }


# ---------------------------------------------------------------------------
# 审批
# ---------------------------------------------------------------------------


@router.get("/api/approvals")
async def list_approvals(
    status: str | None = None,
    limit: int = 50,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_READ)
    return {
        "items": approval_service.list_approvals(
            api.db,
            tenant,
            status=(status or "").strip() or None,
            limit=min(max(limit, 1), 100),
        )
    }


@router.get("/api/approvals/{approval_id}")
async def get_approval(
    approval_id: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_READ)
    approval = approval_service.get_approval(api.db, tenant, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="审批不存在")
    return approval


@router.post("/api/approvals")
async def request_approval(
    payload: dict[str, Any],
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """发起发布审批。注意：审批通过也不会真实发布（平台未接入）。"""
    kind = str(payload.get("kind") or approval_service.KIND_PUBLISH_LISTING)
    if kind != approval_service.KIND_PUBLISH_LISTING:
        raise HTTPException(status_code=400, detail=f"暂不支持审批类型：{kind}")
    listing_id = str(payload.get("listing_id") or "").strip()
    if not listing_id:
        raise HTTPException(status_code=422, detail="这次运行没有关联任何 Listing 草稿")
    try:
        return approval_service.request_publish(
            api.db, tenant, listing_id=listing_id, note=payload.get("note")
        )
    except approval_service.ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except approval_service.ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TenantError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/api/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: str,
    payload: dict[str, Any],
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    try:
        return approval_service.decide(
            api.db,
            tenant,
            approval_id,
            decision=str(payload.get("decision") or ""),
            note=payload.get("note"),
        )
    except approval_service.ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except approval_service.ApprovalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except approval_service.ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TenantError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Agent 注册表
# ---------------------------------------------------------------------------


@router.get("/api/agents")
async def list_agents(
    tenant: TenantContext = Depends(require_tenant), api: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    return {"items": agent_registry.list_agents(api.db, tenant.tenant_id)}


@router.get("/api/agents/{agent_key}")
async def get_agent(
    agent_key: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    agent = agent_registry.get_agent(api.db, agent_key, tenant.tenant_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent 不存在: {agent_key}")
    return agent


@router.get("/api/tools")
async def list_tools(
    tenant: TenantContext = Depends(require_tenant), api: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    return {"items": agent_registry.list_tools(api.db, tenant.tenant_id)}


# ---------------------------------------------------------------------------
# 注册表写入：租户自定义 Agent
#
# 只允许 admin+ 写；只能写当前租户空间，不能改/停用平台内置定义。
# 自定义定义是元数据（列表/详情可见可管理），Agent 运行仍走固定工作流图。
#
# Skills 的读取与执行、以及自定义 Skill 的写入，都在 ``api/skills.py``：
# 能力协议的入口只有一个，避免「列表在 A 文件、执行在 B 文件」再次分叉。
# ---------------------------------------------------------------------------


def _registry_http_error(exc: agent_registry.RegistryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/api/agents", status_code=201)
async def create_tenant_agent(
    payload: dict[str, Any],
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_MANAGE)
    try:
        item = agent_registry.create_agent(api.db, tenant.tenant_id, payload)
    except agent_registry.RegistryError as exc:
        raise _registry_http_error(exc) from exc
    api.audit_context(
        tenant,
        audit.ACTION_AGENT_CREATE,
        target_type="agent",
        target_id=item["agent_key"],
        detail={"version": item.get("version")},
    )
    return item


@router.put("/api/agents/{agent_key}")
async def update_tenant_agent(
    agent_key: str,
    payload: dict[str, Any],
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_MANAGE)
    try:
        item = agent_registry.update_agent(api.db, tenant.tenant_id, agent_key, payload)
    except agent_registry.RegistryError as exc:
        raise _registry_http_error(exc) from exc
    api.audit_context(
        tenant,
        audit.ACTION_AGENT_UPDATE,
        target_type="agent",
        target_id=agent_key,
        detail={"version": item.get("version")},
    )
    return item


@router.delete("/api/agents/{agent_key}")
async def disable_tenant_agent(
    agent_key: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """软删：置为 disabled，不移除历史引用。"""
    require_role(tenant, ROLE_MANAGE)
    try:
        item = agent_registry.disable_agent(api.db, tenant.tenant_id, agent_key)
    except agent_registry.RegistryError as exc:
        raise _registry_http_error(exc) from exc
    api.audit_context(
        tenant,
        audit.ACTION_AGENT_DISABLE,
        target_type="agent",
        target_id=agent_key,
    )
    return {"ok": True, "agent": item}


# ---------------------------------------------------------------------------
# Agent 运行：目标解析与完整工作流（LangGraph）
# ---------------------------------------------------------------------------


@router.post("/api/agent/resolve", response_model=GoalResolveResponse)
async def resolve_goal_endpoint(
    payload: GoalResolveRequest,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> GoalResolveResponse:
    """只解析目标，不执行。供工作台把自然语言预填到参数面板。

    目标解析必须调模型：没有 Key 直接 428，前端据此跳设置页，
    **不再静默降级成规则解析后假装成功**。
    """
    require_role(tenant, ROLE_WRITE)
    _active, _config, provider = api.resolve_llm_provider(user)
    client = provider.chat_client() if hasattr(provider, "chat_client") else None
    resolution = resolve_goal(
        payload.goal,
        client=client,
        fallback_reason=getattr(provider, "fallback_reason", "") or "",
    )
    return GoalResolveResponse(
        spec=resolution.spec.model_dump(),
        degraded=resolution.degraded,
        reason=resolution.reason,
        missing=resolution.missing,
    )


@router.post("/api/agent/runs", response_model=AgentRunResponse)
async def run_agent_endpoint(
    payload: AgentRunRequest,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> AgentRunResponse:
    """执行一次完整 Agent 工作流（LangGraph）。

    - 结构化参数与自然语言目标两个入口都走同一张图；
    - ``async_run=false``（默认）同步返回结果，脚本/测试使用；
    - ``async_run=true`` 立即返回 task_id，工作台据此轮询并支持取消。
    """
    require_role(tenant, ROLE_WRITE)
    if agent_registry.get_agent(api.db, payload.agent_key, tenant.tenant_id) is None:
        raise HTTPException(status_code=404, detail=f"Agent 不存在: {payload.agent_key}")

    api.rate_limit(user, "task.run", api.settings.rate_limit_tasks_per_hour)

    data = payload.model_dump(mode="json")
    goal = (payload.goal or "").strip()
    explicit = payload.model_fields_set
    degraded = False
    degraded_reason = ""
    spec_payload: dict[str, Any] | None = None

    if goal:
        _active, _config, provider = api.build_user_provider(user)
        resolution = resolve_goal(
            goal,
            client=provider.chat_client() if hasattr(provider, "chat_client") else None,
            fallback_reason=getattr(provider, "fallback_reason", "") or "",
        )
        spec = resolution.spec
        spec_payload = spec.model_dump()
        degraded = resolution.degraded
        degraded_reason = resolution.reason
        if not (payload.product_name or "").strip():
            data["product_name"] = spec.product_name
        if "platform" not in explicit:
            data["platform"] = spec.platform
        if "marketplace" not in explicit:
            data["marketplace"] = spec.marketplace
        if "with_listing" not in explicit:
            data["with_listing"] = spec.with_listing
        if "listing_language" not in explicit:
            data["listing_language"] = spec.listing_language

    if payload.agent_key == "competitor_expert":
        data["with_listing"] = False
    data["degraded"] = degraded
    data["degraded_reason"] = degraded_reason

    competitors = data.get("competitors") or []
    if not competitors and payload.import_batch_id:
        try:
            competitors = agent_tools.read_data_asset(
                api.db, tenant.tenant_id, batch_id=payload.import_batch_id
            )
        except Exception as exc:  # noqa: BLE001 - 坏批次按 422 处理
            raise HTTPException(status_code=422, detail=f"读取导入批次失败：{exc}") from exc
        data["competitors"] = competitors
    # 只生成 Listing 的路径不需要竞品：它只读商品事实，不跑竞品分析。
    if not competitors and not data.get("listing_only"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    "缺少竞品数据：目标可以解析，但竞品必须来自导入的文件或显式传入，"
                    "不会凭空生成"
                ),
                "missing": ["competitors"],
                "goal_spec": spec_payload,
            },
        )
    if not (data.get("product_name") or "").strip():
        raise HTTPException(
            status_code=422,
            detail={
                "message": "还没有选商品：先选一个商品，或者写清商品名称再生成。",
                "missing": ["product_name"],
                "goal_spec": spec_payload,
            },
        )

    title_hint = goal or f"{data['product_name']} · Agent 工作流"
    try:
        conversation = conversation_service.ensure_conversation(
            api.db, tenant, payload.conversation_id, title_hint=title_hint
        )
    except conversation_service.ConversationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    user_content = goal or (
        f"分析 {data['product_name']} 的竞品"
        + ("，并生成 Listing" if data.get("with_listing") else "")
    )
    conversation_service.append_message(
        api.db,
        tenant,
        conversation["conversation_id"],
        role="user",
        content=user_content,
        meta={
            "agent_key": payload.agent_key,
            "competitors": len(competitors),
            "with_listing": bool(data.get("with_listing")),
        },
    )

    _active, _config, provider = api.build_user_provider(user)
    engine = engine_label(provider)
    if engine["kind"] == "rule":
        # 没有可用模型就跑规则引擎：结果照出，但必须让用户知道这不是模型写的
        degraded = True
        degraded_reason = degraded_reason or (
            "这次没有用大模型：按规则生成结果。到「设置 → 模型与密钥」配上 API Key 后效果会更好。"
        )
    conversation_id = conversation["conversation_id"]
    plan_preview = plan_for(bool(data.get("with_listing")))

    def completion_message(task_id: str) -> None:
        """任务结束后把结果摘要写回会话（失败/取消也如实标注）。"""
        conversation_service.record_task_result(
            api.db,
            tenant,
            conversation_id,
            task_id,
            fallback_plan=plan_preview,
            degraded=degraded,
        )

    if payload.async_run and not api.settings.force_sync_tasks:
        recorder = create_agent_task(
            db=api.db,
            user_id=user["user_id"],
            tenant_id=tenant.tenant_id,
            payload={**data, "goal": goal},
            title=title_hint[:120],
            conversation_id=conversation_id,
            degraded=degraded,
            queued=True,
        )

        def job() -> None:
            try:
                execute_agent(
                    recorder,
                    db=api.db,
                    provider=provider,
                    payload={**data, "goal": goal},
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
                completion_message(recorder.task_id)

        api.task_queue.submit(recorder.task_id, job)
        api.audit_context(
            tenant,
            audit.ACTION_TASK_RUN,
            target_type="task",
            target_id=recorder.task_id,
            detail={
                "agent_key": payload.agent_key,
                "async": True,
                "degraded": degraded,
                "conversation_id": conversation_id,
            },
            trace_id=recorder.trace_id,
        )
        return AgentRunResponse(
            task_id=recorder.task_id,
            status="queued",
            plan=plan_preview,
            conversation_id=conversation_id,
            engine=engine,
            degraded=degraded,
            degraded_reason=degraded_reason,
        )

    try:
        task_id, final = run_agent(
            db=api.db,
            provider=provider,
            user_id=user["user_id"],
            tenant_id=tenant.tenant_id,
            payload={**data, "goal": goal},
            title=title_hint[:120],
            conversation_id=conversation_id,
            degraded=degraded,
        )
    except TaskCancelled as exc:
        raise HTTPException(status_code=409, detail="任务已取消") from exc
    except AgentRunError as exc:
        raise HTTPException(status_code=502, detail=f"Agent 执行失败：{exc}") from exc

    completion_message(task_id)
    api.audit_context(
        tenant,
        audit.ACTION_TASK_RUN,
        target_type="task",
        target_id=task_id,
        detail={
            "agent_key": payload.agent_key,
            "async": False,
            "degraded": degraded,
            "conversation_id": conversation_id,
        },
    )
    return AgentRunResponse(
        task_id=task_id,
        status="succeeded",
        plan=final.get("plan") or [],
        report=final.get("report"),
        listing=final.get("listing"),
        summary=final.get("summary"),
        checks=final.get("checks"),
        quality=final.get("quality"),
        conversation_id=conversation_id,
        engine=engine,
        degraded=degraded,
        degraded_reason=degraded_reason,
    )


__all__ = ["router"]
