"""Listing 生成、查询、版本链、差异、复检、导出。

**异步是前端唯一路径**：生成 800–1200 tokens 要 15–35 秒，必然超过 HTTP 超时阈值。
同步路径只为脚本与测试保留，且**强制 BYOK**（没有 Key 直接 428，不静默降级）。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from ..models import ListingGenerationRequest, ListingResponse
from ..llm.providers import ProviderError, build_provider
from ..services import listing_service
from ..services.tasks import STATUS_QUEUED, STATUS_RUNNING, TaskRecorder
from ..tenancy import ROLE_READ, ROLE_WRITE, TenantContext, require_role
from .deps import ApiContext, get_ctx, require_tenant, require_user
from .handlers import run_guarded
from .helpers import attachment_headers

router = APIRouter(tags=["Listing"])


def _recorder(
    api: ApiContext, user: dict[str, Any], tenant: TenantContext,
    request: ListingGenerationRequest, status: str,
) -> TaskRecorder:
    return TaskRecorder(
        api.db,
        user["user_id"],
        "listing_generation",
        f"Listing 生成：{request.product.name}",
        origin="form",
        payload={
            "product_name": request.product.name,
            "marketplace": request.marketplace,
            "language": request.language,
            "analysis_report_id": request.analysis_report_id,
            "has_specs": bool(request.product.specifications),
        },
        tenant_id=tenant.tenant_id,
        initial_status=status,
    )


def _read_report(
    api: ApiContext,
    user: dict[str, Any],
    tenant: TenantContext,
    task: TaskRecorder,
    request: ListingGenerationRequest,
) -> dict[str, Any] | None:
    with task.step("读取关联报告"):
        payload: dict[str, Any] | None = request.analysis_report
        if request.analysis_report_id:
            payload = api.db.get_report(
                request.analysis_report_id,
                user_id=user["user_id"],
                tenant_id=tenant.tenant_id,
            )
            if payload is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"分析报告不存在: {request.analysis_report_id}",
                )
        return payload


def _succeed_output(listing) -> dict[str, Any]:
    return {
        "listing_id": listing.listing_id,
        "quality_passed": listing.quality_check.passed,
        "issues": len(listing.quality_check.issues),
        "pending": len(listing.pending_confirmations),
        "engine": listing.engine,
    }


@router.post("/api/listings/generate")
async def generate(
    request: ListingGenerationRequest,
    async_run: bool = False,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> Any:
    """Listing 生成。

    - ``async_run=false``（默认）同步返回：脚本/测试使用。Provider 不可用时
      降级为事实直出，并在 ``engine``/``quality_check`` 里**明确标注**。
    - ``async_run=true``：立即返回 ``{task_id, status: "queued", plan}``。
      前端唯一使用的路径，且**强制 BYOK**。

    两条路径共用同一套步骤与质检，不伪造进度。
    """
    require_role(tenant, ROLE_WRITE)
    api.rate_limit(user, "task.run", api.settings.rate_limit_tasks_per_hour)
    started = time.perf_counter()

    # ---- 异步路径（前端使用） ------------------------------------------
    if async_run:
        _active, config, provider = api.require_llm_provider(user)
        recorder = _recorder(api, user, tenant, request, STATUS_QUEUED).open()

        def job() -> None:
            recorder.mark_running()
            report_payload = _read_report(api, user, tenant, recorder, request)
            with recorder.step("生成文案", f"引擎 {config.provider}/{config.model}"):
                listing = listing_service.generate(provider, request, report_payload)
            with recorder.step("质量检查", f"{len(listing.quality_check.issues)} 个问题"):
                pass
            payload = listing_service.dump_for_storage(listing, request)
            with recorder.step("保存草稿"):
                api.db.save_listing(
                    payload,
                    user_id=user["user_id"],
                    tenant_id=tenant.tenant_id,
                    task_id=recorder.task_id,
                )
            recorder.succeed(
                result_ref=listing.listing_id, output=_succeed_output(listing)
            )

        api.task_queue.submit(recorder.task_id, lambda: run_guarded(recorder, job))
        api.audit_user(
            user,
            "task.run",
            tenant_id=tenant.tenant_id,
            target_type="task",
            target_id=recorder.task_id,
            detail={
                "type": "listing_generation",
                "async": True,
                "provider": config.provider,
            },
        )
        return {
            "task_id": recorder.task_id,
            "status": STATUS_QUEUED,
            "plan": ["listing", "quality", "save_listing"],
            "async": True,
        }

    # ---- 同步路径（脚本/测试） -----------------------------------------
    task = _recorder(api, user, tenant, request, STATUS_RUNNING)
    with task:
        report_payload = _read_report(api, user, tenant, task, request)
        model_config = api.model_service().effective(user["user_id"], api.settings)
        with task.step("生成文案", f"引擎 {model_config.provider}/{model_config.model}"):
            try:
                provider = build_provider(api.settings, model_config)
                # 事实对齐质检在 generate_listing 内部完成，模型输出不被直接信任。
                listing = listing_service.generate(provider, request, report_payload)
            except ProviderError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001 - 转成可读的 502
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Provider {model_config.provider}/{model_config.model} 调用失败: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                ) from exc
        with task.step("质量检查", f"{len(listing.quality_check.issues)} 个问题"):
            pass
        payload = listing_service.dump_for_storage(listing, request)
        with task.step("保存草稿"):
            api.db.save_listing(
                payload,
                user_id=user["user_id"],
                tenant_id=tenant.tenant_id,
                task_id=task.task_id,
            )
        task.succeed(result_ref=listing.listing_id, output=_succeed_output(listing))

    return ListingResponse(
        listing=listing,
        persisted=True,
        duration_ms=int((time.perf_counter() - started) * 1000),
        task_id=task.task_id,
    )


# ---------------------------------------------------------------------------
# 查询 / 版本 / 差异 / 复检 / 导出
# ---------------------------------------------------------------------------


@router.get("/api/listings")
async def list_listings(
    limit: int = 50,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    return {
        "items": api.db.list_listings(
            limit=min(max(limit, 1), 200),
            user_id=user["user_id"],
            tenant_id=tenant.tenant_id,
        )
    }


@router.get("/api/listings/{listing_id}")
async def get_listing(
    listing_id: str,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    payload = api.db.get_listing(listing_id, user_id=user["user_id"], tenant_id=tenant.tenant_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Listing 不存在: {listing_id}")
    meta = api.db.get_listing_meta(listing_id, tenant.tenant_id)
    if meta:
        payload.setdefault("version", meta["version"])
        payload.setdefault("parent_listing_id", meta["parent_listing_id"])
        payload.setdefault("created_at", meta["created_at"])
    return payload


@router.get("/api/listings/{listing_id}/versions")
async def list_listing_versions(
    listing_id: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_READ)
    versions = api.db.list_listing_versions(listing_id, tenant.tenant_id)
    if not versions:
        raise HTTPException(status_code=404, detail="Listing 不存在")
    return {"items": versions, "current": listing_id}


@router.post("/api/listings/{listing_id}/versions")
async def create_listing_version(
    listing_id: str,
    payload: dict[str, Any],
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """基于当前草稿派生新版本；编辑后必须重新质检。"""
    require_role(tenant, ROLE_WRITE)
    try:
        listing = listing_service.create_version(api.db, tenant, listing_id, payload)
    except listing_service.ListingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except listing_service.ListingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    api.audit_context(
        tenant,
        "listing.version_create",
        target_type="listing",
        target_id=listing["listing_id"],
        detail={"parent": listing_id, "version": listing.get("version")},
    )
    return {"listing": listing}


@router.get("/api/listings/{listing_id}/diff")
async def diff_listing(
    listing_id: str,
    against: str | None = None,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_READ)
    try:
        return listing_service.diff(api.db, tenant, listing_id, against)
    except listing_service.ListingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except listing_service.ListingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/listings/{listing_id}/check")
async def check_listing(
    listing_id: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """重新执行事实对齐质检（复用 run_quality_check）。"""
    require_role(tenant, ROLE_WRITE)
    try:
        quality = listing_service.recheck(api.db, tenant, listing_id)
    except listing_service.ListingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except listing_service.ListingSnapshotMissing as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except listing_service.ListingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"listing_id": listing_id, "quality_check": quality}


@router.get("/api/listings/{listing_id}/export")
async def export_listing_endpoint(
    listing_id: str,
    format: str = "md",
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> Response:
    require_role(tenant, ROLE_READ)
    listing = api.db.get_listing(
        listing_id, user_id=tenant.user_id, tenant_id=tenant.tenant_id
    )
    if listing is None:
        raise HTTPException(status_code=404, detail=f"Listing 不存在: {listing_id}")
    try:
        filename, content, media_type = listing_service.export_listing(listing, format)
    except listing_service.ListingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    api.audit_context(
        tenant,
        "listing.export",
        target_type="listing",
        target_id=listing_id,
        detail={"format": format},
    )
    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers=attachment_headers(filename),
    )


__all__ = ["router"]
