"""会话与消息服务（阶段 C4 / D7）。

设计取舍：

- 会话是**个人资产**：同一租户的成员可以看到彼此的任务与报告（团队协作），
  但聊天记录不共享。因此查询同时按 ``tenant_id`` 与 ``user_id`` 过滤。
- 会话标题由第一条用户消息截断生成，不调用模型，避免"标题也要花钱"。
- 消息写入与任务解耦：任务执行中途崩溃时，已写入的用户消息仍然保留，
  助手消息只在有结果时追加，不伪造进度。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..persistence.db import Database
from ..tenancy import TenantContext

TITLE_MAX = 28
DEFAULT_TITLE = "新会话"

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_TOOL = "tool"


class ConversationError(ValueError):
    """会话相关的可预期错误（消息可直接展示）。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def auto_title(text: str) -> str:
    """用首条消息生成标题：压平空白、截断、加省略号。"""
    flat = " ".join((text or "").split())
    if not flat:
        return DEFAULT_TITLE
    if len(flat) <= TITLE_MAX:
        return flat
    return flat[:TITLE_MAX].rstrip() + "…"


def create_conversation(
    db: Database, ctx: TenantContext, title: str | None = None
) -> dict[str, Any]:
    now = _now()
    conversation = {
        "conversation_id": uuid.uuid4().hex,
        "tenant_id": ctx.tenant_id,
        "user_id": ctx.user_id,
        "title": (title or DEFAULT_TITLE).strip() or DEFAULT_TITLE,
        "status": "active",
        "last_task_id": None,
        "created_at": now,
        "updated_at": now,
    }
    db.create_conversation(conversation)
    return conversation


def get_conversation(
    db: Database, ctx: TenantContext, conversation_id: str
) -> dict[str, Any] | None:
    return db.get_conversation(conversation_id, ctx.user_id, ctx.tenant_id)


def conversation_detail(
    db: Database, ctx: TenantContext, conversation_id: str
) -> dict[str, Any] | None:
    conversation = get_conversation(db, ctx, conversation_id)
    if conversation is None:
        return None
    return {
        "conversation": conversation,
        "messages": db.list_messages(conversation_id, ctx.tenant_id),
    }


def list_conversations(
    db: Database, ctx: TenantContext, limit: int = 50
) -> list[dict[str, Any]]:
    return db.list_conversations(ctx.user_id, ctx.tenant_id, limit=limit)


def append_message(
    db: Database,
    ctx: TenantContext,
    conversation_id: str,
    *,
    role: str,
    content: str,
    content_type: str = "text",
    task_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """追加一条消息。会话必须存在且属于当前用户。"""
    if role not in {ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_TOOL}:
        raise ConversationError(f"未知的消息角色：{role}")
    conversation = get_conversation(db, ctx, conversation_id)
    if conversation is None:
        raise ConversationError("会话不存在")
    message = {
        "message_id": uuid.uuid4().hex,
        "conversation_id": conversation_id,
        "tenant_id": ctx.tenant_id,
        "role": role,
        "content": content,
        "content_type": content_type,
        "task_id": task_id,
        "meta": meta or {},
        "created_at": _now(),
    }
    db.add_message(message)
    fields: dict[str, Any] = {"updated_at": _now()}
    if task_id:
        fields["last_task_id"] = task_id
    if conversation["title"] == DEFAULT_TITLE and role == ROLE_USER:
        fields["title"] = auto_title(content)
    db.update_conversation(conversation_id, **fields)
    return message


def archive_conversation(db: Database, ctx: TenantContext, conversation_id: str) -> bool:
    if get_conversation(db, ctx, conversation_id) is None:
        return False
    db.update_conversation(conversation_id, status="archived")
    return True


def ensure_conversation(
    db: Database, ctx: TenantContext, conversation_id: str | None, *, title_hint: str
) -> dict[str, Any]:
    """有 id 则复用（并校验归属），没有则按提示创建。"""
    if conversation_id:
        conversation = get_conversation(db, ctx, conversation_id)
        if conversation is None:
            raise ConversationError("会话不存在或无权访问")
        return conversation
    return create_conversation(db, ctx, auto_title(title_hint))


def record_task_result(
    db: Database,
    ctx: TenantContext,
    conversation_id: str,
    task_id: str,
    *,
    fallback_plan: list[str] | None = None,
    degraded: bool = False,
) -> None:
    """任务结束后把结果摘要写回会话；失败/取消也如实标注。

    线程执行器与 arq worker 共用这一个函数，避免两套文案。
    """
    task = db.get_task_by_id(task_id) or {}
    status = task.get("status")
    output = task.get("output") or {}
    if status == "succeeded":
        parts = ["步骤已完成。"]
        if output.get("report_id"):
            parts.append("竞品报告已保存。")
        if output.get("listing_id"):
            parts.append("Listing 草稿已保存。")
        content = " ".join(parts)
    elif status == "cancelled":
        content = "任务已取消，未产生新结果。"
    else:
        content = f"任务失败：{task.get('error_message') or '未知错误'}"
    append_message(
        db,
        ctx,
        conversation_id,
        role=ROLE_ASSISTANT,
        content=content,
        content_type="result_ref" if status == "succeeded" else "error",
        task_id=task_id,
        meta={
            "status": status,
            "plan": output.get("plan") or fallback_plan or [],
            "report_id": output.get("report_id"),
            "listing_id": output.get("listing_id"),
            "degraded": bool(output.get("degraded") or degraded),
        },
    )


__all__ = [
    "DEFAULT_TITLE",
    "ConversationError",
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "ROLE_TOOL",
    "ROLE_USER",
    "append_message",
    "archive_conversation",
    "auto_title",
    "conversation_detail",
    "create_conversation",
    "ensure_conversation",
    "get_conversation",
    "list_conversations",
    "record_task_result",
]
