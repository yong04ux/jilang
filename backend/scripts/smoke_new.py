"""新接口冒烟：M2 数据源 / M4 多厂商 / M5 演示机制。

用法（从 crosspilot/ 目录）：
    python scripts/smoke_new.py
需要 CROSSPILOT_TEST_DATABASE_URL（或 CROSSPILOT_DATABASE_URL）指向一个可清空的测试库。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}{('  — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def main() -> int:
    from fastapi.testclient import TestClient

    from pg_support import database_url, reset_schema

    reset_schema(database_url())

    from crosspilot.app import create_app

    client = TestClient(create_app())

    resp = client.post("/api/auth/register", json={"username": "smoke", "password": "password123"})
    check("注册", resp.status_code == 200, str(resp.status_code))
    headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    health = client.get("/api/health").json()
    check("health.worker", "backend" in health.get("worker", {}), str(health.get("worker")))
    check("health.requires_api_key", "requires_api_key" in health)

    resp = client.get("/api/settings/providers", headers=headers)
    check("GET /api/settings/providers", resp.status_code == 200)
    body = resp.json()
    check("预置厂商 9 个", len(body.get("presets", [])) == 9, str(len(body.get("presets", []))))

    # SSRF：预置厂商域名之外必须拒绝
    resp = client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek",
            "label": "evil",
            "api_key": "sk-test-1234567890",
            "base_url": "http://169.254.169.254/v1",
            "model": "deepseek-flash",
        },
        headers=headers,
    )
    check("base_url 白名单拦截", resp.status_code == 400, str(resp.status_code))

    resp = client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek",
            "label": "默认",
            "api_key": "sk-test-1234567890",
            "model": "deepseek-flash",
        },
        headers=headers,
    )
    check("保存预置厂商配置", resp.status_code == 200, resp.text[:200])
    config_id = resp.json()["config"]["config_id"] if resp.status_code == 200 else ""
    check("接口只返回掩码", "sk-test-1234567890" not in resp.text)

    resp = client.post(f"/api/settings/providers/{config_id}/activate", json={}, headers=headers)
    check("激活配置", resp.status_code == 200, resp.text[:200])
    health = client.get("/api/health", headers=headers).json()
    check("health 反映激活配置", (health.get("configured_model") or {}).get("provider") == "deepseek",
          str(health.get("configured_model")))

    # 数据源
    resp = client.get("/api/marketplace/sources", headers=headers)
    check("GET /api/marketplace/sources", resp.status_code == 200, resp.text[:200])
    modes = {item["domain"]: item["mode"] for item in resp.json().get("items", [])}
    check("未建连时产品域为未接入", modes.get("products") == "live", str(modes))

    resp = client.post(
        "/api/stores",
        json={"platform": "amazon", "marketplace": "US", "shop_name": "Demo Store"},
        headers=headers,
    )
    check("创建 Mock 连接", resp.status_code == 200, resp.text[:200])

    resp = client.get("/api/marketplace/products", headers=headers)
    check("GET products", resp.status_code == 200, resp.text[:200])
    items = resp.json().get("items", [])
    check("商品全部 is_mock", bool(items) and all(i.get("is_mock") for i in items), f"{len(items)} 条")

    resp = client.get("/api/marketplace/orders", headers=headers)
    check("GET orders", resp.status_code == 200 and resp.json().get("is_mock") is True)

    resp = client.get("/api/marketplace/ads", headers=headers)
    check("GET ads", resp.status_code == 200 and resp.json().get("is_mock") is True)

    resp = client.get("/api/marketplace/metrics", headers=headers)
    check("GET metrics", resp.status_code == 200 and resp.json().get("is_mock") is True)

    resp = client.get("/api/marketplace/overview", headers=headers)
    check("GET overview", resp.status_code == 200)

    # 异步竞品分析
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    resp = client.post("/api/analyze?async_run=true", json=DEMO_ANALYSIS_REQUEST, headers=headers)
    check("POST /api/analyze?async_run=true", resp.status_code == 200, resp.text[:200])
    task_id = resp.json().get("task_id", "")
    check("异步返回 queued + plan", resp.json().get("status") == "queued" and resp.json().get("plan"))

    import time

    deadline = time.time() + 10
    status = ""
    while time.time() < deadline:
        detail = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        status = detail["task"]["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.1)
    check("异步分析完成", status == "succeeded", status)

    # 一键体验
    guest_client = TestClient(create_app())
    resp = guest_client.post("/api/auth/demo", json={})
    check("POST /api/auth/demo", resp.status_code == 200, resp.text[:200])
    check("临时账号带过期时间", resp.json().get("expires_in_hours") == 24)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
