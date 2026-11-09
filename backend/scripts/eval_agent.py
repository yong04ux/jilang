"""离线评测 CLI。

    python -m scripts.eval_agent                # 跑全部，写基线并打印摘要
    python -m scripts.eval_agent --print        # 只打印，不落盘
    python -m scripts.eval_agent --check        # 和基线比，有回归退出码 1（可做门禁）
    python -m scripts.eval_agent --dim tool_call --limit 5

产物：
    examples/eval/latest.json   机器可读结果（**可入库**，作为下次比较的基线）
    docs/eval-report.md         人读的报告（--write-report）

为什么不把基线放 docs/：docs/ 在 .gitignore 里，放那儿等于每次都从零开始比。

为什么用规则引擎：评估要可复现。同一份输入每天跑出不同的模型输出，
"这次比上次差了吗"就变成看运气。规则引擎无网络、无 Key，同输入同输出，
所以 ``latest.json`` 可以逐条 diff。它衡量的是**编排与规则引擎的行为一致性**，
不代表大模型写出来的文案质量。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = ROOT / "examples" / "eval" / "latest.json"
DEFAULT_REPORT = ROOT / "docs" / "eval-report.md"


def _run(cases, quiet: bool) -> tuple[list[dict], list[list[str]], list[str]]:
    from crosspilot.eval import check, observe
    from crosspilot.eval.known_issues import known_reason

    observations: list[dict] = []
    verdicts: list[list[str]] = []
    known: list[str] = []
    width = len(str(len(cases)))
    for index, case in enumerate(cases, start=1):
        observed = observe(case)
        failures = check(case, observed)
        reason = known_reason(case, observed) if failures else ""
        observations.append(observed)
        verdicts.append(failures)
        known.append(reason)
        if not quiet:
            mark = "PASS" if not failures else ("KNOWN" if reason else "FAIL")
            print(
                f"[{index:>{width}}/{len(cases)}] [{mark}] {case.case_id:<56} "
                f"{observed['outcome'] or '-':<16} {observed['duration_ms']:>5}ms"
            )
            if reason:
                print(f"           已知问题：{reason}")
            else:
                for failure in failures:
                    print(f"           - {failure}")
    return observations, verdicts, known


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="跨境电商业务流程离线评测")
    parser.add_argument("--print", action="store_true", help="只打印，不写文件")
    parser.add_argument("--check", action="store_true", help="与基线比较，有回归则退出码 1")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="基线文件路径")
    parser.add_argument(
        "--dim",
        default="",
        help="只跑某个维度：tool_call / fact_consistency / completion / recovery / routing",
    )
    parser.add_argument("--limit", type=int, default=0, help="每个维度最多跑多少条（调试用）")
    parser.add_argument("--write-report", action="store_true", help="生成 docs/eval-report.md")
    parser.add_argument("--quiet", action="store_true", help="不逐条打印，只给摘要")
    args = parser.parse_args(argv)

    from crosspilot.eval import (
        DIMENSIONS,
        build_result,
        build_suite,
        compare,
        load_json,
        render_markdown,
        suite_stats,
        write_json,
    )

    cases = build_suite()
    stats = suite_stats(cases)
    if args.dim:
        cases = [c for c in cases if c.dimension == args.dim]
        if not cases:
            print(f"未知维度：{args.dim}（可选：{', '.join(DIMENSIONS)}）", file=sys.stderr)
            return 2
    if args.limit:
        grouped: dict[str, list] = {}
        for case in cases:
            grouped.setdefault(case.dimension, []).append(case)
        cases = [c for group in grouped.values() for c in group[: args.limit]]

    dims = " / ".join(f"{k} {v}" for k, v in stats.items() if k != "total")
    print(f"评测集：{len(cases)} 条（{dims}）")

    observations, verdicts, known = _run(cases, quiet=args.quiet)
    result = build_result(cases, observations, verdicts, known)

    baseline = load_json(args.baseline)
    diff = compare(baseline, result) if baseline else None

    summary = result["summary"]
    timing = result["timing"]
    print(
        f"\n通过 {summary['passed']}/{result['suite']['total'] - summary['known']}"
        f"（{summary['pass_rate'] * 100:.1f}%），已知问题 {summary['known']}，"
        f"未通过 {summary['failed']}；总耗时 {timing['total_ms']}ms，"
        f"p50 {timing['p50_ms']}ms / p95 {timing['p95_ms']}ms"
    )
    print(
        "结局分布："
        + "、".join(f"{k} {v}" for k, v in sorted(result["outcomes"].items(), key=lambda kv: -kv[1]))
    )
    if result["errors"]:
        print(
            "错误分类："
            + "、".join(f"{k} {v}" for k, v in sorted(result["errors"].items(), key=lambda kv: -kv[1]))
        )

    if diff:
        if diff["regressions"]:
            print(
                f"\n⚠ 相对基线出现 {len(diff['regressions'])} 条回归："
                + "、".join(diff["regressions"][:10])
            )
        if diff["fixed"]:
            print(f"✓ 相对基线修复 {len(diff['fixed'])} 条：" + "、".join(diff["fixed"][:10]))
        if diff["new_cases"]:
            print(f"+ 新增用例 {len(diff['new_cases'])} 条")
        if not any(diff.values()):
            print("\n与基线完全一致")
    else:
        print("\n（没有基线，本次结果将作为基线）")

    if summary["failed"]:
        print("\n未通过明细（前 20 条）：")
        for item in result["failures"][:20]:
            print(f"  - {item['case_id']}：{'；'.join(item['reasons'])}")

    # 门禁模式是只读的：跑完就和基线比，不该顺手把基线改掉
    if not args.print and not args.check:
        write_json(result, args.baseline)
        print(f"\n基线已更新：{args.baseline.relative_to(ROOT)}")
    if args.write_report:
        DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_REPORT.write_text(render_markdown(result, diff), encoding="utf-8")
        print(f"报告：{DEFAULT_REPORT.relative_to(ROOT)}")

    if args.check:
        if diff and diff["regressions"]:
            return 1
        return 0 if summary["failed"] == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
