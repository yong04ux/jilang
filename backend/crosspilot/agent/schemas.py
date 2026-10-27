"""Agent 运行的请求/响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import CompetitorProduct, KeywordMetric, Platform


class AgentRunRequest(BaseModel):
    """一次 Agent 运行的输入。

    两种入口：

    1. **结构化参数**（``product_name`` + ``competitors``）：与 ``/api/analyze``
       一致，工作台的"参数确认"与脚本都走这条；
    2. **自然语言目标**（``goal``）：由 planner 解析成结构化参数，缺少竞品数据时
       返回 422 并说明缺什么——不会凭空生成竞品。

    两种入口执行**同一张图**，因此结果结构完全一致。
    """

    model_config = ConfigDict(extra="forbid")

    agent_key: str = Field(default="main", description="要运行的 Agent")
    goal: str | None = Field(default=None, max_length=2000, description="自然语言目标")
    product_name: str | None = Field(default=None, max_length=200)
    platform: Platform = Platform.AMAZON
    marketplace: str = "US"
    category: str | None = None
    brand: str | None = None
    own_specs: dict[str, str] = Field(default_factory=dict)
    own_key_features: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    own_price: float | None = Field(default=None, ge=0)
    target_audience: str | None = None
    banned_terms: list[str] = Field(default_factory=list)
    competitors: list[CompetitorProduct] = Field(default_factory=list)
    import_batch_id: str | None = Field(
        default=None, description="从数据资产读取竞品；与 competitors 二选一"
    )
    keywords: list[KeywordMetric] = Field(default_factory=list)
    with_listing: bool = True
    listing_language: str = "en-US"
    data_source: str = "manual"
    conversation_id: str | None = Field(default=None, description="关联会话；为空则自动新建")
    async_run: bool = Field(
        default=False,
        description="true 时立即返回 task_id，由异步执行器运行；工作台使用此模式",
    )

    @model_validator(mode="after")
    def _require_goal_or_product(self) -> "AgentRunRequest":
        if not (self.goal or "").strip() and not (self.product_name or "").strip():
            raise ValueError("必须提供 goal 或 product_name")
        return self


class GoalResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=2000)


class GoalResolveResponse(BaseModel):
    spec: dict[str, Any]
    degraded: bool = False
    reason: str = ""
    missing: list[str] = Field(default_factory=list)


class AgentRunResponse(BaseModel):
    task_id: str
    status: str
    plan: list[str] = Field(default_factory=list)
    report: dict[str, Any] | None = None
    listing: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    checks: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    conversation_id: str | None = None
    degraded: bool = False
    degraded_reason: str = ""
    #: 组合工作流暂停时的待确认内容（Phase 5）。非暂停时为 None。
    pending: dict[str, Any] | None = None


class TaskResult(BaseModel):
    """任务详情里附带的结果块（异步执行后前端据此渲染）。"""

    plan: list[str] = Field(default_factory=list)
    report: dict[str, Any] | None = None
    listing: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    checks: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    degraded: bool = False
    degraded_reason: str = ""


class CombinedRunRequest(BaseModel):
    """组合工作流请求（Phase 5）：竞品分析 → （partial 时确认）→ Listing。

    与 ``AgentRunRequest`` 的区别：这里**只服务组合工作流**，不接自然语言目标，
    也不接受 ``agent_key``。字段与 ``AgentRunRequest`` 的同名项语义一致。
    """

    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(min_length=1, max_length=200)
    platform: Platform = Platform.AMAZON
    marketplace: str = Field(default="US", max_length=16)
    brand: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    own_specs: dict[str, str] = Field(default_factory=dict)
    own_key_features: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    own_price: float | None = Field(default=None, ge=0)
    target_audience: str | None = None
    banned_terms: list[str] = Field(default_factory=list)
    competitors: list[CompetitorProduct] = Field(min_length=1)
    keywords: list[KeywordMetric] = Field(default_factory=list)
    listing_language: str = "en-US"
    data_source: str = "manual"


class CombinedRunResponse(BaseModel):
    task_id: str
    status: str
    plan: list[str] = Field(default_factory=list)
    #: 暂停时有值：缺什么、影响哪些结论、继续的风险、确认令牌
    pending: dict[str, Any] | None = None
    analysis_outcome: str | None = None
    message: str = ""


#: 重试时允许覆盖的字段。刻意**不含** ``product_name``：
#: 换商品就是另一个业务请求，应该新建任务，而不是在老任务上改题。
RETRY_OVERRIDABLE_FIELDS = frozenset(
    {
        "marketplace",
        "listing_language",
        "own_specs",
        "own_key_features",
        "certifications",
        "own_price",
        "target_audience",
        "banned_terms",
        "competitors",
        "keywords",
    }
)


class RetryRequest(BaseModel):
    """重试时补充/修改输入（可选）。

    存在的理由：``waiting_for_input`` 的任务本来就是"缺资料、补完再来"。
    如果只能原样重试，用户补了规格也得重新发起一次任务，
    既丢掉任务历史，也要重新填一遍其它参数。

    只允许改「资料类」字段（见 ``RETRY_OVERRIDABLE_FIELDS``）；
    改了之后输入指纹会变，重试**不会**复用上次的中间结果——
    这正是要的：资料变了，旧结论就不作数。
    """

    model_config = ConfigDict(extra="forbid")

    overrides: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_fields(self) -> "RetryRequest":
        unknown = sorted(set(self.overrides) - RETRY_OVERRIDABLE_FIELDS)
        if unknown:
            raise ValueError(
                "以下字段不允许在重试时覆盖：" + "、".join(unknown)
            )
        return self


class ConfirmRequest(BaseModel):
    """暂停点的用户确认。

    ``confirmation_token`` 必填：它把"确认的是哪一次暂停"绑定住，
    避免界面拿着过期的缺失清单去确认另一次暂停。
    """

    model_config = ConfigDict(extra="forbid")

    decision: str = Field(description="continue 或 cancel")
    confirmation_token: str = Field(min_length=1)


__all__ = [
    "RETRY_OVERRIDABLE_FIELDS",
    "AgentRunRequest",
    "AgentRunResponse",
    "CombinedRunRequest",
    "CombinedRunResponse",
    "ConfirmRequest",
    "GoalResolveRequest",
    "GoalResolveResponse",
    "RetryRequest",
    "TaskResult",
]
