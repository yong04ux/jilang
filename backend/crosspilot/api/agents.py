"""会话、审计、审批与 Agent 运行。

三件事的共性：都只读/只写「谁做了什么」这类元数据，不直接产出业务内容。
Agent 运行是唯一的例外 —— 它编排真实业务，但对外仍表现为一个 task_id。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..agent import definitions as skill_definitions
from ..agent import errors as agent_errors
from ..agent import registry as agent_registry
from ..agent import workflows
from ..agent.contracts import DEP_LLM, SkillContext, SkillError
from ..agent.planner import plan_for, resolve_goal
from ..llm.providers import engine_label
from ..market.competitor_provider import (
    MODE_IMPORTED,
    CompetitorProviderError,
    CompetitorQuery,
    build_competitor_provider,
)
from ..agent.runtime import AgentRunError, create_agent_task, execute_agent, run_agent
from ..agent.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    CombinedRunRequest,
    GoalResolveRequest,
    GoalResolveResponse,
)
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
        raise HTTPException(status_code=422, detail="缺少 listing_id")
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


def _merge_skill(row: dict[str, Any]) -> dict[str, Any]:
    """把注册表行与代码里的执行器声明合并成一个视图。

    ``skill_definitions`` 表回答"注册了什么"，``SKILL_DEFINITIONS`` 回答
    "能不能跑"。两者缺一不可：只返回前者，用户看不出哪条点进去跑不了；
    只返回后者，租户自定义技能就消失了（它们只存在于表里）。
    """
    key = str(row.get("skill_key") or "")
    merged = dict(row)
    merged["key"] = key
    definition = skill_definitions.get_definition(key)

    if definition is None:
        # 租户自定义技能：有元数据、没有执行器。如实标注，不留想象空间。
        merged.update(
            {
                "executor_type": None,
                "enabled": row.get("status") != "disabled",
                "executable": False,
                "required_permissions": [],
                "dependencies": [],
                "timeout_seconds": None,
                "max_retries": None,
                "note": "自定义技能只有定义，尚未绑定执行器。",
            }
        )
        return merged

    view = definition.as_view()
    for field in (
        "executor_type",
        "enabled",
        "executable",
        "required_permissions",
        "dependencies",
        "timeout_seconds",
        "max_retries",
        "note",
    ):
        merged[field] = view[field]
    # 输入契约以代码里的 Pydantic 模型为准：表里的手写 JSON 会随版本漂移
    merged["input_schema"] = view["input_schema"]
    merged["output_schema"] = view["output_schema"] or merged.get("output_schema") or {}
    return merged


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


# 技能目录与直连执行统一由 api/skills.py 提供（main 分支的技能平台）：
# /api/skills、/api/skills/{key}、POST /api/skills/{key}/run 及自定义技能增删改。
# 这里曾有一份重复实现，合并时删除——两套同名路由只会让"到底谁在响应"变成谜。


@router.get("/api/tools")
async def list_tools(
    tenant: TenantContext = Depends(require_tenant), api: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    return {"items": agent_registry.list_tools(api.db, tenant.tenant_id)}


# ---------------------------------------------------------------------------
# 注册表写入：租户自定义 Agent / Skill
#
# 只允许 admin+ 写；只能写当前租户空间，不能改/停用平台内置定义。
# 自定义定义是元数据（列表/详情可见可管理），Agent 运行仍走固定工作流图。
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


@router.post("/api/skills", status_code=201)
async def create_tenant_skill(
    payload: dict[str, Any],
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_MANAGE)
    try:
        item = agent_registry.create_skill(api.db, tenant.tenant_id, payload)
    except agent_registry.RegistryError as exc:
        raise _registry_http_error(exc) from exc
    api.audit_context(
        tenant,
        audit.ACTION_SKILL_CREATE,
        target_type="skill",
        target_id=item["skill_key"],
        detail={"version": item.get("version")},
    )
    return item


@router.put("/api/skills/{skill_key}")
async def update_tenant_skill(
    skill_key: str,
    payload: dict[str, Any],
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_MANAGE)
    try:
        item = agent_registry.update_skill(api.db, tenant.tenant_id, skill_key, payload)
    except agent_registry.RegistryError as exc:
        raise _registry_http_error(exc) from exc
    api.audit_context(
        tenant,
        audit.ACTION_SKILL_UPDATE,
        target_type="skill",
        target_id=skill_key,
        detail={"version": item.get("version")},
    )
    return item


@router.delete("/api/skills/{skill_key}")
async def disable_tenant_skill(
    skill_key: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_MANAGE)
    try:
        item = agent_registry.disable_skill(api.db, tenant.tenant_id, skill_key)
    except agent_registry.RegistryError as exc:
        raise _registry_http_error(exc) from exc
    api.audit_context(
        tenant,
        audit.ACTION_SKILL_DISABLE,
        target_type="skill",
        target_id=skill_key,
    )
    return {"ok": True, "skill": item}


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

    # BYOK：Agent 工作流必然要调模型（目标解析 / Listing 生成），
    # 没有 Key 就明确 428，而不是降级成规则引擎后显示"成功"。
    if api.settings.require_api_key:
        api.resolve_llm_provider(user)

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
    if not competitors or payload.import_batch_id:
        # 竞品来源统一走 Provider。导入是当前唯一可用实现；
        # 真实数据源未接入时 Provider 会明确报错，不会退回导入数据冒充实采。
        try:
            competitor_provider = build_competitor_provider(
                MODE_IMPORTED, db=api.db, tenant_id=tenant.tenant_id
            )
            competitor_data = competitor_provider.fetch(
                CompetitorQuery(
                    product_name=str(data.get("product_name") or ""),
                    platform=str(data.get("platform") or "amazon"),
                    marketplace=str(data.get("marketplace") or "US"),
                    category=data.get("category"),
                    batch_id=payload.import_batch_id,
                    rows=competitors or None,
                )
            )
        except CompetitorProviderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        competitors = competitor_data.rows
        data["competitors"] = competitors
        # 来源只在实际来自导入时改写；调用方显式指定的优先级更高
        if "data_source" not in explicit:
            data["data_source"] = competitor_data.source
    if not competitors and not payload.listing_only:
        # 这是「缺输入」而不是「参数写错」：目标能解析，缺的是数据本身，
        # 所以分类用 missing_input，界面可以引导去导入而不是让用户改参数。
        # 例外：``listing_only=true`` 只写文案，本来就不需要竞品数据。
        raise HTTPException(
            status_code=422,
            detail=agent_errors.make(
                agent_errors.ErrorCategory.MISSING_INPUT,
                message=(
                    "缺少竞品数据：目标可以解析，但竞品必须来自导入的文件或显式传入，"
                    "不会凭空生成"
                ),
                code="competitors_missing",
                detail={"missing": ["competitors"], "goal_spec": spec_payload},
            ).as_payload(),
        )
    if not (data.get("product_name") or "").strip():
        raise HTTPException(
            status_code=422,
            detail=agent_errors.make(
                agent_errors.ErrorCategory.VALIDATION_ERROR,
                message="缺少商品名称",
                code="product_name_missing",
                detail={"errors": [{"field": "product_name", "message": "必填"}]},
            ).as_payload(),
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
    # 用的是规则引擎就必须让用户知道：结果照出，但不能让人以为这是模型写的
    if engine_label(provider)["kind"] == "rule":
        degraded = True
        degraded_reason = degraded_reason or (
            "这次没有用大模型：按规则生成结果。到「设置 → 模型与密钥」配上 API Key 后效果会更好。"
        )
    conversation_id = conversation["conversation_id"]
    plan_preview = plan_for(bool(data.get("with_listing")))
    # 按步骤分配模型：analyze / listing 可能各用不同配置（配置级 task_overrides）

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
            engine=engine_label(provider),
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
            competitor_provider=build_competitor_provider(
                MODE_IMPORTED, db=api.db, tenant_id=tenant.tenant_id
            ),
        )
    except TaskCancelled as exc:
        raise HTTPException(status_code=409, detail="任务已取消") from exc
    except AgentRunError as exc:
        # 状态码与文案都由统一分类决定，不再一律 502
        info = exc.info
        raise HTTPException(status_code=info.http_status, detail=info.as_payload()) from exc

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
    spec = workflows.choose(data)
    payload_view = workflows.response_payload(final, spec)
    record = api.db.get_task(task_id, user["user_id"], tenant.tenant_id) or {}
    return AgentRunResponse(
        task_id=task_id,
        # 状态读库：走完修订循环仍未过质检是 partial，停在确认点是 waiting_for_review
        status=record.get("status") or "succeeded",
        plan=payload_view["plan"],
        report=payload_view["report"],
        listing=payload_view["listing"],
        summary=payload_view["summary"],
        checks=payload_view["checks"],
        quality=payload_view["quality"],
        conversation_id=conversation_id,
        engine=engine_label(provider),
        degraded=degraded,
        degraded_reason=degraded_reason,
        # 暂停时把待确认内容一并返回，调用方不必再查任务详情
        pending=(
            workflows.pending_payload(final) if workflows.is_paused(final) else None
        ),
    )


@router.post("/api/agent/combined/runs")
async def run_combined_endpoint(
    payload: CombinedRunRequest,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """组合工作流：竞品分析 → （partial 时暂停等确认）→ Listing 生成。

    下**和 ``/api/agent/runs`` 走同一条路**：``with_listing=true`` 就是
    分派到组合工作流。这个端点只是"参数更窄、不接自然语言目标"的入口，
    不再自己另起一套编排——那正是收敛前的毛病。

    同步返回：
    - 一次跑完 → succeeded / partial / waiting_for_input
    - 停在确认点 → ``waiting_for_review``，``pending`` 带待确认内容
    """
    require_role(tenant, ROLE_WRITE)
    # 无 Key 也用规则引擎跑完并如实标注引擎，不在这里拦人（main 的 BYOK 策略）
    _active, _config, provider = api.resolve_llm_provider(user)
    api.rate_limit(user, "task.run", api.settings.rate_limit_tasks_per_hour)

    # with_listing 是唯一分派判据，由这里显式置位
    request = {**payload.model_dump(mode="json"), "with_listing": True}
    try:
        task_id, final = run_agent(
            db=api.db,
            provider=provider,
            user_id=user["user_id"],
            tenant_id=tenant.tenant_id,
            payload=request,
            title=f"组合工作流：{payload.product_name}"[:120],
            competitor_provider=build_competitor_provider(
                MODE_IMPORTED, db=api.db, tenant_id=tenant.tenant_id
            ),
        )
    except TaskCancelled as exc:
        raise HTTPException(status_code=409, detail="任务已取消") from exc
    except AgentRunError as exc:
        info = exc.info
        raise HTTPException(status_code=info.http_status, detail=info.as_payload()) from exc

    spec = workflows.choose(request)
    record = api.db.get_task(task_id, user["user_id"], tenant.tenant_id) or {}
    paused = workflows.is_paused(final)
    api.audit_context(
        tenant,
        audit.ACTION_TASK_RUN,
        target_type="task",
        target_id=task_id,
        detail={"workflow": spec.kind, "paused_for_review": paused},
    )
    return {
        "task_id": task_id,
        "status": record.get("status") or "succeeded",
        "plan": spec.plan(),
        "pending": workflows.pending_payload(final) if paused else None,
        "analysis_outcome": final.get("analysis_outcome"),
        "message": final.get("message") or "",
    }
