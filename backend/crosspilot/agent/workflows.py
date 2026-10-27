"""工作流分派（Phase 5 下：主图收敛）。

主图只剩三件事：``validate → dispatch → finalize``。业务全部在已有的子图里。

为什么 dispatch 是"选图"而不是"图里的一个节点"
==============================================

本来最直观的做法是：主图放三个节点，``dispatch`` 节点里调用对应的子图。
**实测行不通**——把带 ``interrupt`` 的组合子图当节点塞进父图后，恢复时
父图的 ``validate`` 和子图的 ``analyze`` 都会重跑一遍（LangGraph 会从头重放
到中断点），这直接违反「恢复不重复执行竞品分析」，而且真实 Provider 下
等于把分析的费用付两遍。

所以分派发生在**图级**：先决定跑哪张图，再直接跑那张图。
恢复时命中的仍是同一张顶层图，中断节点之外的东西都不重跑（已实测）。

工作流类型
==========

  类型          触发条件              业务
  ------------  --------------------  ------------------------------------
  competitor    with_listing=false    竞品分析（独立路径，行为不变）
  combined      with_listing=true     竞品分析 →（partial 确认）→ Listing

独立 Listing 生成入口（``/api/listings/generate``）**不经过这里**：
它不要求先做竞品分析，语义不同，保持原样。

统一收尾
========

``apply_result`` 是唯一把"工作流结局"翻译成"任务状态"的地方：

- 停在中断点 → **不收尾**（``is_paused`` 先判），任务留给确认接口
- 缺事实 → ``waiting_for_input``（可重试）
- partial → ``partial``（绝不降级成 succeeded）
- 取消 → ``cancelled``
- 其余 → ``succeeded``
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .graphs.combined_operations import (
    DECISION_CANCEL,
    DECISION_CONTINUE,
    run_combined_graph,
)
from .graphs.competitor_analysis import run_competitor_graph
from .state import (
    OUTCOME_CANCELLED,
    OUTCOME_NEEDS_INPUT,
    OUTCOME_PARTIAL,
)
from .steps import StepRunner

KIND_COMPETITOR = "competitor"
KIND_COMBINED = "combined"
#: 只生成 Listing（``listing_only=true``）：不要求竞品，直接跑 Listing 子图。
#: 这是 main 分支既有的入口语义，合并后必须保留——用户可能只想写文案。
KIND_LISTING = "listing"

#: 工作流版本。**节点结构或语义变化时必须改**，否则重试会把旧版本的中间结果
#: 当成新版本的可复用产物（典型症状：某个节点被拆成两个，旧输出被错配到新节点）。
#: 格式：日期 + 序号，便于人工看出版本先后。
WORKFLOW_VERSION = "2026-10-27.2"

#: 参与输入指纹的字段。**改动这里等于改"什么算同一次输入"**，
#: 所以要和工作流版本一起升级。故意排除：
#: ``goal``（自然语言，同义改写不该导致重算）、``conversation_id``、
#: ``async_run``（执行方式不影响结果）、``degraded``（只影响标注）。
_FINGERPRINT_FIELDS = (
    "product_name",
    "platform",
    "marketplace",
    "brand",
    "category",
    "own_specs",
    "own_key_features",
    "certifications",
    "own_price",
    "target_audience",
    "banned_terms",
    "competitors",
    "keywords",
    "data_source",
    "listing_language",
    "with_listing",
)

#: 主图自己的三个阶段（会出现在任务时间线里，与工作流内部步骤区分开）
MAIN_STEPS = ("validate", "dispatch", "finalize")

MAIN_STEP_LABELS = {
    "validate": "校验任务输入",
    "dispatch": "分派工作流",
    "finalize": "收尾并落任务状态",
}


@dataclass(frozen=True)
class WorkflowSpec:
    """一种工作流的契约：类型、面向用户的名称、步骤骨架、模型依赖、超时。"""

    kind: str
    label: str
    step_names: tuple[str, ...]
    needs_llm: bool
    #: 整条工作流的超时（秒）。在节点边界检查，不另起线程去杀。
    #: 值按"最慢的合法路径"给：组合流程可能跑两轮模型。
    timeout_seconds: float = 180.0

    def plan(self) -> list[str]:
        """任务计划骨架：主图三阶段 + 工作流内部步骤。

        计划按**最坏路径**给（含 ``confirm_partial``）：真实步骤以
        ``task_steps`` 为准，计划只用于任务刚提交时的骨架占位。
        """
        return ["validate", "dispatch", *self.step_names, "finalize"]


_COMPETITOR = WorkflowSpec(
    kind=KIND_COMPETITOR,
    label="竞品分析",
    step_names=(
        "validate_input",
        "resolve_data_provider",
        "fetch_competitors",
        "normalize_data",
        "check_data_sufficiency",
        "analyze_market",
        "validate_analysis",
        "summarize_opportunities",
        "persist_result",
    ),
    needs_llm=False,
    timeout_seconds=120.0,
)

_COMBINED = WorkflowSpec(
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
    timeout_seconds=240.0,
)

_LISTING = WorkflowSpec(
    kind=KIND_LISTING,
    label="Listing 生成",
    step_names=(
        "validate_input",
        "resolve_product_facts",
        "load_brand_rules",
        "load_market_insights",
        "check_required_facts",
        "generate_listing",
        "validate_listing",
        "persist_draft",
    ),
    needs_llm=True,
    timeout_seconds=180.0,
)


def fingerprint(payload: dict[str, Any]) -> str:
    """输入指纹：把"这次请求到底喂了什么"压成短哈希。

    用途是**防止拿旧答案回答新问题**：重试时如果输入变了，
    ``resume_from`` 里那些中间结果就属于另一次请求，不能复用。

    只取工作流关心的字段（见 ``_FINGERPRINT_FIELDS``），
    自然语言目标、会话 id 这些不影响结论的东西故意排除——
    否则用户把同一句话换个说法重试就白白重算一遍。
    """
    material = {name: payload.get(name) for name in _FINGERPRINT_FIELDS}
    encoded = json.dumps(
        material, sort_keys=True, ensure_ascii=False, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def can_reuse(
    *,
    stored_fingerprint: str | None,
    stored_version: str | None,
    payload: dict[str, Any],
) -> tuple[bool, str]:
    """这次重试能不能复用上次的中间结果。返回 ``(能否复用, 原因)``。

    宁可重算也不复用的情况：历史任务没有记录指纹/版本。
    重算的代价是多花一次模型调用；错误复用的代价是用户拿到一份
    "看起来是针对这次请求、实际基于另一次输入"的结论——后者更贵。
    """
    if not stored_fingerprint or not stored_version:
        return False, "上次运行未记录输入指纹或工作流版本，不复用中间结果"
    if stored_version != WORKFLOW_VERSION:
        return False, (
            f"工作流版本已从 {stored_version} 变更为 {WORKFLOW_VERSION}，不复用中间结果"
        )
    if stored_fingerprint != fingerprint(payload):
        return False, "输入内容与上次运行不同，不复用中间结果"
    return True, ""


def choose(payload: dict[str, Any]) -> WorkflowSpec:
    """按请求选工作流。**唯一的分派判据**，不要在别处再写一份。

    判据按优先级：

    1. ``listing_only`` → 只写文案（不需要竞品）；
    2. ``with_listing`` → 竞品分析 + Listing；
    3. 其余 → 只做竞品分析。

    用 ``with_listing`` 而不是 ``agent_key`` 做判据：它本来就是"要不要写文案"
    的开关，恰好等于"走不走组合流程"。用 agent_key 会把分派逻辑分散到两处。
    """
    if payload.get("listing_only"):
        return _LISTING
    return _COMBINED if bool(payload.get("with_listing")) else _COMPETITOR


def spec_for(kind: str) -> WorkflowSpec:
    if kind == KIND_COMBINED:
        return _COMBINED
    if kind == KIND_LISTING:
        return _LISTING
    return _COMPETITOR


def is_paused(state: dict[str, Any]) -> bool:
    """图是否停在中断点。暂停时节点还没返回，所以看 ``__interrupt__``。"""
    return bool(state.get("__interrupt__"))


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------


def _analysis_request(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_name": payload.get("product_name"),
        "platform": payload.get("platform") or "amazon",
        "marketplace": payload.get("marketplace") or "US",
        "category": payload.get("category"),
        "own_specs": payload.get("own_specs") or {},
        "own_key_features": payload.get("own_key_features") or [],
        "own_price": payload.get("own_price"),
        "competitors": payload.get("competitors") or [],
        "keywords": payload.get("keywords") or [],
        "data_source": payload.get("data_source") or "manual",
    }


def _listing_request(payload: dict[str, Any]) -> dict[str, Any]:
    """把 Agent 请求摊成 Listing 子图要的结构。

    与组合图里 ``validate_request`` 的映射保持一致：两处都从同一个扁平请求出发，
    只是组合图还要顺带构造分析侧的入参。
    """
    return {
        "product": {
            "name": payload.get("product_name"),
            "brand": payload.get("brand"),
            "target_platform": payload.get("platform") or "amazon",
            "marketplace": payload.get("marketplace") or "US",
            "specifications": payload.get("own_specs") or {},
            "key_features": payload.get("own_key_features") or [],
            "certifications": payload.get("certifications") or [],
            "price": payload.get("own_price"),
            "target_audience": payload.get("target_audience"),
            "banned_terms": payload.get("banned_terms") or [],
        },
        "language": payload.get("listing_language") or "en-US",
        "marketplace": payload.get("marketplace") or "US",
        "data_source": payload.get("data_source") or "manual",
    }


def run(
    spec: WorkflowSpec,
    payload: dict[str, Any],
    *,
    db: Any,
    tenant_id: str,
    user_id: str,
    task_id: str,
    provider: Any,
    competitor_provider: Any = None,
    task: Any = None,
    resume_from: dict[str, Any] | None = None,
    listing_note: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    """执行选定的工作流，返回图状态（可能停在中断点）。

    ``persist=False`` 用于评估/试跑：不写业务表，也就不需要数据库。
    """
    # 降级标记随状态一起传进去：任务输出里要保留"目标是用规则解析的"这一事实
    extra = {
        "degraded": bool(payload.get("degraded")),
        "degraded_reason": payload.get("degraded_reason") or "",
    }
    if spec.kind == KIND_COMBINED:
        return run_combined_graph(
            {
                "request": payload,
                "persist": persist,
                "task_id": task_id,
                **extra,
            },
            provider=provider,
            competitor_provider=competitor_provider,
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            task=task,
            persist=persist,
            resume_from=resume_from,
            listing_note=listing_note,
            config=thread_config(tenant_id, task_id),
        )

    if spec.kind == KIND_LISTING:
        # 只写文案：不碰竞品数据，也不需要 checkpointer（没有中断点）
        from .graphs.listing_generation import run_listing_graph

        return run_listing_graph(
            {
                "request": _listing_request(payload),
                "persist": persist,
                "task_id": task_id,
                **extra,
            },
            provider=provider,
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            task=task,
            persist=persist,
            resume_from=resume_from,
        )

    return run_competitor_graph(
        {
            "request": _analysis_request(payload),
            "persist": persist,
            "task_id": task_id,
            **extra,
        },
        provider=provider,
        competitor_provider=competitor_provider,
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        task=task,
        persist=persist,
        resume_from=resume_from,
    )


def thread_config(tenant_id: str, task_id: str) -> dict[str, Any]:
    """组合工作流需要按线程存取 checkpoint；竞品路径虽然用不上，
    统一传进去可以让两条路径的调用形态一致。"""
    from .checkpoint import thread_config as _thread_config

    return _thread_config(tenant_id, task_id)


# ---------------------------------------------------------------------------
# 统一收尾
# ---------------------------------------------------------------------------


def pending_payload(state: dict[str, Any]) -> dict[str, Any]:
    """暂停时写给用户看的待确认内容。"""
    confirmation = state.get("confirmation") or {}
    return {
        "kind": confirmation.get("kind") or "partial_analysis_confirmation",
        "question": confirmation.get("question") or "是否继续？",
        "reasons": confirmation.get("reasons") or [],
        "affected_conclusions": confirmation.get("affected_conclusions") or [],
        "risks": confirmation.get("risks") or [],
        "metrics": confirmation.get("metrics") or {},
        "confirmation_token": confirmation.get("confirmation_token") or "",
        "options": confirmation.get("options") or [DECISION_CONTINUE, DECISION_CANCEL],
    }


def result_output(state: dict[str, Any], spec: WorkflowSpec | None = None) -> dict[str, Any]:
    """把图状态压成任务输出（对外展示用）。

    两条路径的键保持同一套：报告来自 ``analysis_report``（组合）或
    ``report``（竞品独立），Listing 来自 ``listing``。
    """
    artifact = state.get("artifact") or {}
    listing = state.get("listing") or {}
    report = state.get("analysis_report") or state.get("report")
    return {
        "plan": (spec.plan() if spec else []),
        "workflow": (spec.kind if spec else ""),
        "analysis_outcome": state.get("analysis_outcome")
        or ("partial" if state.get("outcome") == OUTCOME_PARTIAL else None),
        "message": state.get("message") or "",
        "summary": state.get("analysis_summary") or state.get("summary"),
        "checks": state.get("checks"),
        "quality": (listing.get("quality_check") if listing else None)
        or state.get("quality"),
        "report_id": artifact.get("report_id") or (report or {}).get("report_id"),
        "listing_id": artifact.get("listing_id") or listing.get("listing_id"),
        "provenance": state.get("provenance") or state.get("analysis_provenance") or {},
        "decision": state.get("decision") or "",
        # 目标解析降级的标记必须留在任务输出里（界面要显示"用规则解析的目标"）
        "degraded": bool(state.get("degraded")),
        "degraded_reason": state.get("degraded_reason") or "",
    }


def response_payload(
    state: dict[str, Any], spec: WorkflowSpec | None = None
) -> dict[str, Any]:
    """给 ``/api/agent/runs`` 的响应块（**保持旧字段名不变**）。

    旧契约里 ``report`` / ``listing`` / ``summary`` 是完整对象，不是引用；
    换了编排之后这两条路径的状态键不同（``report`` vs ``analysis_report``），
    所以在这里做一次映射，而不是让每个端点各写一遍。
    """
    listing = state.get("listing") or {}
    return {
        "plan": spec.plan() if spec else [],
        "report": state.get("analysis_report") or state.get("report"),
        "listing": listing or None,
        "summary": state.get("analysis_summary") or state.get("summary"),
        "checks": state.get("checks"),
        "quality": (listing.get("quality_check") if listing else None)
        or state.get("quality"),
    }


def apply_result(
    recorder: Any,
    state: dict[str, Any],
    db: Any = None,
    *,
    spec: WorkflowSpec | None = None,
) -> str:
    """把工作流结局落到任务记录上，返回任务状态。

    **暂停状态绝不在这里收尾**：调用方必须先判 ``is_paused``。
    这条不是防御性代码——一旦在这里把暂停的任务标成 succeeded，
    用户点确认时就会发现任务已经"完成"，工作流却还在等。
    """
    status = state.get("task_status")
    output = result_output(state, spec)
    artifact = state.get("artifact") or {}
    listing = state.get("listing") or {}
    result_ref = (
        artifact.get("report_id")
        or artifact.get("listing_id")
        or listing.get("listing_id")
        or (state.get("report") or {}).get("report_id")
    )

    if state.get("outcome") == OUTCOME_CANCELLED or status == "cancelled":
        recorder.cancel(reason=state.get("message") or "用户取消")
        final_status = "cancelled"
    elif state.get("outcome") == OUTCOME_NEEDS_INPUT or status == "waiting_for_input":
        recorder.await_input(
            output={**output, "missing": (artifact or {}).get("missing") or []}
        )
        final_status = "waiting_for_input"
    elif state.get("outcome") == OUTCOME_PARTIAL or status == "partial":
        recorder.partial(result_ref=result_ref, output=output)
        final_status = "partial"
    else:
        recorder.succeed(result_ref=result_ref, output=output)
        final_status = "succeeded"

    # 任务进终态后 checkpoint 就是死数据，顺手清掉（尽力而为，失败不影响收尾）。
    # 注意：暂停（waiting_for_review）**不会**走到这里，那条路在 runtime 里提前返回。
    _cleanup_checkpoint(recorder)
    return final_status


def _cleanup_checkpoint(recorder: Any) -> None:
    tenant_id = getattr(recorder, "tenant_id", "") or ""
    task_id = getattr(recorder, "task_id", "") or ""
    if not tenant_id or not task_id:
        return
    try:
        from .checkpoint import cleanup_thread

        cleanup_thread(tenant_id, task_id)
    except Exception:  # noqa: BLE001 - 清理失败不改写任务结果
        pass


def step_runner(
    task: Any,
    resume_from: dict[str, Any] | None,
    cancel_check: Any = None,
) -> StepRunner:
    """主图自己的三阶段也走同一套步骤记录（含取消检查与断点复用）。"""
    return StepRunner(
        task=task,
        resume_from=resume_from,
        labels=MAIN_STEP_LABELS,
        cancel_check=cancel_check,
    )


__all__ = [
    "KIND_COMBINED",
    "KIND_COMPETITOR",
    "MAIN_STEPS",
    "MAIN_STEP_LABELS",
    "WORKFLOW_VERSION",
    "WorkflowSpec",
    "apply_result",
    "can_reuse",
    "choose",
    "fingerprint",
    "is_paused",
    "pending_payload",
    "response_payload",
    "result_output",
    "run",
    "spec_for",
    "step_runner",
    "thread_config",
]
