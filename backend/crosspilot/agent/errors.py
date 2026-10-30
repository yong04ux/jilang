"""统一错误分类。

为什么要有这一层
================

如果所有失败都写成 ``code="agent_step_failed"``、``message`` 直接拼
``f"{type(exc).__name__}: {exc}"``，后果是：

- 界面上分不清「参数填错」和「模型服务挂了」，用户只能干瞪眼；
- 节点无法按类型决定要不要重试，只能全都不重试或全都重试；
- 错误码里混进了 Python 异常类名，违反界面文案红线。

这里建立**唯一分类点**：把异常映射成 10 个枚举类别 + 处置策略，
任务记录、HTTP 响应、dispatcher 都从这里取结论。

刻意的边界
==========

- **只做分类，不做重试**。``retryable`` 是**声明**，具体重试循环由各自执行体
  决定（当前 dispatcher 只对超时重试，图节点不重试）。不在这里实现退避或队列重投。
- **不把异常原文透给用户**。``message`` 一律是面向用户的中文说明；
  原始文本只放在 ``log_message`` 里供日志使用，不进 API 响应。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    """ 的 10 类。取值直接落进 ``tasks.error_code``。"""

    VALIDATION_ERROR = "validation_error"
    MISSING_INPUT = "missing_input"
    PERMISSION_DENIED = "permission_denied"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    QUALITY_GATE_FAILED = "quality_gate_failed"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class ErrorPolicy:
    """某一类错误的默认处置。"""

    retryable: bool
    http_status: int
    #: 界面该引导用户做什么；为空表示不需要额外动作
    user_action: str = ""


#: 默认策略
POLICIES: dict[ErrorCategory, ErrorPolicy] = {
    ErrorCategory.VALIDATION_ERROR: ErrorPolicy(False, 422, "fix_input"),
    ErrorCategory.MISSING_INPUT: ErrorPolicy(False, 422, "provide_input"),
    ErrorCategory.PERMISSION_DENIED: ErrorPolicy(False, 403),
    ErrorCategory.PROVIDER_UNAVAILABLE: ErrorPolicy(True, 503),
    ErrorCategory.RATE_LIMITED: ErrorPolicy(True, 429),
    ErrorCategory.MODEL_TIMEOUT: ErrorPolicy(True, 504),
    ErrorCategory.MODEL_OUTPUT_INVALID: ErrorPolicy(True, 502),
    ErrorCategory.QUALITY_GATE_FAILED: ErrorPolicy(False, 422, "review"),
    ErrorCategory.CANCELLED: ErrorPolicy(False, 409),
    ErrorCategory.INTERNAL_ERROR: ErrorPolicy(False, 500),
}


#: 各类别面向用户的默认文案。**不拼接异常类名、不暴露环境变量与内部标识。**
DEFAULT_MESSAGES: dict[ErrorCategory, str] = {
    ErrorCategory.VALIDATION_ERROR: "输入不符合要求，请检查后重试",
    ErrorCategory.MISSING_INPUT: "缺少必要信息，请补充后再运行",
    ErrorCategory.PERMISSION_DENIED: "当前账号没有执行该操作的权限",
    ErrorCategory.PROVIDER_UNAVAILABLE: "上游服务暂时不可用，请稍后重试",
    ErrorCategory.RATE_LIMITED: "请求过于频繁，请稍后再试",
    ErrorCategory.MODEL_TIMEOUT: "模型响应超时，请稍后重试",
    ErrorCategory.MODEL_OUTPUT_INVALID: "模型返回的内容不符合要求，可以重试或换一个模型",
    ErrorCategory.QUALITY_GATE_FAILED: "结果未通过质量检查，请查看问题后修订",
    ErrorCategory.CANCELLED: "任务已取消",
    ErrorCategory.INTERNAL_ERROR: "服务内部错误，已记录追踪信息",
}


@dataclass
class ErrorInfo:
    """一次失败的分类结论。

    ``code`` 是**细粒度**错误码（例如 ``skill_not_executable``），
    ``category`` 是分类。两者都要留：分类决定处置策略，细码决定文案与排查方向。
    """

    category: ErrorCategory
    message: str
    code: str = ""
    retryable: bool = False
    http_status: int = 500
    user_action: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    #: 原始异常文本，**只进日志**，不进 API 响应
    log_message: str = ""

    @property
    def task_code(self) -> str:
        """落 ``tasks.error_code`` 的值：用分类而不是异常类名。"""
        return self.category.value

    def as_payload(self) -> dict[str, Any]:
        """扁平化的错误载荷：``detail`` 里的键提到顶层。

        前端只读 ``detail.errors`` / ``detail.message``（见
        ``frontend/js/api.js`` 的 ``describe``），多套一层就拿不到字段名。
        """
        payload: dict[str, Any] = dict(self.detail or {})
        payload["code"] = self.code or self.category.value
        payload["category"] = self.category.value
        payload["message"] = self.message
        payload["retryable"] = self.retryable
        if self.user_action:
            payload["action"] = self.user_action
        return payload


def _policy(category: ErrorCategory) -> ErrorPolicy:
    return POLICIES[category]


def make(
    category: ErrorCategory,
    *,
    message: str = "",
    code: str = "",
    detail: dict[str, Any] | None = None,
    retryable: bool | None = None,
    user_action: str | None = None,
    log_message: str = "",
) -> ErrorInfo:
    """按类别构造结论，未指定的项取该类别的默认值。"""
    policy = _policy(category)
    return ErrorInfo(
        category=category,
        code=code,
        message=message or DEFAULT_MESSAGES[category],
        retryable=policy.retryable if retryable is None else retryable,
        http_status=policy.http_status,
        user_action=policy.user_action if user_action is None else user_action,
        detail=detail or {},
        log_message=log_message,
    )


# ---------------------------------------------------------------------------
# 异常 → 分类
#
# 用「按类型逐个判」而不是「按消息猜」：猜消息会在文案改动时静默失效。
# 所有跨层导入都放在函数内，避免 agent 包反向依赖 api / services 造成循环。
# ---------------------------------------------------------------------------


def _error_items(exc: BaseException, limit: int = 5) -> list[dict[str, Any]]:
    """把不同来源的"错误条目"统一成 ``{field, message}``。

    两处实现不一样：``AnalysisInputError.errors`` 是字符串数组，
    ``ImportValidationError.errors`` 是 ``RowError`` 对象。统一在边界做掉，
    免得前端要按来源分支。
    """
    items: list[dict[str, Any]] = []
    for raw in list(getattr(exc, "errors", []) or [])[:limit]:
        if isinstance(raw, str):
            items.append({"field": None, "message": raw})
        elif hasattr(raw, "as_dict"):
            data = raw.as_dict()
            items.append(
                {
                    "field": data.get("field"),
                    "message": data.get("message") or "",
                    "row": data.get("row"),
                }
            )
        elif isinstance(raw, dict):
            items.append(dict(raw))
        else:  # pragma: no cover - 兜底
            items.append({"field": None, "message": str(raw)})
    return items


def classify(exc: BaseException) -> ErrorInfo:
    """把任意异常映射成分类结论。未知异常一律 ``internal_error``。"""
    raw = f"{type(exc).__name__}: {exc}"[:500]

    # -- 取消（必须最先判：它是控制流，不是错误） -------------------------
    from ..services.tasks import TaskCancelled

    if isinstance(exc, TaskCancelled):
        return make(ErrorCategory.CANCELLED, message=str(exc) or "任务已取消", log_message=raw)

    # -- 技能层错误：已经自带语义，按类映射 -------------------------------
    from .contracts import (
        SkillDependencyMissing,
        SkillDisabled,
        SkillForbidden,
        SkillInputInvalid,
        SkillMissingInput,
        SkillNotExecutable,
        SkillNotFound,
        SkillTimeout,
    )

    if isinstance(exc, SkillMissingInput):
        return make(
            ErrorCategory.MISSING_INPUT,
            message=str(exc),
            code=exc.code,
            detail=exc.detail or {},
            log_message=raw,
        )
    if isinstance(exc, (SkillInputInvalid,)):
        return make(
            ErrorCategory.VALIDATION_ERROR,
            message=str(exc),
            code=exc.code,
            detail=exc.detail or {},
            log_message=raw,
        )
    if isinstance(exc, (SkillNotFound, SkillDisabled, SkillNotExecutable)):
        # 技能不存在/停用/没实现：不是用户的输入问题，也不是系统故障
        return make(
            ErrorCategory.VALIDATION_ERROR,
            message=str(exc),
            code=exc.code,
            detail=exc.detail or {},
            user_action="choose_skill",
            log_message=raw,
        )
    if isinstance(exc, SkillForbidden):
        return make(
            ErrorCategory.PERMISSION_DENIED,
            message=str(exc),
            code=exc.code,
            detail=exc.detail or {},
            log_message=raw,
        )
    if isinstance(exc, SkillDependencyMissing):
        missing = (exc.detail or {}).get("missing") or []
        if "llm" in missing:
            # 缺模型 Key 是「没配置」，不是「服务挂了」：引导去设置页
            return make(
                ErrorCategory.PROVIDER_UNAVAILABLE,
                message=str(exc),
                code="llm_not_configured",
                retryable=False,
                user_action="open_settings",
                log_message=raw,
            )
        return make(
            ErrorCategory.PROVIDER_UNAVAILABLE,
            message=str(exc),
            code=exc.code,
            retryable=False,
            detail=exc.detail or {},
            log_message=raw,
        )
    if isinstance(exc, SkillTimeout):
        return make(
            ErrorCategory.MODEL_TIMEOUT,
            message=str(exc),
            code=exc.code,
            detail=exc.detail or {},
            log_message=raw,
        )

    # -- 模型调用 ---------------------------------------------------------
    from ..llm.llm import LLMError

    if isinstance(exc, LLMError):
        kind = getattr(exc, "kind", "unknown")
        if kind == "rate_limit":
            return make(ErrorCategory.RATE_LIMITED, log_message=raw)
        if kind == "network":
            return make(ErrorCategory.MODEL_TIMEOUT, log_message=raw)
        if kind == "auth":
            return make(
                ErrorCategory.PROVIDER_UNAVAILABLE,
                message="模型密钥无效或没有权限，请到设置里检查并重新测试",
                code="llm_auth_failed",
                retryable=False,
                user_action="open_settings",
                log_message=raw,
            )
        if kind == "bad_request":
            return make(ErrorCategory.VALIDATION_ERROR, message=str(exc), log_message=raw)
        if kind == "server":
            return make(ErrorCategory.PROVIDER_UNAVAILABLE, log_message=raw)
        if kind in {"invalid_json", "empty"}:
            return make(ErrorCategory.MODEL_OUTPUT_INVALID, log_message=raw)
        return make(ErrorCategory.INTERNAL_ERROR, log_message=raw)

    from ..llm.providers import ProviderError

    if isinstance(exc, ProviderError):
        return make(
            ErrorCategory.PROVIDER_UNAVAILABLE,
            message="模型配置有误，请到设置里检查",
            retryable=False,
            user_action="open_settings",
            log_message=raw,
        )

    # -- 数据源 -----------------------------------------------------------
    from ..market.competitor_provider import CompetitorProviderError, ProviderNotConfigured

    if isinstance(exc, ProviderNotConfigured):
        # 未接入/未配置：不是"过会儿再试"，是"现在就没有这条路"
        return make(
            ErrorCategory.PROVIDER_UNAVAILABLE,
            message=str(exc),
            code="data_provider_not_configured",
            retryable=False,
            user_action="import_data",
            log_message=raw,
        )
    if isinstance(exc, CompetitorProviderError):
        return make(
            ErrorCategory.PROVIDER_UNAVAILABLE,
            message="竞品数据获取失败，请稍后重试",
            code="competitor_fetch_failed",
            log_message=raw,
        )

    # -- 输入校验 ---------------------------------------------------------
    # 注意：pydantic 的 ValidationError 也继承 ValueError，必须单独判
    try:
        from pydantic import ValidationError as PydanticValidationError
    except ImportError:  # pragma: no cover - pydantic 是硬依赖
        PydanticValidationError = ()  # type: ignore[assignment]

    if isinstance(exc, PydanticValidationError):
        errors = [
            {
                "field": ".".join(str(p) for p in item.get("loc", ())) or None,
                "message": str(item.get("msg") or ""),
            }
            for item in getattr(exc, "errors", lambda: [])()[:5]
        ]
        first = errors[0]["field"] if errors else None
        return make(
            ErrorCategory.VALIDATION_ERROR,
            message="输入不符合要求" + (f"：{first}" if first else ""),
            detail={"errors": errors},
            log_message=raw,
        )

    from ..services.competitor_service import AnalysisInputError
    from ..ingest.importers import ImportValidationError
    from ..services.listing_service import ListingError

    if isinstance(exc, (AnalysisInputError, ImportValidationError)):
        return make(
            ErrorCategory.VALIDATION_ERROR,
            message=str(exc),
            detail={"errors": _error_items(exc)},
            log_message=raw,
        )
    if isinstance(exc, ListingError):
        return make(ErrorCategory.VALIDATION_ERROR, message=str(exc), log_message=raw)

    # 裸 ValueError：本项目里 `engine` 层用它表达"输入校验失败"
    # （例如 run_analysis 的 "输入校验失败: ..."），所以归到 validation_error。
    # 必须放在上面那些具体子类之后，否则会掩盖更精确的分类。
    if isinstance(exc, ValueError):
        return make(ErrorCategory.VALIDATION_ERROR, message=str(exc), log_message=raw)

    # -- 权限 -------------------------------------------------------------
    from ..tenancy import TenantError

    if isinstance(exc, TenantError):
        return make(ErrorCategory.PERMISSION_DENIED, message=str(exc), log_message=raw)

    status_code = getattr(exc, "status_code", None)
    if status_code in (401, 403):
        detail = getattr(exc, "detail", None)
        return make(
            ErrorCategory.PERMISSION_DENIED,
            message=detail if isinstance(detail, str) and detail else "",
            log_message=raw,
        )

    # -- 数据层 -----------------------------------------------------------
    from ..persistence.db import DatabaseError

    if isinstance(exc, DatabaseError):
        # 数据服务不可用是**暂时性**的，可以重试；但不要暴露连接串
        return make(
            ErrorCategory.PROVIDER_UNAVAILABLE,
            message="数据服务暂时不可用，请稍后重试",
            code="database_unavailable",
            log_message=raw,
        )

    if isinstance(exc, TimeoutError):
        return make(ErrorCategory.MODEL_TIMEOUT, log_message=raw)

    # -- 兜底 -------------------------------------------------------------
    return make(ErrorCategory.INTERNAL_ERROR, log_message=raw)


def is_retryable(exc: BaseException) -> bool:
    """该异常按分类是否可以重试。**不执行重试**，只是查询策略。"""
    return classify(exc).retryable


__all__ = [
    "DEFAULT_MESSAGES",
    "POLICIES",
    "ErrorCategory",
    "ErrorInfo",
    "ErrorPolicy",
    "classify",
    "is_retryable",
    "make",
]
