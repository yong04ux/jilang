"""成本与利润测算：单件经济模型、盈亏平衡、定价反算与敏感性分析。

为什么这个模块不需要外部数据
============================

它算的是**卖家自己的账**：采购多少钱、头程多少、平台抽多少、退多少。
这些数只有卖家知道，任何平台 API 都拿不到。所以它天然是"真功能"，
不是演示替身——Mock 数据在这里没有意义，全部输入来自用户填报。

设计纪律（与项目其余部分一致）
==============================

1. **不编造数字**。每一笔成本要么来自用户输入（``source="user"``），
   要么是用户勾选/填写的比率（``source="user"``），要么是**显式标注的假设**
   （``source="assumed"``，同时进 ``assumptions`` 列表让前端提示）。
   平台佣金率这类"行业常见值"只作为**占位默认**，绝不会静默当成事实。
2. **每个结果都能手算复核**。每笔成本项都带 ``formula`` 文字口径，
   盈亏平衡与定价反算都带 ``derivation``，卖家看得懂才敢用。
3. **缺失即提示**。影响结论的缺项进 ``warnings``，不猜、不补零了事
   （例如履约费填 0 时明确告知"若走 FBA，毛利会偏高"）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# 输入
# ---------------------------------------------------------------------------

FulfillmentMode = Literal["fba", "fbm", "self"]

_FULFILLMENT_LABEL = {
    "fba": "平台仓配（FBA 类）",
    "fbm": "自发货（海外仓/直发）",
    "self": "自营履约（国内直发）",
}

#: 各站点平台佣金率的**参考占位值**，只用于预填，必须由用户确认。
#: 刻意不写成"默认值"——真实费率随类目变化（3%–45%），这里只给一个能起算的起点。
COMMISSION_PRESETS: dict[str, float] = {
    "US": 0.15,
    "CA": 0.15,
    "MX": 0.15,
    "DE": 0.15,
    "FR": 0.15,
    "IT": 0.15,
    "ES": 0.15,
    "UK": 0.15,
    "JP": 0.15,
    "SG": 0.12,
    "BR": 0.14,
}


class ProfitRequest(BaseModel):
    """一次测算的输入。

    金额单位统一为用户选择的币种（默认 USD），不做汇率换算——
    换算是另一件事，混进来会让"这笔账到底怎么算的"变得不可复核。
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    # ``title`` 是用户可见文案：技能页的参数表单由 ``model_json_schema()`` 生成，
    # 没有 title 就只能把字段名印在界面上（文案红线的直接违反）。
    product_name: str = Field(default="未命名商品", max_length=200, title="商品名称")
    marketplace: str = Field(default="US", max_length=16, title="站点")
    currency: str = Field(default="USD", max_length=8, title="币种")
    fulfillment: FulfillmentMode = Field(default="fba", title="履约方式")

    # ---- 售价与成本（单件口径） ----
    selling_price: float = Field(gt=0, le=1_000_000, description="单件售价", title="单件售价")
    purchase_cost: float = Field(
        ge=0, le=1_000_000, description="采购成本（含税到仓）", title="采购成本"
    )
    shipping_cost: float = Field(
        default=0.0, ge=0, le=1_000_000, description="头程运费（单件摊销）", title="头程运费"
    )
    packaging_cost: float = Field(
        default=0.0, ge=0, le=1_000, description="包装耗材", title="包装耗材"
    )
    fulfillment_fee: float = Field(
        default=0.0, ge=0, le=1_000, description="履约/配送费（单件）", title="履约配送费"
    )
    other_cost: float = Field(
        default=0.0, ge=0, le=1_000, description="其他（关税/合规/汇损等）", title="其他成本"
    )
    ad_cost_per_order: float = Field(
        default=0.0,
        ge=0,
        le=1_000,
        description="广告摊销（每单，不是 ACOS 百分比）",
        title="广告摊销（每单）",
    )

    # ---- 比率 ----
    commission_rate: float = Field(
        default=0.15, ge=0, le=0.6, description="平台佣金率", title="平台佣金率"
    )
    return_rate: float = Field(default=0.0, ge=0, le=1, description="退货率", title="退货率")
    return_handling_cost: float = Field(
        default=0.0,
        ge=0,
        le=1_000,
        description="单件退货处理成本（换标/弃置/回运）",
        title="退货处理成本",
    )

    # ---- 一次性投入与目标 ----
    fixed_cost: float = Field(
        default=0.0,
        ge=0,
        le=10_000_000,
        description="一次性投入（开模/认证/首批备货/拍摄）",
        title="一次性投入",
    )
    target_margin: float | None = Field(
        default=None,
        gt=0,
        lt=0.95,
        description="目标毛利率，用于反算定价",
        title="目标毛利率",
    )

    @field_validator("marketplace")
    @classmethod
    def _upper_marketplace(cls, value: str) -> str:
        return (value or "").strip().upper() or "US"

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return (value or "").strip().upper() or "USD"

    @model_validator(mode="after")
    def _check_rates(self) -> ProfitRequest:
        if self.commission_rate + (self.target_margin or 0) >= 1:
            raise ValueError("平台佣金率与目标毛利率相加不能达到或超过 100%")
        return self


