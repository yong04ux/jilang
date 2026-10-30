"""组合工作流的**恢复**编排。

下这一步只剩"恢复"这一件事：

- 首次执行已经统一到 ``agent/workflows.py``（主图分派后直接跑组合子图）；
- 结果收尾统一到 ``workflows.apply_result``；
- 待确认载荷统一到 ``workflows.pending_payload``。

保留本模块的原因是**恢复不是"再跑一遍"**：它必须用
``Command(resume=...)`` 打在同一份 checkpoint 上，和 ``start`` 的调用形态不同。
把这个差异收在一个函数里，确认接口就不用了解 LangGraph 的细节。

本模块只做三件事：探测可恢复性、恢复执行、清理。**不再有第二套收尾逻辑**——
那正是收敛前"两套主图各写一份"的老毛病。
"""

from __future__ import annotations

from typing import Any

from ..agent.checkpoint import thread_config
from ..agent.graphs.combined_operations import (
    DECISION_CANCEL,
    DECISION_CONTINUE,
    build_combined_graph,
)
from ..agent.workflows import (
    KIND_COMBINED,
    WorkflowSpec,
    apply_result,
    is_paused,
    pending_payload,
    result_output,
)
from ..persistence.db import Database

#: 兼容旧值：早期组合任务用过这个类型名。现在统一走 ``agent_workflow``，
#: 但确认接口不再依赖类型名判断（只认状态与待确认载荷），所以保留常量不删。
TASK_TYPE = "combined_workflow"

#: 恢复时给 ``apply_result`` 用的 spec（组合流程的步骤骨架）。
_COMBINED_SPEC = WorkflowSpec(
    kind=KIND_COMBINED,
    label="竞品分析 + Listing 生成",
    step_names=(
        "validate_request",
        "run_analysis",
        "prepare_confirmation",
        "confirm_partial",
        "check_listing_facts",
        "run_listing",
        "settle",
    ),
    needs_llm=True,
)


class CombinedRunError(RuntimeError):
    """组合工作流无法恢复。"""


def has_pending_checkpoint(tenant_id: str, task_id: str, *, provider: Any) -> bool:
    """线程里是否真的存在待恢复的中断点。

    恢复前必须先问这一句：进程重启后内存 checkpoint 会丢，
    直接 ``Command(resume=...)`` 会让 LangGraph 从入口重新开始跑，
    而状态是空的 —— 表现为莫名其妙的 KeyError，用户完全看不懂。
    提前判断就能给一句"工作流状态已失效，请重新发起"。
    """
    graph = build_combined_graph(provider=provider, persist=False)
    return bool(graph.pending(thread_config(tenant_id, task_id)))


def resume(
    db: Database,
    *,
    tenant_id: str,
    user_id: str,
    task_id: str,
    decision: str,
    provider: Any,
    competitor_provider: Any = None,
    persist: bool = True,
    task: Any = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从暂停点恢复。**已完成的竞品分析不会重跑**（checkpoint 保证）。"""
    graph = build_combined_graph(
        provider=provider,
        competitor_provider=competitor_provider,
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        task=task,
        persist=persist,
    )
    return graph.resume(decision, config or thread_config(tenant_id, task_id))


def pending(tenant_id: str, task_id: str, *, provider: Any) -> list[dict[str, Any]]:
    """读当前线程的待确认载荷（诊断用）。"""
    graph = build_combined_graph(provider=provider, persist=False)
    return graph.pending(thread_config(tenant_id, task_id))


def spec() -> WorkflowSpec:
    return _COMBINED_SPEC


__all__ = [
    "DECISION_CANCEL",
    "DECISION_CONTINUE",
    "TASK_TYPE",
    "CombinedRunError",
    "apply_result",
    "has_pending_checkpoint",
    "is_paused",
    "pending",
    "pending_payload",
    "resume",
    "result_output",
    "spec",
]
