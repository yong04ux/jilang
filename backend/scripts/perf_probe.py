"""首屏接口性能探针：端到端耗时 + ``X-Perf`` 分段。

用法（服务需以 ``CROSSPILOT_PROFILE=1`` 启动）：

    python -m scripts.perf_probe --base http://127.0.0.1:8011 --rounds 5

只做 GET，不写入业务数据（注册/登录除外）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from typing import Any

import httpx

FIRST_SCREEN = (
    "/api/health",
    "/api/dashboard",
    "/api/settings/providers",
    "/api/marketplace/overview?range=30d",
    "/api/providers",
    "/api/marketplace/metrics?range=30d",
)


def ensure_store(base: str, token: str) -> None:
    """市场数据接口需要一个连接；没有就建一个 Mock 连接（带 is_mock 标记）。"""
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=base, headers=headers, timeout=30) as client:
        response = client.post(
            "/api/stores",
            json={
                "platform": "amazon",
                "marketplace": "US",
                "shop_name": "perf-probe-shop",
                "mode": "mock",
            },
        )
        if response.status_code not in (200, 409):
            response.raise_for_status()


def login(base: str, username: str, password: str) -> str:
    with httpx.Client(base_url=base, timeout=30) as client:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        if response.status_code != 200:
            response = client.post(
                "/api/auth/login",
                json={"username": username, "password": password},
            )
        response.raise_for_status()
        return response.json()["token"]


def summary(values: list[float]) -> dict[str, float]:
    return {
        "median_ms": round(statistics.median(values), 1),
        "min_ms": round(min(values), 1),
        "max_ms": round(max(values), 1),
    }


def perf_of(response: httpx.Response) -> dict[str, Any]:
    raw = response.headers.get("x-perf")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def run_sequential(base: str, token: str, rounds: int) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    print(f"\n== 串行（每个接口 {rounds} 次，含 1 次预热）==")
    with httpx.Client(base_url=base, headers=headers, timeout=60) as client:
        for path in FIRST_SCREEN:
            client.get(path).raise_for_status()
            samples: list[float] = []
            last: dict[str, Any] = {}
            for _ in range(rounds):
                started = time.perf_counter()
                response = client.get(path)
                response.raise_for_status()
                samples.append((time.perf_counter() - started) * 1000)
                last = perf_of(response)
            print(f"{path:48s} {summary(samples)}")
            if last:
                print(f"  counters={last.get('counters')}")
                segs = last.get("segments") or {}
                top = sorted(segs.items(), key=lambda kv: kv[1]["total_ms"], reverse=True)
                for name, item in top[:8]:
                    print(
                        f"  - {name:28s} count={item['count']:<3d} "
                        f"total={item['total_ms']} ms"
                    )


async def first_screen_wall(base: str, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    print("\n== 并发（模拟首屏同时发起）==")
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=60) as client:
        started = time.perf_counter()
        requests = [client.get(path) for path in FIRST_SCREEN]
        responses = await asyncio.gather(*requests)
        wall = (time.perf_counter() - started) * 1000
        for path, response in zip(FIRST_SCREEN, responses):
            elapsed = response.elapsed.total_seconds() * 1000
            perf = perf_of(response)
            print(
                f"{path:48s} {elapsed:8.1f} ms  "
                f"connections={perf.get('counters', {}).get('db.connections')} "
                f"queries={perf.get('counters', {}).get('db.queries')}"
            )
        print(f"{'首屏全部完成（墙钟）':48s} {wall:8.1f} ms")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8011")
    parser.add_argument("--username", default="perf_probe")
    parser.add_argument("--password", default="perf-probe-pass")
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()

    token = login(args.base, args.username, args.password)
    ensure_store(args.base, token)
    run_sequential(args.base, token, args.rounds)
    asyncio.run(first_screen_wall(args.base, token))


if __name__ == "__main__":
    main()
