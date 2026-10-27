"""测试用 PostgreSQL 辅助：连接串与 schema 重置。"""

from __future__ import annotations

import os

import pytest


def database_url() -> str:
    url = os.environ.get("CROSSPILOT_TEST_DATABASE_URL") or os.environ.get(
        "CROSSPILOT_DATABASE_URL"
    )
    if not url:
        pytest.exit(
            "测试需要 PostgreSQL：请设置 CROSSPILOT_TEST_DATABASE_URL"
            "（或 CROSSPILOT_DATABASE_URL）。",
            returncode=2,
        )
    return url


def reset_schema(url: str | None = None) -> None:
    """清空 public schema；仅用于测试库。

    重建 schema 后必须重跑 checkpoint 建表：langgraph 的 checkpoint 表在
    public 里，被 DROP 之后 saver 一写就 UndefinedTable，而报错位置在
    LangGraph 内部，排查成本很高。
    """
    import psycopg

    target = url or database_url()
    with psycopg.connect(target, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connection.execute("CREATE SCHEMA public")

    from crosspilot.agent import checkpoint

    checkpoint.reset_checkpointer()
    checkpoint.setup_checkpointer()
