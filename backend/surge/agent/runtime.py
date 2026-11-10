"""Agent 执行入口：校验 → 分派 → 收尾。

主图不再是一张十几个节点的 LangGraph。业务只有两份，都在子图里：

- ``with_listing=false`` → 竞品分析子图（``graphs/competitor_analysis.py``）
- ``with_listing=true``  → 组合子图（``graphs/combined_operations.py``）

这一层只做三件事，而且**只做这三件**：

1. ``validate``：确认工作流真的能跑（商品名、竞品非空）；
2. ``dispatch``：按 ``with_listing`` 选工作流，交给 ``agent/workflows.py``；
3. ``finalize``：把结局落到任务状态（暂停时**不收尾**，见下）。

为什么不是"一张只有三个节点的图"
================================

试过：把带 ``interrupt`` 的组合子图当节点塞进父图。**实测恢复时父图的
``validate`` 与子图的 ``analyze`` 都会重跑一遍**（LangGraph 会从头重放到中断点），
这既违反「恢复不重复执行竞品分析」，真实 Provider 下还会把分析费用付两遍。
所以分派发生在图级：先选图，再直接跑那张图。恢复命中的仍是同一张顶层图，
中断节点之外都不会重跑。

暂停为什么不收尾
================

``finalize`` 之前先判 ``is_paused``：停在确认点的任务必须留在
``waiting_for_review``，等确认接口恢复。一旦这里把状态写成 succeeded，
用户点确认时任务已经"完成"，工作流却还在等——这是最难查的一类不一致。
"""

from __future__ import annotations

from typing import Any, Callable

from ..services.tasks import TaskCancelled, TaskRecorder
from . import errors as agent_errors
from . import steps as steps_module
from . import workflows
from .state import OUTCOME_NEEDS_INPUT


class AgentRunError(RuntimeError):
    """Agent 执行失败（消息可直接展示）。

    ``info`` 是统一错误分类的结论（``agent/errors.py``）：HTTP 层据此决定状态码。
    """

    def __init__(self, message: str, *, info: "agent_errors.ErrorInfo | None" = None) -> None:
        super().__init__(message)
        self.info = info or agent_errors.make(
            agent_errors.ErrorCategory.INTERNAL_ERROR, message=message
        )


