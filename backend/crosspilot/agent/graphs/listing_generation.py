"""Listing 生成子图（计划 §6.2 / Phase 3）。

节点图
======

    validate_input
      -> resolve_product_facts
      -> load_brand_rules
      -> load_market_insights (可选)
      -> check_required_facts
           ├─ 没有可引用的事实 -> needs_user_input -> END
           └─ 可以写           -> generate_listing
      -> validate_listing
           ├─ 通过             -> persist_draft（仅独立运行时）-> END
           ├─ 不通过且还有修订次数 -> revise_listing -> validate_listing
           └─ 不通过且用完     -> needs_review -> END

三条刻意的设计
==============

**① 落库是可选的。**
被主图调用时 ``persist=False``：主图有自己的 ``persist`` 节点，是唯一写库点
（Phase 1 已确立）。两处都写会在失败时留下半份数据。

**② 修订 = 带着问题清单重新生成，不是增量修补。**
实现方式是给 ``ListingGenerationRequest.revision_notes`` 填上一版的具体问题，
走同一条 ``provider.generate`` 路径。这样产出结构与首次生成完全一致，
下游质检不用改；代价是要重算一遍（明确记录在 ``limitations`` 里）。
没有可用模型时（规则引擎）**不做修订**——没有模型就没有"改措辞"这回事，
直接进 ``needs_review``，不假装修过。

**③ 缺事实的判定保守。**
只有"一条属性事实和一条卖点事实都没有"时才阻塞。部分必填项缺失不阻塞：
它会进 ``pending_confirmations``，让人看到"这里没写"，而不是把任务停掉。

步骤记录
========
``task`` 传入时每个节点各落一条 ``task_steps``（独立运行、需要时间线时用）。
被主图调用时传 ``None``：主图会把整个子图合并成一条 ``listing`` 步骤，
断点续跑按 ``node="listing"`` 复用，语义不变。
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from ...models import ListingDraft, ListingGenerationRequest, OwnProduct
from ...services import listing_facts
from ...services.artifacts import save_run_artifacts
from ...services.tasks import TaskRecorder
from ..contracts import SkillContext, SkillInputInvalid
from ..state import (
    DEFAULT_MAX_REVISIONS,
    OUTCOME_NEEDS_INPUT,
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_SUCCEEDED,
    ListingState,
)
from ..steps import StepRunner

#: 节点名 → 面向用户的步骤名
STEP_LABELS = {
    "validate_input": "校验 Listing 输入",
    "resolve_product_facts": "整理商品事实",
    "load_brand_rules": "加载品牌与站点规则",
    "load_market_insights": "读取竞品洞察",
    "check_required_facts": "检查关键事实",
    "needs_user_input": "等待补充商品资料",
    "generate_listing": "生成 Listing 草稿",
    "validate_listing": "质检草稿",
    "revise_listing": "按质检问题修订",
    "persist_draft": "保存草稿",
    "needs_review": "等待人工复核",
}


class RevisionUnavailable(RuntimeError):
    """没有可用模型，无法修订。内部使用：由路由决定进 needs_review。"""


class MissingProductFacts(RuntimeError):
    """商品资料里没有可引用的事实，不能在不编造的前提下生成。

    子图遇到这种情况会停在 ``needs_user_input``。调用方（主图 / 技能入口）
    应当把它翻译成"等待补充资料"，而**不是**失败——任务跑到这一步本身是成功的，
    缺的是用户输入。
    """

    def __init__(self, message: str, *, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing = list(missing or [])


class ListingGraph:
    """一次 Listing 子图运行。实例只跑一次。"""

    def __init__(
        self,
        *,
        provider: Any,
        db: Any = None,
        tenant_id: str = "",
        user_id: str = "",
        task: TaskRecorder | None = None,
        persist: bool = False,
        max_revisions: int = DEFAULT_MAX_REVISIONS,
        resume_from: dict[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.task = task
        self.persist = persist
        self.max_revisions = max(0, int(max_revisions))
        self._steps = StepRunner(task=task, resume_from=resume_from, labels=STEP_LABELS)
        self._graph = self._build()

    # -- 图构建 ------------------------------------------------------------
    def _build(self):
        graph = StateGraph(dict)
        graph.add_node("validate_input", self._node_validate_input)
        graph.add_node("resolve_product_facts", self._node_resolve_facts)
        graph.add_node("load_brand_rules", self._node_load_rules)
        graph.add_node("load_market_insights", self._node_load_insights)
        graph.add_node("check_required_facts", self._node_check_required)
        graph.add_node("needs_user_input", self._node_needs_input)
        graph.add_node("generate_listing", self._node_generate)
        graph.add_node("validate_listing", self._node_validate_listing)
        graph.add_node("revise_listing", self._node_revise)
        graph.add_node("persist_draft", self._node_persist)
        graph.add_node("needs_review", self._node_needs_review)

        graph.set_entry_point("validate_input")
        graph.add_edge("validate_input", "resolve_product_facts")
        graph.add_edge("resolve_product_facts", "load_brand_rules")
        graph.add_edge("load_brand_rules", "load_market_insights")
        graph.add_edge("load_market_insights", "check_required_facts")
        graph.add_conditional_edges(
            "check_required_facts",
            self._route_after_facts,
            {"needs_user_input": "needs_user_input", "generate_listing": "generate_listing"},
        )
        graph.add_edge("generate_listing", "validate_listing")
        graph.add_conditional_edges(
            "validate_listing",
            self._route_after_quality,
            {
                "persist_draft": "persist_draft",
                "revise_listing": "revise_listing",
                "needs_review": "needs_review",
                "end": END,
            },
        )
        graph.add_edge("revise_listing", "generate_listing")
        graph.add_edge("persist_draft", END)
        graph.add_edge("needs_user_input", END)
        graph.add_edge("needs_review", END)
        return graph.compile()

    # -- 步骤包装 ----------------------------------------------------------
    def _step(self, name: str, detail: str, fn: Callable[[], Any]) -> Any:
        """记录步骤 / 复用断点。**不在这里做取消检查**：

        被主图调用时主图已在节点边界查过；独立运行时由 dispatcher 的超时与
        任务状态负责。重复检查会让"取消"的语义分叉。
        """
        return self._steps.run(name, detail, fn)

    # -- 路由 --------------------------------------------------------------
    @staticmethod
    def _route_after_facts(state: dict[str, Any]) -> str:
        return "generate_listing" if state["required"]["can_generate"] else "needs_user_input"

    def _route_after_quality(self, state: dict[str, Any]) -> str:
        if state["quality"].get("passed"):
            return "persist_draft" if state.get("persist") else "end"
        if int(state.get("revision") or 0) < self.max_revisions and self._can_revise():
            return "revise_listing"
        return "needs_review"

    def _can_revise(self) -> bool:
        """修订要真的改措辞，所以必须有可调用模型（规则引擎不算）。"""
        return SkillContext(provider=self.provider).has_llm()

    # -- 节点 --------------------------------------------------------------
    def _node_validate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            # 延迟导入：definitions 会 import 本模块（技能入口要跑子图），
            # 模块级导入会形成循环。契约本身没变，只是取用时机后移。
            from ..definitions import ListingGenerationInput

            raw = state.get("request") or {}
            try:
                payload = ListingGenerationInput(**raw)
            except ValidationError as exc:
                fields = [
                    {
                        "field": ".".join(str(p) for p in err.get("loc", ())) or None,
                        "message": str(err.get("msg") or ""),
                    }
                    for err in exc.errors()[:8]
                ]
                raise SkillInputInvalid("Listing 参数不合法", detail={"errors": fields}) from exc
            return payload.model_dump(mode="json")

        state["request"] = self._step(
            "validate_input", "校验站点、语言与商品资料", body
        )
        return state

    def _node_resolve_facts(self, state: dict[str, Any]) -> dict[str, Any]:
        product = state["request"]["product"]
        state["facts"] = self._step(
            "resolve_product_facts",
            "把商品资料抽成带 ID 的事实台账",
            lambda: listing_facts.resolve_product_facts(product),
        )
        return state

    def _node_load_rules(self, state: dict[str, Any]) -> dict[str, Any]:
        request = state["request"]
        product = request["product"]
        state["rules"] = self._step(
            "load_brand_rules",
            "站点长度上限与禁用词",
            lambda: listing_facts.load_brand_rules(
                request.get("marketplace") or "US",
                list(product.get("banned_terms") or []),
            ),
        )
        return state

    def _node_load_insights(self, state: dict[str, Any]) -> dict[str, Any]:
        report = state.get("analysis_report")
        state["insights"] = self._step(
            "load_market_insights",
            "取差异化方向" if report else "没有竞品报告，跳过",
            lambda: listing_facts.load_market_insights(report),
        )
        return state

    def _node_check_required(self, state: dict[str, Any]) -> dict[str, Any]:
        state["required"] = self._step(
            "check_required_facts",
            "判断是否有可引用的事实",
            lambda: listing_facts.check_required_facts(state["facts"]),
        )
        return state

    def _node_needs_input(self, state: dict[str, Any]) -> dict[str, Any]:
        required = state["required"]

        def body() -> dict[str, Any]:
            return {
                "missing": required["missing"],
                "missing_labels": required["missing_labels"],
            }

        payload = self._step("needs_user_input", "缺少可引用的事实，停止生成", body)
        state["outcome"] = OUTCOME_NEEDS_INPUT
        state["message"] = (
            required["reason"] + "。请补充商品规格或卖点后重试。"
            if required["reason"]
            else "缺少商品资料，请补充后重试。"
        )
        state["artifact"] = payload
        return state

    def _node_generate(self, state: dict[str, Any]) -> dict[str, Any]:
        request_payload = state["request"]
        notes = list(state.get("revision_notes") or [])
        attempt = int(state.get("revision") or 0) + 1

        def body() -> dict[str, Any]:
            request = ListingGenerationRequest(
                product=OwnProduct(**request_payload["product"]),
                language=request_payload.get("language") or "en-US",
                marketplace=request_payload.get("marketplace") or "US",
                analysis_report=state.get("analysis_report"),
                data_source=request_payload.get("data_source") or "manual",
                revision_notes=notes,
            )
            draft = self.provider.generate(request, state.get("analysis_report"))
            payload = draft.model_dump(mode="json")
            # 商品事实快照：供后续版本复检（不参与对外展示）
            payload["product_snapshot"] = request.product.model_dump(mode="json")
            return payload

        detail = "基于事实台账生成文案"
        if notes:
            detail = f"{detail}（第 {attempt} 次，带 {len(notes)} 条质检问题）"
        state["listing"] = self._step("generate_listing", detail, body)
        return state

    def _node_validate_listing(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            draft = ListingDraft(**state["listing"])
            quality = draft.quality_check
            notes = [
                issue.message
                for issue in quality.issues
                if issue.severity.value == "error"
            ] or [
                issue.message
                for issue in quality.issues
                if issue.severity.value == "warning"
            ]
            return {
                "passed": quality.passed,
                "issue_count": len(quality.issues),
                "error_count": sum(
                    1 for i in quality.issues if i.severity.value == "error"
                ),
                "notes": notes[:8],
                "engine": draft.engine,
            }

        state["quality"] = self._step("validate_listing", "读取草稿自带的质检结果", body)
        return state

    def _node_revise(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            return {
                "revision": int(state.get("revision") or 0) + 1,
                "notes": list(state["quality"].get("notes") or []),
            }

        detail = f"带着 {state['quality'].get('error_count', 0)} 个错误重新生成"
        revised = self._step("revise_listing", detail, body)
        state["revision"] = revised["revision"]
        state["revision_notes"] = revised["notes"]
        return state

    def _node_needs_review(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            return {
                "notes": state["quality"].get("notes") or [],
                "revisions": int(state.get("revision") or 0),
                "revised": bool(state.get("revision")),
            }

        payload = self._step("needs_review", "质检未通过，交由人工复核", body)
        state["outcome"] = OUTCOME_NEEDS_REVIEW
        if payload["revisions"]:
            state["message"] = (
                f"已修订 {payload['revisions']} 次仍未通过质检，请人工复核后修改。"
            )
        elif not self._can_revise():
            state["message"] = "质检未通过，且当前没有可用模型可以自动修订，请人工复核。"
        else:
            state["message"] = "质检未通过，请人工复核后修改。"
        state["artifact"] = payload
        return state

    def _node_persist(self, state: dict[str, Any]) -> dict[str, Any]:
        if not self.persist:
            # 防御：路由不该把非持久化模式导到这里
            raise RuntimeError("未启用落库时不应进入 persist_draft")

        listing = dict(state["listing"])
        task_id = state.get("task_id")

        def body() -> dict[str, Any]:
            # 幂等（同一任务复用原草稿 id）统一在 services/artifacts.py 里做，
            # 这里不要再写第二份判断——否则换调用方就会漏。
            return save_run_artifacts(
                self.db,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                task_id=task_id,
                listing=listing,
            )

        saved = self._step("persist_draft", "保存草稿", body)
        state["listing"] = listing
        state["artifact"] = saved
        state["outcome"] = OUTCOME_SUCCEEDED
        state["message"] = "草稿已生成并通过质检"
        return state

    # -- 入口 --------------------------------------------------------------
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: dict[str, Any] = dict(payload)
        state.setdefault("persist", self.persist)
        state.setdefault("revision", 0)
        final = self._graph.invoke(state)
        # 通过质检但不需要落库时，没有节点负责收尾：在这里补齐结局
        if not final.get("outcome"):
            final["outcome"] = OUTCOME_SUCCEEDED
            final["message"] = "草稿已生成并通过质检"
        return final


def run_listing_graph(
    payload: dict[str, Any],
    *,
    provider: Any,
    db: Any = None,
    tenant_id: str = "",
    user_id: str = "",
    task: TaskRecorder | None = None,
    persist: bool = False,
    max_revisions: int = DEFAULT_MAX_REVISIONS,
    resume_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运行 Listing 子图，返回最终状态。

    ``payload`` 至少包含 ``request``（``ListingGenerationInput`` 的结构），
    可选 ``analysis_report`` / ``task_id`` / ``persist``。
    """
    graph = ListingGraph(
        provider=provider,
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        task=task,
        persist=persist,
        max_revisions=max_revisions,
        resume_from=resume_from,
    )
    return graph.run(payload)


__all__ = [
    "STEP_LABELS",
    "ListingGraph",
    "MissingProductFacts",
    "RevisionUnavailable",
    "run_listing_graph",
]
