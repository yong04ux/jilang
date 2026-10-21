"""模型配置：旧的单套配置 + 多厂商 Provider 配置（多套 + 单一激活）。

两套接口并存是**有意的**：

- ``/api/settings/model``（旧）：单套配置，仍作为回退路径，逐步淘汰；
- ``/api/settings/providers``（新）：一个账号可存多套，单一激活，
  这才是设置页实际使用的接口。

新增端点一律走 ``providers``，不要给旧接口加功能。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..llm.llm import LLMError
from ..llm.model_settings import ModelSettingsError, ModelSettingsUpdate
from ..llm.provider_configs import ProviderConfigError, ProviderConfigInput
from ..llm.providers import DeepSeekProvider, ProviderError, build_provider
from ..services import audit
from .deps import ApiContext, get_ctx, require_user

router = APIRouter(tags=["模型与密钥"])

CLEAR_KEY_SENTINEL = "__CLEAR__"


# ---------------------------------------------------------------------------
# 旧的单套配置（回退路径）
# ---------------------------------------------------------------------------


@router.get("/api/settings/model")
async def get_model_settings(
    user: dict[str, Any] = Depends(require_user), api: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    return api.model_service().to_public(user["user_id"], api.settings)


@router.put("/api/settings/model")
async def update_model_settings(
    payload: ModelSettingsUpdate,
    user: dict[str, Any] = Depends(require_user),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    api.guard_demo_key_write(user)
    try:
        result = api.model_service().update(user["user_id"], payload, api.settings)
    except ModelSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 加密等异常不静默
        raise HTTPException(status_code=500, detail=f"保存配置失败：{exc}") from exc
    api.audit_user(
        user,
        audit.ACTION_MODEL_UPDATE,
        target_type="model_settings",
        target_id=user["user_id"],
        detail={
            "provider": payload.provider,
            "model": payload.model,
            "api_key": payload.api_key,
        },
    )
    return result


@router.delete("/api/settings/model")
async def reset_model_settings(
    user: dict[str, Any] = Depends(require_user), api: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    api.guard_demo_key_write(user)
    result = api.model_service().reset(user["user_id"], api.settings)
    api.audit_user(
        user,
        audit.ACTION_MODEL_RESET,
        target_type="model_settings",
        target_id=user["user_id"],
    )
    return result


@router.post("/api/settings/model/test")
async def test_model_settings(
    payload: ModelSettingsUpdate,
    user: dict[str, Any] = Depends(require_user),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """用"提交但未保存"的参数试连一次，避免用户先存错再改。

    Key 未提交时使用已保存的 Key；两者都没有则明确告知。
    """
    active = api.settings
    service = api.model_service()
    effective = service.effective(user["user_id"], active)
    merged = ModelSettingsUpdate(**payload.model_dump(exclude_none=True))
    _apply_patch(effective, merged)

    if effective.provider == "rule":
        return {"ok": True, "detail": "rule 引擎为本地实现，无需连通性测试", "model": "rule"}
    if not effective.api_key:
        return {"ok": False, "detail": "尚未配置 API Key，无法测试连接"}

    try:
        provider = build_provider(active, effective)
    except ProviderError as exc:
        return {"ok": False, "detail": str(exc), "model": effective.model}

    return _ping_provider(provider, effective.model)


def _apply_patch(effective, merged: ModelSettingsUpdate) -> None:
    """把"提交但未保存"的字段覆盖到生效配置上。"""
    if merged.provider:
        effective.provider = merged.provider
    if merged.model:
        effective.model = merged.model
    if merged.base_url:
        effective.base_url = merged.base_url
    if merged.timeout is not None:
        effective.timeout = merged.timeout
    if merged.max_retries is not None:
        effective.max_retries = merged.max_retries
    if merged.temperature is not None:
        effective.temperature = merged.temperature
    if merged.thinking is not None:
        effective.thinking = merged.thinking
    if merged.reasoning_effort is not None:
        effective.reasoning_effort = merged.reasoning_effort
    if merged.api_key and merged.api_key != CLEAR_KEY_SENTINEL:
        effective.api_key = merged.api_key.strip()


def _ping_provider(provider, model: str) -> dict[str, Any]:
    ping = getattr(provider, "ping", None)
    if not callable(ping):
        return {
            "ok": False,
            "detail": f"当前 Provider（{provider.name}）不支持连通性检测",
            "model": model,
        }
    started = time.perf_counter()
    try:
        ok, detail = ping()
    except Exception as exc:  # noqa: BLE001 - 把异常转成可读结果
        return {
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "model": model,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    return {
        "ok": bool(ok),
        "detail": detail,
        "model": model,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


# ---------------------------------------------------------------------------
# 多厂商 Provider 配置（设置页实际使用）
# ---------------------------------------------------------------------------


@router.get("/api/settings/providers")
async def list_provider_configs(
    user: dict[str, Any] = Depends(require_user), api: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    return api.provider_service().list_public(user["user_id"])


@router.post("/api/settings/providers")
async def upsert_provider_config(
    payload: ProviderConfigInput,
    user: dict[str, Any] = Depends(require_user),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """新增一套配置；``config_id`` 有值时表示更新已有配置。"""
    api.guard_demo_key_write(user)
    service = api.provider_service()
    config_id = (payload.config_id or "").strip() or None
    try:
        saved = service.save(user["user_id"], payload, config_id=config_id)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 加密失败等不静默
        raise HTTPException(status_code=500, detail=f"保存配置失败：{exc}") from exc
    api.audit_user(
        user,
        "model.provider_save",
        target_type="provider_config",
        target_id=saved["config_id"],
        detail={
            "provider": saved["provider"],
            "label": saved["label"],
            "base_url": saved["base_url"],
            "model": saved["model"],
        },
    )
    return {"config": saved}


@router.delete("/api/settings/providers/{config_id}")
async def delete_provider_config(
    config_id: str,
    user: dict[str, Any] = Depends(require_user),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    api.guard_demo_key_write(user)
    service = api.provider_service()
    try:
        service.delete(user["user_id"], config_id)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    api.audit_user(
        user,
        "model.provider_delete",
        target_type="provider_config",
        target_id=config_id,
    )
    return {
        "ok": True,
        "active_config_id": api.provider_service().active_config_id(user["user_id"]),
    }


@router.post("/api/settings/providers/{config_id}/test")
async def test_provider_config(
    config_id: str,
    user: dict[str, Any] = Depends(require_user),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    """最小连通性测试（会消耗极少额度）。结果落库但不改激活状态。"""
    api.guard_demo_key_write(user)
    api.rate_limit(user, "provider.test", api.settings.rate_limit_key_tests_per_hour)
    service = api.provider_service()
    try:
        row = service.get_row(user["user_id"], config_id)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    provider_key = row["provider"]
    if provider_key == "rule":
        return {
            "ok": True,
            "detail": "rule 是本地规则引擎，无需连通性测试",
            "model": "rule",
            "elapsed_ms": 0,
            "config": service.public_row(row),
        }

    api_key = service.decrypt_key(row)
    if not api_key:
        result = {"ok": False, "detail": "这套配置没有可用的 API Key，请重新填写"}
    else:
        # 统一走 OpenAI 兼容客户端：预置厂商与自定义地址都走同一条路径
        candidate = DeepSeekProvider(
            api_key=api_key,
            base_url=row.get("base_url") or "",
            model=row.get("model") or "",
            timeout=min(api.settings.deepseek_timeout, 20.0),
            max_retries=0,
        )
        started = time.perf_counter()
        try:
            ok, detail = candidate.ping()
        except LLMError as exc:
            ok, detail = False, f"{exc.kind}: {exc}"
        except Exception as exc:  # noqa: BLE001 - 把异常转成可读结果
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        result = {
            "ok": bool(ok),
            "detail": detail,
            "model": row.get("model") or "",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    updated = service.record_test(
        user["user_id"], config_id, ok=result["ok"], detail=result["detail"]
    )
    api.audit_user(
        user,
        "model.provider_test",
        target_type="provider_config",
        target_id=config_id,
        detail={"ok": result["ok"], "provider": provider_key},
    )
    return {**result, "config": updated}


@router.post("/api/settings/providers/{config_id}/activate")
async def activate_provider_config(
    config_id: str,
    user: dict[str, Any] = Depends(require_user),
    api: ApiContext = Depends(get_ctx),
) -> dict[str, Any]:
    api.guard_demo_key_write(user)
    service = api.provider_service()
    try:
        activated = service.activate(user["user_id"], config_id)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    api.audit_user(
        user,
        "model.provider_activate",
        target_type="provider_config",
        target_id=config_id,
        detail={"provider": activated["provider"], "label": activated["label"]},
    )
    return {"config": activated, "active_config_id": config_id}


__all__ = ["router"]
