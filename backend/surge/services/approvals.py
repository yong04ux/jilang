"""发布审批（阶段 D8）。

边界（必须如实）：

- 本项目**没有接入任何平台发布接口**（Amazon SP-API 在阶段 G 才做接入准备）。
  所以审批通过后的动作是「记录审批结论」，不是"发布成功"。
- ``publish_listing`` 任务在等待审批时状态为 ``awaiting_approval``，
  这是真实状态机，不是进度条装饰。
- 审批人要求 admin/owner；发起人要求 editor 及以上。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..persistence.db import Database
from ..tenancy import ROLE_MANAGE, ROLE_WRITE, TenantContext, require_role
from . import audit

KIND_PUBLISH_LISTING = "publish_listing"
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
DECISIONS = {STATUS_APPROVED, STATUS_REJECTED}


class ApprovalError(ValueError):
    """审批参数错误（可直接展示）。"""


class ApprovalNotFound(LookupError):
    """审批或关联资源不存在（统一 404，不泄漏存在性）。"""


class ApprovalConflict(RuntimeError):
    """审批状态不允许当前操作。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_approval(
    db: Database, ctx: TenantContext, approval_id: str
) -> dict[str, Any] | None:
    return db.get_approval(approval_id, ctx.tenant_id)


def list_approvals(
    db: Database, ctx: TenantContext, *, status: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    return db.list_approvals(ctx.tenant_id, status=status, limit=limit)


def request_publish(
    db: Database, ctx: TenantContext, *, listing_id: str, note: str | None = None
) -> dict[str, Any]:
    """为一个 Listing 草稿发起发布审批。"""
    require_role(ctx, ROLE_WRITE)
    listing = db.get_listing(listing_id, user_id=ctx.user_id, tenant_id=ctx.tenant_id)
    if listing is None:
        raise ApprovalNotFound("Listing 不存在")

    approval_id = uuid.uuid4().hex
    task_id = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex[:12]
    now = _now()
    payload = {
        "listing_id": listing_id,
        "product_name": listing.get("product_name") or "",
        "platform": str(listing.get("platform") or "amazon"),
        "marketplace": listing.get("marketplace") or "",
        "note": note or "",
    }
    db.create_approval(
        {
            "approval_id": approval_id,
            "tenant_id": ctx.tenant_id,
            "task_id": task_id,
            "kind": KIND_PUBLISH_LISTING,
            "payload": payload,
            "status": STATUS_PENDING,
            "requested_by": ctx.user_id,
            "decided_by": None,
            "decided_at": None,
            "note": note,
            "created_at": now,
        }
    )
    db.create_task(
        {
            "task_id": task_id,
            "user_id": ctx.user_id,
            "tenant_id": ctx.tenant_id,
            "origin": "form",
            "type": KIND_PUBLISH_LISTING,
            "title": f"发布审批：{payload['product_name']}",
            "status": "awaiting_approval",
            "input": {"listing_id": listing_id, "approval_id": approval_id},
            "output": {
                "approval_id": approval_id,
                "listing_id": listing_id,
                "published": False,
                "publish_not_connected": True,
            },
            "error_code": None,
            "error_message": None,
            "result_ref": listing_id,
            "trace_id": trace_id,
            "created_at": now,
            "started_at": now,
            "finished_at": None,
            "degraded": 0,
        }
    )
    db.add_task_step(
        {
            "step_id": uuid.uuid4().hex,
            "task_id": task_id,
            "user_id": ctx.user_id,
            "tenant_id": ctx.tenant_id,
            "seq": 1,
            "name": "等待发布审批",
            "status": "pending",
            "detail": "审批通过也不会真实发布：平台发布接口尚未接入（阶段 G）",
            "started_at": now,
            "finished_at": None,
            "duration_ms": None,
        }
    )
    audit.record_for_context(
        db,
        ctx,
        audit.ACTION_APPROVAL_REQUEST,
        target_type="approval",
        target_id=approval_id,
        detail={"listing_id": listing_id, "kind": KIND_PUBLISH_LISTING},
        trace_id=trace_id,
    )
    approval = db.get_approval(approval_id, ctx.tenant_id)
    assert approval is not None
    return approval


def decide(
    db: Database,
    ctx: TenantContext,
    approval_id: str,
    *,
    decision: str,
    note: str | None = None,
) -> dict[str, Any]:
    """审批通过/拒绝。通过只记录结论，不调用任何平台接口。"""
    require_role(ctx, ROLE_MANAGE)
    decision = (decision or "").strip().lower()
    if decision not in DECISIONS:
        raise ApprovalError("decision 只能是 approved 或 rejected")
    approval = db.get_approval(approval_id, ctx.tenant_id)
    if approval is None:
        raise ApprovalNotFound("审批不存在")
    if approval["status"] != STATUS_PENDING:
        raise ApprovalConflict(f"审批已{_label(approval['status'])}，不能重复处理")

    now = _now()
    db.update_approval(
        approval_id,
        status=decision,
        decided_by=ctx.user_id,
        decided_at=now,
        note=note if note is not None else approval.get("note"),
    )

    task_id = approval.get("task_id")
    if task_id:
        task = db.get_task(task_id, ctx.user_id, ctx.tenant_id)
        if task is not None:
            steps = db.list_task_steps(task_id, ctx.user_id, ctx.tenant_id)
            pending = [s for s in steps if s["status"] == "pending"]
            for step in pending:
                db.update_task_step(
                    step["step_id"],
                    status="succeeded" if decision == STATUS_APPROVED else "failed",
                    detail=(
                        "审批通过；平台发布接口未接入，未实际发布"
                        if decision == STATUS_APPROVED
                        else "审批被拒绝，未发布"
                    ),
                    finished_at=now,
                )
            output = {
                "approval_id": approval_id,
                "listing_id": approval["payload"].get("listing_id"),
                "published": False,
                "publish_not_connected": True,
                "decision": decision,
            }
            if decision == STATUS_APPROVED:
                db.update_task(
                    task_id,
                    status="succeeded",
                    output=output,
                    finished_at=now,
                )
            else:
                db.update_task(
                    task_id,
                    status="failed",
                    output=output,
                    error_code="approval_rejected",
                    error_message=note or "审批被拒绝",
                    finished_at=now,
                )

    audit.record_for_context(
        db,
        ctx,
        audit.ACTION_APPROVAL_DECIDE,
        target_type="approval",
        target_id=approval_id,
        detail={
            "decision": decision,
            "note": note or "",
            "task_id": task_id,
        },
    )
    updated = db.get_approval(approval_id, ctx.tenant_id)
    assert updated is not None
    return updated


def _label(status: str) -> str:
    return {
        STATUS_PENDING: "等待处理",
        STATUS_APPROVED: "通过",
        STATUS_REJECTED: "拒绝",
    }.get(status, status)


__all__ = [
    "ApprovalConflict",
    "ApprovalError",
    "ApprovalNotFound",
    "DECISIONS",
    "KIND_PUBLISH_LISTING",
    "STATUS_APPROVED",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "decide",
    "get_approval",
    "list_approvals",
    "request_publish",
]
