r"""arq worker 入口（阶段 D6）。

启动：

```powershell
# 1) 启动 Redis（本机已安装）
C:\\Redis\\redis-server.exe
# 2) 启动 worker（独立进程）
.\.venv\Scripts\python.exe -m crosspilot.worker
# 3) 让 API 使用 arq 后端
$env:CROSSPILOT_TASK_QUEUE = "arq"
.\.venv\Scripts\python.exe -m crosspilot uvicorn ...
```

worker 不依赖 FastAPI：它从数据库读取 ``tasks.input``（完整运行参数），
按租户/用户重建 Provider 与 SecretBox，执行同一张 LangGraph，因此
「线程执行器」与「arq 执行器」跑的是完全相同的业务代码。

注意：本机没有常驻 Redis，``pytest`` **不覆盖**这条路径（会跳过）。
线上默认不用这条路径——Render 单实例场景走 ``worker_service.py`` 的
进程内线程队列（见 ``CROSSPILOT_TASK_QUEUE``）。
"""

from __future__ import annotations

import logging

from .agent.runtime import AgentRunError, execute_agent
from .config import get_settings
from .persistence.db import Database
from .llm.model_settings import ModelSettingsService
from .llm.providers import build_provider
from .llm.step_providers import build_step_providers
from .persistence.secrets import SecretBox
from .services import conversations
from .services.tasks import TaskCancelled, TaskRecorder
from .tenancy import TenantContext

logger = logging.getLogger(__name__)


def _db() -> Database:
    return Database(get_settings().database_url)


def _provider_for(db: Database, user_id: str):
    settings = get_settings()
    secret_box = SecretBox(settings.resolve_path(settings.data_dir) / ".secret_key")
    service = ModelSettingsService(db, secret_box)
    config = service.effective(user_id, settings)
    return build_provider(settings, config)


async def run_task(ctx, task_id: str) -> dict[str, str]:
    """arq job：按 task_id 执行一个已落库的 Agent 任务。"""
    db = _db()
    task = db.get_task_by_id(task_id)
    if task is None:
        logger.warning("arq: 任务不存在 %s", task_id)
        return {"status": "missing"}
    if task["status"] not in {"queued", "running"}:
        logger.info("arq: 任务状态为 %s，跳过 %s", task["status"], task_id)
        return {"status": task["status"]}

    recorder = TaskRecorder.resume(db, task)
    tenant_ctx = TenantContext(
        tenant_id=task.get("tenant_id") or "",
        tenant_name="",
        user_id=task["user_id"],
        role="editor",
    )
    try:
        provider = _provider_for(db, task["user_id"])
        # 与 HTTP 路径共用同一套解析：analyze / listing 可能各用不同配置
        step_providers = build_step_providers(db, get_settings(), task["user_id"])
        execute_agent(
            recorder,
            db=db,
            provider=provider,
            payload=dict(task.get("input") or {}),
            providers=step_providers,
        )
    except TaskCancelled:
        logger.info("arq: 任务在检查点取消 %s", task_id)
    except AgentRunError:
        logger.warning("arq: 任务失败 %s", task_id)
    except Exception as exc:  # noqa: BLE001 - 任务不能停在 running
        logger.exception("arq: worker 异常 %s", task_id)
        recorder.fail(code="worker_error", message=f"{type(exc).__name__}: {exc}"[:500])
    finally:
        if task.get("conversation_id"):
            conversations.record_task_result(
                db,
                tenant_ctx,
                task["conversation_id"],
                task_id,
                fallback_plan=(task.get("output") or {}).get("plan"),
                degraded=bool(task.get("degraded")),
            )
    updated = db.get_task_by_id(task_id) or {}
    return {"status": str(updated.get("status"))}


def _redis_settings():
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    """arq CLI 使用的配置。"""

    functions = [run_task]
    redis_settings = _redis_settings()
    max_jobs = 4
    job_timeout = 900
    keep_result = 3600


def main() -> None:  # pragma: no cover - 独立进程入口
    from arq.worker import run_worker

    logging.basicConfig(level=logging.INFO)
    run_worker(WorkerSettings)


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["WorkerSettings", "run_task"]
