"""离线评测的用例集（确定性生成，无随机数）。

为什么生成而不是手写
====================

手写 4 条能守住主干，但守不住"组合"。真实输入是「商品资料完整度 × 竞品数量 ×
是否写文案 × 会不会出错」的笛卡尔积，漏掉任何一格，那一格的回归就没人看着。

这里用固定清单穷举这个矩阵，**不用随机数**：同一份代码跑出来的用例 id、输入、
期望完全一致，所以 `latest.json` 可以和上一次逐条 diff——这是"可复现"的前提。

四个维度
========

- ``tool_call``：选没选对工作流、计划骨架对不对、实际跑的步骤是不是按计划走；
- ``fact_consistency``：Listing 里的每个数字能不能追回事实、有没有绝对化用语；
- ``completion``：给定输入应该以什么结局收尾（完成 / 暂停 / 拦下 / 失败）；
- ``recovery``：注入各类故障后，错误分类对不对、有没有留下不该留的产物。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 维度
# ---------------------------------------------------------------------------

DIM_TOOL_CALL = "tool_call"
DIM_FACT = "fact_consistency"
DIM_COMPLETION = "completion"
DIM_RECOVERY = "recovery"
DIM_ROUTING = "routing"

DIMENSIONS = (DIM_TOOL_CALL, DIM_FACT, DIM_COMPLETION, DIM_RECOVERY, DIM_ROUTING)

KIND_COMPETITOR = "competitor"
KIND_LISTING = "listing"
KIND_COMBINED = "combined"
KIND_ROUTING = "routing"

# ---------------------------------------------------------------------------
# 故障注入（离线可重复，不依赖网络）
# ---------------------------------------------------------------------------

FAULT_NONE = ""
FAULT_RATE_LIMIT = "llm_rate_limit"
FAULT_NETWORK = "llm_network"
FAULT_AUTH = "llm_auth"
FAULT_ANALYSIS = "analysis_error"
FAULT_QUALITY = "quality_always_fail"
FAULT_TIMEOUT = "run_timeout"

#: 故障 → 期望的错误分类（`tasks.error_code` 的口径）
FAULT_ERROR = {
    FAULT_RATE_LIMIT: "rate_limited",
    FAULT_NETWORK: "model_timeout",
    FAULT_AUTH: "provider_unavailable",
    FAULT_ANALYSIS: "internal_error",
    FAULT_TIMEOUT: "model_timeout",
}


@dataclass(frozen=True)
class EvalCase:
    """一个可独立执行的评测用例。"""

    case_id: str
    dimension: str
    title: str
    kind: str
    payload: dict[str, Any]
    expect: dict[str, Any] = field(default_factory=dict)
    fault: str = FAULT_NONE
    note: str = ""


# ---------------------------------------------------------------------------
# 固定素材
# ---------------------------------------------------------------------------

#: 商品资料完整度变体。键是 profile 名，值是（规格, 卖点, 价格）
PRODUCT_PROFILES: dict[str, tuple[dict[str, str], list[str], float | None]] = {
    "full": ({"容量": "750ml", "材质": "304 不锈钢", "重量": "420g"}, ["双层真空保温", "防漏翻盖"], 22.9),
    "minimal": ({"容量": "750ml"}, ["双层真空保温"], 22.9),
    "specs_only": ({"容量": "500ml", "杯口": "广口"}, [], 15.5),
    "features_only": ({}, ["一键开盖", "可拆洗滤网", "杯身防滑"], 19.9),
    "empty": ({}, [], None),
}

PRODUCTS: tuple[tuple[str, str], ...] = (
    ("EcoSip 保温杯", "full"),
    ("EcoSip 保温杯 500ml", "minimal"),
    ("TrailFlask 户外水壶", "specs_only"),
    ("AquaGo 运动水杯", "features_only"),
    ("ThermoOne 焖烧罐", "full"),
    ("PureSip 玻璃水瓶", "minimal"),
    ("CampMug 露营杯", "specs_only"),
    ("HydroLite 轻量水袋", "empty"),
)

_BASE_ROWS: tuple[dict[str, Any], ...] = (
    {
        "name": "AquaPeak 32oz Insulated Water Bottle",
        "brand": "AquaPeak",
        "asin": "EVAL-AQUA-001",
        "price": 25.99,
        "rating": 4.4,
        "review_count": 1842,
        "key_features": ["双层真空保温", "防漏旋盖"],
        "specifications": {"容量": "32oz", "材质": "18/8 不锈钢"},
        "reviews": [
            {"rating": 5, "title": "保温好", "text": "冰水放了 9 小时还没化。"},
            {"rating": 2, "title": "盖子漏", "text": "第三天就漏了，包里全是水。"},
        ],
    },
    {
        "name": "TrailMug 24oz Bottle",
        "brand": "TrailMug",
        "asin": "EVAL-TRAIL-002",
        "price": 18.5,
        "rating": 4.1,
        "review_count": 634,
        "key_features": ["轻量", "单手开盖"],
        "specifications": {"容量": "24oz"},
        "reviews": [{"rating": 4, "title": "还行", "text": "轻，但保温一般。"}],
    },
    {
        "name": "HydroKing 40oz",
        "brand": "HydroKing",
        "asin": "EVAL-HYDRO-003",
        "price": 32.0,
        "rating": 4.6,
        "review_count": 5210,
        "key_features": ["大容量", "防漏"],
        "specifications": {"容量": "40oz", "材质": "不锈钢"},
        "reviews": [
            {"rating": 5, "title": "容量大", "text": "一天够喝。"},
            {"rating": 3, "title": "偏重", "text": "装满水有点沉。"},
        ],
    },
    {
        "name": "BudgetSip 20oz",
        "brand": "BudgetSip",
        "asin": "EVAL-BUDGET-004",
        "price": 11.9,
        "rating": 3.7,
        "review_count": 128,
        "key_features": ["便宜"],
        "specifications": {"容量": "20oz"},
        "reviews": [{"rating": 2, "title": "保温差", "text": "两小时就凉了。"}],
    },
    {
        "name": "SteelMax 36oz Pro",
        "brand": "SteelMax",
        "asin": "EVAL-STEEL-005",
        "price": 45.0,
        "rating": 4.8,
        "review_count": 903,
        "key_features": ["专业级保温", "可换盖"],
        "specifications": {"容量": "36oz", "材质": "316 不锈钢"},
        "reviews": [{"rating": 5, "title": "值这个价", "text": "做工扎实。"}],
    },
)

#: 竞品集：数量决定"样本够不够"，outlier 用来试极值干扰
COMPETITOR_SETS: dict[str, list[dict[str, Any]]] = {
    "none": [],
    "one": [_BASE_ROWS[0]],
    "two": [_BASE_ROWS[0], _BASE_ROWS[1]],
    "three": [_BASE_ROWS[0], _BASE_ROWS[1], _BASE_ROWS[2]],
    "five": list(_BASE_ROWS),
    "five_outlier": [
        *_BASE_ROWS,
        {
            "name": "LuxuryFlask 60oz",
            "brand": "LuxuryFlask",
            "asin": "EVAL-LUX-006",
            "price": 899.0,
            "rating": 1.0,
            "review_count": 3,
            "key_features": ["奢侈定位"],
            "specifications": {"容量": "60oz"},
            "reviews": [{"rating": 1, "title": "太贵", "text": "完全不值。"}],
        },
    ],
}


def _rows(profile: str) -> list[dict[str, Any]]:
    """取竞品行并补齐公共字段（深拷贝，避免用例之间互相污染）。"""
    import copy

    rows = copy.deepcopy(COMPETITOR_SETS[profile])
    for row in rows:
        row.setdefault("currency", "USD")
        row.setdefault("category", "Sports Water Bottles")
        row.setdefault("is_demo", True)
        row.setdefault("source_ref", "eval-dataset-v1")
    return rows


def _payload(kind: str, product: str, spec_profile: str, competitor_profile: str) -> dict[str, Any]:
    name, _ = next((p for p in PRODUCTS if p[0] == product), (product, ""))
    specs, features, price = PRODUCT_PROFILES[spec_profile]
    return {
        "product_name": name,
        "platform": "amazon",
        "marketplace": "US",
        "own_specs": dict(specs),
        "own_key_features": list(features),
        "own_price": price,
        "competitors": _rows(competitor_profile),
        "with_listing": kind == KIND_COMBINED,
        "listing_only": kind == KIND_LISTING,
        "data_source": "demo",
    }


def _expect(
    kind: str,
    spec_profile: str,
    competitor_profile: str,
    fault: str,
) -> dict[str, Any]:
    """按输入推导期望结局。**规则写在这里一处**，别在断言里再判一遍。"""
    has_facts = spec_profile != "empty"
    thin = len(COMPETITOR_SETS[competitor_profile]) < 3
    no_competitors = len(COMPETITOR_SETS[competitor_profile]) == 0
    expect: dict[str, Any] = {"kind": kind}

    # 0 条竞品：子图入口判"参数不合法"直接拒绝，压根跑不到分析。
    # （API 入口会在更早的 pre-check 里拦成 missing_input/competitors_missing，
    #  这里走的是图本身，分类落到 validation_error——两处口径不同，评估如实记录。）
    if kind != KIND_LISTING and no_competitors:
        expect["outcome"] = "failed"
        expect["error_code"] = "validation_error"
        expect["rejected_at_input"] = True
        return expect

    if kind == KIND_LISTING:
        expect["needs_facts"] = True
        expect["expects_pause"] = False
        expect["outcome"] = "succeeded" if has_facts else "needs_user_input"
    elif kind == KIND_COMBINED:
        expect["needs_facts"] = True
        expect["expects_pause"] = bool(has_facts and thin)
        if not has_facts:
            expect["outcome"] = "needs_user_input"
        elif thin:
            # 暂停后确认继续 → partial（样本不足，结论要标出来）
            expect["outcome"] = "partial"
        else:
            expect["outcome"] = "succeeded"
    else:
        expect["needs_facts"] = False
        expect["expects_pause"] = False
        # 竞品分析不看商品资料，但**看竞品样本量**：少于 3 条只能给 partial
        expect["outcome"] = "partial" if thin else "succeeded"

    if fault == FAULT_QUALITY:
        expect["outcome"] = "partial"
        expect["listing_expected"] = True
    elif fault == FAULT_TIMEOUT:
        expect["outcome"] = "failed"
        expect["error_code"] = FAULT_ERROR[fault]
    elif fault:
        expect["error_code"] = FAULT_ERROR.get(fault, "internal_error")
        if fault == FAULT_ANALYSIS and kind == KIND_LISTING:
            # 只写文案的流程不跑分析，这个故障注入是个空操作
            expect["fault_noop"] = True
        else:
            expect["outcome"] = "failed"

    return expect


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------


def _case_id(dimension: str, *parts: str) -> str:
    return "-".join((dimension, *[p for p in parts if p]))


def _tool_call_cases() -> list[EvalCase]:
    """选对工作流 + 计划骨架正确。

    竞品分析对全部商品跑满（成本最低、最该守住）；组合流程挑 6 个商品 ×
    全部竞品档位——它最慢，用商品数控制总时长，档位不缩，因为"样本够不够"
    这条判据只跟竞品数量有关。
    """
    cases: list[EvalCase] = []
    profiles = list(COMPETITOR_SETS)
    for kind in (KIND_COMPETITOR, KIND_LISTING, KIND_COMBINED):
        selected = PRODUCTS[:6] if kind == KIND_COMBINED else PRODUCTS
        for product, spec_profile in selected:
            for competitor_profile in profiles:
                if kind == KIND_LISTING and competitor_profile != "none":
                    continue  # 只写文案时竞品是无关变量，不必重复
                cases.append(
                    EvalCase(
                        case_id=_case_id(DIM_TOOL_CALL, kind, product, spec_profile, competitor_profile),
                        dimension=DIM_TOOL_CALL,
                        title=f"{kind} · {product} · 竞品 {competitor_profile}",
                        kind=kind,
                        payload=_payload(kind, product, spec_profile, competitor_profile),
                        expect=_expect(kind, spec_profile, competitor_profile, FAULT_NONE),
                    )
                )
    return cases


def _fact_cases() -> list[EvalCase]:
    """Listing 的事实一致性：数字必须有出处，不出现绝对化用语。"""
    cases: list[EvalCase] = []
    fact_profiles = [p for p in PRODUCT_PROFILES if p != "empty"]
    for kind in (KIND_COMBINED, KIND_LISTING):
        for product, _ in PRODUCTS:
            for spec_profile in fact_profiles:
                competitor_profile = "three" if kind == KIND_COMBINED else "none"
                cases.append(
                    EvalCase(
                        case_id=_case_id(DIM_FACT, kind, product, spec_profile),
                        dimension=DIM_FACT,
                        title=f"{kind} · {product} · 资料 {spec_profile}",
                        kind=kind,
                        payload=_payload(kind, product, spec_profile, competitor_profile),
                        expect=_expect(kind, spec_profile, competitor_profile, FAULT_NONE),
                    )
                )
    return cases


def _completion_cases() -> list[EvalCase]:
    """结局是否符合预期：完成 / 暂停 / 拦下。"""
    cases: list[EvalCase] = []
    for product, spec_profile in PRODUCTS:
        for competitor_profile in ("none", "one", "two", "three", "five_outlier"):
            kind = KIND_COMBINED
            cases.append(
                EvalCase(
                    case_id=_case_id(DIM_COMPLETION, product, spec_profile, competitor_profile),
                    dimension=DIM_COMPLETION,
                    title=f"{product} · 资料 {spec_profile} · 竞品 {competitor_profile}",
                    kind=kind,
                    payload=_payload(kind, product, spec_profile, competitor_profile),
                    expect=_expect(kind, spec_profile, competitor_profile, FAULT_NONE),
                )
            )
    # 只做分析的对照：不管资料是否齐全都该跑通（分析不需要商品事实）
    for competitor_profile in ("one", "three", "five_outlier"):
        cases.append(
            EvalCase(
                case_id=_case_id(DIM_COMPLETION, "competitor", competitor_profile),
                dimension=DIM_COMPLETION,
                title=f"只做分析 · 竞品 {competitor_profile}",
                kind=KIND_COMPETITOR,
                payload=_payload(KIND_COMPETITOR, PRODUCTS[0][0], "full", competitor_profile),
                expect=_expect(KIND_COMPETITOR, "full", competitor_profile, FAULT_NONE),
            )
        )
    return cases


def _recovery_cases() -> list[EvalCase]:
    """故障注入：错误分类要准，失败不留半成品。"""
    cases: list[EvalCase] = []
    faults = (
        FAULT_RATE_LIMIT,
        FAULT_NETWORK,
        FAULT_AUTH,
        FAULT_ANALYSIS,
        FAULT_QUALITY,
        FAULT_TIMEOUT,
    )
    for fault in faults:
        for kind in (KIND_COMBINED, KIND_LISTING):
            for product, spec_profile in PRODUCTS[:3]:
                competitor_profile = "three" if kind == KIND_COMBINED else "none"
                cases.append(
                    EvalCase(
                        case_id=_case_id(DIM_RECOVERY, fault, kind, product),
                        dimension=DIM_RECOVERY,
                        title=f"{fault} · {kind} · {product}",
                        kind=kind,
                        payload=_payload(kind, product, spec_profile, competitor_profile),
                        expect=_expect(kind, spec_profile, competitor_profile, fault),
                        fault=fault,
                        note="注入故障，验证错误分类与产物洁净度",
                    )
                )
    return cases


#: 路由金标：目标 → 应选能力。required 必须全中，forbidden 命中即错；
#: ``None`` 的开关表示"不关心"，避免把与目标无关的默认值写死进期望。
_ROUTING_GOLD: tuple[dict[str, Any], ...] = (
    {
        "goal": "帮我分析这批竞品的价格定位",
        "required": ["competitor_analysis"],
        "forbidden": ["listing_generation", "data_validation"],
        "with_listing": False,
        "listing_only": False,
    },
    {
        "goal": "看看竞品的评分和评论，找差异化机会",
        "required": ["competitor_analysis"],
        "forbidden": ["listing_generation"],
        "with_listing": False,
        "listing_only": False,
    },
    {
        "goal": "对比一下这几个竞品的价格带和卖点",
        "required": ["competitor_analysis"],
        "forbidden": ["listing_generation"],
        "with_listing": False,
        "listing_only": False,
    },
    {
        "goal": "帮我写一份英文 Listing",
        "required": ["listing_generation"],
        "forbidden": ["competitor_analysis"],
        "with_listing": True,
        "listing_only": True,
    },
    {
        "goal": "根据商品资料生成标题和五点描述",
        "required": ["listing_generation"],
        "forbidden": ["competitor_analysis"],
        "with_listing": True,
        "listing_only": True,
    },
    {
        "goal": "写个能过审的产品文案",
        "required": ["listing_generation"],
        "forbidden": ["competitor_analysis"],
        "with_listing": True,
        "listing_only": True,
    },
    {
        "goal": "先分析竞品，再写文案",
        "required": ["competitor_analysis", "listing_generation"],
        "forbidden": [],
        "with_listing": True,
        "listing_only": False,
    },
    {
        "goal": "竞品和 listing 一起做",
        "required": ["competitor_analysis", "listing_generation"],
        "forbidden": [],
        "with_listing": True,
        "listing_only": False,
    },
    {
        "goal": "把这份竞品分析总结成市场机会",
        "required": ["market_summary"],
        "forbidden": ["listing_generation"],
        "with_listing": False,
        "listing_only": False,
    },
    {
        "goal": "这个市场还有没有机会",
        "required": ["market_summary"],
        "forbidden": ["listing_generation"],
        "with_listing": False,
        "listing_only": False,
    },
    {
        "goal": "给我一段市场结论",
        "required": ["market_summary"],
        "forbidden": ["listing_generation"],
        "with_listing": False,
        "listing_only": False,
    },
    {
        "goal": "从评论里挖一下用户痛点",
        "required": ["review_mining"],
        "forbidden": ["listing_generation"],
        "with_listing": False,
        "listing_only": False,
    },
    {
        "goal": "买家差评都在抱怨什么",
        "required": ["review_mining"],
        "forbidden": ["listing_generation"],
        "with_listing": False,
        "listing_only": False,
    },
    {
        "goal": "总结一下用户的需求和顾虑",
        "required": ["review_mining"],
        "forbidden": ["listing_generation"],
        "with_listing": False,
        "listing_only": False,
    },
    {
        "goal": "先校验这份 CSV 数据文件",
        "required": ["data_validation"],
        "forbidden": ["listing_generation", "competitor_analysis"],
        "with_listing": None,
        "listing_only": None,
        "mode": "unsupported",
    },
    {
        "goal": "这个 Excel 表格里的字段有没有问题",
        "required": ["data_validation"],
        "forbidden": ["listing_generation", "competitor_analysis"],
        "with_listing": None,
        "listing_only": None,
        "mode": "unsupported",
    },
    {
        "goal": "帮我检查一下导入的数据格式",
        "required": ["data_validation"],
        "forbidden": ["listing_generation", "competitor_analysis"],
        "with_listing": None,
        "listing_only": None,
        "mode": "unsupported",
    },
    {
        "goal": "算一下这批货的成本和利润",
        "required": ["profit_calc"],
        "forbidden": ["listing_generation", "competitor_analysis"],
        "with_listing": None,
        "listing_only": None,
        "mode": "unsupported",
    },
    {
        "goal": "这批货多久能回本",
        "required": ["profit_calc"],
        "forbidden": ["listing_generation", "competitor_analysis"],
        "with_listing": None,
        "listing_only": None,
        "mode": "unsupported",
    },
    {
        "goal": "帮我算盈亏平衡",
        "required": ["profit_calc"],
        "forbidden": ["listing_generation", "competitor_analysis"],
        "with_listing": None,
        "listing_only": None,
        "mode": "unsupported",
    },
    {
        "goal": "毛利率多少才不亏",
        "required": ["profit_calc"],
        "forbidden": ["listing_generation", "competitor_analysis"],
        "with_listing": None,
        "listing_only": None,
        "mode": "unsupported",
    },
    {
        "goal": "核对这份草稿里的数字有没有出处",
        "required": ["listing_quality"],
        "forbidden": ["listing_generation", "competitor_analysis"],
        "with_listing": None,
        "listing_only": None,
        "mode": "unsupported",
    },
    {
        "goal": "检查这份草稿的出处",
        "required": ["listing_quality"],
        "forbidden": ["listing_generation", "competitor_analysis"],
        "with_listing": None,
        "listing_only": None,
        "mode": "unsupported",
    },
    {
        "goal": "你好",
        "required": [],
        "forbidden": [
            "competitor_analysis",
            "listing_generation",
            "market_summary",
            "review_mining",
            "data_validation",
            "profit_calc",
            "listing_quality",
        ],
        "with_listing": None,
        "listing_only": None,
    },
    {
        "goal": "帮我看看",
        "required": [],
        "forbidden": [
            "competitor_analysis",
            "listing_generation",
            "market_summary",
            "review_mining",
            "data_validation",
            "profit_calc",
            "listing_quality",
        ],
        "with_listing": None,
        "listing_only": None,
    },
    {
        "goal": "帮我写文案",
        "skill_key": "competitor_analysis",
        "required": ["competitor_analysis"],
        "forbidden": ["listing_generation"],
        "with_listing": False,
        "listing_only": False,
        "mode": "explicit",
    },
    {
        "goal": "分析竞品",
        "skill_key": "listing_generation",
        "required": ["listing_generation"],
        "forbidden": ["competitor_analysis"],
        "with_listing": True,
        "listing_only": True,
        "mode": "explicit",
    },
)


def _routing_cases() -> list[EvalCase]:
    """路由金标：自然语言目标 → 应选技能与工作流开关。"""
    cases: list[EvalCase] = []
    for index, gold in enumerate(_ROUTING_GOLD, start=1):
        mode = gold.get("mode", "auto")
        skill_key = gold.get("skill_key")
        cases.append(
            EvalCase(
                case_id=_case_id(
                    DIM_ROUTING, f"{index:02d}", "explicit" if skill_key else "auto"
                ),
                dimension=DIM_ROUTING,
                title=gold["goal"],
                kind=KIND_ROUTING,
                payload={"goal": gold["goal"], "skill_key": skill_key},
                expect={
                    "mode": mode,
                    "skills": list(gold["required"]),
                    "forbidden": list(gold["forbidden"]),
                    "with_listing": gold.get("with_listing"),
                    "listing_only": gold.get("listing_only"),
                },
                note="路由只读，不执行",
            )
        )
    return cases


def build_suite() -> list[EvalCase]:
    """全部用例（顺序固定）。"""
    return [
        *_tool_call_cases(),
        *_fact_cases(),
        *_completion_cases(),
        *_recovery_cases(),
        *_routing_cases(),
    ]


def suite_stats(cases: list[EvalCase]) -> dict[str, int]:
    stats: dict[str, int] = {}
    for case in cases:
        stats[case.dimension] = stats.get(case.dimension, 0) + 1
    stats["total"] = len(cases)
    return stats


__all__ = [
    "DIMENSIONS",
    "DIM_COMPLETION",
    "DIM_FACT",
    "DIM_RECOVERY",
    "DIM_ROUTING",
    "DIM_TOOL_CALL",
    "FAULT_ANALYSIS",
    "FAULT_AUTH",
    "FAULT_NETWORK",
    "FAULT_NONE",
    "FAULT_QUALITY",
    "FAULT_RATE_LIMIT",
    "FAULT_TIMEOUT",
    "KIND_COMBINED",
    "KIND_COMPETITOR",
    "KIND_LISTING",
    "KIND_ROUTING",
    "EvalCase",
    "build_suite",
    "suite_stats",
]
