"""跑真模型的评测：构造 Provider、重复采样、汇总波动。

三个前提
========

1. **必须真的是模型。** 没有 Key 时 ``build_provider`` 会**静默降级**成规则引擎
   （那是产品的正确行为），但在这里会变成"拿规则引擎的结果冒充模型质量"。
   所以开跑前先验 ``engine_label``，是 rule 就直接报错退出。
2. **单次结果不作数。** 模型有波动，同一用例跑 ``--repeats`` 次，看均值、
   最差值和通过率——只看一次容易把运气当水平。
3. **不落库。** 全程 ``persist=False``，不写业务表。

干跑模式（``--dry-run``）用规则引擎走完整链路，只为验证评测本身没写坏，
**不代表模型质量**，输出里会显式标成 ``dry-run``。
"""

from __future__ import annotations

import time
from typing import Any

from .live_cases import LLMCase
from .live_scoring import DraftScore, score_draft


class LiveEvalError(RuntimeError):
    """评测无法继续（缺 Key、降级成规则引擎等）。"""


def build_live_provider(
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = "",
    timeout: float = 120.0,
    max_retries: int = 1,
    temperature: float = 0.3,
) -> Any:
    """按显式参数构造 Provider（不经用户配置、不读数据库）。"""
    from ..config import get_settings
    from ..llm.model_settings import EffectiveModelConfig
    from ..llm.providers import build_provider

    config = EffectiveModelConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        max_tokens=None,
        timeout=timeout,
        max_retries=max_retries,
        thinking=False,
        reasoning_effort="",
        source="user",
    )
    return build_provider(get_settings(), config)


def rule_provider() -> Any:
    """干跑用：规则引擎，确定性。"""
    from ..llm.providers import RuleProvider

    return RuleProvider()


def assert_not_fallback(provider: Any) -> dict[str, Any]:
    """确认拿到的是真模型；是规则引擎就报错，别让降级冒充评测结果。"""
    from ..llm.providers import engine_label

    label = engine_label(provider)
    if label["kind"] != "llm":
        reason = getattr(provider, "fallback_reason", "") or "没有可用的模型凭据"
        raise LiveEvalError(
            f"Provider 降级成了规则引擎（{reason}）。"
            "真模型评测需要可用的 API Key，否则测出来的不是模型质量。"
        )
    return label


# ---------------------------------------------------------------------------
# 单次与重复
# ---------------------------------------------------------------------------


def _run_once(case: LLMCase, provider: Any) -> tuple[dict[str, Any], float, dict[str, int]]:
    from ..agent.graphs.listing_generation import run_listing_graph

    before = dict(getattr(provider, "last_usage", {}) or {})
    started = time.perf_counter()
    state = run_listing_graph(
        {"request": dict(case.request), "persist": False, "task_id": f"eval-{case.case_id}"},
        provider=provider,
        db=None,
        persist=False,
    )
    elapsed = (time.perf_counter() - started) * 1000
    after = dict(getattr(provider, "last_usage", {}) or {})
    usage = {key: int(after.get(key, 0) - before.get(key, 0)) for key in set(after) | set(before)}
    # 质检没过也要把草稿拿出来打分：那是模型输出本身，评分不看流程结局
    return (state.get("listing") or {}), elapsed, usage


def run_case(case: LLMCase, provider: Any, repeats: int) -> dict[str, Any]:
    """同一条用例跑 ``repeats`` 次，返回分数分布与最差的一次。"""
    scores: list[DraftScore] = []
    durations: list[float] = []
    tokens = 0
    errors: list[str] = []

    for _ in range(max(1, repeats)):
        try:
            draft, elapsed, usage = _run_once(case, provider)
        except Exception as exc:  # noqa: BLE001 - 单次失败不该中断整轮
            errors.append(f"{type(exc).__name__}: {exc}"[:300])
            continue
        durations.append(elapsed)
        tokens += int(usage.get("total_tokens", 0) or 0)
        scores.append(score_draft(case, draft))

    if not scores:
        return {
            "case_id": case.case_id,
            "title": case.title,
            "runs": 0,
            "passed": 0,
            "pass_rate": 0.0,
            "mean_score": 0,
            "min_score": 0,
            "max_score": 0,
            "score_spread": 0,
            "p50_ms": 0,
            "tokens": tokens,
            "failures": [],
            "errors": errors or ["全部运行失败"],
        }

    values = [s.score for s in scores]
    passed = sum(1 for s in scores if s.passed)
    failures: list[str] = []
    for item in scores:
        for failure in item.failures:
            if failure not in failures:
                failures.append(failure)

    ordered = sorted(durations)
    return {
        "case_id": case.case_id,
        "title": case.title,
        "runs": len(scores),
        "passed": passed,
        "pass_rate": round(passed / len(scores), 3),
        "mean_score": round(sum(values) / len(values), 1),
        "min_score": min(values),
        "max_score": max(values),
        # 波动幅度：同一输入分数差多少，是模型稳定性的直接读数
        "score_spread": max(values) - min(values),
        "p50_ms": int(ordered[len(ordered) // 2]),
        "tokens": tokens,
        "failures": failures,
        "errors": errors,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """把逐用例结果压成总体口径。"""
    total_runs = sum(r["runs"] for r in rows)
    passed_runs = sum(r["passed"] for r in rows)
    scores = [r["mean_score"] for r in rows if r["runs"]]
    spreads = [r["score_spread"] for r in rows if r["runs"]]
    latencies = [r["p50_ms"] for r in rows if r["runs"]]

    return {
        "cases": len(rows),
        "runs": total_runs,
        "run_pass_rate": round(passed_runs / total_runs, 3) if total_runs else 0.0,
        # 用例级通过：该用例所有重复都过，才算稳
        "stable_pass_rate": (
            round(sum(1 for r in rows if r["runs"] and r["passed"] == r["runs"]) / len(rows), 3)
            if rows
            else 0.0
        ),
        "mean_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "worst_score": min((r["min_score"] for r in rows if r["runs"]), default=0),
        "mean_spread": round(sum(spreads) / len(spreads), 1) if spreads else 0.0,
        "p50_ms": sorted(latencies)[len(latencies) // 2] if latencies else 0,
        "tokens": sum(r["tokens"] for r in rows),
    }


__all__ = [
    "LiveEvalError",
    "assert_not_fallback",
    "build_live_provider",
    "rule_provider",
    "run_case",
    "summarize",
]
