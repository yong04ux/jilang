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
    #: 只生成 Listing：跳过竞品分析与市场总结，直接用商品事实写文案。
    #: 置 true 时 ``competitors`` 可以为空——这条路径不需要竞品数据。
    listing_only: bool = False
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
            raise ValueError("填一句业务目标，或者至少写清商品名称")
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
    #: 本次执行用的是大模型还是规则引擎（界面必须如实标出来）
    engine: dict[str, Any] | None = None
    degraded: bool = False
    degraded_reason: str = ""


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


__all__ = [
    "AgentRunRequest",
    "AgentRunResponse",
    "GoalResolveRequest",
    "GoalResolveResponse",
    "TaskResult",
]
