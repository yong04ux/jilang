"""图节点的步骤记录与断点复用（三个子图共用）。

为什么要抽出来
==============

Phase 3/4/5 三个子图各自有一份几乎相同的 ``_step``：记录 ``task_steps``、
失败时按错误分类写一句人话、以及（本轮新增）命中 ``resume_from`` 时不重跑。

三份实现的结果是"改一处漏两处"——比如错误分类只在其中一个图里生效。
这里收成一个类，三个图都委托给它。

``resume_from`` 的语义
=====================

``{node: 上次成功输出}``。命中就**直接返回缓存输出、不执行函数体**——
这既省掉一次模型调用，也避免重复写库。它由 ``/api/tasks/{id}/retry`` 构造。

前提是「节点返回值就是可序列化的状态片段」：三个子图都遵守这个约定，
因为 Phase 6 要接 checkpointer，本来就不能往状态里塞对象。

**节点名是契约**：改名会让历史任务的 ``task_steps.node`` 匹配不上，
断点复用的范围随之缩小（不会报错，只是不复用）。所以节点名一旦发布就别乱改。
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any, Callable

from . import errors as agent_errors
from ..llm import telemetry as llm_telemetry

#: 当前工作流的截止时间（monotonic）。用 ContextVar 而不是层层传参：
#: 组合图里还套着竞品图与 Listing 图，参数要穿过五层才到得了最内层的节点。
_DEADLINE: ContextVar[float | None] = ContextVar("crosspilot_step_deadline", default=None)


def begin_deadline(seconds: float | None):
    """设置超时窗口，返回 token（用 ``end_deadline`` 还原）。

    ``seconds`` 为空或 <=0 表示不设超时。
    """
    if not seconds or seconds <= 0:
        return _DEADLINE.set(None)
    return _DEADLINE.set(time.monotonic() + float(seconds))


def end_deadline(token) -> None:
    _DEADLINE.reset(token)


def remaining_seconds() -> float | None:
    """剩余秒数；没设超时返回 ``None``。"""
    deadline = _DEADLINE.get()
    if deadline is None:
        return None
    return deadline - time.monotonic()


class StepRunner:
    """按节点名记录步骤；支持失败留痕与断点复用。"""

    def __init__(
        self,
        task: Any = None,
        resume_from: dict[str, Any] | None = None,
        labels: dict[str, str] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.task = task
        self.resume_from = resume_from or {}
        self.labels = labels or {}
        # 有任务记录就默认按任务状态判取消：原来只有主图在节点边界查取消，
        # 拆成子图后三个图共用这一个检查点，语义才不会分叉。
        if cancel_check is not None:
            self.cancel_check = cancel_check
        elif task is not None and hasattr(task, "is_cancel_requested"):
            self.cancel_check = task.is_cancel_requested
        else:
            self.cancel_check = None

    def label(self, name: str) -> str:
        return self.labels.get(name, name)

    def run(self, name: str, detail: str, fn: Callable[[], Any]) -> Any:
        # 0) 取消检查必须在最前面：已经取消的任务连缓存都不该复用
        if self.cancel_check is not None and self.cancel_check():
            from ..services.tasks import TaskCancelled

            raise TaskCancelled("用户取消")

        # 0.5) 超时检查同样放在复用之前：一个已经超时的工作流不该因为
        # "这一步恰好有缓存"而继续往下跑，那会把超时变成"跑到一半忽然结束"。
        if remaining_seconds() is not None and remaining_seconds() <= 0:
            from .contracts import SkillTimeout

            raise SkillTimeout("工作流执行超时，请稍后重试或减少竞品数量")

        # 1) 断点复用：不执行函数体，只补一条"复用"记录
        if name in self.resume_from:
            cached = self.resume_from[name]
            if self.task is not None:
                step_id = self.task.begin_step(
                    self.label(name), "复用上次成功步骤", node=name
                )
                self.task.end_step(
                    step_id,
                    status="succeeded",
                    detail="复用上次成功步骤（未重跑）",
                    duration_ms=0,
                    output=cached,
                )
            return cached

        if self.task is None:
            return fn()

        started = time.perf_counter()
        step_id = self.task.begin_step(self.label(name), detail, node=name)
        with llm_telemetry.scope(name):
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - 记录后继续抛
                # 必须在 with 内取走记录：窗口一关缓冲就还原了，之后 drain 是空的
                self._persist_calls(llm_telemetry.drain())
                # 步骤描述用**面向用户**的分类文案，不写异常类名：
                # 时间线会展示给用户，`RuntimeError: ...` 属于内部实现细节。
                info = agent_errors.classify(exc)
                self.task.end_step(
                    step_id,
                    status="failed",
                    detail=f"失败：{info.message}"[:500],
                    started_perf=started,
                )
                raise
            calls = llm_telemetry.drain()
        self._persist_calls(calls)
        self.task.end_step(step_id, started_perf=started, output=result)
        return result

    def _persist_calls(self, records: list[Any]) -> None:
        """把本节点的模型调用记录写进 ``llm_calls``。

        遥测落库失败不影响业务（所以单独一段 try）：
        排查信息丢了可以接受，任务失败不可以。
        """
        try:
            if not records:
                return
            db = getattr(self.task, "db", None)
            if db is None:
                return
            db.add_llm_calls(
                [
                    {
                        **record.as_dict(),
                        "task_id": getattr(self.task, "task_id", ""),
                        "tenant_id": getattr(self.task, "tenant_id", "") or "",
                        "user_id": getattr(self.task, "user_id", "") or "",
                    }
                    for record in records
                ]
            )
        except Exception:  # noqa: BLE001 - 见 docstring
            pass


__all__ = ["StepRunner", "begin_deadline", "end_deadline", "remaining_seconds"]
