"""模型调用遥测。

记录什么
========

每次底层模型调用一行：节点、Provider、模型、耗时、token 用量、**尝试次数**、成败。

**不记录 prompt / 响应正文。** 两个原因：
一是里面会有商品资料，属于租户数据；二是日志膨胀没有上限。
排查要靠"哪个节点、哪个模型、几秒、多少 token、报什么错"，这些字段够了。

**不计算金额。** 本仓库没有维护各厂商的价格表，凭空写一个单价算出来的钱
既不准、又会被当成真数据引用。token 用量是成本的可核对基础，金额留给有
真实价目表的地方算。

为什么用 ContextVar
===================

调用点在一次运行的深处（子图 → Provider → client），没有 task_id 可传。
``StepRunner`` 在每次执行节点前后开/收一个收集窗口，窗口期内发生的调用
会自动记到"当前节点"名下——不需要把 task_id 一路穿过五层构造函数。

收集窗口关闭后由 ``StepRunner`` 落库（``llm_calls`` 表）。
没有窗口时 ``record`` 是空操作，所以 ``ping`` 这类探活调用不会污染统计。
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any

#: 当前节点名（空串表示不在任何步骤里）
_NODE: ContextVar[str] = ContextVar("crosspilot_llm_node", default="")
#: 收集缓冲；``None`` 表示没开窗口
_BUFFER: ContextVar[list["CallRecord"] | None] = ContextVar(
    "crosspilot_llm_buffer", default=None
)


@dataclass(slots=True)
class CallRecord:
    """一次模型调用的可观测记录（**不含文本内容**）。"""

    node: str = ""
    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: 这一"次调用"底层实际发了几次请求（含重试）
    attempts: int = 1
    ok: bool = True
    error_code: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class _Scope:
    """一次步骤内的收集窗口。

    **可嵌套，但只有最外层能定节点名。** 规则来自用途：``trace`` 按
    ``task_steps.node`` 分组展示模型调用，如果节点内部再改一次名字，
    这次调用就会掉到某个不存在的步骤名下、在时间线上凭空消失。

    需要更细的区分时应该加独立字段（例如 ``stage``），而不是复用 ``node``。
    """

    def __init__(self, node: str) -> None:
        self.node = node
        self._node_token = None
        self._buffer_token = None
        self._created_buffer = False

    def __enter__(self) -> "_Scope":
        if _BUFFER.get() is None:
            self._buffer_token = _BUFFER.set([])
            self._created_buffer = True
            # 只有最外层才有权决定"这批调用属于哪个节点"
            self._node_token = _NODE.set(self.node)
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._created_buffer and self._buffer_token is not None:
            _BUFFER.reset(self._buffer_token)
        if self._node_token is not None:
            _NODE.reset(self._node_token)


def scope(node: str) -> _Scope:
    """开一个收集窗口：``with telemetry.scope("generate_listing"): ...``"""
    return _Scope(node)


def drain() -> list[CallRecord]:
    """取出当前窗口内收集到的记录（不清空窗口本身，窗口由 ``scope`` 关闭）。"""
    buffer = _BUFFER.get()
    return list(buffer) if buffer else []


def record(
    *,
    provider: str,
    model: str,
    started: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    attempts: int = 1,
    ok: bool = True,
    error_code: str = "",
) -> None:
    """登记一次调用。没有收集窗口时静默跳过。

    **永不抛异常**：遥测写不进去不该让业务调用失败。
    """
    try:
        buffer = _BUFFER.get()
        if buffer is None:
            return
        buffer.append(
            CallRecord(
                node=_NODE.get(),
                provider=provider,
                model=model,
                latency_ms=_now_ms(started),
                prompt_tokens=int(prompt_tokens or 0),
                completion_tokens=int(completion_tokens or 0),
                attempts=int(attempts or 1),
                ok=ok,
                error_code=error_code,
            )
        )
    except Exception:  # noqa: BLE001 - 见 docstring
        pass


def summarize(records: list[CallRecord]) -> dict[str, Any]:
    """把一组调用压成摘要（进任务输出或接口响应用）。"""
    if not records:
        return {"calls": 0, "attempts": 0, "tokens": 0, "latency_ms": 0, "failures": 0}
    return {
        "calls": len(records),
        "attempts": sum(r.attempts for r in records),
        "tokens": sum(r.prompt_tokens + r.completion_tokens for r in records),
        "latency_ms": sum(r.latency_ms for r in records),
        "failures": sum(0 if r.ok else 1 for r in records),
    }


__all__ = ["CallRecord", "drain", "record", "scope", "summarize"]