# ---------------------------------------------------------------------------
# 输出结构
# ---------------------------------------------------------------------------


class CostItem(BaseModel):
    """一笔成本。``formula`` 是给人看的手算口径，不是给机器看的。"""

    key: str
    label: str
    amount: float
    ratio_to_price: float
    formula: str
    source: Literal["user", "assumed"] = "user"
    note: str = ""


class SensitivityRow(BaseModel):
    variable: str
    label: str
    delta: float
    new_value: float
    unit_profit: float
    margin: float
    margin_change: float


class ProfitResult(BaseModel):
    """测算结果。所有金额均为单件、本币口径。"""

    product_name: str
    marketplace: str
    currency: str
    fulfillment: FulfillmentMode
    fulfillment_label: str
    is_estimate: bool = True

    selling_price: float
    total_cost: float
    unit_profit: float
    margin: float
    roi: float | None = None
    cost_breakdown: list[CostItem]

    break_even_price: float | None
    break_even_note: str
    break_even_units: int | None
    break_even_units_note: str

    recommended_price: float | None
    recommended_price_note: str
    price_floor: float | None
    price_ceiling: float | None

    sensitivity: list[SensitivityRow]
    assumptions: list[str]
    warnings: list[str]
    derivation: list[str]


# ---------------------------------------------------------------------------
# 计算
# ---------------------------------------------------------------------------


def _round(value: float) -> float:
    """金额保留 4 位、比率保留 4 位，避免浮点尾巴污染展示。"""
    return round(float(value), 4)


def _pct(part: float, whole: float) -> float:
    return _round(part / whole) if whole else 0.0


def _build_costs(request: ProfitRequest) -> tuple[list[CostItem], float]:
    """逐项算成本。返回 (明细, 合计)。

    退货损耗的口径：``退货率 ×（采购 + 头程 + 退货处理）``。
    为什么把采购和头程算进去：退回来的货多数不能再原价出售，
    这部分货值就是损失；只算"处理费"会系统性低估退货成本。
    """
    price = request.selling_price
    commission = request.commission_rate * price
    return_loss = request.return_rate * (
        request.purchase_cost + request.shipping_cost + request.return_handling_cost
    )

    items = [
        CostItem(
            key="purchase",
            label="采购成本",
            amount=_round(request.purchase_cost),
            ratio_to_price=_pct(request.purchase_cost, price),
            formula="用户填报（含税到仓单价）",
        ),
        CostItem(
            key="shipping",
            label="头程运费",
            amount=_round(request.shipping_cost),
            ratio_to_price=_pct(request.shipping_cost, price),
            formula="单件摊销：整批头程总运费 ÷ 件数",
        ),
        CostItem(
            key="packaging",
            label="包装耗材",
            amount=_round(request.packaging_cost),
            ratio_to_price=_pct(request.packaging_cost, price),
            formula="单件包装材料 + 标签 + 说明卡",
        ),
        CostItem(
            key="commission",
            label="平台佣金",
            amount=_round(commission),
            ratio_to_price=_pct(commission, price),
            formula=f"售价 × {request.commission_rate:.2%}",
            source="user",
            note="费率按类目不同差异很大（3%–45%），请用后台实际费率",
        ),
        CostItem(
            key="fulfillment",
            label="履约配送",
            amount=_round(request.fulfillment_fee),
            ratio_to_price=_pct(request.fulfillment_fee, price),
            formula=f"{_FULFILLMENT_LABEL[request.fulfillment]}单件费用",
        ),
        CostItem(
            key="ad",
            label="广告摊销",
            amount=_round(request.ad_cost_per_order),
            ratio_to_price=_pct(request.ad_cost_per_order, price),
            formula="每单广告花费（也可用 售价 × ACOS × 广告订单占比 估）",
        ),
        CostItem(
            key="return_loss",
            label="退货损耗",
            amount=_round(return_loss),
            ratio_to_price=_pct(return_loss, price),
            formula=f"退货率 {request.return_rate:.1%} ×（采购 + 头程 + 退货处理）",
            note="退回货品多数无法原价再售，按货值计损",
        ),
        CostItem(
            key="other",
            label="其他成本",
            amount=_round(request.other_cost),
            ratio_to_price=_pct(request.other_cost, price),
            formula="关税 / 合规 / 汇损 / 仓储等未列入上面的部分",
        ),
    ]
    total = sum(item.amount for item in items)
    return items, _round(total)


