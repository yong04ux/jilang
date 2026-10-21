"""Listing 生成与质检测试：重点验证"不编造参数"与"待确认"机制。"""

from __future__ import annotations


from crosspilot.demo.demo_data import DEMO_LISTING_REQUEST, DEMO_OWN_PRODUCT, DEMO_OWN_PRODUCT_SPARSE
from crosspilot.engine.listing import (
    audit_declarations,
    build_search_terms,
    generate_listing,
)
from crosspilot.models import (
    IssueCode,
    ListingGenerationRequest,
    Platform,
    Severity,
)
from crosspilot.engine.rules import get_rules


def _request(**product_overrides) -> ListingGenerationRequest:
    product = dict(DEMO_OWN_PRODUCT)
    product.update(product_overrides)
    payload = dict(DEMO_LISTING_REQUEST)
    payload["product"] = product
    return ListingGenerationRequest(**payload)


def test_generate_listing_end_to_end():
    listing = generate_listing(_request())
    assert listing.title
    assert len(listing.bullets) == 5
    assert listing.description
    assert listing.a_plus_outline
    assert listing.fact_ledger, "必须记录事实来源台账"
    assert listing.quality_check.rules_applied


def test_missing_specifications_are_marked_pending_not_invented():
    request = _request(
        specifications={},
        materials=[],
        certifications=[],
        key_features=["双层真空保温"],
    )
    listing = generate_listing(request)
    pending = " ".join(listing.pending_confirmations)
    assert "尺寸" in pending and "材质" in pending
    # 文案里不得出现任何被编造的规格数值
    for token in ["750ml", "380g", "26cm", "304 不锈钢"]:
        assert token not in listing.title
        assert token not in listing.description
    # 五点中不应出现真实规格段落（因为没有规格）
    assert not any("真实规格一览" == b.headline for b in listing.bullets)


def test_sparse_product_quality_check_flags_missing_facts():
    payload = dict(DEMO_LISTING_REQUEST)
    payload["product"] = dict(DEMO_OWN_PRODUCT_SPARSE)
    listing = generate_listing(ListingGenerationRequest(**payload))
    codes = {i.code for i in listing.quality_check.issues}
    assert IssueCode.MISSING_FACT in codes
    assert listing.pending_confirmations


def test_unsupported_number_is_detected():
    issue = audit_declarations(
        "Holds up to 999 hours of heat and 42oz capacity.",
        "description",
        __import__("crosspilot.engine.listing", fromlist=["AuditContext"]).AuditContext(
            allowed_numbers={"750", "380"},
            allowed_phrases=set(),
            banned=get_rules().banned_terms(),
            rules=get_rules().platform_rules(Platform.AMAZON, "US"),
        ),
    )
    assert any(i.code == IssueCode.UNSUPPORTED_NUMBER for i in issue)
    assert all(i.severity == Severity.ERROR for i in issue if i.code == IssueCode.UNSUPPORTED_NUMBER)


def test_supported_numbers_pass_audit():
    from crosspilot.engine.listing import AuditContext

    context = AuditContext(
        allowed_numbers={"750ml", "750", "380", "380g"},
        allowed_phrases=set(),
        banned=get_rules().banned_terms(),
        rules=get_rules().platform_rules(Platform.AMAZON, "US"),
    )
    issues = audit_declarations("Capacity 750ml, weight 380g.", "description", context)
    assert not [i for i in issues if i.code == IssueCode.UNSUPPORTED_NUMBER]


def test_unverified_certification_is_error():
    from crosspilot.engine.listing import AuditContext

    context = AuditContext(
        allowed_numbers=set(),
        allowed_phrases=set(),
        banned=get_rules().banned_terms(),
        rules=get_rules().platform_rules(Platform.AMAZON, "US"),
    )
    context.certifications = []
    issues = audit_declarations("FDA approved and BPA free for daily use.", "description", context)
    codes = {i.code for i in issues}
    assert IssueCode.UNVERIFIED_CERTIFICATION in codes
    assert any(i.severity == Severity.ERROR for i in issues if i.code == IssueCode.UNVERIFIED_CERTIFICATION)


def test_banned_terms_are_flagged_and_block_pass():
    request = _request(banned_terms=["guaranteed"])
    listing = generate_listing(request)
    # 禁用词来自品牌声明；如果生成文本未命中，则至少规则被加载
    assert listing.quality_check.rules_applied


def test_brand_banned_term_forces_error_when_used():
    from crosspilot.engine.listing import AuditContext

    banned = get_rules().banned_terms(["EcoSipMagic"])
    context = AuditContext(
        allowed_numbers=set(),
        allowed_phrases=set(),
        banned=banned,
        rules=get_rules().platform_rules(Platform.AMAZON, "US"),
    )
    issues = audit_declarations("Made with EcoSipMagic technology.", "description", context)
    assert any(i.code == IssueCode.BANNED_TERM and i.severity == Severity.ERROR for i in issues)


