"""Listing 子图的状态契约（计划 §6.2 / Phase 3）。

为什么不能再共用裸 dict
======================

Phase 0 盘点 §6.1 指出主图状态是 ``StateGraph(dict)``，键的集合靠约定。
拆子图后这个做法会立刻出问题：

- 子图的输入输出要对外承诺（组合工作流、技能入口、Phase 6 的 checkpoint 都要用）；
- 裸 dict 无法表达"这个键一定存在"，每个节点都得 ``state.get(k) or {}``；
- Phase 6 接 checkpointer 时状态必须可序列化，随手塞 Pydantic 对象会埋雷。

因此这里用 ``TypedDict`` 声明键，并约定**状态里只放 JSON 可序列化的值**
（dict / list / str / int / bool / None）。需要对象时在节点内临时构造，
不往状态里塞。

``total=False`` 是刻意的：节点是逐步填充状态的，不是一次给全。
"""

from __future__ import annotations

from typing import Any, TypedDict

#: 子图结局。与任务状态（``services.tasks``）是两回事：
#: 结局描述"这次生成走到哪一步停的"，任务状态描述"这条任务记录怎么收尾"。
OUTCOME_SUCCEEDED = "succeeded"
OUTCOME_NEEDS_INPUT = "needs_user_input"
OUTCOME_NEEDS_REVIEW = "needs_review"

OUTCOMES = (OUTCOME_SUCCEEDED, OUTCOME_NEEDS_INPUT, OUTCOME_NEEDS_REVIEW)

#: 质量修订的最大次数。1 次是刻意选的：修订要重新过一遍模型（花钱、耗时），
#: 而两轮之后仍不过通常是**资料问题**而不是措辞问题，继续重试只会重复扣费。
DEFAULT_MAX_REVISIONS = 1


class ListingState(TypedDict, total=False):
    """Listing 子图的状态。

    分组看：输入 → 事实/规则/洞察 → 生成与质检 → 结局。
    """

    # -- 输入 --------------------------------------------------------------
    #: ``ListingGenerationInput`` 的 ``model_dump``（已校验）
    request: dict[str, Any]
    #: 竞品报告（可选；只取差异化方向与关键词）
    analysis_report: dict[str, Any] | None
    #: 是否由本子图负责落库。主图调用时为 False——它有自己的 persist 节点，
    #: 两处都写会留下半份数据（Phase 1 已确立"唯一写库点"的约定）。
    persist: bool
    #: 任务 id，落库与幂等判重用
    task_id: str | None

    # -- 事实 / 规则 / 洞察 ------------------------------------------------
    facts: dict[str, Any]
    rules: dict[str, Any]
    insights: dict[str, Any]
    required: dict[str, Any]

    # -- 生成与质检 --------------------------------------------------------
    listing: dict[str, Any]
    quality: dict[str, Any]
    #: 已修订次数
    revision: int
    revision_notes: list[str]

    # -- 结局 --------------------------------------------------------------
    outcome: str
    #: 面向用户的一句话结论（不含内部标识）
    message: str
    artifact: dict[str, Any]


#: 竞品分析的结局。比 Listing 少一个「等补充资料」：
#: 竞品数据是**素材**而不是商品属性，缺了顶多是结论不稳（partial），
#: 不存在"补一条就能继续"的确定性缺口。
OUTCOME_PARTIAL = "partial"

#: 用户在暂停点选择取消。与任务状态 ``cancelled`` 同名，但这里是**工作流**的结局：
#: 图走完了自己的取消分支，不是被外部强杀。
OUTCOME_CANCELLED = "cancelled"


class CompetitorState(TypedDict, total=False):
    """竞品分析子图的状态（计划 §6.1）。

    与 Listing 的关键差别：这里**没有模型修订环节**。分析是确定性统计，
    没有"改措辞"的余地——数据不足只能标 partial 并说明原因，不能靠重试变好。
    """

    # -- 输入 --------------------------------------------------------------
    #: ``CompetitorAnalysisInput`` 的 ``model_dump``（已校验）
    request: dict[str, Any]
    persist: bool
    task_id: str | None

    # -- 取数与归一化 ------------------------------------------------------
    provider: dict[str, Any]
    fetched: dict[str, Any]
    normalized: dict[str, Any]
    sufficiency: dict[str, Any]

    # -- 分析结果 ----------------------------------------------------------
    report: dict[str, Any]
    checks: dict[str, Any]
    summary: dict[str, Any]
    validation: dict[str, Any]

    # -- 结局 --------------------------------------------------------------
    outcome: str
    message: str
    provenance: dict[str, Any]
    artifact: dict[str, Any]


class CombinedState(TypedDict, total=False):
    """组合工作流状态（Phase 5）：竞品分析 + Listing 生成。

    暂停点是 ``confirm_partial`` 节点——它**只做一件事**：``interrupt()`` 并
    把用户的决定放回状态。

    **为什么确认节点不能有副作用**：LangGraph 恢复时会把中断节点**从头重跑一遍**
    （已实测：中断前的节点不重跑，中断节点本身会重跑）。所以"写任务输出""扣额度"
    "发通知"这类动作必须放在 ``prepare_confirmation`` 或恢复之后的节点里，
    否则用户每点一次确认就会多执行一次。
    """

    # -- 输入 --------------------------------------------------------------
    #: 组合请求（商品资料 + 竞品明细），两项子请求由节点自行拆分
    request: dict[str, Any]
    analysis_request: dict[str, Any]
    listing_request: dict[str, Any]
    persist: bool
    task_id: str | None

    # -- 阶段一：竞品分析 --------------------------------------------------
    analysis_outcome: str
    analysis_report: dict[str, Any]
    analysis_summary: dict[str, Any]
    analysis_provenance: dict[str, Any]
    analysis_reasons: list[str]

    # -- 暂停点 ------------------------------------------------------------
    #: 给用户看的待确认载荷（缺什么、影响什么、继续的风险、确认令牌）
    confirmation: dict[str, Any]
    #: 用户决定：continue / cancel
    decision: str

    # -- 阶段二：Listing ---------------------------------------------------
    required: dict[str, Any]
    listing: dict[str, Any]
    listing_review: dict[str, Any]

    # -- 结局 --------------------------------------------------------------
    outcome: str
    #: 建议的任务状态（succeeded / partial / waiting_for_input / cancelled）
    task_status: str
    message: str
    provenance: dict[str, Any]
    artifact: dict[str, Any]


__all__ = [
    "DEFAULT_MAX_REVISIONS",
    "OUTCOMES",
    "OUTCOME_CANCELLED",
    "OUTCOME_NEEDS_INPUT",
    "OUTCOME_NEEDS_REVIEW",
    "OUTCOME_PARTIAL",
    "OUTCOME_SUCCEEDED",
    "CombinedState",
    "CompetitorState",
    "ListingState",
]
