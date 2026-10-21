r"""PostgreSQL 验收脚本（阶段 F7）。

用法：

```powershell
# 先启动 PostgreSQL（示例：Docker）
docker run -d --name cp-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=crosspilot -p 55432:5432 postgres:16-alpine
.\.venv\Scripts\python.exe scripts\pg_check.py postgresql://postgres:postgres@127.0.0.1:55432/crosspilot --reset
```

脚本会清空 public schema（仅测试库！）、在 PG 上创建应用并跑一遍核心链路：
注册 → 分析 → 导出 → Listing → 版本/复检 → 导入预览/提交 → Mock 店铺同步 → 审计。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def reset_schema(url: str) -> None:
    import psycopg

    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connection.execute("CREATE SCHEMA public")


def main() -> int:
    url = (
        sys.argv[1]
        if len(sys.argv) > 1 and sys.argv[1].startswith("postgres")
        else os.environ.get("CROSSPILOT_DATABASE_URL", "")
    )
    if not url:
        print("需要传入 PostgreSQL URL 或设置 CROSSPILOT_DATABASE_URL")
        return 2
    if "--reset" in sys.argv:
        print("重置 public schema…")
        reset_schema(url)

    tmp = ROOT / "data" / "pg-check"
    tmp.mkdir(parents=True, exist_ok=True)
    env_file = tmp / "empty.env"
    env_file.write_text("", encoding="utf-8")
    os.environ["CROSSPILOT_ENV_FILE"] = str(env_file)
    os.environ["CROSSPILOT_DATABASE_URL"] = url
    os.environ["CROSSPILOT_PROVIDER"] = "rule"
    os.environ["CROSSPILOT_DATA_DIR"] = str(tmp)

    from fastapi.testclient import TestClient

    from crosspilot.app import create_app
    from crosspilot.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    check("db.postgres", app.state.db.path.startswith("postgresql://"))
    check(
        "migrations.all-applied",
        all(item["applied"] for item in app.state.db.migration_status()),
    )

    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            json={"username": "pg_checker", "password": "password123"},
        )
        check("auth.register", registered.status_code == 200, str(registered.status_code))
        headers = {"Authorization": f"Bearer {registered.json()['token']}"}

        demo = client.get("/api/demo/dataset").json()
        analyzed = client.post("/api/analyze", json=demo["analysis_request"], headers=headers)
        check("analyze", analyzed.status_code == 200, str(analyzed.status_code))
        report = analyzed.json()["report"]
        report_id = report["report_id"]

        exported = client.get(f"/api/reports/{report_id}/export?format=md", headers=headers)
        check("report.export", exported.status_code == 200 and "## 竞品对比" in exported.text)

        listing_resp = client.post(
            "/api/listings/generate",
            json={**demo["listing_request"], "analysis_report_id": report_id},
            headers=headers,
        )
        check("listing.generate", listing_resp.status_code == 200, listing_resp.text[:160])
        listing = listing_resp.json()["listing"]

        versioned = client.post(
            f"/api/listings/{listing['listing_id']}/versions",
            json={"title": "PostgreSQL verified title"},
            headers=headers,
        )
        check("listing.version", versioned.status_code == 200, versioned.text[:160])
        if versioned.status_code == 200:
            new_id = versioned.json()["listing"]["listing_id"]
            checked = client.post(f"/api/listings/{new_id}/check", headers=headers)
            check("listing.recheck", checked.status_code == 200)
            diffed = client.get(f"/api/listings/{new_id}/diff", headers=headers)
            check("listing.diff", diffed.status_code == 200)

        preview = client.post(
            "/api/import/preview",
            files={"file": ("pg.csv", b"name,price\nPG Bottle,12.5\n", "text/csv")},
            headers=headers,
        )
        check("import.preview", preview.status_code == 200, preview.text[:160])
        if preview.status_code == 200:
            ds_id = preview.json()["data_source_id"]
            committed = client.post(
                "/api/import/commit", json={"data_source_id": ds_id}, headers=headers
            )
            check("import.commit", committed.status_code == 200, committed.text[:160])

        store = client.post(
            "/api/stores",
            json={
                "platform": "amazon",
                "marketplace": "US",
                "shop_name": "PG Shop",
                "mode": "mock",
            },
            headers=headers,
        )
        check("store.create", store.status_code == 200, store.text[:160])
        if store.status_code == 200:
            synced = client.post(
                f"/api/stores/{store.json()['connection_id']}/sync", headers=headers
            )
            check("store.sync", synced.status_code == 200 and synced.json()["is_mock"])

        tasks = client.get("/api/tasks", headers=headers)
        check("tasks.list", tasks.status_code == 200 and len(tasks.json()["items"]) >= 1)
        audit = client.get("/api/audit", headers=headers)
        check("audit.list", audit.status_code == 200 and len(audit.json()["items"]) >= 1)
        conversations = client.get("/api/conversations", headers=headers)
        check("conversation.list", conversations.status_code == 200)
        dual = client.app.state.db.list_reports(
            limit=10, user_id=None, tenant_id=client.get("/api/tenants/current", headers=headers).json()["tenant_id"]
        )
        check("report.dual-write", any(item["report_id"] == report_id for item in dual))

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("ALL POSTGRES CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
