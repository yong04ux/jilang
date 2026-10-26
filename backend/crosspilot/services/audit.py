"""审计日志（阶段 C7）。

原则：

- **只追加**，不提供修改/删除接口；
- 写入前统一 ``scrub``，凭据不进 ``audit_logs.detail``；
- 审计失败**不阻断业务**（例如登录），但会在应用日志里留一条错误，
  避免"因为审计挂了导致用户无法登录"。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..persistence.db import Database
from ..engine.scrubbing import scrub
from ..tenancy import TenantContext

logger = logging.getLogger(__name__)

# 动作名集中登记，避免各处拼字符串导致筛选失效
ACTION_LOGIN = "auth.login"
ACTION_LOGOUT = "auth.logout"
ACTION_REGISTER = "auth.register"
ACTION_PASSWORD_CHANGE = "auth.password_change"
ACTION_MODEL_UPDATE = "model.update"
ACTION_MODEL_RESET = "model.reset"
ACTION_MEMBER_INVITE = "member.invite"
ACTION_INVITE_CREATE = "invite.create"
ACTION_TASK_CANCEL = "task.cancel"
ACTION_TASK_RUN = "task.run"
ACTION_TASK_RETRY = "task.retry"
ACTION_AGENT_CREATE = "agent.create"
ACTION_AGENT_UPDATE = "agent.update"
ACTION_AGENT_DISABLE = "agent.disable"
ACTION_SKILL_CREATE = "skill.create"
ACTION_SKILL_UPDATE = "skill.update"
ACTION_SKILL_DISABLE = "skill.disable"
ACTION_SKILL_RUN = "skill.run"
ACTION_CONVERSATION_ARCHIVE = "conversation.archive"
ACTION_APPROVAL_REQUEST = "approval.request"
ACTION_APPROVAL_DECIDE = "approval.decide"
ACTION_REPORT_EXPORT = "report.export"
ACTION_LISTING_EXPORT = "listing.export"
ACTION_LISTING_VERSION = "listing.version_create"
ACTION_STORE_CREATE = "store.create"
ACTION_STORE_SYNC = "store.sync"
ACTION_STORE_DISCONNECT = "store.disconnect"
ACTION_STORE_CREDENTIAL = "store.credential"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(
    db: Database,
    *,
    tenant_id: str,
    actor_id: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> None:
    """写一条审计。失败只记应用日志，不向业务抛错。"""
    entry = {
        "tenant_id": tenant_id or "",
        "actor_id": actor_id or "",
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "detail": scrub(detail or {}),
        "trace_id": trace_id or uuid.uuid4().hex[:12],
        "created_at": _now(),
    }
    try:
        db.add_audit_log(entry)
    except Exception:  # noqa: BLE001 - 审计不能拖垮业务
        logger.exception("写入审计日志失败：action=%s", action)


def record_for_context(
    db: Database,
    ctx: TenantContext,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> None:
    record(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        trace_id=trace_id,
    )


def list_logs(
    db: Database,
    tenant_id: str,
    *,
    limit: int = 100,
    action: str | None = None,
    actor_id: str | None = None,
) -> list[dict[str, Any]]:
    return db.list_audit_logs(
        tenant_id, limit=limit, action=action, actor_id=actor_id
    )


__all__ = [
    "ACTION_APPROVAL_DECIDE",
    "ACTION_APPROVAL_REQUEST",
    "ACTION_CONVERSATION_ARCHIVE",
    "ACTION_INVITE_CREATE",
    "ACTION_LISTING_EXPORT",
    "ACTION_LISTING_VERSION",
    "ACTION_LOGIN",
    "ACTION_LOGOUT",
    "ACTION_MEMBER_INVITE",
    "ACTION_MODEL_RESET",
    "ACTION_MODEL_UPDATE",
    "ACTION_PASSWORD_CHANGE",
    "ACTION_REGISTER",
    "ACTION_REPORT_EXPORT",
    "ACTION_SKILL_RUN",
    "ACTION_STORE_CREATE",
    "ACTION_STORE_CREDENTIAL",
    "ACTION_STORE_DISCONNECT",
    "ACTION_STORE_SYNC",
    "ACTION_TASK_CANCEL",
    "ACTION_TASK_RUN",
    "list_logs",
    "record",
    "record_for_context",
]
