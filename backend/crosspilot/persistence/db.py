"""PostgreSQL 持久化层。

唯一数据库后端；SQLite 已移除。

- 只依赖 ``psycopg``（异步/同步均可，这里用同步）；
- 所有主键为字符串，JSON 内容整体存为 TEXT，便于审计与迁移；
- 业务 SQL 用 ``?`` 占位符，由 ``_PgConnection`` 统一转成 ``%s``，
  这样从 SQLite 迁移时业务代码无需逐条改写。
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .migrations import apply_migrations, migration_status


class DatabaseError(RuntimeError):
    """数据库不可用（配置错误、驱动缺失、连接失败）。"""


class _PgConnection:
    """把 psycopg 连接适配成 db.py 使用的极简接口。

    只做两件事：``?`` → ``%s`` 占位符转换、``executescript`` 拆分。
    dict 行结果由 psycopg 的 ``dict_row`` 提供。
    """

    def __init__(self, connection: Any):
        self._connection = connection

    def execute(self, sql: str, params: Any = ()):
        return self._connection.execute(sql.replace("?", "%s"), params or ())

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            text = statement.strip()
            if text:
                self._connection.execute(text)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def _redact_dsn(dsn: str) -> str:
    return re.sub(r"(://[^:/@]+:)[^@]+@", r"\1***@", dsn)


def _connect_kwargs(dsn: str) -> dict[str, Any]:
    """连接参数：Supabase pooler / 免费实例需要的保守设置。

    - ``connect_timeout``：Render 冷启动 + pooler 排队时，默认无限等待会挂死；
    - ``application_name``：方便在 Supabase / PG 侧定位是哪个服务在建连；
    - ``sslmode=require``：Supabase 强制 TLS，连接串里没写时补上；
    - ``prepare_threshold=None``：**用 PgBouncer transaction 模式时必需**，
      否则 psycopg3 的预编译语句会在不同后端连接间失效，报
      "prepared statement already exists"。
    """
    kwargs: dict[str, Any] = {"connect_timeout": 10}
    lowered = dsn.lower()
    is_local = "127.0.0.1" in lowered or "localhost" in lowered
    if not is_local:
        kwargs["application_name"] = "crosspilot"
        if "sslmode=" not in lowered:
            kwargs["sslmode"] = "require"
    # 6543 是 Supabase 的 transaction-mode pooler 端口
    if ":6543" in dsn:
        kwargs["prepare_threshold"] = None
    return kwargs



_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS tenant_members (
    tenant_id  TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('owner','admin','editor','viewer')),
    joined_at  TEXT NOT NULL,
    PRIMARY KEY (tenant_id, user_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_members_user ON tenant_members(user_id);

-- Agent / Skill / Tool 注册表。tenant_id 为 NULL 表示平台内置定义。
CREATE TABLE IF NOT EXISTS agent_definitions (
    agent_key   TEXT NOT NULL,
    tenant_id   TEXT,
    name        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    input_schema  TEXT NOT NULL DEFAULT '{}',
    output_schema TEXT NOT NULL DEFAULT '{}',
    skill_keys  TEXT NOT NULL DEFAULT '[]',
    tool_keys   TEXT NOT NULL DEFAULT '[]',
    version     TEXT NOT NULL,
    status      TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (agent_key, tenant_id)
);

CREATE TABLE IF NOT EXISTS skill_definitions (
    skill_key   TEXT NOT NULL,
    tenant_id   TEXT,
    name        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    input_schema  TEXT NOT NULL DEFAULT '{}',
    output_schema TEXT NOT NULL DEFAULT '{}',
    version     TEXT NOT NULL,
    status      TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (skill_key, tenant_id)
);

CREATE TABLE IF NOT EXISTS tool_definitions (
    tool_key    TEXT NOT NULL,
    tenant_id   TEXT,
    name        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    input_schema  TEXT NOT NULL DEFAULT '{}',
    output_schema TEXT NOT NULL DEFAULT '{}',
    version     TEXT NOT NULL,
    status      TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (tool_key, tenant_id)
);

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id    TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    source_format TEXT NOT NULL,
    total_rows  INTEGER NOT NULL,
    valid_rows  INTEGER NOT NULL,
    errors      TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    last_seen_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_model_settings (
    user_id        TEXT PRIMARY KEY,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    base_url       TEXT,
    api_key_encrypted TEXT,
    temperature    REAL,
    max_tokens     INTEGER,
    timeout        REAL,
    max_retries    INTEGER,
    thinking       INTEGER NOT NULL DEFAULT 0,
    reasoning_effort TEXT,
    updated_at     TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    origin       TEXT NOT NULL DEFAULT 'form',
    type         TEXT NOT NULL,
    title        TEXT NOT NULL,
    status       TEXT NOT NULL,
    input        TEXT NOT NULL DEFAULT '{}',
    output       TEXT,
    error_code   TEXT,
    error_message TEXT,
    result_ref   TEXT,
    trace_id     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS task_steps (
    step_id     TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    duration_ms INTEGER,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(user_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_steps_task ON task_steps(task_id, seq);
"""


