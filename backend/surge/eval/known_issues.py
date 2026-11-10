"""已知问题清单：确认过、暂不修的行为，单独统计，不混进通过率。

为什么要有这张表
================

评估一旦有长期红灯，红灯就会失去意义——没人再看。但把红灯改成绿灯更糟：
那等于把缺陷写进"通过标准"。

所以第三条路：**显式登记**。每条都要写清"是什么行为、为什么先接受、
修好之后应该改成什么"。它们不进通过率、不阻断门禁，但在报告里单独列一段，
每次跑都能看见还剩几条。

判据刻意写得很窄（同时看维度、类型、故障、观测结果），
**不允许按前缀一刀切**——那会顺手把同一批里的真实回归也放过。
"""

from __future__ import annotations

from typing import Any, Callable

from .cases import DIM_FACT, EvalCase, FAULT_QUALITY, KIND_COMBINED


class KnownIssue:
    def __init__(self, rule_id: str, reason: str, matches: Callable[[EvalCase, dict[str, Any]], bool]) -> None:
        self.rule_id = rule_id
        self.reason = reason
        self._matches = matches

    def hits(self, case: EvalCase, observed: dict[str, Any]) -> bool:
        return self._matches(case, observed)


def _has_no_bullets(observed: dict[str, Any]) -> bool:
    return not (observed.get("listing") or {}).get("bullets")


KNOWN_ISSUES: tuple[KnownIssue, ...] = (
    KnownIssue(
        rule_id="empty-draft-specs-only",
        reason=(
            "只有规格、没有卖点时，规则引擎产出 0 条要点的空草稿，任务仍以成功收尾。"
            "待定：是在事实闸门处拦成「待补充卖点」，还是把空草稿降级为待复核。"
        ),
        matches=lambda case, observed: (
            case.dimension == DIM_FACT and "specs_only" in case.case_id and _has_no_bullets(observed)
        ),
    ),
    KnownIssue(
        rule_id="qc-failed-but-succeeded",
        reason=(
            "组合流程在「质检未通过且无法修订」时仍标成功（降级生成不计为 partial）。"
            "后果是用户可能把未过质检的草稿当成可用产出，建议改为 needs_review。"
        ),
        matches=lambda case, observed: (
            case.fault == FAULT_QUALITY
            and case.kind == KIND_COMBINED
            and observed.get("outcome") == "succeeded"
        ),
    ),
)


def known_reason(case: EvalCase, observed: dict[str, Any]) -> str:
    """命中已知问题则返回说明，否则返回空串。"""
    for issue in KNOWN_ISSUES:
        if issue.hits(case, observed):
            return issue.reason
    return ""


__all__ = ["KNOWN_ISSUES", "KnownIssue", "known_reason"]
