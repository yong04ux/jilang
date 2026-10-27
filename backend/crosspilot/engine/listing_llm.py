"""Listing 生成：LLM + 事实接地（替换原来的模板拼装）。

流程
----
1. ``build_fact_sheet``  从商品资料抽事实（带 fact_id），缺失项不补全；
2. ``generate_with_llm`` 让模型**只引用 fact_id** 产出目标语言文案；
3. ``validate_and_repair`` 逐条断言对齐 fact_id，出现台账外数字/认证即报错；
4. ``check_limits``      按站点字符/字节限制裁剪或标记；
5. ``assemble``          组装成 ListingDraft，附带台账、待确认、质检结果。

降级
----
没有 API Key 或调用失败时，退化为 ``rule_fallback``：使用事实原文拼装，
**不做机器翻译**，并在结果中明确标注"未使用模型，文案为事实直出，需人工改写"。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from .facts import FactKind, FactSheet, allowed_numeric_equivalents, build_fact_sheet
from ..llm.llm import DeepSeekClient, LLMError
from ..market.marketplaces import MarketplaceProfile, aplus_specs_for, get_marketplace
from ..models import (
    APlusModule,
    BulletPoint,
    IssueCode,
    ListingDraft,
    ListingGenerationRequest,
    QualityCheck,
    QualityIssue,
    SectionLength,
    Severity,
)
from .rules import BannedTermRules, RuleSet, get_rules
from .textutils import byte_len_utf8, char_len, contains_cjk

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

# 内部属性键 -> 面向用户的中文标签
MISSING_LABELS = {
    "size": "尺寸",
    "material": "材质",
    "capacity": "容量/净含量",
    "color": "颜色",
    "weight": "重量",
    "quantity": "数量/套装件数",
}

SYSTEM_PROMPT = """你是资深亚马逊 Listing 文案专家，服务跨境电商卖家。

铁律（违反即失败）：
1. 只能使用【事实清单】中标注了 fact_id 的信息。禁止编造任何规格、尺寸、容量、
   材质、认证、销量、排名、获奖、用户数量。
2. 事实清单里没有的信息，一律不要写。宁可句子短，也不要补全。
3. 禁止医疗/功效/绝对化表述（cure, treat, best, #1, 100%, guaranteed, FDA approved 等），
   除非事实清单中明确列出了该认证。
4. 输出语言必须是 {language}，不要混入其他语言。
5. 不要出现价格、促销、包邮、限时等词。
6. 每条文案必须能在 fact_ids 中给出其依据；没有依据的内容直接不写。

风格要求：
- 亚马逊标题：品牌 + 核心品类词 + 关键规格/差异点，自然可读，不堆砌关键词；
- 五点描述：每点"利益点开头 + 事实支撑"，避免空洞形容词；
- 产品描述：场景化说明 + 可验证信息；
- 不要用营销腔，不要重复同一卖点。"""

USER_PROMPT_TEMPLATE = """请为以下商品生成亚马逊 Listing。

【目标站点】{marketplace_label}，语言：{language}
【目标人群】{audience}
【平台限制】标题 ≤ {title_max} 字符；每条五点 ≤ {bullet_max} 字符，共 {bullet_count} 条；
           描述 ≤ {desc_max} 字符
【度量体系】{measurement}（如需换算单位，只能在事实数值基础上换算，不得改变数量）

【事实清单】（唯一可用信息源）
{fact_block}

【缺失的关键属性】（不得编造，也不要出现在文案里）
{missing}

【竞品差异化方向】（仅用于决定"强调什么"，不得当作事实写入）
{differentiation}

【关键词】（用于自然布局，不得堆砌；无搜索量数据不代表无用，只是未提供指标）
{keywords}

