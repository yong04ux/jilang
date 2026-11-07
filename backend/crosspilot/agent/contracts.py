"""Skill 契约层：把「能力的声明」和「能力能不能跑」分开。

为什么需要这一层
================

同一件能力只能有一份可执行的描述，否则会出现两份互不相干的说法——

- ``agent/registry.py`` 的 ``SKILLS``：静态 JSON，只有 ``status``；
- ``agent/skills.py`` 的裸函数：真正能跑的代码。

两者**命名对不上、数量也不对**（``check_integrity`` / ``quality_snapshot``
有函数没元数据，``data_validation`` / ``keyword_layout`` 有元数据没函数）。
后果是 ``GET /api/skills`` 会把跑不了的技能和能跑的技能列成一样，
用户点进去才发现没有执行入口。

这里做三件事，别的都不做：

1. ``SkillDefinition``：一份能力声明，**必须显式回答"有没有执行器"**；
2. ``SkillContext``：执行所需的上下文（Provider / 租户 / 预算），不塞进参数；
3. ``SkillResult``：统一结果信封。

刻意不做的事
------------

- **不在这里写业务**：executor 一律调用 ``agent/skills.py`` 或既有 ``engine``，
  否则「技能直连」「工作台」「独立页面」会慢慢分叉。
- **不把 timeout 当装饰**：``timeout_seconds`` 是真的会被执行的（见
  ``dispatcher._run_with_timeout``），不是只写进文档。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel

#: 执行器类型。``function`` = 一次函数调用；``graph`` = 需要多步状态/分支，
#: 由 LangGraph 子图执行。
ExecutorType = Literal["function", "graph"]

#: 定义状态，与 ``skill_definitions`` 表的取值保持一致。
STATUS_AVAILABLE = "available"
STATUS_BETA = "beta"
STATUS_DEV = "dev"
STATUS_DISABLED = "disabled"
STATUSES = (STATUS_AVAILABLE, STATUS_BETA, STATUS_DEV, STATUS_DISABLED)

#: 依赖项声明用的保留字。
#: - ``provider``：需要一个 Provider 实例（规则引擎也算，只要传进来）；
#: - ``llm``：需要**真正可调用模型**的 Provider（缺 Key 时不算满足）。
DEP_PROVIDER = "provider"
DEP_LLM = "llm"


class SkillContext:
    """执行一次技能所需的上下文。

    为什么和执行参数分开：``provider`` / ``tenant_id`` 不是业务输入，
    让它们出现在 ``input_schema`` 里会污染参数表单，也会诱导调用方伪造租户。
    """

    __slots__ = ("db", "tenant_id", "user_id", "provider", "timeout_seconds")

    def __init__(
        self,
        *,
        db: Any = None,
        tenant_id: str = "",
        user_id: str = "",
        provider: Any = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def has_provider(self) -> bool:
        return self.provider is not None

    def has_llm(self) -> bool:
        """Provider 是否**真的能调模型**（不是降级后的规则引擎）。"""
        provider = self.provider
        if provider is None:
            return False
        # RuleProvider.chat_client() 返回 None；DeepSeekProvider 返回真实客户端
        chat_client = getattr(provider, "chat_client", None)
        if callable(chat_client):
            try:
                return chat_client() is not None
            except Exception:  # noqa: BLE001 - 探测不能反过来让请求失败
                return False
        return False


class Executor(Protocol):
    """执行器签名：拿到上下文与**已校验**的输入模型，返回业务对象或 dict。"""

    def __call__(self, ctx: SkillContext, payload: BaseModel) -> Any: ...


@dataclass(frozen=True)
class SkillDefinition:
    """一个能力的完整声明。

    ``executable`` 是**派生属性**而不是独立字段：它必须由
    「已启用 + 绑定了执行器」算出来。写成独立字段就会出现
    "``executable=True`` 但 ``executor=None``" 这种自相矛盾的状态。
    """

    key: str
    name: str
    summary: str
    version: str
    #: 输入契约：优先用 Pydantic 模型（校验 + 生成 schema 共用一份定义）
    input_model: type[BaseModel] | None = None
    #: 没有输入模型时（未实现的技能）用它给出声明的 schema
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] = field(default_factory=dict)
    executor_type: ExecutorType = "function"
    executor: Executor | None = None
    required_permissions: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    timeout_seconds: float = 60.0
    max_retries: int = 0
    status: str = STATUS_AVAILABLE
    #: 面向用户的补充说明（为什么不可执行）。不写内部实现细节。
    note: str = ""

    # -- 派生状态 ----------------------------------------------------------
    @property
    def enabled(self) -> bool:
        """是否已启用（``disabled`` 是软删，不能执行）。"""
        return self.status != STATUS_DISABLED

    @property
    def executable(self) -> bool:
        """是否**真的**能跑。注册成功 ≠ 可以执行。"""
        return self.enabled and self.executor is not None

    # -- 契约导出 ----------------------------------------------------------
    def resolved_input_schema(self) -> dict[str, Any]:
        if self.input_model is not None:
            return self.input_model.model_json_schema()
        return self.input_schema or {"type": "object", "properties": {}}

    def as_registry_row(self) -> dict[str, Any]:
        """转成 ``seed_registry`` 需要的行（兼容旧 ``SKILLS`` 结构）。"""
        import json

        return {
            "key": self.key,
            "name": self.name,
            "summary": self.summary,
            "input": json.dumps(self.resolved_input_schema(), ensure_ascii=False),
            "output": json.dumps(self.output_schema or {}, ensure_ascii=False),
            "status": self.status,
        }

    def as_view(self) -> dict[str, Any]:
        """面向 API 的视图：在原有的基础上补上"能不能跑"。"""
        return {
            "key": self.key,
            "skill_key": self.key,
            "name": self.name,
            "summary": self.summary,
            "version": self.version,
            "status": self.status,
            "input_schema": self.resolved_input_schema(),
            "output_schema": self.output_schema or {},
            "executor_type": self.executor_type,
            "enabled": self.enabled,
            "executable": self.executable,
            "required_permissions": list(self.required_permissions),
            "dependencies": list(self.dependencies),
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# 统一结果信封
# ---------------------------------------------------------------------------


@dataclass
class SkillResult:
    """技能执行结果。

    ``result_ref`` 当前恒为 ``None``：执行入口**不落库**，
    产物由调用方决定是否保存（图里的 ``persist`` 节点统一保存，
    避免失败的任务留下半份数据）。
    """

    skill_key: str
    skill_version: str
    status: str
    result: Any = None
    warnings: list[str] = field(default_factory=list)
    quality: dict[str, Any] | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    result_ref: str | None = None
    task_id: str | None = None
    attempts: int = 1
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "skill_key": self.skill_key,
            "skill_version": self.skill_version,
            "status": self.status,
            "result": self.result,
            "result_ref": self.result_ref,
            "warnings": self.warnings,
            "quality": self.quality,
            "provenance": self.provenance,
            "attempts": self.attempts,
            "duration_ms": self.duration_ms,
        }


# ---------------------------------------------------------------------------
# 执行期错误（带 status_code，HTTP 层直接映射）
# ---------------------------------------------------------------------------


class SkillError(RuntimeError):
    """技能执行的可预期错误。``code`` 面向程序，``message`` 面向用户。"""

    code = "skill_error"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, detail: Any = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.detail = detail

    def as_payload(self) -> dict[str, Any]:
        """扁平化的错误载荷。

        ``detail`` 里的键（``errors`` / ``missing`` / ``field`` …）直接提到顶层，
        因为前端只会读 ``detail.errors`` 这一层（见 ``frontend/js/api.js``）；
        再套一层 ``detail`` 会让它拿不到字段名，只能显示一句干巴巴的提示。
        """
        payload: dict[str, Any] = dict(self.detail or {})
        payload["code"] = self.code
        payload["message"] = str(self)
        return payload


class SkillNotFound(SkillError):
    code = "skill_not_found"
    status_code = 404


class SkillDisabled(SkillError):
    code = "skill_disabled"
    status_code = 409


class SkillNotExecutable(SkillError):
    """有元数据但没有执行器——注册成功不等于可以执行。"""

    code = "skill_not_executable"
    status_code = 409


class SkillInputInvalid(SkillError):
    code = "skill_input_invalid"
    status_code = 422


class SkillMissingInput(SkillError):
    """输入格式没问题，但**内容缺失**，需要用户补充（不是参数写错）。

    单独一类是因为引导动作不同：``SkillInputInvalid`` 让用户改参数，
    这一类让用户补资料后重跑。
    """

    code = "skill_missing_input"
    status_code = 422


class SkillForbidden(SkillError):
    code = "skill_forbidden"
    status_code = 403


class SkillDependencyMissing(SkillError):
    code = "skill_dependency_missing"
    status_code = 409


class SkillTimeout(SkillError):
    code = "skill_timeout"
    status_code = 504


__all__ = [
    "DEP_LLM",
    "DEP_PROVIDER",
    "STATUSES",
    "STATUS_AVAILABLE",
    "STATUS_BETA",
    "STATUS_DEV",
    "STATUS_DISABLED",
    "Executor",
    "ExecutorType",
    "SkillContext",
    "SkillDefinition",
    "SkillDependencyMissing",
    "SkillDisabled",
    "SkillError",
    "SkillForbidden",
    "SkillInputInvalid",
    "SkillMissingInput",
    "SkillNotExecutable",
    "SkillNotFound",
    "SkillResult",
    "SkillTimeout",
]
