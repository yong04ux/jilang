"""Agent Runtime：用 LangGraph 编排 Tool / Skill 执行。

图结构（节点即真实执行步骤，全部落 task_steps）：

    plan ──► analyze ──► integrity ──► summary ──┬─► listing ──► quality ──┐
                                                  └──────────────► persist ◄┘

设计取舍：

- **计划生成是确定性的**：自然语言目标由 ``planner`` 解析成参数，
  但"执行哪些节点"由 ``plan_for(with_listing)`` 决定，LLM 不参与，
  因此质检不会被模型跳过，测试也不需要真实模型。
- **每个节点都包在 task step 里**，失败能定位到具体节点。
- **取消在节点边界生效**：每个节点开始前检查任务状态（``cancelling``），
  命中则抛 ``TaskCancelled``，任务落成 ``cancelled``，不是失败。
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, StateGraph

from ..models import (
    AnalysisReport,
    CompetitorAnalysisRequest,
    ListingDraft,
    ListingGenerationRequest,
    OwnProduct,
    Platform,
)
from ..services.tasks import TaskCancelled, TaskRecorder
from . import planner, tools


class AgentRunError(RuntimeError):
    """Agent 执行失败（消息可直接展示）。"""


# 节点名 → 面向用户的步骤名
STEP_LABELS = {
    "plan": "生成执行计划",
    "analyze": "竞品分析",
    "integrity": "数据完整性检查",
    "summary": "生成市场机会总结",
    "listing": "生成 Listing 草稿",
    "quality": "质量检查",
    "persist": "保存报告与任务记录",
}


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
        providers: dict[str, tuple[Any, str]] | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.task = task
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.cancel_check = cancel_check
        # 断点续跑：{node: 上次成功输出}；命中的节点直接复用，不重跑（含不重调 LLM）
        self.resume_from = resume_from or {}
        # 按步骤分配模型：{node: (provider, 说明)}；缺省时全部回落到 self.provider
        self.providers = providers or {}
        self._graph = self._build_graph()

    # -- 图构建 ------------------------------------------------------------
    def _build_graph(self):
        graph = StateGraph(dict)
        graph.add_node("plan", self._node_plan)
        graph.add_node("analyze", self._node_analyze)
        graph.add_node("integrity", self._node_integrity)
        graph.add_node("summary", self._node_summary)
        graph.add_node("listing", self._node_listing)
        graph.add_node("quality", self._node_quality)
        graph.add_node("persist", self._node_persist)

        graph.set_entry_point("plan")
        graph.add_edge("plan", "analyze")
        graph.add_edge("analyze", "integrity")
        graph.add_edge("integrity", "summary")
        graph.add_conditional_edges(
            "summary",
            self._route_after_summary,
            {"listing": "listing", "persist": "persist"},
        )
        graph.add_edge("listing", "quality")
        graph.add_edge("quality", "persist")
        graph.add_edge("persist", END)
        return graph.compile()

    # -- 路由 --------------------------------------------------------------
    @staticmethod
    def _route_after_summary(state: dict[str, Any]) -> str:
        return "listing" if state.get("with_listing") else "persist"

    # -- 步骤包装 ----------------------------------------------------------
    def _step_provider(self, node: str) -> tuple[Any, str]:
        """取该节点该用的 Provider 与说明；没有按步骤配置时回落到默认 Provider。"""
        entry = self.providers.get(node)
        if entry is None:
            return self.provider, ""
        return entry

    def _checkpoint(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise TaskCancelled("用户取消")

    def _run_step(self, name: str, detail: str, fn: Callable[[], Any]) -> Any:
        import time

        self._checkpoint()
        if name in self.resume_from:
            result = self.resume_from[name]
            step_id = self.task.begin_step(STEP_LABELS[name], "复用上次成功步骤", node=name)
            self.task.end_step(
                step_id,
                status="succeeded",
                detail="复用上次成功步骤（未重跑）",
                duration_ms=0,
                output=result,
            )
            return result
        started = time.perf_counter()
        step_id = self.task.begin_step(STEP_LABELS[name], detail, node=name)
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - 记录失败后继续抛出
            self.task.end_step(
                step_id,
                status="failed",
                detail=f"失败：{type(exc).__name__}: {exc}"[:500],
                started_perf=started,
            )
            raise
        self.task.end_step(step_id, started_perf=started, output=result)
        return result

    # -- 节点 --------------------------------------------------------------
    def _node_plan(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> list[str]:
            return planner.plan_for(bool(state.get("with_listing")))

        detail = "按输入确定步骤（确定性规则）"
        if state.get("goal"):
            detail = "目标已解析；执行节点由确定性规则决定"
        if state.get("degraded"):
            detail = "目标解析降级为规则；执行节点不变"
        plan = self._run_step("plan", detail, body)
        state["plan"] = plan
        return state

    def _node_analyze(self, state: dict[str, Any]) -> dict[str, Any]:
        provider, note = self._step_provider("analyze")

        def body() -> dict[str, Any]:
            request = CompetitorAnalysisRequest(
                product_name=state["product_name"],
                platform=Platform(state.get("platform") or "amazon"),
                marketplace=state.get("marketplace") or "US",
                category=state.get("category"),
                own_specs=state.get("own_specs") or {},
                own_key_features=state.get("own_key_features") or [],
                own_price=state.get("own_price"),
                competitors=state["competitors"],
                keywords=state.get("keywords") or [],
                data_source=state.get("data_source") or "manual",
            )
            report = tools.run_competitor_analysis(provider, request)
            return report.model_dump(mode="json")

        detail = f"{len(state['competitors'])} 个竞品"
        if note:
            detail = f"{detail} · {note}"
        state["report"] = self._run_step("analyze", detail, body)
        return state

    def _node_integrity(self, state: dict[str, Any]) -> dict[str, Any]:
        report = AnalysisReport(**state["report"])
        checks = self._run_step(
            "integrity",
            "检查竞品数、评论样本、价格覆盖与字段缺失",
            lambda: _integrity(report),
        )
        state["checks"] = checks
        return state

    def _node_summary(self, state: dict[str, Any]) -> dict[str, Any]:
        report = AnalysisReport(**state["report"])
        summary = self._run_step(
            "summary",
            "只引用报告已有结论，不调用模型",
            lambda: _summary(report),
        )
        state["summary"] = summary
        return state

    def _node_listing(self, state: dict[str, Any]) -> dict[str, Any]:
        provider, note = self._step_provider("listing")

        def body() -> dict[str, Any]:
            product = OwnProduct(
                name=state["product_name"],
                brand=state.get("brand"),
                target_platform=Platform(state.get("platform") or "amazon"),
                marketplace=state.get("marketplace") or "US",
                specifications=state.get("own_specs") or {},
                key_features=state.get("own_key_features") or [],
                certifications=state.get("certifications") or [],
                price=state.get("own_price"),
                target_audience=state.get("target_audience"),
                banned_terms=state.get("banned_terms") or [],
            )
            request = ListingGenerationRequest(
                product=product,
                language=state.get("listing_language") or "en-US",
                marketplace=state.get("marketplace") or "US",
                analysis_report=state["report"],
                data_source=state.get("data_source") or "manual",
            )
            listing = tools.generate_listing(provider, request, state["report"])
            # 保存商品事实快照，供后续版本复检（不参与对外展示）
            payload = listing.model_dump(mode="json")
            payload["product_snapshot"] = request.product.model_dump(mode="json")
            return payload

        detail = "基于事实台账生成文案"
        if note:
            detail = f"{detail} · {note}"
        state["listing"] = self._run_step("listing", detail, body)
        return state

    def _node_quality(self, state: dict[str, Any]) -> dict[str, Any]:
        listing = ListingDraft(**state["listing"])
        quality = self._run_step(
            "quality",
            "读取质检结果，不重复实现规则",
            lambda: tools.run_quality_check(listing),
        )
        state["quality"] = quality
        return state

    def _node_persist(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            report = state.get("report") or {}
            listing = state.get("listing") or {}
            if report:
                self.db.save_report(
                    report,
                    user_id=self.user_id,
                    tenant_id=self.tenant_id,
                    task_id=self.task.task_id,
                )
            if listing:
                self.db.save_listing(
                    listing,
                    user_id=self.user_id,
                    tenant_id=self.tenant_id,
                    task_id=self.task.task_id,
                )
            return {
                "report_id": report.get("report_id"),
                "listing_id": listing.get("listing_id"),
            }

        persisted = self._run_step("persist", "写入报告与草稿", body)
        state["persisted"] = persisted
        self.task.succeed(
            result_ref=persisted.get("report_id") or persisted.get("listing_id"),
            output={
                "report_id": persisted.get("report_id"),
                "listing_id": persisted.get("listing_id"),
                "plan": state.get("plan") or [],
                "summary": state.get("summary"),
                "checks": state.get("checks"),
                "quality": state.get("quality"),
                "degraded": bool(state.get("degraded")),
                "degraded_reason": state.get("degraded_reason") or "",
                "goal": state.get("goal") or "",
            },
        )
        return state

    # -- 入口 --------------------------------------------------------------
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: dict[str, Any] = dict(payload)
        state.setdefault("with_listing", True)
        state.setdefault("platform", "amazon")
        state.setdefault("marketplace", "US")
        try:
            final = self._graph.invoke(state)
        except TaskCancelled:
            self.task.cancel()
            raise
        except Exception as exc:  # noqa: BLE001 - 统一转成可展示的错误
            self.task.fail(code="agent_step_failed", message=f"{type(exc).__name__}: {exc}"[:500])
            raise AgentRunError(str(exc)) from exc
        return final


def _integrity(report: AnalysisReport) -> dict[str, Any]:
    from .skills import check_integrity

    return check_integrity(report)


def _summary(report: AnalysisReport) -> dict[str, Any]:
    from .skills import market_summary

    return market_summary(report)


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
    providers: dict[str, tuple[Any, str]] | None = None,
) -> dict[str, Any]:
    """执行一个已创建的任务。异常由 Runtime 记录到任务上。

    ``providers`` 用于「按步骤分配模型」：``{node: (provider, 说明)}``，
    只有 ``analyze`` / ``listing`` 会被查询；缺省时全部用 ``provider``。
    """
    recorder.mark_running()
    runtime = AgentRuntime(
        db=db,
        provider=provider,
        task=recorder,
        user_id=recorder.user_id,
        tenant_id=recorder.tenant_id or "",
        cancel_check=cancel_check or recorder.is_cancel_requested,
        resume_from=resume_from,
        providers=providers,
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
    providers: dict[str, tuple[Any, str]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """创建任务并同步执行整张图，返回 (task_id, 结果)。"""
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
        recorder, db=db, provider=provider, payload=payload, providers=providers
    )
    return recorder.task_id, final


__all__ = [
    "AgentRunError",
    "AgentRuntime",
    "STEP_LABELS",
    "create_agent_task",
    "execute_agent",
    "run_agent",
]