请输出 JSON：
{{
  "title": "string",
  "bullets": [{{"headline": "string", "body": "string", "fact_ids": ["F01"]}}],
  "description": "string",
  "search_terms": "string",
  "a_plus": [{{"module_type": "hero_banner", "title": "string", "content_outline": ["..."], "assets_needed": ["..."], "fact_ids": ["S01"]}}],
  "used_fact_ids": ["F01", "S01"],
  "notes": "如有信息不足处，在此说明（不要写进正文）"
}}
"""


@dataclass
class GeneratedContent:
    """LLM 返回并解析后的原始内容（尚未做长度裁剪与最终组装）。"""

    title: str = ""
    bullets: list[dict[str, Any]] = field(default_factory=list)
    description: str = ""
    search_terms: str = ""
    a_plus: list[dict[str, Any]] = field(default_factory=list)
    used_fact_ids: list[str] = field(default_factory=list)
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 事实对齐校验
# ---------------------------------------------------------------------------

_CLAIM_NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(ml|毫升|l|升|oz|盎司|g|克|kg|千克|cm|厘米|mm|毫米|inch|in|英寸|lb|lbs|磅|ft|mah|w|瓦|v|伏|%|hours?|hrs?|days?|years?)?", re.IGNORECASE)

# 认证词的中英文对照：事实里写中文、文案用英文时，应视为同一断言（转述），
# 而不是"新增认证"。只有两边都没有的认证词才是真的无依据。
_CERT_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "foodgrade": ("食品级", "food grade", "food-grade"),
    "bpa": ("bpa", "双酚A", "不含双酚"),
    "fda": ("fda", "美国食品药品"),
    "ce": ("ce", "欧盟认证"),
    "rohs": ("rohs", "有害物质限用"),
    "iso": ("iso", "iso认证"),
}

# 这些表述属于"材质/工艺描述"，不是需要证书的认证声明。
# 例："食品级 304 不锈钢"是材质说明，行业惯例不要求附证书；
# 但 "FDA approved" 这类明确宣称必须要有证书。
_DESCRIPTIVE_MATERIAL_TERMS = ("foodgrade",)


def _cert_declared(name: str, cert_text: str, fact_corpus: str) -> bool:
    """判断某个认证词是否已在事实层中出现（含中英文转述）。"""
    variants = _CERT_EQUIVALENTS.get(name, (name,))
    corpus = f"{cert_text} {fact_corpus}".lower()
    return any(v.lower() in corpus for v in variants)


# 认证缩写必须独立成词，且排除 common words：
#   - "reach" 常作普通动词（reach the bottom），不能当 REACH 认证
#   - "ce"/"ul" 太短，必须大写且独立
_CERT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("fda", re.compile(r"\bFDA\b")),
    ("ce", re.compile(r"\bCE\b(?=\s*(?:mark|certif|approved|compliant|tested))")),
    ("ukca", re.compile(r"\bUKCA\b")),
    ("ul", re.compile(r"\bUL\b(?=\s*(?:listed|certif|approved))")),
    ("etl", re.compile(r"\bETL\b(?=\s*(?:listed|certif|approved))")),
    ("fcc", re.compile(r"\bFCC\b")),
    ("rohs", re.compile(r"\bRoHS\b", re.IGNORECASE)),
    ("reach", re.compile(r"\bREACH\b")),
    ("iso", re.compile(r"\bISO\s?\d{3,5}\b")),
    ("bpa", re.compile(r"\bBPA[-\s]?free\b", re.IGNORECASE)),
    ("foodgrade", re.compile(r"\bfood[-\s]?grade\b", re.IGNORECASE)),
    ("hypoallergenic", re.compile(r"\bhypoallergenic\b", re.IGNORECASE)),
)

# 功效词：排除常见的中性用法（prevent leaks / prevent damage 属于机械功能描述）
_EFFICACY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(kills?|eliminates?|cures?|treats?|heals?|disinfects?|sterilizes?)\b", re.IGNORECASE),
    re.compile(r"\bantibacterial\b", re.IGNORECASE),
    re.compile(r"\bprevent(?:s|ed|ing)?\s+(?:disease|illness|infection|bacteria|germs?|mold|mould)\b", re.IGNORECASE),
)
_SUPERLATIVE_RE = re.compile(r"\b(best|greatest|perfect|unbeatable|world'?s|#1|number one|no\.?\s?1|guaranteed|finest|superior to all)\b", re.IGNORECASE)
_PROMO_RE = re.compile(r"\b(free shipping|limited time|sale|discount|cheapest|lowest price|buy now|money back)\b", re.IGNORECASE)


def _fact_numbers(sheet: FactSheet) -> tuple[set[str], set[str]]:
    """事实层允许出现的数字与单位。"""
    numbers: set[str] = set()
    for fact in sheet.facts:
        numbers.update(fact.numbers)
    return numbers, set()


def audit_claim(
    text: str,
    sheet: FactSheet,
    *,
    banned: BannedTermRules,
    location: str,
) -> list[QualityIssue]:
    """逐条检查一段文案是否越出事实边界。"""
    issues: list[QualityIssue] = []
    allowed_numbers, _ = _fact_numbers(sheet)
    # 允许模型做等价单位换算（750ml -> 25.4oz、26cm -> 10.2in）
    allowed_numbers = allowed_numbers | allowed_numeric_equivalents(sheet)
    # 事实原文里已经出现的词（如"食品级 304 不锈钢"）不算"新增断言"
    fact_corpus = " ".join(f"{f.label} {f.value}" for f in sheet.facts).lower()

    # 1) 数字必须来自事实层（排除序号类数字与年份）
    for match in _CLAIM_NUMBER_RE.finditer(text):
        value = match.group(1)
        unit = (match.group(2) or "").lower()
        if value in allowed_numbers:
            continue
        if len(value) == 4 and value.startswith(("19", "20")):
            continue
        if value in {"1", "2", "3", "4", "5"} and not unit:
            continue
        if unit == "%" and value in {"100"}:
            # 100% 属于绝对化，单独在下面判定
            pass
        issues.append(
            QualityIssue(
                code=IssueCode.UNSUPPORTED_NUMBER,
                severity=Severity.ERROR,
                message=f"出现事实清单中没有的数字「{value}{unit}」",
                location=location,
                excerpt=match.group(0),
                suggestion="删除该数字，或在商品规格中补充真实数据后重新生成",
            )
        )

    # 2) 认证：只有"新增"的认证断言才算问题
    #    - 事实层确有该认证 -> 通过；
    #    - 事实原文本身就含该词（如"食品级 304 不锈钢"）-> 属于转述，不新增断言；
    #    - 两者都不满足 -> 判为未验证认证。
    cert_text = " ".join(f.value for f in sheet.of_kind(FactKind.CERTIFICATION))
    for name, pattern in _CERT_PATTERNS:
        for match in pattern.finditer(text):
            if _cert_declared(name, cert_text, fact_corpus):
                continue
            # 材质类描述（食品级/不含BPA）不是需要证书的认证声明，
            # 但仍提示人工对照平台规则确认，避免误判也为合规留痕。
            descriptive = name in _DESCRIPTIVE_MATERIAL_TERMS
            issues.append(
                QualityIssue(
                    code=IssueCode.UNVERIFIED_CERTIFICATION,
                    severity=Severity.WARNING if descriptive else Severity.ERROR,
                    message=(
                        f"出现材质表述「{match.group(0)}」，未提供检测报告；"
                        "平台可能要求可验证依据"
                        if descriptive
                        else f"出现认证表述「{match.group(0)}」，但事实清单未提供对应证书"
                    ),
                    location=location,
                    excerpt=match.group(0),
                    suggestion=(
                        "确认该材质描述与实物一致，并准备可提供的检测依据"
                        if descriptive
                        else "在 certifications 中登记证书并重新生成，或删除该表述"
                    ),
                )
            )

    # 3) 功效承诺（仅真正的医疗/杀菌类表述）
    for pattern in _EFFICACY_PATTERNS:
        for match in pattern.finditer(text):
            issues.append(
                QualityIssue(
                    code=IssueCode.UNVERIFIED_EFFICACY,
                    severity=Severity.ERROR,
                    message=f"出现功效承诺「{match.group(0)}」，需要检测报告或平台许可",
                    location=location,
                    excerpt=match.group(0),
                    suggestion="改为客观描述材质与结构",
                )
            )

    # 4) 绝对化
    for match in _SUPERLATIVE_RE.finditer(text):
        issues.append(
            QualityIssue(
                code=IssueCode.UNSUPPORTED_SUPERLATIVE,
                severity=Severity.WARNING,
                message=f"出现绝对化表述「{match.group(0)}」",
                location=location,
                excerpt=match.group(0),
                suggestion="改为具体、可验证的表述",
            )
        )

    # 5) 促销词
    for match in _PROMO_RE.finditer(text):
        issues.append(
            QualityIssue(
                code=IssueCode.UNSUPPORTED_CLAIM,
                severity=Severity.WARNING,
                message=f"出现促销/价格类表述「{match.group(0)}」",
                location=location,
                excerpt=match.group(0),
                suggestion="删除促销表述，平台通常限制此类用词",
            )
        )

    # 6) 禁用词（平台/品牌）
    for term in banned.matches(text):
        issues.append(
            QualityIssue(
                code=IssueCode.BANNED_TERM,
                severity=term.severity,
                message=f"命中{term.category_label}禁用词：{term.term}",
                location=location,
                excerpt=term.term,
                suggestion="替换为中性、可验证的描述",
            )
        )

    # 7) 语言校验：目标语言与文本语言不一致
    if location != "search_terms":
        has_cjk = contains_cjk(text)
        # 英文站点出现中文 -> 语言不匹配（中文站点反过来也检查）
        if _expects_latin(text) and has_cjk and len(text) > 20:
            issues.append(
                QualityIssue(
                    code=IssueCode.UNSUPPORTED_CLAIM,
                    severity=Severity.ERROR,
                    message="目标语言为英文，但文案中包含中文",
                    location=location,
                    suggestion="重新生成，或在商品资料中提供目标语言的事实描述",
                )
            )
    return issues


def _expects_latin(text: str) -> bool:
    """粗略判断文本主体是否为拉丁字母（用于语言一致性检查）。"""
    latin = sum(1 for c in text if "a" <= c.lower() <= "z")
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return latin > cjk


# 常见占位符：[Brand]、[Product Name]、{brand}、<PRODUCT>
# 只匹配"看起来就是待替换字段"的形态：方括号内为不含数字的纯字母词，
# 避免把 [2-Pack] 这类合法文案误判为错误。
_PLACEHOLDER_RE = re.compile(
    r"\[\s*[A-Za-z][A-Za-z _-]{0,23}\s*\]"   # [Brand] / [Product Name]
    r"|\{\s*[a-z][a-z0-9_]{1,29}\s*\}"        # {brand} / {product_name}
    r"|<\s*[A-Z][A-Z0-9 _-]{1,29}\s*>"        # <PRODUCT>
)


def audit_placeholders(
    title: str,
    bullets: list[BulletPoint],
    description: str,
) -> list[QualityIssue]:
    """拦截未替换的模板占位符。这类文本绝不能进入可发布文案。"""
    issues: list[QualityIssue] = []
    sections: list[tuple[str, str]] = [("title", title), ("description", description)]
    for index, bullet in enumerate(bullets, start=1):
        sections.append((f"bullet[{index}]", f"{bullet.headline} {bullet.body}"))

    for location, text in sections:
        for match in _PLACEHOLDER_RE.finditer(text or ""):
            snippet = match.group(0)
            issues.append(
                QualityIssue(
                    code=IssueCode.PLACEHOLDER_TEXT,
                    severity=Severity.ERROR,
                    message=f"文案中残留未替换的占位符：{snippet}",
                    location=location,
                    excerpt=snippet,
                    suggestion="补齐该字段后重新生成；占位符不允许出现在可发布文案中",
                )
            )
    return issues


# ---------------------------------------------------------------------------
# LLM 生成
# ---------------------------------------------------------------------------


def _build_prompts(
    request: ListingGenerationRequest,
    sheet: FactSheet,
    profile: MarketplaceProfile,
    differentiation: list[str],
    keywords: list[str],
) -> tuple[str, str]:
    product = request.product
    audience = product.target_audience or "（未提供，请勿编造具体人群）"
    missing = "、".join(sheet.missing_critical) if sheet.missing_critical else "无"
    diff_block = "\n".join(f"- {d}" for d in differentiation[:6]) if differentiation else "（未提供竞品分析）"
    keyword_block = "、".join(keywords[:15]) if keywords else "（未提供关键词数据）"
    system = SYSTEM_PROMPT.format(language=profile.language)
    user = USER_PROMPT_TEMPLATE.format(
        marketplace_label=profile.label,
        language=profile.language,
        audience=audience,
        title_max=profile.title_max_chars,
        bullet_max=profile.bullet_max_chars,
        bullet_count=profile.bullet_count,
        desc_max=profile.description_max_chars,
        measurement="英制（inch/oz/lb），可在事实数值基础上换算展示" if profile.measurement_system == "imperial" else "公制（cm/ml/kg）",
        fact_block=sheet.prompt_block(),
        missing=missing,
        differentiation=diff_block,
        keywords=keyword_block,
    )
    # 质量修订（Phase 3）：带着上一版的具体问题重新生成，而不是让它自由发挥。
    # 只在提示词层面加约束——产出结构与首次生成完全一致，因此下游质检不用改。
    revision_notes = [
        str(note).strip() for note in (request.revision_notes or []) if str(note).strip()
    ]
    if revision_notes:
        user += (
            "\n\n【上一版未通过质检，以下问题必须逐条修正】\n"
            + "\n".join(f"- {note}" for note in revision_notes[:8])
            + "\n修正时不得引入事实台账之外的新事实、数字或认证；"
            "无法在不编造的前提下修正的，宁可不写。"
        )
    return system, user


def generate_with_llm(
    client: DeepSeekClient,
    request: ListingGenerationRequest,
    sheet: FactSheet,
    profile: MarketplaceProfile,
    differentiation: list[str],
    keywords: list[str],
) -> tuple[GeneratedContent, Any]:
    system, user = _build_prompts(request, sheet, profile, differentiation, keywords)
    data, result = client.chat_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.5,
        max_tokens=4000,
        schema_hint=(
            '{"title": str, "bullets": [{"headline": str, "body": str, "fact_ids": [str]}], '
            '"description": str, "search_terms": str, '
            '"a_plus": [{"module_type": str, "title": str, "content_outline": [str], '
            '"assets_needed": [str], "fact_ids": [str]}], "used_fact_ids": [str], "notes": str}'
        ),
    )
    content = GeneratedContent(
        title=str(data.get("title", "")).strip(),
        bullets=[b for b in (data.get("bullets") or []) if isinstance(b, dict)],
        description=str(data.get("description", "")).strip(),
        search_terms=str(data.get("search_terms", "")).strip(),
        a_plus=[m for m in (data.get("a_plus") or []) if isinstance(m, dict)],
        used_fact_ids=[str(x) for x in (data.get("used_fact_ids") or [])],
        notes=str(data.get("notes", "")),
        raw=data,
    )
    return content, result


# ---------------------------------------------------------------------------
# 降级：无模型时的事实直出
# ---------------------------------------------------------------------------


def rule_fallback(
    request: ListingGenerationRequest,
    sheet: FactSheet,
    profile: MarketplaceProfile,
) -> GeneratedContent:
    """没有模型时的兜底：只用事实原文拼装。

    注意：这里**不做机器翻译**。如果事实是中文而目标站点是英文，
    直出结果会是中英混排——所以必须显式标注"不可直接发布"，
    并在质检里给出语言不匹配错误，而不是假装能用。
    """
    product = request.product
    title_parts: list[str] = []
    brand = product.brand or (product.name.split()[0] if product.name.split() else None)
    if brand and brand.lower() not in product.name.lower():
        title_parts.append(brand)
    title_parts.append(product.name)
    # 只追加"看起来与目标语言一致"的规格，避免中英混排
    latin_only = _expects_latin(product.name + " " + (product.brand or ""))
    for fact in sheet.of_kind(FactKind.ATTRIBUTE)[:2]:
        if latin_only and contains_cjk(f"{fact.label} {fact.value}"):
            continue
        title_parts.append(f"{fact.label} {fact.value}")
    title = " - ".join(p for p in title_parts if p)

    bullets: list[dict[str, Any]] = []
    features = sheet.of_kind(FactKind.FEATURE)
    attributes = sheet.of_kind(FactKind.ATTRIBUTE)

    # 降级时不丢弃事实（否则五点会是空的），而是原样保留，
    # 由质检器的"语言不匹配"错误明确告诉用户该内容不可直接发布。
    usable_features = list(features)
    if usable_features:
        bullets.append(
            {
                "headline": usable_features[0].value[:80],
                "body": " ".join(f.value for f in usable_features[1:3]) or usable_features[0].value,
                "fact_ids": [f.fact_id for f in usable_features[:3]],
            }
        )
    usable_attrs = [f for f in attributes if not (latin_only and contains_cjk(f"{f.label} {f.value}"))]
    if usable_attrs:
        bullets.append(
            {
                "headline": "Specifications" if latin_only else "规格",
                "body": "; ".join(f"{f.label} {f.value}" for f in usable_attrs[:6])
                if latin_only
                else "；".join(f"{f.label} {f.value}" for f in usable_attrs[:6]),
                "fact_ids": [f.fact_id for f in usable_attrs[:6]],
            }
        )

    description_lines = [product.name]
    for fact in (usable_features + usable_attrs)[:8]:
        description_lines.append(f"- {fact.label}: {fact.value}")
    description_lines.append(
        "All details above come from the product fact sheet. "
        "Unlisted specifications are marked as pending confirmation and were not filled in."
    )
    return GeneratedContent(
        title=title,
        bullets=bullets,
        description="\n".join(description_lines),
        search_terms="",
        a_plus=[],
        used_fact_ids=[f.fact_id for f in (usable_features + usable_attrs)],
        notes="未调用模型：当前为事实直出的兜底草案，必须人工改写后再使用。",
    )


# ---------------------------------------------------------------------------
# 长度与结构处理
# ---------------------------------------------------------------------------


def _trim_to_limit(text: str, limit: int) -> str:
    if char_len(text) <= limit:
        return text
    clipped = text[: max(0, limit - 1)].rstrip()
    # 尽量在词边界截断
    cut = clipped.rfind(" ")
    if cut > limit * 0.6:
        clipped = clipped[:cut]
    return clipped.rstrip(" ,;:-") + "…"


def _resolve_fact_ids(raw_ids: list[Any], sheet: FactSheet) -> list[str]:
    """把模型返回的 fact 引用映射到真实 ID。

    模型经常只写 ``F01`` 或 ``F1``，甚至写卖点原文。这里做三档匹配：
    精确 ID -> 去零补零归一 -> 文本包含。匹配不上就丢弃（宁缺毋滥）。
    """
    by_id = sheet.by_id()
    resolved: list[str] = []
    for raw in raw_ids:
        token = str(raw).strip()
        if not token:
            continue
        if token in by_id:
            resolved.append(token)
            continue
        # 归一化：F1 -> F01
        match = re.fullmatch(r"([A-Za-z]+)0*(\d+)", token)
        if match:
            prefix, number = match.group(1).upper(), int(match.group(2))
            candidate = f"{prefix}{number:02d}"
            if candidate in by_id:
                resolved.append(candidate)
                continue
        # 文本包含匹配
        hit = next(
            (fid for fid, fact in by_id.items() if token and (token in fact.value or fact.value in token)),
            None,
        )
        if hit:
            resolved.append(hit)
    return list(dict.fromkeys(resolved))


def _build_bullets(
    raw_bullets: list[dict[str, Any]],
    profile: MarketplaceProfile,
    sheet: FactSheet,
) -> list[BulletPoint]:
    by_id = sheet.by_id()
    bullets: list[BulletPoint] = []
    for index, item in enumerate(raw_bullets[: profile.bullet_count], start=1):
        headline = str(item.get("headline", "")).strip()
        body = str(item.get("body", "")).strip()
        fact_ids = _resolve_fact_ids(list(item.get("fact_ids") or []), sheet)
        if not headline and not body:
            continue
        total = char_len(headline) + char_len(body)
        if total > profile.bullet_max_chars:
            headline = _trim_to_limit(headline, 100)
            body = _trim_to_limit(body, max(40, profile.bullet_max_chars - char_len(headline) - 1))
        bullets.append(
            BulletPoint(
                headline=headline,
                body=body,
                character_count=char_len(headline) + char_len(body),
                supporting_facts=[f"{by_id[fid].label}：{by_id[fid].value}" for fid in fact_ids],
            )
        )
    return bullets


def _build_a_plus(
    raw_modules: list[dict[str, Any]],
    profile: MarketplaceProfile,
    sheet: FactSheet,
) -> list[APlusModule]:
    specs = aplus_specs_for(profile.code)
    modules: list[APlusModule] = []
    seen: set[str] = set()
    for item in raw_modules:
        module_type = str(item.get("module_type", "")).strip()
        if module_type not in specs or module_type in seen:
            continue
        seen.add(module_type)
        outline = [str(x) for x in (item.get("content_outline") or []) if str(x).strip()]
        assets = [str(x) for x in (item.get("assets_needed") or []) if str(x).strip()]
        modules.append(
            APlusModule(
                module_type=module_type,  # type: ignore[arg-type]
                title=str(item.get("title") or specs[module_type]["title"]),
                purpose=specs[module_type]["purpose"],
                content_outline=outline,
                assets_needed=assets,
            )
        )
    # 补齐必需模块（规格表），但内容只放事实
    if "spec_table" in specs and "spec_table" not in seen:
        modules.append(
            APlusModule(
                module_type="spec_table",
                title=specs["spec_table"]["title"],
                purpose=specs["spec_table"]["purpose"],
                content_outline=[
                    f"{f.label}：{f.value}" for f in sheet.of_kind(FactKind.ATTRIBUTE)
                ] or ["待补充真实规格"],
                assets_needed=["规格表设计稿"],
            )
        )
    return modules


def _build_search_terms(
    raw_terms: str,
    keywords: list[str],
    profile: MarketplaceProfile,
    facts_text: str,
) -> str:
    """Search Terms：去重、剔除已在正文出现的词、按 UTF-8 字节限制。"""
    seen: set[str] = set()
    chosen: list[str] = []
    lower_facts = facts_text.lower()
    candidates = [t for t in re.split(r"[,;]", raw_terms) if t.strip()] + keywords
    for term in candidates:
        cleaned = term.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        if key in lower_facts:
            continue
        seen.add(key)
        candidate = " ".join(chosen + [cleaned])
        if byte_len_utf8(candidate) > profile.search_terms_max_bytes:
            continue
        chosen.append(cleaned)
    return " ".join(chosen)


def _check_limits(
    title: str,
    bullets: list[BulletPoint],
    description: str,
    search_terms: str,
    profile: MarketplaceProfile,
) -> tuple[list[SectionLength], list[QualityIssue]]:
    issues: list[QualityIssue] = []
    lengths = [
        SectionLength(
            section="title",
            length=char_len(title),
            limit=profile.title_max_chars,
            within_limit=char_len(title) <= profile.title_max_chars,
        ),
        SectionLength(
            section="description",
            length=char_len(description),
            limit=profile.description_max_chars,
            within_limit=char_len(description) <= profile.description_max_chars,
        ),
        SectionLength(
            section="search_terms",
            length=byte_len_utf8(search_terms),
            limit=profile.search_terms_max_bytes,
            within_limit=byte_len_utf8(search_terms) <= profile.search_terms_max_bytes,
        ),
    ]
    for index, bullet in enumerate(bullets, start=1):
        lengths.append(
            SectionLength(
                section=f"bullet[{index}]",
                length=bullet.character_count,
                limit=profile.bullet_max_chars,
                within_limit=bullet.character_count <= profile.bullet_max_chars,
            )
        )
    for section in lengths:
        if not section.within_limit:
            issues.append(
                QualityIssue(
                    code=IssueCode.OVER_LENGTH,
                    severity=Severity.ERROR,
                    message=f"{section.section} 长度 {section.length}，超过上限 {section.limit}",
                    location=section.section,
                )
            )
    if len(bullets) < profile.bullet_count:
        issues.append(
            QualityIssue(
                code=IssueCode.EMPTY_SECTION,
                severity=Severity.WARNING,
                message=f"五点只有 {len(bullets)} 条，平台建议 {profile.bullet_count} 条",
                location="bullets",
                suggestion="补充更多可验证卖点后重新生成",
            )
        )
    return lengths, issues


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def generate_listing(
    request: ListingGenerationRequest,
    *,
    analysis_report: dict | None = None,
    client: DeepSeekClient | None = None,
    ruleset: RuleSet | None = None,
    engine: str = "deepseek",
    engine_version: str = "0.2.0",
) -> ListingDraft:
    """生成 Listing。``client`` 为 None 时走事实直出降级。"""
    ruleset = ruleset or get_rules()
    product = request.product
    marketplace_code = (request.marketplace or product.marketplace or "US").upper()
    profile = get_marketplace(marketplace_code)
    banned = ruleset.banned_terms(request.banned_terms + product.banned_terms)

    sheet = build_fact_sheet(product)

    # 竞品分析 -> 差异化方向
    differentiation: list[str] = []
    report_id = None
    report = analysis_report or request.analysis_report or {}
    if report:
        report_id = report.get("report_id")
        for item in report.get("differentiation_opportunities", []) or []:
            angle = item.get("angle")
            if angle:
                differentiation.append(angle)

    keywords = [k.keyword for k in request.keywords if k.keyword.strip()]

    fallback_reason: str | None = None
    content: GeneratedContent
    usage: dict[str, int] = {}
    if client is None:
        content = rule_fallback(request, sheet, profile)
        fallback_reason = "未配置 DeepSeek API Key，已降级为事实直出草案（需人工改写）"
        engine = "rule-fallback"
    else:
        try:
            content, result = generate_with_llm(
                client, request, sheet, profile, differentiation, keywords
            )
            usage = result.usage.as_dict()
        except LLMError as exc:
            content = rule_fallback(request, sheet, profile)
            fallback_reason = f"LLM 调用失败（{exc.kind}）：{exc}"
            engine = "rule-fallback"

    # 组装
    title = _trim_to_limit(content.title or product.name, profile.title_max_chars)
    bullets = _build_bullets(content.bullets, profile, sheet)
    description = _trim_to_limit(content.description, profile.description_max_chars)
    a_plus = _build_a_plus(content.a_plus, profile, sheet)
    facts_text = " ".join([title, description] + [b.headline + " " + b.body for b in bullets])
    search_terms = _build_search_terms(content.search_terms, keywords, profile, facts_text)

    # 质检
    issues: list[QualityIssue] = []
    issues.extend(audit_claim(title, sheet, banned=banned, location="title"))
    for index, bullet in enumerate(bullets, start=1):
        issues.extend(
            audit_claim(
                f"{bullet.headline} {bullet.body}",
                sheet,
                banned=banned,
                location=f"bullet[{index}]",
            )
        )
    issues.extend(audit_claim(description, sheet, banned=banned, location="description"))
    # 模型偶尔会留下 [Brand] / {product_name} 之类占位符，绝不能进入可发布文案
    issues.extend(audit_placeholders(title, bullets, description))
    lengths, limit_issues = _check_limits(title, bullets, description, search_terms, profile)
    issues.extend(limit_issues)

    # 未使用的关键事实提示（不算错误，但提示可能漏卖点）
    used = set(_resolve_fact_ids(list(content.used_fact_ids), sheet))
    # 五点中引用的 fact 也算已使用
    by_id = sheet.by_id()
    for bullet in bullets:
        for fact in by_id.values():
            if f"{fact.label}：{fact.value}" in bullet.supporting_facts:
                used.add(fact.fact_id)
    unused_features = [
        f.value for f in sheet.of_kind(FactKind.FEATURE) if f.fact_id not in used
    ]
    if unused_features:
        issues.append(
            QualityIssue(
                code=IssueCode.MISSING_FACT,
                severity=Severity.WARNING,
                message=f"有 {len(unused_features)} 条卖点未被使用：{'、'.join(unused_features[:3])}",
                location="bullets",
                suggestion="确认是否有意省略，或要求模型覆盖更多卖点",
            )
        )

    # 关键规格缺失：必须进入质检问题，否则"没写规格"的草稿会被判为通过。
    # 规则路径一直有这条，LLM 路径此前漏了（真实模型调用时会静默通过）。
    if sheet.missing_critical:
        labels = [MISSING_LABELS.get(x, x) for x in sheet.missing_critical]
        issues.append(
            QualityIssue(
                code=IssueCode.MISSING_FACT,
                severity=Severity.WARNING,
                message=(
                    f"缺少 {len(labels)} 项关键商品事实：{'、'.join(labels[:4])}"
                    "；文案未编造这些参数，发布前必须补齐"
                ),
                location="listing",
                suggestion="补充规格与认证后重新生成，或确认该商品确实不需要这些参数",
            )
        )

    # 去重：同一问题在多个章节重复出现时合并为一条，并列出所涉章节，
    # 避免同一个数字在 title/bullet/description 各报一次、把面板刷满。
    merged: dict[tuple[str, str, str], QualityIssue] = {}
    order: list[tuple[str, str, str]] = []
    for issue in issues:
        key = (issue.code.value, issue.excerpt or "", issue.message)
        existing = merged.get(key)
        if existing is None:
            merged[key] = issue
            order.append(key)
        else:
            locs = [x for x in (existing.location or "").split("、") if x]
            if issue.location and issue.location not in locs:
                locs.append(issue.location)
                merged[key] = existing.model_copy(update={"location": "、".join(locs)})
    deduped: list[QualityIssue] = [merged[k] for k in order]

    passed = not [i for i in deduped if i.severity == Severity.ERROR]

    pending = [
        f"待确认：{MISSING_LABELS.get(label, label)}（资料中未提供，文案未填写）"
        for label in sheet.missing_critical
    ]
    if not product.certifications:
        pending.append("待确认：认证/检测报告（如需出现 CE/FDA/食品级等表述，必须提供证书编号）")
    pending.extend(sheet.warnings)

    rules_applied = [
        f"站点：{profile.label}（{profile.language}）",
        f"标题 ≤ {profile.title_max_chars} 字符；五点 ≤ {profile.bullet_max_chars} 字符 × {profile.bullet_count}",
        f"描述 ≤ {profile.description_max_chars} 字符；Search Terms ≤ {profile.search_terms_max_bytes} 字节",
        f"生成引擎：{engine}",
        *[f"站点提示：{note}" for note in profile.compliance_notes],
    ]
    if fallback_reason:
        rules_applied.append(f"降级原因：{fallback_reason}")
        # 降级不属于"可发布结果"：必须让人看到
        deduped.append(
            QualityIssue(
                code=IssueCode.MISSING_FACT,
                severity=Severity.WARNING,
                message="本次为降级生成：未调用大模型，文案为事实直出，缺少润色与完整五点",
                location="listing",
                suggestion="配置 CROSSPILOT_DEEPSEEK_API_KEY 后重新生成，或人工改写",
            )
        )
        # 目标语言不是中文，但正文含中文 -> 必须报错（日语文本会含汉字，单独排除）
        if not profile.language.startswith("zh") and profile.language != "ja-JP":
            if any(contains_cjk(b.headline + b.body) for b in bullets):
                deduped.append(
                    QualityIssue(
                        code=IssueCode.UNSUPPORTED_CLAIM,
                        severity=Severity.ERROR,
                        message=f"降级文案包含中文，与目标语言 {profile.language} 不符，不可直接发布",
                        location="bullets",
                        suggestion="配置模型后重新生成，或提供目标语言版本的资料",
                    )
                )
        passed = False

    disclaimer = (
        "本质检基于「事实台账 + 可配置规则」做一致性校验，未对亚马逊最新政策做实时核验，"
        "不构成合规承诺。发布前必须人工逐条复核。"
    )

    return ListingDraft(
        listing_id=uuid.uuid4().hex,
        product_name=product.name,
        platform=product.target_platform,
        marketplace=profile.code,
        language=profile.language,
        title=title,
        bullets=bullets,
        description=description,
        a_plus_outline=a_plus,
        search_terms=search_terms,
        keywords_used=[k for k in keywords if k.lower() in facts_text.lower()],
        keyword_layout_notes=[
            f"Search Terms 使用 {byte_len_utf8(search_terms)}/{profile.search_terms_max_bytes} 字节",
            "关键词只做自然布局，未按搜索量排序（无指标数据）" if not any(
                getattr(k, "has_metrics", False) for k in request.keywords
            ) else "关键词已按提供指标参考布局",
        ],
        fact_ledger=sheet.ledger(),
        pending_confirmations=pending,
        quality_check=QualityCheck(
            passed=passed,
            issues=deduped,
            section_lengths=lengths,
            rules_applied=rules_applied,
            policy_disclaimer=disclaimer,
        ),
        differentiation_used=differentiation[:5],
        analysis_report_id=report_id,
        limitations=[
            "文案由大模型生成，事实来自输入资料；任何未登记在事实台账中的声明都应视为风险",
            "未做原生母语审校，建议目标市场母语者复核语气与用词",
            f"本次生成使用 {usage.get('total_tokens', 0)} tokens（{usage.get('calls', 0)} 次调用）"
            if usage
            else "本次未调用模型",
        ],
        engine=engine,
        engine_version=engine_version,
    )


__all__ = [
    "GeneratedContent",
    "audit_claim",
    "generate_listing",
    "generate_with_llm",
    "rule_fallback",
]
