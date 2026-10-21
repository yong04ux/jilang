"""亚马逊站点配置：语言、度量体系、类目要求与 A+ 模块规范。

原则
----
- 平台差异（站点语言、英制/公制、字符上限）放在配置里，不散落在业务代码；
- 语言只影响"展示与度量"，不影响事实本身（事实来自事实层）；
- 所有限制标注来源与是否核验，禁止声称"完全合规"。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketplaceProfile:
    """一个亚马逊站点的写作与合规配置。"""

    code: str
    label: str
    language: str
    locale_name: str
    measurement_system: str  # metric / imperial
    currency: str
    title_max_chars: int
    bullet_max_chars: int
    description_max_chars: int
    bullet_count: int
    search_terms_max_bytes: int
    aplus_allowed: bool
    # 该市场常用的合规敏感词提示（不是完整清单）
    compliance_notes: tuple[str, ...] = ()
    # 类目相关：A+ 模块建议
    aplus_modules: tuple[str, ...] = (
        "hero_banner",
        "benefit_icons",
        "comparison_chart",
        "spec_table",
        "lifestyle_image",
        "brand_story",
    )

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "language": self.language,
            "locale_name": self.locale_name,
            "measurement_system": self.measurement_system,
            "currency": self.currency,
            "title_max_chars": self.title_max_chars,
            "bullet_max_chars": self.bullet_max_chars,
            "description_max_chars": self.description_max_chars,
            "bullet_count": self.bullet_count,
            "search_terms_max_bytes": self.search_terms_max_bytes,
            "aplus_allowed": self.aplus_allowed,
            "compliance_notes": list(self.compliance_notes),
        }


# 站点配置。字符上限参考亚马逊卖家帮助中心常见条目（2024-2025），
# 但**未逐条核验最新政策**，属于可配置示例，必须由运营最终确认。
MARKETPLACES: dict[str, MarketplaceProfile] = {
    "US": MarketplaceProfile(
        code="US",
        label="Amazon.com（美国）",
        language="en-US",
        locale_name="English (US)",
        measurement_system="imperial",
        currency="USD",
        title_max_chars=200,
        bullet_max_chars=500,
        description_max_chars=2000,
        bullet_count=5,
        search_terms_max_bytes=250,
        aplus_allowed=True,
        compliance_notes=(
            "美国站对医疗、功效、认证类表述审查严格，无证书不得声称 FDA/抗菌/治疗。",
            "加州 Prop 65 相关警示需按产品适用性单独确认。",
        ),
    ),
    "CA": MarketplaceProfile(
        code="CA",
        label="Amazon.ca（加拿大）",
        language="en-CA",
        locale_name="English (Canada)",
        measurement_system="metric",
        currency="CAD",
        title_max_chars=200,
        bullet_max_chars=500,
        description_max_chars=2000,
        bullet_count=5,
        search_terms_max_bytes=250,
        aplus_allowed=True,
        compliance_notes=(
            "加拿大站要求英法双语标签信息（包装层面），Listing 可仅英文但需与包装一致。",
        ),
    ),
    "UK": MarketplaceProfile(
        code="UK",
        label="Amazon.co.uk（英国）",
        language="en-GB",
        locale_name="English (UK)",
        measurement_system="metric",
        currency="GBP",
        title_max_chars=200,
        bullet_max_chars=500,
        description_max_chars=2000,
        bullet_count=5,
        search_terms_max_bytes=250,
        aplus_allowed=True,
        compliance_notes=("英国站需符合 UKCA 相关标识要求，无证书不得声称 CE/UKCA。",),
    ),
    "DE": MarketplaceProfile(
        code="DE",
        label="Amazon.de（德国）",
        language="de-DE",
        locale_name="Deutsch",
        measurement_system="metric",
        currency="EUR",
        title_max_chars=200,
        bullet_max_chars=500,
        description_max_chars=2000,
        bullet_count=5,
        search_terms_max_bytes=250,
        aplus_allowed=True,
        compliance_notes=(
            "德国站受 VerpackG/LUCID 包装法约束，需提供包装注册号。",
            "德语区对绝对化用语（如 'beste'）和功效声称审查严格。",
        ),
    ),
    "FR": MarketplaceProfile(
        code="FR",
        label="Amazon.fr（法国）",
        language="fr-FR",
        locale_name="Français",
        measurement_system="metric",
        currency="EUR",
        title_max_chars=200,
        bullet_max_chars=500,
        description_max_chars=2000,
        bullet_count=5,
        search_terms_max_bytes=250,
        aplus_allowed=True,
        compliance_notes=("法国站要求法语商品信息；环保声明受严格监管。",),
    ),
    "IT": MarketplaceProfile(
        code="IT",
        label="Amazon.it（意大利）",
        language="it-IT",
        locale_name="Italiano",
        measurement_system="metric",
        currency="EUR",
        title_max_chars=200,
        bullet_max_chars=500,
        description_max_chars=2000,
        bullet_count=5,
        search_terms_max_bytes=250,
        aplus_allowed=True,
    ),
    "ES": MarketplaceProfile(
        code="ES",
        label="Amazon.es（西班牙）",
        language="es-ES",
        locale_name="Español",
        measurement_system="metric",
        currency="EUR",
        title_max_chars=200,
        bullet_max_chars=500,
        description_max_chars=2000,
        bullet_count=5,
        search_terms_max_bytes=250,
        aplus_allowed=True,
    ),
    "JP": MarketplaceProfile(
        code="JP",
        label="Amazon.co.jp（日本）",
        language="ja-JP",
        locale_name="日本語",
        measurement_system="metric",
        currency="JPY",
        title_max_chars=200,
        bullet_max_chars=500,
        description_max_chars=2000,
        bullet_count=5,
        search_terms_max_bytes=250,
        aplus_allowed=True,
        compliance_notes=(
            "日本站对成分表示、原产地标注有本地化要求（景品表示法）。",
            "禁止夸大效果表述，需与实物规格一致。",
        ),
    ),
    "MX": MarketplaceProfile(
        code="MX",
        label="Amazon.com.mx（墨西哥）",
        language="es-MX",
        locale_name="Español (México)",
        measurement_system="metric",
        currency="MXN",
        title_max_chars=200,
        bullet_max_chars=500,
        description_max_chars=2000,
        bullet_count=5,
        search_terms_max_bytes=250,
        aplus_allowed=True,
        compliance_notes=("墨西哥站需西班牙语信息，并遵守 NOM 相关标识要求。",),
    ),
}

DEFAULT_MARKETPLACE = "US"


def get_marketplace(code: str) -> MarketplaceProfile:
    """按站点代码取配置；未知站点回退到 US 并在调用方提示。"""
    return MARKETPLACES.get((code or "").upper(), MARKETPLACES[DEFAULT_MARKETPLACE])


def supported_marketplaces() -> dict[str, str]:
    return {code: profile.label for code, profile in MARKETPLACES.items()}


def language_for(code: str) -> str:
    return get_marketplace(code).language


# A+ 模块的写作规范：给模型的内容约束，避免生成"空话型"模块
APLUS_MODULE_SPECS: dict[str, dict[str, str]] = {
    "hero_banner": {
        "title": "主视觉 Banner",
        "purpose": "用一句可验证的价值主张说明这是什么、为谁解决什么问题",
        "max_words": "12",
        "rules": "不得出现价格、促销、绝对化用语；不得出现未提供的规格",
    },
    "benefit_icons": {
        "title": "卖点图标行",
        "purpose": "把 3-4 个已验证卖点图标化",
        "max_words": "8",
        "rules": "每条必须对应一个 fact_id；无事实支撑的图标不生成",
    },
    "comparison_chart": {
        "title": "对比图",
        "purpose": "对比自家不同型号或使用场景，而非贬低竞品",
        "max_words": "15",
        "rules": "禁止点名竞品、禁止无法验证的对比结论",
    },
    "spec_table": {
        "title": "规格表",
        "purpose": "完整呈现可验证规格",
        "max_words": "—",
        "rules": "只允许列事实层中的规格；缺项写「待补充」而不是留空或编造",
    },
    "lifestyle_image": {
        "title": "使用场景图",
        "purpose": "展示真实使用方式",
        "max_words": "15",
        "rules": "场景描述不得暗示未提供的功能",
    },
    "brand_story": {
        "title": "品牌故事",
        "purpose": "建立信任，只讲可核实信息",
        "max_words": "60",
        "rules": "不得编造成立年份、销量、用户数量、获奖情况",
    },
}


def aplus_specs_for(code: str) -> dict[str, dict[str, str]]:
    profile = get_marketplace(code)
    return {key: APLUS_MODULE_SPECS[key] for key in profile.aplus_modules if key in APLUS_MODULE_SPECS}


__all__ = [
    "APLUS_MODULE_SPECS",
    "DEFAULT_MARKETPLACE",
    "MARKETPLACES",
    "MarketplaceProfile",
    "aplus_specs_for",
    "get_marketplace",
    "language_for",
    "supported_marketplaces",
]
