"""任务记录服务：把一次业务操作记录成可追溯的 task + task_steps。

设计要点：

1. **步骤由真实执行过程产生**，不是预先写死的模板。每个 ``with task.step(...)``
   记录真实的起止时间与耗时，因此任务详情里的时间线可信。
2. **失败也要留痕**：``__exit__`` 会把未完成的任务标为 failed 并写入错误码，
   异常本身继续向上抛，不吞异常。
3. **取消是异步的**：``running`` 任务收到取消请求后先进入 ``cancelling``，
   执行器在下一个图节点前检查到该状态，把任务置为 ``cancelled``。
   这样既不会假装"立刻停止"，也不会像旧版那样完全不能取消。
4. **排队任务可立即取消**；同步执行（非队列）的任务仍如实返回冲突。
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from ..persistence.db import Database

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CANCELLING = "cancelling"
STATUS_CANCELLED = "cancelled"

TERMINAL_STATUSES = {STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED}
CANCELLABLE_STATUSES = {STATUS_QUEUED, STATUS_RUNNING, STATUS_CANCELLING}


class TaskCancelled(Exception):
    """任务在检查点被取消。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskRecorder:
    """记录一次任务执行。

    用法::

        with TaskRecorder(db, user_id, "competitor_analysis", "竞品分析：X") as task:
            with task.step("校验输入"):
                ...
            task.succeed(result_ref=report_id, output={"report_id": report_id})

    异步执行时不要用 ``with``：调用 ``open()`` 落库，再交给队列；
    执行线程里先 ``mark_running()``，最后 ``succeed()/fail()/cancel()``。
    """

    def __init__(
        self,
        db: Database,
        user_id: str,
        task_type: str,
        title: str,
        *,
        origin: str = "form",
        payload: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        initial_status: str = STATUS_RUNNING,
        conversation_id: str | None = None,
        degraded: bool = False,
        task_id: str | None = None,
        retry_of: str | None = None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.task_id = task_id or uuid.uuid4().hex
        self.trace_id = uuid.uuid4().hex[:12]
        self.type = task_type
        self.title = title
        self.origin = origin
        self.payload = payload or {}
        self.initial_status = initial_status
        self.conversation_id = conversation_id
        self.degraded = degraded
        self.retry_of = retry_of
        self._seq = 0
        self._finished = False
        self._opened = False
        self._context = False

    # -- 生命周期 ----------------------------------------------------------
    def open(self) -> "TaskRecorder":
        if self._opened:
            return self
        now = _now()
        self.db.create_task(
            {
                "task_id": self.task_id,
                "user_id": self.user_id,
                "tenant_id": self.tenant_id,
                "origin": self.origin,
                "type": self.type,
                "title": self.title,
                "status": self.initial_status,
                "input": self.payload,
                "output": None,
                "error_code": None,
                "error_message": None,
                "result_ref": None,
                "retry_of": self.retry_of,
                "trace_id": self.trace_id,
                "created_at": now,
                "started_at": now if self.initial_status == STATUS_RUNNING else None,
                "finished_at": None,
                "conversation_id": self.conversation_id,
                "degraded": 1 if self.degraded else 0,
            }
        )
        self._opened = True
        return self

    def __enter__(self) -> "TaskRecorder":
        self._context = True
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self._context:
            return False
        if self._finished:
            return False
        if exc is not None:
            if isinstance(exc, TaskCancelled):
                self.cancel()
                return False
            code = getattr(exc, "status_code", None)
            self.fail(
                code=f"http_{code}" if code else "unhandled_error",
                message=str(getattr(exc, "detail", exc))[:500],
            )
        else:
            # 没有显式 succeed/fail 却正常退出：说明调用方忘了收尾，明确标记出来
            self.fail(code="task_not_finished", message="任务结束时未标记结果")
        return False  # 不吞异常

    # -- 状态 --------------------------------------------------------------
    def mark_running(self) -> None:
        if self._finished:
            raise TaskCancelled("任务已结束")
        task = self.db.get_task_by_id(self.task_id)
        if task is not None and task["status"] in {STATUS_CANCELLED, STATUS_CANCELLING}:
            # 排队期间被取消：不要再抢回 running
            self._finished = True
            raise TaskCancelled("任务在开始前已被取消")
        self.db.update_task(
            self.task_id,
            status=STATUS_RUNNING,
            started_at=_now(),
        )

    def is_cancel_requested(self) -> bool:
        """检查点：数据库状态是取消的唯一真相（跨进程也成立）。"""
        task = self.db.get_task_by_id(self.task_id)
        return bool(task and task["status"] in {STATUS_CANCELLING, STATUS_CANCELLED})

    # -- 步骤 --------------------------------------------------------------
    def begin_step(self, name: str, detail: str | None = None, node: str | None = None) -> str:
        """显式开一个步骤，返回 step_id。

        Agent Runtime 的每个图节点用这个接口记录，便于在图里精确控制起止。
        ``node`` 是稳定的节点键（如 ``analyze``），失败任务重试时据此复用输出。
        """
        self._seq += 1
        step_id = uuid.uuid4().hex
        self.db.add_task_step(
            {
                "step_id": step_id,
                "task_id": self.task_id,
                "user_id": self.user_id,
                "tenant_id": self.tenant_id,
                "seq": self._seq,
                "name": name,
                "node": node,
                "status": STATUS_RUNNING,
                "detail": detail,
                "started_at": _now(),
                "finished_at": None,
                "duration_ms": None,
            }
        )
        return step_id

    def end_step(
        self,
        step_id: str,
        *,
        status: str = STATUS_SUCCEEDED,
        detail: str | None = None,
        started_perf: float | None = None,
        duration_ms: int | None = None,
        output: Any = None,
    ) -> None:
        if duration_ms is None and started_perf is not None:
            duration_ms = int((time.perf_counter() - started_perf) * 1000)
        self.db.update_task_step(
            step_id,
            status=status,
            detail=detail,
            finished_at=_now(),
            duration_ms=duration_ms,
            output=output,
        )

    @contextmanager
    def step(self, name: str, detail: str | None = None) -> Iterator[dict[str, Any]]:
        started_perf = time.perf_counter()
        step_id = self.begin_step(name, detail)
        try:
            yield {"step_id": step_id, "name": name}
        except Exception as exc:  # noqa: BLE001 - 记录后继续抛出
            self.end_step(
                step_id,
                status=STATUS_FAILED,
                detail=f"{detail + ' · ' if detail else ''}失败：{exc}"[:500],
                started_perf=started_perf,
            )
            raise
        else:
            self.end_step(step_id, started_perf=started_perf)

    # -- 收尾 --------------------------------------------------------------
    def succeed(
        self,
        *,
        result_ref: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        self.db.update_task(
            self.task_id,
            status=STATUS_SUCCEEDED,
            result_ref=result_ref,
            output=output or {},
            finished_at=_now(),
        )

    def fail(self, *, code: str, message: str) -> None:
        if self._finished:
            return
        self._finished = True
        self.db.update_task(
            self.task_id,
            status=STATUS_FAILED,
            error_code=code,
            error_message=message,
            finished_at=_now(),
        )

    def cancel(self, *, reason: str = "用户取消") -> None:
        """把任务落成 cancelled，并留下一个取消步骤。"""
        if self._finished:
            return
        self._finished = True
        self.db.update_task(
            self.task_id,
            status=STATUS_CANCELLED,
            output={"cancelled": True, "reason": reason},
            finished_at=_now(),
        )
        self._seq += 1
        step_id = uuid.uuid4().hex
        now = _now()
        self.db.add_task_step(
            {
                "step_id": step_id,
                "task_id": self.task_id,
                "user_id": self.user_id,
                "tenant_id": self.tenant_id,
                "seq": self._seq,
                "name": "任务已取消",
                "status": STATUS_CANCELLED,
                "detail": f"在检查点停止：{reason}",
                "started_at": now,
                "finished_at": now,
                "duration_ms": 0,
            }
        )

    # -- 恢复（arq worker 用） --------------------------------------------
    @classmethod
    def resume(cls, db: Database, task: dict[str, Any]) -> "TaskRecorder":
        recorder = cls(
            db,
            task["user_id"],
            task["type"],
            task["title"],
            origin=task.get("origin") or "form",
            payload=task.get("input") or {},
            tenant_id=task.get("tenant_id"),
            initial_status=task.get("status") or STATUS_QUEUED,
            conversation_id=task.get("conversation_id"),
            degraded=bool(task.get("degraded")),
            task_id=task["task_id"],
            retry_of=task.get("retry_of"),
        )
        recorder.trace_id = task.get("trace_id") or recorder.trace_id
        recorder._opened = True
        return recorder


def cancel_task(
    db: Database,
    user_id: str,
    task_id: str,
    tenant_id: str | None = None,
    *,
    queue: Any = None,
) -> tuple[str, str]:
    """取消任务。

    返回 (result, message)，result 取值：
    - ``"ok"``         已取消 / 已进入 cancelling
    - ``"not_found"``  不存在或不属于该用户（不泄漏任务是否存在）
    - ``"conflict"``   状态不允许取消

    ``queued`` 立即变 ``cancelled``；``running`` 只有在队列确实托管该任务时
    才接受取消（置 ``cancelling``，由执行器在检查点收尾）。同步执行的请求
    仍然返回冲突，避免"点了取消但请求还在跑"的假象。
    """
    task = db.get_task(task_id, user_id, tenant_id)
    if task is None:
        return "not_found", f"任务不存在: {task_id}"
    status = task["status"]
    if status == STATUS_CANCELLED:
        return "ok", "任务已取消"
    if status in TERMINAL_STATUSES:
        return "conflict", f"任务已{_status_label(status)}，无法取消"
    if status == STATUS_CANCELLING:
        return "ok", "已请求取消，等待当前步骤结束"
    if status == STATUS_QUEUED:
        db.update_task(task_id, status=STATUS_CANCELLED, finished_at=_now())
        return "ok", "排队任务已取消"
    if status == STATUS_RUNNING:
        managed = bool(queue is not None and queue.is_active(task_id))
        if not managed:
            return (
                "conflict",
                "任务正在同步执行，当前请求内无法中途取消；请使用异步执行模式",
            )
        db.update_task(task_id, status=STATUS_CANCELLING)
        queue.cancel(task_id)
        return "ok", "已请求取消，将在当前步骤结束后停止"
    return "conflict", f"任务状态（{status}）不允许取消"


def _status_label(status: str) -> str:
    return {
        STATUS_SUCCEEDED: "完成",
        STATUS_FAILED: "失败",
        STATUS_CANCELLED: "取消",
        STATUS_RUNNING: "执行中",
        STATUS_QUEUED: "排队",
        STATUS_CANCELLING: "正在取消",
        STATUS_AWAITING_APPROVAL: "等待审批",
    }.get(status, status)


__all__ = [
    "CANCELLABLE_STATUSES",
    "STATUS_AWAITING_APPROVAL",
    "STATUS_CANCELLED",
    "STATUS_CANCELLING",
    "STATUS_FAILED",
    "STATUS_QUEUED",
    "STATUS_RUNNING",
    "STATUS_SUCCEEDED",
    "TERMINAL_STATUSES",
    "TaskCancelled",
    "TaskRecorder",
    "cancel_task",
]
