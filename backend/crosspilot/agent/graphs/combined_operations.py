"""组合工作流（Phase 5）：竞品分析 → （partial 时人工确认）→ Listing 生成。

节点图
======

    validate_request
      -> run_analysis            （复用竞品子图，persist=False）
      -> route_after_analysis
           ├─ success  ────────────────────────────┐
           ├─ partial  -> prepare_confirmation     │
           │               -> confirm_partial ◄────┼── interrupt() 暂停点
           │                    ├─ continue ───────┤
           │                    └─ cancel  -> cancel_flow -> END
           └─ failed   -> 抛异常（统一错误处理，不进入 Listing）
      -> check_listing_facts     （即使已确认也必须过这一关）
           ├─ 缺必需事实 -> needs_user_input -> END
           └─ 齐 -> run_listing  （复用 Listing 子图，含质检与有限修订）
                       -> settle -> END

> 末节点叫 ``settle`` 而不是 ``finalize``：主图的统一收尾步骤已经叫 ``finalize``，
> 两个同名节点混在一条时间线里，看的人分不清哪条是"业务落库"哪条是"任务收尾"。

三条硬约束（对应需求里的「不得」）
==================================

**① partial 不得静默变 success。**
``settle`` 里只要分析阶段是 partial，最终 ``outcome`` 就保持 partial，
任务状态也落 ``partial``；确认只代表"用户允许继续"，不代表"数据够用了"。

**② 不得把推断当成商品事实。**
Listing 子图只读 ``OwnProduct``（用户给的规格/卖点）。竞品分析结论只通过
``analysis_report`` 作为"差异化参考"传入，**不会被写进事实台账**。
这不是靠自觉：``engine.listing_llm`` 的质检会拦掉台账外的数字与断言。

**③ 不得因确认而跳过质检。**
``run_listing`` 必然经过 ``validate_listing`` 与有限修订循环，
确认流程里没有任何"跳过质检"的分支。

暂停点的实现要点
================

``confirm_partial`` 里 ``interrupt()`` 是**第一条语句**。原因见
``agent/state.py`` 的说明：恢复时中断节点会从头重跑，任何放在它前面的
副作用都会执行两次。因此：待确认载荷在 ``prepare_confirmation`` 里算好并写进状态，
确认节点只负责问与收答案。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from ...services import listing_facts
from ...services.artifacts import save_run_artifacts
from ...services.tasks import TaskRecorder
from ..contracts import SkillInputInvalid
from ..state import (
    OUTCOME_CANCELLED,
    OUTCOME_NEEDS_INPUT,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_PARTIAL,
    OUTCOME_SUCCEEDED,
    CombinedState,
)
from ..steps import StepRunner
from .competitor_analysis import run_competitor_graph
from .listing_generation import run_listing_graph

DECISION_CONTINUE = "continue"
DECISION_CANCEL = "cancel"

STEP_LABELS = {
    "validate_request": "校验组合请求",
    "run_analysis": "竞品分析",
    "prepare_confirmation": "整理待确认信息",
    "confirm_partial": "等待用户确认",
    "cancel_flow": "按用户要求取消",
    "check_listing_facts": "检查 Listing 必需事实",
    "needs_user_input": "等待补充商品资料",
    "run_listing": "生成 Listing 草稿",
    "settle": "收尾并保存结果",
}


def _confirmation_token(report: dict[str, Any], reasons: list[str]) -> str:
    """确认令牌：把"这次暂停是因为什么"压成一个短哈希。

    用途是**确认内容校验**——用户界面在暂停时拿到这个令牌，确认时原样带回。
    如果中途任务被重跑成另一次暂停（数据变了、原因变了），令牌就对不上，
    接口会拒绝，避免"看着旧的缺失清单点了确认，实际应用到新的一次暂停"。

    不用密钥、不可逆推：它不是鉴权凭证（鉴权由登录态 + 任务归属完成），
    只是一致性校验。
    """
    material = json.dumps(
        {
            "report_id": report.get("report_id"),
            "competitor_count": (report.get("data_provenance") or {}).get("competitor_count"),
            "reasons": reasons,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


class CombinedGraph:
    """一次组合工作流运行。实例可跨"暂停 → 恢复"两次请求复用同一份图。"""

    def __init__(
        self,
        *,
        provider: Any,
        competitor_provider: Any = None,
        db: Any = None,
        tenant_id: str = "",
        user_id: str = "",
        task: TaskRecorder | None = None,
        persist: bool = False,
        resume_from: dict[str, Any] | None = None,
        listing_note: str = "",
    ) -> None:
        self.provider = provider
        self.competitor_provider = competitor_provider
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.task = task
        self.persist = persist
        # 这一步用的是哪套模型配置，要能在时间线上看到（按步骤分配模型的可见性）
        self.listing_note = listing_note
        self._steps = StepRunner(task=task, resume_from=resume_from, labels=STEP_LABELS)
        self._graph = self._build()

    # -- 图构建 ------------------------------------------------------------
    def _build(self):
        from ..checkpoint import get_checkpointer

        graph = StateGraph(dict)
        graph.add_node("validate_request", self._node_validate)
        graph.add_node("run_analysis", self._node_analysis)
        graph.add_node("prepare_confirmation", self._node_prepare_confirmation)
        graph.add_node("confirm_partial", self._node_confirm)
        graph.add_node("cancel_flow", self._node_cancel)
        graph.add_node("check_listing_facts", self._node_check_facts)
        graph.add_node("needs_user_input", self._node_needs_input)
        graph.add_node("run_listing", self._node_listing)
        graph.add_node("settle", self._node_finalize)

        graph.set_entry_point("validate_request")
        graph.add_edge("validate_request", "run_analysis")
        # 先判商品事实，再决定要不要问用户：
        # 事实缺了就必然生成不了，这时候还问"要不要继续"只会白浪费一次点击。
        graph.add_edge("run_analysis", "check_listing_facts")
        graph.add_conditional_edges(
            "check_listing_facts",
            self._route_after_facts,
            {
                "block": "needs_user_input",
                "partial": "prepare_confirmation",
                "success": "run_listing",
            },
        )
        graph.add_edge("prepare_confirmation", "confirm_partial")
        graph.add_conditional_edges(
            "confirm_partial",
            self._route_after_confirmation,
            {"continue": "run_listing", "cancel": "cancel_flow"},
        )
        graph.add_edge("cancel_flow", END)
        graph.add_edge("needs_user_input", END)
        graph.add_edge("run_listing", "settle")
        graph.add_edge("settle", END)
        # checkpoint 是暂停/恢复的前提，不是可选优化
        return graph.compile(checkpointer=get_checkpointer())

    # -- 步骤包装 ----------------------------------------------------------
    def _step(self, name: str, detail: str, fn: Callable[[], Any]) -> Any:
        return self._steps.run(name, detail, fn)

    # -- 路由 --------------------------------------------------------------
    def _route_after_facts(self, state: dict[str, Any]) -> str:
        """一个路由回答两件事：事实够不够写、分析样本够不够撑结论。

        顺序有意义：**事实**不够就先停（补资料才能继续），
        事实够了才轮到"样本不足要不要问用户"。
        """
        if not state["required"]["can_generate"]:
            return "block"
        return "partial" if state.get("analysis_outcome") == OUTCOME_PARTIAL else "success"

    @staticmethod
    def _route_after_confirmation(state: dict[str, Any]) -> str:
        return DECISION_CANCEL if state.get("decision") == DECISION_CANCEL else DECISION_CONTINUE

    # -- 阶段一：竞品分析 --------------------------------------------------
    def _node_validate(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            from ..definitions import CompetitorAnalysisInput, ListingGenerationInput

            request = state.get("request") or {}
            analysis_fields = {
                "product_name": request.get("product_name"),
                "platform": request.get("platform") or "amazon",
                "marketplace": request.get("marketplace") or "US",
                "category": request.get("category"),
                "own_specs": request.get("own_specs") or {},
                "own_key_features": request.get("own_key_features") or [],
                "own_price": request.get("own_price"),
                "competitors": request.get("competitors") or [],
                "keywords": request.get("keywords") or [],
                "data_source": request.get("data_source") or "manual",
            }
            listing_fields = {
                "product": {
                    "name": request.get("product_name"),
                    "brand": request.get("brand"),
                    "target_platform": request.get("platform") or "amazon",
                    "marketplace": request.get("marketplace") or "US",
                    "specifications": request.get("own_specs") or {},
                    "key_features": request.get("own_key_features") or [],
                    "certifications": request.get("certifications") or [],
                    "price": request.get("own_price"),
                    "target_audience": request.get("target_audience"),
                    "banned_terms": request.get("banned_terms") or [],
                },
                "language": request.get("listing_language") or "en-US",
                "marketplace": request.get("marketplace") or "US",
                "data_source": request.get("data_source") or "manual",
            }
            try:
                CompetitorAnalysisInput(**analysis_fields)
                ListingGenerationInput(**listing_fields)
            except ValidationError as exc:
                fields = [
                    {
                        "field": ".".join(str(p) for p in err.get("loc", ())) or None,
                        "message": str(err.get("msg") or ""),
                    }
                    for err in exc.errors()[:8]
                ]
                raise SkillInputInvalid("组合请求参数不合法", detail={"errors": fields}) from exc
            return {"analysis_request": analysis_fields, "listing_request": listing_fields}

        built = self._step("validate_request", "校验分析侧与文案侧参数", body)
        state["analysis_request"] = built["analysis_request"]
        state["listing_request"] = built["listing_request"]
        return state

    def _node_analysis(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            result = run_competitor_graph(
                {"request": state["analysis_request"], "persist": False},
                provider=self.provider,
                competitor_provider=self.competitor_provider,
                db=self.db,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                task=None,
                persist=False,
            )
            return {
                "outcome": result["outcome"],
                "report": result["report"],
                "summary": result["summary"],
                "provenance": result["provenance"],
                # partial 的原因要单独留一份：provenance 里的键会随版本变
                "reasons": list((result.get("provenance") or {}).get("partial_reasons") or []),
            }

        analysis = self._step("run_analysis", "复用竞品分析子图", body)
        state["analysis_outcome"] = analysis["outcome"]
        state["analysis_report"] = analysis["report"]
        state["analysis_summary"] = analysis["summary"]
        state["analysis_provenance"] = analysis["provenance"]
        state["analysis_reasons"] = analysis["reasons"]
        return state

    # -- 暂停点 ------------------------------------------------------------
    def _node_prepare_confirmation(self, state: dict[str, Any]) -> dict[str, Any]:
        """把"缺什么、影响什么、继续的风险"算成一段给用户看的话。

        放在独立节点里（而不是确认节点里），因为确认节点恢复时会重跑——
        这里只计算、无副作用，重跑也安全。
        """

        def body() -> dict[str, Any]:
            report = state["analysis_report"]
            reasons = state["analysis_reasons"]
            metrics = report.get("data_provenance") or {}
            provenance = state.get("analysis_provenance") or {}

            # 受影响的结论直接从"缺什么"推出来，不另造一套判断
            prices = report.get("price_analysis") or {}
            insights = report.get("review_insights") or {}
            affected: list[str] = []
            if not prices.get("compared_count"):
                affected.append("价格定位（没有可对比的竞品价格）")
            if not insights.get("total_samples"):
                affected.append("评论痛点与需求洞察（没有评论样本）")
            if int(metrics.get("competitor_count") or 0) < 3:
                affected.append("卖点覆盖与差异化方向的置信度（样本偏少）")
            if not affected:
                affected.append("整体结论的置信度")

            payload = {
                "kind": "partial_analysis_confirmation",
                "question": "竞品数据不足，是否仍按现有数据生成 Listing？",
                "reasons": reasons,
                "affected_conclusions": affected,
                "risks": [
                    "结论基于较少样本，价格与卖点判断可能不代表真实市场",
                    "Listing 只会使用你已提供的商品事实，不会用竞品数据补全参数",
                ],
                "metrics": {
                    "competitor_count": metrics.get("competitor_count"),
                    "review_sample_count": metrics.get("review_sample_count"),
                    "is_demo": bool((state.get("analysis_provenance") or {}).get("is_demo")),
                },
                "options": [DECISION_CONTINUE, DECISION_CANCEL],
            }
            payload["confirmation_token"] = _confirmation_token(report, reasons)
            return payload

        state["confirmation"] = self._step(
            "prepare_confirmation", "列出缺失项、受影响的结论与风险", body
        )
        return state

    def _node_confirm(self, state: dict[str, Any]) -> dict[str, Any]:
        """暂停点。**第一句必须是 interrupt()**，恢复时本节点会整体重跑。"""
        decision = interrupt(state["confirmation"])
        # 容错：调用方可能直接回传 {"decision": "..."}
        if isinstance(decision, dict):
            decision = decision.get("decision") or DECISION_CANCEL
        state["decision"] = DECISION_CANCEL if decision == DECISION_CANCEL else DECISION_CONTINUE
        return state

    def _node_cancel(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            return {"reason": "用户在确认竞品数据不足后选择取消"}

        payload = self._step("cancel_flow", "按用户要求结束工作流", body)
        state["outcome"] = OUTCOME_CANCELLED
        state["task_status"] = "cancelled"
        state["message"] = payload["reason"] + "，未生成 Listing"
        state["artifact"] = {}
        return state

    # -- 阶段二：Listing ---------------------------------------------------
    def _node_check_facts(self, state: dict[str, Any]) -> dict[str, Any]:
        """确认继续之后仍然要过这一关（需求第 6 条）。"""
        product = state["listing_request"]["product"]

        def body() -> dict[str, Any]:
            facts = listing_facts.resolve_product_facts(product)
            return listing_facts.check_required_facts(facts)

        state["required"] = self._step(
            "check_listing_facts", "判断是否有可引用的事实", body
        )
        return state

    def _node_needs_input(self, state: dict[str, Any]) -> dict[str, Any]:
        required = state["required"]

        def body() -> dict[str, Any]:
            return {"missing": required["missing"], "missing_labels": required["missing_labels"]}

        state["artifact"] = self._step("needs_user_input", "缺少可引用事实，停止生成", body)
        state["outcome"] = OUTCOME_NEEDS_INPUT
        state["task_status"] = "waiting_for_input"
        state["message"] = (
            (required["reason"] + "。请补充商品规格或卖点后重试。")
            if required["reason"]
            else "缺少商品资料，请补充后重试。"
        )
        return state

    def _node_listing(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            result = run_listing_graph(
                {
                    "request": state["listing_request"],
                    "analysis_report": state["analysis_report"],
                    "persist": False,
                    "task_id": state.get("task_id"),
                },
                provider=self.provider,
                db=self.db,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                task=None,
                persist=False,
            )
            return {
                "listing": result.get("listing") or {},
                "outcome": result.get("outcome"),
                "revisions": int(result.get("revision") or 0),
                "message": result.get("message") or "",
            }

        detail = "复用 Listing 子图（含质检与有限修订）"
        if self.listing_note:
            detail = f"{detail} · {self.listing_note}"
        listing = self._step("run_listing", detail, body)
        state["listing"] = listing["listing"]
        state["listing_review"] = {
            "outcome": listing["outcome"],
            "revisions": listing["revisions"],
            "message": listing["message"],
        }
        return state

    def _node_finalize(self, state: dict[str, Any]) -> dict[str, Any]:
        review = state.get("listing_review") or {}
        analysis_partial = state.get("analysis_outcome") == OUTCOME_PARTIAL
        revised_but_failed = (
            review.get("outcome") == OUTCOME_NEEDS_REVIEW and int(review.get("revisions") or 0) > 0
        )

        def body() -> dict[str, Any]:
            saved: dict[str, Any] = {"report_id": None, "listing_id": None}
            if state.get("persist"):
                saved = save_run_artifacts(
                    self.db,
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    task_id=state.get("task_id"),
                    report=state.get("analysis_report"),
                    listing=state.get("listing") or None,
                )
            return saved

        state["artifact"] = self._step("settle", "写入结果并判定最终状态", body)

        # partial 不得静默变 success：分析阶段不足，最终结论就必须带上这个标记
        if analysis_partial or revised_but_failed:
            state["outcome"] = OUTCOME_PARTIAL
            state["task_status"] = "partial"
            bits: list[str] = []
            if analysis_partial:
                bits.append("竞品样本不足，结论仅供参考")
            if revised_but_failed:
                bits.append("文案修订后仍未通过质检，需人工复核")
            state["message"] = "；".join(bits)
        else:
            state["outcome"] = OUTCOME_SUCCEEDED
            state["task_status"] = "succeeded"
            state["message"] = "分析完成，Listing 草稿已通过质检"

        state["provenance"] = {
            **(state.get("analysis_provenance") or {}),
            "analysis_outcome": state.get("analysis_outcome"),
            "listing_revisions": int(review.get("revisions") or 0),
        }
        return state

    # -- 入口 --------------------------------------------------------------
    def start(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """从入口开始跑，遇到 interrupt 就停下并返回当前状态。"""
        state: dict[str, Any] = dict(payload)
        state.setdefault("persist", self.persist)
        return self._graph.invoke(state, config)

    def resume(self, decision: str, config: dict[str, Any]) -> dict[str, Any]:
        """从暂停点继续。已完成的分析节点不会重跑（checkpoint 保证）。"""
        return self._graph.invoke(Command(resume=decision), config)

    def pending(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """当前线程的待确认载荷；空列表表示没有可恢复的中断点。"""
        from ..checkpoint import pending_interrupts

        return pending_interrupts(self._graph, config)


def build_combined_graph(**kwargs: Any) -> CombinedGraph:
    return CombinedGraph(**kwargs)


def run_combined_graph(
    payload: dict[str, Any],
    *,
    provider: Any,
    competitor_provider: Any = None,
    db: Any = None,
    tenant_id: str = "",
    user_id: str = "",
    task: TaskRecorder | None = None,
    persist: bool = False,
    resume_from: dict[str, Any] | None = None,
    listing_note: str = "",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从入口跑组合工作流。返回图状态——可能停在 ``interrupt``。

    ``config`` 必须带 ``thread_id``（要能暂停就必须能恢复）；不传时按
    tenant+task 生成。没有 task_id 直接报错——没有线程标识的暂停是无意义的，
    恢复时找不到状态。
    """
    from ..checkpoint import thread_config

    task_id = str(payload.get("task_id") or "").strip()
    if config is None:
        if not task_id:
            raise ValueError("组合工作流需要 task_id 才能暂停/恢复")
        config = thread_config(tenant_id, task_id)

    graph = build_combined_graph(
        provider=provider,
        competitor_provider=competitor_provider,
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        task=task,
        persist=persist,
        resume_from=resume_from,
        listing_note=listing_note,
    )
    return graph.start(payload, config)


__all__ = [
    "DECISION_CANCEL",
    "DECISION_CONTINUE",
    "STEP_LABELS",
    "CombinedGraph",
    "build_combined_graph",
    "run_combined_graph",
]
