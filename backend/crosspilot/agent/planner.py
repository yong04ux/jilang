"""目标解析与计划（阶段 D5）。

分工：

- **LLM 只做"把自然语言翻译成结构化参数"**（商品、平台、站点、是否生成 Listing）；
- **计划本身是确定性的**：图节点固定为 analyze→integrity→summary→
  (listing→quality)→persist，LLM 不决定执行哪些节点。这样计划可测试、
  不会因为模型幻觉跳过质检。
- LLM 不可用 / 返回不合规时，降级为规则解析，并在任务上标 ``degraded=true``，
  同时把原因写进任务输出与界面——**不允许静默降级**。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..models import Platform
from ..engine.scrubbing import scrub_for_llm

PLATFORM_VALUES = {item.value for item in Platform}

# 站点 → 默认文案语言
MARKETPLACE_LANGUAGE = {
    "US": "en-US",
    "CA": "en-CA",
    "UK": "en-GB",
    "DE": "de-DE",
    "FR": "fr-FR",
    "IT": "it-IT",
    "ES": "es-ES",
    "JP": "ja-JP",
    "MX": "es-MX",
}

_MARKETPLACE_HINTS = (
    ("美国", "US"),
    ("US", "US"),
    ("加拿大", "CA"),
    ("英国", "UK"),
    ("UK", "UK"),
    ("德国", "DE"),
    ("法国", "FR"),
    ("意大利", "IT"),
    ("西班牙", "ES"),
    ("日本", "JP"),
    ("墨西哥", "MX"),
)

_LANGUAGE_HINTS = (
    ("英文", "en-US"),
    ("英语", "en-US"),
    ("日文", "ja-JP"),
    ("日语", "ja-JP"),
    ("德文", "de-DE"),
    ("德语", "de-DE"),
    ("法文", "fr-FR"),
    ("法语", "fr-FR"),
    ("西语", "es-ES"),
)

_NO_LISTING_HINTS = ("只做竞品", "只分析", "不要生成 listing", "不要 listing", "不生成文案", "仅竞品分析")


class GoalSpec(BaseModel):
    """一次 Agent 运行的结构化目标。"""

    product_name: str = Field(min_length=1, max_length=200)
    platform: str = "amazon"
    marketplace: str = "US"
    category: str | None = None
    with_listing: bool = True
    listing_language: str = "en-US"
    keywords: list[str] = Field(default_factory=list)
    notes: str = ""

    def normalized(self) -> "GoalSpec":
        platform = (self.platform or "amazon").strip().lower()
        if platform not in PLATFORM_VALUES:
            platform = "amazon"
        marketplace = (self.marketplace or "US").strip().upper()
        language = (self.listing_language or "").strip() or MARKETPLACE_LANGUAGE.get(
            marketplace, "en-US"
        )
        return GoalSpec(
            product_name=self.product_name.strip(),
            platform=platform,
            marketplace=marketplace,
            category=(self.category or "").strip() or None,
            with_listing=self.with_listing,
            listing_language=language,
            keywords=[k for k in (self.keywords or []) if str(k).strip()][:20],
            notes=self.notes or "",
        )


@dataclass
class GoalResolution:
    spec: GoalSpec
    degraded: bool = False
    reason: str = ""
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.model_dump(),
            "degraded": self.degraded,
            "reason": self.reason,
            "missing": self.missing,
        }


def _marketplace_from_text(text: str) -> str:
    upper = text.upper()
    for hint, code in _MARKETPLACE_HINTS:
        if hint.isupper():
            if re.search(rf"\b{re.escape(hint)}\b", upper):
                return code
        elif hint in text:
            return code
    return "US"


def _product_from_text(text: str) -> str:
    quoted = re.search(r"[“\"「『]([^”\"」』]{2,120})[”\"」』]", text)
    if quoted:
        return quoted.group(1).strip()

    cleaned = re.sub(
        r"(帮我|请|麻烦|先|然后|再|并且|并|要|想|需要|分析|生成|撰写|写一份|一份|英文|中文|"
        r"listing|Listing|LISTING|的竞品|竞品|市场|报告|文案|草稿)",
        " ",
        text,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。.：:；;、-")
    if not cleaned:
        return text.strip()[:80]
    return cleaned[:80]


def rule_resolve(goal: str) -> GoalSpec:
    """确定性降级解析：只做能站得住脚的推断，其余交给用户确认。"""
    text = " ".join((goal or "").split())
    with_listing = not any(hint in text.lower() for hint in _NO_LISTING_HINTS)
    marketplace = _marketplace_from_text(text)
    language = MARKETPLACE_LANGUAGE.get(marketplace, "en-US")
    for hint, code in _LANGUAGE_HINTS:
        if hint in text:
            language = code
            break
    return GoalSpec(
        product_name=_product_from_text(text) or text[:80],
        platform="amazon",
        marketplace=marketplace,
        with_listing=with_listing,
        listing_language=language,
    ).normalized()


_LLM_SCHEMA_HINT = """{
  "product_name": "商品名（保留原文，不要翻译）",
  "platform": "amazon | ebay（默认 amazon）",
  "marketplace": "US | CA | UK | DE | FR | IT | ES | JP | MX",
  "category": "品类或 null",
  "with_listing": true,
  "listing_language": "en-US | ja-JP | de-DE ...",
  "keywords": ["用户提到的关键词"],
  "notes": "无法确定的点"
}"""


def resolve_goal(
    goal: str,
    *,
    client: Any = None,
    fallback_reason: str = "",
) -> GoalResolution:
    """解析自然语言目标。

    ``client`` 需提供 ``chat_json(messages, schema_hint=...)``（DeepSeekClient
    或测试里的假客户端）。没有客户端、调用失败、输出不合规都降级。
    """
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("goal 不能为空")

    rule_spec = rule_resolve(goal)
    if client is None:
        return GoalResolution(
            spec=rule_spec,
            degraded=True,
            reason=fallback_reason
            or "未配置可用模型，已用规则解析目标；商品名与参数请在参数面板确认",
        )

    messages = [
        {
            "role": "system",
            "content": (
                "你是电商运营任务的目标解析器。只提取用户明确说出的信息；"
                "不要编造商品、认证、销量或竞品数据。无法确定的字段留空或用默认值。"
            ),
        },
        {"role": "user", "content": scrub_for_llm(goal)[:2000]},
    ]
    try:
        data, _result = client.chat_json(
            messages, schema_hint=_LLM_SCHEMA_HINT, temperature=0.0
        )
        spec = GoalSpec(**data).normalized()
        return GoalResolution(spec=spec, degraded=False, reason="")
    except (ValidationError, ValueError, TypeError) as exc:
        return GoalResolution(
            spec=rule_spec,
            degraded=True,
            reason=f"模型返回的目标不合规，已降级为规则解析：{exc}",
        )
    except Exception as exc:  # noqa: BLE001 - 网络/限流等一律降级但必须留痕
        return GoalResolution(
            spec=rule_spec,
            degraded=True,
            reason=f"模型目标解析失败，已降级为规则解析：{type(exc).__name__}: {exc}",
        )


def plan_for(with_listing: bool) -> list[str]:
    """执行计划骨架（与 ``agent/workflows.py`` 的分派结果一致）。

    Phase 5 起计划不再是"图里有哪些节点"，而是「主图三阶段 + 所选工作流的步骤」。
    保留这个函数名是因为 ``api/agents.py`` 与既有测试都按它取计划；
    实现委托给 workflows，**分派判据只有一处**。
    """
    from . import workflows

    return workflows.choose({"with_listing": with_listing}).plan()


__all__ = [
    "GoalResolution",
    "GoalSpec",
    "MARKETPLACE_LANGUAGE",
    "plan_for",
    "resolve_goal",
    "rule_resolve",
]
