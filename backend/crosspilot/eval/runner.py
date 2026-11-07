"""执行器：把一条用例跑起来，采集结局、步骤、耗时、错误分类。

三条约束
========

1. **不落库**。评估跑 ``persist=False``，不写业务表，所以没有数据库也能跑，
   也不会污染任何人看到的数据。
2. **checkpoint 用内存 saver**，每个用例一份。理由同上：评估不该在共享库里
   留线程。生产用 Postgres，这里只验证「暂停能恢复」这件事本身。
3. **故障注入必须还原**。用 contextmanager + try/finally 包住，任何异常都要
   还原被替换的函数，否则后面的用例会跑在一个坏掉的进程里。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

from .cases import (
    EvalCase,
    FAULT_ANALYSIS,
    FAULT_AUTH,
    FAULT_NETWORK,
    FAULT_NONE,
    FAULT_QUALITY,
    FAULT_RATE_LIMIT,
    FAULT_TIMEOUT,
    KIND_LISTING,
)

EVAL_TENANT = "eval-tenant"
EVAL_USER = "eval-user"


# ---------------------------------------------------------------------------
# 步骤记录器：不落库，只把节点顺序留在内存
# ---------------------------------------------------------------------------


class MemoryTask:
    """满足 ``StepRunner`` 对 task 的最小接口。

    ``StepRunner`` 只用到 ``begin_step`` / ``end_step``（以及可选的
    ``is_cancel_requested``）。有了它就能拿到**真实执行的节点序列**，
    而这正是"工具调用正确性"要断言的东西。
    """

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self._seq = 0
        self.cancelled = False

    def begin_step(self, name: str, detail: str = "", node: str | None = None) -> str:
        self._seq += 1
        step_id = f"s{self._seq}"
        self.steps.append(
            {
                "seq": self._seq,
                "name": name,
                "node": node or name,
                "detail": detail,
                "status": "running",
            }
        )
        return step_id

    def end_step(self, step_id: str, **kwargs: Any) -> None:
        for step in self.steps:
            if f"s{step['seq']}" == step_id:
                step["status"] = kwargs.get("status", "succeeded")
                if kwargs.get("detail"):
                    step["detail"] = kwargs["detail"]
                break

    def is_cancel_requested(self) -> bool:
        return self.cancelled


# ---------------------------------------------------------------------------
# 故障注入
# ---------------------------------------------------------------------------


class _FaultyProvider:
    """包一层 Provider，在生成时抛出指定类型的模型错误。

    只包 ``generate``：竞品分析不走模型（纯统计），所以这里不会误伤分析路径——
    这恰好也让 ``FAULT_ANALYSIS`` 必须单独注入，两种故障不会混在一起。
    """

    def __init__(self, inner: Any, kind: str) -> None:
        self._inner = inner
        self._kind = kind

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        from ..llm.llm import LLMError

        raise LLMError(f"评测注入的模型故障：{self._kind}", kind=self._kind)


@contextmanager
def injected(case: EvalCase) -> Iterator[None]:
    """按用例的 ``fault`` 字段临时替换实现；退出时一定还原。"""
    from unittest.mock import patch

    fault = case.fault
    if fault == FAULT_NONE:
        yield
        return

    patchers = []
    try:
        if fault == FAULT_ANALYSIS:
            def _boom(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("评测注入：统计阶段异常")

            patchers.append(patch("crosspilot.engine.analysis.run_analysis", _boom))
        elif fault == FAULT_QUALITY:
            from ..models import QualityCheck, QualityIssue, IssueCode, Severity

            def _always_fail(*args: Any, **kwargs: Any) -> QualityCheck:
                return QualityCheck(
                    passed=False,
                    issues=[
                        QualityIssue(
                            code=IssueCode.FACT_MISMATCH,
                            severity=Severity.ERROR,
                            message="评测注入：质检始终不通过",
                        )
                    ],
                    rules_applied=["eval-fault"],
                )

            patchers.append(patch("crosspilot.engine.listing.run_quality_check", _always_fail))
        elif fault == FAULT_TIMEOUT:
            # 让"剩余时间"立刻为 0：StepRunner 在第一步就抛 SkillTimeout，
            # 走的是真实的超时分支，不是伪造的异常。
            patchers.append(patch("crosspilot.agent.steps.remaining_seconds", lambda: 0.0))
        for patcher in patchers:
            patcher.start()
        yield
    finally:
        for patcher in reversed(patchers):
            patcher.stop()


def _wrap_provider(provider: Any, fault: str) -> Any:
    mapping = {
        FAULT_RATE_LIMIT: "rate_limit",
        FAULT_NETWORK: "network",
        FAULT_AUTH: "auth",
    }
    kind = mapping.get(fault)
    return _FaultyProvider(provider, kind) if kind else provider


# ---------------------------------------------------------------------------
# 跑一条用例
# ---------------------------------------------------------------------------


def _memory_checkpointer() -> Any:
    """每个用例一份内存 saver：线程互不干扰，也不写共享库。"""
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


def observe(case: EvalCase) -> dict[str, Any]:
    """执行一条用例并返回观测结果（不做断言）。"""
    from unittest.mock import patch

    from ..agent import errors as agent_errors
    from ..agent import workflows
    from ..agent.graphs.combined_operations import build_combined_graph
    from ..llm.providers import RuleProvider
    from ..market.competitor_provider import MODE_IMPORTED, build_competitor_provider

    payload = dict(case.payload)
    provider = _wrap_provider(RuleProvider(), case.fault)
    competitor_provider = build_competitor_provider(MODE_IMPORTED, db=None, tenant_id="")
    task = MemoryTask()
    thread_task_id = f"eval-{case.case_id}"

    observed: dict[str, Any] = {
        "case_id": case.case_id,
        "dimension": case.dimension,
        "spec_kind": "",
        "plan": [],
        "steps": [],
        "outcome": "",
        "task_status": "",
        "paused": False,
        "paused_once": False,
        "pending": None,
        "report": {},
        "listing": {},
        "provenance": {},
        "error_code": "",
        "error_message": "",
        "duration_ms": 0,
    }

    saver = _memory_checkpointer()
    started = time.perf_counter()
    try:
        spec = workflows.choose(payload)
        observed["spec_kind"] = spec.kind
        observed["plan"] = spec.plan()

        with patch("crosspilot.agent.checkpoint.get_checkpointer", lambda: saver), injected(case):
            state = workflows.run(
                spec,
                payload,
                db=None,
                tenant_id=EVAL_TENANT,
                user_id=EVAL_USER,
                task_id=thread_task_id,
                provider=provider,
                competitor_provider=competitor_provider,
                task=task,
                resume_from=None,
                persist=False,
            )
            if workflows.is_paused(state):
                observed["paused"] = True
                observed["paused_once"] = True
                observed["pending"] = state.get("confirmation") or state.get("pending")

                # 人工点「继续生成」：走真实恢复路径，验证断点确实可续
                graph = build_combined_graph(provider=provider, persist=False)
                state = graph.resume(
                    "continue", workflows.thread_config(EVAL_TENANT, thread_task_id)
                )

        observed["outcome"] = state.get("outcome") or ""
        observed["task_status"] = state.get("task_status") or ""
        observed["report"] = state.get("analysis_report") or state.get("report") or {}
        observed["listing"] = state.get("listing") or {}
        observed["provenance"] = state.get("provenance") or {}
    except BaseException as exc:  # noqa: BLE001 - 评估要记录，不中断整轮
        info = agent_errors.classify(exc)
        observed["outcome"] = "failed"
        observed["error_code"] = info.category.value
        observed["error_message"] = info.message
        observed["exception"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        observed["duration_ms"] = int((time.perf_counter() - started) * 1000)
        observed["steps"] = list(task.steps)

    return observed


__all__ = ["MemoryTask", "injected", "observe"]
