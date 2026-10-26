"""Listing（LLM + 事实接地）测试。

全部使用假的 LLM 客户端，不消耗真实额度；同时覆盖无 Key 降级路径。
"""

from __future__ import annotations

import pytest

from crosspilot.demo.demo_data import DEMO_LISTING_REQUEST, DEMO_OWN_PRODUCT, DEMO_OWN_PRODUCT_SPARSE
from crosspilot.engine.facts import FactKind, build_fact_sheet
from crosspilot.engine.listing_llm import audit_claim, generate_listing, rule_fallback
from crosspilot.llm.llm import Usage, normalize_model, parse_json_response
from crosspilot.market.marketplaces import get_marketplace
from crosspilot.models import IssueCode, ListingGenerationRequest, OwnProduct, Severity
from crosspilot.engine.rules import get_rules


class FakeClient:
    def __init__(self, payload, usage=None):
        self.payload = payload
        self.usage = usage or Usage(900, 500, 1400, 1)
        self.calls = 0

    def chat_json(self, messages, **kwargs):
        self.calls += 1
        return self.payload, type("R", (), {"usage": self.usage, "model": "fake"})()


def _request(**overrides) -> ListingGenerationRequest:
    payload = dict(DEMO_LISTING_REQUEST)
    product = dict(DEMO_OWN_PRODUCT)
    product.update(overrides.pop("product", {}))
    payload["product"] = product
    payload.update(overrides)
    return ListingGenerationRequest(**payload)


GOOD = {
    "title": "EcoSip 750ml Insulated Water Bottle - Double-Wall Vacuum, 304 Stainless Steel",
    "bullets": [
        {
            "headline": "Cold for 24 Hours",
            "body": "Double-wall vacuum insulation keeps drinks cold for 24 hours on long commutes.",
            "fact_ids": ["F01"],
        },
        {
            "headline": "Seamless Liner",
            "body": "The one-piece inner liner leaves no seams where residue collects.",
            "fact_ids": ["F02"],
        },
        {
            "headline": "Wide Mouth",
            "body": "A wide opening takes standard ice cubes and makes rinsing quick.",
            "fact_ids": ["F03"],
        },
        {
            "headline": "Leak-Resistant Seal",
            "body": "A silicone gasket tested through 500 open-close cycles helps keep the lid closed.",
            "fact_ids": ["F04"],
        },
        {
            "headline": "Light Enough to Carry",
            "body": "At 380g and 26cm tall it slips into a backpack side pocket.",
            "fact_ids": ["S01", "S02"],
        },
    ],
    "description": (
        "EcoSip is made for commuters and gym sessions. The 750ml bottle uses 304 stainless steel, "
        "and double-wall vacuum insulation keeps cold drinks cold for 24 hours. A silicone gasket "
        "tested through 500 open-close cycles helps keep the lid shut in a bag."
    ),
    "search_terms": "travel bottle gym flask",
    "a_plus": [
        {
            "module_type": "hero_banner",
            "title": "Cold water all day",
            "content_outline": ["750ml double-wall bottle"],
            "assets_needed": ["hero shot"],
            "fact_ids": ["F01"],
        }
    ],
    "used_fact_ids": ["F01", "F02", "F03", "F04", "S01", "S02"],
    "notes": "",
}


# ---------------------------------------------------------------------------
# 事实层
# ---------------------------------------------------------------------------


def test_fact_sheet_extracts_typed_facts_with_stable_ids():
    sheet = build_fact_sheet(OwnProduct(**DEMO_OWN_PRODUCT))
    assert sheet.count > 0
    kinds = {f.kind for f in sheet.facts}
    assert FactKind.BRAND in kinds
    assert FactKind.ATTRIBUTE in kinds
    assert FactKind.FEATURE in kinds
    # ID 按类别连续编号
    feature_ids = [f.fact_id for f in sheet.of_kind(FactKind.FEATURE)]
    assert feature_ids == ["F01", "F02", "F03", "F04"]
    # 每条事实都有来源
    assert all(f.source for f in sheet.facts)