class Database:
    """线程安全的 PostgreSQL 封装（每次操作使用独立连接）。"""

    def __init__(self, database_url: str, *, auto_migrate: bool = True):
        self._dsn = (database_url or "").strip()
        if not self._dsn:
            raise DatabaseError(
                "缺少数据库连接串：请设置 CROSSPILOT_DATABASE_URL，"
                "例如 postgresql://user:pass@127.0.0.1:5432/crosspilot"
            )
        if not self._dsn.startswith(("postgres://", "postgresql://")):
            raise DatabaseError("CROSSPILOT_DATABASE_URL 必须是 PostgreSQL 连接串")
        try:
            import psycopg  # noqa: F401
        except ImportError as exc:  # pragma: no cover - 取决于环境
            raise DatabaseError(
                "PostgreSQL 后端需要 psycopg：pip install 'psycopg[binary]>=3.2'"
            ) from exc
        self.path = _redact_dsn(self._dsn)
        self.auto_migrate = auto_migrate
        self._lock = threading.Lock()
        if auto_migrate:
            self._init_schema()

    def init_schema(self) -> None:
        """显式执行建表与迁移（``auto_migrate=false`` 时由 CLI 调用）。"""
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        import psycopg
        from psycopg.rows import dict_row

        try:
            raw = psycopg.connect(
                self._dsn,
                row_factory=dict_row,
                autocommit=False,
                **_connect_kwargs(self._dsn),
            )
        except Exception as exc:  # noqa: BLE001 - 启动失败要明确
            raise DatabaseError(f"无法连接 PostgreSQL：{exc}") from exc
        connection = _PgConnection(raw)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._lock, self.connect() as connection:
            connection.executescript(_SCHEMA)
            self._migrate(connection)
            # 版本化迁移：只执行尚未应用的 revision（详见 migrations.py）
            apply_migrations(connection)

    def migration_status(self) -> list[dict[str, Any]]:
        """返回迁移版本表，供 ``python -m crosspilot migrate`` 使用。"""
        with self.connect() as connection:
            return migration_status(connection)

    # -- 结构检查 ----------------------------------------------------------
    def _columns(self, connection: Any, table: str) -> list[str]:
        rows = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return [row["column_name"] for row in rows]

    def _tables(self, connection: Any) -> list[str]:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        ).fetchall()
        return [row["table_name"] for row in rows]

    def _migrate(self, connection: Any) -> None:
        """为旧库补齐新增列；不删除任何已有列或数据。"""
        if "import_batches" in set(self._tables(connection)):
            batch_columns = set(self._columns(connection, "import_batches"))
            if "user_id" not in batch_columns:
                connection.execute("ALTER TABLE import_batches ADD COLUMN user_id TEXT")

        # ---- 多租户：为已有表补 tenant_id，并按用户回填个人租户 ----
        self._migrate_tenants(connection)

    def _migrate_tenants(self, connection: Any) -> None:
        """多租户迁移。

        1. 给业务表补 ``tenant_id`` 列；
        2. 为每个还没有租户的用户建一个「个人空间」租户（owner）；
        3. 按 ``user_id`` 回填历史记录的 ``tenant_id``。

        历史遗留记录（``user_id IS NULL``）保持 ``tenant_id`` 为空，
        不臆测归属——它们仍由管理员显式认领。
        """
        tables = ("import_batches", "tasks", "task_steps")
        for table in tables:
            if table not in set(self._tables(connection)):
                continue
            cols = set(self._columns(connection, table))
            if "tenant_id" not in cols:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT")
            if "created_at" in cols:
                connection.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant "
                    f"ON {table}(tenant_id, created_at DESC)"
                )
            else:
                connection.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant ON {table}(tenant_id)"
                )

        users = connection.execute(
            "SELECT u.user_id, u.username FROM users u "
            "WHERE NOT EXISTS (SELECT 1 FROM tenant_members m WHERE m.user_id = u.user_id)"
        ).fetchall()
        for row in users:
            tenant_id = uuid.uuid4().hex
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "INSERT INTO tenants (tenant_id, name, slug, created_at) VALUES (?, ?, ?, ?)",
                (tenant_id, f"{row['username']} 的个人空间", f"personal-{row['user_id'][:12]}", now),
            )
            connection.execute(
                "INSERT INTO tenant_members (tenant_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
                (tenant_id, row["user_id"], now),
            )
            # 该用户的全部历史数据归入其个人租户
            for table in tables:
                connection.execute(
                    f"UPDATE {table} SET tenant_id = ? WHERE user_id = ? AND tenant_id IS NULL",
                    (tenant_id, row["user_id"]),
                )

    # -- 租户与成员 ---------------------------------------------------------
    def create_tenant(self, tenant_id: str, name: str, slug: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO tenants (tenant_id, name, slug, created_at) VALUES (?, ?, ?, ?)",
                (tenant_id, name, slug, datetime.now(timezone.utc).isoformat()),
            )

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
        return dict(row) if row else None

    def find_tenant_by_slug(self, slug: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tenants WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None

    def add_member(self, tenant_id: str, user_id: str, role: str = "owner") -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO tenant_members (tenant_id, user_id, role, joined_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(tenant_id, user_id) DO UPDATE SET role=excluded.role, joined_at=excluded.joined_at",
                (tenant_id, user_id, role, datetime.now(timezone.utc).isoformat()),
            )

    def get_membership(self, user_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        with self.connect() as connection:
            if tenant_id is None:
                row = connection.execute(
                    "SELECT * FROM tenant_members WHERE user_id = ? ORDER BY joined_at LIMIT 1",
                    (user_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM tenant_members WHERE user_id = ? AND tenant_id = ?",
                    (user_id, tenant_id),
                ).fetchone()
        return dict(row) if row else None

    def list_memberships(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT m.tenant_id, m.role, m.joined_at, t.name, t.slug "
                "FROM tenant_members m JOIN tenants t ON t.tenant_id = m.tenant_id "
                "WHERE m.user_id = ? ORDER BY m.joined_at",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_tenant_members(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT m.user_id, m.role, m.joined_at, u.username, u.display_name "
                "FROM tenant_members m JOIN users u ON u.user_id = m.user_id "
                "WHERE m.tenant_id = ? ORDER BY m.joined_at",
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def tenant_stats(self, tenant_id: str) -> dict[str, int]:
        with self.connect() as connection:
            def count(table: str) -> int:
                row = connection.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE tenant_id = ?", (tenant_id,)
                ).fetchone()
                return int(row["n"] if row else 0)

            return {
                "reports": count("competitor_reports"),
                "listings": count("listing_drafts"),
                "imports": count("import_batches"),
                "tasks": count("tasks"),
            }

    # -- 分析报告 ---------------------------------------------------------
    def save_report(
        self,
        report: dict[str, Any],
        user_id: str | None = None,
        tenant_id: str | None = None,
        *,
        task_id: str | None = None,
    ) -> None:
        """写入报告（新表 ``competitor_reports``）。"""
        provenance = report.get("data_provenance") or {}
        price = report.get("price_analysis") or {}
        summary = {
            "competitor_count": provenance.get("competitor_count"),
            "review_sample_count": provenance.get("review_sample_count"),
            "price_min": price.get("min_price"),
            "price_max": price.get("max_price"),
            "price_median": price.get("median_price"),
        }
        payload = json.dumps(report, ensure_ascii=False)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO competitor_reports
                   (report_id, tenant_id, user_id, task_id, product_name, platform, marketplace,
                    is_demo, data_source, summary, payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(report_id) DO UPDATE SET
                     tenant_id=excluded.tenant_id, user_id=excluded.user_id,
                     task_id=excluded.task_id, product_name=excluded.product_name,
                     platform=excluded.platform, marketplace=excluded.marketplace,
                     is_demo=excluded.is_demo, data_source=excluded.data_source,
                     summary=excluded.summary, payload=excluded.payload""",
                (
                    report["report_id"],
                    tenant_id,
                    user_id,
                    task_id,
                    report.get("product_name", ""),
                    str(report.get("platform", "")),
                    report.get("marketplace", ""),
                    1 if provenance.get("is_demo") else 0,
                    provenance.get("data_source", ""),
                    json.dumps(summary, ensure_ascii=False),
                    payload,
                    created_at,
                ),
            )

    def get_report(
        self,
        report_id: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        query = "SELECT payload FROM competitor_reports WHERE report_id = ?"
        params: list[Any] = [report_id]
        # 租户优先：同一租户内的成员共享数据；未提供租户时才退回按用户过滤
        if tenant_id is not None:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        elif user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        with self.connect() as connection:
            row = connection.execute(query, params).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_reports(
        self,
        limit: int = 50,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """SELECT report_id, product_name, platform, marketplace, data_source, is_demo, created_at
                   FROM competitor_reports"""
        params: list[Any] = []
        if tenant_id is not None:
            query += " WHERE tenant_id = ?"
            params.append(tenant_id)
        elif user_id is not None:
            query += " WHERE user_id = ?"
            params.append(user_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def report_summary(self, report_id: str, tenant_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT summary FROM competitor_reports WHERE report_id = ? AND tenant_id = ?",
                (report_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["summary"] or "{}")
        except ValueError:
            return {}

    # -- Listing ------------------------------------------------------------
    def save_listing(
        self,
        listing: dict[str, Any],
        user_id: str | None = None,
        tenant_id: str | None = None,
        *,
        task_id: str | None = None,
        version: int | None = None,
        parent_listing_id: str | None = None,
    ) -> None:
        provenance = listing.get("data_provenance") or {}
        payload = json.dumps(listing, ensure_ascii=False)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self.connect() as connection:
            existing = connection.execute(
                "SELECT version, parent_listing_id FROM listing_drafts WHERE listing_id = ?",
                (listing["listing_id"],),
            ).fetchone()
            resolved_version = (
                version
                if version is not None
                else (int(existing["version"]) if existing else 1)
            )
            resolved_parent = (
                parent_listing_id
                if parent_listing_id is not None
                else (existing["parent_listing_id"] if existing else None)
            )
            connection.execute(
                """INSERT INTO listing_drafts
                   (listing_id, tenant_id, user_id, report_id, task_id, version, parent_listing_id,
                    product_name, platform, marketplace, language, title, bullets, description,
                    search_terms, quality_check, fact_ledger, pending_confirmations, is_demo,
                    engine, payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(listing_id) DO UPDATE SET
                     tenant_id=excluded.tenant_id, user_id=excluded.user_id,
                     report_id=excluded.report_id, task_id=excluded.task_id,
                     parent_listing_id=excluded.parent_listing_id,
                     product_name=excluded.product_name, platform=excluded.platform,
                     marketplace=excluded.marketplace, language=excluded.language,
                     title=excluded.title, bullets=excluded.bullets,
                     description=excluded.description, search_terms=excluded.search_terms,
                     quality_check=excluded.quality_check, fact_ledger=excluded.fact_ledger,
                     pending_confirmations=excluded.pending_confirmations,
                     is_demo=excluded.is_demo, engine=excluded.engine,
                     payload=excluded.payload""",
                (
                    listing["listing_id"],
                    tenant_id,
                    user_id,
                    listing.get("analysis_report_id"),
                    task_id,
                    resolved_version,
                    resolved_parent,
                    listing.get("product_name", ""),
                    str(listing.get("platform", "")),
                    listing.get("marketplace", ""),
                    listing.get("language", ""),
                    listing.get("title", ""),
                    json.dumps(listing.get("bullets") or [], ensure_ascii=False),
                    listing.get("description", ""),
                    listing.get("search_terms", ""),
                    json.dumps(listing.get("quality_check") or {}, ensure_ascii=False),
                    json.dumps(listing.get("fact_ledger") or [], ensure_ascii=False),
                    json.dumps(listing.get("pending_confirmations") or [], ensure_ascii=False),
                    1 if provenance.get("is_demo") else 0,
                    listing.get("engine") or "",
                    payload,
                    created_at,
                ),
            )

    def get_listing(
        self,
        listing_id: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        query = "SELECT payload FROM listing_drafts WHERE listing_id = ?"
        params: list[Any] = [listing_id]
        if tenant_id is not None:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        elif user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        with self.connect() as connection:
            row = connection.execute(query, params).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_listings(
        self,
        limit: int = 50,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """SELECT listing_id, product_name, platform, marketplace, language, report_id,
                          is_demo, created_at, version, parent_listing_id
                   FROM listing_drafts"""
        params: list[Any] = []
        if tenant_id is not None:
            query += " WHERE tenant_id = ?"
            params.append(tenant_id)
        elif user_id is not None:
            query += " WHERE user_id = ?"
            params.append(user_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["is_demo"] = bool(item.get("is_demo"))
            items.append(item)
        return items

    def get_listing_meta(
        self, listing_id: str, tenant_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT listing_id, version, parent_listing_id, task_id, created_at "
                "FROM listing_drafts WHERE listing_id = ? AND tenant_id = ?",
                (listing_id, tenant_id),
            ).fetchone()
        return dict(row) if row else None

    def list_listing_versions(
        self, listing_id: str, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        """返回同一谱系的全部版本（按版本号升序）。

        先沿 ``parent_listing_id`` 回溯到根，再从根沿子节点向下走；
        最多 100 层，避免脏数据死循环。分支时取版本号最小的子节点。
        """
        columns = "listing_id, version, parent_listing_id, title, created_at"

        def fetch(draft_id: str) -> dict[str, Any] | None:
            sql = f"SELECT {columns} FROM listing_drafts WHERE listing_id = ?"
            params: list[Any] = [draft_id]
            if tenant_id is not None:
                sql += " AND tenant_id = ?"
                params.append(tenant_id)
            with self.connect() as connection:
                row = connection.execute(sql, params).fetchone()
            return dict(row) if row else None

        target = fetch(listing_id)
        if target is None:
            return []

        chain: list[dict[str, Any]] = [target]
        current = target
        for _ in range(100):
            parent_id = current.get("parent_listing_id")
            if not parent_id:
                break
            parent = fetch(str(parent_id))
            if parent is None:
                break
            chain.append(parent)
            current = parent
        chain.reverse()

        # 从根向下的主干：取版本号最小的直接子节点
        versioned = [chain[0]]
        cursor = chain[0]["listing_id"]
        for _ in range(100):
            with self.connect() as connection:
                sql = (
                    f"SELECT {columns} FROM listing_drafts WHERE parent_listing_id = ?"
                )
                params: list[Any] = [cursor]
                if tenant_id is not None:
                    sql += " AND tenant_id = ?"
                    params.append(tenant_id)
                sql += " ORDER BY version, created_at LIMIT 1"
                row = connection.execute(sql, params).fetchone()
            if row is None:
                break
            child = dict(row)
            versioned.append(child)
            cursor = child["listing_id"]
        return versioned

    def update_listing_quality(
        self, listing_id: str, quality_check: dict[str, Any]
    ) -> None:
        payload_row = self.get_listing(listing_id)
        if payload_row is None:
            return
        payload_row["quality_check"] = quality_check
        payload = json.dumps(payload_row, ensure_ascii=False)
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE listing_drafts SET quality_check = ?, payload = ? WHERE listing_id = ?",
                (
                    json.dumps(quality_check, ensure_ascii=False),
                    payload,
                    listing_id,
                ),
            )

    # -- 导入批次 -----------------------------------------------------------
    def save_import_batch(
        self,
        batch: dict[str, Any],
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO import_batches
                   (batch_id, filename, source_format, total_rows, valid_rows, errors, payload,
                    created_at, user_id, tenant_id, data_source_id, field_mapping)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(batch_id) DO UPDATE SET
                     filename=excluded.filename, source_format=excluded.source_format,
                     total_rows=excluded.total_rows, valid_rows=excluded.valid_rows,
                     errors=excluded.errors, payload=excluded.payload,
                     user_id=excluded.user_id, tenant_id=excluded.tenant_id,
                     data_source_id=excluded.data_source_id,
                     field_mapping=excluded.field_mapping""",
                (
                    batch["batch_id"],
                    batch.get("filename", ""),
                    batch.get("source_format", ""),
                    int(batch.get("total_rows", 0)),
                    int(batch.get("valid_rows", 0)),
                    json.dumps(batch.get("errors", []), ensure_ascii=False),
                    json.dumps(batch, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                    user_id,
                    tenant_id,
                    batch.get("data_source_id"),
                    json.dumps(batch.get("field_mapping") or {}, ensure_ascii=False),
                ),
            )

    # -- 用户 ---------------------------------------------------------------
    def create_user(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        display_name: str | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO users (user_id, username, display_name, password_hash, is_admin, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    username.strip().lower(),
                    display_name,
                    password_hash,
                    1 if is_admin else 0,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return {
            "user_id": user_id,
            "username": username.strip().lower(),
            "display_name": display_name,
            "is_admin": is_admin,
        }

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?", ((username or "").strip().lower(),)
            ).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def count_users(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"] if row else 0)

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT user_id, username, display_name, is_admin, created_at, last_login_at FROM users ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def touch_last_login(self, user_id: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE users SET last_login_at = ? WHERE user_id = ?",
                (datetime.now(timezone.utc).isoformat(), user_id),
            )

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE user_id = ?", (password_hash, user_id)
            )

    # -- 临时账号（一键体验） ----------------------------------------------
    def mark_guest(self, user_id: str, expires_at: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE users SET is_guest = 1, guest_expires_at = ? WHERE user_id = ?",
                (expires_at, user_id),
            )

    def list_expired_guests(self, now_iso: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT user_id, username, guest_expires_at FROM users "
                "WHERE is_guest = 1 AND (guest_expires_at IS NULL OR guest_expires_at < ?)",
                (now_iso,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_user_cascade(self, user_id: str) -> None:
        """删除临时账号及其数据。外键不一定带 CASCADE，这里显式逐表清理。"""
        with self._lock, self.connect() as connection:
            memberships = connection.execute(
                "SELECT tenant_id FROM tenant_members WHERE user_id = ?", (user_id,)
            ).fetchall()
            tenant_ids = [row["tenant_id"] for row in memberships]

            for tenant_id in tenant_ids:
                connection.execute(
                    "DELETE FROM task_steps WHERE task_id IN "
                    "(SELECT task_id FROM tasks WHERE tenant_id = ?)",
                    (tenant_id,),
                )
                for table in (
                    "tasks",
                    "messages",
                    "conversations",
                    "competitor_reports",
                    "listing_drafts",
                    "data_sources",
                    "import_batches",
                    "audit_logs",
                    "approval_requests",
                    "tenant_invites",
                    "store_credentials",
                    "store_connections",
                ):
                    connection.execute(
                        f"DELETE FROM {table} WHERE tenant_id = ?", (tenant_id,)
                    )
                connection.execute(
                    "DELETE FROM tenant_members WHERE tenant_id = ?", (tenant_id,)
                )
                connection.execute("DELETE FROM tenants WHERE tenant_id = ?", (tenant_id,))

            connection.execute(
                "DELETE FROM user_provider_configs WHERE user_id = ?", (user_id,)
            )
            connection.execute(
                "DELETE FROM user_model_settings WHERE user_id = ?", (user_id,)
            )
            connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
            connection.execute(
                "DELETE FROM tenant_members WHERE user_id = ?", (user_id,)
            )
            connection.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

    # -- 会话 ---------------------------------------------------------------
    def create_session(self, token_hash: str, user_id: str, expires_at: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (token_hash, user_id, now, expires_at, now),
            )

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        return dict(row) if row else None

    def touch_session(self, token_hash: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
                (datetime.now(timezone.utc).isoformat(), token_hash),
            )

    def delete_session(self, token_hash: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))

    def delete_user_sessions(self, user_id: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))

    def purge_expired_sessions(self) -> int:
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at < ?",
                (datetime.now(timezone.utc).isoformat(),),
            )
            return cursor.rowcount or 0

    # -- 每用户模型配置 ------------------------------------------------------
    def get_model_settings(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_model_settings WHERE user_id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def save_model_settings(self, user_id: str, values: dict[str, Any]) -> None:
        fields = (
            "provider",
            "model",
            "base_url",
            "api_key_encrypted",
            "temperature",
            "max_tokens",
            "timeout",
            "max_retries",
            "thinking",
            "reasoning_effort",
        )
        payload = {name: values.get(name) for name in fields}
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO user_model_settings
                   (user_id, provider, model, base_url, api_key_encrypted, temperature,
                    max_tokens, timeout, max_retries, thinking, reasoning_effort, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     provider=excluded.provider,
                     model=excluded.model,
                     base_url=excluded.base_url,
                     api_key_encrypted=excluded.api_key_encrypted,
                     temperature=excluded.temperature,
                     max_tokens=excluded.max_tokens,
                     timeout=excluded.timeout,
                     max_retries=excluded.max_retries,
                     thinking=excluded.thinking,
                     reasoning_effort=excluded.reasoning_effort,
                     updated_at=excluded.updated_at""",
                (
                    user_id,
                    payload["provider"],
                    payload["model"],
                    payload["base_url"],
                    payload["api_key_encrypted"],
                    payload["temperature"],
                    payload["max_tokens"],
                    payload["timeout"],
                    payload["max_retries"],
                    1 if payload["thinking"] else 0,
                    payload["reasoning_effort"],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def delete_model_settings(self, user_id: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM user_model_settings WHERE user_id = ?", (user_id,))

    # -- 多厂商 Provider 配置（每用户可存多套） ----------------------------
    def list_provider_configs(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM user_provider_configs WHERE user_id = ? "
                "ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_provider_config(
        self, user_id: str, config_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_provider_configs WHERE user_id = ? AND config_id = ?",
                (user_id, config_id),
            ).fetchone()
        return dict(row) if row else None

    def find_provider_config(
        self, user_id: str, provider: str, label: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_provider_configs "
                "WHERE user_id = ? AND provider = ? AND label = ?",
                (user_id, provider, label),
            ).fetchone()
        return dict(row) if row else None

    def save_provider_config(self, record: dict[str, Any]) -> None:
        """按 (user_id, provider, label) 幂等写入，config_id 由调用方生成。"""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO user_provider_configs
                   (config_id, user_id, provider, label, base_url, model,
                    api_key_encrypted, enabled, last_tested_at, last_test_ok,
                    last_test_detail, task_overrides, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, provider, label) DO UPDATE SET
                     base_url = excluded.base_url,
                     model = excluded.model,
                     api_key_encrypted = COALESCE(
                        excluded.api_key_encrypted,
                        user_provider_configs.api_key_encrypted
                     ),
                     enabled = excluded.enabled,
                     last_tested_at = excluded.last_tested_at,
                     last_test_ok = excluded.last_test_ok,
                     last_test_detail = excluded.last_test_detail,
                     task_overrides = excluded.task_overrides,
                     updated_at = excluded.updated_at""",
                (
                    record["config_id"],
                    record["user_id"],
                    record["provider"],
                    record["label"],
                    record.get("base_url") or "",
                    record.get("model") or "",
                    record.get("api_key_encrypted"),
                    1 if record.get("enabled", True) else 0,
                    record.get("last_tested_at"),
                    None if record.get("last_test_ok") is None
                    else (1 if record["last_test_ok"] else 0),
                    record.get("last_test_detail"),
                    record.get("task_overrides") or "{}",
                    now,
                    now,
                ),
            )

    def delete_provider_config(self, user_id: str, config_id: str) -> bool:
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM user_provider_configs WHERE user_id = ? AND config_id = ?",
                (user_id, config_id),
            )
            return bool(cursor.rowcount)

    def list_all_provider_configs(self) -> list[dict[str, Any]]:
        """全量列表（仅供管理员/迁移脚本使用，绝不返回给普通接口）。"""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM user_provider_configs ORDER BY created_at ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_active_provider_config(self, user_id: str, config_id: str | None) -> None:
        """把某套配置设为当前使用；None 表示取消激活。"""
        with self._lock, self.connect() as connection:
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """INSERT INTO user_model_settings
                   (user_id, provider, model, base_url, temperature, thinking,
                    reasoning_effort, active_config_id, updated_at)
                   VALUES (?, 'rule', '', '', NULL, 0, '', ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     active_config_id = excluded.active_config_id,
                     updated_at = excluded.updated_at""",
                (user_id, config_id, now),
            )

    # -- 限流计数 ----------------------------------------------------------
    def bump_rate_limit(self, bucket_key: str, window_start: str) -> int:
        """原子自增窗口计数，返回自增后的值。"""
        with self._lock, self.connect() as connection:
            row = connection.execute(
                """INSERT INTO rate_limit_counters (bucket_key, window_start, count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(bucket_key) DO UPDATE SET
                     count = CASE
                       WHEN rate_limit_counters.window_start = excluded.window_start
                       THEN rate_limit_counters.count + 1
                       ELSE 1
                     END,
                     window_start = excluded.window_start
                   RETURNING count""",
                (bucket_key, window_start),
            ).fetchone()
        return int(row["count"]) if row else 1

    def purge_rate_limit_before(self, window_start: str) -> int:
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM rate_limit_counters WHERE window_start < ?", (window_start,)
            )
            return cursor.rowcount or 0

    def list_encrypted_settings(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT user_id, api_key_encrypted FROM user_model_settings WHERE api_key_encrypted IS NOT NULL"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_encrypted_setting(self, user_id: str, encrypted: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE user_model_settings SET api_key_encrypted = ?, updated_at = ? WHERE user_id = ?",
                (encrypted, datetime.now(timezone.utc).isoformat(), user_id),
            )

    # -- 遗留数据 -----------------------------------------------------------
    def count_legacy_records(self) -> dict[str, int]:
        with self.connect() as connection:
            reports = connection.execute(
                "SELECT COUNT(*) AS n FROM competitor_reports WHERE user_id IS NULL"
            ).fetchone()
            listings = connection.execute(
                "SELECT COUNT(*) AS n FROM listing_drafts WHERE user_id IS NULL"
            ).fetchone()
        return {"reports": int(reports["n"]), "listings": int(listings["n"])}

    def claim_legacy_records(self, user_id: str, tenant_id: str | None = None) -> dict[str, int]:
        """把启用账号前的遗留记录认领给指定用户（显式操作，不自动分配）。

        同时写入 ``tenant_id``，否则多租户过滤后这些记录仍然查不到。
        """
        with self._lock, self.connect() as connection:
            r1 = connection.execute(
                "UPDATE competitor_reports SET user_id = ?, tenant_id = ? WHERE user_id IS NULL",
                (user_id, tenant_id),
            ).rowcount
            r2 = connection.execute(
                "UPDATE listing_drafts SET user_id = ?, tenant_id = ? WHERE user_id IS NULL",
                (user_id, tenant_id),
            ).rowcount
        return {"reports": r1 or 0, "listings": r2 or 0}

    # -- 任务与步骤 ---------------------------------------------------------
    _TASK_COLUMNS = (
        "task_id",
        "user_id",
        "origin",
        "type",
        "title",
        "status",
        "input",
        "output",
        "error_code",
        "error_message",
        "result_ref",
        "retry_of",
        "trace_id",
        "created_at",
        "started_at",
        "finished_at",
        "tenant_id",
        "conversation_id",
        "degraded",
    )

    def create_task(self, task: dict[str, Any]) -> None:
        payload = {name: task.get(name) for name in self._TASK_COLUMNS}
        payload["input"] = json.dumps(payload.get("input") or {}, ensure_ascii=False)
        if payload.get("output") is not None:
            payload["output"] = json.dumps(payload["output"], ensure_ascii=False)
        if payload.get("degraded") is None:
            payload["degraded"] = 0
        placeholders = ", ".join("?" for _ in self._TASK_COLUMNS)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO tasks ({', '.join(self._TASK_COLUMNS)}) VALUES ({placeholders})",
                tuple(payload[name] for name in self._TASK_COLUMNS),
            )

    def update_task(self, task_id: str, **fields: Any) -> None:
        allowed = {
            "status", "output", "error_code", "error_message", "result_ref",
            "started_at", "finished_at", "conversation_id", "degraded",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        if "output" in updates and updates["output"] is not None:
            updates["output"] = json.dumps(updates["output"], ensure_ascii=False)
        assignments = ", ".join(f"{name} = ?" for name in updates)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"UPDATE tasks SET {assignments} WHERE task_id = ?",
                (*updates.values(), task_id),
            )

    @staticmethod
    def _task_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        for key in ("input", "output"):
            raw = item.get(key)
            if isinstance(raw, str) and raw:
                try:
                    item[key] = json.loads(raw)
                except ValueError:
                    item[key] = {}
            elif raw is None:
                item[key] = {} if key == "input" else None
        return item

    def get_task(
        self, task_id: str, user_id: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        sql = "SELECT * FROM tasks WHERE task_id = ?"
        params: list[Any] = [task_id]
        if tenant_id is not None:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        else:
            sql += " AND user_id = ?"
            params.append(user_id)
        with self.connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return self._task_row(row) if row else None

    def get_task_by_id(self, task_id: str) -> dict[str, Any] | None:
        """内部/Worker 用：不按用户过滤，调用方必须先校验归属。"""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return self._task_row(row) if row else None

    def list_tasks(
        self,
        user_id: str,
        *,
        status: str | None = None,
        query: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if tenant_id is not None:
            sql = "SELECT * FROM tasks WHERE tenant_id = ?"
            params: list[Any] = [tenant_id]
        else:
            sql = "SELECT * FROM tasks WHERE user_id = ?"
            params: list[Any] = [user_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        if query:
            sql += " AND (title LIKE ? OR task_id LIKE ? OR type LIKE ?)"
            like = f"%{query}%"
            params.extend([like, like, like])
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._task_row(row) for row in rows]

    def add_task_step(self, step: dict[str, Any]) -> None:
        fields = (
            "step_id", "task_id", "user_id", "tenant_id", "seq", "name", "status",
            "detail", "started_at", "finished_at", "duration_ms",
        )
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO task_steps ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                tuple(step.get(name) for name in fields),
            )

    def update_task_step(self, step_id: str, **fields: Any) -> None:
        allowed = {"status", "detail", "started_at", "finished_at", "duration_ms"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{name} = ?" for name in updates)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"UPDATE task_steps SET {assignments} WHERE step_id = ?",
                (*updates.values(), step_id),
            )

    def list_task_steps(
        self, task_id: str, user_id: str, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM task_steps WHERE task_id = ?"
        params: list[Any] = [task_id]
        if tenant_id is not None:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        else:
            sql += " AND user_id = ?"
            params.append(user_id)
        sql += " ORDER BY seq"
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def task_stats(self, user_id: str, tenant_id: str | None = None) -> dict[str, int]:
        if tenant_id is not None:
            sql = "SELECT status, COUNT(*) AS n FROM tasks WHERE tenant_id = ?"
            params: list[Any] = [tenant_id]
        else:
            sql = "SELECT status, COUNT(*) AS n FROM tasks WHERE user_id = ?"
            params: list[Any] = [user_id]
        sql += " GROUP BY status"
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return {row["status"]: int(row["n"]) for row in rows}

    def daily_task_counts(
        self, user_id: str, *, days: int = 14, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        """近 N 天每日新建任务数（缺失日期补 0，供趋势图直接使用）。"""
        from datetime import timedelta

        span = max(1, min(days, 60))
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=span - 1)
        if tenant_id is not None:
            sql = (
                "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n FROM tasks "
                "WHERE tenant_id = ? AND substr(created_at, 1, 10) >= ? GROUP BY day"
            )
            params: list[Any] = [tenant_id, start.isoformat()]
        else:
            sql = (
                "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n FROM tasks "
                "WHERE user_id = ? AND substr(created_at, 1, 10) >= ? GROUP BY day"
            )
            params = [user_id, start.isoformat()]
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        counts = {row["day"]: int(row["n"]) for row in rows}
        series: list[dict[str, Any]] = []
        for offset in range(span):
            day = (start + timedelta(days=offset)).isoformat()
            series.append({"date": day, "count": counts.get(day, 0)})
        return series

    def count_records(self, user_id: str, tenant_id: str | None = None) -> dict[str, int]:
        """报告 / Listing / 店铺 / 待审批的计数（工作台 KPI 用）。

        部分表没有 ``user_id`` 列（店铺、审批只有 ``tenant_id`` /
        ``requested_by``），因此按表分别指定回退列，避免生成非法 SQL。
        """

        def _count(table: str, user_column: str, extra: str = "") -> int:
            if tenant_id is not None:
                sql = f"SELECT COUNT(*) AS n FROM {table} WHERE tenant_id = ?{extra}"
                params: list[Any] = [tenant_id]
            else:
                sql = f"SELECT COUNT(*) AS n FROM {table} WHERE {user_column} = ?{extra}"
                params = [user_id]
            with self.connect() as connection:
                row = connection.execute(sql, params).fetchone()
            return int(row["n"]) if row else 0

        return {
            "reports": _count("competitor_reports", "user_id"),
            "listings": _count("listing_drafts", "user_id"),
            "stores": _count("store_connections", "tenant_id"),
            "approvals": _count(
                "approval_requests", "requested_by", " AND status = 'pending'"
            ),
        }

    # -- 会话与消息 ---------------------------------------------------------
    _CONVERSATION_FIELDS = (
        "conversation_id", "tenant_id", "user_id", "title", "status",
        "last_task_id", "created_at", "updated_at",
    )

    def create_conversation(self, conversation: dict[str, Any]) -> None:
        fields = self._CONVERSATION_FIELDS
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO conversations ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                tuple(conversation.get(name) for name in fields),
            )

    def get_conversation(
        self, conversation_id: str, user_id: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        """会话属于个人（同一租户成员之间也不共享聊天记录）。"""
        sql = "SELECT * FROM conversations WHERE conversation_id = ? AND user_id = ? AND status = 'active'"
        params: list[Any] = [conversation_id, user_id]
        if tenant_id is not None:
            sql += " AND tenant_id = ?"
            params.append(tenant_id)
        with self.connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return dict(row) if row else None

    def list_conversations(
        self, user_id: str, tenant_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT c.*, "
            "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.conversation_id) "
            "AS message_count FROM conversations c WHERE c.user_id = ?"
        )
        params: list[Any] = [user_id]
        if tenant_id is not None:
            sql += " AND c.tenant_id = ?"
            params.append(tenant_id)
        sql += " AND c.status = 'active' ORDER BY c.updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def update_conversation(self, conversation_id: str, **fields: Any) -> None:
        allowed = {"title", "status", "last_task_id", "updated_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if "updated_at" not in updates:
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        assignments = ", ".join(f"{name} = ?" for name in updates)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"UPDATE conversations SET {assignments} WHERE conversation_id = ?",
                (*updates.values(), conversation_id),
            )

    @staticmethod
    def _message_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        try:
            item["meta"] = json.loads(item.get("meta") or "{}")
        except ValueError:
            item["meta"] = {}
        return item

    def add_message(self, message: dict[str, Any]) -> None:
        fields = (
            "message_id", "conversation_id", "tenant_id", "role", "content",
            "content_type", "task_id", "meta", "created_at",
        )
        payload = {name: message.get(name) for name in fields}
        payload["meta"] = json.dumps(payload.get("meta") or {}, ensure_ascii=False)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO messages ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                tuple(payload[name] for name in fields),
            )

    def list_messages(
        self, conversation_id: str, tenant_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? AND tenant_id = ? "
                "ORDER BY created_at, message_id LIMIT ?",
                (conversation_id, tenant_id, limit),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    # -- 审计 ---------------------------------------------------------------
    def add_audit_log(self, entry: dict[str, Any]) -> None:
        fields = (
            "tenant_id", "actor_id", "action", "target_type", "target_id",
            "detail", "trace_id", "created_at",
        )
        payload = {name: entry.get(name) for name in fields}
        payload["detail"] = json.dumps(payload.get("detail") or {}, ensure_ascii=False)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO audit_logs ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                tuple(payload[name] for name in fields),
            )

    def list_audit_logs(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        action: str | None = None,
        actor_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM audit_logs WHERE tenant_id = ?"
        params: list[Any] = [tenant_id]
        if action:
            sql += " AND action = ?"
            params.append(action)
        if actor_id:
            sql += " AND actor_id = ?"
            params.append(actor_id)
        sql += " ORDER BY audit_id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["detail"] = json.loads(item.get("detail") or "{}")
            except ValueError:
                item["detail"] = {}
            items.append(item)
        return items

    # -- 审批 ---------------------------------------------------------------
    _APPROVAL_FIELDS = (
        "approval_id", "tenant_id", "task_id", "kind", "payload", "status",
        "requested_by", "decided_by", "decided_at", "note", "created_at",
    )

    def create_approval(self, approval: dict[str, Any]) -> None:
        fields = self._APPROVAL_FIELDS
        payload = {name: approval.get(name) for name in fields}
        payload["payload"] = json.dumps(payload.get("payload") or {}, ensure_ascii=False)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO approval_requests ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                tuple(payload[name] for name in fields),
            )

    @staticmethod
    def _approval_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.get("payload") or "{}")
        except ValueError:
            item["payload"] = {}
        return item

    def get_approval(self, approval_id: str, tenant_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM approval_requests WHERE approval_id = ? AND tenant_id = ?",
                (approval_id, tenant_id),
            ).fetchone()
        return self._approval_row(row) if row else None

    def list_approvals(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM approval_requests WHERE tenant_id = ?"
        params: list[Any] = [tenant_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._approval_row(row) for row in rows]

    def update_approval(
        self,
        approval_id: str,
        *,
        status: str,
        decided_by: str | None = None,
        decided_at: str | None = None,
        note: str | None = None,
    ) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE approval_requests SET status = ?, decided_by = ?, "
                "decided_at = ?, note = ? WHERE approval_id = ?",
                (status, decided_by, decided_at, note, approval_id),
            )

    # -- 租户邀请 -----------------------------------------------------------
    def create_invite(self, invite: dict[str, Any]) -> None:
        fields = (
            "invite_id", "tenant_id", "role", "token_hash", "created_by",
            "created_at", "expires_at", "accepted_at", "accepted_by",
        )
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO tenant_invites ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                tuple(invite.get(name) for name in fields),
            )

    def get_invite_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tenant_invites WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        return dict(row) if row else None

    def mark_invite_accepted(self, invite_id: str, user_id: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE tenant_invites SET accepted_at = ?, accepted_by = ? WHERE invite_id = ?",
                (datetime.now(timezone.utc).isoformat(), user_id, invite_id),
            )

    def list_invites(self, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """返回邀请记录，但**绝不返回 token_hash**。"""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT invite_id, tenant_id, role, created_by, created_at, expires_at, "
                "accepted_at, accepted_by FROM tenant_invites "
                "WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # -- 数据资产（导入批次） ----------------------------------------------
    def get_import_batch(
        self, batch_id: str, tenant_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM import_batches WHERE batch_id = ? AND tenant_id = ?",
                (batch_id, tenant_id),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    # -- 数据源（阶段 E6） --------------------------------------------------
    _DATA_SOURCE_FIELDS = (
        "data_source_id", "tenant_id", "user_id", "kind", "name", "format",
        "storage_key", "row_count", "is_demo", "status", "field_mapping",
        "validation", "created_at",
    )

    @staticmethod
    def _data_source_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        for key in ("field_mapping", "validation"):
            raw = item.get(key)
            if isinstance(raw, str) and raw:
                try:
                    item[key] = json.loads(raw)
                except ValueError:
                    item[key] = {}
            elif raw is None:
                item[key] = {}
        item["is_demo"] = bool(item.get("is_demo"))
        return item

    def create_data_source(self, record: dict[str, Any]) -> None:
        fields = self._DATA_SOURCE_FIELDS
        payload = {name: record.get(name) for name in fields}
        # PostgreSQL 的 INTEGER 列不接受 Python bool；统一转 0/1
        payload["is_demo"] = 1 if payload.get("is_demo") else 0
        payload["field_mapping"] = json.dumps(
            payload.get("field_mapping") or {}, ensure_ascii=False
        )
        payload["validation"] = json.dumps(
            payload.get("validation") or {}, ensure_ascii=False
        )
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO data_sources ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                tuple(payload[name] for name in fields),
            )

    def get_data_source(
        self, data_source_id: str, tenant_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM data_sources WHERE data_source_id = ? AND tenant_id = ?",
                (data_source_id, tenant_id),
            ).fetchone()
        return self._data_source_row(row) if row else None

    def update_data_source(self, data_source_id: str, **fields: Any) -> None:
        allowed = {"status", "row_count", "validation", "field_mapping"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        if "validation" in updates:
            updates["validation"] = json.dumps(updates["validation"] or {}, ensure_ascii=False)
        if "field_mapping" in updates:
            updates["field_mapping"] = json.dumps(
                updates["field_mapping"] or {}, ensure_ascii=False
            )
        assignments = ", ".join(f"{name} = ?" for name in updates)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"UPDATE data_sources SET {assignments} WHERE data_source_id = ?",
                (*updates.values(), data_source_id),
            )

    def list_data_sources(
        self, tenant_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM data_sources WHERE tenant_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        return [self._data_source_row(row) for row in rows]

    # -- 店铺连接（阶段 F） -------------------------------------------------
    _STORE_FIELDS = (
        "connection_id", "tenant_id", "platform", "marketplace", "shop_name",
        "mode", "status", "scopes", "credential_ref", "last_sync_at",
        "last_sync_status", "last_sync_error", "last_sync_summary", "created_at",
    )

    @staticmethod
    def _store_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        for key in ("scopes", "last_sync_summary"):
            raw = item.get(key)
            if isinstance(raw, str) and raw:
                try:
                    item[key] = json.loads(raw)
                except ValueError:
                    item[key] = [] if key == "scopes" else {}
            elif raw is None:
                item[key] = [] if key == "scopes" else {}
        return item

    def create_store_connection(self, record: dict[str, Any]) -> None:
        fields = self._STORE_FIELDS
        payload = {name: record.get(name) for name in fields}
        payload["scopes"] = json.dumps(payload.get("scopes") or [], ensure_ascii=False)
        payload["last_sync_summary"] = json.dumps(
            payload.get("last_sync_summary") or {}, ensure_ascii=False
        )
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO store_connections ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                tuple(payload[name] for name in fields),
            )

    def get_store_connection(
        self, connection_id: str, tenant_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM store_connections WHERE connection_id = ? AND tenant_id = ?",
                (connection_id, tenant_id),
            ).fetchone()
        return self._store_row(row) if row else None

    def list_store_connections(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM store_connections WHERE tenant_id = ? ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
        return [self._store_row(row) for row in rows]

    def update_store_connection(self, connection_id: str, **fields: Any) -> None:
        allowed = {
            "status", "scopes", "credential_ref", "last_sync_at",
            "last_sync_status", "last_sync_error", "last_sync_summary",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        if "scopes" in updates:
            updates["scopes"] = json.dumps(updates["scopes"] or [], ensure_ascii=False)
        if "last_sync_summary" in updates:
            updates["last_sync_summary"] = json.dumps(
                updates["last_sync_summary"] or {}, ensure_ascii=False
            )
        assignments = ", ".join(f"{name} = ?" for name in updates)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"UPDATE store_connections SET {assignments} WHERE connection_id = ?",
                (*updates.values(), connection_id),
            )

    def delete_store_connection(self, connection_id: str, tenant_id: str) -> bool:
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM store_connections WHERE connection_id = ? AND tenant_id = ?",
                (connection_id, tenant_id),
            )
        return bool(cursor.rowcount)

    def save_store_credential(
        self, credential_ref: str, tenant_id: str, ciphertext: str
    ) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO store_credentials (credential_ref, tenant_id, ciphertext, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(credential_ref) DO UPDATE SET ciphertext=excluded.ciphertext",
                (
                    credential_ref,
                    tenant_id,
                    ciphertext,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_store_credential(
        self, credential_ref: str, tenant_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM store_credentials WHERE credential_ref = ? AND tenant_id = ?",
                (credential_ref, tenant_id),
            ).fetchone()
        return dict(row) if row else None


    # -- Agent / Skill / Tool 注册表 ---------------------------------------
    _AGENT_FIELDS = (
        "agent_key", "tenant_id", "name", "summary", "description",
        "input_schema", "output_schema", "skill_keys", "tool_keys",
        "version", "status", "updated_at",
    )
    _SKILL_FIELDS = (
        "skill_key", "tenant_id", "name", "summary", "input_schema",
        "output_schema", "version", "status", "updated_at",
    )
    _TOOL_FIELDS = (
        "tool_key", "tenant_id", "name", "summary", "input_schema",
        "output_schema", "version", "status", "updated_at",
    )

    def _upsert(
        self,
        table: str,
        fields: tuple[str, ...],
        payload: dict[str, Any],
        conflict: str,
    ) -> None:
        values = tuple(payload.get(name) for name in fields)
        updates = ", ".join(f"{name}=excluded.{name}" for name in fields[2:])
        with self._lock, self.connect() as connection:
            connection.execute(
                f"INSERT INTO {table} ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)}) "
                f"ON CONFLICT({conflict}) DO UPDATE SET {updates}",
                values,
            )

    def upsert_agent(self, payload: dict[str, Any]) -> None:
        self._upsert(
            "agent_definitions", self._AGENT_FIELDS, payload, "agent_key, tenant_id"
        )

    def upsert_skill(self, payload: dict[str, Any]) -> None:
        self._upsert(
            "skill_definitions", self._SKILL_FIELDS, payload, "skill_key, tenant_id"
        )

    def upsert_tool(self, payload: dict[str, Any]) -> None:
        self._upsert(
            "tool_definitions", self._TOOL_FIELDS, payload, "tool_key, tenant_id"
        )

    @staticmethod
    def _definition_row(row: Any) -> dict[str, Any]:
        item = dict(row)
        for key in ("input_schema", "output_schema"):
            try:
                item[key] = json.loads(item.get(key) or "{}")
            except ValueError:
                item[key] = {}
        for key in ("skill_keys", "tool_keys"):
            if key in item:
                try:
                    item[key] = json.loads(item.get(key) or "[]")
                except ValueError:
                    item[key] = []
        return item

    def _get_definition(
        self, table: str, key_field: str, key: str, tenant_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {key_field} = ? AND tenant_id = ?",
                (key, tenant_id),
            ).fetchone()
        return self._definition_row(row) if row else None

    def _list_definitions(
        self, table: str, key_field: str, tenant_id: str
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE tenant_id IN (?, '') ORDER BY {key_field}",
                (tenant_id,),
            ).fetchall()
        return [self._definition_row(row) for row in rows]

    def get_agent_definition(self, key: str, tenant_id: str = "") -> dict[str, Any] | None:
        return self._get_definition("agent_definitions", "agent_key", key, tenant_id)

    def list_agent_definitions(self, tenant_id: str = "") -> list[dict[str, Any]]:
        return self._list_definitions("agent_definitions", "agent_key", tenant_id)

    def get_skill_definition(self, key: str, tenant_id: str = "") -> dict[str, Any] | None:
        return self._get_definition("skill_definitions", "skill_key", key, tenant_id)

    def list_skill_definitions(self, tenant_id: str = "") -> list[dict[str, Any]]:
        return self._list_definitions("skill_definitions", "skill_key", tenant_id)

    def list_tool_definitions(self, tenant_id: str = "") -> list[dict[str, Any]]:
        return self._list_definitions("tool_definitions", "tool_key", tenant_id)


__all__ = ["Database"]
