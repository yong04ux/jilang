"""竞品分析：校验、同步分析、异步分析、报告查询与导出。

为什么竞品分析**不需要 BYOK**：分析本身是本地确定性计算（价格统计、评论主题、
关键词打分），不调模型。因此它可以脱离 API Key 运行 —— 这也是演示站里
「不配 Key 也能看到完整流程」的那条链路。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from ..engine.analysis import validate_request
from ..models import AnalysisReport, AnalysisResponse, CompetitorAnalysisRequest
from ..llm.providers import ProviderError, RuleProvider, build_provider
from ..services import audit
from ..services import competitor_service
from ..services import report_service
from ..services.tasks import STATUS_QUEUED, TaskRecorder
from ..tenancy import ROLE_READ, ROLE_WRITE, TenantContext, require_role
from .deps import ApiContext, get_ctx, require_tenant, require_user
from .handlers import run_guarded
from .helpers import attachment_headers

router = APIRouter(tags=["竞品分析"])


@router.post("/api/analyze/validate")
async def validate_analysis(request: CompetitorAnalysisRequest) -> dict[str, Any]:
    outcome = validate_request(request)
    return {
        "ok": outcome.ok,
        "errors": outcome.errors,
        "warnings": outcome.warnings,
        "review_samples": request.total_review_count(),
    }


@router.post("/api/analyze")
async def analyze(
    request: CompetitorAnalysisRequest,
    async_run: bool = False,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> Any:
    """竞品分析。

    - ``async_run=false``（默认）同步返回，脚本/测试使用；
    - ``async_run=true`` 立即返回 ``{task_id, status: "queued", plan}``，
      前端轮询 ``GET /api/tasks/{id}`` 并支持取消。

    分析本身是本地确定性计算（不调 LLM），所以两条路径结果一致。
    """
    require_role(tenant, ROLE_WRITE)
    api.rate_limit(user, "task.run", api.settings.rate_limit_tasks_per_hour)
    started = time.perf_counter()

    def job_payload() -> dict[str, Any]:
        return {
            "product_name": request.product_name,
            "platform": request.platform.value,
            "marketplace": request.marketplace,
            "competitors": len(request.competitors),
            "keywords": len(request.keywords),
            "data_source": request.data_source,
        }

    def invalid_input() -> HTTPException:
        outcome = validate_request(request)
        return HTTPException(
            status_code=422,
            detail={
                "message": "输入校验失败",
                "errors": outcome.errors,
                "warnings": outcome.warnings,
            },
        )

    def record_report(task: TaskRecorder, report: AnalysisReport) -> None:
        with task.step("保存报告"):
            api.db.save_report(
                report.model_dump(mode="json"),
                user_id=user["user_id"],
                tenant_id=tenant.tenant_id,
                task_id=task.task_id,
            )

    def report_output(report: AnalysisReport) -> dict[str, Any]:
        return {
            "report_id": report.report_id,
            "competitors": report.data_provenance.competitor_count,
            "review_samples": report.data_provenance.review_sample_count,
            "is_demo": report.data_provenance.is_demo,
        }

    # ---- 异步路径 ------------------------------------------------------
    if async_run:
        outcome = validate_request(request)
        if not outcome.ok:
            raise invalid_input()

        recorder = TaskRecorder(
            api.db,
            user["user_id"],
            "competitor_analysis",
            f"竞品分析：{request.product_name}",
            origin="form",
            payload=job_payload(),
            tenant_id=tenant.tenant_id,
            initial_status=STATUS_QUEUED,
        ).open()

        def job() -> None:
            recorder.mark_running()
            with recorder.step("执行分析", "本地规则引擎（确定性统计）"):
                report = competitor_service.run(
                    RuleProvider(engine_version=api.settings.engine_version),
                    request,
                    validate=False,
                )
            record_report(recorder, report)
            recorder.succeed(result_ref=report.report_id, output=report_output(report))

        api.task_queue.submit(recorder.task_id, lambda: run_guarded(recorder, job))
        api.audit_user(
            user,
            audit.ACTION_TASK_RUN,
            tenant_id=tenant.tenant_id,
            target_type="task",
            target_id=recorder.task_id,
            detail={"type": "competitor_analysis", "async": True},
        )
        return {
            "task_id": recorder.task_id,
            "status": STATUS_QUEUED,
            "plan": ["analyze", "persist"],
            "async": True,
        }

    # ---- 同步路径 ------------------------------------------------------
    task = TaskRecorder(
        api.db,
        user["user_id"],
        "competitor_analysis",
        f"竞品分析：{request.product_name}",
        origin="form",
        payload=job_payload(),
        tenant_id=tenant.tenant_id,
    )
    with task:
        with task.step(
            "校验输入",
            f"{len(request.competitors)} 个竞品 / {len(request.keywords)} 个关键词",
        ):
            outcome = validate_request(request)
            if not outcome.ok:
                raise invalid_input()
        model_config = api.model_service().effective(user["user_id"], api.settings)
        with task.step("执行分析", f"引擎 {model_config.provider}/{model_config.model}"):
            try:
                provider = build_provider(api.settings, model_config)
                report = competitor_service.run(provider, request, validate=False)
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
        record_report(task, report)
        task.succeed(result_ref=report.report_id, output=report_output(report))

    return AnalysisResponse(
        report=report,
        persisted=True,
        duration_ms=int((time.perf_counter() - started) * 1000),
        task_id=task.task_id,
    )


# ---------------------------------------------------------------------------
# 报告查询与导出
# ---------------------------------------------------------------------------


@router.get("/api/reports")
async def list_reports(
    limit: int = 50,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    return {
        "items": api.db.list_reports(
            limit=min(max(limit, 1), 200),
            user_id=user["user_id"],
            tenant_id=tenant.tenant_id,
        )
    }


@router.get("/api/reports/{report_id}", response_model=AnalysisReport)
async def get_report(
    report_id: str,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> AnalysisReport:
    payload = api.db.get_report(
        report_id, user_id=user["user_id"], tenant_id=tenant.tenant_id
    )
    if payload is None:
        raise HTTPException(status_code=404, detail=f"报告不存在: {report_id}")
    return AnalysisReport(**payload)


@router.get("/api/reports/{report_id}/export")
async def export_report_endpoint(
    report_id: str,
    format: str = "md",
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> Response:
    require_role(tenant, ROLE_READ)
    report = report_service.get_report(api.db, tenant, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"报告不存在: {report_id}")
    try:
        filename, content, media_type = report_service.export_report(report, format)
    except report_service.ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    api.audit_context(
        tenant,
        "report.export",
        target_type="report",
        target_id=report_id,
        detail={"format": format},
    )
    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers=attachment_headers(filename),
    )


__all__ = ["router"]
