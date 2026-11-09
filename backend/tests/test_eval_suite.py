"""评测体系自身的测试。

评测是"丈量质量的那把尺子"，尺子本身必须被检验，否则它一直在量错的东西
而没人发现。这里测三类东西：

1. **规模与覆盖**：五个维度都在，用例数达到要求；
2. **确定性**：同一份代码两次生成的用例完全一致（否则基线无法比较）；
3. **断言真的会失败**：给一个伪造的坏结果，断言必须报错——
   只测"能通过"不测"能失败"，等于没测。
"""

from __future__ import annotations

from crosspilot.eval import DIMENSIONS, build_suite, check, suite_stats
from crosspilot.eval.assertions import BANNED_TERMS
from crosspilot.eval.cases import KIND_COMBINED, KIND_LISTING
from crosspilot.eval.known_issues import known_reason
from crosspilot.eval.report import build_result, compare


def test_suite_covers_all_dimensions_and_exceeds_200_cases():
    cases = build_suite()
    stats = suite_stats(cases)

    assert stats["total"] >= 200, f"用例只有 {stats['total']} 条，覆盖不足"
    for dimension in DIMENSIONS:
        assert stats.get(dimension, 0) >= 20, f"{dimension} 维度用例偏少：{stats.get(dimension, 0)}"


def test_suite_is_deterministic():
    """两次生成必须一模一样，否则 latest.json 没法逐条 diff。"""
    first = build_suite()
    second = build_suite()
    assert [c.case_id for c in first] == [c.case_id for c in second]
    assert all(a.payload == b.payload for a, b in zip(first, second))
    assert all(a.expect == b.expect for a, b in zip(first, second))
    assert len({c.case_id for c in first}) == len(first), "用例 id 有重复"


def _fake(observed: dict) -> dict:
    base = {
        "case_id": "",
        "dimension": "",
        "spec_kind": "",
        "plan": [],
        "steps": [],
        "outcome": "succeeded",
        "task_status": "succeeded",
        "paused": False,
        "paused_once": False,
        "pending": None,
        "report": {},
        "listing": {},
        "provenance": {},
        "error_code": "",
        "error_message": "",
        "duration_ms": 1,
    }
    base.update(observed)
    return base


def test_fact_check_flags_fabricated_number():
    """要点里出现事实中查不到的数字，必须被判为编造。"""
    case = next(
        c for c in build_suite() if c.dimension == "fact_consistency" and c.kind == KIND_LISTING
    )
    observed = _fake(
        {
            "case_id": case.case_id,
            "dimension": case.dimension,
            "spec_kind": case.kind,
            "plan": ["validate", "dispatch", "finalize"],
            "listing": {
                "title": "Stainless Steel Bottle",
                "bullets": [
                    {
                        "headline": "保温 72 小时",
                        "body": "实测 72 小时仍保持冰温",
                        "supporting_facts": ["卖点1：双层真空保温"],
                    }
                ],
                "fact_ledger": [{"fact": "双层真空保温"}],
                "data_provenance": {"is_demo": True, "data_source": "demo"},
            },
            "provenance": {"is_demo": True},
        }
    )
    failures = check(case, observed)
    assert any("72" in f for f in failures), failures


def test_fact_check_flags_bullets_without_supporting_facts():
    case = next(
        c for c in build_suite() if c.dimension == "fact_consistency" and c.kind == KIND_LISTING
    )
    observed = _fake(
        {
            "case_id": case.case_id,
            "dimension": case.dimension,
            "spec_kind": case.kind,
            "plan": ["validate", "dispatch", "finalize"],
            "listing": {
                "title": "Stainless Steel Bottle",
                "bullets": [{"headline": "耐用", "body": "很耐用", "supporting_facts": []}],
                "fact_ledger": [{"fact": "材质"}],
                "data_provenance": {"is_demo": True},
            },
            "provenance": {"is_demo": True},
        }
    )
    assert any("没有引用事实" in f for f in check(case, observed))


def test_fact_check_flags_banned_terms():
    case = next(
        c for c in build_suite() if c.dimension == "fact_consistency" and c.kind == KIND_LISTING
    )
    term = BANNED_TERMS[0]
    observed = _fake(
        {
            "case_id": case.case_id,
            "dimension": case.dimension,
            "spec_kind": case.kind,
            "plan": ["validate", "dispatch", "finalize"],
            "listing": {
                "title": f"Our {term} bottle",
                "bullets": [{"headline": "好", "body": "好", "supporting_facts": ["卖点1"]}],
                "fact_ledger": [{"fact": "卖点1"}],
                "data_provenance": {"is_demo": True},
            },
            "provenance": {"is_demo": True},
        }
    )
    assert any("绝对化用语" in f for f in check(case, observed))


def test_tool_call_check_flags_wrong_workflow_and_extra_node():
    case = next(c for c in build_suite() if c.dimension == "tool_call" and c.kind == KIND_COMBINED)
    observed = _fake(
        {
            "case_id": case.case_id,
            "dimension": case.dimension,
            "spec_kind": "competitor",  # 分派错了
            "plan": ["validate", "dispatch", "validate_request", "finalize"],
            "steps": [{"node": "不存在的节点"}],
        }
    )
    failures = check(case, observed)
    assert any("分派错误" in f for f in failures)
    assert any("计划外" in f for f in failures)


def test_routing_check_flags_missing_forbidden_and_wrong_switch():
    """路由尺子也要能判错：漏选、误选、开关不对都必须报出来。"""
    case = next(
        c for c in build_suite() if c.dimension == "routing" and c.expect["mode"] == "auto"
    )
    observed = _fake(
        {
            "case_id": case.case_id,
            "dimension": case.dimension,
            "spec_kind": "auto",
            "routing": {
                "mode": "auto",
                "skill_keys": ["data_validation"],
                "with_listing": True,
                "listing_only": True,
            },
        }
    )
    failures = check(case, observed)
    assert any("漏选" in f for f in failures), failures
    assert any("误选" in f for f in failures), failures
    assert any("with_listing" in f for f in failures), failures


def test_recovery_check_flags_swallowed_fault():
    case = next(c for c in build_suite() if c.dimension == "recovery" and c.fault)
    observed = _fake(
        {
            "case_id": case.case_id,
            "dimension": case.dimension,
            "spec_kind": case.kind,
            "plan": ["validate", "dispatch", "finalize"],
            "outcome": "succeeded",  # 注入的故障被吞了
            "error_code": "",
        }
    )
    assert any("故障被吞掉" in f or "错误分类" in f for f in check(case, observed))


def test_known_issue_matching_is_narrow():
    """已知问题只命中登记过的那一格，不按前缀大范围放过。"""
    cases = build_suite()
    specs_only = next(
        c for c in cases if "specs_only" in c.case_id and c.dimension == "fact_consistency"
    )
    observed = _fake({"listing": {}, "outcome": "succeeded"})
    assert known_reason(specs_only, observed)

    # 同样带 specs_only，但维度不同 → 不该被放过
    other = next(
        c for c in cases if "specs_only" in c.case_id and c.dimension == "tool_call"
    )
    assert known_reason(other, observed) == ""


def test_report_detects_regressions():
    case = next(c for c in build_suite() if c.dimension == "tool_call")
    observed = _fake(
        {"case_id": case.case_id, "dimension": case.dimension, "spec_kind": case.kind}
    )
    baseline = build_result([case], [observed], [[]])
    current = build_result([case], [observed], [["某条断言挂了"]])

    diff = compare(baseline, current)
    assert diff["regressions"] == [case.case_id]

    reverse = compare(current, baseline)
    assert reverse["fixed"] == [case.case_id]
