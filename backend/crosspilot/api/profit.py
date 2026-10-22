"""成本与利润测算：即时计算 + 方案保存。

为什么不用异步任务
==================

竞品分析走异步是因为要跑统计流水线；这里是纯算术，毫秒级完成，
套一层任务队列只会让前端多轮询一次。**复杂度要花在有用的地方。**

数据性质
========

输入全部来自用户填报（采购价、头程、佣金率、退货率……），没有任何一项
来自平台 API —— 所以这里不存在"Mock 数据"，也不需要 Provider 抽象。
结果一律带 ``is_estimate: true``：它是基于输入口径的**估算**，
不是财务账。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..engine.profit import (
    COMMISSION_PRESETS,
    ProfitRequest,
    calculate,
)
from ..services import audit
from ..tenancy import ROLE_READ, ROLE_WRITE, TenantContext, require_role
from .deps import ApiContext, get_ctx, require_tenant, require_user

router = APIRouter(tags=["成本与利润"])

KIND = "profit"


def _summary_of(result: Any) -> dict[str, Any]:
    """列表页只用得着几个关键数字，别把整份结果塞进去。"""
    return {
        "currency": result.currency,
        "selling_price": result.selling_price,
        "total_cost": result.total_cost,
        "unit_profit": result.unit_profit,
        "margin": result.margin,
        "break_even_price": result.break_even_price,
        "is_estimate": True,
    }


@router.get("/api/profit/presets")
async def profit_presets(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """表单预填用的参考值。

    ``commission_rate`` 是**站点参考费率**，不是这个卖家的真实费率——
    前端必须显示成"参考值，请按后台实际费率修改"，不能预填完当事实用。
    """
    return {
        "commission_presets": COMMISSION_PRESETS,
        "currencies": ["USD", "EUR", "GBP", "JPY", "SGD", "BRL", "CNY"],
        "fulfillment_modes": [
            {"key": "fba", "label": "平台仓配（FBA 类）"},
            {"key": "fbm", "label": "自发货（海外仓/直发）"},
            {"key": "self", "label": "自营履约（国内直发）"},
        ],
        "note": "佣金率为站点参考值，实际费率随类目在 3%–45% 之间变化，请用后台真实费率",
    }


@router.post("/api/profit/calc")
async def profit_calc(
    request: ProfitRequest,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """即时测算，不落库。用来做"改一个数字立刻看结果"的交互。"""
    require_role(tenant, ROLE_READ)
    try:
        result = calculate(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc)}) from exc
    return result.model_dump(mode="json")


@router.post("/api/profit/plans")
async def save_profit_plan(
    request: ProfitRequest,
    title: str = Query(default="", max_length=200),
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """保存一套测算方案（含输入与结果），便于回头对比。"""
    require_role(tenant, ROLE_WRITE)
    result = calculate(request)
    report_id = api.db.save_business_report(
        tenant_id=tenant.tenant_id,
        user_id=user["user_id"],
        kind=KIND,
        title=title.strip() or request.product_name,
        report_input=request.model_dump(mode="json"),
        summary=_summary_of(result),
        payload=result.model_dump(mode="json"),
    )
    audit.record_for_context(
        api.db,
        tenant,
        "profit.save",
        target_type="business_report",
        target_id=report_id,
        detail={"product_name": request.product_name, "margin": result.margin},
    )
    return {"report_id": report_id, "kind": KIND, "summary": _summary_of(result)}


@router.get("/api/profit/plans")
async def list_profit_plans(
    limit: int = Query(default=20, ge=1, le=200),
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_READ)
    items = api.db.list_business_reports(tenant.tenant_id, kind=KIND, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/api/profit/plans/{report_id}")
async def get_profit_plan(
    report_id: str,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_READ)
    row = api.db.get_business_report(report_id, tenant.tenant_id)
    if row is None or row.get("kind") != KIND:
        raise HTTPException(status_code=404, detail={"message": "方案不存在"})
    return row


@router.delete("/api/profit/plans/{report_id}")
async def delete_profit_plan(
    report_id: str,
    user: dict[str, Any] = Depends(require_user),
    tenant: TenantContext = Depends(require_tenant),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    require_role(tenant, ROLE_WRITE)
    row = api.db.get_business_report(report_id, tenant.tenant_id)
    if row is None or row.get("kind") != KIND:
        raise HTTPException(status_code=404, detail={"message": "方案不存在"})
    api.db.delete_business_report(report_id, tenant.tenant_id)
    audit.record_for_context(
        api.db,
        tenant,
        "profit.delete",
        target_type="business_report",
        target_id=report_id,
    )
    return {"deleted": True, "report_id": report_id}
