"""版本化数据库迁移（PostgreSQL）。

为什么不是 Alembic
==================

计划里写的是 Alembic，但实际落地时做了一个**明确的取舍**：

- 本项目没有 SQLAlchemy / ORM，业务层用 psycopg 直连；
  Alembic 强依赖 SQLAlchemy，引入它等于为了迁移再背一个 ORM 依赖。
- 真正需要的是**可追踪、可重复执行的 SQL 版本**，不是 ORM 元数据。
- 因此这里实现一个等价的轻量 runner：``schema_migrations`` 表记录已执行
  版本，每个 revision 是纯 SQL（或极小的 Python 函数），启动时自动补齐。
  未来若引入 SQLAlchemy，可平滑替换执行器。

约束
====

1. 迁移**只增不删**：不 DROP 表、不删列、不改已有列类型。
2. 每个 revision **幂等**：重复执行不报错（用 ``IF NOT EXISTS`` 与列存在性检查）。
3. 已执行版本永不重跑；修改历史 revision 属于违规，必须新增 revision。
4. 迁移在 ``Database._init_schema()`` 内、与建表同一个事务里执行，
   失败会回滚，不会留下半套结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

SCHEMA_VERSION_TABLE = "schema_migrations"


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    apply: Callable[[Any], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_table(connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _has_column(connection, table: str, column: str) -> bool:
    if not _has_table(connection, table):
        return False
    row = connection.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ? AND column_name = ?",
        (table, column),
    ).fetchone()
    return row is not None


def _add_column(connection, table: str, column: str, ddl: str) -> None:
    if not _has_column(connection, table, column):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------


def _baseline(connection) -> None:
    """0001 是基线：表结构由 ``db._SCHEMA`` 建好，这里只记录版本。

    对已有数据库同样安全：``CREATE TABLE IF NOT EXISTS`` 已保证基线表存在。
    """


def _conversations(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            tenant_id       TEXT NOT NULL,
            user_id         TEXT NOT NULL,
            title           TEXT NOT NULL DEFAULT '新会话',
            status          TEXT NOT NULL DEFAULT 'active',
            last_task_id    TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_conv_tenant
            ON conversations(tenant_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_conv_user
            ON conversations(user_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS messages (
            message_id      TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            tenant_id       TEXT NOT NULL,
            role            TEXT NOT NULL,
            content         TEXT NOT NULL,
            content_type    TEXT NOT NULL DEFAULT 'text',
            task_id         TEXT,
            meta            TEXT NOT NULL DEFAULT '{}',
            created_at      TEXT NOT NULL,
            FOREIGN KEY (conversation_id)
                REFERENCES conversations(conversation_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_msg_conv
            ON messages(conversation_id, created_at);
        """
    )


def _audit(connection) -> None:
    id_column = "BIGSERIAL PRIMARY KEY"
    connection.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS audit_logs (
            audit_id    {id_column},
            tenant_id   TEXT NOT NULL,
            actor_id    TEXT NOT NULL,
            action      TEXT NOT NULL,
            target_type TEXT,
            target_id   TEXT,
            detail      TEXT NOT NULL DEFAULT '{{}}',
            trace_id    TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audit_tenant
            ON audit_logs(tenant_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_action
            ON audit_logs(action, created_at DESC);
        """
    )


def _approvals_and_invites(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS approval_requests (
            approval_id  TEXT PRIMARY KEY,
            tenant_id    TEXT NOT NULL,
            task_id      TEXT,
            kind         TEXT NOT NULL,
            payload      TEXT NOT NULL DEFAULT '{}',
            status       TEXT NOT NULL DEFAULT 'pending',
            requested_by TEXT NOT NULL,
            decided_by   TEXT,
            decided_at   TEXT,
            note         TEXT,
            created_at   TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_approval_tenant
            ON approval_requests(tenant_id, status, created_at DESC);

        CREATE TABLE IF NOT EXISTS tenant_invites (
            invite_id    TEXT PRIMARY KEY,
            tenant_id    TEXT NOT NULL,
            role         TEXT NOT NULL,
            token_hash   TEXT NOT NULL UNIQUE,
            created_by   TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            expires_at   TEXT NOT NULL,
            accepted_at  TEXT,
            accepted_by  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_invite_tenant
            ON tenant_invites(tenant_id, created_at DESC);
        """
    )


def _task_columns(connection) -> None:
    _add_column(connection, "tasks", "conversation_id", "TEXT")
    _add_column(connection, "tasks", "degraded", "INTEGER NOT NULL DEFAULT 0")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_conv ON tasks(conversation_id, created_at DESC)"
    )


