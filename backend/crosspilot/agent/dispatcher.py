"""Skill Dispatcher：技能的统一执行入口。

职责（计划 §5.1 规定的检查顺序）
================================

一次派发依次回答五个问题，**任何一个不通过都不进入执行**：

1. 技能存在吗？            → 404 ``skill_not_found``
2. 技能启用了吗？          → 409 ``skill_disabled``
3. 绑定执行器了吗？        → 409 ``skill_not_executable``（注册成功 ≠ 可以跑）
4. 输入合法吗？            → 422 ``skill_input_invalid``（带字段名）
5. 权限与依赖满足吗？      → 403 ``skill_forbidden`` / 409 ``skill_dependency_missing``

为什么要把这些检查放在一个地方
==============================

改造前 ``api/agents.py`` 的 ``/api/agent/runs`` 直接在端点里判「缺不缺竞品」
「缺不缺商品名」，技能级的前置条件没有统一位置；再加一条入口（技能直连、
对话调度器）就得复制一遍。这里收敛成一条路径，端点只负责认证与错误映射。

超时的真实性与边界
==================

``timeout_seconds`` 是**真的会被执行**的：执行器跑在单独线程里，
超时抛 ``SkillTimeout``。必须如实说明它的局限——**同步线程无法被强杀**，
超时后底层调用（例如模型请求）可能仍在进行。因此：

- 这只是**兜底**，不是细粒度超时控制；模型调用自己的超时
  （``DeepSeekClient(timeout=90)``）才是第一道防线；
- 线程池 ``shutdown(wait=False)``，不会因为超时把请求一起卡住。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

from pydantic import BaseModel, ValidationError

from .contracts import (
    DEP_LLM,
    DEP_PROVIDER,
    SkillContext,
    SkillDefinition,
    SkillDependencyMissing,
    SkillDisabled,
    SkillForbidden,
    SkillInputInvalid,
    SkillNotExecutable,
    SkillNotFound,
    SkillResult,
    SkillTimeout,
)
from .definitions import get_definition

STATUS_SUCCEEDED = "succeeded"


# ---------------------------------------------------------------------------
# 检查
# ---------------------------------------------------------------------------


def _require_definition(key: str) -> SkillDefinition:
    definition = get_definition(key)
    if definition is None:
        # 注意：租户自定义技能只有元数据（表里），没有执行器，因此同样落在
        # 「不存在于可执行清单」这一支，提示里说清楚，避免用户以为是权限问题。
        raise SkillNotFound(
            f"技能不存在或暂不支持直接运行：{key}",
            detail={"skill_key": key},
        )
    if not definition.enabled:
        raise SkillDisabled(f"技能已停用：{definition.name}", detail={"skill_key": key})
    if definition.executor is None:
        raise SkillNotExecutable(
            f"技能「{definition.name}」尚未实现执行器，当前不可运行"
            + (f"：{definition.note}" if definition.note else ""),
            detail={"skill_key": key, "status": definition.status},
        )
    return definition


def _check_permissions(definition: SkillDefinition, granted: set[str] | None) -> None:
    required = set(definition.required_permissions)
    if not required:
        return
    if not required <= (granted or set()):
        missing = sorted(required - (granted or set()))
        raise SkillForbidden(
            f"缺少运行「{definition.name}」所需的权限",
            detail={"missing_permissions": missing},
        )


def _check_dependencies(definition: SkillDefinition, ctx: SkillContext) -> None:
    missing: list[str] = []
    for dep in definition.dependencies:
        if dep == DEP_PROVIDER and not ctx.has_provider():
            missing.append(dep)
        elif dep == DEP_LLM and not ctx.has_llm():
            missing.append(dep)
    if not missing:
        return
    if DEP_LLM in missing:
        # 缺模型不是"服务不可用"，是"没配置"——文案要让用户知道去设置页
        raise SkillDependencyMissing(
            "该技能需要调用大模型，当前没有可用配置；请先在设置里配置并测试模型",
            detail={"missing": missing, "action": "open_settings"},
        )
    raise SkillDependencyMissing(
        "运行环境缺少该技能所需的服务，请稍后重试",
        detail={"missing": missing},
    )


def _validate_input(
    definition: SkillDefinition, params: dict[str, Any] | None
) -> BaseModel | None:
    if definition.input_model is None:
        return None
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise SkillInputInvalid("参数必须是一个对象", detail={"field": None})
    try:
        return definition.input_model(**params)
    except ValidationError as exc:
        fields = [
            {
                "field": ".".join(str(p) for p in err.get("loc", ())) or None,
                "message": str(err.get("msg") or ""),
                "type": str(err.get("type") or ""),
            }
            for err in exc.errors()[:8]
        ]
        first = fields[0]["field"] if fields else None
        raise SkillInputInvalid(
            "参数不合法" + (f"：{first}" if first else ""),
            detail={"errors": fields},
        ) from exc


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------


def _run_with_timeout(fn, timeout_seconds: float):
    """在独立线程里跑，超时抛 ``SkillTimeout``（局限见模块文档）。"""
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="skill")
    future = pool.submit(fn)
    try:
        return future.result(timeout=max(timeout_seconds, 0.001))
    except FuturesTimeout as exc:
        future.cancel()
        raise SkillTimeout(
            f"技能执行超过 {timeout_seconds:g} 秒未返回，已停止等待",
            detail={"timeout_seconds": timeout_seconds},
        ) from exc
    finally:
        pool.shutdown(wait=False)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _collect_warnings(result: Any) -> list[str]:
    raw = getattr(result, "warnings", None)
    if raw is None and isinstance(result, dict):
        raw = result.get("warnings")
    if not raw:
        return []
    return [str(item) for item in raw][:20]


def _collect_quality(result: Any) -> dict[str, Any] | None:
    """只有草稿带质检块；其它技能没有，返回 None 而不是伪造一个空壳。"""
    qc = getattr(result, "quality_check", None)
    if qc is None:
        return None
    return _jsonable(qc)


def _collect_provenance(result: Any, ctx: SkillContext) -> dict[str, Any]:
    """来源标记。

    两条来源合并，**执行器显式声明的优先**：

    1. 执行器在结果里给的 ``provenance``（子图会带 ``data_provider`` /
       ``fetched_at`` / ``is_demo`` —— 数据从哪来、什么时候取的）；
    2. 从这里的内省补充模型 Provider（``provider``）。

    本分支上"示例数据"的等价标记是 ``is_demo``（没有 ``is_mock`` 这一维，
    也不为了对齐计划示例而编一个出来）。拿不到来源就不写这个键。
    """
    provenance: dict[str, Any] = {}

    declared = result.get("provenance") if isinstance(result, dict) else None
    if isinstance(declared, dict):
        provenance.update({k: v for k, v in declared.items() if v not in (None, "", [])})

    provider = getattr(ctx.provider, "name", None)
    if provider:
        provenance["provider"] = provider

    data_provenance = getattr(result, "data_provenance", None)
    if data_provenance is not None:
        data_source = getattr(data_provenance, "data_source", None)
        if data_source:
            provenance.setdefault("data_source", data_source)
        is_demo = getattr(data_provenance, "is_demo", None)
        if is_demo is not None:
            provenance.setdefault("is_demo", bool(is_demo))
    elif isinstance(result, dict):
        if isinstance(result.get("is_demo"), bool):
            provenance.setdefault("is_demo", result["is_demo"])
        if result.get("source_format"):
            provenance.setdefault("data_source", result["source_format"])
        if result.get("source_name"):
            provenance.setdefault("source_name", result["source_name"])
    return provenance


def dispatch(
    key: str,
    params: dict[str, Any] | None,
    *,
    ctx: SkillContext,
    granted_permissions: set[str] | None = None,
) -> SkillResult:
    """执行一个技能并返回统一信封。

    失败一律抛 ``SkillError`` 子类（带 ``status_code`` / ``code`` / ``detail``），
    由 HTTP 层翻译成响应；这里不做任何降级——缺依赖就报缺依赖。
    """
    definition = _require_definition(key)
    _check_permissions(definition, granted_permissions)
    payload = _validate_input(definition, params)
    _check_dependencies(definition, ctx)

    attempts = 0
    started = time.perf_counter()
    last_error: Exception | None = None
    result: Any = None

    # 重试次数有上限，且**只对超时重试**：错误分类落地（Phase 2 G10）之前，
    # 把"哪些错误该重试"猜宽了会重复扣费（Listing 生成会掉 tokens）。
    while attempts <= definition.max_retries:
        attempts += 1
        try:
            result = _run_with_timeout(
                lambda: definition.executor(ctx, payload), definition.timeout_seconds  # type: ignore[misc]
            )
            last_error = None
            break
        except SkillTimeout as exc:
            last_error = exc
            if attempts > definition.max_retries:
                raise
        # 其它异常不重试，直接向上抛（交给 HTTP 层或调用方分类）

    if last_error is not None:  # pragma: no cover - 上面的循环已经抛出
        raise last_error

    duration_ms = int((time.perf_counter() - started) * 1000)
    return SkillResult(
        skill_key=definition.key,
        skill_version=definition.version,
        status=STATUS_SUCCEEDED,
        result=_jsonable(result),
        warnings=_collect_warnings(result),
        quality=_collect_quality(result),
        provenance=_collect_provenance(result, ctx),
        attempts=attempts,
        duration_ms=duration_ms,
    )


__all__ = ["STATUS_SUCCEEDED", "dispatch"]
