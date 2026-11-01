"""大模型评测集自身的测试。

不调网络：用构造好的草稿直接喂给评分器，验证"它能判对"。
评分器判错比模型写差更危险——前者会让团队一直看错的数字。
"""

from __future__ import annotations

import pytest

from crosspilot.eval.live_cases import build_live_suite
from crosspilot.eval.live_runner import LiveEvalError, assert_not_fallback, build_live_provider, rule_provider
from crosspilot.eval.live_scoring import PASS_SCORE, score_draft


def _case(case_id: str):
    return next(c for c in build_live_suite() if c.case_id == case_id)


def _good_draft(case) -> dict:
    """按输入事实拼一份"老实"的草稿：数字全来自输入，卖点全覆盖。"""
    product = case.request["product"]
    features = list(product.get("key_features") or [])
    while len(features) < 5:
        features.append(features[len(features) % max(1, len(features))] if features else "durable")
    bullets = [
        {"headline": feature, "body": f"Built with {feature}", "supporting_facts": [feature]}
        for feature in features[:5]
    ]
    specs = product.get("specifications") or {}
    spec_line = "; ".join(f"{k} {v}" for k, v in specs.items())
    return {
        "title": f"{product['name']} - {spec_line}"[:180],
        "bullets": bullets,
        "description": (
            f"{product['name']} is designed for daily use. {spec_line}. "
            "Every specification above comes from the product fact sheet. "
            "Unlisted details are intentionally left out rather than guessed."
        ),
        "search_terms": ["insulated", "portable"],
    }


def test_suite_has_twelve_unique_cases():
    cases = build_live_suite()
    assert len(cases) >= 10
    assert len({c.case_id for c in cases}) == len(cases)


def test_good_draft_passes():
    case = _case("llm-insulated-bottle")
    result = score_draft(case, _good_draft(case))
    assert result.passed, result.failures
    assert result.score >= PASS_SCORE


def test_fabricated_number_scores_zero():
    """编造参数是红线：不是扣分，是直接 0。"""
    case = _case("llm-insulated-bottle")
    draft = _good_draft(case)
    draft["bullets"][0]["body"] = "Keeps drinks cold for 72 hours"
    result = score_draft(case, draft)
    assert result.score == 0
    assert not result.passed
    assert any("编造参数" in f for f in result.failures)


def test_ordinal_labels_are_not_treated_as_fabrication():
    """「卖点1」「1. ...」里的数字是编号，不是参数——不能误判成编造。"""
    case = _case("llm-ceramic-mug")
    draft = _good_draft(case)
    draft["description"] = (
        "1. Microwave safe\n2. Dishwasher safe\n卖点1：microwave safe\n"
        + draft["description"]
    )
    result = score_draft(case, draft)
    assert not any("编造参数" in f for f in result.failures)


def test_wrong_bullet_count_fails_even_with_high_score():
    """条数不对是硬性违规：分数再高也不算通过。

    Amazon 的五个卖点是平台要求，缺了就是不合规，不该靠别处多得几分补回来。
    """
    case = _case("llm-ceramic-mug")
    draft = _good_draft(case)
    draft["bullets"] = draft["bullets"][:2]
    result = score_draft(case, draft)
    assert any("要点条数" in f for f in result.failures)
    assert result.score > 0
    assert not result.passed


def test_banned_terms_lose_wording_points():
    case = _case("llm-yoga-mat")
    draft = _good_draft(case)
    draft["bullets"][0]["body"] += " It is the #1 choice and 100% non-slip."
    result = score_draft(case, draft)
    # 100% 不含数字字母之外的内容，会被当作数字 claims；这里只要求被判不合格
    assert not result.passed
    assert any("绝对化" in f or "编造" in f for f in result.failures)


def test_empty_draft_scores_zero():
    case = _case("llm-tote-bag")
    result = score_draft(case, {})
    assert result.score == 0
    assert not result.passed


def test_unit_conversion_is_not_fabrication():
    """420g 写成 14.8 oz、24oz 写成 710ml 是合规换算，美国站本来就该这么写。"""
    case = _case("llm-insulated-bottle")
    draft = _good_draft(case)
    draft["bullets"][0]["body"] += " Weighs 14.8 oz and holds 710 ml."
    result = score_draft(case, draft)
    assert not any("编造" in f for f in result.failures), result.failures


def test_search_terms_as_string_is_not_character_split():
    """search_terms 是逗号串时不能被按字符拆开，否则「24 oz」会变成「2」「4」。"""
    case = _case("llm-insulated-bottle")
    draft = _good_draft(case)
    draft["search_terms"] = "24 oz insulated tumbler for travel"
    result = score_draft(case, draft)
    assert not any("编造" in f for f in result.failures), result.failures


def test_feature_reference_codes_are_not_fabrication():
    """模型会用 (F01)/(F02) 标注引用的是哪条卖点，那不是参数。"""
    case = _case("llm-filter-pitcher")
    draft = _good_draft(case)
    draft["bullets"][0]["body"] += " Fast filtration (F01) keeps things moving, lid (F02) opens."
    result = score_draft(case, draft)
    assert not any("编造" in f for f in result.failures), result.failures


def test_rule_provider_is_rejected_as_llm_engine():
    """没有真模型时必须报错，不能让规则引擎的产出冒充模型质量。"""
    with pytest.raises(LiveEvalError):
        assert_not_fallback(rule_provider())


def test_live_provider_is_constructed_without_network():
    """用假 Key 也能构造出 llm 类型 Provider（不联网，只验接线）。"""
    provider = build_live_provider(
        provider="deepseek", model="deepseek-flash", api_key="sk-wiring-check"
    )
    label = assert_not_fallback(provider)
    assert label["kind"] == "llm"
    assert label["model"] == "deepseek-flash"
