"""成本与利润测算的数学口径。

这些测试不是在验代码，是在**验账**。每一项都手算过一遍，
数字对不上就说明卖家照着页面算出来的结果是错的。

关键口径（写在这里，避免以后有人"顺手优化"改坏）：
- 平台佣金 = 售价 × 费率（跟售价挂钩，不是固定值）
- 退货损耗 = 退货率 ×（采购 + 头程 + 退货处理）
- 不亏价 = 与售价无关的成本 ÷ (1 － 佣金率)
- 反算定价 = 与售价无关的成本 ÷ (1 － 佣金率 － 目标毛利)
- 回本销量 = 一次性投入 ÷ 单件毛利（向上取整）
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crosspilot.engine.profit import ProfitRequest, calculate

BASE = dict(
    product_name="折叠收纳箱",
    marketplace="US",
    currency="USD",
    fulfillment="fba",
    selling_price=30.0,
    purchase_cost=8.0,
    shipping_cost=2.0,
    packaging_cost=0.0,
    fulfillment_fee=4.0,
    other_cost=0.0,
    ad_cost_per_order=3.0,
    commission_rate=0.15,
    return_rate=0.0,
    return_handling_cost=0.0,
    fixed_cost=1000.0,
    target_margin=0.2,
)


def _calc(**overrides):
    return calculate(ProfitRequest(**{**BASE, **overrides}))


def test_unit_economics_add_up():
    """8 + 2 + 0 + 4.5(佣金) + 4 + 3 = 21.5，毛利 8.5，毛利率 28.33%。"""
    result = _calc()

    assert result.total_cost == pytest.approx(21.5)
    assert result.unit_profit == pytest.approx(8.5)
    assert result.margin == pytest.approx(0.2833, abs=1e-4)
    assert result.roi == pytest.approx(0.3953, abs=1e-4)


def test_commission_scales_with_price_not_fixed():
    """佣金是售价的 15%，涨价时它也跟着涨——这是定错价最常见的原因。"""
    result = _calc(selling_price=60.0)
    commission = next(item for item in result.cost_breakdown if item.key == "commission")

    assert commission.amount == pytest.approx(9.0)
    assert commission.ratio_to_price == pytest.approx(0.15)


def test_return_loss_counts_goods_value_not_just_handling():
    """退货率 10%：损失 = 10% ×（采购 8 + 头程 2 + 处理 1.5）= 1.15。"""
    result = _calc(return_rate=0.1, return_handling_cost=1.5)
    item = next(i for i in result.cost_breakdown if i.key == "return_loss")

    assert item.amount == pytest.approx(1.15)
    assert result.total_cost == pytest.approx(22.65)


def test_break_even_price_excludes_commission_from_cost_base():
    """不亏价 = 与售价无关的成本 17 ÷ 0.85 = 20，不是 21.5。"""
    result = _calc()

    assert result.break_even_price == pytest.approx(20.0)
    assert "20.00" in result.break_even_note


def test_recommended_price_for_target_margin():
    """要 20% 毛利：17 ÷ (1 - 0.15 - 0.2) = 26.15。"""
    result = _calc()

    assert result.recommended_price == pytest.approx(26.1538, abs=1e-4)


def test_break_even_units_rounds_up():
    """1000 ÷ 8.5 = 117.6，必须向上取整到 118——117 件回不了本。"""
    result = _calc()

    assert result.break_even_units == 118
    assert "118" in result.break_even_units_note


def test_losing_price_gives_no_break_even_units_and_warns():
    """亏损时不该编一个"回本销量"，要给明确结论。"""
    result = _calc(selling_price=18.0)

    assert result.unit_profit < 0
    assert result.break_even_units is None
    assert "回不了本" in result.break_even_units_note
    assert any("亏损" in warning for warning in result.warnings)


def test_sensitivity_covers_four_variables_both_directions():
    """四个变量 × 上下 10% = 8 行；采购涨 10% 毛利率掉 2.66 个点。"""
    result = _calc()

    assert len(result.sensitivity) == 8
    purchase_up = next(
        row
        for row in result.sensitivity
        if row.variable == "purchase_cost" and row.delta > 0
    )
    assert purchase_up.new_value == pytest.approx(8.8)
    assert purchase_up.unit_profit == pytest.approx(7.7)
    assert purchase_up.margin_change == pytest.approx(-0.0266, abs=1e-4)


def test_zero_fulfillment_fee_is_flagged_not_silently_accepted():
    """履约费填 0 时毛利会系统性偏高，必须提示，不能自己当 0 收下。"""
    result = _calc(fulfillment_fee=0.0)

    assert any("履约配送费填的是 0" in warning for warning in result.warnings)


def test_assumption_lists_commission_rate_source():
    """佣金率等于站点参考值时必须声明是参考值，不能当用户真实费率。"""
    result = _calc()

    assert any("参考值" in item for item in result.assumptions)


def test_custom_commission_rate_is_not_labelled_as_preset():
    result = _calc(commission_rate=0.08)

    assert any("用户填写" in item for item in result.assumptions)
    assert not any("参考值" in item for item in result.assumptions)


def test_commission_plus_target_margin_cannot_reach_100_percent():
    with pytest.raises(ValidationError):
        ProfitRequest(**{**BASE, "commission_rate": 0.5, "target_margin": 0.5})


def test_calculate_is_reentrant():
    """敏感性分析内部会递归调用 calculate，不能有隐藏状态。"""
    first = _calc()
    second = _calc()

    assert first.model_dump() == second.model_dump()
