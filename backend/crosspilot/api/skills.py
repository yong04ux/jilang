"""技能（能力协议）的读取、写入与统一执行入口。

为什么要有 ``POST /api/skills/{key}/run``
=========================================
如果每个能力各自写一套执行路径（任务记录、BYOK、审计、落库），
能力一多就会变成 N 套平行实现。

这里把「跑一个能力」收敛成一个入口，判定顺序固定：

    登录 → 角色 → 技能存在 → 参数校验 → 依赖（requires）→ 限流 → 执行

顺序不是随手排的：参数错误应当先于「没配 Key」暴露，否则用户配完 Key
还会再撞一次 422，白折腾一轮。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from ..agent import registry as agent_registry
from ..labels import humanize_message
from ..llm.providers import ProviderError
from ..skills import REQUIRE_LLM, SKILL_REGISTRY
from ..skills import registry as skills_registry
from ..llm.providers import engine_label
from ..skills import runtime as skills_runtime
from ..skills.base import (
    SkillError,
    SkillInputError,
    SkillPayloadTooLarge,
    SkillResourceMissing,
)
from ..services import audit
from ..services.tasks import STATUS_QUEUED, STATUS_RUNNING, TaskRecorder
from ..tenancy import ROLE_MANAGE, ROLE_WRITE, TenantContext, require_role
from .deps import ApiContext, get_ctx, require_tenant, require_user
from .handlers import run_guarded
from .helpers import validation_errors

router = APIRouter(tags=["技能"])

#: 产出过大、只回 id 的技能（完整数据走 /api/reports、/api/listings 取）
_HEAVY_OUTPUT = {"competitor_analysis", "listing_generation"}


# ---------------------------------------------------------------------------
# 读：列表与详情都由注册表生成，前端不再硬编码技能清单
# ---------------------------------------------------------------------------


@router.get("/api/skills")
async def list_skills(
    tenant: TenantContext = Depends(require_tenant), api: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    return {"items": skills_registry.list_skill_views(api.db, tenant.tenant_id)}


@router.get("/api/skills/{skill_key}")
async def get_skill(
    skill_key: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    skill = skills_registry.get_skill_view(api.db, tenant.tenant_id, skill_key)
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    return skill


# ---------------------------------------------------------------------------
# 写：租户自定义技能（纯元数据，不可执行）
# ---------------------------------------------------------------------------


def _registry_http_error(exc: agent_registry.RegistryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


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
# 运行
# ---------------------------------------------------------------------------


def _subject(spec_key: str, inputs: Any) -> str:
    """给任务标题用的对象名。只取已经填好的字段，没有就留空。"""
    if spec_key == "listing_generation":
        product = getattr(inputs, "product", None)
        return getattr(product, "name", "") or ""
    if spec_key == "data_validation":
        return getattr(inputs, "filename", "") or ""
    return getattr(inputs, "product_name", "") or ""


def _payload_preview(inputs: Any) -> dict[str, Any]:
    """任务入参留痕：只留能看懂又不会把整份文件写进库的字段。"""
    if hasattr(inputs, "model_dump"):
        dumped = inputs.model_dump(mode="json", exclude_none=True)
    else:
        dumped = {}
    dumped.pop("content_base64", None)
    dumped.pop("competitors", None)
    dumped.pop("report", None)
    dumped.pop("listing", None)
    dumped.pop("analysis_report", None)
    return dumped


def _task_output(spec, output: Any, ref: str | None) -> dict[str, Any]:
    public = skills_runtime.strip_internal(output)
    is_heavy = spec.key in _HEAVY_OUTPUT
    return {
        "skill_key": spec.key,
        "renderer": spec.renderer,
        "is_demo": skills_runtime.resolve_is_demo(output),
        "result_ref": ref,
        # 大产出只留 id，避免任务列表与轮询响应被几百 KB 的 JSON 拖着走
        "output": None if is_heavy else public,
        "report_id": public.get("report_id") if isinstance(public, dict) else None,
        "listing_id": public.get("listing_id") if isinstance(public, dict) else None,
    }


def _http_error(exc: Exception) -> HTTPException:
    """把执行期异常翻译成用户能看懂的响应。不把堆栈或模块名甩给界面。"""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, (SkillResourceMissing, SkillInputError, SkillPayloadTooLarge)):
        return HTTPException(status_code=exc.status_code, detail={"message": exc.message})
    if isinstance(exc, ProviderError):
        return HTTPException(
            status_code=503,
            detail={"message": "模型服务暂时不可用，请稍后再试或检查密钥配置"},
        )
    if isinstance(exc, ValidationError):
        return HTTPException(
            status_code=422,
            detail={
                "message": "提交的内容有几处需要修正",
                "errors": validation_errors(exc),
            },
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=422, detail={"message": humanize_message(str(exc))}
        )
    return HTTPException(
        status_code=502, detail={"message": "这次运行没有完成，可以重试一次"}
    )


@router.post("/api/skills/{skill_key}/run")
async def run_skill(
    skill_key: str,
    payload: dict[str, Any],
    async_run: bool = False,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> Any:
    """统一执行入口。

    - ``async_run=false``（默认）：同步返回产出，脚本与测试使用；
    - ``async_run=true``：返回 ``{task_id, status:"queued", plan}``，页面轮询任务。

    两条路径共用同一个 executor 与同一段落库逻辑，进度不伪造。
    """
    require_role(tenant, ROLE_WRITE)
    spec = SKILL_REGISTRY.get(skill_key)
    if spec is None:
        raise HTTPException(status_code=404, detail="技能不存在")

    # 参数校验先于依赖判定：先告诉用户「哪一格填错了」，再谈缺不缺 Key
    try:
        inputs = spec.inputs.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "提交的内容有几处需要修正",
                "errors": validation_errors(exc),
            },
        ) from exc

    if REQUIRE_LLM in spec.requires:
        _active, config, provider = api.resolve_llm_provider(user)
    else:
        _active, config, provider = api.build_user_provider(user)
    # 步骤说明里不复述 "deepseek/deepseek-flash" 这种内部写法，只说人话：
    # 这次是规则引擎算的，还是大模型写的。
    engine = engine_label(provider)
    provider_note = engine["label"]

    api.rate_limit(user, "task.run", api.settings.rate_limit_tasks_per_hour)

    subject = _subject(spec.key, inputs)
    title = f"{spec.name}：{subject}" if subject else spec.name
    is_async = bool(async_run) and not api.settings.force_sync_tasks
    started = time.perf_counter()

    recorder = TaskRecorder(
        api.db,
        user["user_id"],
        "skill_run",
        title,
        origin="form",
        payload=_payload_preview(inputs),
        tenant_id=tenant.tenant_id,
        initial_status=STATUS_QUEUED if is_async else STATUS_RUNNING,
    )

    def context():
        from ..skills.base import SkillContext

        return SkillContext(
            db=api.db,
            user_id=user["user_id"],
            tenant_id=tenant.tenant_id,
            provider=provider,
            settings=api.settings,
            task=recorder,
        )

    # ---- 异步路径 ------------------------------------------------------
    if is_async:
        recorder.open()

        def job() -> None:
            recorder.mark_running()
            with recorder.step(spec.name, provider_note):
                output, ref = skills_runtime.execute_and_persist(spec, inputs, context())
            recorder.succeed(
                result_ref=ref, output={**_task_output(spec, output, ref), "engine": engine}
            )

        api.task_queue.submit(recorder.task_id, lambda: run_guarded(recorder, job))
        api.audit_context(
            tenant,
            audit.ACTION_SKILL_RUN,
            target_type="skill",
            target_id=spec.key,
            detail={"task_id": recorder.task_id, "async": True},
        )
        return {
            "skill_key": spec.key,
            "task_id": recorder.task_id,
            "status": STATUS_QUEUED,
            "async": True,
            "renderer": spec.renderer,
            "plan": [spec.name],
            "engine": engine,
        }

    # ---- 同步路径 ------------------------------------------------------
    try:
        with recorder:
            with recorder.step(spec.name, provider_note):
                output, ref = skills_runtime.execute_and_persist(spec, inputs, context())
            recorder.succeed(result_ref=ref, output=_task_output(spec, output, ref))
    except Exception as exc:  # noqa: BLE001 - 统一翻译成可展示的错误
        raise _http_error(exc) from exc

    api.audit_context(
        tenant,
        audit.ACTION_SKILL_RUN,
        target_type="skill",
        target_id=spec.key,
        detail={"task_id": recorder.task_id, "async": False, "result_ref": ref},
    )
    public = skills_runtime.strip_internal(output)
    return {
        "skill_key": spec.key,
        "task_id": recorder.task_id,
        "status": "succeeded",
        "renderer": spec.renderer,
        "is_demo": skills_runtime.resolve_is_demo(output),
        "credits": spec.credits,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "result_ref": ref,
        "engine": engine,
        "output": public,
    }
