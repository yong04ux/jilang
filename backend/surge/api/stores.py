"""店铺连接（Mock 连接器；真实 SP-API 未接入，不会显示为已连接）。

凭据明文绝不回传：只存 ``SecretBox`` 密文，接口返回引用与掩码。
角色约定：建连/同步/断开需要写权限，保存凭据需要管理权限（ROLE_MANAGE）。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..persistence.secrets import SecretBox
from ..services import audit
from ..services import connectors as connector_service
from ..tenancy import ROLE_MANAGE, ROLE_READ, TenantContext, TenantError, require_role
from .deps import ApiContext, get_ctx, require_tenant

router = APIRouter(tags=["店铺与渠道"])


@router.get("/api/stores")
async def list_stores(
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    return {
        "items": connector_service.list_connections(api.db, ctx),
        "capabilities": {
            "mock": True,
            "live": False,
            "note": "仅 Mock 连接器可用；真实 SP-API 未接入，不会显示为已连接",
        },
    }


@router.post("/api/stores")
async def create_store(
    payload: dict[str, Any],
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        connection = connector_service.create_mock_connection(
            api.db,
            ctx,
            platform=str(payload.get("platform") or "amazon"),
            marketplace=str(payload.get("marketplace") or "US"),
            shop_name=str(payload.get("shop_name") or ""),
            mode=str(payload.get("mode") or "mock"),
        )
    except connector_service.StoreConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TenantError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except connector_service.ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    api.audit_context(
        ctx,
        "store.create",
        target_type="store_connection",
        target_id=connection["connection_id"],
        detail={"platform": connection["platform"], "mode": "mock"},
    )
    return connection


@router.get("/api/stores/{connection_id}")
async def get_store(
    connection_id: str,
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    try:
        connection = connector_service.get_connection(api.db, ctx, connection_id)
    except connector_service.StoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return connection


@router.post("/api/stores/{connection_id}/test")
async def test_store(
    connection_id: str,
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        result = connector_service.test_connection(api.db, ctx, connection_id)
    except connector_service.StoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


@router.post("/api/stores/{connection_id}/sync")
async def sync_store(
    connection_id: str,
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        result = connector_service.sync_connection(api.db, ctx, connection_id)
    except connector_service.StoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TenantError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except connector_service.ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    api.audit_context(
        ctx,
        "store.sync",
        target_type="store_connection",
        target_id=connection_id,
        detail={
            "mode": result.get("mode"),
            "products": result.get("products"),
            "orders": result.get("orders"),
        },
    )
    return result


@router.get("/api/stores/{connection_id}/products")
async def store_products(
    connection_id: str,
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    try:
        items = connector_service.list_products(api.db, ctx, connection_id)
    except connector_service.StoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except connector_service.ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": items, "is_mock": True}


@router.get("/api/stores/{connection_id}/orders")
async def store_orders(
    connection_id: str,
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    require_role(ctx, ROLE_READ)
    try:
        items = connector_service.list_orders(api.db, ctx, connection_id)
    except connector_service.StoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except connector_service.ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": items, "is_mock": True}


@router.delete("/api/stores/{connection_id}")
async def disconnect_store(
    connection_id: str,
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        connection = connector_service.disconnect(api.db, ctx, connection_id)
    except connector_service.StoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    api.audit_context(
        ctx,
        "store.disconnect",
        target_type="store_connection",
        target_id=connection_id,
    )
    return connection


@router.post("/api/stores/{connection_id}/credential")
async def store_credential(
    connection_id: str,
    payload: dict[str, Any],
    api: ApiContext = Depends(get_ctx),
    ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """保存加密凭据，只返回引用与掩码。明文绝不回传。"""
    require_role(ctx, ROLE_MANAGE)
    secret = str(payload.get("secret") or "").strip()
    if not secret:
        raise HTTPException(status_code=422, detail="缺少 secret")
    # 复用装配期缓存 SecretBox：密钥损坏时工厂会给出可操作的 500，且避免重复派生
    ciphertext = api.secret_box_factory().encrypt(secret)
    credential_ref = uuid.uuid4().hex
    api.db.save_store_credential(credential_ref, ctx.tenant_id, ciphertext)
    try:
        connector_service.attach_credential(api.db, ctx, connection_id, credential_ref)
    except connector_service.StoreNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    api.audit_context(
        ctx,
        "store.credential",
        target_type="store_connection",
        target_id=connection_id,
        detail={"credential_ref": credential_ref},
    )
    return {
        "credential_ref": credential_ref,
        "masked": SecretBox.mask(secret),
        "note": "凭据已加密保存；接口不会返回明文",
    }


__all__ = ["router"]
