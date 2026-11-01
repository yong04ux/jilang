"""离线评测体系。

四个维度：工具调用正确性、Listing 事实一致性、任务完成率、失败恢复。
全部离线执行（规则引擎 + 内存 checkpoint），同输入同输出，可逐条 diff。

    python -m scripts.eval_agent            # 跑全部，更新基线
    python -m scripts.eval_agent --print    # 只打印，不写文件
    python -m scripts.eval_agent --check    # 与基线比较，有回归则退出码 1

边界：不评大模型文案质量，也不算调用金额。原因见 ``report.render_markdown`` 末尾。
"""

from __future__ import annotations

from .assertions import BANNED_TERMS, check
from .cases import DIMENSIONS, EvalCase, build_suite, suite_stats
from .report import build_result, compare, load_json, render_markdown, write_json
from .runner import observe

__all__ = [
    "BANNED_TERMS",
    "DIMENSIONS",
    "EvalCase",
    "build_result",
    "build_suite",
    "check",
    "compare",
    "load_json",
    "observe",
    "render_markdown",
    "suite_stats",
    "write_json",
]
