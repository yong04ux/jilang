"""竞品分析服务（阶段 E2）。

把"校验 + 调用 Provider"收拢成一个函数，路由与 Agent Tool 共用，
避免工作台与独立页面各写一套。统计仍由 ``analysis.run_analysis`` 完成。
"""

from __future__ import annotations


from ..engine.analysis import validate_request
from ..models import AnalysisReport, CompetitorAnalysisRequest


class AnalysisInputError(ValueError):
    """输入校验失败，携带逐项错误。"""

    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        super().__init__("输入校验失败")
        self.errors = errors
        self.warnings = warnings or []


def run(
    provider, request: CompetitorAnalysisRequest, *, validate: bool = True
) -> AnalysisReport:
    """执行一次竞品分析（不落库；持久化由调用方负责）。"""
    if validate:
        outcome = validate_request(request)
        if not outcome.ok:
            raise AnalysisInputError(outcome.errors, outcome.warnings)
    return provider.analyze(request)


__all__ = ["AnalysisInputError", "run"]
