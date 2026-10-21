"""Listing 生成 Agent（规则引擎实现）。

核心约束：
- 每一项商品事实都必须来自 ``OwnProduct`` 输入或分析报告中可追溯的数据；
- 缺失字段进入 ``pending_confirmations``，**绝不**由模板补成事实；
- 生成后运行声明审计（数字、绝对化、认证、功效、关键词密度）与长度检查；
- 平台限制全部来自可配置规则，并附带"未核验最新平台政策"的免责声明。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from ..models import (
    APlusModule,
    BulletPoint,
    IssueCode,
    KeywordMetric,
    ListingDraft,
    ListingGenerationRequest,
    ListingProvenance,
    OwnProduct,
    QualityCheck,
    QualityIssue,
    SectionLength,
    Severity,
)
from .rules import BannedTermRules, PlatformRules, RuleSet, get_rules
from .textutils import (
    byte_len_utf8,
    char_len,
    contains_emoji,
    truncate,
)

# 五点的常见结构：利益点 + 支撑细节
_BULLET_ANGLES: tuple[tuple[str, str], ...] = (
    ("核心价值", "把商品最重要的真实卖点放在第一条，直接回应买家最关心的问题"),
    ("使用体验", "描述真实使用场景与便利性"),
    ("材质与做工", "说明材质、结构与耐用性（仅使用输入中已有的信息）"),
    ("规格与适配", "给出真实尺寸、容量、兼容范围"),
    ("包装与服务", "包装清单、使用说明、售后政策（仅使用输入中已有的信息）"),
)


# ---------------------------------------------------------------------------
# 事实台账
# ---------------------------------------------------------------------------


@dataclass
class FactLedger:
    """记录每个可用事实及其输入来源，供内容生成与质检使用。"""

    facts: dict[str, str] = field(default_factory=dict)  # statement -> source field
    confirmed_attributes: set[str] = field(default_factory=set)
    pending: list[str] = field(default_factory=list)

    def add(self, statement: str, source: str) -> None:
        self.facts[statement] = source

    def has_attribute(self, name: str) -> bool:
        return name.lower() in {a.lower() for a in self.confirmed_attributes}


REQUIRED_ATTRIBUTE_KEYS = {
    "size": ("size", "dimensions", "dimension", "尺寸", "规格", "长宽高"),
    "material": ("material", "材质", "面料"),
    "capacity": ("capacity", "volume", "容量", "净含量"),
    "color": ("color", "colour", "颜色"),
    "weight": ("weight", "重量", "净重"),
    "quantity": ("quantity", "pieces", "pack", "数量", "件数", "套装"),
}


def build_fact_ledger(product: OwnProduct) -> FactLedger:
    ledger = FactLedger()
    if product.brand:
        ledger.add(f"品牌：{product.brand}", "brand")
    if product.category:
        ledger.add(f"类目：{product.category}", "category")
    for key, value in product.specifications.items():
        ledger.add(f"{key}：{value}", f"specifications.{key}")
        ledger.confirmed_attributes.add(key)
    for feature in product.key_features:
        ledger.add(f"卖点：{feature}", "key_features")
    for material in product.materials:
        ledger.add(f"材质：{material}", "materials")
        ledger.confirmed_attributes.add("material")
    for cert in product.certifications:
        ledger.add(f"认证：{cert}", "certifications")
        ledger.confirmed_attributes.add("certifications")
    if product.price is not None:
        ledger.add(f"价格：{product.price} {product.currency}", "price")
    if product.target_audience:
        ledger.add(f"目标用户：{product.target_audience}", "target_audience")

    # 缺失关键属性 -> 待确认（绝不补全）
    for canonical, aliases in REQUIRED_ATTRIBUTE_KEYS.items():
        if any(ledger.has_attribute(alias) for alias in aliases):
            continue
        missing_labels = {
            "size": "尺寸",
            "material": "材质",
            "capacity": "容量/净含量",
            "color": "颜色",
            "weight": "重量",
            "quantity": "数量/套装件数",
        }
        ledger.pending.append(f"待确认：{missing_labels[canonical]}（输入资料中未提供，未在文案中填写）")
    if not product.certifications:
        ledger.pending.append("待确认：认证/检测报告（如需出现 CE/FDA/食品级等表述，必须提供证书编号）")
    return ledger


# ---------------------------------------------------------------------------
# 文本构建
# ---------------------------------------------------------------------------


def _join_clauses(parts: list[str], limit: int) -> str:
    """按顺序拼接分句，直到接近字符上限。"""
    output: list[str] = []
    for part in parts:
        candidate = "；".join(output + [part]) if output else part
        if char_len(candidate) <= limit:
            output.append(part)
        else:
            break
    return "；".join(output)


def _english_variant(feature: str) -> str:
    """卖点原文即英文时直接使用，避免机器翻译引入错误事实。"""
    return feature.strip()


def build_title(
    product: OwnProduct,
    rules: PlatformRules,
    ledger: FactLedger,
    keywords: list[str],
) -> str:
    """标题 = 品牌 + 商品名 + 核心规格 + 场景/卖点，按优先级裁剪到字符上限。"""
    parts: list[str] = []
    name_lower = product.name.lower()
    # 商品名已包含品牌时不再重复追加；brand 缺省时用商品名首词判断
    brand = product.brand or (product.name.split()[0] if product.name.split() else None)
    if brand and brand.lower() not in name_lower:
        parts.append(brand)
    parts.append(product.name)

    # 规格：只取已确认的前 2 项（不写单位外的修饰词）
    spec_parts = [f"{k} {v}" for k, v in list(product.specifications.items())[:2]]
    parts.extend(spec_parts)

    # 核心卖点：取第一条短卖点
    if product.key_features:
        first = _english_variant(product.key_features[0])
        if char_len(first) <= 60 and first.lower() not in name_lower:
            parts.append(first)

    # 关键词：仅在已有指标数据时追加，且必须与商品名/卖点有文本重叠，
    # 避免把无关词（如 plastic tumbler）塞进不锈钢瓶的标题。
    if keywords:
        base_terms = {w for w in re.findall(r"[a-z0-9]+", " ".join([product.name] + product.key_features).lower()) if len(w) > 2}
        for keyword in keywords[:3]:
            keyword_terms = {w for w in re.findall(r"[a-z0-9]+", keyword.lower()) if len(w) > 2}
            if not (keyword_terms & base_terms):
                continue
            if keyword.lower() in " ".join(parts).lower():
                continue
            parts.append(keyword)

    title = " - ".join(p for p in parts if p)
    if char_len(title) > rules.title_max_chars:
        while parts and char_len(" - ".join(parts)) > rules.title_max_chars:
            parts.pop()
        title = " - ".join(parts) or product.name
    title = truncate(title, rules.title_max_chars, "")
    # 平台禁止的全大写/特殊字符做一次兜底替换，质检仍会复检
    if not rules.allow_all_caps:
        title = re.sub(r"\b([A-Z]{4,})\b", lambda m: m.group(1).title(), title)
    return title


def build_bullets(
    product: OwnProduct,
    rules: PlatformRules,
    ledger: FactLedger,
    insight_modules: list[str] | None = None,
) -> list[BulletPoint]:
    """五点描述：每条由真实事实构建；无事实支撑的角度不生成。"""
    bullets: list[BulletPoint] = []
    specs_items = list(product.specifications.items())
    features = list(product.key_features)

    # 角度 1：核心价值（取第一条真实卖点）
    if features:
        headline = truncate(features[0], 60, "")
        body_parts = [f for f in features[1:3]]
        if specs_items:
            body_parts.append("；".join(f"{k} {v}" for k, v in specs_items[:2]))
        body = _join_clauses(body_parts, rules.bullet_max_chars) or "详见商品规格。"
        bullets.append(
            BulletPoint(
                headline=headline,
                body=body,
                character_count=char_len(headline) + char_len(body),
                supporting_facts=[features[0]] + [f for f in features[1:3]],
            )
        )

    # 角度 2：规格与适配（以真实规格为限）
    if specs_items:
        headline = "真实规格一览"
        body = _join_clauses([f"{k}：{v}" for k, v in specs_items], rules.bullet_max_chars)
        bullets.append(
            BulletPoint(
                headline=headline,
                body=body,
                character_count=char_len(headline) + char_len(body),
                supporting_facts=[f"{k}：{v}" for k, v in specs_items],
            )
        )

    # 角度 3：使用体验（来自剩余卖点）
    remaining = features[3:]
    if remaining:
        headline = "为日常使用而设计"
        body = _join_clauses(remaining, rules.bullet_max_chars)
        bullets.append(
            BulletPoint(
                headline=headline,
                body=body,
                character_count=char_len(headline) + char_len(body),
                supporting_facts=remaining,
            )
        )

    # 角度 4：材质与认证（仅当输入中有）
    material_parts: list[str] = []
    if product.materials:
        material_parts.append("材质：" + "、".join(product.materials))
    if product.certifications:
        material_parts.append("认证：" + "、".join(product.certifications) + "（以证书编号为准）")
    if material_parts:
        headline = "材质与合规信息"
        body = _join_clauses(material_parts, rules.bullet_max_chars)
        bullets.append(
            BulletPoint(
                headline=headline,
                body=body,
                character_count=char_len(headline) + char_len(body),
                supporting_facts=[f"materials：{m}" for m in product.materials]
                + [f"certifications：{c}" for c in product.certifications],
            )
        )

    # 角度 5：包装清单/场景（只使用 target_audience 与已确认信息）
    if product.target_audience:
        headline = "适用场景与人群"
        body = f"适合 {product.target_audience}。实际使用前请确认规格与安装条件。"
        bullets.append(
            BulletPoint(
                headline=headline,
                body=body,
                character_count=char_len(headline) + char_len(body),
                supporting_facts=[product.target_audience],
            )
        )

    # 不足 5 条时补齐"待确认"占位，而不是编造事实
    while len(bullets) < rules.bullet_count:
        bullets.append(
            BulletPoint(
                headline="待补充卖点",
                body="该卖点缺少可验证的输入资料，暂未生成。请补充商品规格或检测报告后再生成。",
                character_count=0,
                supporting_facts=[],
            )
        )

    # 裁剪到平台允许的条数与字符上限
    trimmed: list[BulletPoint] = []
    for bullet in bullets[: rules.bullet_count]:
        headline = truncate(bullet.headline, 80, "")
        body = truncate(bullet.body, max(0, rules.bullet_max_chars - char_len(headline)), "…")
        trimmed.append(
            bullet.model_copy(
                update={
                    "headline": headline,
                    "body": body,
                    "character_count": char_len(headline) + char_len(body),
                }
            )
        )
    return trimmed


def build_description(
    product: OwnProduct,
    rules: PlatformRules,
    ledger: FactLedger,
    differentiation: list[str],
    language: str,
) -> str:
    """产品描述：场景 + 真实信息 + 使用提示。不使用任何未提供的参数。"""
    paragraphs: list[str] = []
    intro = f"{product.name}"
    if product.brand:
        intro = f"{product.brand} {intro}"
    if product.category:
        intro += f"｜{product.category}"
    paragraphs.append(intro + "。")

    if product.target_audience:
        paragraphs.append(f"为 {product.target_audience} 设计，帮助你在日常场景中获得更稳定的使用体验。")

    if product.key_features:
        features_text = "；".join(f"- {f}" for f in product.key_features[:5])
        paragraphs.append("主要特点：\n" + features_text)

    if product.specifications:
        specs_text = "；".join(f"{k}：{v}" for k, v in product.specifications.items())
        paragraphs.append(f"规格信息：{specs_text}")

    if product.materials:
        paragraphs.append("材质：" + "、".join(product.materials))

    if product.certifications:
        paragraphs.append("认证信息：" + "、".join(product.certifications) + "（请以证书为准，发布前核对编号）")

    if differentiation:
        paragraphs.append("适用场景：" + "；".join(differentiation[:3]))

    paragraphs.append(
        "提示：本描述中的规格均来自商品资料；未提供的参数（如尺寸、容量、认证）未做任何补充，"
        "请在上架前补齐并人工复核。"
    )

    text = "\n\n".join(paragraphs)
    return truncate(text, rules.description_max_chars, "…")


def build_a_plus_outline(
    product: OwnProduct,
    insights: dict[str, list[str]],
    has_specs: bool,
) -> list[APlusModule]:
    modules: list[APlusModule] = [
        APlusModule(
            module_type="hero_banner",
            title="主视觉 Banner",
            purpose="一句话传达核心价值，避免任何未验证的承诺",
            content_outline=[
                f"{product.name} 的核心使用场景",
                "品牌名与核心卖点（来自 input.key_features）",
            ],
            assets_needed=["1 张 1464x600 场景主图", "品牌 Logo"],
        ),
        APlusModule(
            module_type="benefit_icons",
            title="利益点图标行",
            purpose="把最能验证的 3-4 个卖点图标化",
            content_outline=product.key_features[:4] or ["待补充真实卖点后生成"],
            assets_needed=["3-4 个图标", "对应文案（<10 字/条）"],
        ),
    ]
    if insights.get("pain_points"):
        modules.append(
            APlusModule(
                module_type="comparison_chart",
                title="痛点-解决方案对比",
                purpose="针对评论中高频问题说明产品设计（须有真实依据）",
                content_outline=[
                    f"问题：{label}（来自评论样本）" for label in insights["pain_points"][:3]
                ]
                + ["解决方式：待产品团队确认后填写"],
                assets_needed=["对比示意图", "真实细节图"],
            )
        )
    if has_specs:
        modules.append(
            APlusModule(
                module_type="spec_table",
                title="真实规格表",
                purpose="完整列出可验证规格，降低因信息缺失导致的退货",
                content_outline=[f"{k}：{v}" for k, v in product.specifications.items()],
                assets_needed=["规格表设计稿"],
            )
        )
    modules.append(
        APlusModule(
            module_type="lifestyle_image",
            title="使用场景图",
            purpose="展示真实使用方式，避免夸大效果",
            content_outline=[
                "目标用户日常使用场景",
                "安装/使用步骤（如产品需要）",
            ],
            assets_needed=["2-3 张场景图"],
        )
    )
    modules.append(
        APlusModule(
            module_type="brand_story",
            title="品牌故事",
            purpose="建立信任，只讲可核实的品牌信息",
            content_outline=["品牌定位", "售后与支持方式（须与政策一致）"],
            assets_needed=["品牌故事文案", "售后说明"],
        )
    )
    return modules


def build_search_terms(keywords: list[KeywordMetric], rules: PlatformRules, facts_text: str) -> str:
    """Search Terms：去重、剔除已出现在标题/五点中的词、按 UTF-8 字节限制裁剪。"""
    seen: set[str] = set()
    chosen: list[str] = []
    lower_facts = facts_text.lower()
    for keyword in keywords:
        term = keyword.keyword.strip()
        if not term or term.lower() in seen:
            continue
        if term.lower() in lower_facts:
            continue
        seen.add(term.lower())
        candidate = " ".join(chosen + [term])
        if byte_len_utf8(candidate) > rules.search_terms_max_bytes:
            continue
        chosen.append(term)
    return " ".join(chosen)


# ---------------------------------------------------------------------------
# 质检
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(mm|cm|m|ml|l|g|kg|oz|lb|lbs|inch|in|ft|v|w|mah|hours?|hrs?|days?|years?|pcs?|pieces?|pack|%|x)?",
    re.IGNORECASE,
)


def _extract_numbers(text: str) -> list[tuple[str, str]]:
    """提取文本中的数字及其单位，用于比对输入事实。"""
    found: list[tuple[str, str]] = []
    for match in _NUMBER_RE.finditer(text):
        unit = (match.group(2) or "").lower()
        value = match.group(1)
        # 忽略纯序号类数字（如 1. / #2）与常见的列表编号
        found.append((value, unit))
    return found


@dataclass
class AuditContext:
    allowed_numbers: set[str]
    allowed_phrases: set[str]
    banned: BannedTermRules
    rules: PlatformRules


def _collect_allowed_numbers(product: OwnProduct) -> set[str]:
    """允许出现的数字全部来自输入资料。"""
    allowed: set[str] = set()
    for key, value in product.specifications.items():
        for number, unit in _extract_numbers(f"{key} {value}"):
            allowed.add(number)
            if unit:
                allowed.add(f"{number}{unit}")
    for text in product.key_features + product.materials + product.certifications:
        for number, unit in _extract_numbers(text):
            allowed.add(number)
            if unit:
                allowed.add(f"{number}{unit}")
    if product.price is not None:
        allowed.add(str(product.price))
    return allowed


def _sentence_context(text: str, start: int, end: int) -> str:
    left = max(text.rfind("\n", 0, start), text.rfind("。", 0, start), text.rfind("；", 0, start))
    return text[left + 1: end + 40]


def audit_declarations(
    text: str,
    location: str,
    context: AuditContext,
) -> list[QualityIssue]:
    """声明审计：无依据数字、绝对化、认证/功效、禁用词。"""
    issues: list[QualityIssue] = []
    if not text.strip():
        return issues

    # 1) 数字必须有输入依据
    for number, unit in _extract_numbers(text):
        if number in context.allowed_numbers or (unit and f"{number}{unit}" in context.allowed_numbers):
            continue
        # 纯年份或列表编号豁免
        if len(number) == 4 and number.startswith(("19", "20")):
            continue
        if number in {"1", "2", "3", "4", "5"} and not unit:
            continue
        issues.append(
            QualityIssue(
                code=IssueCode.UNSUPPORTED_NUMBER,
                severity=Severity.ERROR,
                message=f"出现输入资料中没有的数字「{number}{unit}」，请确认是否为编造参数",
                location=location,
                excerpt=truncate(_sentence_context(text, 0, 0), 120, ""),
                suggestion="删除该数字，或在商品规格/卖点中补充真实数据后重新生成",
            )
        )

    # 2) 禁用词（平台/品牌）
    for term in context.banned.matches(text):
        issues.append(
            QualityIssue(
                code=IssueCode.BANNED_TERM,
                severity=term.severity,
                message=f"命中{term.category_label}禁用词：{term.term}",
                location=location,
                excerpt=term.term,
                suggestion="替换为中性、可验证的描述，或确认品牌/平台是否允许",
            )
        )

    # 3) 认证与功效：即使没进禁用词库，也要求输入中有对应证据
    cert_patterns = re.compile(
        r"\b(fda|ce|ul|etl|fcc|rohs|reach|iso\s?\d{3,5}|bpa[- ]?free|food[- ]?grade)\b",
        re.IGNORECASE,
    )
    for match in cert_patterns.finditer(text):
        token = match.group(1).lower()
        if any(token in cert.lower() for cert in getattr(context, "certifications", [])):
            continue
        # 认证信息在输入中不存在 -> 未验证
        if not any(token in phrase.lower() for phrase in context.allowed_phrases):
            issues.append(
                QualityIssue(
                    code=IssueCode.UNVERIFIED_CERTIFICATION,
                    severity=Severity.ERROR,
                    message=f"出现认证表述「{match.group(1)}」，但输入资料未提供对应证书",
                    location=location,
                    excerpt=match.group(0),
                    suggestion="提供证书编号并在 certifications 中登记，或删除该表述",
                )
            )

    efficacy_patterns = re.compile(
        r"\b(kills?|eliminates?|prevents?|cures?|treats?|heals?|disinfects?|steriliz(?:e|es))\b",
        re.IGNORECASE,
    )
    for match in efficacy_patterns.finditer(text):
        issues.append(
            QualityIssue(
                code=IssueCode.UNVERIFIED_EFFICACY,
                severity=Severity.ERROR,
                message=f"出现功效承诺「{match.group(0)}」，需要检测报告或平台许可",
                location=location,
                excerpt=match.group(0),
                suggestion="删除功效承诺，改为描述产品客观材质/结构",
            )
        )

    # 4) 绝对化表述
    for superlative in context.banned.universal_superlatives:
        if re.search(rf"(?<![a-z]){re.escape(superlative)}(?![a-z])", text, re.IGNORECASE):
            issues.append(
                QualityIssue(
                    code=IssueCode.UNSUPPORTED_SUPERLATIVE,
                    severity=Severity.WARNING,
                    message=f"出现绝对化表述「{superlative}」，通常需要可验证依据",
                    location=location,
                    excerpt=superlative,
                    suggestion="改为具体、可验证的表述（例如给出测试条件与结果）",
                )
            )

    # 5) 全大写/表情/特殊符号（按平台规则）
    if not context.rules.allow_all_caps and location != "description":
        for word in re.findall(r"\b[A-Z]{4,}\b", text):
            issues.append(
                QualityIssue(
                    code=IssueCode.UNSUPPORTED_CLAIM,
                    severity=Severity.WARNING,
                    message=f"出现全大写词「{word}」",
                    location=location,
                    excerpt=word,
                    suggestion="平台通常限制全大写，请改为正常大小写",
                )
            )
    if not context.rules.allow_emoji and contains_emoji(text):
        issues.append(
            QualityIssue(
                code=IssueCode.UNSUPPORTED_CLAIM,
                severity=Severity.WARNING,
                message="文案包含表情符号",
                location=location,
                suggestion="删除表情符号，平台上架通常不支持或影响专业度",
            )
        )
    for char in context.rules.prohibited_characters:
        if char in text:
            issues.append(
                QualityIssue(
                    code=IssueCode.UNSUPPORTED_CLAIM,
                    severity=Severity.WARNING,
                    message=f"包含平台规则限制的字符「{char}」",
                    location=location,
                    excerpt=char,
                    suggestion="替换或删除特殊字符",
                )
            )
    return issues


def check_keyword_stuffing(
    text: str,
    keywords: list[str],
    max_repeat_per_100_words: int,
    location: str,
) -> list[QualityIssue]:
    words = re.findall(r"[A-Za-z\u4e00-\u9fff]+", text.lower())
    word_count = max(1, len(words))
    issues: list[QualityIssue] = []
    for keyword in keywords:
        if not keyword.strip():
            continue
        pattern = re.escape(keyword.strip().lower())
        occurrences = len(re.findall(pattern, " ".join(words)))
        density = occurrences / word_count * 100
        allowed = max_repeat_per_100_words * word_count / 100
        if occurrences > max(allowed, 2) or density > max_repeat_per_100_words:
            issues.append(
                QualityIssue(
                    code=IssueCode.KEYWORD_STUFFING,
                    severity=Severity.WARNING,
                    message=f"关键词「{keyword}」重复 {occurrences} 次，可能构成堆砌",
                    location=location,
                    excerpt=keyword,
                    suggestion="减少重复，改用同义词或自然句式",
                )
            )
    return issues


def run_quality_check(
    draft: ListingDraft,
    product: OwnProduct,
    rules: PlatformRules,
    banned: BannedTermRules,
) -> QualityCheck:
    allowed_numbers = _collect_allowed_numbers(product)
    allowed_phrases = set(product.certifications) | set(product.key_features) | set(product.materials)
    context = AuditContext(
        allowed_numbers=allowed_numbers,
        allowed_phrases=allowed_phrases,
        banned=banned,
        rules=rules,
    )
    # 让 certifications 能被审计函数读取
    setattr(context, "certifications", product.certifications)

    issues: list[QualityIssue] = []
    lengths: list[SectionLength] = []

    # 标题
    title_len = char_len(draft.title)
    lengths.append(
        SectionLength(
            section="title",
            length=title_len,
            limit=rules.title_max_chars,
            within_limit=title_len <= rules.title_max_chars,
        )
    )
    issues.extend(audit_declarations(draft.title, "title", context))
    if title_len > rules.title_max_chars:
        issues.append(
            QualityIssue(
                code=IssueCode.OVER_LENGTH,
                severity=Severity.ERROR,
                message=f"标题 {title_len} 字符，超过 {'规则配置的 ' + str(rules.title_max_chars) + ' 字符'} 上限",
                location="title",
                suggestion="精简标题或调整 package/spec 描述",
            )
        )

    # 五点
    for index, bullet in enumerate(draft.bullets, start=1):
        text = f"{bullet.headline} {bullet.body}"
        loc = f"bullet[{index}]"
        bullet_len = char_len(text)
        lengths.append(
            SectionLength(
                section=loc,
                length=bullet_len,
                limit=rules.bullet_max_chars,
                within_limit=bullet_len <= rules.bullet_max_chars,
            )
        )
        issues.extend(audit_declarations(text, loc, context))
        if bullet_len > rules.bullet_max_chars:
            issues.append(
                QualityIssue(
                    code=IssueCode.OVER_LENGTH,
                    severity=Severity.ERROR,
                    message=f"第 {index} 条五点 {bullet_len} 字符，超过上限 {rules.bullet_max_chars}",
                    location=loc,
                )
            )
        if "待补充卖点" in bullet.headline:
            issues.append(
                QualityIssue(
                    code=IssueCode.MISSING_FACT,
                    severity=Severity.WARNING,
                    message=f"第 {index} 条为占位内容：输入资料不足以生成该卖点",
                    location=loc,
                    suggestion="补充商品资料后重新生成",
                )
            )

    # 描述
    desc_len = char_len(draft.description)
    lengths.append(
        SectionLength(
            section="description",
            length=desc_len,
            limit=rules.description_max_chars,
            within_limit=desc_len <= rules.description_max_chars,
        )
    )
    issues.extend(audit_declarations(draft.description, "description", context))

    # Search Terms 字节限制
    search_bytes = byte_len_utf8(draft.search_terms)
    lengths.append(
        SectionLength(
            section="search_terms",
            length=search_bytes,
            limit=rules.search_terms_max_bytes,
            within_limit=search_bytes <= rules.search_terms_max_bytes,
        )
    )
    if search_bytes > rules.search_terms_max_bytes:
        issues.append(
            QualityIssue(
                code=IssueCode.OVER_LENGTH,
                severity=Severity.ERROR,
                message=f"Search Terms {search_bytes} 字节，超过 {rules.search_terms_max_bytes} 字节上限",
                location="search_terms",
            )
        )

    # 关键词堆砌（针对标题 + 五点）
    combined = draft.title + " " + " ".join(f"{b.headline} {b.body}" for b in draft.bullets)
    issues.extend(
        check_keyword_stuffing(
            combined,
            list(draft.keywords_used),
            rules.max_keyword_repeat_per_100_words,
            "title+bullets",
        )
    )

    # 去重
    deduped: list[QualityIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (issue.code.value, issue.location or "", issue.message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)

    errors = [i for i in deduped if i.severity == Severity.ERROR]
    passed = not errors

    policy_disclaimer = (
        "本质检仅依据激浪内部可配置规则与输入资料进行一致性检查，"
        "未对平台最新政策做实时核验，不构成合规承诺。"
    )
    if rules.disclaimer:
        policy_disclaimer += " 规则文件说明：" + rules.disclaimer

    rules_applied = [
        f"平台/站点：{rules.platform.upper()} / {rules.marketplace}",
        f"标题上限：{rules.title_max_chars} 字符",
        f"五点上限：{rules.bullet_max_chars} 字符 × {rules.bullet_count} 条",
        f"描述上限：{rules.description_max_chars} 字符",
        f"Search Terms 上限：{rules.search_terms_max_bytes} 字节",
        f"规则核验状态：{'已核验' if rules.verified else '未核验（示例配置）'}",
    ]
    if banned.disclaimer:
        rules_applied.append("禁用词说明：" + banned.disclaimer)

    return QualityCheck(
        passed=passed,
        issues=deduped,
        section_lengths=lengths,
        rules_applied=rules_applied,
        policy_disclaimer=policy_disclaimer,
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def generate_listing(
    request: ListingGenerationRequest,
    *,
    analysis_report: dict | None = None,
    ruleset: RuleSet | None = None,
    engine: str = "rule",
    engine_version: str = "0.1.0",
) -> ListingDraft:
    """生成 Listing 草稿（标题、五点、描述、A+ 大纲、Search Terms、质检）。"""
    ruleset = ruleset or get_rules()
    product = request.product
    rules = ruleset.platform_rules(product.target_platform, request.marketplace or product.marketplace)
    banned = ruleset.banned_terms(request.banned_terms + product.banned_terms)

    ledger = build_fact_ledger(product)
    report = analysis_report or request.analysis_report or {}

    # 分析报告中的可用信息
    differentiation_angles: list[str] = []
    insight_modules: dict[str, list[str]] = {}
    report_id = None
    if report:
        report_id = report.get("report_id")
        for item in report.get("differentiation_opportunities", []) or []:
            angle = item.get("angle")
            if angle:
                differentiation_angles.append(angle)
        review = report.get("review_insights") or {}
        insight_modules["pain_points"] = [
            p.get("label") for p in review.get("low_rating_themes", []) or [] if p.get("label")
        ]
        insight_modules["needs"] = [
            n.get("label") for n in review.get("needs", []) or [] if n.get("label")
        ]

    # 关键词：只有带指标或明确提供的词才会进入文案
    keywords = list(request.keywords)
    if not keywords:
        keyword_analysis = report.get("keyword_analysis") or {}
        for item in keyword_analysis.get("opportunities", []) or []:
            if item.get("has_metrics"):
                keywords.append(
                    KeywordMetric(
                        keyword=item["keyword"],
                        search_volume=item.get("search_volume"),
                        rank=item.get("rank"),
                        relevance=item.get("relevance"),
                        competition=item.get("competition"),
                        source="analysis_report",
                    )
                )
    keyword_strings = [k.keyword for k in keywords if k.keyword.strip()]
    # 只有带量化指标的关键词才允许进入标题，避免把无数据的猜测词写成卖点。
    metric_keywords = [k.keyword for k in keywords if k.has_metrics and k.keyword.strip()]

    # 生成各部分
    title = build_title(product, rules, ledger, metric_keywords)
    bullets = build_bullets(product, rules, ledger, insight_modules.get("pain_points"))
    description = build_description(product, rules, ledger, differentiation_angles, request.language)
    a_plus = build_a_plus_outline(product, insight_modules, bool(product.specifications))
    search_terms = build_search_terms(
        keywords,
        rules,
        facts_text=" ".join([title] + [f"{b.headline} {b.body}" for b in bullets] + [description]),
    )

    draft = ListingDraft(
        listing_id=uuid.uuid4().hex,
        product_name=product.name,
        platform=product.target_platform,
        marketplace=rules.marketplace,
        language=request.language,
        title=title,
        bullets=bullets,
        description=description,
        a_plus_outline=a_plus,
        search_terms=search_terms,
        keywords_used=[k for k in keyword_strings if k.lower() in (title + " " + description + " " + search_terms).lower()],
        keyword_layout_notes=[
            "关键词仅使用用户提供或有指标的数据，不推断搜索量",
            f"Search Terms 使用 {byte_len_utf8(search_terms)}/{rules.search_terms_max_bytes} 字节",
        ],
        fact_ledger=[{"statement": s, "source": src} for s, src in ledger.facts.items()],
        pending_confirmations=list(ledger.pending),
        quality_check=QualityCheck(passed=False),
        differentiation_used=differentiation_angles[:5],
        analysis_report_id=report_id,
        limitations=[
            "本 Listing 为规则引擎生成的草稿，需人工润色与平台政策复核",
            "所有商品事实来自输入资料；未提供的属性已列入待确认，未做补写",
        ],
    )
    draft.quality_check = run_quality_check(draft, product, rules, banned)
    draft.engine = engine
    draft.engine_version = engine_version
    data_source = request.data_source or "manual"
    is_sample = data_source == "demo" or any(k.source == "demo" for k in keywords)
    draft.data_provenance = ListingProvenance(
        data_source=data_source,
        is_demo=is_sample,
        notes=[
            "商品事实来自本次填写的商品资料，未提供项列为待确认",
            (
                "关键词数据包含示例数据，文案中的关键词不代表真实搜索量或排名"
                if is_sample
                else "关键词仅使用用户提供的数据，未推断搜索量或排名"
            ),
        ],
    )
    return draft


__all__ = [
    "FactLedger",
    "audit_declarations",
    "build_a_plus_outline",
    "build_bullets",
    "build_description",
    "build_fact_ledger",
    "build_search_terms",
    "build_title",
    "check_keyword_stuffing",
    "generate_listing",
    "run_quality_check",
]
