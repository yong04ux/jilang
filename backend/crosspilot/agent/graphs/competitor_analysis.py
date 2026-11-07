"""竞品分析子图。

节点图
======

    validate_input
      -> resolve_data_provider
      -> fetch_competitors        （有限重试，仅对可重试失败）
      -> normalize_data
      -> check_data_sufficiency
      -> analyze_market           （确定性统计，不调模型）
      -> validate_analysis
           ├─ 样本不足 -> build_partial_result  -> [persist_result] -> END
           └─ 样本充足 -> summarize_opportunities -> [persist_result] -> END

与计划字面描述的两处差异（都在这里说明，不藏着）
================================================

**① 没有 `revise_analysis` 节点。**
 画了「retryable_issue -> revise_analysis (bounded)」，前提是
`analyze_market` 会调用模型。这里的分析**不调模型**——
数字必须来自 `engine.analysis` 的确定性计算。既然产出是算出来的，
就没有"改措辞重试"这回事：样本不够只能如实标 partial，重跑一遍还是同样的数字。
**重试只保留在取数环节**（`fetch_competitors`），那是唯一可能"再试一次就好了"的地方。

**② 样本不足时仍然计算，而不是直接跳 partial。**
计划画的是一条旁路 `insufficient -> build_partial_result`。这里改成
"先算完再标 partial"：用 1 个竞品算出来的价格区间仍然有信息量，
直接跳过等于什么都不给用户。partial 的语义是「结论不稳定」，
不是「没有结论」。

`analyze_market` 的 LLM 列在计划表格里写「是」，这里写「否」——以用户决定为准。
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from ...models import CompetitorAnalysisRequest, Platform
from ...services import competitor_facts
from ...services.artifacts import save_run_artifacts
from ...services.tasks import TaskRecorder
from ..contracts import SkillInputInvalid
from ..state import (
    OUTCOME_PARTIAL,
    OUTCOME_SUCCEEDED,
    CompetitorState,
)
from ..steps import StepRunner

#: 取数重试上限。只对"可重试失败"生效，配置类错误一次都不重试。
DEFAULT_FETCH_ATTEMPTS = 2

STEP_LABELS = {
    "validate_input": "校验分析输入",
    "resolve_data_provider": "确定数据来源",
    "fetch_competitors": "获取竞品数据",
    "normalize_data": "归一化与去重",
    "check_data_sufficiency": "检查样本充分性",
    "analyze_market": "计算价格、卖点与评论结论",
    "validate_analysis": "校验分析结果",
    "summarize_opportunities": "归纳市场机会",
    "build_partial_result": "生成部分结果",
    "persist_result": "保存报告",
}


class CompetitorGraph:
    """一次竞品分析子图运行。实例只跑一次。"""

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
        max_fetch_attempts: int = DEFAULT_FETCH_ATTEMPTS,
        resume_from: dict[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.competitor_provider = competitor_provider
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.task = task
        self.persist = persist
        self.max_fetch_attempts = max(1, int(max_fetch_attempts))
        self._steps = StepRunner(task=task, resume_from=resume_from, labels=STEP_LABELS)
        self._graph = self._build()

    # -- 图构建 ------------------------------------------------------------
    def _build(self):
        graph = StateGraph(dict)
        graph.add_node("validate_input", self._node_validate_input)
        graph.add_node("resolve_data_provider", self._node_resolve_provider)
        graph.add_node("fetch_competitors", self._node_fetch)
        graph.add_node("normalize_data", self._node_normalize)
        graph.add_node("check_data_sufficiency", self._node_sufficiency)
        graph.add_node("analyze_market", self._node_analyze)
        graph.add_node("validate_analysis", self._node_validate_analysis)
        graph.add_node("summarize_opportunities", self._node_summarize)
        graph.add_node("build_partial_result", self._node_partial)
        graph.add_node("persist_result", self._node_persist)

        graph.set_entry_point("validate_input")
        graph.add_edge("validate_input", "resolve_data_provider")
        graph.add_edge("resolve_data_provider", "fetch_competitors")
        graph.add_edge("fetch_competitors", "normalize_data")
        graph.add_edge("normalize_data", "check_data_sufficiency")
        graph.add_edge("check_data_sufficiency", "analyze_market")
        graph.add_edge("analyze_market", "validate_analysis")
        graph.add_conditional_edges(
            "validate_analysis",
            self._route_after_validation,
            {"partial": "build_partial_result", "ok": "summarize_opportunities"},
        )
        for source in ("summarize_opportunities", "build_partial_result"):
            graph.add_conditional_edges(
                source,
                self._route_after_finalize,
                {"persist_result": "persist_result", "end": END},
            )
        graph.add_edge("persist_result", END)
        return graph.compile()

    # -- 步骤包装 ----------------------------------------------------------
    def _step(self, name: str, detail: str, fn: Callable[[], Any]) -> Any:
        return self._steps.run(name, detail, fn)

    # -- 路由 --------------------------------------------------------------
    @staticmethod
    def _route_after_validation(state: dict[str, Any]) -> str:
        return "ok" if state["sufficiency"]["sufficient"] else "partial"

    def _route_after_finalize(self, state: dict[str, Any]) -> str:
        return "persist_result" if state.get("persist") else "end"

    # -- 节点 --------------------------------------------------------------
    def _node_validate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            # 延迟导入：definitions 会 import 本模块，模块级导入会成环
            from ..definitions import CompetitorAnalysisInput

            raw = state.get("request") or {}
            try:
                payload = CompetitorAnalysisInput(**raw)
            except ValidationError as exc:
                fields = [
                    {
                        "field": ".".join(str(p) for p in err.get("loc", ())) or None,
                        "message": str(err.get("msg") or ""),
                    }
                    for err in exc.errors()[:8]
                ]
                raise SkillInputInvalid("竞品分析参数不合法", detail={"errors": fields}) from exc
            return payload.model_dump(mode="json")

        state["request"] = self._step("validate_input", "校验商品、站点与竞品明细", body)
        return state

    def _node_resolve_provider(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            provider = self.competitor_provider
            if provider is None:
                return {"mode": "none", "label": "未指定数据来源"}
            return {
                "mode": getattr(provider, "mode", "unknown"),
                "label": getattr(provider, "name", "unknown"),
            }

        state["provider"] = self._step("resolve_data_provider", "确定竞品数据来自哪里", body)
        return state

    def _node_fetch(self, state: dict[str, Any]) -> dict[str, Any]:
        request = state["request"]

        def body() -> dict[str, Any]:
            from ...market.competitor_provider import (
                CompetitorProviderError,
                CompetitorQuery,
                ProviderNotConfigured,
            )

            if self.competitor_provider is None:
                # 没有 Provider 时直接用调用方给的竞品行，来源标 manual
                return {
                    "rows": request.get("competitors") or [],
                    "source": "manual",
                    "is_demo": False,
                    "fetched_at": "",
                    "notes": ["未指定数据来源，使用调用方直接提供的竞品明细"],
                    "attempts": 0,
                }

            query = CompetitorQuery(
                product_name=request.get("product_name") or "",
                platform=str(request.get("platform") or "amazon"),
                marketplace=request.get("marketplace") or "US",
                category=request.get("category"),
                rows=request.get("competitors") or [],
            )
            last: Exception | None = None
            for attempt in range(1, self.max_fetch_attempts + 1):
                try:
                    data = self.competitor_provider.fetch(query)
                    payload = data.as_dict()
                    payload["attempts"] = attempt
                    return payload
                except ProviderNotConfigured:
                    # 配置问题重试没有意义，直接上抛（会被分类成 provider_unavailable）
                    raise
                except CompetitorProviderError as exc:
                    last = exc
                    if attempt >= self.max_fetch_attempts:
                        raise
            raise last or CompetitorProviderError("取数失败")  # pragma: no cover

        state["fetched"] = self._step(
            "fetch_competitors",
            f"{len(request.get('competitors') or [])} 条竞品明细",
            body,
        )
        return state

    def _node_normalize(self, state: dict[str, Any]) -> dict[str, Any]:
        request = state["request"]
        rows = state["fetched"]["rows"]

        def body() -> dict[str, Any]:
            from ...engine.analysis import normalize
            from ...models import CompetitorProduct

            competitors = [CompetitorProduct(**row) for row in rows]
            analysis_request = _build_request(request, competitors)
            data = normalize(analysis_request)
            return {
                "competitors": [c.model_dump(mode="json") for c in data.competitors],
                "reviews": [[name, review.model_dump(mode="json")] for name, review in data.reviews],
                "keywords": [k.model_dump(mode="json") for k in data.keywords],
                "warnings": data.warnings,
            }

        state["normalized"] = self._step("normalize_data", "字段标准化、去重与空值处理", body)
        return state

    def _node_sufficiency(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            summary = competitor_facts.summarize_normalized(state["normalized"])
            verdict = competitor_facts.assess_sufficiency(summary)
            return {**summary, **verdict}

        state["sufficiency"] = self._step(
            "check_data_sufficiency", "竞品数、评论样本与价格覆盖", body
        )
        return state

    def _node_analyze(self, state: dict[str, Any]) -> dict[str, Any]:
        request = state["request"]

        def body() -> dict[str, Any]:
            from ...engine.analysis import run_analysis
            from ...models import CompetitorProduct

            competitors = [CompetitorProduct(**row) for row in state["fetched"]["rows"]]
            analysis_request = _build_request(request, competitors)
            report = run_analysis(
                analysis_request,
                engine=getattr(self.provider, "name", "rule") or "rule",
            )
            return report.model_dump(mode="json")

        state["report"] = self._step(
            "analyze_market", "确定性统计：价格、卖点、评论主题与差异化", body
        )
        return state

    def _node_validate_analysis(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            from .. import skills

            report = state["report"]
            structure = competitor_facts.validate_report(report)
            if not structure["ok"]:
                # 结构残缺是系统问题，不该降级成 partial 糊过去
                raise RuntimeError("分析结果结构不完整：" + "；".join(structure["issues"]))

            from ...models import AnalysisReport

            integrity = skills.check_integrity(AnalysisReport(**report))
            return {
                "structure_ok": True,
                "integrity_ok": integrity["ok"],
                "issues": integrity["issues"],
                "metrics": integrity["metrics"],
            }

        state["checks"] = self._step(
            "validate_analysis", "结构完整性与数据完整性", body
        )
        return state

    def _node_summarize(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            from .. import skills
            from ...models import AnalysisReport

            return skills.market_summary(AnalysisReport(**state["report"]))

        state["summary"] = self._step(
            "summarize_opportunities", "只引用报告已有结论", body
        )
        state["outcome"] = OUTCOME_SUCCEEDED
        state["message"] = "分析完成，样本量足以支撑结论"
        state["provenance"] = self._provenance(state)
        return state

    def _node_partial(self, state: dict[str, Any]) -> dict[str, Any]:
        def body() -> dict[str, Any]:
            from .. import skills
            from ...models import AnalysisReport

            return {
                "summary": skills.market_summary(AnalysisReport(**state["report"])),
                "reasons": state["sufficiency"]["reasons"],
            }

        payload = self._step("build_partial_result", "样本不足，标注结论的适用范围", body)
        state["summary"] = payload["summary"]
        state["outcome"] = OUTCOME_PARTIAL
        state["message"] = (
            "分析已按现有数据完成，但样本不足，结论仅供参考："
            + "；".join(payload["reasons"])
        )
        state["provenance"] = {**self._provenance(state), "partial_reasons": payload["reasons"]}
        return state

    def _node_persist(self, state: dict[str, Any]) -> dict[str, Any]:
        if not self.persist:
            raise RuntimeError("未启用落库时不应进入 persist_result")

        report = state["report"]

        def body() -> dict[str, Any]:
            return save_run_artifacts(
                self.db,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                task_id=state.get("task_id"),
                report=report,
            )

        state["artifact"] = self._step("persist_result", "保存报告与来源信息", body)
        return state

    # -- 来源 --------------------------------------------------------------
    @staticmethod
    def _provenance(state: dict[str, Any]) -> dict[str, Any]:
        """来源标记：数据从哪来、什么时候取的、是不是示例数据。

         要求「保存 Provider、数据时间、Mock 标记和证据引用」。
        Mock 标记在本分支的等价物是 ``is_demo``（没有 ``is_mock`` 这一维，
        不为对齐文档而编一个）。
        """
        fetched = state.get("fetched") or {}
        report = state.get("report") or {}
        data_provenance = report.get("data_provenance") or {}
        provenance: dict[str, Any] = {
            # 两个不同轴的来源，分开命名，别混成 "provider"：
            # data_provider = 数据从哪个来源拿的；provider = 用哪个模型跑的（由调用方补）
            "data_provider": fetched.get("source") or "manual",
            "data_source": data_provenance.get("data_source") or "",
            "fetched_at": fetched.get("fetched_at") or "",
            "competitor_count": data_provenance.get("competitor_count"),
            "review_sample_count": data_provenance.get("review_sample_count"),
        }
        if fetched.get("is_demo") or data_provenance.get("is_demo"):
            provenance["is_demo"] = True
        if fetched.get("notes"):
            provenance["notes"] = list(fetched["notes"])
        if data_provenance.get("fields_missing"):
            provenance["fields_missing"] = list(data_provenance["fields_missing"])
        return provenance

    # -- 入口 --------------------------------------------------------------
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: dict[str, Any] = dict(payload)
        state.setdefault("persist", self.persist)
        return self._graph.invoke(state)


def _build_request(
    payload: dict[str, Any], competitors: list[Any]
) -> CompetitorAnalysisRequest:
    """把已校验的输入还原成 ``CompetitorAnalysisRequest``。

    统计一律交给 ``engine.analysis``，这里只做字段搬运——不在这里加任何计算。
    关键词必须原样带过去：丢了它，报告的"关键词布局"一节会凭空变成"没有数据"。
    """
    from ...models import KeywordMetric

    return CompetitorAnalysisRequest(
        product_name=payload["product_name"],
        platform=Platform(payload.get("platform") or "amazon"),
        marketplace=payload.get("marketplace") or "US",
        category=payload.get("category"),
        own_specs=payload.get("own_specs") or {},
        own_key_features=payload.get("own_key_features") or [],
        own_price=payload.get("own_price"),
        competitors=competitors,
        keywords=[KeywordMetric(**item) for item in (payload.get("keywords") or [])],
        data_source=payload.get("data_source") or "manual",
    )


def run_competitor_graph(
    payload: dict[str, Any],
    *,
    provider: Any,
    competitor_provider: Any = None,
    db: Any = None,
    tenant_id: str = "",
    user_id: str = "",
    task: TaskRecorder | None = None,
    persist: bool = False,
    max_fetch_attempts: int = DEFAULT_FETCH_ATTEMPTS,
    resume_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运行竞品分析子图，返回最终状态。

    ``payload`` 至少包含 ``request``（``CompetitorAnalysisInput`` 的结构）。
    """
    graph = CompetitorGraph(
        provider=provider,
        competitor_provider=competitor_provider,
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        task=task,
        persist=persist,
        max_fetch_attempts=max_fetch_attempts,
        resume_from=resume_from,
    )
    return graph.run(payload)


__all__ = [
    "DEFAULT_FETCH_ATTEMPTS",
    "STEP_LABELS",
    "CompetitorGraph",
    "run_competitor_graph",
]
