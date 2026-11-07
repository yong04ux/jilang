"""LangGraph Checkpoint。

为什么必须有这一层
==================

`partial` 暂停依赖 ``interrupt()``，而 ``interrupt`` **必须配 checkpointer**：
没有它，LangGraph 无法保存"停在哪个节点、当时状态是什么"，也就谈不上恢复。

后端选择
========

- **postgres**（默认，有数据库时）：``langgraph-checkpoint-postgres`` 的
  ``PostgresSaver``。暂停状态写进数据库，**进程重启后仍能恢复**。
- **memory**（测试/无数据库时）：``InMemorySaver``。重启即丢。

选哪个由 ``CROSSPILOT_CHECKPOINT_BACKEND`` 决定，默认 ``auto``：
有数据库串且能连上就用 postgres，否则退 memory。真实后端通过
``backend_name()`` 暴露出去，让接口能如实说"这次暂停重启后会丢"，
而不是让人以为已经持久化了。

连接细节（踩过的坑）
====================

1. **长连接 + ``prepare_threshold=None``**：生产走 Supabase 的 pgbouncer
   transaction 模式（``:6543``），它不支持会话级预处理语句。psycopg3 默认在
   第 5 次执行后启用 prepared statement，直接踩雷。关掉才能稳定复用连接。
2. **单例按数据库 URL 缓存**：暂停与恢复是两次请求，必须命中同一份状态；
   不同 URL（本地/测试/线上）必须彼此隔离。
3. **``setup()`` 是幂等建表**（``CREATE TABLE IF NOT EXISTS``）。
   测试里 ``reset_schema()`` 会 DROP 整个 public schema，所以测试支撑代码
   在重建 schema 之后要再调一次 ``setup_checkpointer()``。

清理策略
========

checkpoint 只在"暂停中"有价值，任务进终态后线程就是死数据：

- ``workflows.apply_result`` 落终态后调 ``cleanup_thread``；
- 暂停中任务被取消时，``cancel_task`` 也清理；
- **删除是尽力而为**：失败只记 warning，绝不让收尾失败。清理不掉只是留下
  一点无用数据，而收尾失败会让任务卡在 running——代价不对等。

保留期：不设 TTL。终态即删比"存 7 天"更符合本项目（暂停恢复都是分钟级人工确认）；
将来要做审计级重放，再引入保留期，而不是现在拍一个数字。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: 按 key 缓存 saver；内存后端用 ``"memory"``，Postgres 用 ``postgres::<url>``
_SAVERS: dict[str, Any] = {}
#: 已经成功建过表的 key（仅一次）
_READY: set[str] = set()
#: 回落到内存后端时只提醒一次，避免刷日志
_FALLBACK_WARNED = False


def _settings():
    from ..config import get_settings

    return get_settings()


def backend_choice() -> str:
    """``auto`` / ``postgres`` / ``memory``。"""
    return (getattr(_settings(), "checkpoint_backend", "auto") or "auto").lower()


def _database_url() -> str:
    return str(getattr(_settings(), "database_url", "") or "")


def _build_postgres_saver(url: str) -> Any:
    """建一个绑定长连接的 PostgresSaver。

    ``prepare_threshold=None`` 是关键（见模块文档）。连接用 autocommit：
    saver 自己管事务边界，外层再包事务会和 LangGraph 的写入顺序打架。
    """
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    connection = psycopg.Connection.connect(
        url, autocommit=True, prepare_threshold=None
    )
    return PostgresSaver(connection)


def _memory_saver() -> Any:
    if "memory" not in _SAVERS:
        from langgraph.checkpoint.memory import InMemorySaver

        _SAVERS["memory"] = InMemorySaver()
    return _SAVERS["memory"]


def get_checkpointer() -> Any:
    """返回当前进程使用的 checkpointer（按数据库 URL 缓存）。

    单例是硬要求：暂停和恢复是两次请求，必须命中同一份状态。
    """
    global _FALLBACK_WARNED

    if backend_choice() == "memory":
        return _memory_saver()

    url = _database_url()
    if not url:
        return _memory_saver()

    key = f"postgres::{url}"
    if key in _SAVERS:
        return _SAVERS[key]

    try:
        saver = _build_postgres_saver(url)
    except Exception as exc:  # noqa: BLE001 - 连不上就如实降级，但要留痕
        if not _FALLBACK_WARNED:
            logger.warning(
                "checkpoint 无法连接数据库，已回落到内存后端；"
                "暂停中的工作流在进程重启后会丢失：%s",
                exc,
            )
            _FALLBACK_WARNED = True
        return _memory_saver()

    _SAVERS[key] = saver
    # 建完立刻建表（幂等，每个 URL 只做一次）。
    # 为什么不能只依赖启动时的 setup_checkpointer()：进程生命周期里 schema 可能被
    # 别的东西重建（测试的 reset_schema、运维手工 DROP），那时缓存里的 saver
    # 会对着"没有表的库"写，报错位置在 LangGraph 内部，非常难查。
    # 放在这里等于加了一层自愈：新连接一定先保证表存在。
    if key not in _READY:
        try:
            saver.setup()
            _READY.add(key)
        except Exception as exc:  # noqa: BLE001 - 建表失败仍返回 saver，让它自己报错
            logger.warning("checkpoint 表初始化失败：%s", exc)
    return saver


def backend_name() -> str:
    """当前**实际**使用的后端：``postgres`` 或 ``memory``。

    接口用它决定要不要提醒"重启会丢"。不要用"配了 postgres 就一定持久"来推断。
    """
    return "memory" if type(get_checkpointer()).__name__ == "InMemorySaver" else "postgres"


def setup_checkpointer() -> None:
    """建 checkpoint 表（幂等）。应用启动后、测试重建 schema 后各调一次。"""
    if backend_choice() == "memory":
        return
    url = _database_url()
    if not url:
        return
    key = f"postgres::{url}"
    if key in _READY:
        return
    saver = get_checkpointer()
    if type(saver).__name__ == "InMemorySaver":
        return
    try:
        saver.setup()
        _READY.add(key)
    except Exception as exc:  # noqa: BLE001 - 建表失败不阻断启动
        logger.warning("checkpoint 表初始化失败，恢复能力可能不可用：%s", exc)


def reset_checkpointer() -> None:
    """丢弃全部 saver 与建表标记。**仅供测试与本地调试**。

    线上调用会让所有暂停中的工作流失去状态——不要在请求路径里用。

    必须真的把底层连接关掉：``PostgresSaver`` 持有 psycopg 连接，
    只把引用从缓存里删掉的话连接还挂在服务端，跑几百个用例就会把
    ``max_connections`` 耗光（表现为测试进行到一半突然连不上库）。
    """
    for saver in list(_SAVERS.values()):
        connection = getattr(saver, "conn", None)
        closer = getattr(connection, "close", None)
        if closer is not None:
            try:
                closer()
            except Exception:  # noqa: BLE001 - 关闭失败不影响重置
                pass
    _SAVERS.clear()
    _READY.clear()


# ---------------------------------------------------------------------------
# 线程标识与读取
# ---------------------------------------------------------------------------


def thread_id(tenant_id: str, task_id: str) -> str:
    """工作流线程标识：租户 + 任务。两者缺一不可。

    拼上租户不是"顺手加的"：只按 ``task_id`` 查线程的话，一个知道 task_id
    的人就能跨租户接管别人的暂停流程。拼上租户后跨租户**根本找不到线程**
    （纵深防御第一层），接口层的任务归属校验是第二层。
    """
    tenant = (tenant_id or "").strip()
    task = (task_id or "").strip()
    if not tenant or not task:
        raise ValueError("线程标识需要租户与任务，缺一不可")
    return f"{tenant}:{task}"


def thread_config(tenant_id: str, task_id: str) -> dict[str, Any]:
    """LangGraph 调用配置。"""
    return {"configurable": {"thread_id": thread_id(tenant_id, task_id)}}


def pending_interrupts(graph: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    """读出当前线程待处理的 interrupt 载荷（给接口返回用）。

    返回 ``{"id": ..., "value": {...}}`` 列表。拿不到就返回空列表——
    "没有待确认"和"读不到状态"在调用方看来是同一件事：不能恢复。
    """
    try:
        snapshot = graph.get_state(config)
    except Exception:  # noqa: BLE001 - 读不到就是没有，不把读取失败变成 500
        return []
    found: list[dict[str, Any]] = []
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            found.append({"id": getattr(item, "id", ""), "value": getattr(item, "value", {})})
    return found


def cleanup_thread(tenant_id: str, task_id: str) -> bool:
    """删除某个任务的 checkpoint（尽力而为）。返回是否真的删掉了。

    **只在任务进终态后调用。** 删不掉不抛异常：清理失败只是留下死数据，
    抛异常却会让收尾失败、任务卡在 running——代价不对等。
    """
    if not tenant_id or not task_id:
        return False
    try:
        deleter = getattr(get_checkpointer(), "delete_thread", None)
        if deleter is None:
            return False
        deleter(thread_id(tenant_id, task_id))
        return True
    except Exception as exc:  # noqa: BLE001 - 见 docstring
        logger.warning("清理 checkpoint 失败（不影响任务收尾）：%s", exc)
        return False


__all__ = [
    "backend_choice",
    "backend_name",
    "cleanup_thread",
    "get_checkpointer",
    "pending_interrupts",
    "reset_checkpointer",
    "setup_checkpointer",
    "thread_config",
    "thread_id",
]