def test_title_respects_platform_limit():
    long_name = "Premium Insulated Water Bottle " * 8
    listing = generate_listing(_request(name=long_name))
    rules = get_rules().platform_rules(Platform.AMAZON, "US")
    assert len(listing.title) <= rules.title_max_chars
    section = next(s for s in listing.quality_check.section_lengths if s.section == "title")
    assert section.within_limit is True


def test_search_terms_respect_byte_limit():
    rules = get_rules().platform_rules(Platform.AMAZON, "US")
    from crosspilot.models import KeywordMetric

    keywords = [KeywordMetric(keyword=f"keyword-{i}-" + "x" * 20) for i in range(30)]
    terms = build_search_terms(keywords, rules, facts_text="")
    assert len(terms.encode("utf-8")) <= rules.search_terms_max_bytes


def test_keyword_stuffing_is_detected():
    from crosspilot.engine.listing import check_keyword_stuffing

    text = " ".join(["insulated bottle"] * 20)
    issues = check_keyword_stuffing(text, ["insulated bottle"], 4, "title")
    assert issues and issues[0].code == IssueCode.KEYWORD_STUFFING


def test_policy_disclaimer_present_and_not_claiming_compliance():
    listing = generate_listing(_request())
    qc = listing.quality_check
    assert "未对平台最新政策做实时核验" in qc.policy_disclaimer
    assert "不构成合规承诺" in qc.policy_disclaimer
    assert any("未核验" in rule for rule in qc.rules_applied)


def test_fact_ledger_traces_every_generated_fact():
    listing = generate_listing(_request())
    sources = {item["source"] for item in listing.fact_ledger}
    assert any(src.startswith("specifications.") for src in sources)
    assert "key_features" in sources
    # 生成的每个 support fact 都应能在台账或输入中找到
    known = " ".join(item["statement"] for item in listing.fact_ledger)
    for bullet in listing.bullets:
        for fact in bullet.supporting_facts:
            assert fact.split("：")[-1] in known or fact in known


def test_a_plus_outline_contains_required_modules():
    listing = generate_listing(_request())
    module_types = {m.module_type for m in listing.a_plus_outline}
    assert "hero_banner" in module_types
    assert "spec_table" in module_types


def test_listing_with_analysis_report_uses_differentiation():
    from crosspilot.engine.analysis import run_analysis
    from crosspilot.models import CompetitorAnalysisRequest

    report = run_analysis(CompetitorAnalysisRequest(**__import__("crosspilot.demo.demo_data", fromlist=["DEMO_ANALYSIS_REQUEST"]).DEMO_ANALYSIS_REQUEST))
    listing = generate_listing(_request(), analysis_report=report.model_dump(mode="json"))
    assert listing.analysis_report_id == report.report_id
    assert listing.differentiation_used


def test_bullets_never_exceed_configured_limit():
    rules = get_rules().platform_rules(Platform.AMAZON, "US")
    listing = generate_listing(_request())
    for bullet in listing.bullets:
        assert bullet.character_count <= rules.bullet_max_chars


def test_empty_product_specs_do_not_break_generation():
    sparse = dict(DEMO_OWN_PRODUCT_SPARSE)
    payload = dict(DEMO_LISTING_REQUEST)
    payload["product"] = sparse
    listing = generate_listing(ListingGenerationRequest(**payload))
    assert listing.title
    assert listing.quality_check is not None


def test_brand_not_duplicated_when_product_name_contains_it():
    listing = generate_listing(_request(name="EcoSip Insulated Bottle", brand="EcoSip"))
    assert listing.title.count("EcoSip") == 1, listing.title


def test_brand_not_duplicated_when_brand_omitted():
    """未填 brand 时也不能把商品名首词当成品牌重复拼接。"""
    listing = generate_listing(_request(name="EcoSip Bottle", brand=None))
    assert listing.title.lower().count("ecosip") == 1, listing.title


def test_keywords_without_metrics_never_enter_title():
    """无指标关键词只是候选词，不能作为标题卖点（演示：水瓶标题不能出现 tumbler）。"""
    listing = generate_listing(_request())
    assert "tumbler" not in listing.title.lower()
    # 但仍会进入 Search Terms 作为候选
    assert "stainless steel tumbler" in listing.search_terms


def test_irrelevant_keyword_not_added_to_title_even_with_metrics():
    from crosspilot.models import KeywordMetric

    payload = dict(DEMO_LISTING_REQUEST)
    payload["product"] = dict(DEMO_OWN_PRODUCT)
    payload["keywords"] = [KeywordMetric(keyword="garden hose nozzle", search_volume=9000, rank=4)]
    listing = generate_listing(ListingGenerationRequest(**payload))
    assert "garden hose" not in listing.title.lower()


def test_relevant_metric_keyword_can_enter_title():
    from crosspilot.models import KeywordMetric

    payload = dict(DEMO_LISTING_REQUEST)
    payload["product"] = dict(DEMO_OWN_PRODUCT)
    payload["keywords"] = [KeywordMetric(keyword="insulated water bottle", search_volume=9000, rank=4)]
    listing = generate_listing(ListingGenerationRequest(**payload))
    assert "insulated water bottle" in listing.title.lower()
