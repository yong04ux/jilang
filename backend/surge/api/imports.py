"""数据导入：一步导入 + 两步导入（预览 → 映射 → 提交）+ 错误 CSV。

两步导入是页面实际使用的路径：**先预览识别到的列，用户确认字段映射，再提交**。
错误永远定位到「行 + 字段」，并可导出 CSV —— 不给出"第 3 行 price 不是数字"
就等于让用户自己找。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from ..ingest.importers import ImportValidationError, import_competitor_data
from ..labels import humanize_error
from ..services import import_service
from ..services.tasks import TaskRecorder
from ..tenancy import ROLE_READ, ROLE_WRITE, TenantContext, require_role
from .deps import ApiContext, get_ctx, require_tenant, require_user
from .helpers import attachment_headers

router = APIRouter(tags=["数据导入"])


def _parse_mapping(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    try:
        mapping = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="列对应关系没能识别，请重新选择一遍") from exc
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=422, detail="列对应关系格式不对，请重新选择一遍")
    return mapping


# ---------------------------------------------------------------------------
# 一步导入（脚本 / 旧调用方）
# ---------------------------------------------------------------------------


@router.post("/api/import")
async def import_file(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_WRITE)
    filename = file.filename or "upload"
    task = TaskRecorder(
        api.db,
        user["user_id"],
        "data_import",
        f"数据导入：{filename}",
        origin="form",
        payload={"filename": filename},
        tenant_id=tenant.tenant_id,
    )
    with task:
        with task.step("读取文件"):
            data = await file.read()
            if len(data) > api.settings.max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"文件超过 {api.settings.max_upload_bytes} 字节上限",
                )
            if not data:
                raise HTTPException(status_code=422, detail="文件为空")
        with task.step("解析并逐行校验", f"{len(data)} 字节"):
            try:
                result = import_competitor_data(data, filename)
            except ImportValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": str(exc),
                        "errors": [
                            humanize_error(e.as_dict())
                            for e in getattr(exc, "errors", [])
                        ],
                    },
                ) from exc
        with task.step("保存导入批次"):
            batch_id = uuid.uuid4().hex
            payload = {"batch_id": batch_id, **result.as_dict()}
            api.db.save_import_batch(
                {
                    "batch_id": batch_id,
                    "filename": filename,
                    "source_format": result.source_format,
                    "total_rows": result.total_rows,
                    "valid_rows": len(result.competitors),
                    "errors": [humanize_error(e.as_dict()) for e in result.errors],
                    "payload": payload,
                },
                user_id=user["user_id"],
                tenant_id=tenant.tenant_id,
            )
        task.succeed(
            result_ref=batch_id,
            output={
                "batch_id": batch_id,
                "total_rows": result.total_rows,
                "valid_rows": len(result.competitors),
                "errors": len(result.errors),
                "source_format": result.source_format,
            },
        )
    # 出接口这一份用中文；落库的 payload 仍是原始字段名，便于回溯与重放
    payload["errors"] = [humanize_error(e) for e in payload.get("errors", [])]
    payload["task_id"] = task.task_id
    return payload


# ---------------------------------------------------------------------------
# 两步导入：预览 / 重新映射 / 提交
# ---------------------------------------------------------------------------


@router.post("/api/import/preview")
async def preview_import(
    file: UploadFile = File(...),
    field_mapping: str | None = Form(default=None),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """保存原始文件并返回列识别 + 预览；不写业务数据。"""
    require_role(tenant, ROLE_WRITE)
    data = await file.read()
    if len(data) > api.settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="文件超过上传上限")
    mapping = _parse_mapping(field_mapping)
    try:
        return import_service.preview(
            api.db,
            tenant,
            api.storage,
            data,
            file.filename or "upload",
            field_mapping=mapping,
        )
    except import_service.ImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/import/remap")
async def remap_import(
    payload: dict[str, Any],
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """用新的字段映射重新校验已上传文件（不重传文件、不写业务数据）。"""
    require_role(tenant, ROLE_WRITE)
    data_source_id = str(payload.get("data_source_id") or "").strip()
    if not data_source_id:
        raise HTTPException(status_code=422, detail="没有指定要提交哪一次导入，请重新上传文件")
    mapping = payload.get("field_mapping")
    if not isinstance(mapping, dict) or not mapping:
        raise HTTPException(status_code=422, detail="请先把每一列对应到字段后再提交")
    try:
        return import_service.remap(
            api.db,
            tenant,
            api.storage,
            data_source_id,
            field_mapping={str(k): str(v) for k, v in mapping.items()},
        )
    except import_service.ImportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except import_service.ImportConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except import_service.ImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/import/commit")
async def commit_import(
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """按映射写入批次；已提交过的数据源不能重复提交。"""
    require_role(tenant, ROLE_WRITE)
    data_source_id = str(payload.get("data_source_id") or "").strip()
    if not data_source_id:
        raise HTTPException(status_code=422, detail="没有指定要提交哪一次导入，请重新上传文件")
    mapping = payload.get("field_mapping")
    if mapping is not None and not isinstance(mapping, dict):
        raise HTTPException(status_code=422, detail="列对应关系格式不对，请重新选择一遍")
    source = api.db.get_data_source(data_source_id, tenant.tenant_id)
    if source is None:
        raise HTTPException(status_code=404, detail="数据源不存在")

    task = TaskRecorder(
        api.db,
        user["user_id"],
        "data_import",
        f"数据导入：{source['name']}",
        origin="form",
        payload={"data_source_id": data_source_id, "filename": source["name"]},
        tenant_id=tenant.tenant_id,
    )
    with task:
        with task.step("读取数据源", source["name"]):
            pass
        with task.step("校验并写入批次"):
            try:
                result = import_service.commit(
                    api.db, tenant, api.storage, data_source_id, field_mapping=mapping
                )
            except import_service.ImportNotFound as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except import_service.ImportConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except import_service.ImportError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        with task.step("写入数据源状态"):
            pass
        task.succeed(
            result_ref=result["batch_id"],
            output={
                "batch_id": result["batch_id"],
                "data_source_id": data_source_id,
                "total_rows": result["total_rows"],
                "valid_rows": len(result["competitors"]),
            },
        )
    result["task_id"] = task.task_id
    return result


# ---------------------------------------------------------------------------
# 数据源查询与错误 CSV
# ---------------------------------------------------------------------------


@router.get("/api/data-sources")
async def list_data_sources(
    limit: int = 50,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_READ)
    return {
        "items": import_service.list_sources(
            api.db, tenant, limit=min(max(limit, 1), 100)
        )
    }


@router.get("/api/data-sources/{data_source_id}")
async def get_data_source(
    data_source_id: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_READ)
    source = api.db.get_data_source(data_source_id, tenant.tenant_id)
    if source is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return source


@router.get("/api/data-sources/{data_source_id}/errors.csv")
async def download_import_errors(
    data_source_id: str,
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> Response:
    require_role(tenant, ROLE_READ)
    source = api.db.get_data_source(data_source_id, tenant.tenant_id)
    if source is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    filename = f"import-errors-{data_source_id[:8]}.csv"
    return Response(
        content=import_service.error_csv(source).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers=attachment_headers(filename),
    )


__all__ = ["router"]
