"""竞品分析 Agent（规则引擎实现，可被 LLM Provider 增强）。

流水线：
1. ``validate_request``  —— 校验输入与必需字段
2. ``normalize``         —— 规范化竞品/评论/关键词
3. ``analyze_features``  —— 核心卖点与价格差异
4. ``analyze_reviews``   —— 高频需求、痛点、负面反馈、购买顾虑
5. ``analyze_keywords``  —— 仅在存在指标时计算机会分
6. ``compare_own``       —— 自有商品 vs 竞品差异
7. ``build_report``      —— 组装带证据分级的结构化报告

所有结论都携带 ``EvidenceKind``：fact / statistic / inference / assumption。
没有数据时宁可不输出数字，也不做任何编造。
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import mean, median

from .lexicon import CONCERN_THEMES, NEED_THEMES, PAIN_THEMES, Theme, themes_of
from ..models import (
    AnalysisReport,
    Claim,
    CompetitorAnalysisRequest,
    CompetitorProduct,
    ContentRecommendation,
    DataProvenance,
    DifferentiationOpportunity,
    EvidenceKind,
    EvidenceRef,
    FeatureComparison,
    KeywordAnalysis,
    KeywordMetric,
    KeywordOpportunity,
    PainPoint,
    PriceAnalysis,
    ProductSnapshot,
    ReviewInsights,
    ReviewSample,
    normalize_text,
)
from .textutils import contains_cjk as _contains_cjk, quote, split_sentences, top_terms

MAX_SAMPLES_PER_THEME = 3
MAX_REPORT_QUOTE = 160


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------


@dataclass
class ValidationOutcome:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_request(request: CompetitorAnalysisRequest) -> ValidationOutcome:
    """校验必需字段并收集数据质量警告。"""
    outcome = ValidationOutcome()
    if not request.competitors:
        outcome.errors.append("至少需要 1 个竞品才能进行分析")
        return outcome

    seen_names: Counter[str] = Counter()
    for index, competitor in enumerate(request.competitors, start=1):
        label = f"竞品 #{index}（{competitor.name}）"
        seen_names[competitor.name.lower()] += 1
        if competitor.price is None:
            outcome.warnings.append(f"{label} 缺少价格，价格分析将排除该竞品")
        if competitor.rating is None and competitor.review_count is None:
            outcome.warnings.append(f"{label} 缺少评分与评论数，可信度对比将不完整")
        if not competitor.key_features:
            outcome.warnings.append(f"{label} 没有提供核心卖点，卖点对比将不完整")
        if not competitor.reviews:
            outcome.warnings.append(f"{label} 没有评论样本，评论洞察将不覆盖该竞品")
        for review_index, review in enumerate(competitor.reviews):
            if not normalize_text(review.text):
                outcome.errors.append(f"{label} 的第 {review_index + 1} 条评论为空")
    duplicates = [name for name, count in seen_names.items() if count > 1]
    if duplicates:
        outcome.warnings.append(f"存在同名竞品，请确认是否为重复录入: {', '.join(duplicates)}")
    if request.total_review_count() == 0:
        outcome.warnings.append("没有任何评论样本，评论痛点/需求分析将不可用")
    if not request.own_specs:
        outcome.warnings.append("自有商品未填写规格，差异化分析将只基于卖点与价格")
    if request.keywords and all(not k.has_metrics for k in request.keywords):
        outcome.warnings.append("关键词均无搜索量/排名指标，不做关键词机会打分")
    return outcome


# ---------------------------------------------------------------------------
# 规范化
# ---------------------------------------------------------------------------


@dataclass
class NormalizedData:
    competitors: list[CompetitorProduct]
    reviews: list[tuple[str, ReviewSample]]
    keywords: list[KeywordMetric]
    warnings: list[str] = field(default_factory=list)


def normalize(request: CompetitorAnalysisRequest) -> NormalizedData:
    competitors: list[CompetitorProduct] = []
    reviews: list[tuple[str, ReviewSample]] = []
    warnings: list[str] = []

    for competitor in request.competitors:
        cleaned_features = [f.strip() for f in competitor.key_features if f.strip()]
        cleaned_specs = {
            k.strip(): v.strip() for k, v in competitor.specifications.items() if k.strip() and v.strip()
        }
        cleaned_reviews: list[ReviewSample] = []
        for review in competitor.reviews:
            text = normalize_text(review.text)
            if not text:
                continue
            cleaned_reviews.append(
                review.model_copy(
                    update={
                        "text": text,
                        "title": normalize_text(review.title),
                        "source": review.source or request.data_source,
                    }
                )
            )
            reviews.append((competitor.name, cleaned_reviews[-1]))
        if len(cleaned_features) != len(competitor.key_features):
            warnings.append(f"{competitor.name} 的卖点中存在空值，已忽略")
        competitors.append(
            competitor.model_copy(
                update={
                    "key_features": cleaned_features,
                    "specifications": cleaned_specs,
                    "reviews": cleaned_reviews,
                }
            )
        )

    # 关键词去重（保留首个，来源不同则提示）
    seen_keywords: dict[str, KeywordMetric] = {}
    duplicate_keywords: list[str] = []
    for keyword in request.keywords:
        key = keyword.keyword.lower()
        if key in seen_keywords:
            duplicate_keywords.append(keyword.keyword)
            continue
        seen_keywords[key] = keyword
    if duplicate_keywords:
        warnings.append(f"重复关键词已去重: {', '.join(sorted(set(duplicate_keywords)))}")

    return NormalizedData(
        competitors=competitors,
        reviews=reviews,
        keywords=list(seen_keywords.values()),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _data_completeness(competitor: CompetitorProduct) -> tuple[float, list[str]]:
    checks = {
        "price": competitor.price is not None,
        "rating": competitor.rating is not None,
        "review_count": competitor.review_count is not None,
        "key_features": bool(competitor.key_features),
        "specifications": bool(competitor.specifications),
        "reviews": bool(competitor.reviews),
        "brand": competitor.brand is not None,
    }
    missing = [name for name, filled in checks.items() if not filled]
    return round(sum(checks.values()) / len(checks), 3), missing


def _review_ref(competitor: str, review: ReviewSample, index: int, data_source: str) -> EvidenceRef:
    return EvidenceRef(
        competitor=competitor,
        field="reviews",
        quote=quote(review.text, MAX_REPORT_QUOTE),
        review_index=index,
        data_source=review.source or data_source,
    )


def _theme_matcher(theme: Theme):
    compiled = [re.compile(p, re.IGNORECASE) for p in theme.patterns]
    return compiled


# ---------------------------------------------------------------------------
# 评论分析
# ---------------------------------------------------------------------------

_THEME_COMPILED: dict[str, list[re.Pattern[str]]] = {}
for _theme in PAIN_THEMES + NEED_THEMES + CONCERN_THEMES:
    _THEME_COMPILED[_theme.key] = _theme_matcher(_theme)

# 简单的否定与转折判断，避免把 "not bad" / "isn't loud" 误判为负面
_NEGATION_RE = re.compile(
    r"\b(?:not|isn't|isnt|aren't|arent|wasn't|wasnt|weren't|werent|no|never|hardly)\b",
    re.IGNORECASE,
)
_CONTRAST_RE = re.compile(
    r"\b(?:but|however|although|though|except|wish|unfortunately|only problem|downside)\b",
    re.IGNORECASE,
)


def _is_negated(sentence: str, match_start: int, window: int = 24) -> bool:
    prefix = sentence[max(0, match_start - window): match_start]
    return bool(_NEGATION_RE.search(prefix))


@dataclass
class ThemeHit:
    theme: Theme
    competitor: str
    review: ReviewSample
    review_index: int
    sentence: str


def match_themes(
    reviews: list[tuple[str, ReviewSample]],
    kind: str,
    *,
    negative_context_only: bool = False,
) -> list[ThemeHit]:
    """在评论中匹配主题。

    ``negative_context_only`` 用于痛点：只接受评级 ≤3 星的评论，或句子中出现
    否定/转折词，避免把好评里的 "great size" 误判为尺寸问题。
    """
    hits: list[ThemeHit] = []
    for competitor, review in reviews:
        text = review.text
        sentences = split_sentences(text)
        for theme in themes_of(kind):  # type: ignore[arg-type]
            patterns = _THEME_COMPILED[theme.key]
            matched = False
            for sentence in sentences:
                for pattern in patterns:
                    match = pattern.search(sentence)
                    if not match:
                        continue
                    if negative_context_only:
                        low_rating = review.rating is not None and review.rating <= 3
                        negated = _is_negated(sentence, match.start())
                        contrast = bool(_CONTRAST_RE.search(sentence))
                        # "does not leak" 是正面表述，不能算作痛点；
                        # 只有低星、或句子中出现转折/让步时才计入。
                        if negated and not contrast:
                            continue
                        if not (low_rating or contrast):
                            continue
                    hits.append(
                        ThemeHit(
                            theme=theme,
                            competitor=competitor,
                            review=review,
                            review_index=0,
                            sentence=sentence.strip(),
                        )
                    )
                    matched = True
                    break
                if matched:
                    break
    return hits


def _theme_breakdown(hits: list[ThemeHit], total_reviews: int) -> list[PainPoint]:
    grouped: dict[str, list[ThemeHit]] = defaultdict(list)
    for hit in hits:
        grouped[hit.theme.key].append(hit)

    points: list[PainPoint] = []
    for key, items in grouped.items():
        theme = items[0].theme
        competitors = Counter(item.competitor for item in items)
        samples: list[EvidenceRef] = []
        seen_quotes: set[str] = set()
        for item in items:
            text = quote(item.sentence, MAX_REPORT_QUOTE)
            if text in seen_quotes:
                continue
            seen_quotes.add(text)
            samples.append(
                EvidenceRef(
                    competitor=item.competitor,
                    field="reviews",
                    quote=text,
                    data_source=item.review.source,
                )
            )
            if len(samples) >= MAX_SAMPLES_PER_THEME:
                break
        frequency = len(items)
        share = round(frequency / total_reviews, 4) if total_reviews else 0.0
        claim = Claim(
            statement=(
                f"{frequency} 条评论样本提及「{theme.label}」，占全部评论样本的 {share:.1%}"
            ),
            evidence_kind=EvidenceKind.STATISTIC,
            evidence=samples,
            sample_size=total_reviews,
        )
        points.append(
            PainPoint(
                label=theme.label,
                description=theme.description,
                frequency=frequency,
                share=share,
                sentiment="negative" if theme.kind == "pain" else "mixed",
                competitor_breakdown=dict(competitors),
                samples=samples,
                claim=claim,
            )
        )
    points.sort(key=lambda p: (-p.frequency, p.label))
    return points


def analyze_reviews(data: NormalizedData) -> ReviewInsights:
    """评论洞察：高频需求、痛点、负面反馈、购买顾虑。"""
    total = len(data.reviews)
    insights = ReviewInsights(total_samples=total)
    if total == 0:
        insights.limitations.append("没有评论样本，未进行评论分析")
        return insights

    rated = [(name, r) for name, r in data.reviews if r.rating is not None]
    insights.with_rating = len(rated)
    distribution: Counter[str] = Counter()
    for _, review in rated:
        distribution[f"{int(round(review.rating or 0))}星"] += 1
    insights.rating_distribution = dict(sorted(distribution.items()))
    low_rating = [(name, r) for name, r in data.reviews if r.rating is not None and r.rating <= 3]
    insights.low_rating_count = len(low_rating)

    pain_hits = match_themes(data.reviews, "pain", negative_context_only=True)
    insights.pain_points = _theme_breakdown(pain_hits, total) if total else []
    needs_hits = match_themes(data.reviews, "need")
    insights.needs = _theme_breakdown(needs_hits, total) if total else []
    concern_hits = match_themes(data.reviews, "concern")
    insights.purchase_concerns = _theme_breakdown(concern_hits, total) if total else []
    # 低星评论主题单独列出（负面反馈）
    if low_rating:
        low_hits = match_themes(low_rating, "pain", negative_context_only=True)
        insights.low_rating_themes = _theme_breakdown(low_hits, len(low_rating))
    else:
        insights.limitations.append("没有 1-3 星评论样本，低星负面反馈分析不可用")

    if insights.with_rating == 0:
        insights.limitations.append("所有评论均未提供星级，负面反馈只能依靠文本转折/否定词判断")
    elif insights.with_rating < total:
        insights.limitations.append(
            f"仅 {insights.with_rating}/{total} 条评论带星级，星级分布不代表真实评分结构"
        )
    if not pain_hits:
        insights.limitations.append("评论中未匹配到已知痛点主题，可能是样本过少或品类词典未覆盖")
    return insights


def review_frequent_terms(data: NormalizedData, limit: int = 10) -> list[tuple[str, int]]:
    """评论高频词（英文）。仅统计，不用于生成结论。"""
    return top_terms([r.text for _, r in data.reviews], limit=limit)


# ---------------------------------------------------------------------------
# 卖点与价格
# ---------------------------------------------------------------------------


def _tokenize_feature(feature: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", feature.lower())
    return {w for w in words if len(w) > 2}


def analyze_features(data: NormalizedData, own_features: list[str]) -> list[FeatureComparison]:
    """把竞品卖点做要点/词级归并，统计提及覆盖率。"""
    competitors = data.competitors
    total = len(competitors)

    # 1) 完全相同的卖点直接归并
    exact: dict[str, list[str]] = defaultdict(list)
    for competitor in competitors:
        for feature in competitor.key_features:
            exact[feature.strip().lower()].append(competitor.name)

    comparisons: list[FeatureComparison] = []
    for feature_key, names in exact.items():
        label = next(
            f for c in competitors for f in c.key_features if f.strip().lower() == feature_key
        )
        comparisons.append(
            FeatureComparison(
                feature=label,
                mentioned_by=sorted(set(names)),
                mention_count=len(set(names)),
                coverage_ratio=round(len(set(names)) / total, 4) if total else 0.0,
                evidence_kind=EvidenceKind.FACT,
            )
        )

    # 2) 词级共性：找出被 2 个以上竞品提及的关键词
    word_sources: dict[str, set[str]] = defaultdict(set)
    for competitor in competitors:
        for feature in competitor.key_features:
            for word in _tokenize_feature(feature):
                word_sources[word].add(competitor.name)
    common_words = {
        word: names for word, names in word_sources.items() if len(names) >= 2
    }
    existing_labels = {c.feature.lower() for c in comparisons}
    for word, names in common_words.items():
        if any(word in label for label in existing_labels):
            continue
        comparisons.append(
            FeatureComparison(
                feature=f"(关键词) {word}",
                mentioned_by=sorted(names),
                mention_count=len(names),
                coverage_ratio=round(len(names) / total, 4) if total else 0.0,
                evidence_kind=EvidenceKind.STATISTIC,
            )
        )

    # 3) 自有商品独有卖点
    own_tokens: set[str] = set()
    for feature in own_features:
        own_tokens |= _tokenize_feature(feature)
    for feature in own_features:
        tokens = _tokenize_feature(feature)
        covered = any(tokens & _tokenize_feature(c.feature) for c in comparisons)
        if not covered:
            comparisons.append(
                FeatureComparison(
                    feature=f"[自有] {feature}",
                    mentioned_by=["自有商品"],
                    mention_count=0,
                    coverage_ratio=0.0,
                    evidence_kind=EvidenceKind.FACT,
                )
            )

    comparisons.sort(key=lambda c: (-c.coverage_ratio, c.feature))
    return comparisons


def analyze_prices(data: NormalizedData, own_price: float | None) -> PriceAnalysis:
    priced = [c for c in data.competitors if c.price is not None]
    analysis = PriceAnalysis(
        compared_count=len(priced),
        currency=priced[0].currency if priced else "USD",
        own_price=own_price,
    )
    if not priced:
        analysis.claims.append(
            Claim(
                statement="没有可用的竞品价格，未做价格分析",
                evidence_kind=EvidenceKind.ASSUMPTION,
            )
        )
        return analysis

    values = sorted(c.price for c in priced if c.price is not None)
    analysis.min_price = round(values[0], 2)
    analysis.max_price = round(values[-1], 2)
    analysis.mean_price = round(mean(values), 2)
    analysis.median_price = round(median(values), 2)

    evidence = [
        EvidenceRef(competitor=c.name, field="price", data_source=c.source_ref)
        for c in priced
    ]
    analysis.claims.append(
        Claim(
            statement=(
                f"共 {len(priced)} 个竞品提供价格，区间 {analysis.min_price}-{analysis.max_price} "
                f"{analysis.currency}，中位数 {analysis.median_price} {analysis.currency}"
            ),
            evidence_kind=EvidenceKind.STATISTIC,
            evidence=evidence,
            sample_size=len(priced),
        )
    )

    if own_price is not None:
        below = sum(1 for v in values if v < own_price)
        if len(values) >= 2:
            analysis.position_percentile = below / len(values)
        else:
            analysis.position_percentile = 1.0 if own_price > values[0] else 0.0
        if own_price < values[0]:
            analysis.own_position = "below_range"
            statement = (
                f"自有商品价格 {own_price} {analysis.currency} 低于竞品最低价 {analysis.min_price}，"
                "可能形成价格优势，但需核查是否存在低价=低质的认知风险"
            )
        elif own_price > values[-1]:
            analysis.own_position = "above_range"
            statement = (
                f"自有商品价格 {own_price} {analysis.currency} 高于竞品最高价 {analysis.max_price}，"
                "必须在卖点或品质上提供可验证的溢价理由"
            )
        else:
            analysis.own_position = "within_range"
            statement = (
                f"自有商品价格 {own_price} {analysis.currency} 位于竞品区间内"
                + (
                    f"，约高于 {analysis.position_percentile:.0%} 的竞品报价"                    if analysis.position_percentile is not None
                    else f"（竞品最高价 {analysis.max_price}，最低价 {analysis.min_price}）"
                )
            )
        analysis.claims.append(
            Claim(
                statement=statement,
                evidence_kind=EvidenceKind.STATISTIC,
                evidence=evidence,
                sample_size=len(priced),
            )
        )
    elif own_price is None:
        analysis.claims.append(
            Claim(
                statement="未提供自有商品价格，无法判断价格位置",
                evidence_kind=EvidenceKind.ASSUMPTION,
            )
        )
    return analysis


# ---------------------------------------------------------------------------
# 关键词
# ---------------------------------------------------------------------------


def analyze_keywords(keywords: list[KeywordMetric], product_name: str) -> KeywordAnalysis:
    """只在存在量化指标时排序与打分；相关性缺失时用文本重叠度（并标注为估算）。"""
    analysis = KeywordAnalysis(available=bool(keywords), total_keywords=len(keywords))
    if not keywords:
        analysis.notes.append("未提供关键词数据，报告不含关键词机会分析")
        return analysis

    with_metrics = [k for k in keywords if k.has_metrics]
    analysis.with_metrics = len(with_metrics)
    if not with_metrics:
        analysis.opportunities = [
            KeywordOpportunity(keyword=k.keyword, has_metrics=False, basis="仅有词表，无搜索量/排名数据")
            for k in keywords
        ]
        analysis.notes.append(
            "全部关键词缺少搜索量/排名等指标：只列出关键词，不计算机会分，也不推断流量大小"
        )
        return analysis

    product_terms = _tokenize_feature(product_name)
    max_volume = max((k.search_volume or 0) for k in with_metrics) or 0

    opportunities: list[KeywordOpportunity] = []
    missing_rank = 0
    missing_volume = 0
    for keyword in keywords:
        if not keyword.has_metrics:
            opportunities.append(
                KeywordOpportunity(keyword=keyword.keyword, has_metrics=False, basis="无指标数据")
            )
            continue
        if keyword.search_volume is None:
            missing_volume += 1
        if keyword.rank is None:
            missing_rank += 1
        # 机会分：仅使用真实存在的指标，缺失项不参与且不补零以外的假设
        score_parts: list[float] = []
        basis_parts: list[str] = []
        if keyword.search_volume is not None and max_volume > 0:
            score_parts.append(keyword.search_volume / max_volume)
            basis_parts.append(f"搜索量 {keyword.search_volume}")
        if keyword.rank is not None:
            # 排名越靠前（数字小）分数越高，前 100 名映射到 1..0
            score_parts.append(max(0.0, 1 - (keyword.rank - 1) / 100))
            basis_parts.append(f"排名 {keyword.rank}")
        if keyword.relevance is not None:
            score_parts.append(keyword.relevance)
            basis_parts.append(f"相关性 {keyword.relevance}")
        elif product_terms:
            overlap = len(product_terms & set(re.findall(r"[a-z0-9]+", keyword.keyword.lower())))
            estimated = min(1.0, overlap / max(1, len(product_terms)))
            score_parts.append(estimated)
            basis_parts.append(f"文本重叠估算 {estimated:.2f}（无相关性字段）")
        if keyword.competition is not None:
            competition_factor = {"low": 1.0, "medium": 0.7, "high": 0.4}[keyword.competition]
            score_parts.append(competition_factor)
            basis_parts.append(f"竞争度 {keyword.competition}")
        score = round(sum(score_parts) / len(score_parts), 4) if score_parts else None
        opportunities.append(
            KeywordOpportunity(
                keyword=keyword.keyword,
                has_metrics=True,
                search_volume=keyword.search_volume,
                rank=keyword.rank,
                relevance=keyword.relevance,
                competition=keyword.competition,
                opportunity_score=score,
                basis="；".join(basis_parts) or "指标均为空",
            )
        )
    opportunities.sort(key=lambda o: (-(o.opportunity_score or 0), o.keyword))
    analysis.opportunities = opportunities
    if missing_volume:
        analysis.notes.append(f"{missing_volume} 个关键词缺少搜索量，机会分未包含该维度")
    if missing_rank:
        analysis.notes.append(f"{missing_rank} 个关键词缺少排名，机会分未包含该维度")
    analysis.notes.append(
        "机会分为激浪内部可解释加权值，非平台官方指标，仅供排序参考"
    )
    return analysis


# ---------------------------------------------------------------------------
# 自有商品对比 & 差异化
# ---------------------------------------------------------------------------


def compare_own(
    request: CompetitorAnalysisRequest,
    data: NormalizedData,
    features: list[FeatureComparison],
    insights: ReviewInsights,
) -> list[Claim]:
    """对比自有商品与竞品。缺少自有规格时只做卖点/价格层面的对比。"""
    claims: list[Claim] = []
    competitors = data.competitors

    # 1) 价格对比
    if request.own_price is not None:
        priced = [c for c in competitors if c.price is not None]
        if priced:
            cheaper = [c for c in priced if c.price is not None and c.price > request.own_price]
            claims.append(
                Claim(
                    statement=(
                        f"自有商品价格低于 {len(cheaper)}/{len(priced)} 个提供价格的竞品"
                    ),
                    evidence_kind=EvidenceKind.STATISTIC,
                    evidence=[EvidenceRef(competitor=c.name, field="price") for c in priced],
                    sample_size=len(priced),
                )
            )
    # 2) 卖点覆盖
    own_features = request.own_key_features
    if own_features:
        competitor_feature_text = " ".join(
            f.lower() for c in competitors for f in c.key_features
        )
        covered, unique = [], []
        for feature in own_features:
            tokens = _tokenize_feature(feature)
            if tokens and any(t in competitor_feature_text for t in tokens):
                covered.append(feature)
            else:
                unique.append(feature)
        if covered:
            claims.append(
                Claim(
                    statement=f"自有卖点中有 {len(covered)} 项已被竞品以类似表述覆盖：{'、'.join(covered[:5])}",
                    evidence_kind=EvidenceKind.INFERENCE,
                    evidence=[
                        EvidenceRef(competitor=c.name, field="key_features", quote=" | ".join(c.key_features[:3]))
                        for c in competitors
                        if c.key_features
                    ],
                )
            )
        if unique:
            claims.append(
                Claim(
                    statement=f"自有卖点中有 {len(unique)} 项未在竞品卖点中发现：{'、'.join(unique[:5])}",
                    evidence_kind=EvidenceKind.INFERENCE,
                    evidence=[EvidenceRef(field="own.key_features", quote=" | ".join(unique))],
                )
            )
    # 3) 规格覆盖
    own_spec_keys = {k.lower().strip() for k in request.own_specs}
    if own_spec_keys:
        competitor_spec_keys = {
            key.lower().strip()
            for c in competitors
            for key in c.specifications
        }
        uncovered = own_spec_keys - competitor_spec_keys
        if uncovered:
            claims.append(
                Claim(
                    statement=(
                        f"自有规格中的 {', '.join(sorted(uncovered))} 未在任何竞品规格中出现，"
                        "可作为差异化信息点，但需先确认这些规格真实可对外披露"
                    ),
                    evidence_kind=EvidenceKind.INFERENCE,
                    evidence=[EvidenceRef(field="own.specifications", quote=", ".join(sorted(uncovered)))],
                )
            )
    # 4) 评论痛点 vs 自有卖点
    if insights.pain_points and own_features:
        own_text = " ".join(own_features).lower()
        addressed = [
            point.label
            for point in insights.pain_points
            if any(theme_word in own_text for theme_word in _feature_terms_for_label(point.label))
        ]
        if addressed:
            claims.append(
                Claim(
                    statement=f"自有卖点可能已回应以下评论痛点：{'、'.join(addressed)}",
                    evidence_kind=EvidenceKind.INFERENCE,
                    evidence=[
                        p.samples[0] for p in insights.pain_points if p.label in addressed and p.samples
                    ],
                )
            )
    if not claims:
        claims.append(
            Claim(
                statement="自有商品资料不足，未能形成可对比结论",
                evidence_kind=EvidenceKind.ASSUMPTION,
            )
        )
    return claims


def _feature_terms_for_label(label: str) -> list[str]:
    mapping = {
        "尺寸/容量与预期不符": ["size", "capacity", "dimension", "尺寸", "容量"],
        "做工/材质质量": ["quality", "material", "sturdy", "材质", "耐用"],
        "耐用性不足": ["durable", "durability", "long", "耐用"],
        "安装/组装困难": ["easy", "assemble", "install", "install", "免安装", "易安装"],
        "密封/渗漏问题": ["seal", "leak", "密封"],
        "异味": ["odor", "smell", "无味", "除味"],
        "噪音过大": ["quiet", "noise", "静音"],
        "续航/供电问题": ["battery", "charge", "续航", "充电"],
        "包装/运输损坏": ["packaging", "包装"],
        "缺少配件/零件": ["includes", "accessories", "配件"],
        "颜色/外观与图片不符": ["color", "颜色"],
        "操作不便/设计不合理": ["easy", "clean", "方便", "易清洗"],
        "描述与实物不一致": ["accurate", "真实", "如实"],
    }
    return mapping.get(label, [])


def build_differentiation(
    request: CompetitorAnalysisRequest,
    data: NormalizedData,
    price: PriceAnalysis,
    insights: ReviewInsights,
    keywords: KeywordAnalysis,
) -> list[DifferentiationOpportunity]:
    opportunities: list[DifferentiationOpportunity] = []

    # 1) 未被满足的痛点 → 差异化
    for point in insights.pain_points[:3]:
        opportunities.append(
            DifferentiationOpportunity(
                angle=f"用可验证的设计回应「{point.label}」",
                rationale=(
                    f"{point.frequency} 条评论样本（{point.share:.1%}）提及该问题，"
                    "若自有商品在真实规格上确有改进，可在详情页优先说明"
                ),
                supporting_evidence=[point.claim] if point.claim else [],
                priority="high" if point.share >= 0.15 else "medium",
                confidence="medium",
                requires_confirmation=True,
            )
        )

    # 2) 高频需求 → 内容侧重
    for need in insights.needs[:2]:
        opportunities.append(
            DifferentiationOpportunity(
                angle=f"围绕「{need.label}」组织内容",
                rationale=f"{need.frequency} 条评论样本表达该需求，可在标题/五点中正面回应",
                supporting_evidence=[need.claim] if need.claim else [],
                priority="medium",
                confidence="medium",
                requires_confirmation=True,
            )
        )

    # 3) 价格定位
    if price.own_position == "below_range":
        opportunities.append(
            DifferentiationOpportunity(
                angle="价格优势 + 品质背书",
                rationale="自有价格低于竞品区间，需在内容中补充可验证的品质信息以消除低价疑虑",
                supporting_evidence=price.claims[1:2],
                priority="medium",
                confidence="high",
            )
        )
    elif price.own_position == "above_range":
        opportunities.append(
            DifferentiationOpportunity(
                angle="为溢价提供可验证理由",
                rationale="自有价格高于所有竞品，必须在材质/工艺/服务上给出可验证证据",
                supporting_evidence=price.claims[1:2],
                priority="high",
                confidence="high",
            )
        )
    elif price.own_position == "within_range":
        opportunities.append(
            DifferentiationOpportunity(
                angle="在同价位中突出可验证差异",
                rationale="价格处于竞品区间，单纯降价空间有限，应强调规格与体验差异",
                supporting_evidence=price.claims[1:2],
                priority="medium",
                confidence="medium",
            )
        )

    # 4) 关键词
    metric_opps = [k for k in keywords.opportunities if k.has_metrics][:2]
    for opportunity in metric_opps:
        if opportunity.opportunity_score is None:
            continue
        opportunities.append(
            DifferentiationOpportunity(
                angle=f"布局关键词「{opportunity.keyword}」",
                rationale=f"机会分 {opportunity.opportunity_score:.2f}（{opportunity.basis}）",
                priority="medium" if opportunity.opportunity_score >= 0.5 else "low",
                confidence="medium",
                requires_confirmation=True,
            )
        )

    # 5) 自有规格未覆盖
    own_spec_keys = {k.lower().strip() for k in request.own_specs}
    competitor_spec_keys = {k.lower().strip() for c in data.competitors for k in c.specifications}
    unique_specs = own_spec_keys - competitor_spec_keys
    if unique_specs:
        opportunities.append(
            DifferentiationOpportunity(
                angle=f"把独有规格作为信任状：{', '.join(sorted(unique_specs))}",
                rationale="这些规格字段未在竞品规格中出现，可使内容比竞品更具体",
                priority="medium",
                confidence="medium",
                requires_confirmation=True,
            )
        )

    if not opportunities:
        opportunities.append(
            DifferentiationOpportunity(
                angle="补充数据后再定差异化方向",
                rationale="当前竞品数据与自有资料都不足以支撑明确差异化",
                priority="low",
                confidence="low",
                requires_confirmation=True,
            )
        )
    return opportunities


def build_recommendations(
    request: CompetitorAnalysisRequest,
    price: PriceAnalysis | None,
    features: list[FeatureComparison],
    insights: ReviewInsights,
    keywords: KeywordAnalysis,
) -> list[ContentRecommendation]:
    recommendations: list[ContentRecommendation] = []

    # 标题
    top_features = [f for f in features if not f.feature.startswith("(关键词)") and not f.feature.startswith("[自有]")][:2]
    if top_features:
        recommendations.append(
            ContentRecommendation(
                area="title",
                recommendation=(
                    "标题优先放置自有商品「品类词 + 核心规格 + 主要使用场景」，"
                    f"竞品高频卖点可参考：{'、'.join(f.feature for f in top_features)}"
                ),
                evidence_kind=EvidenceKind.INFERENCE,
                rationale="竞品普遍强调的卖点通常对应买家搜索意图，但不建议照搬表述",
                evidence=[
                    EvidenceRef(competitor=name, field="key_features")
                    for f in top_features
                    for name in f.mentioned_by[:2]
                ],
            )
        )
    # 五点
    if insights.pain_points:
        recommendations.append(
            ContentRecommendation(
                area="bullet",
                recommendation=(
                    "五点的前 2 条正面回应高频痛点："
                    + "、".join(p.label for p in insights.pain_points[:2])
                    + "；仅在自有商品真实具备对应设计时使用，否则标注待确认"
                ),
                evidence_kind=EvidenceKind.INFERENCE,
                rationale="负面体验是购买阻碍，提前解释可降低退货与差评风险",
                evidence=[s for p in insights.pain_points[:2] for s in p.samples[:1]],
            )
        )
    if insights.needs:
        recommendations.append(
            ContentRecommendation(
                area="description",
                recommendation="产品描述中加入使用场景段落，覆盖需求：" + "、".join(n.label for n in insights.needs[:3]),
                evidence_kind=EvidenceKind.INFERENCE,
                rationale="评论中的正面使用场景可作为场景化描述的真实依据",
                evidence=[s for n in insights.needs[:3] for s in n.samples[:1]],
            )
        )
    # A+
    recommendations.append(
        ContentRecommendation(
            area="a_plus",
            recommendation=(
                "A+ 建议包含：痛点-解决方案对比图、真实规格表、使用场景图、包装清单。"
                "所有数据须来自自有商品资料"
            ),
            evidence_kind=EvidenceKind.INFERENCE,
            rationale="对比图与规格表是转化率提升的常见模块，但必须以真实信息为前提",
        )
    )
    # 价格
    if price is not None and price.own_position in {"within_range", "above_range"}:
        recommendations.append(
            ContentRecommendation(
                area="pricing",
                recommendation=(
                    "不建议在 Listing 内直接写价格对比；通过规格/材质/配件数量体现价值差"
                    if price.own_position == "within_range"
                    else "为溢价准备可验证证据（检测报告、材质说明、质保条款），并在详情页说明"
                ),
                evidence_kind=EvidenceKind.INFERENCE,
                rationale="平台通常限制价格类表述，且价格随促销变化",
                evidence=[item for claim in price.claims for item in claim.evidence][:5],
            )
        )
    recommendations.append(
        ContentRecommendation(
            area="image",
            recommendation="主图突出自有规格中可量化的差异（如容量、数量、尺寸），并保证与实物一致",
            evidence_kind=EvidenceKind.INFERENCE,
            rationale="规格差异是最容易被图片直观表达的信息",
        )
    )
    if keywords.available and keywords.with_metrics:
        recommendations.append(
            ContentRecommendation(
                area="title",
                recommendation="在标题与 Search Terms 中自然覆盖机会分最高的 2-3 个关键词，避免堆砌",
                evidence_kind=EvidenceKind.STATISTIC,
                rationale="机会分基于已有指标计算，可解释但非平台官方数据",
                evidence=[
                    EvidenceRef(field="keywords", quote=o.keyword)
                    for o in keywords.opportunities[:3]
                    if o.has_metrics
                ],
            )
        )
    return recommendations


# ---------------------------------------------------------------------------
# 组装报告
# ---------------------------------------------------------------------------


def _snapshots(data: NormalizedData) -> list[ProductSnapshot]:
    snapshots: list[ProductSnapshot] = []
    for competitor in data.competitors:
        completeness, missing = _data_completeness(competitor)
        snapshots.append(
            ProductSnapshot(
                name=competitor.name,
                brand=competitor.brand,
                price=competitor.price,
                currency=competitor.currency,
                rating=competitor.rating,
                review_count=competitor.review_count,
                review_samples=len(competitor.reviews),
                key_features=competitor.key_features,
                is_demo=competitor.is_demo,
                data_completeness=completeness,
                missing_fields=missing,
            )
        )
    return snapshots


def run_analysis(
    request: CompetitorAnalysisRequest,
    *,
    engine: str = "rule",
    engine_version: str = "0.1.0",
    demo_label: str = "demo",
) -> AnalysisReport:
    """同步执行完整竞品分析流程并返回结构化报告。"""
    validation = validate_request(request)
    if not validation.ok:
        raise ValueError("输入校验失败: " + "；".join(validation.errors))

    data = normalize(request)
    if not data.competitors:
        raise ValueError("输入校验失败: 规范化后没有有效竞品")

    # 价格
    price = analyze_prices(data, request.own_price)
    # 卖点
    features = analyze_features(data, request.own_key_features)
    # 评论
    insights = analyze_reviews(data)
    # 关键词
    keywords = analyze_keywords(data.keywords, request.product_name)
    # 对比
    own_vs = compare_own(request, data, features, insights)
    # 差异化
    differentiation = build_differentiation(request, data, price, insights, keywords)
    # 建议
    recommendations = build_recommendations(request, price, features, insights, keywords)

    is_demo = any(c.is_demo for c in data.competitors)
    missing_fields: list[str] = []
    for snapshot in _snapshots(data):
        missing_fields.extend(snapshot.missing_fields)
    provenance = DataProvenance(
        data_source=request.data_source,
        is_demo=is_demo,
        competitor_count=len(data.competitors),
        review_sample_count=len(data.reviews),
        keyword_count=len(data.keywords),
        fields_missing=sorted(set(missing_fields)),
        notes=[
            ("竞品数据标记为 demo（模拟数据），不代表真实 Amazon 商品、销量或排名"
             if is_demo else "竞品数据由用户提供，激浪未做外部核实"),
            f"评论样本 {len(data.reviews)} 条；仅有 {insights.with_rating} 条带星级",
        ],
    )

    limitations = [
        "本报告基于用户提供的竞品文本与评论做统计与规则匹配，未抓取平台实时数据",
        "评论主题命中为关键词规则判断，同义表达可能漏检，样本量小时比例波动大",
        "评论星级未提供时，负面判断依赖否定/转折词规则，存在误判可能",
        "价格与评分均为输入时点数据，未考虑促销、Coupon 与地区差异",
        "所有 inference 类型结论为可解释推断，发布前需人工核验自有商品是否真的具备该优势",
    ]
    if any(_contains_cjk(f) for f in request.own_key_features):
        limitations.append(
            "自有卖点为中文、竞品卖点为英文时无法做词级匹配，"
            "「未被竞品覆盖」的结论需要人工确认，不应直接当作竞品未提供的证据"
        )
    if any(_contains_cjk(c.name) for c in data.competitors):
        limitations.append("竞品名称/卖点为中文，英文语义匹配能力有限，结论需人工复核")
    if not keywords.available:
        limitations.append("未提供关键词数据，本报告不含关键词机会分析")
    elif keywords.with_metrics == 0:
        limitations.append("关键词缺少搜索量与排名，未计算机会分，也未推断流量")
    if insights.total_samples == 0:
        limitations.append("没有评论样本，评论结论缺失")
    if not request.own_specs:
        limitations.append("自有商品规格为空，规格级差异化未展开")

    warnings = validation.warnings + data.warnings
    if not price.claims or price.compared_count == 0:
        warnings.append("没有竞品价格，价格差异分析不可用")
    if is_demo:
        warnings.append(f"当前数据包含 {demo_label} 模拟数据，请勿用于真实经营决策")

    return AnalysisReport(
        report_id=uuid.uuid4().hex,
        product_name=request.product_name,
        platform=request.platform,
        marketplace=request.marketplace,
        category=request.category,
        locale=request.locale,
        data_provenance=provenance,
        competitor_snapshots=_snapshots(data),
        price_analysis=price,
        feature_comparison=features,
        own_vs_competitors=own_vs,
        review_insights=insights,
        keyword_analysis=keywords,
        differentiation_opportunities=differentiation,
        content_recommendations=recommendations,
        limitations=limitations,
        warnings=warnings,
        engine=engine,
        engine_version=engine_version,
    )


__all__ = [
    "NormalizedData",
    "analyze_features",
    "analyze_keywords",
    "analyze_prices",
    "analyze_reviews",
    "build_differentiation",
    "build_recommendations",
    "compare_own",
    "match_themes",
    "normalize",
    "run_analysis",
    "run_analysis",
    "validate_request",
]
