"""FastAPI 应用装配层。

本文件只做三件事：**装配 → 挂载 → 错误处理**，不再出现任何端点定义。
所有端点按业务域拆分在 ``crosspilot/api/`` 下（分层约定见 ``api/__init__.py``）：

- ``api/deps.py``     —— ``ApiContext``：所有 router 的唯一共享依赖；
- ``api/<domain>.py`` —— 某一业务域的端点，只依赖 ``ApiContext``；
- ``api/handlers.py`` / ``api/helpers.py`` —— 任务外层保护 / 无状态小工具。

**历史**：端点曾经是 ``create_app()`` 里的 88 个闭包函数，共享 15 个闭包变量
（``db`` / ``require_user`` / ``audit_user`` / ``require_llm_provider``…），
导致无法拆文件、无法脱离 ``create_app()`` 单测。现已全部搬入 ``api/``，
这里收敛成"装配 + 挂载"。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .version import __version__
from .agent import registry as agent_registry
from .api import ALL_ROUTERS
from .api.deps import ApiContext, make_secret_box
from .api.helpers import validation_errors
from .config import get_settings
from .persistence.db import Database
from .demo.demo_mode import ensure_demo_account
from .services.queue import QueueBackendError, build_task_queue
from .persistence.storage import StorageError, build_storage
from .tenancy import TenantError

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """装配 FastAPI 应用：构造共享上下文，挂载全部 router 与静态资源。"""
    settings = get_settings()
    # 生产建议 CROSSPILOT_AUTO_MIGRATE=false，由 `python -m crosspilot migrate` 显式迁移
    db = Database(settings.database_url, auto_migrate=bool(settings.auto_migrate))
    if not settings.auto_migrate:
        logger.info(
            "CROSSPILOT_AUTO_MIGRATE=false：跳过启动期迁移，请先运行 crosspilot migrate"
        )

    app = FastAPI(
        title="激浪 API",
        version=__version__,
        description=(
            "激浪：跨境电商 AI 运营演示站（MVP）。竞品分析 Agent、Listing 生成 Agent、"
            "数据导入与审批。平台数据来自可替换的 Provider（默认 Mock，全部带 is_mock 标记）。"
        ),
    )
    app.state.db = db
    app.state.settings = settings

    try:
        storage = build_storage(settings)
    except StorageError as exc:
        raise RuntimeError(f"存储后端配置错误：{exc}") from exc
    app.state.storage = storage

    # 注册表随代码发布，启动时幂等写入（tenant_id="" 表示平台内置）
    agent_registry.seed_registry(db)

    try:
        task_queue = build_task_queue(settings)
    except QueueBackendError as exc:
        raise RuntimeError(f"任务队列配置错误：{exc}") from exc
    app.state.task_queue = task_queue

    # 演示站的固定账号：只有配置了密码才创建（不设置默认弱口令）
    try:
        ensure_demo_account(
            db, username=settings.demo_username, password=settings.demo_password
        )
    except Exception as exc:  # noqa: BLE001 - 演示账号失败不应阻断启动，但要说清
        logger.warning("demo 账号初始化失败：%s", exc)

    # ------------------------------------------------------------------
    # 共享依赖：router 只认 ApiContext，不再依赖 create_app 的词法作用域。
    # 认证依赖（require_user/require_admin）由 api.deps 作为 FastAPI 依赖
    # 直接提供，不进上下文对象。
    # ------------------------------------------------------------------
    ctx = ApiContext(
        db=db,
        storage=storage,
        task_queue=task_queue,
        secret_box_factory=make_secret_box(settings),
    )
    app.state.ctx = ctx

    # CORS：仅当部署方显式配置了允许来源（例如 Vercel 域名），默认同源
    origins = settings.origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    # ------------------------------------------------------------------
    # 错误处理：租户错误统一 403；两类校验错误统一 422 结构化载荷
    # ------------------------------------------------------------------
    @app.exception_handler(TenantError)
    async def tenant_error_handler(_: Request, exc: TenantError) -> JSONResponse:
        """角色不足统一返回 403，消息可直接展示。"""
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "message": "请求数据校验失败",
                    "errors": [
                        {
                            "field": ".".join(
                                str(p) for p in err.get("loc", ()) if p != "body"
                            )
                            or "body",
                            "message": err.get("msg", ""),
                            "type": err.get("type", ""),
                        }
                        for err in exc.errors()
                    ],
                }
            },
        )

    @app.exception_handler(ValidationError)
    async def pydantic_error_handler(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "message": "请求数据校验失败",
                    "errors": validation_errors(exc),
                }
            },
        )

    # ------------------------------------------------------------------
    # 静态资源（唯一前端：仓库根/frontend，CROSSPILOT_WEB_DIR 可覆盖）与业务路由
    # ------------------------------------------------------------------
    web_dir = settings.web_dir
    app.mount("/css", StaticFiles(directory=str(web_dir / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(web_dir / "js")), name="js")
    app.mount("/media", StaticFiles(directory=str(web_dir / "assets")), name="media")

    for router in ALL_ROUTERS:
        app.include_router(router)

    return app


app = create_app()


def run() -> None:  # pragma: no cover - 由命令行入口调用
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "crosspilot.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )


if __name__ == "__main__":  # pragma: no cover
    run()


__all__ = ["app", "create_app", "run"]
