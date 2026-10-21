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
    """清空 public schema；仅用于测试库。"""
    import psycopg

    with psycopg.connect(url or database_url(), autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connection.execute("CREATE SCHEMA public")
