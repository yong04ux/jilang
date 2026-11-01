"""汇总与报告：把一堆用例结果压成能读、能比、能入库的东西。

为什么要入库
============

评测的价值在"这次和上次比变了吗"。报告只打印到屏幕上，就没法 diff，
下次只能凭印象说"应该没问题"。所以默认把结果写到
``examples/eval/latest.json``——**这个路径不在 .gitignore 里**，
可以随代码一起提交，成为基线。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cases import DIMENSIONS, EvalCase


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * ratio)))
    return ordered[index]


def build_result(
    cases: list[EvalCase],
    observations: list[dict[str, Any]],
    verdicts: list[list[str]],
    known: list[str] | None = None,
) -> dict[str, Any]:
    """把逐条结果汇总成一份可比较的报告。

    ``known`` 是已知问题说明（按用例对齐）。命中的用例**不算通过也不算未通过**，
    单独计数——它们不阻断门禁，但每次都会出现在报告里。
    """
    known = known or [""] * len(observations)
    by_id = {case.case_id: case for case in cases}
    rows: list[dict[str, Any]] = []
    for observation, failures, known_reason in zip(observations, verdicts, known):
        case = by_id[observation["case_id"]]
        rows.append(
            {
                "case_id": case.case_id,
                "dimension": case.dimension,
                "kind": case.kind,
                "fault": case.fault,
                "known": known_reason,
                "ok": not failures and not known_reason,
                "outcome": observation["outcome"],
                "duration_ms": observation["duration_ms"],
                "error_code": observation["error_code"],
                "reasons": failures,
            }
        )

    per_dimension: dict[str, dict[str, Any]] = {}
    for dimension in DIMENSIONS:
        subset = [r for r in rows if r["dimension"] == dimension]
        if not subset:
            continue
        per_dimension[dimension] = {
            "cases": len(subset),
            "passed": sum(1 for r in subset if r["ok"]),
            "failed": sum(1 for r in subset if not r["ok"] and not r["known"]),
            "known": sum(1 for r in subset if r["known"]),
            "total_ms": sum(r["duration_ms"] for r in subset),
        }

    durations = [r["duration_ms"] for r in rows]
    outcomes: dict[str, int] = {}
    errors: dict[str, int] = {}
    for row in rows:
        outcomes[row["outcome"] or "(空)"] = outcomes.get(row["outcome"] or "(空)", 0) + 1
        if row["error_code"]:
            errors[row["error_code"]] = errors.get(row["error_code"], 0) + 1

    # 完成率口径：跑通或标了 partial 都算"给出结果"，拦下与失败不算
    finished = sum(outcomes.get(k, 0) for k in ("succeeded", "partial"))
    delivered = finished + outcomes.get("needs_user_input", 0)
    total = len(rows) or 1

    known_rows = [r for r in rows if r["known"]]
    effective = total - len(known_rows) or 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": "rule（确定性，不调模型）",
        "suite": {
            "total": len(rows),
            "dimensions": {k: v["cases"] for k, v in per_dimension.items()},
        },
        "summary": {
            "passed": sum(1 for r in rows if r["ok"]),
            "failed": sum(1 for r in rows if not r["ok"] and not r["known"]),
            "known": len(known_rows),
            # 通过率的分母排除已知问题：否则一条登记过的缺陷会永久压低分母
            "pass_rate": round(sum(1 for r in rows if r["ok"]) / effective, 4),
            "total_ms": sum(durations),
        },
        "timing": {
            "p50_ms": _percentile(durations, 0.5),
            "p95_ms": _percentile(durations, 0.95),
            "max_ms": max(durations) if durations else 0,
            "total_ms": sum(durations),
            "by_dimension": {k: v["total_ms"] for k, v in per_dimension.items()},
        },
        "rates": {
            # 「完成率」只统计该给出结果的用例（排除故意注入故障的那批）
            "completion_rate": round(finished / total, 4),
            "answered_rate": round(delivered / total, 4),
            "failed_rate": round(outcomes.get("failed", 0) / total, 4),
        },
        "outcomes": outcomes,
        "errors": errors,
        "dimensions": per_dimension,
        "failures": [
            {"case_id": r["case_id"], "dimension": r["dimension"], "reasons": r["reasons"]}
            for r in rows
            if not r["ok"] and not r["known"]
        ],
        "known_issues": [
            {"case_id": r["case_id"], "dimension": r["dimension"], "reason": r["known"]}
            for r in known_rows
        ],
        "cases": rows,
    }


# ---------------------------------------------------------------------------
# 与基线比较
# ---------------------------------------------------------------------------


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    """逐条对比两次结果，只关心"原本通过的现在挂了"。"""
    before = {c["case_id"]: c for c in baseline.get("cases") or []}
    after = {c["case_id"]: c for c in current.get("cases") or []}

    regressions: list[str] = []
    fixed: list[str] = []
    for case_id, row in after.items():
        old = before.get(case_id)
        if old is None:
            continue
        if old["ok"] and not row["ok"]:
            regressions.append(case_id)
        elif not old["ok"] and row["ok"]:
            fixed.append(case_id)

    return {
        # 排序保证输出稳定，方便直接看 diff
        "regressions": sorted(regressions),
        "fixed": sorted(fixed),
        "new_cases": sorted(set(after) - set(before)),
        "removed_cases": sorted(set(before) - set(after)),
    }


# ---------------------------------------------------------------------------
# 落盘与 Markdown
# ---------------------------------------------------------------------------


def write_json(result: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


_DIMENSION_LABEL = {
    "tool_call": "工具调用正确性",
    "fact_consistency": "Listing 事实一致性",
    "completion": "任务完成率",
    "recovery": "失败恢复",
}


def render_markdown(result: dict[str, Any], diff: dict[str, list[str]] | None = None) -> str:
    summary = result["summary"]
    timing = result["timing"]
    lines = [
        "# 离线评测报告",
        "",
        f"- 生成时间：{result['generated_at']}",
        f"- 引擎：{result['engine']}",
        f"- 用例：**{result['suite']['total']}** 条 · 通过 {summary['passed']} · 未通过 {summary['failed']}"
        f" · 通过率 {summary['pass_rate'] * 100:.1f}%",
        f"- 耗时：总计 {timing['total_ms']} ms · p50 {timing['p50_ms']} ms · p95 {timing['p95_ms']} ms",
        "",
        "## 分维度",
        "",
        "| 维度 | 用例 | 通过 | 未通过 | 耗时(ms) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for key, stat in result["dimensions"].items():
        lines.append(
            f"| {_DIMENSION_LABEL.get(key, key)} | {stat['cases']} | {stat['passed']} | "
            f"{stat['failed']} | {stat['total_ms']} |"
        )

    lines += [
        "",
        "## 结局与错误分类",
        "",
        "| 结局 | 条数 |",
        "| --- | ---: |",
    ]
    for outcome, count in sorted(result["outcomes"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {outcome} | {count} |")
    if result["errors"]:
        lines += ["", "| 错误分类 | 条数 |", "| --- | ---: |"]
        for code, count in sorted(result["errors"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| {code} | {count} |")

    if diff:
        lines += ["", "## 与基线比较", ""]
        if diff["regressions"]:
            lines.append(f"- **回归 {len(diff['regressions'])} 条**：" + "、".join(diff["regressions"][:10]))
        else:
            lines.append("- 无回归")
        if diff["fixed"]:
            lines.append(f"- 修复 {len(diff['fixed'])} 条：" + "、".join(diff["fixed"][:10]))
        if diff["new_cases"]:
            lines.append(f"- 新增用例 {len(diff['new_cases'])} 条")
        if diff["removed_cases"]:
            lines.append(f"- 移除用例 {len(diff['removed_cases'])} 条")

    if result["failures"]:
        lines += ["", "## 未通过明细", "", "| 用例 | 维度 | 原因 |", "| --- | --- | --- |"]
        for item in result["failures"][:40]:
            reason = "；".join(item["reasons"])
            lines.append(f"| `{item['case_id']}` | {item['dimension']} | {reason} |")
        if len(result["failures"]) > 40:
            lines.append(f"| … | | 另有 {len(result['failures']) - 40} 条，见 latest.json |")

    lines += [
        "",
        "> 本表衡量的是**编排、规则引擎与错误处理**的行为一致性：该拦的有没有拦住、"
        "该标的有没有标、出错时分类对不对、恢复后有没有留下半成品。",
        "> **它不代表大模型写出来的文案质量**——评估全程使用规则引擎，不产生网络调用。",
    ]
    return "\n".join(lines) + "\n"


__all__ = ["build_result", "compare", "load_json", "render_markdown", "write_json"]
