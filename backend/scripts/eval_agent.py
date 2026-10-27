"""固定评估集运行器（Phase 7：质量变化可用同一套样例比较）。

为什么用规则引擎
================

评估要**可复现**，否则"重构前 vs 重构后"的数字没法比——同一份输入每天跑出
不同的模型输出，比较就退化成看运气。所以默认用 ``RuleProvider``（无网络、
无 Key、确定性），衡量的是**编排与规则引擎的结构性质量**：

- 该拦的有没有拦住（缺事实不进生成）
- 该存的标记有没有存（示例数据标记、来源）
- 结论有没有证据（统计类 vs 推断类）
- 有没有"partial 被悄悄变成 success"

**它不代表大模型生成质量。** 要评模型质量得另外建一套带人工评审的样例，
那需要真 Key 和评审流程，不在本脚本范围内。

跑法
====

    python -m scripts.eval_agent            # 跑全部用例，更新 docs/eval-latest.json
    python -m scripts.eval_agent --print    # 只打印，不写文件

输出
====

- ``docs/eval-latest.json``：机器可读结果（用于前后对比）
- 控制台摘要；``--write-report`` 时再生成 ``docs/eval-report.md``
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "examples" / "eval" / "cases.json"
OUT_JSON = ROOT / "docs" / "eval-latest.json"
OUT_MD = ROOT / "docs" / "eval-report.md"


def _demo_competitors(limit: int | None = None) -> list[dict[str, Any]]:
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    rows = [dict(item) for item in DEMO_ANALYSIS_REQUEST["competitors"]]
    return rows[:limit] if limit else rows


def _build_request(case: dict[str, Any]) -> dict[str, Any]:
    payload = dict(case["input"])
    limit = payload.pop("competitors_limit", None)
    if "competitors" not in payload:
        payload["competitors"] = _demo_competitors(limit)
    return payload


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    """跑一个用例，返回观测结果（不含断言结论）。"""
    from crosspilot.agent import workflows
    from crosspilot.llm.providers import RuleProvider
    from crosspilot.market.competitor_provider import MODE_IMPORTED, build_competitor_provider

    provider = RuleProvider()
    competitor_provider = build_competitor_provider(MODE_IMPORTED, db=None, tenant_id="")
    payload = _build_request(case)
    payload["with_listing"] = case["kind"] == "combined"

    started = time.perf_counter()
    paused = False
    state: dict[str, Any] = {}
    error = ""
    try:
        spec = workflows.choose(payload)
        state = workflows.run(
            spec,
            payload,
            db=None,
            tenant_id="eval-tenant",
            user_id="eval-user",
            task_id=f"eval-{case['id']}",
            provider=provider,
            competitor_provider=competitor_provider,
            task=None,
            resume_from=None,
            # 评估不落库：不写业务表，也就不需要数据库
            persist=False,
        )
        if workflows.is_paused(state):
            paused = True
            # 评估"用户确认继续"之后的结果，而不是停在暂停点
            from crosspilot.agent.graphs.combined_operations import build_combined_graph

            graph = build_combined_graph(provider=provider, persist=False)
            state = graph.resume(
                "continue", workflows.thread_config("eval-tenant", f"eval-{case['id']}")
            )
    except Exception as exc:  # noqa: BLE001 - 评估脚本要记录失败而不是中断整轮
        error = f"{type(exc).__name__}: {exc}"

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    report = state.get("analysis_report") or state.get("report") or {}
    listing = state.get("listing") or {}
    return {
        "id": case["id"],
        "kind": case["kind"],
        "paused": paused,
        "outcome": state.get("outcome") or ("failed" if error else "unknown"),
        "task_status": state.get("task_status") or "",
        "elapsed_ms": elapsed_ms,
        "error": error,
        "report": report,
        "listing": listing,
        "provenance": state.get("provenance") or {},
    }


def _bullets(listing: dict[str, Any]) -> list[dict[str, Any]]:
    """取草稿要点。要点是**对象**（headline/body/supporting_facts），不是字符串。

    早先这里直接 ``str(b)``，把 ``character_count`` 也算进正文，
    结果"要点里出现编造数字"这条检查被自己的脚本触发了——取值方式必须精确。
    """
    raw = listing.get("bullets") or []
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            text = f"{item.get('headline') or ''} {item.get('body') or ''}".strip()
            result.append(
                {
                    "text": text,
                    "facts": [str(f) for f in (item.get("supporting_facts") or [])],
                }
            )
        elif str(item).strip():
            result.append({"text": str(item), "facts": []})
    return result


def _facts_text(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False)


def _check(case: dict[str, Any], observed: dict[str, Any], checks: dict[str, Any]) -> list[str]:
    """返回不满足的断言（空列表 = 通过）。"""
    expect = case.get("expect") or {}
    failures: list[str] = []
    listing = observed["listing"]
    bullets = _bullets(listing)

    if "outcome" in expect and observed["outcome"] != expect["outcome"]:
        failures.append(f"outcome={observed['outcome']}，期望 {expect['outcome']}")
    if "has_listing" in expect:
        if bool(listing) != bool(expect["has_listing"]):
            failures.append(f"listing 存在={bool(listing)}，期望 {expect['has_listing']}")
    if "has_report" in expect and bool(observed["report"]) != bool(expect["has_report"]):
        failures.append("报告存在性不符")
    if "pauses" in expect and observed["paused"] != expect["pauses"]:
        failures.append(f"暂停={observed['paused']}，期望 {expect['pauses']}")
    if expect.get("never_silently_succeeds") and observed["paused"]:
        if observed["outcome"] == "succeeded":
            failures.append("partial 被静默转换成了 success")

    if "bullets" in expect:
        low, high = expect["bullets"]
        if bullets and not (low <= len(bullets) <= high):
            failures.append(f"要点数 {len(bullets)} 不在 [{low}, {high}]")

    if expect.get("demo_flagged"):
        provenance = observed["provenance"] or {}
        if not provenance.get("is_demo"):
            failures.append("示例数据标记丢失")

    # 可追溯性：每条要点都必须引用事实。这是"不编造"的直接落点——
    # 没有 supporting_facts 的要点等于无依据。
    for index, bullet in enumerate(bullets, start=1):
        if not bullet["facts"]:
            failures.append(f"第 {index} 条要点没有引用任何事实")

    # 违禁词：Listing 不许出现绝对化承诺
    for term in checks.get("banned_terms") or []:
        haystack = " ".join(
            [b["text"] for b in bullets] + [str(listing.get("title") or "")]
        ).lower()
        if term.lower() in haystack:
            failures.append(f"出现违禁词：{term}")

    # 关键事实核对：要点正文出现的数字必须能在事实/竞品数据里找到，
    # 否则就是编造参数（本项目最在意的红线）
    if bullets:
        facts = _facts_text(observed["report"]).lower()
        for bullet in bullets:
            for token in _numbers(bullet["text"]):
                if token not in facts:
                    failures.append(f"要点里的数字「{token}」在事实与竞品数据中找不到")
                    break

    # 证据：统计结论必须带证据条数
    if checks.get("must_have_evidence"):
        price = (observed["report"].get("price_analysis") or {})
        for claim in price.get("claims") or []:
            if claim.get("evidence_kind") == "statistic" and not claim.get("evidence"):
                failures.append("统计结论缺少证据引用")
                break
    return failures


def _numbers(text: str) -> list[str]:
    """抽取文本里的数字（含小数），用于"是否编造参数"的核对。"""
    import re

    return re.findall(r"\d+(?:\.\d+)?", text)


def run_all(write: bool = True) -> dict[str, Any]:
    cases_doc = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    checks = cases_doc.get("checks") or {}
    results: list[dict[str, Any]] = []
    for case in cases_doc["cases"]:
        observed = _run_case(case)
        failures = _check(case, observed, checks)
        results.append(
            {
                "id": observed["id"],
                "title": case.get("title"),
                "kind": observed["kind"],
                "paused": observed["paused"],
                "outcome": observed["outcome"],
                "elapsed_ms": observed["elapsed_ms"],
                "bullets": len(_bullets(observed["listing"])),
                "ok": not failures,
                "failures": failures,
                "error": observed["error"],
            }
        )

    summary = {
        "version": cases_doc.get("version"),
        "engine": "rule（确定性，不含大模型）",
        "cases": len(results),
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "total_ms": sum(r["elapsed_ms"] for r in results),
        # 信息性指标：如实记录，不设阈值。规则引擎的要点数天然少于
        # 电商惯例的 3–5 条，这里把差距摆出来，而不是靠调期望值把它藏掉。
        "bullet_counts": {r["id"]: r["bullets"] for r in results},
        "results": results,
    }
    if write:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# 固定评估集结果",
        "",
        f"- 引擎：{summary['engine']}",
        f"- 用例：{summary['cases']}，通过 {summary['passed']}，未通过 {summary['failed']}",
        f"- 总耗时：{summary['total_ms']} ms（本机，仅供参考，不是性能结论）",
        "",
        "| 用例 | 类型 | 结果 | 暂停 | 要点数 | 耗时(ms) | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summary["results"]:
        note = "通过" if row["ok"] else "；".join(row["failures"])
        lines.append(
            f"| {row['id']} | {row['kind']} | {row['outcome']} | "
            f"{'是' if row['paused'] else '否'} | {row['bullets']} | {row['elapsed_ms']} | {note} |"
        )
    lines += [
        "",
        "> 本表衡量的是**编排与规则引擎**的结构性质量（是否拦住、是否保留标记、"
        "结论是否有证据），不代表大模型生成质量。",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="跑固定评估集")
    parser.add_argument("--print", action="store_true", help="只打印，不写文件")
    parser.add_argument("--write-report", action="store_true", help="同时生成 docs/eval-report.md")
    args = parser.parse_args(argv)

    summary = run_all(write=not args.print)
    for row in summary["results"]:
        mark = "PASS" if row["ok"] else "FAIL"
        print(f"[{mark}] {row['id']:<22} outcome={row['outcome']:<18} {row['elapsed_ms']}ms")
        for failure in row["failures"]:
            print(f"       - {failure}")
    print(
        f"\n{summary['passed']}/{summary['cases']} 通过，"
        f"总耗时 {summary['total_ms']}ms（规则引擎，确定性）"
    )
    if args.write_report and not args.print:
        OUT_MD.write_text(render_markdown(summary), encoding="utf-8")
        print(f"报告：{OUT_MD.relative_to(ROOT)}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
