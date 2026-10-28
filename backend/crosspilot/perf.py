"""请求级分段耗时统计（默认关闭）。

用途：回答「一次请求的时间花在哪」，而不是凭猜测优化。

- 开关：``CROSSPILOT_PROFILE=1``（见 ``config.Settings.profile``）；
- 采集：``timed()`` 标记业务段，``Database`` 在连接与 SQL 处自动打点；
- 输出：响应头 ``Server-Timing`` 与 ``X-Perf``（JSON）；明细同时写日志。

并发正确性：``ContextVar`` 只保存一个 dict **引用**，进入线程池时
``copy_context()`` 复制的是引用，因此各线程对同一 dict 的写入都能被
中间件读到。不要给它重新赋值，否则写入会丢。
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import time
from typing import Any, Iterator

_current: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "crosspilot_perf", default=None
)

#: 事件明细上限，避免一个请求产生几千条 SQL 记录撑爆日志
MAX_EVENTS = 200


def start() -> dict[str, Any]:
    state: dict[str, Any] = {
        "segments": {},
        "counters": {},
        "events": [],
        "started": time.perf_counter(),
    }
    _current.set(state)
    return state


def stop() -> None:
    _current.set(None)


def active() -> bool:
    return _current.get() is not None


def add(segment: str, ms: float, **detail: Any) -> None:
    state = _current.get()
    if state is None:
        return
    bucket = state["segments"].setdefault(segment, {"count": 0, "total_ms": 0.0})
    bucket["count"] += 1
    bucket["total_ms"] += ms
    if detail and len(state["events"]) < MAX_EVENTS:
        event = {"segment": segment, "ms": round(ms, 3)}
        for key, value in detail.items():
            event[key] = value if isinstance(value, (int, float, bool, str)) else str(value)
        state["events"].append(event)


def incr(name: str, n: int = 1) -> None:
    state = _current.get()
    if state is None:
        return
    state["counters"][name] = state["counters"].get(name, 0) + n


@contextlib.contextmanager
def timed(segment: str, **detail: Any) -> Iterator[None]:
    if not active():
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        add(segment, (time.perf_counter() - started) * 1000, **detail)


def snapshot(state: dict[str, Any], *, total_ms: float | None = None) -> dict[str, Any]:
    segments = {
        name: {"count": item["count"], "total_ms": round(item["total_ms"], 1)}
        for name, item in state["segments"].items()
    }
    payload: dict[str, Any] = {
        "segments": segments,
        "counters": dict(state["counters"]),
    }
    if total_ms is not None:
        payload["total_ms"] = round(total_ms, 1)
    return payload


def server_timing(payload: dict[str, Any]) -> str:
    parts = []
    for name, item in payload["segments"].items():
        metric = name.replace(" ", "_")
        parts.append(f'{metric};dur={item["total_ms"]}')
    if "total_ms" in payload:
        parts.append(f'total;dur={payload["total_ms"]}')
    return ", ".join(parts)


def log_line(payload: dict[str, Any], state: dict[str, Any]) -> str:
    body = dict(payload)
    body["events"] = state["events"]
    return json.dumps(body, ensure_ascii=False)
