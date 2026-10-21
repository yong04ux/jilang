"""异步任务的外层保护。

任何异常都必须把任务落到终态：任务停在 ``running`` 会让前端无限轮询。
"""

from __future__ import annotations

import logging
from typing import Callable

from ..services.queue import TaskCancelled

logger = logging.getLogger(__name__)


def run_guarded(recorder, job: Callable[[], None]) -> None:
    """执行队列任务；异常一律落库为 failed / cancelled，不再抛给线程池。"""
    try:
        job()
    except TaskCancelled:
        # job 自己已经把任务落成 cancelled
        logger.info("任务在检查点取消：%s", recorder.task_id)
    except BaseException as exc:  # noqa: BLE001 - 兜底，不能再抛
        recorder.fail(code="worker_error", message=f"{type(exc).__name__}: {exc}"[:500])
        logger.exception("任务执行失败：%s", recorder.task_id)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise


__all__ = ["run_guarded"]