def calculate(request: ProfitRequest) -> ProfitResult:
    """跑一次完整测算。纯函数，无副作用、无 IO。"""
    result = _solve(request)
    # 敏感性要反复重算同一套公式，所以放在 ``_solve`` 之外：
    # 否则 _solve 内部再算敏感性 → 无限递归。
    result.sensitivity = _sensitivity(request, result.margin)
    return result


def _solve(request: ProfitRequest) -> ProfitResult:
    """算到敏感性为止的完整结果（``sensitivity`` 留空，由 ``calculate`` 填）。"""
    costs, total = _build_costs(request)
    price = request.selling_price
    profit = _round(price - total)
    margin = _pct(profit, price)
    roi = _round(profit / total) if total > 0 else None

    warnings: list[str] = []
    assumptions: list[str] = []

    # ---- 盈亏平衡价格 ----
    # 售价 P 满足 P - (固定成本 + 佣金率×P) = 0  →  P = 固定成本 / (1 - 佣金率)
    # 这里的"固定成本"指与售价无关的那部分（采购/头程/履约/广告/退货/其他）。
    rate = request.commission_rate
    variable_cost = _round(total - rate * price)  # 与售价无关的合计
    if rate >= 1:
        break_even_price = None
        break_even_note = "佣金率达到 100%，任何售价都无法盈利"
    elif variable_cost <= 0:
        break_even_price = 0.0
        break_even_note = "未填报任何与售价无关的成本，任何正价都不亏"
    else:
        break_even_price = _round(variable_cost / (1 - rate))
        break_even_note = (
            f"按当前成本结构，售价低于 {break_even_price:.2f} 即亏损"
            f"（不亏价 = 无关成本 {variable_cost:.2f} ÷ (1 - 佣金率 {rate:.0%})）"
        )

    # ---- 一次性投入回本销量 ----
    if request.fixed_cost <= 0:
        break_even_units = None
        break_even_units_note = "未填一次性投入，无需回本销量"
    elif profit <= 0:
        break_even_units = None
        break_even_units_note = "当前单件亏损，卖多少都回不了本——先解决定价或成本"
    else:
        import math

        break_even_units = math.ceil(request.fixed_cost / profit)
        break_even_units_note = (
            f"一次性投入 {request.fixed_cost:.2f} ÷ 单件毛利 {profit:.2f}，"
            f"约 {break_even_units} 件回本"
        )

    # ---- 目标毛利反算定价 ----
    # margin = (1 - 佣金率) - 无关成本 / 售价  →  售价 = 无关成本 / (1 - 佣金率 - 目标毛利)
    recommended_price: float | None = None
    if request.target_margin is None:
        recommended_price_note = "未填目标毛利率，不做定价反算"
    else:
        denominator = 1 - rate - request.target_margin
        if denominator <= 0:
            recommended_price_note = "目标毛利 + 佣金率已达 100%，无法反算定价"
            warnings.append("目标毛利率与平台佣金率之和过高，定价反算无解")
        elif variable_cost <= 0:
            recommended_price_note = "缺少与售价无关的成本，无法反算定价"
        else:
            recommended_price = _round(variable_cost / denominator)
            recommended_price_note = (
                f"要拿到 {request.target_margin:.0%} 毛利，售价需不低于 "
                f"{recommended_price:.2f}（= 无关成本 {variable_cost:.2f} ÷ "
                f"(1 - 佣金率 {rate:.0%} - 目标毛利 {request.target_margin:.0%})）"
            )

    price_floor = break_even_price
    price_ceiling: float | None = None
    if price_floor and recommended_price and recommended_price > price_floor:
        # 上限只做"当前定价的 1.5 倍"这种可解释刻度，不编造市场可接受价
        price_ceiling = _round(price * 1.5)

    # ---- 敏感性分析由 calculate() 填，见上方注释 ----
    sensitivity: list[SensitivityRow] = []

    # ---- 假设与提示 ----
    if request.fulfillment_fee <= 0 and request.fulfillment in ("fba", "fbm"):
        warnings.append(
            f"履约配送费填的是 0。如果实际走{_FULFILLMENT_LABEL[request.fulfillment]}，"
            "这笔钱必须计入，否则毛利会系统性偏高"
        )
    if request.ad_cost_per_order <= 0:
        warnings.append("广告摊销填的是 0。新品期几乎一定有广告花费，不填会高估利润")
    if request.return_rate <= 0:
        warnings.append("退货率填的是 0。跨境退货率通常在 3%–15%，长期为 0 不现实")
    if request.other_cost <= 0:
        assumptions.append("其他成本按 0 计：关税 / VAT / 汇损未纳入")
    assumptions.append(
        f"平台佣金率按 {rate:.1%} 计，来自站点参考值，**必须**用后台实际费率替换"
        if abs(rate - COMMISSION_PRESETS.get(request.marketplace, -1)) < 1e-9
        else f"平台佣金率按用户填写的 {rate:.1%} 计"
    )
    assumptions.append("未做汇率换算：所有金额须为同一币种")
    if profit < 0:
        warnings.append(f"当前定价单件亏损 {abs(profit):.2f}，卖得越多亏得越多")

    derivation = [
        "单件毛利 = 售价 － 各项成本合计",
        "毛利率 = 单件毛利 ÷ 售价",
        f"不亏价 = 与售价无关的成本 ÷ (1 － 佣金率 {rate:.0%})",
        "回本销量 = 一次性投入 ÷ 单件毛利（向上取整）",
        "反算定价 = 与售价无关的成本 ÷ (1 － 佣金率 － 目标毛利率)",
    ]

    return ProfitResult(
        product_name=request.product_name,
        marketplace=request.marketplace,
        currency=request.currency,
        fulfillment=request.fulfillment,
        fulfillment_label=_FULFILLMENT_LABEL[request.fulfillment],
        selling_price=_round(price),
        total_cost=total,
        unit_profit=profit,
        margin=margin,
        roi=roi,
        cost_breakdown=costs,
        break_even_price=break_even_price,
        break_even_note=break_even_note,
        break_even_units=break_even_units,
        break_even_units_note=break_even_units_note,
        recommended_price=recommended_price,
        recommended_price_note=recommended_price_note,
        price_floor=price_floor,
        price_ceiling=price_ceiling,
        sensitivity=sensitivity,
        assumptions=assumptions,
        warnings=warnings,
        derivation=derivation,
    )


