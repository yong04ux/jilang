"""Agent 能力路由：显式选择优先，未选择时按目标从技能目录里挑。

优先级（从高到低）
==================

1. ``skill_key``：用户在界面上明确选了技能，直接按它的语义执行；
2. 调用方显式给的 ``listing_only`` / ``with_listing``：参数即约束；
3. 自动路由：模型（或关键词兜底）从目录里选出本次真正需要的技能，
   再映射到现有的工作流（竞品 / 组合 / 仅 Listing）。

只做「选能力」，不改执行图：映射结果仍然是 ``workflows.choose`` 认得的那两个开关。
这样路由错了最多是多跑/少跑 Listing，不会绕过质检或落库节点。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..skills.discovery import CatalogEntry, DiscoveryResult, discover

#: 显式选择 → (with_listing, listing_only)。其余技能需要专属参数，不走 Agent 图。
EXPLICIT_ROUTES: dict[str, tuple[bool, bool]] = {
    "competitor_analysis": (False, False),
    "listing_generation": (True, True),
}

#: Agent 图能直接执行的能力。``market_summary`` / ``review_mining`` 由竞品工作流
#: 内部完成（报告里已经包含评论洞察），不需要单独节点。
AGENT_SKILLS = {
    "competitor_analysis",
    "listing_generation",
    "market_summary",
    "review_mining",
}

#: 判定「需要竞品」的技能：命中任意一个就至少跑竞品工作流。
_COMPETITOR_SKILLS = {"competitor_analysis", "market_summary", "review_mining"}


@dataclass(frozen=True)
class RoutingDecision:
    #: ``explicit`` = 用户选的；``auto`` = Agent 按目标选的；``default`` = 没干预
    mode: str = "default"
    skill_keys: tuple[str, ...] = ()
    skills: tuple[dict[str, Any], ...] = ()
    with_listing: bool | None = None
    listing_only: bool | None = None
    degraded: bool = False
    reason: str = ""
    #: 识别到但本次不执行的技能（需要专属参数），给用户一句解释
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "skill_keys": list(self.skill_keys),
            "skills": [dict(item) for item in self.skills],
            "with_listing": self.with_listing,
            "listing_only": self.listing_only,
            "degraded": self.degraded,
            "reason": self.reason,
            "note": self.note,
        }


def _entry_views(entries: list[CatalogEntry], keys: list[str]) -> tuple[dict[str, Any], ...]:
    by_key = {entry.key: entry for entry in entries}
    views = []
    for key in keys:
        entry = by_key.get(key)
        if entry is not None:
            views.append(entry.as_dict())
    return tuple(views)


def decide(
    *,
    skill_key: str | None,
    goal: str,
    entries: list[CatalogEntry],
    client: Any = None,
    with_listing_explicit: bool = False,
    listing_only_explicit: bool = False,
) -> RoutingDecision:
    """给出本次执行的能力路由。

    显式 ``skill_key`` 不做二次判断；自动路由失败（没有模型/模型输出不合规）
    会退到关键词匹配，并在 ``degraded/reason`` 里如实标注。
    """
    key = (skill_key or "").strip()
    if key:
        route = EXPLICIT_ROUTES.get(key)
        if route is None:
            raise ValueError(f"技能 {key} 需要专属参数，不能走 Agent 工作流")
        with_listing, listing_only = route
        return RoutingDecision(
            mode="explicit",
            skill_keys=(key,),
            skills=_entry_views(entries, [key]),
            with_listing=with_listing,
            listing_only=listing_only,
        )

    if not (goal or "").strip() or listing_only_explicit:
        return RoutingDecision()

    result: DiscoveryResult = discover(
        goal,
        entries=entries,
        client=client,
        load_body=False,
        limit=5,
    )
    keys = [item.entry.key for item in result.items]
    if not keys:
        return RoutingDecision(
            mode="auto",
            degraded=result.degraded,
            reason=result.reason,
        )

    key_set = set(keys)
    if not (key_set & AGENT_SKILLS):
        # 只选中了利润测算/数据校验/质检这类需要专属参数的能力。
        # 不能默默退回默认组合流程——那会跑一堆与目标无关的步骤。
        return RoutingDecision(
            mode="unsupported",
            skill_keys=tuple(keys),
            skills=tuple(item.entry.as_dict() for item in result.items),
            degraded=result.degraded,
            reason=result.reason,
            note="这些能力需要专属参数，本次 Agent 不能直接执行。",
        )

    needs_competitor = bool(key_set & _COMPETITOR_SKILLS)
    has_listing = "listing_generation" in key_set

    with_listing: bool | None = None
    listing_only: bool | None = None
    if has_listing:
        if not with_listing_explicit:
            with_listing = True
        if not listing_only_explicit:
            listing_only = not needs_competitor
    elif needs_competitor:
        if not with_listing_explicit:
            with_listing = False
        if not listing_only_explicit:
            listing_only = False

    # 显式 ``with_listing=false`` 与「只写文案」矛盾时，以显式参数为准
    if with_listing is False and not listing_only_explicit:
        listing_only = False

    unsupported = sorted(key_set - AGENT_SKILLS)
    note = ""
    if unsupported:
        names = "、".join(
            item.entry.name for item in result.items if item.entry.key in unsupported
        )
        note = f"已识别到「{names}」，但它们需要专属参数，本次 Agent 不会直接执行。"

    return RoutingDecision(
        mode="auto",
        skill_keys=tuple(keys),
        skills=tuple(item.entry.as_dict() for item in result.items),
        with_listing=with_listing,
        listing_only=listing_only,
        degraded=result.degraded,
        reason=result.reason,
        note=note,
    )


__all__ = ["AGENT_SKILLS", "EXPLICIT_ROUTES", "RoutingDecision", "decide"]
