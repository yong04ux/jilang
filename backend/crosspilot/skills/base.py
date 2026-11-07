"""Skill 协议层：能力单元的统一描述（PRD v3.0 §5.2）。

``SkillSpec`` 是能力的**唯一真源**，被三处消费：

1. ``GET /api/skills`` —— 列表与参数表单（前端不再硬编码技能清单）；
2. ``POST /api/skills/{key}/run`` —— 统一执行入口；
3. 对话调度器（P1，从注册表得知「有哪些能力、各自要什么参数」）。

纪律（与 ``agent/skills.py`` 的文件头注释一致）：

- executor **只做参数拼装与调用**，算数一律在 ``engine`` / ``ingest`` 里，
  保证「技能页」「工作台」「旧 7 节点图」走同一条代码路径；
- ``requires`` 不满足就报错，不降级（缺模型 Key → 428 ``api_key_required``）；
- 产出里的 ``is_demo`` 一路透传到接口与任务记录，绝不假装是真数据。

本模块**不 import** 任何 ``engine`` / ``ingest`` / ``agent`` 模块：协议层不依赖业务，
业务由 executor 实现，避免「协议层 → 业务 → 协议层」的回环。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel

#: 产出渲染方式。前端按它选渲染器，不按 skill key 硬编码。
RENDERERS = ("report", "table", "listing", "chart")

#: 依赖项前缀约定：``llm`` = 需要可用模型；``data:xxx`` = 需要某类数据资产。
REQUIRE_LLM = "llm"


@dataclass(frozen=True)
class SkillSpec:
    """一个可独立运行的能力单元。

    ``inputs`` 是真 Pydantic 模型而不是 JSON Schema 字符串：表单由它生成，
    执行时用它校验，两件事共用一份定义（同一件能力只允许一处定义）。
    """

    key: str
    name: str
    category: str
    summary: str
    inputs: type[BaseModel]
    output_schema: dict[str, Any]
    executor: Callable[["SkillContext", Any], Any]
    renderer: str = "report"
    requires: tuple[str, ...] = ()
    credits: int = 1
    status: str = "available"

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("SkillSpec.key 不能为空")
        if self.renderer not in RENDERERS:
            raise ValueError(f"{self.key}: 未知的 renderer {self.renderer!r}")
        if not isinstance(self.requires, tuple):
            raise ValueError(f"{self.key}: requires 必须是 tuple")


@dataclass(frozen=True)
class SkillContext:
    """执行一次技能所需的上下文。

    图内节点传 ``task=None``：节点自己已有 ``_run_step`` 包装，
    让 executor 再开子步骤会改变 ``task_steps`` 的行数（既有测试断言步骤列表完全相等）。
    """

    db: Any
    user_id: str
    tenant_id: str
    provider: Any = None
    settings: Any = None
    storage: Any = None
    task: Any = None
    marketplace: Any = None
    is_demo: bool = False


class SkillError(Exception):
    """技能执行的可预期错误（消息可直接展示给用户）。"""

    status_code = 400
    code = "skill_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SkillResourceMissing(SkillError):
    """引用的报告 / 草稿 / 数据批次不存在，或不属于当前租户。"""

    status_code = 404
    code = "skill_resource_missing"

    def __init__(self, kind: str, ref: str | None = None) -> None:
        super().__init__(f"{kind}不存在")
        self.kind = kind
        self.ref = ref


class SkillInputError(SkillError):
    """参数本身不合法（比 Pydantic 校验更靠后的一层：语义检查）。"""

    status_code = 422
    code = "skill_input_invalid"


class SkillPayloadTooLarge(SkillError):
    """上传内容超过配置上限。"""

    status_code = 413
    code = "skill_payload_too_large"

    def __init__(self, limit: int) -> None:
        super().__init__(f"文件超过 {limit // (1024 * 1024)}MB 上限，请拆分后重试")
        self.limit = limit


__all__ = [
    "REQUIRE_LLM",
    "RENDERERS",
    "SkillContext",
    "SkillError",
    "SkillInputError",
    "SkillPayloadTooLarge",
    "SkillResourceMissing",
    "SkillSpec",
]
