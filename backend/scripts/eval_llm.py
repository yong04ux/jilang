"""调用大模型的评测 CLI。

    # 真模型（Key 走参数或环境变量）
    python -m scripts.eval_llm --provider deepseek --model deepseek-flash \
        --api-key $SURGE_EVAL_API_KEY --repeats 3

    # 干跑：用规则引擎验证评测链路本身（不代表模型质量）
    python -m scripts.eval_llm --dry-run --repeats 1

环境变量（参数优先）：``SURGE_EVAL_PROVIDER`` / ``_MODEL`` / ``_API_KEY`` / ``_BASE_URL``

产物：``examples/eval/llm-latest.json``（含逐用例分数与波动，可入库做趋势）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "examples" / "eval" / "llm-latest.json"


def _markdown(result: dict) -> str:
    summary = result["summary"]
    lines = [
        "# 大模型评测报告",
        "",
        f"- 生成时间：{result['generated_at']}",
        f"- 引擎：{result['engine']}",
        f"- 用例：{summary['cases']} 条 × {result['repeats']} 次 = {summary['runs']} 次调用",
        f"- 平均分 **{summary['mean_score']}** · 最差 {summary['worst_score']} · "
        f"分数波动均值 {summary['mean_spread']}",
        f"- 单次通过率 {summary['run_pass_rate'] * 100:.1f}% · "
        f"稳定通过率（每次都过）{summary['stable_pass_rate'] * 100:.1f}%",
        f"- p50 延迟 {summary['p50_ms']} ms · 总 token {summary['tokens']}",
        "",
        "## 逐用例",
        "",
        "| 用例 | 次数 | 通过 | 均分 | 最差 | 波动 | p50(ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result["cases"]:
        lines.append(
            f"| {row['title']} | {row['runs']} | {row['passed']}/{row['runs']} | "
            f"{row['mean_score']} | {row['min_score']} | {row['score_spread']} | {row['p50_ms']} |"
        )

    broken = [row for row in result["cases"] if row["failures"] or row["errors"]]
    if broken:
        lines += ["", "## 未达标明细", ""]
        for row in broken:
            reasons = "；".join([*row["failures"], *row["errors"]])
            lines.append(f"- **{row['title']}**（均分 {row['mean_score']}）：{reasons}")

    lines += [
        "",
        "> 评分口径：事实可追溯 30 / 结构完整 25 / 卖点覆盖 20 / 格式合规 15 / 用语克制 10，",
        "> 75 分及格。**编造参数直接判 0**——不设部分分。",
        "> 单次结果会波动，请以「稳定通过率」（每次都过）与「分数波动」为准，不要看一次的成绩。",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="大模型写作质量评测（Listing）")
    parser.add_argument("--provider", default=os.environ.get("SURGE_EVAL_PROVIDER", ""))
    parser.add_argument("--model", default=os.environ.get("SURGE_EVAL_MODEL", ""))
    parser.add_argument("--api-key", default=os.environ.get("SURGE_EVAL_API_KEY", ""))
    parser.add_argument("--base-url", default=os.environ.get("SURGE_EVAL_BASE_URL", ""))
    parser.add_argument("--repeats", type=int, default=3, help="每条用例重复次数（默认 3）")
    parser.add_argument("--only", default="", help="只跑某个 case_id 前缀")
    parser.add_argument("--dry-run", action="store_true", help="用规则引擎干跑，验证链路")
    parser.add_argument("--print", action="store_true", help="只打印，不写结果文件")
    parser.add_argument("--write-report", action="store_true", help="额外生成 docs/eval-llm-report.md")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    from surge.eval.live_cases import build_live_suite
    from surge.eval.live_runner import (
        LiveEvalError,
        assert_not_fallback,
        build_live_provider,
        rule_provider,
        run_case,
        summarize,
    )

    cases = build_live_suite()
    if args.only:
        cases = [c for c in cases if c.case_id.startswith(args.only)]
        if not cases:
            print(f"没有匹配 {args.only} 的用例", file=sys.stderr)
            return 2

    if args.dry_run:
        provider = rule_provider()
        engine = "dry-run（规则引擎，仅验证链路，不代表模型质量）"
    else:
        if not (args.provider and args.model and args.api_key):
            print(
                "缺少模型凭据：需要 --provider / --model / --api-key，"
                "或设置 SURGE_EVAL_PROVIDER / _MODEL / _API_KEY。\n"
                "只想验证评测链路可以加 --dry-run。",
                file=sys.stderr,
            )
            return 2
        provider = build_live_provider(
            provider=args.provider,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
        )
        try:
            label = assert_not_fallback(provider)
        except LiveEvalError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        engine = label["label"]

    print(f"引擎：{engine}")
    print(f"用例：{len(cases)} 条 × {args.repeats} 次\n")

    rows = []
    for index, case in enumerate(cases, start=1):
        row = run_case(case, provider, args.repeats)
        rows.append(row)
        mark = "PASS" if row["runs"] and row["passed"] == row["runs"] else "WARN"
        print(
            f"[{index:>2}/{len(cases)}] [{mark}] {case.case_id:<28} "
            f"均分 {row['mean_score']:>3} 最差 {row['min_score']:>3} "
            f"波动 {row['score_spread']:>3} {row['p50_ms']:>6}ms"
        )
        for failure in row["failures"][:3]:
            print(f"           - {failure}")

    summary = summarize(rows)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": engine,
        "provider": args.provider or ("rule" if args.dry_run else ""),
        "model": args.model,
        "repeats": args.repeats,
        "summary": summary,
        "cases": rows,
    }

    print(
        f"\n平均分 {summary['mean_score']}（最差 {summary['worst_score']}），"
        f"波动均值 {summary['mean_spread']}"
    )
    print(
        f"单次通过率 {summary['run_pass_rate'] * 100:.1f}% · "
        f"稳定通过率 {summary['stable_pass_rate'] * 100:.1f}% · "
        f"p50 {summary['p50_ms']}ms · 总 token {summary['tokens']}"
    )

    if not args.print:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n结果：{args.out.relative_to(ROOT)}")
    if args.write_report:
        report = ROOT / "docs" / "eval-llm-report.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(_markdown(result), encoding="utf-8")
        print(f"报告：{report.relative_to(ROOT)}")

    if args.dry_run:
        # 干跑只验证评测链路本身；规则引擎写不出 5 条要点，分数天然不达标
        print(
            "\n（干跑：以上分数来自规则引擎，只证明评测链路可用，不代表任何模型的质量）"
        )
        return 0
    return 0 if summary["stable_pass_rate"] >= 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