def test_fact_sheet_records_missing_critical_attributes():
    sheet = build_fact_sheet(OwnProduct(**DEMO_OWN_PRODUCT_SPARSE))
    assert "size" in sheet.missing_critical
    assert "material" in sheet.missing_critical
    assert "capacity" in sheet.missing_critical


def test_fact_sheet_warns_when_certification_words_lack_certificates():
    product = dict(DEMO_OWN_PRODUCT)
    product["certifications"] = []
    product["key_features"] = ["食品级 304 不锈钢内胆"]
    sheet = build_fact_sheet(OwnProduct(**product))
    assert any("证书" in w for w in sheet.warnings)


def test_fact_numbers_are_collected_for_auditing():
    sheet = build_fact_sheet(OwnProduct(**DEMO_OWN_PRODUCT))
    numbers = sheet.allowed_numbers()
    assert "750" in numbers
    assert "380" in numbers


# ---------------------------------------------------------------------------
# LLM 生成
# ---------------------------------------------------------------------------


def test_generate_with_fake_llm_produces_target_language_listing():
    client = FakeClient(GOOD)
    draft = generate_listing(_request(), client=client, engine="deepseek")
    assert draft.language == "en-US"
    assert draft.marketplace == "US"
    assert "EcoSip" in draft.title
    assert len(draft.bullets) == 5
    assert draft.engine == "deepseek"
    # 英文文案不应混入中文
    assert not any("\u4e00" <= c <= "\u9fff" for c in draft.title)
    assert "750ml" in draft.description


def test_generated_listing_has_fact_ledger_with_ids():
    draft = generate_listing(_request(), client=FakeClient(GOOD), engine="deepseek")
    assert draft.fact_ledger
    assert all("fact_id" in item for item in draft.fact_ledger)
    assert all(item["source"] for item in draft.fact_ledger)


def test_bullet_supporting_facts_trace_back_to_ledger():
    draft = generate_listing(_request(), client=FakeClient(GOOD), engine="deepseek")
    ledger_statements = " ".join(item["statement"] for item in draft.fact_ledger)
    traced = [b for b in draft.bullets if b.supporting_facts]
    assert traced, "至少要有可追溯的事实支撑"
    for bullet in traced:
        for fact in bullet.supporting_facts:
            assert fact in ledger_statements


def test_fabricated_number_is_rejected():
    bad = dict(GOOD)
    bad["title"] = "EcoSip 1000ml Insulated Bottle"
    draft = generate_listing(_request(), client=FakeClient(bad), engine="deepseek")
    assert draft.quality_check.passed is False
    codes = {i.code for i in draft.quality_check.issues}
    assert IssueCode.UNSUPPORTED_NUMBER in codes
    assert any("1000" in i.message for i in draft.quality_check.issues)


def test_fabricated_certification_is_rejected():
    bad = dict(GOOD)
    bad["description"] = GOOD["description"] + " FDA approved and BPA free."
    draft = generate_listing(_request(), client=FakeClient(bad), engine="deepseek")
    codes = {i.code for i in draft.quality_check.issues}
    assert IssueCode.UNVERIFIED_CERTIFICATION in codes
    assert draft.quality_check.passed is False


def test_health_claim_is_rejected():
    bad = dict(GOOD)
    bad["description"] = GOOD["description"] + " This bottle kills 99% of bacteria."
    draft = generate_listing(_request(), client=FakeClient(bad), engine="deepseek")
    codes = {i.code for i in draft.quality_check.issues}
    assert IssueCode.UNVERIFIED_EFFICACY in codes


