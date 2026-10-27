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


def test_0014_removes_unsupported_node_overrides(pg_url):
    """analyze 不再是可覆盖节点，旧配置里的该键必须被清掉，listing 保留。

    迁移函数按「执行当时的清单」硬编码，所以这里直接调它验证行为，
    而不是依赖 ``OVERRIDE_NODES`` 的当前取值。
    """
    from crosspilot.persistence.migrations import _clean_task_overrides

    db = Database(pg_url)
    db.create_user("u-ov", "ov_user", "hash")
    with db.connect() as connection:
        connection.execute(
            """INSERT INTO user_provider_configs
               (config_id, user_id, provider, label, base_url, model, enabled,
                task_overrides, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                "cfg-ov",
                "u-ov",
                "deepseek",
                "主",
                "",
                "deepseek-flash",
                1,
                '{"analyze": {"model": "x"}, "listing": {"config_id": "cfg-2"}}',
                "2026-10-27T00:00:00+00:00",
                "2026-10-27T00:00:00+00:00",
            ),
        )

    with db.connect() as connection:
        _clean_task_overrides(connection)

    with db.connect() as connection:
        row = connection.execute(
            "SELECT task_overrides FROM user_provider_configs WHERE config_id = ?",
            ("cfg-ov",),
        ).fetchone()
    import json

    assert json.loads(row["task_overrides"]) == {"listing": {"config_id": "cfg-2"}}


def test_0014_leaves_invalid_json_alone(pg_url):
    """坏 JSON 不动：读取端本来就当空对象处理，删掉反而丢掉可修复的数据。"""
    from crosspilot.persistence.migrations import _clean_task_overrides

    db = Database(pg_url)
    db.create_user("u-bad", "bad_user", "hash")
    with db.connect() as connection:
        connection.execute(
            """INSERT INTO user_provider_configs
               (config_id, user_id, provider, label, base_url, model, enabled,
                task_overrides, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                "cfg-bad",
                "u-bad",
                "deepseek",
                "主",
                "",
                "m",
                1,
                "{not json",
                "2026-10-27T00:00:00+00:00",
                "2026-10-27T00:00:00+00:00",
            ),
        )

    with db.connect() as connection:
        _clean_task_overrides(connection)

    with db.connect() as connection:
        row = connection.execute(
            "SELECT task_overrides FROM user_provider_configs WHERE config_id = ?",
            ("cfg-bad",),
        ).fetchone()
    assert row["task_overrides"] == "{not json"
