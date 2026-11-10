"""调用大模型的评测集：金标用例与评分口径。

和离线评测的区别
================

离线那套（``cases.py``）跑规则引擎，**确定性**，用来守"该拦的有没有拦住"。
这一套真的调模型，产出会波动，所以它不比较"结果是否一致"，而是比**质量与遵从度**：

- 事实一致性：文案里的每个数字能不能追回输入事实（模型最爱编参数）
- 指令遵从：条数、字数、语言、卖点覆盖
- 稳定性：同一用例跑多次，通过率与分数波动

**分数不是目的，红线才是。** 编造参数一律判 0——这条不设权重、
不给部分分，因为"编出来的规格"在电商场景里是直接会导致退货和投诉的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMCase:
    """一条金标用例：输入 + 评分口径。"""

    case_id: str
    title: str
    request: dict[str, Any]
    rubric: dict[str, Any] = field(default_factory=dict)


def _req(
    name: str,
    specs: dict[str, str],
    features: list[str],
    price: float | None,
    *,
    language: str = "en-US",
) -> dict[str, Any]:
    return {
        "product": {
            "name": name,
            "target_platform": "amazon",
            "marketplace": "US",
            "specifications": specs,
            "key_features": features,
            "price": price,
            "brand": "",
            "certifications": [],
            "target_audience": "",
            "banned_terms": [],
        },
        "language": language,
        "marketplace": "US",
        "data_source": "manual",
    }


def _rubric(
    *,
    min_bullets: int = 5,
    max_bullets: int = 5,
    max_title_chars: int = 200,
    max_bullet_chars: int = 500,
    min_description_chars: int = 200,
    required_features: list[str] | None = None,
    min_feature_coverage: float = 0.7,
) -> dict[str, Any]:
    return {
        "min_bullets": min_bullets,
        "max_bullets": max_bullets,
        "max_title_chars": max_title_chars,
        "max_bullet_chars": max_bullet_chars,
        "min_description_chars": min_description_chars,
        # 卖点覆盖：至少这些卖点中要有 min_feature_coverage 的比例被用上
        "required_features": required_features or [],
        "min_feature_coverage": min_feature_coverage,
    }


LLM_CASES: tuple[LLMCase, ...] = (
    LLMCase(
        case_id="llm-insulated-bottle",
        title="保温杯 · 资料齐全",
        request=_req(
            "EcoSip Insulated Water Bottle 24oz",
            {"capacity": "24oz", "material": "18/8 stainless steel", "weight": "420g"},
            ["double-wall vacuum insulation", "leak-proof twist lid", "fits standard cup holders"],
            27.99,
        ),
        rubric=_rubric(
            required_features=["insulation", "leak", "cup holder"],
            min_feature_coverage=0.66,
        ),
    ),
    LLMCase(
        case_id="llm-ceramic-mug",
        title="陶瓷马克杯 · 两个卖点",
        request=_req(
            "Hearth Ceramic Mug 12oz",
            {"capacity": "12oz", "material": "stoneware"},
            ["microwave safe", "dishwasher safe"],
            16.5,
        ),
        rubric=_rubric(
            required_features=["microwave", "dishwasher"],
            min_feature_coverage=1.0,
            min_description_chars=150,
        ),
    ),
    LLMCase(
        case_id="llm-pet-bowl",
        title="宠物饮水碗 · 三个卖点",
        request=_req(
            "PawFlow Pet Water Bowl 1.5L",
            {"capacity": "1.5L", "material": "food-grade PP"},
            ["non-slip silicone base", "splash-proof rim", "easy to disassemble"],
            21.0,
        ),
        rubric=_rubric(
            required_features=["non-slip", "splash", "disassemble"],
            min_feature_coverage=0.66,
        ),
    ),
    LLMCase(
        case_id="llm-desk-lamp",
        title="护眼台灯 · 三个规格",
        request=_req(
            "LumiDesk LED Task Lamp",
            {"wattage": "12W", "color_temperature": "3000K-6000K", "cord_length": "1.8m"},
            ["flicker-free dimming", "touch control"],
            39.99,
        ),
        rubric=_rubric(
            required_features=["flicker", "touch"],
            min_feature_coverage=1.0,
        ),
    ),
    LLMCase(
        case_id="llm-tote-bag",
        title="帆布托特包 · 资料偏少",
        request=_req(
            "CarryAll Canvas Tote",
            {"material": "12oz cotton canvas"},
            ["reinforced handles", "inner zip pocket"],
            24.0,
        ),
        rubric=_rubric(
            required_features=["handle", "pocket"],
            min_feature_coverage=1.0,
            min_description_chars=150,
        ),
    ),
    LLMCase(
        case_id="llm-yoga-mat",
        title="瑜伽垫 · 两个规格",
        request=_req(
            "ZenGrip Yoga Mat 6mm",
            {"thickness": "6mm", "size": "183cm x 61cm"},
            ["non-slip texture", "carrying strap included"],
            32.0,
        ),
        rubric=_rubric(required_features=["non-slip", "strap"], min_feature_coverage=1.0),
    ),
    LLMCase(
        case_id="llm-kitchen-scale",
        title="厨房秤 · 三个卖点",
        request=_req(
            "PrecisionKitchen Scale 5kg",
            {"max_capacity": "5kg", "resolution": "1g"},
            ["tare function", "backlit display", "stainless platform"],
            18.9,
        ),
        rubric=_rubric(
            required_features=["tare", "backlit", "stainless"],
            min_feature_coverage=0.66,
        ),
    ),
    LLMCase(
        case_id="llm-travel-pillow",
        title="旅行枕 · 一个规格",
        request=_req(
            "CloudRest Travel Pillow",
            {"filling": "memory foam"},
            ["360-degree neck support", "washable cover", "compression bag"],
            19.5,
        ),
        rubric=_rubric(
            required_features=["neck support", "washable", "compression"],
            min_feature_coverage=0.66,
        ),
    ),
    LLMCase(
        case_id="llm-filter-pitcher",
        title="滤水壶 · 三个规格",
        request=_req(
            "ClearFlow Water Filter Pitcher 2.5L",
            {"capacity": "2.5L", "filter_life": "60 days", "material": "BPA-free plastic"},
            ["fast filtration", "flip-top lid"],
            34.0,
        ),
        rubric=_rubric(
            required_features=["filtration", "flip-top"],
            min_feature_coverage=1.0,
        ),
    ),
    LLMCase(
        case_id="llm-camping-lantern",
        title="露营灯 · 三个卖点",
        request=_req(
            "TrailGlow Camping Lantern",
            {"battery": "3 x AA", "brightness": "300 lumens"},
            ["three lighting modes", "collapsible hook", "water resistant"],
            26.0,
        ),
        rubric=_rubric(
            required_features=["lighting modes", "hook", "water"],
            min_feature_coverage=0.66,
        ),
    ),
    LLMCase(
        case_id="llm-baby-bottle",
        title="婴儿奶瓶 · 需谨慎表述",
        request=_req(
            "GentleFeed Baby Bottle 240ml",
            {"capacity": "240ml", "material": "borosilicate glass"},
            ["anti-colic vent", "soft silicone nipple"],
            22.0,
        ),
        rubric=_rubric(
            required_features=["anti-colic", "silicone"],
            min_feature_coverage=1.0,
        ),
    ),
    LLMCase(
        case_id="llm-sparse-facts",
        title="资料极少 · 探编造（对抗用例）",
        request=_req("Unknown Brand Storage Box", {}, ["stackable"], None),
        rubric=_rubric(
            required_features=["stackable"],
            min_feature_coverage=1.0,
            min_description_chars=120,
        ),
    ),
)


def build_live_suite() -> list[LLMCase]:
    return list(LLM_CASES)


__all__ = ["LLMCase", "build_live_suite"]
