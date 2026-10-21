r"""arq 队列联调脚本（需要本机 Redis）。

用法：

```powershell
C:\\Redis\\redis-server.exe --port 6379
.\.venv\Scripts\python.exe scripts\arq_check.py
```

它做一次真实的跨进程链路验证：
API 进程侧把任务投递到 Redis → arq worker（同进程内的独立事件循环，
模拟独立 worker 进程）执行同一个 ``run_task`` → 任务落库为 succeeded。

脚本使用 Redis 的 15 号库与临时数据库，不污染开发数据。
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="crosspilot-arq-"))
(tmp / "empty.env").write_text("", encoding="utf-8")
os.environ["CROSSPILOT_ENV_FILE"] = str(tmp / "empty.env")
os.environ["CROSSPILOT_DATA_DIR"] = str(tmp)
os.environ["CROSSPILOT_SECRET_KEY"] = "arq-check-secret-material"
os.environ["CROSSPILOT_TASK_QUEUE"] = "arq"
os.environ["CROSSPILOT_REDIS_URL"] = "redis://127.0.0.1:6379/15"

base_url = os.environ.get("CROSSPILOT_DATABASE_URL", "")
if not base_url.startswith("postgres"):
    raise SystemExit("需要 CROSSPILOT_DATABASE_URL（PostgreSQL）才能运行 arq 联调")

parsed = urlparse(base_url)
check_db = f"cp_arq_check_{int(time.time())}"
admin_url = urlunparse(parsed._replace(path="/postgres"))
temp_url = urlunparse(parsed._replace(path="/" + check_db))

import psycopg  # noqa: E402

with psycopg.connect(admin_url, autocommit=True) as admin:
    admin.execute(f'CREATE DATABASE "{check_db}"')
os.environ["CROSSPILOT_DATABASE_URL"] = temp_url

from fastapi.testclient import TestClient  # noqa: E402

from crosspilot.app import create_app  # noqa: E402
from crosspilot.config import get_settings  # noqa: E402
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST  # noqa: E402
from crosspilot.worker import run_task  # noqa: E402


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    app = create_app()

    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            json={"username": "arq_checker", "password": "password123"},
        )
        assert registered.status_code == 200, registered.text
        headers = {"Authorization": f"Bearer {registered.json()['token']}"}

        started = client.post(
            "/api/agent/runs",
            json={
                "product_name": "Arq Check Bottle",
                "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
                "with_listing": False,
                "data_source": "demo",
                "async_run": True,
            },
            headers=headers,
        )
        assert started.status_code == 200, started.text
        task_id = started.json()["task_id"]
        print(f"已投递 arq 任务: {task_id}")

        from arq.connections import RedisSettings
        from arq.worker import Worker

        def run_worker() -> None:
            # Worker 构造时会取当前线程的事件循环；必须先建好循环再构造，
            # 否则 asyncio.run 会新建循环导致 "attached to a different loop"。
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            worker = Worker(
                [run_task],
                redis_settings=RedisSettings.from_dsn(settings.redis_url),
                queue_name="crosspilot",
                burst=True,
                poll_delay=0.1,
                job_timeout=120,
            )
            try:
                loop.run_until_complete(worker.async_run())
            finally:
                loop.close()

        thread = threading.Thread(target=run_worker, daemon=True)
        thread.start()

        deadline = time.time() + 30
        status = "queued"
        detail: dict = {}
        while time.time() < deadline:
            detail = client.get(f"/api/tasks/{task_id}", headers=headers).json()
            status = detail["task"]["status"]
            if status in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.1)
        thread.join(timeout=10)

        print(f"最终状态: {status}")
        if status == "succeeded":
            print(f"报告: {detail['result']['report']['report_id']}")
            print(f"步骤: {[s['name'] for s in detail['steps']]}")
            print("arq 链路验证通过")
            _drop_check_db()
            return 0
        print(f"任务详情: {detail}")
        _drop_check_db()
        return 1


def _drop_check_db() -> None:
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{check_db}" WITH (FORCE)')
    except Exception as exc:  # noqa: BLE001 - 清理失败不影响结论
        print(f"清理临时数据库失败（可手动删除 {check_db}）：{exc}")


if __name__ == "__main__":
    raise SystemExit(main())
