"""Render / 单实例部署入口：FastAPI + 进程内 worker + ``/health``。

架构 A（见 docs/09-refactor-plan.md 第 9 节）：

```
Vercel（静态）  ──/api/*──▶  Render Web Service（本文件）
                               ├── FastAPI (uvicorn)
                               ├── 线程任务队列（同进程，max 2 并发）
                               └── GET /health（保活用，不查库）
```

为什么 worker 与 API 同进程：Render 免费实例只允许一个 Web Service，
独立 worker 会额外占一个服务名额；而本项目的任务量很小，
``ThreadTaskQueue`` 已经能保证"提交即返回、步骤真实落库、可取消"。

健康检查分两个：
- ``/health``      ：进程存活（给 cron-job.org 保活，不碰数据库，最快返回）
- ``/health/deep``  ：数据库 + Provider + 队列的深度检查

启动：

```bash
CROSSPILOT_WORKER_MODE=inline uvicorn crosspilot.worker_service:app --host 0.0.0.0 --port $PORT
```
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from .app import create_app
from .config import get_settings

logging.basicConfig(
    level=os.environ.get("CROSSPILOT_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("crosspilot.worker_service")

_STARTED_AT = time.time()

#: 与 crosspilot.app:app 完全相同的应用实例；只是额外挂了 /health
app = create_app()


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, Any]:
    """保活探针：不查数据库，保证 Render 休眠后能被快速唤醒。"""
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - _STARTED_AT),
        "mode": os.environ.get("CROSSPILOT_WORKER_MODE", "inline"),
    }


@app.get("/health/deep", include_in_schema=False)
async def health_deep() -> dict[str, Any]:
    """深度探针：数据库连通、Provider 状态、队列后端。"""
    settings = get_settings()
    result: dict[str, Any] = {"status": "ok", "uptime_seconds": int(time.time() - _STARTED_AT)}
    db = app.state.db
    try:
        with db.connect() as connection:
            connection.execute("SELECT 1")
        result["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - 探针要报出原因而不是抛 500
        result["status"] = "degraded"
        result["database"] = f"error: {type(exc).__name__}: {exc}"
    result["task_queue"] = getattr(app.state.task_queue, "name", "unknown")
    result["provider"] = settings.provider
    result["require_api_key"] = bool(settings.require_api_key)
    result["storage"] = getattr(app.state.storage, "name", "unknown")
    if result["status"] != "ok":
        logger.warning("深度健康检查异常：%s", result)
    return result


@app.on_event("startup")
async def _log_startup() -> None:
    settings = get_settings()
    logger.info(
        "激浪启动：queue=%s storage=%s demo_account=%s require_api_key=%s auto_migrate=%s",
        getattr(app.state.task_queue, "name", "?"),
        getattr(app.state.storage, "name", "?"),
        settings.is_demo_account_enabled,
        settings.require_api_key,
        settings.auto_migrate,
    )


__all__ = ["app"]