class AgentRuntime:
    """一次 Agent 运行。实例只跑一次任务。"""

    def __init__(
        self,
        *,
        db,
        provider,
        task: TaskRecorder,
        user_id: str,
        tenant_id: str,
        cancel_check: Callable[[], bool] | None = None,
        resume_from: dict[str, Any] | None = None,
        competitor_provider: Any = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.task = task
        self.user_id = user_id
        self.tenant_id = tenant_id
        # 断点续跑：{node: 上次成功输出}，命中的节点不重跑（子图的 StepRunner 负责）
        self.resume_from = resume_from or {}
        self.competitor_provider = competitor_provider
        self._steps = workflows.step_runner(task, self.resume_from, cancel_check)

    # -- 阶段 --------------------------------------------------------------
    def _validate(self, state: dict[str, Any]) -> None:
        def body() -> dict[str, Any]:
            from .contracts import SkillInputInvalid

            missing: list[str] = []
            if not str(state.get("product_name") or "").strip():
                missing.append("product_name")
            # 只写文案的运行不需要竞品：竞品是分析侧的必需输入，不是 Listing 的
            if not state.get("listing_only") and not state.get("competitors"):
                missing.append("competitors")
            if missing:
                raise SkillInputInvalid(
                    "缺少运行所需的输入",
                    detail={"missing": missing, "errors": [
                        {"field": name, "message": "必填"} for name in missing
                    ]},
                )
            return {"with_listing": bool(state.get("with_listing")), "has_competitors": True}

        self._steps.run("validate", "确认工作流能跑起来", body)

    def _dispatch(self, state: dict[str, Any]) -> workflows.WorkflowSpec:
        def body() -> dict[str, Any]:
            spec = workflows.choose(state)
            return {"kind": spec.kind, "label": spec.label, "needs_llm": spec.needs_llm}

        spec = workflows.choose(state)
        # 先算 spec 再记录：detail 里要写清"分派到哪条"，用户才看得懂时间线
        self._steps.run("dispatch", f"工作流：{spec.label}", body)
        return spec

    def _finalize(self, state: dict[str, Any], spec: workflows.WorkflowSpec) -> str:
        def body() -> dict[str, Any]:
            return workflows.apply_result(self.task, state, self.db, spec=spec)

        return str(self._steps.run("finalize", "按结局落任务状态", body))

    # -- 入口 --------------------------------------------------------------
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: dict[str, Any] = dict(payload)
        state.setdefault("with_listing", True)
        state.setdefault("platform", "amazon")
        state.setdefault("marketplace", "US")

        spec: workflows.WorkflowSpec | None = None
        try:
            self._validate(state)
            spec = self._dispatch(state)
            # 超时窗口覆盖整条工作流（含子图）。用 ContextVar 传递，
            # 免得把 deadline 一路穿过 combined → competitor/listing 的构造参数。
            token = steps_module.begin_deadline(spec.timeout_seconds)
            try:
                result = workflows.run(
                    spec,
                    state,
                    db=self.db,
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    task_id=self.task.task_id,
                    provider=self.provider,
                    competitor_provider=self.competitor_provider,
                    task=self.task,
                    resume_from=self.resume_from,
                )
            finally:
                steps_module.end_deadline(token)

            if workflows.is_paused(result):
                # 暂停：落 pending 与计划骨架，**不收尾**
                self.task.await_review(
                    output={
                        "pending": workflows.pending_payload(result),
                        "plan": spec.plan(),
                        "workflow": spec.kind,
                        "analysis_outcome": result.get("analysis_outcome"),
                        "analysis_summary": result.get("analysis_summary"),
                        "provenance": result.get("analysis_provenance") or {},
                    }
                )
                result["task_status"] = "waiting_for_review"
                return result

            self._finalize(result, spec)
        except TaskCancelled:
            self.task.cancel()
            raise
        except AgentRunError:
            # 已经分过类，别重复分类
            raise
        except Exception as exc:  # noqa: BLE001 - 统一分类后转成可展示的错误
            info = agent_errors.classify(exc)
            self.task.fail(code=info.task_code, message=info.message[:500])
            raise AgentRunError(info.message, info=info) from exc

        # 缺商品事实：任务已经落成 waiting_for_input（见 apply_result），
        # 但请求本身是"没法执行"，所以用 422 明确告诉调用方"需要补资料"，
        # 而不是 200 + 空结果让前端自己去猜。
        if result.get("outcome") == OUTCOME_NEEDS_INPUT:
            missing = (result.get("artifact") or {}).get("missing") or []
            info = agent_errors.make(
                agent_errors.ErrorCategory.MISSING_INPUT,
                message=result.get("message") or "缺少商品资料，请补充后重试",
                code="product_facts_missing",
                detail={"missing": missing},
            )
            raise AgentRunError(info.message, info=info)
        return result

def create_agent_task(
    *,
    db,
    user_id: str,
    tenant_id: str,
    payload: dict[str, Any],
    task_type: str = "agent_workflow",
    title: str | None = None,
    conversation_id: str | None = None,
    degraded: bool = False,
    queued: bool = False,
    retry_of: str | None = None,
) -> TaskRecorder:
    """创建任务记录（不执行）。异步模式以 queued 落库，交给执行器。"""
    recorder = TaskRecorder(
        db,
        user_id,
        task_type,
        title or f"Agent 任务：{payload.get('product_name', '')}",
        origin="chat",
        payload=payload,
        tenant_id=tenant_id,
        initial_status="queued" if queued else "running",
        conversation_id=conversation_id,
        degraded=degraded,
        retry_of=retry_of,
    )
    recorder.open()
    return recorder


def execute_agent(
    recorder: TaskRecorder,
    *,
    db,
    provider,
    payload: dict[str, Any],
    cancel_check: Callable[[], bool] | None = None,
    resume_from: dict[str, Any] | None = None,
    competitor_provider: Any = None,
) -> dict[str, Any]:
    """执行一个已创建的任务。异常由 Runtime 记录到任务上。

    """
    recorder.mark_running()
    # 记录本次输入的指纹与工作流版本：下一次重试要靠这两项判断"能不能复用旧结果"。
    # 放在执行前更新，保证"比较用的是上次的值、写入的是这次的"。
    try:
        db.update_task(
            recorder.task_id,
            input_fingerprint=workflows.fingerprint(payload),
            workflow_version=workflows.WORKFLOW_VERSION,
        )
    except Exception:  # noqa: BLE001 - 记录失败只影响复用判断，不该阻断执行
        pass
    runtime = AgentRuntime(
        db=db,
        provider=provider,
        task=recorder,
        user_id=recorder.user_id,
        tenant_id=recorder.tenant_id or "",
        cancel_check=cancel_check,
        resume_from=resume_from,
        competitor_provider=competitor_provider,
    )
    return runtime.run(payload)


def run_agent(
    *,
    db,
    provider,
    user_id: str,
    tenant_id: str,
    payload: dict[str, Any],
    task_type: str = "agent_workflow",
    title: str | None = None,
    conversation_id: str | None = None,
    degraded: bool = False,
    competitor_provider: Any = None,
) -> tuple[str, dict[str, Any]]:
    """创建任务并同步执行，返回 (task_id, 结果状态)。"""
    recorder = create_agent_task(
        db=db,
        user_id=user_id,
        tenant_id=tenant_id,
        payload=payload,
        task_type=task_type,
        title=title,
        conversation_id=conversation_id,
        degraded=degraded,
    )
    final = execute_agent(
        recorder,
        db=db,
        provider=provider,
        payload=payload,
        competitor_provider=competitor_provider,
    )
    return recorder.task_id, final


__all__ = [
    "AgentRunError",
    "AgentRuntime",
    "create_agent_task",
    "execute_agent",
    "run_agent",
]
