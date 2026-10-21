"""PG 迁移测试（SQLite 后端已移除）。

每个用例重置 public schema；`schema_migrations` 由 runner 维护。
"""

from __future__ import annotations

import pytest

from crosspilot.persistence.db import Database
from crosspilot.persistence.migrations import MIGRATIONS, apply_migrations


@pytest.fixture()
def pg_url():
    from pg_support import database_url, reset_schema

    url = database_url()
    reset_schema(url)
    return url


def test_fresh_database_applies_all_migrations(pg_url):
    db = Database(pg_url)
    status = db.migration_status()
    assert len(status) == len(MIGRATIONS)
    assert all(item["applied"] for item in status)
    assert [item["version"] for item in status] == [m.version for m in MIGRATIONS]

    with db.connect() as connection:
        tables = {
            row["table_name"]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            )
        }
    assert {
        "schema_migrations",
        "conversations",
        "messages",
        "audit_logs",
        "approval_requests",
        "tenant_invites",
        "competitor_reports",
        "listing_drafts",
        "data_sources",
        "store_connections",
    } <= tables


def test_migrations_are_idempotent(pg_url):
    db = Database(pg_url)
    with db.connect() as connection:
        assert apply_migrations(connection) == []
        assert apply_migrations(connection) == []
        applied = connection.execute(
            "SELECT COUNT(*) AS n FROM schema_migrations"
        ).fetchone()["n"]
    assert applied == len(MIGRATIONS)


def test_reinitializing_preserves_data(pg_url):
    db = Database(pg_url)
    db.create_tenant("tenant-keep", "保留租户", "keep-tenant")
    again = Database(pg_url)
    tenant = again.get_tenant("tenant-keep")
    assert tenant is not None
    assert tenant["name"] == "保留租户"
