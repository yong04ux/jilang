"""导入服务（阶段 E6）：preview → commit 两步流程。

为什么拆两步：

- 真实文件常出现列名不一致（中文/英文/自定义），一步导入只能报错，用户无法修正；
- 预览把「列识别 + 字段映射 + 前 10 行 + 逐行错误」摆出来，确认后再落库；
- 原始文件落 ``LocalStorage``，提交时重新解析，避免把未经验证的数据先写库。

提交规则（验收项 5）：**只要有行级错误就不允许提交**，错误可通过 CSV 下载。
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any

from ..persistence.db import Database
from ..ingest.importers import (
    ImportResult,
    ImportValidationError,
    detect_file_columns,
    import_competitor_data,
)
from ..persistence.storage import ObjectStorage, StorageError
from ..tenancy import TenantContext

PREVIEW_ROWS = 10
ALLOWED_STATUS = {"validated", "rejected", "needs_mapping", "imported"}


class ImportError(ValueError):
    pass


class ImportNotFound(ImportError):
    pass


class ImportConflict(ImportError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _errors_as_dict(result: ImportResult) -> list[dict[str, Any]]:
    return [error.as_dict() for error in result.errors]


def preview(
    db: Database,
    ctx: TenantContext,
    storage: ObjectStorage,
    content: bytes,
    filename: str,
    *,
    field_mapping: dict[str, str] | None = None,
) -> dict[str, Any]:
    """保存原始文件并返回预览；不写业务数据，只写 ``data_sources`` 记录。"""
    if not content:
        raise ImportError("文件为空")
    data_source_id = uuid.uuid4().hex
    safe_name = storage.sanitize_name(filename)
    key = f"{ctx.tenant_id}/{data_source_id}/{safe_name}"
    try:
        storage.put(key, content)
    except StorageError as exc:
        raise ImportError(str(exc)) from exc

    columns, column_errors = detect_file_columns(content, filename)
    result: ImportResult | None = None
    errors: list[dict[str, Any]] = [e.as_dict() for e in column_errors]
    warnings: list[str] = []
    status = "needs_mapping"
    if not column_errors:
        try:
            result = import_competitor_data(
                content, filename, column_mapping=field_mapping
            )
            errors = _errors_as_dict(result)
            warnings = result.warnings
            status = "validated" if not errors else "rejected"
        except ImportValidationError as exc:
            errors = [e.as_dict() for e in exc.errors] or [
                {"row": 1, "field": "file", "message": str(exc)}
            ]
            status = "needs_mapping"
        except Exception as exc:  # noqa: BLE001 - 解析失败要变成可读预览
            errors = [{"row": 1, "field": "file", "message": f"{type(exc).__name__}: {exc}"}]
            status = "rejected"

    competitors = [c.model_dump(mode="json") for c in (result.competitors if result else [])]
    total_rows = result.total_rows if result else 0
    valid_rows = len(competitors)
    is_demo = bool(competitors) and all(c.get("is_demo") for c in competitors)
    source_format = (
        result.source_format if result else filename.rsplit(".", 1)[-1].lower()
    )
    validation = {
        "errors": errors,
        "warnings": warnings,
        "total": total_rows,
        "valid": valid_rows,
        "preview_rows": competitors[:PREVIEW_ROWS],
    }
    db.create_data_source(
        {
            "data_source_id": data_source_id,
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            "kind": "upload",
            "name": filename,
            "format": source_format,
            "storage_key": key,
            "row_count": total_rows,
            "is_demo": is_demo,
            "status": status,
            "field_mapping": field_mapping or {},
            "validation": validation,
            "created_at": _now(),
        }
    )
    return {
        "data_source_id": data_source_id,
        "status": status,
        "filename": filename,
        "format": source_format,
        "columns": columns,
        "field_mapping": field_mapping or {},
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "preview": competitors[:PREVIEW_ROWS],
        "errors": errors,
        "warnings": warnings,
        "is_demo": is_demo,
        "can_commit": status == "validated",
    }


def commit(
    db: Database,
    ctx: TenantContext,
    storage: ObjectStorage,
    data_source_id: str,
    *,
    field_mapping: dict[str, str] | None = None,
) -> dict[str, Any]:
    source = db.get_data_source(data_source_id, ctx.tenant_id)
    if source is None:
        raise ImportNotFound("数据源不存在")
    if source["status"] == "imported":
        raise ImportConflict("该数据源已提交过，不能重复导入")
    mapping = field_mapping if field_mapping is not None else (source.get("field_mapping") or {})

    try:
        content = storage.get(source.get("storage_key") or "")
    except StorageError as exc:
        raise ImportError(f"原始文件不可用：{exc}") from exc

    try:
        result = import_competitor_data(
            content, source["name"], column_mapping=mapping
        )
    except ImportValidationError as exc:
        errors = [e.as_dict() for e in exc.errors] or [
            {"row": 1, "field": "file", "message": str(exc)}
        ]
        db.update_data_source(
            data_source_id,
            status="rejected",
            validation={"errors": errors, "total": 0, "valid": 0},
        )
        raise ImportError(str(exc)) from exc

    if result.errors:
        db.update_data_source(
            data_source_id,
            status="rejected",
            validation={
                "errors": _errors_as_dict(result),
                "warnings": result.warnings,
                "total": result.total_rows,
                "valid": len(result.competitors),
            },
        )
        raise ImportError(
            f"存在 {len(result.errors)} 处行级错误，修正后才能提交"
        )

    batch_id = uuid.uuid4().hex
    payload = {
        "batch_id": batch_id,
        **result.as_dict(),
        "data_source_id": data_source_id,
        "field_mapping": mapping,
    }
    db.save_import_batch(
        {
            "batch_id": batch_id,
            "filename": source["name"],
            "source_format": result.source_format,
            "total_rows": result.total_rows,
            "valid_rows": len(result.competitors),
            "errors": [],
            "payload": payload,
            "data_source_id": data_source_id,
            "field_mapping": mapping,
        },
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
    )
    db.update_data_source(
        data_source_id,
        status="imported",
        row_count=result.total_rows,
        field_mapping=mapping,
        validation={
            "errors": [],
            "warnings": result.warnings,
            "total": result.total_rows,
            "valid": len(result.competitors),
        },
    )
    return {**payload, "task_id": None}


def remap(
    db: Database,
    ctx: TenantContext,
    storage: ObjectStorage,
    data_source_id: str,
    *,
    field_mapping: dict[str, str],
) -> dict[str, Any]:
    """用新的字段映射重新校验已上传的文件（不重新上传、不写业务数据）。

    前端「用新映射重新校验」走这里：避免让用户为了改一列映射重传整个文件。
    """
    source = db.get_data_source(data_source_id, ctx.tenant_id)
    if source is None:
        raise ImportNotFound("数据源不存在")
    if source["status"] == "imported":
        raise ImportConflict("该数据源已提交过，不能再次映射")

    try:
        content = storage.get(source.get("storage_key") or "")
    except StorageError as exc:
        raise ImportError(f"原始文件不可用：{exc}") from exc

    columns, column_errors = detect_file_columns(content, source["name"])
    result: ImportResult | None = None
    errors: list[dict[str, Any]] = [e.as_dict() for e in column_errors]
    warnings: list[str] = []
    status = "needs_mapping"
    if not column_errors:
        try:
            result = import_competitor_data(
                content, source["name"], column_mapping=field_mapping
            )
            errors = _errors_as_dict(result)
            warnings = result.warnings
            status = "validated" if not errors else "rejected"
        except ImportValidationError as exc:
            errors = [e.as_dict() for e in exc.errors] or [
                {"row": 1, "field": "file", "message": str(exc)}
            ]
            status = "needs_mapping"

    competitors = [c.model_dump(mode="json") for c in (result.competitors if result else [])]
    validation = {
        "errors": errors,
        "warnings": warnings,
        "total": result.total_rows if result else 0,
        "valid": len(competitors),
        "preview_rows": competitors[:PREVIEW_ROWS],
    }
    db.update_data_source(
        data_source_id,
        status=status,
        row_count=result.total_rows if result else 0,
        field_mapping=field_mapping,
        validation=validation,
    )
    return {
        "data_source_id": data_source_id,
        "status": status,
        "filename": source["name"],
        "format": source.get("format") or "",
        "columns": columns,
        "field_mapping": field_mapping,
        "total_rows": result.total_rows if result else 0,
        "valid_rows": len(competitors),
        "preview": competitors[:PREVIEW_ROWS],
        "errors": errors,
        "warnings": warnings,
        "is_demo": bool(competitors) and all(c.get("is_demo") for c in competitors),
        "can_commit": status == "validated",
    }


def error_csv(source: dict[str, Any]) -> str:
    """把预览/提交时的错误导出为 CSV（带 BOM，Excel 可直接打开）。"""
    validation = source.get("validation") or {}
    errors = validation.get("errors") or []
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["row", "field", "message", "value"])
    for error in errors:
        writer.writerow(
            [
                error.get("row", ""),
                error.get("field", ""),
                error.get("message", ""),
                error.get("value", ""),
            ]
        )
    return "\ufeff" + output.getvalue()


def list_sources(
    db: Database, ctx: TenantContext, limit: int = 50
) -> list[dict[str, Any]]:
    return db.list_data_sources(ctx.tenant_id, limit=limit)


__all__ = [
    "ImportConflict",
    "ImportError",
    "ImportNotFound",
    "PREVIEW_ROWS",
    "commit",
    "error_csv",
    "list_sources",
    "preview",
    "remap",
]
