"""``ThreadTaskQueue`` 的并发上限与排队行为。

背景：``CROSSPILOT_MAX_JOBS`` 曾经只是个摆设 —— ``Settings`` 里没有这个字段，
``ThreadTaskQueue`` 也没有任何并发控制，每个任务立刻起一个线程。免费实例
（Render 512MB）上几个用户同时点分析就有 OOM 风险。这组测试锁住修复后的语义：

- ``submit`` 永不阻塞调用方（API 仍然"提交即返回"）
- 超出上限的任务在线程内排队，不并发执行
- 排队期间被取消的任务不会被执行
"""

from __future__ import annotations

import threading
import time

from crosspilot.services.queue import ThreadTaskQueue, build_task_queue


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_submit_does_not_block_and_honours_max_jobs():
    """max_jobs=1 时任务串行执行，且 submit 立刻返回。"""
    queue = ThreadTaskQueue(max_jobs=1)
    order: list[str] = []
    first_started = threading.Event()
    release_first = threading.Event()

    def first() -> None:
        order.append("first-start")
        first_started.set()
        release_first.wait(3)
        order.append("first-end")

    def second() -> None:
        order.append("second-start")

    started_at = time.time()
    queue.submit("t1", first)
    # submit 必须在毫秒级返回，即使并发已满
    assert time.time() - started_at < 1.0
    assert first_started.wait(3)

    queue.submit("t2", second)
    assert time.time() - started_at < 1.0

    # 第一个还没结束，第二个不许开始
    time.sleep(0.2)
    assert "second-start" not in order

    release_first.set()
    assert _wait_until(lambda: "second-start" in order)
    assert order == ["first-start", "first-end", "second-start"]

    queue.shutdown(wait=False)


def test_cancelled_while_queued_is_never_executed():
    """排队期间被取消的任务，拿到空位后不应再执行。"""
    queue = ThreadTaskQueue(max_jobs=1)
    executed: list[str] = []
    first_started = threading.Event()
    release_first = threading.Event()

    def blocking() -> None:
        first_started.set()
        release_first.wait(3)

    def should_not_run() -> None:
        executed.append("second")

    queue.submit("t1", blocking)
    assert first_started.wait(3)
    queue.submit("t2", should_not_run)
    assert queue.cancel("t2") is True
    assert queue.is_cancelled("t2") is True

    release_first.set()
    time.sleep(0.4)
    assert executed == []

    queue.shutdown(wait=False)


def test_non_positive_max_jobs_means_unlimited():
    """max_jobs<=0 时不限制并发（保留原来的行为）。"""
    queue = ThreadTaskQueue(max_jobs=0)
    assert queue.max_jobs == 0
    assert queue._slots is None


def test_build_task_queue_passes_max_jobs_from_settings():
    """工厂必须把 Settings.max_jobs 传下去，否则环境变量仍然无效。"""
    from crosspilot.config import Settings

    settings = Settings(task_queue="thread", max_jobs=2)
    queue = build_task_queue(settings)
    assert isinstance(queue, ThreadTaskQueue)
    assert queue.max_jobs == 2