@dataclass(frozen=True)
class _SensitivitySpec:
    variable: str
    label: str
    field: str
    unit: str = "amount"


_SENSITIVITY_SPECS: tuple[_SensitivitySpec, ...] = (
    _SensitivitySpec("selling_price", "售价", "selling_price"),
    _SensitivitySpec("purchase_cost", "采购成本", "purchase_cost"),
    _SensitivitySpec("ad_cost_per_order", "广告摊销", "ad_cost_per_order"),
    _SensitivitySpec("return_rate", "退货率", "return_rate", unit="rate"),
)

_SENSITIVITY_DELTAS = (-0.1, 0.1)


def _sensitivity(request: ProfitRequest, base_margin: float) -> list[SensitivityRow]:
    """把单个变量 ±10% 后的毛利变化算出来。

    比只报一个"毛利率 32%"有用得多：卖家能立刻看到
    「采购涨一成 → 毛利掉 X 个点」，这才是要盯的地方。
    """
    rows: list[SensitivityRow] = []
    payload: dict[str, Any] = request.model_dump()

    for spec in _SENSITIVITY_SPECS:
        base_value = float(payload.get(spec.field) or 0)
        for delta in _SENSITIVITY_DELTAS:
            new_value = base_value * (1 + delta)
            if spec.unit == "rate":
                new_value = max(0.0, min(1.0, new_value))
            trial = dict(payload)
            trial[spec.field] = new_value
            try:
                result = _solve(ProfitRequest(**trial))
            except ValueError:
                continue
            rows.append(
                SensitivityRow(
                    variable=spec.variable,
                    label=spec.label,
                    delta=delta,
                    new_value=_round(new_value),
                    unit_profit=result.unit_profit,
                    margin=result.margin,
                    margin_change=_round(result.margin - base_margin),
                )
            )
    return rows


__all__ = [
    "COMMISSION_PRESETS",
    "CostItem",
    "ProfitRequest",
    "ProfitResult",
    "SensitivityRow",
    "calculate",
]
