"""技能协议层（PRD v3.0 · P0）。

本包把已有业务能力包成可独立寻址的单元，是「能力协议」而不是「页面」的实现：

- ``base``     —— ``SkillSpec`` / ``SkillContext`` / 错误类型（不含业务依赖）
- ``inputs``   —— 七个技能的输入模型，同时是前端参数表单的契约
- ``executors``—— 七个 executor（薄壳，只拼装与调用）
- ``registry`` —— ``SKILL_REGISTRY``（唯一真源）与读视图
- ``runtime``  —— 执行、落库、``is_demo`` 透传

注意：``agent/skills.py`` 是**流程内部步骤**的实现来源，与这里的 executor 分工不同，
不要把它合并进来——旧图与既有测试都以它为锚点。
"""

from .base import (
    REQUIRE_LLM,
    RENDERERS,
    SkillContext,
    SkillError,
    SkillInputError,
    SkillPayloadTooLarge,
    SkillResourceMissing,
    SkillSpec,
)
from .registry import SKILL_REGISTRY, VERSION, get_skill_view, list_skill_views

__all__ = [
    "REQUIRE_LLM",
    "RENDERERS",
    "SKILL_REGISTRY",
    "VERSION",
    "SkillContext",
    "SkillError",
    "SkillInputError",
    "SkillPayloadTooLarge",
    "SkillResourceMissing",
    "SkillSpec",
    "get_skill_view",
    "list_skill_views",
]