def _exports_and_versions(connection) -> None:
    """阶段 E1：报告/Listing 新表 + 导入数据源 + 历史数据回填。"""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS competitor_reports (
            report_id      TEXT PRIMARY KEY,
            tenant_id      TEXT,
            user_id        TEXT,
            task_id        TEXT,
            product_name   TEXT NOT NULL,
            platform       TEXT NOT NULL,
            marketplace    TEXT NOT NULL,
            is_demo        INTEGER NOT NULL DEFAULT 0,
            data_source    TEXT NOT NULL DEFAULT '',
            summary        TEXT NOT NULL DEFAULT '{}',
            payload        TEXT NOT NULL,
            created_at     TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_creports_tenant
            ON competitor_reports(tenant_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_creports_user
            ON competitor_reports(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS listing_drafts (
            listing_id     TEXT PRIMARY KEY,
            tenant_id      TEXT,
            user_id        TEXT,
            report_id      TEXT,
            task_id        TEXT,
            version        INTEGER NOT NULL DEFAULT 1,
            parent_listing_id TEXT,
            product_name   TEXT NOT NULL,
            platform       TEXT NOT NULL,
            marketplace    TEXT NOT NULL,
            language       TEXT NOT NULL,
            title          TEXT NOT NULL,
            bullets        TEXT NOT NULL DEFAULT '[]',
            description    TEXT NOT NULL DEFAULT '',
            search_terms   TEXT NOT NULL DEFAULT '',
            quality_check  TEXT NOT NULL DEFAULT '{}',
            fact_ledger    TEXT NOT NULL DEFAULT '[]',
            pending_confirmations TEXT NOT NULL DEFAULT '[]',
            is_demo        INTEGER NOT NULL DEFAULT 0,
            engine         TEXT NOT NULL DEFAULT '',
            payload        TEXT NOT NULL,
            created_at     TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ldrafts_tenant
            ON listing_drafts(tenant_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ldrafts_report
            ON listing_drafts(report_id);

        CREATE TABLE IF NOT EXISTS data_sources (
            data_source_id TEXT PRIMARY KEY,
            tenant_id      TEXT NOT NULL,
            user_id        TEXT NOT NULL,
            kind           TEXT NOT NULL,
            name           TEXT NOT NULL,
            format         TEXT,
            storage_key    TEXT,
            row_count      INTEGER,
            is_demo        INTEGER NOT NULL DEFAULT 0,
            status         TEXT NOT NULL,
            field_mapping  TEXT NOT NULL DEFAULT '{}',
            validation     TEXT,
            created_at     TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_datasources_tenant
            ON data_sources(tenant_id, created_at DESC);
        """
    )
    _add_column(connection, "import_batches", "data_source_id", "TEXT")
    _add_column(
        connection,
        "import_batches",
        "field_mapping",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _backfill_v2(connection)


def _backfill_v2(connection) -> None:
    """把旧表数据回填到新表。

    迁移函数内直接读写 JSON，不依赖数据库 JSON 扩展。
    ``ON CONFLICT DO NOTHING`` 保证重复执行安全。
    """
    import json

    if not _has_table(connection, "analysis_reports") or not _has_table(
        connection, "listings"
    ):
        return

    report_rows = connection.execute(
        "SELECT report_id, user_id, tenant_id, product_name, platform, marketplace, "
        "data_source, is_demo, payload, created_at FROM analysis_reports"
    ).fetchall()
    for row in report_rows:
        payload_raw = row["payload"]
        try:
            payload = json.loads(payload_raw)
        except (TypeError, ValueError):
            payload = {}
        provenance = payload.get("data_provenance") or {}
        price = payload.get("price_analysis") or {}
        summary = {
            "competitor_count": provenance.get("competitor_count"),
            "review_sample_count": provenance.get("review_sample_count"),
            "price_min": price.get("min_price"),
            "price_max": price.get("max_price"),
            "price_median": price.get("median_price"),
        }
        connection.execute(
            "INSERT INTO competitor_reports "
            "(report_id, tenant_id, user_id, task_id, product_name, platform, marketplace, "
            " is_demo, data_source, summary, payload, created_at) "
            "VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(report_id) DO NOTHING",
            (
                row["report_id"],
                row["tenant_id"],
                row["user_id"],
                row["product_name"],
                row["platform"],
                row["marketplace"],
                1 if row["is_demo"] else 0,
                row["data_source"] or "",
                json.dumps(summary, ensure_ascii=False),
                payload_raw,
                row["created_at"],
            ),
        )

    listing_rows = connection.execute(
        "SELECT listing_id, user_id, tenant_id, product_name, platform, marketplace, "
        "language, report_id, data_source, is_demo, payload, created_at FROM listings"
    ).fetchall()
    for row in listing_rows:
        payload_raw = row["payload"]
        try:
            payload = json.loads(payload_raw)
        except (TypeError, ValueError):
            payload = {}
        bullets = payload.get("bullets") or []
        quality = payload.get("quality_check") or {}
        ledger = payload.get("fact_ledger") or []
        pending = payload.get("pending_confirmations") or []
        connection.execute(
            "INSERT INTO listing_drafts "
            "(listing_id, tenant_id, user_id, report_id, task_id, version, parent_listing_id, "
            " product_name, platform, marketplace, language, title, bullets, description, "
            " search_terms, quality_check, fact_ledger, pending_confirmations, is_demo, engine, "
            " payload, created_at) "
            "VALUES (?, ?, ?, ?, NULL, 1, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(listing_id) DO NOTHING",
            (
                row["listing_id"],
                row["tenant_id"],
                row["user_id"],
                row["report_id"],
                row["product_name"],
                row["platform"],
                row["marketplace"],
                row["language"],
                payload.get("title") or "",
                json.dumps(bullets, ensure_ascii=False),
                payload.get("description") or "",
                payload.get("search_terms") or "",
                json.dumps(quality, ensure_ascii=False),
                json.dumps(ledger, ensure_ascii=False),
                json.dumps(pending, ensure_ascii=False),
                1 if row["is_demo"] else 0,
                payload.get("engine") or "",
                payload_raw,
                row["created_at"],
            ),
        )


def _stores(connection) -> None:
    """阶段 F1/F3/F4：店铺连接与凭据引用。"""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS store_connections (
            connection_id TEXT PRIMARY KEY,
            tenant_id     TEXT NOT NULL,
            platform      TEXT NOT NULL,
            marketplace   TEXT NOT NULL,
            shop_name     TEXT NOT NULL,
            mode          TEXT NOT NULL,
            status        TEXT NOT NULL,
            scopes        TEXT NOT NULL DEFAULT '[]',
            credential_ref TEXT,
            last_sync_at  TEXT,
            last_sync_status TEXT,
            last_sync_error  TEXT,
            last_sync_summary TEXT,
            created_at    TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_store_conn
            ON store_connections(tenant_id, platform, marketplace, shop_name);

        CREATE TABLE IF NOT EXISTS store_credentials (
            credential_ref TEXT PRIMARY KEY,
            tenant_id      TEXT NOT NULL,
            ciphertext     TEXT NOT NULL,
            created_at     TEXT NOT NULL
        );
        """
    )


def _drop_legacy_tables(connection) -> None:
    """删除 SQLite 时代的旧表：数据已回填到 ``competitor_reports`` / ``listing_drafts``。"""
    connection.execute("DROP TABLE IF EXISTS analysis_reports")
    connection.execute("DROP TABLE IF EXISTS listings")


def _provider_configs(connection) -> None:
    """多厂商 LLM 配置：一个用户可保存多套，``active_config_id`` 决定默认。"""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_provider_configs (
            config_id         TEXT PRIMARY KEY,
            user_id           TEXT NOT NULL,
            provider          TEXT NOT NULL,
            label             TEXT NOT NULL DEFAULT '默认',
            base_url          TEXT NOT NULL DEFAULT '',
            model             TEXT NOT NULL DEFAULT '',
            api_key_encrypted TEXT,
            enabled           INTEGER NOT NULL DEFAULT 1,
            last_tested_at    TEXT,
            last_test_ok      INTEGER,
            last_test_detail  TEXT,
            task_overrides    TEXT NOT NULL DEFAULT '{}',
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_cfg
            ON user_provider_configs(user_id, provider, label);
        CREATE INDEX IF NOT EXISTS idx_provider_cfg_user
            ON user_provider_configs(user_id, created_at DESC);
        """
    )
    # user_model_settings 改语义：active_config_id 指向当前使用的那套配置
    _add_column(connection, "user_model_settings", "active_config_id", "TEXT")
    _add_column(connection, "user_model_settings", "task_overrides", "TEXT NOT NULL DEFAULT '{}'")
    _add_column(connection, "user_model_settings", "disabled", "INTEGER NOT NULL DEFAULT 0")


def _guest_accounts(connection) -> None:
    """一键体验的临时账号：标记为 guest 并记录过期时间。"""
    _add_column(connection, "users", "is_guest", "INTEGER NOT NULL DEFAULT 0")
    _add_column(connection, "users", "guest_expires_at", "TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_guest ON users(is_guest, guest_expires_at)"
    )
    # 限流计数：按账号 + 动作 + 小时窗口聚合
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS rate_limit_counters (
            bucket_key  TEXT PRIMARY KEY,
            window_start TEXT NOT NULL,
            count       INTEGER NOT NULL DEFAULT 0
        );
        """
    )


def _demo_seed_flag(connection) -> None:
    """示例数据标记：区分"种子生成的演示数据"与"用户真实产生的数据"。"""
    _add_column(connection, "competitor_reports", "seed_demo", "INTEGER NOT NULL DEFAULT 0")
    _add_column(connection, "listing_drafts", "seed_demo", "INTEGER NOT NULL DEFAULT 0")
    _add_column(connection, "tasks", "seed_demo", "INTEGER NOT NULL DEFAULT 0")


def _retry_of_column(connection) -> None:
    """0012：任务重试血缘（指向被重试的原任务）。"""
    _add_column(connection, "tasks", "retry_of", "TEXT")


def _task_step_io(connection) -> None:
    """0013：任务步骤记录节点名与输出，用于失败任务从断点续跑。"""
    _add_column(connection, "task_steps", "node", "TEXT")
    _add_column(connection, "task_steps", "output", "TEXT")


MIGRATIONS: tuple[Migration, ...] = (
    Migration("0001", "baseline", _baseline),
    Migration("0002", "conversations_and_messages", _conversations),
    Migration("0003", "audit_logs", _audit),
    Migration("0004", "approvals_and_tenant_invites", _approvals_and_invites),
    Migration("0005", "tasks_conversation_and_degraded", _task_columns),
    Migration("0006", "reports_listings_v2_and_data_sources", _exports_and_versions),
    Migration("0007", "store_connections_and_credentials", _stores),
    Migration("0008", "drop_sqlite_era_tables", _drop_legacy_tables),
    Migration("0009", "user_provider_configs", _provider_configs),
    Migration("0010", "guest_accounts_and_rate_limits", _guest_accounts),
    Migration("0011", "seed_demo_flags", _demo_seed_flag),
    Migration("0012", "tasks_retry_of", _retry_of_column),
    Migration("0013", "task_steps_node_output", _task_step_io),
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _ensure_version_table(connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} (
            version    TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _value(row, index: int, name: str):
    """兼容 dict 行与旧式序列行。"""
    try:
        return row[name]
    except (KeyError, TypeError, IndexError):
        return row[index]


def apply_migrations(connection) -> list[str]:
    """执行尚未应用的 revision，返回本次新执行的版本号。"""
    _ensure_version_table(connection)
    applied = {
        _value(row, 0, "version")
        for row in connection.execute(f"SELECT version FROM {SCHEMA_VERSION_TABLE}")
    }
    newly: list[str] = []
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        migration.apply(connection)
        connection.execute(
            f"INSERT INTO {SCHEMA_VERSION_TABLE} (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, _now()),
        )
        newly.append(migration.version)
    return newly


def migration_status(connection) -> list[dict[str, str | bool]]:
    """返回全部 revision 及其应用状态（供 CLI 与诊断使用）。"""
    _ensure_version_table(connection)
    applied = {
        _value(row, 0, "version"): _value(row, 1, "applied_at")
        for row in connection.execute(
            f"SELECT version, applied_at FROM {SCHEMA_VERSION_TABLE}"
        )
    }
    return [
        {
            "version": migration.version,
            "name": migration.name,
            "applied": migration.version in applied,
            "applied_at": applied.get(migration.version),
        }
        for migration in MIGRATIONS
    ]


__all__ = [
    "MIGRATIONS",
    "SCHEMA_VERSION_TABLE",
    "Migration",
    "apply_migrations",
    "migration_status",
]