def test_absolute_claim_is_warning_not_error():
    bad = dict(GOOD)
    bad["bullets"] = list(GOOD["bullets"])
    bad["bullets"][0] = {**bad["bullets"][0], "body": "The best bottle you will ever own."}
    draft = generate_listing(_request(), client=FakeClient(bad), engine="deepseek")
    superlatives = [i for i in draft.quality_check.issues if i.code == IssueCode.UNSUPPORTED_SUPERLATIVE]
    assert superlatives
    assert all(i.severity == Severity.WARNING for i in superlatives)


def test_reach_and_prevent_are_not_false_positives():
    """'reach the bottom' 与 'prevent leaks' 属于正常描述，不应报认证/功效错误。"""
    sheet = build_fact_sheet(OwnProduct(**DEMO_OWN_PRODUCT))
    issues = audit_claim(
        "A bottle brush can reach the bottom, and the gasket helps prevent leaks.",
        sheet,
        banned=get_rules().banned_terms(),
        location="description",
    )
    codes = {i.code for i in issues}
    assert IssueCode.UNVERIFIED_CERTIFICATION not in codes
    assert IssueCode.UNVERIFIED_EFFICACY not in codes


def test_chinese_text_in_english_listing_is_error():
    bad = dict(GOOD)
    bad["title"] = "EcoSip 保温杯 750ml Insulated Water Bottle 双层真空保温"
    draft = generate_listing(_request(), client=FakeClient(bad), engine="deepseek")
    assert draft.quality_check.passed is False


def test_missing_specs_are_pending_and_not_invented():
    payload = dict(DEMO_LISTING_REQUEST)
    payload["product"] = dict(DEMO_OWN_PRODUCT_SPARSE)
    request = ListingGenerationRequest(**payload)
    # 即使模型"编"了规格，也要被质检拦下
    bad = dict(GOOD)
    bad["title"] = "EcoSip 750ml Bottle - 304 Stainless Steel"
    draft = generate_listing(request, client=FakeClient(bad), engine="deepseek")
    assert draft.pending_confirmations
    assert any("尺寸" in p or "材质" in p for p in draft.pending_confirmations)
    codes = {i.code for i in draft.quality_check.issues}
    assert IssueCode.UNSUPPORTED_NUMBER in codes


def test_search_terms_respect_byte_limit():
    payload = dict(DEMO_LISTING_REQUEST)
    payload["keywords"] = [{"keyword": "very long keyword phrase " + "x" * 20} for _ in range(20)]
    request = ListingGenerationRequest(**payload)
    draft = generate_listing(request, client=FakeClient(GOOD), engine="deepseek")
    limit = get_marketplace("US").search_terms_max_bytes
    assert len(draft.search_terms.encode("utf-8")) <= limit


def test_title_respects_marketplace_limit():
    bad = dict(GOOD)
    bad["title"] = "EcoSip " + "Insulated Water Bottle " * 12
    draft = generate_listing(_request(), client=FakeClient(bad), engine="deepseek")
    assert len(draft.title) <= get_marketplace("US").title_max_chars


def test_japanese_marketplace_uses_japanese_language():
    request = _request(marketplace="JP")
    ja = dict(GOOD)
    ja["title"] = "EcoSip 750ml 真空断熱ウォーターボトル"
    ja["description"] = "二重真空断熱構造で冷たい飲み物を24時間キープします。"
    draft = generate_listing(request, client=FakeClient(ja), engine="deepseek")
    assert draft.language == "ja-JP"
    assert draft.marketplace == "JP"
    assert "750ml" in draft.title


def test_usage_is_reported_in_limitations():
    draft = generate_listing(_request(), client=FakeClient(GOOD), engine="deepseek")
    assert any("tokens" in item for item in draft.limitations)


# ---------------------------------------------------------------------------
# 降级
# ---------------------------------------------------------------------------


def test_no_client_falls_back_without_fabrication():
    draft = generate_listing(_request(), client=None)
    assert draft.engine == "rule-fallback"
    assert draft.quality_check.passed is False  # 降级结果不允许标记为通过
    assert any("降级" in r for r in draft.quality_check.rules_applied)
    # 不应出现事实中不存在的数字
    allowed = build_fact_sheet(OwnProduct(**DEMO_OWN_PRODUCT)).allowed_numbers()
    import re

    for number in re.findall(r"\d+(?:\.\d+)?", draft.title):
        assert number in allowed


