"""服务元信息：健康检查、平台/站点规则、禁用词、Provider 状态、页面外壳。

这里全是**公开或半公开**接口（页面外壳与平台规则不需要登录），
所以刻意不放业务逻辑 —— 业务端点见其它模块。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import perf
from ..config import get_settings
from ..version import __version__
from ..auth import extract_token, resolve_session
from ..llm.llm import KNOWN_MODELS
from ..market.marketplaces import get_marketplace, supported_marketplaces
from ..market.platforms import ALL_CAPABILITIES, DEFAULT_PLATFORM, list_platforms
from ..llm.providers import ProviderError, build_provider, provider_status
from ..engine.rules import get_rules
from .deps import ApiContext, get_ctx, require_user

router = APIRouter(tags=["元信息"])

#: SPA 外壳：与 backend/ 平级的 frontend/index.html（CROSSPILOT_WEB_DIR 可覆盖）
FRONTEND_INDEX = get_settings().web_dir / "index.html"

#: SPA 路由：都返回同一个外壳，由前端路由接管。
#: 只登记明确路径，不用通配符，避免吞掉 /api、/docs。
SPA_ROUTES = (
    "/workbench",
    "/dashboard",
    "/tasks",
    "/tasks/{task_id}",
    "/data",
    "/agents",
    "/skills",
    "/stores",
    # 店铺经营助手的四个子页：刷新 / 直接打开 / 分享链接都要能落到外壳，
    # 少登记一条，用户看到的就是 404 的裸 JSON。
    "/stores/authorize",
    "/stores/product",
    "/stores/ledger",
    "/settings",
    "/research",
    "/assets",
    "/operations",
    "/workflows",
    "/knowledge",
)


def worker_health(settings) -> dict[str, Any]:
    """异步执行器健康探针：不建连、不发请求，只报配置与库是否可用。"""
    backend = (getattr(settings, "task_queue", "thread") or "thread").lower()
    info: dict[str, Any] = {"backend": backend, "alive": True, "redis": None}
    if backend == "arq":
        info["redis"] = False
        try:
            import redis

            client = redis.Redis.from_url(
                settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5
            )
            info["redis"] = bool(client.ping())
            info["alive"] = bool(info["redis"])
        except Exception:  # noqa: BLE001 - 不可用就是不可用，不抛给健康检查
            info["alive"] = False
    return info


# ---------------------------------------------------------------------------
# 页面外壳
# ---------------------------------------------------------------------------


# 外壳页不缓存：保证改完 index.html / 静态资源版本号后刷新即可见
_NO_CACHE = {"Cache-Control": "no-cache"}

#: 构建戳缓存：连续刷新时不重复扫描目录
_ASSET_STAMP: dict[str, Any] = {"value": "", "at": 0.0}
_ASSET_STAMP_TTL = 1.5


def asset_stamp() -> str:
    """前端构建戳 = 所有前端文件的最新修改时间（毫秒）。

    外壳页里的 ``?v=0`` 会被替换成它。任何一个 css/js 改动都会让它变化，
    资源 URL 随之变化，浏览器只能重新下载 —— 不需要用户手动硬刷新。
    """
    now = time.monotonic()
    if _ASSET_STAMP["value"] and now - _ASSET_STAMP["at"] < _ASSET_STAMP_TTL:
        return str(_ASSET_STAMP["value"])

    root = FRONTEND_INDEX.parent
    latest = 0.0
    for pattern in ("index.html", "css/*.css", "js/*.js", "js/pages/*.js"):
        for path in root.glob(pattern):
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:  # 扫描期间文件被替换/删除，跳过即可
                continue

    value = f"{int(latest * 1000)}"
    _ASSET_STAMP["value"] = value
    _ASSET_STAMP["at"] = now
    return value


def _shell_response() -> HTMLResponse:
    """返回 SPA 外壳：注入资源版本戳，并禁掉页面缓存。"""
    try:
        html = FRONTEND_INDEX.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail="页面外壳缺失") from exc
    return HTMLResponse(html.replace("?v=0", f"?v={asset_stamp()}"), headers=_NO_CACHE)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> HTMLResponse:
    return _shell_response()


if FRONTEND_INDEX.is_file():
    for _path in SPA_ROUTES:
        router.add_api_route(
            _path,
            _shell_response,
            methods=["GET"],
            response_class=HTMLResponse,
            include_in_schema=False,
            name=f"spa{_path.replace('/', '-')}",
        )


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


@router.get("/api/health")
def health(request: Request, api: ApiContext = Depends(get_ctx)) -> dict[str, Any]:
    """公开接口：只报服务状态；已登录时顺带反映该用户的模型配置。"""
    active = api.settings
    token = extract_token(request)
    with perf.timed("health.session"):
        user = resolve_session(api.db, token) if token else None
    model_config = None
    if user is not None:
        try:
            with perf.timed("health.provider_config"):
                model_config = api.provider_service().effective(user["user_id"], active)
                if model_config is None:
                    model_config = api.model_service().effective(user["user_id"], active)
        except Exception:  # noqa: BLE001 - 探针不能让健康检查失败
            model_config = None
    try:
        with perf.timed("health.provider_status"):
            provider_info = provider_status(active, model_config)
    except ProviderError as exc:
        name = model_config.provider if model_config else active.provider
        provider_info = {"name": name, "available": False, "detail": str(exc)}

    # 「验证过」的唯一证据是真的调通过一次。顶栏据此区分「已就绪」和「未验证」，
    # 所以把当前这套配置的测试结果带上，否则测试通过了界面还在说未验证。
    if user is not None and provider_info.get("available"):
        try:
            config_id = api.provider_service().active_config_id(user["user_id"])
            row = (
                api.db.get_provider_config(user["user_id"], config_id)
                if config_id
                else None
            )
            if row is not None and row.get("last_test_ok") is not None:
                provider_info["verified"] = bool(row["last_test_ok"])
        except Exception:  # noqa: BLE001 - 探针不能让健康检查失败
            pass

    with perf.timed("health.worker"):
        worker_info = worker_health(active)

    return {
        "status": "ok",
        "version": __version__,
        "brand": active.brand_name,
        "provider": provider_info,
        "requires_api_key": bool(active.require_api_key),
        "configured_model": (
            {
                "provider": model_config.provider,
                "model": model_config.model,
                "source": model_config.source,
            }
            if model_config
            else None
        ),
        "worker": worker_info,
        "marketplace_mode": active.marketplace_mode,
        "demo_data": "所有示例数据标记为示例/Mock，不代表真实商品/销量/排名",
        "db": str(api.db.path),
        "platforms": get_rules().supported_platforms(),
    }


@router.get("/api/platforms")
async def platforms() -> dict[str, Any]:
    """平台信息，两个用途分开返回，别混着用：

    - ``platforms`` / ``marketplaces``：**文案规则**支持的平台与站点（字符上限、禁用词）；
    - ``catalog``：**数据接入**目录（字段名、能力、认证方式、真实接入状态）。
    """
    return {
        "platforms": get_rules().supported_platforms(),
        "marketplaces": supported_marketplaces(),
        "catalog": list_platforms(),
        "capabilities": list(ALL_CAPABILITIES),
        "default_platform": DEFAULT_PLATFORM,
        "note": "字符限制与禁用词来自可配置规则，未经平台最新政策核验",
        "catalog_note": (
            "真实平台接入均未完成（live_status=not_configured）："
            "需要应用注册、卖家授权与平台审核。当前只有 Mock 连接器可用，不伪造真实数据。"
        ),
    }


@router.get("/api/marketplaces")
async def marketplaces() -> dict[str, Any]:
    return {
        "marketplaces": supported_marketplaces(),
        "profiles": {
            code: get_marketplace(code).as_dict() for code in supported_marketplaces()
        },
    }


@router.get("/api/platform-rules/{platform}/{marketplace}")
async def platform_rule_detail(platform: str, marketplace: str) -> dict[str, Any]:
    try:
        return get_rules().platform_rules(platform, marketplace).as_dict()
    except Exception as exc:  # noqa: BLE001 - 未知平台给 404 而不是 500
        raise HTTPException(
            status_code=404, detail=f"不支持的平台/站点: {platform}/{marketplace}"
        ) from exc


@router.get("/api/ban-lists")
async def ban_lists() -> dict[str, Any]:
    banned = get_rules().banned_terms()
    categories: dict[str, list[str]] = {}
    for term in banned.terms:
        categories.setdefault(term.category_label, []).append(term.term)
    return {
        "categories": categories,
        "universal_superlatives": list(banned.universal_superlatives),
        "disclaimer": (
            "禁用词清单为项目内部可配置示例，未经平台审核，"
            "发布前必须人工对照平台最新政策确认。"
        ),
    }


# ---------------------------------------------------------------------------
# Provider 状态（每用户）
# ---------------------------------------------------------------------------


@router.get("/api/providers")
def providers(
    user: dict[str, Any] = Depends(require_user), api: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    with perf.timed("providers.config"):
        model_config = api.model_service().effective(user["user_id"], api.settings)
    with perf.timed("providers.status"):
        status = provider_status(api.settings, model_config)
    return {
        "active": model_config.provider,
        "model": model_config.model,
        "source": model_config.source,
        "status": status,
        "models": list(KNOWN_MODELS),
        "note": "deepseek-flash 是官方文档的当前模型名；deepseek-v4-flash 等旧名仍可用但已退役",
    }


@router.post("/api/providers/ping")
async def ping_provider(
    user: dict[str, Any] = Depends(require_user), api: ApiContext = Depends(get_ctx)
) -> dict[str, Any]:
    """用当前用户的已保存配置真实调用一次模型（会消耗极少量额度）。"""
    active = api.settings
    model_config = api.model_service().effective(user["user_id"], active)
    try:
        provider = build_provider(active, model_config)
    except ProviderError as exc:
        return {"ok": False, "detail": str(exc)}

    # 配置了 deepseek 但被降级：直接说明缺什么，而不是说"不支持检测"
    fallback_reason = getattr(provider, "fallback_reason", None)
    if fallback_reason and model_config.provider != "rule":
        return {"ok": False, "detail": fallback_reason, "model": model_config.model}

    if model_config.provider == "rule":
        return {"ok": True, "detail": "rule 引擎为本地实现，无需连通性测试", "model": "rule"}
    if not model_config.api_key:
        return {
            "ok": False,
            "detail": "还没有配置 API Key，暂时无法测试连接",
            "model": model_config.model,
        }

    ping = getattr(provider, "ping", None)
    if not callable(ping):
        return {
            "ok": False,
            "detail": f"当前 Provider（{provider.name}）不支持连通性检测",
            "model": model_config.model,
        }
    started = time.perf_counter()
    try:
        ok, detail = ping()
    except Exception as exc:  # noqa: BLE001 - 把异常转成可读结果
        return {
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "model": model_config.model,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    return {
        "ok": bool(ok),
        "detail": detail,
        "model": model_config.model,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


__all__ = ["SPA_ROUTES", "router", "worker_health"]
