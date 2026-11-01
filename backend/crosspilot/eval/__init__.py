"""评测体系，分两层。

**离线层**（``cases`` / ``assertions`` / ``runner`` / ``report``）
    四个维度：工具调用正确性、Listing 事实一致性、任务完成率、失败恢复。
    规则引擎 + 内存 checkpoint，同输入同输出，可逐条 diff。

**模型层**（``live_cases`` / ``live_scoring`` / ``live_runner``）
    真的调模型，产出有波动，所以比的是质量分与稳定性，不是"是否一致"。

    python -m scripts.eval_agent             # 离线：跑全部，更新基线
    python -m scripts.eval_agent --check     # 离线：与基线比，有回归退出码 1
    python -m scripts.eval_llm --dry-run     # 模型层：干跑验证链路
    python -m scripts.eval_llm --provider deepseek --model deepseek-flash         --api-key $KEY --repeats 3          # 模型层：真跑

边界：模型层只评 Listing 的事实一致性与遵从度，不评"文案好不好读"；
两层都不算调用金额。
"""

from __future__ import annotations

from .assertions import BANNED_TERMS, check
from .live_cases import LLMCase, build_live_suite
from .live_scoring import DraftScore, score_draft
from .cases import DIMENSIONS, EvalCase, build_suite, suite_stats
from .report import build_result, compare, load_json, render_markdown, write_json
from .runner import observe

__all__ = [
    "BANNED_TERMS",
    "DIMENSIONS",
    "DraftScore",
    "LLMCase",
    "EvalCase",
    "build_result",
    "build_live_suite",
    "build_suite",
    "check",
    "compare",
    "load_json",
    "observe",
    "render_markdown",
    "score_draft",
    "suite_stats",
    "write_json",
]