def test_fallback_does_not_duplicate_brand():
    draft = generate_listing(_request(), client=None)
    assert draft.title.lower().count("ecosip") == 1


def test_fallback_avoids_mixing_chinese_into_english_title():
    """中文资料 + 英文站点时，降级标题不得出现中文规格。"""
    payload = dict(DEMO_LISTING_REQUEST)
    payload["product"] = dict(DEMO_OWN_PRODUCT_SPARSE)
    draft = generate_listing(ListingGenerationRequest(**payload), client=None)
    assert not any("\u4e00" <= c <= "\u9fff" for c in draft.title)


def test_rule_fallback_function_marks_pending():
    product = OwnProduct(**DEMO_OWN_PRODUCT_SPARSE)
    sheet = build_fact_sheet(product)
    content = rule_fallback(_request(product=DEMO_OWN_PRODUCT_SPARSE), sheet, get_marketplace("US"))
    assert "未调用模型" in content.notes


# ---------------------------------------------------------------------------
# LLM 工具
# ---------------------------------------------------------------------------


def test_model_alias_normalization():
    # 官方文档的当前模型名是 deepseek-flash / deepseek-v4-pro
    assert normalize_model("deepseek-chat") == "deepseek-flash"
    assert normalize_model("deepseek-flash") == "deepseek-flash"
    assert normalize_model("deepseek-v4-pro") == "deepseek-v4-pro"
    # 退役旧名要能收敛回来，否则老配置保存后直接报「模型不存在」
    assert normalize_model("deepseek-v4-flash") == "deepseek-flash"
    assert normalize_model("") == "deepseek-flash"
    # 非 DeepSeek 的模型名原样放行，不能被别名表改写
    assert normalize_model("gpt-4o-mini") == "gpt-4o-mini"


def test_parse_json_strips_code_fence():
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_rejects_non_object():
    from crosspilot.llm.llm import LLMError

    with pytest.raises(LLMError):
        parse_json_response("[1, 2, 3]")


def test_parse_json_recovers_trailing_text():
    assert parse_json_response('{"a": 1} 希望有帮助') == {"a": 1}


# ---------------------------------------------------------------------------
# 质检补齐：缺关键事实、占位符
# ---------------------------------------------------------------------------


def test_missing_critical_specs_are_reported_in_quality_check():
    """缺关键规格时，LLM 路径也必须给出 missing_fact，而不是静默通过。"""
    draft = generate_listing(
        _request(product={"specifications": {}}), client=FakeClient(GOOD), engine="deepseek"
    )
    codes = {issue.code for issue in draft.quality_check.issues}
    assert IssueCode.MISSING_FACT in codes
    assert draft.pending_confirmations


def test_placeholder_text_is_an_error():
    """模型残留 [Brand] / {product_name} 时必须报错，不能当作可发布文案。"""
    payload = dict(GOOD)
    payload["title"] = "[Brand] 750ml Insulated Water Bottle"
    draft = generate_listing(_request(), client=FakeClient(payload), engine="deepseek")
    codes = {issue.code for issue in draft.quality_check.issues}
    assert IssueCode.PLACEHOLDER_TEXT in codes
    assert draft.quality_check.passed is False


def test_legitimate_bracketed_text_is_not_flagged():
    """合法文案（如 [2-Pack]）不应被占位符规则误伤。"""
    payload = dict(GOOD)
    payload["title"] = "EcoSip 750ml [2-Pack] Insulated Water Bottle"
    draft = generate_listing(_request(), client=FakeClient(payload), engine="deepseek")
    codes = {issue.code for issue in draft.quality_check.issues}
    assert IssueCode.PLACEHOLDER_TEXT not in codes
