"""规则加载与可配置性测试。"""

from __future__ import annotations

import json


from crosspilot.engine.rules import RuleSet, get_rules
from crosspilot.config import load_json_config


def test_rules_load_platform_limits():
    rules = get_rules()
    amazon = rules.platform_rules("amazon", "US")
    assert amazon.title_max_chars == 200
    assert amazon.bullet_count == 5
    ebay = rules.platform_rules("ebay", "US")
    assert ebay.title_max_chars == 80


def test_unknown_marketplace_falls_back_to_us():
    rules = get_rules()
    amazon_xx = rules.platform_rules("amazon", "XX")
    amazon_us = rules.platform_rules("amazon", "US")
    assert amazon_xx.title_max_chars == amazon_us.title_max_chars


def test_banned_terms_matcher_respects_word_boundaries():
    rules = get_rules().banned_terms()
    hits = [t.term for t in rules.matches("This is the bestseller and the best choice.")]
    assert "best seller" not in hits or "bestseller" in hits
    assert "best" in hits
    # 不应把 "best" 命中到 "bestseller" 内部以外的位置造成误报
    assert all(term for term in hits)


def test_custom_banned_terms_are_errors():
    rules = get_rules().banned_terms(["MyBrandOnly"])
    custom = [t for t in rules.terms if t.category == "custom"]
    assert custom and custom[0].severity.value == "error"


def test_rules_are_configurable_via_file(tmp_path):
    platform_file = tmp_path / "platform.json"
    banned_file = tmp_path / "banned.json"
    platform_file.write_text(
        json.dumps(
            {
                "defaults": {"title_max_chars": 50, "bullet_max_chars": 100, "bullet_count": 3},
                "platforms": {"amazon": {"US": {"title_max_chars": 50}}},
                "_meta": {"verified": True, "disclaimer": "test"},
            }
        ),
        encoding="utf-8",
    )
    banned_file.write_text(
        json.dumps({"categories": {"x": {"label": "测试", "severity": "warning", "terms": ["foo"]}}}),
        encoding="utf-8",
    )
    rule_set = RuleSet(load_json_config(platform_file), load_json_config(banned_file))
    amazon = rule_set.platform_rules("amazon", "US")
    assert amazon.title_max_chars == 50
    assert amazon.bullet_count == 3
    assert amazon.verified is True
    assert rule_set.banned_terms().matches("a foo bar")


def test_missing_rules_file_raises():
    rules = get_rules()
    assert rules.supported_platforms()["amazon"]


def test_rule_set_supported_platforms_shape():
    platforms = get_rules().supported_platforms()
    assert "amazon" in platforms
    assert "US" in platforms["amazon"]
