"""任务队列抽象（阶段 C6 / D6）。

当前实现提供两种后端：

1. ``thread``（默认，已验证）：进程内线程池。任务在独立线程执行，
   每个任务一个取消事件；运行时在每个图节点前检查，因此取消能在
   **当前步骤结束后**立即生效（不会打断已经发出的 LLM 请求）。
2. ``arq``（可选，需 ``pip install arq redis`` 并启动 Redis）：
   由 ``arq_backend.ArqTaskQueue`` 把任务投递给独立 worker 进程。
   本机没有常驻 Redis，因此这条路径**未在本环境联调**，代码里明确标注。

接口刻意做成"按 task_id 投递、按 task_id 取消"，这样两种后端的
调用方完全一致，将来换 arq 不需要改 API 层。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class TaskCancelled(Exception):
    """任务在检查点被取消（不是失败）。"""


class QueueBackendError(RuntimeError):
    """队列配置错误（消息可直接展示）。"""


@runtime_checkable
class TaskQueue(Protocol):
    name: str

    def submit(self, task_id: str, job: Callable[[], None]) -> None: ...

    def cancel(self, task_id: str) -> bool: ...

    def is_active(self, task_id: str) -> bool: ...

    def is_cancelled(self, task_id: str) -> bool: ...

    def shutdown(self, wait: bool = False, timeout: float = 5.0) -> None: ...


class _Job:
    __slots__ = ("event", "thread")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.thread: threading.Thread | None = None


class ThreadTaskQueue:
    """进程内线程执行器：无外部依赖，测试与单机部署的默认后端。"""

    name = "thread"

    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def submit(self, task_id: str, job: Callable[[], None]) -> None:
        with self._lock:
            if task_id in self._jobs:
                raise QueueBackendError(f"任务已在执行中：{task_id}")
            record = _Job()
            self._jobs[task_id] = record
            thread = threading.Thread(
                target=self._run, args=(task_id, record, job), name=f"task-{task_id[:8]}", daemon=True
            )
            record.thread = thread
            thread.start()

    def _run(self, task_id: str, record: _Job, job: Callable[[], None]) -> None:
        try:
            job()
        except TaskCancelled:
            logger.info("任务在检查点取消：%s", task_id)
        except Exception:  # noqa: BLE001 - 任务本身的失败由 TaskRecorder 记录
            logger.exception("任务执行线程异常：%s", task_id)
        finally:
            with self._lock:
                self._jobs.pop(task_id, None)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            record = self._jobs.get(task_id)
        if record is None:
            return False
        record.event.set()
        return True

    def is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            record = self._jobs.get(task_id)
        return bool(record and record.event.is_set())

    def is_active(self, task_id: str) -> bool:
        with self._lock:
            record = self._jobs.get(task_id)
        return bool(record and record.thread and record.thread.is_alive())

    def shutdown(self, wait: bool = False, timeout: float = 5.0) -> None:
        with self._lock:
            records = list(self._jobs.values())
        for record in records:
            record.event.set()
        if wait:
            for record in records:
                if record.thread:
                    record.thread.join(timeout)


class ArqTaskQueue:
    """arq 后端：任务投递到独立 worker 进程。

    与线程后端的差异：进程之间不共享内存，因此取消不是设置 Event，
    而是写数据库状态（``cancelling``）并依赖 worker 的检查点读取。
    ``cancel`` 在这里只负责投递取消信号，任务状态的落库由 API 层完成。
    """

    name = "arq"

    def __init__(self, redis_url: str, *, queue_name: str = "crosspilot") -> None:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings
        except ImportError as exc:  # pragma: no cover - 依赖未安装
            raise QueueBackendError(
                "CROSSPILOT_TASK_QUEUE=arq 需要安装 arq 与 redis：pip install arq redis"
            ) from exc
        from urllib.parse import urlparse

        parsed = urlparse(redis_url)
        self._redis_settings = RedisSettings(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 6379,
            database=int((parsed.path or "/0").strip("/") or 0),
        )
        self._create_pool = create_pool
        self._queue_name = queue_name
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def submit(self, task_id: str, job: Callable[[], None]) -> None:
        # arq 的 job 必须是可序列化的函数 + 参数；这里投递 task_id，
        # 由 crosspilot.worker.run_task 从数据库读取完整输入后执行。
        import asyncio
        import threading

        async def _enqueue() -> None:
            pool = await self._create_pool(self._redis_settings)
            try:
                await pool.enqueue_job("run_task", task_id, _queue_name=self._queue_name)
            finally:
                # redis-py asyncio 用 aclose()，旧版 arq 用 async_close()
                close = getattr(pool, "aclose", None) or getattr(pool, "async_close", None)
                if close is not None:
                    await close()

        def _run() -> None:
            asyncio.run(_enqueue())

        error: list[BaseException] = []

        def _target() -> None:
            try:
                _run()
            except BaseException as exc:  # noqa: BLE001 - 传给调用线程
                error.append(exc)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            _run()
        else:
            # FastAPI 的 async handler 里已有事件循环，不能嵌套 asyncio.run
            thread = threading.Thread(target=_target, daemon=True)
            thread.start()
            thread.join(timeout=10)
            if thread.is_alive():
                raise QueueBackendError("投递 arq 任务超时（Redis 无响应）")
        if error:
            raise QueueBackendError(
                f"无法连接 Redis（{redis_url_ref(self)}）：{error[0]}"
            ) from error[0]

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            self._cancelled.add(task_id)
        return True

    def is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._cancelled

    def is_active(self, task_id: str) -> bool:
        # 跨进程无法可靠判断，由 worker 的数据库状态决定
        return True

    def shutdown(self, wait: bool = False, timeout: float = 5.0) -> None:
        return None


def redis_url_ref(queue: ArqTaskQueue) -> str:  # pragma: no cover - 仅错误信息
    settings = queue._redis_settings
    return f"redis://{settings.host}:{settings.port}/{settings.database}"


def build_task_queue(settings) -> TaskQueue:
    """按配置构造队列；``arq`` 缺依赖时给出可操作错误，不静默降级。"""
    backend = (getattr(settings, "task_queue", "thread") or "thread").lower()
    if backend == "thread":
        return ThreadTaskQueue()
    if backend == "arq":
        return ArqTaskQueue(getattr(settings, "redis_url", "redis://127.0.0.1:6379/0"))
    raise QueueBackendError(f"未知的 CROSSPILOT_TASK_QUEUE={backend!r}，可选：thread / arq")


__all__ = [
    "ArqTaskQueue",
    "QueueBackendError",
    "TaskCancelled",
    "TaskQueue",
    "ThreadTaskQueue",
    "build_task_queue",
]
