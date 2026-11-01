"""给模型产出的草稿打分。

四条判据，权重加起来 100，但**红线不参与权重**：

| 判据 | 分值 | 说明 |
| --- | ---: | --- |
| 事实可追溯 | 30 | 文案里每个数字都能在输入事实中找到 |
| 结构完整 | 25 | 标题 / 五点 / 描述 / 关键词齐全，条数在区间内 |
| 卖点覆盖 | 20 | 输入里的卖点有多少被真正写进文案 |
| 格式合规 | 15 | 标题与要点不超长、描述有实质内容 |
| 用语克制 | 10 | 不出现 best seller / 100% / #1 这类绝对化表述 |

**编造参数 → 0 分。** 不是扣分，是直接判 0：一个不存在的规格到了平台页面上，
代价是退货与投诉，不是"再润色一下"能解决的。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .assertions import BANNED_TERMS
from .live_cases import LLMCase

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

#: 编号/标签里的数字不是"参数"，不能当成编造。
#: 模型和规则引擎都爱写「1. ...」「卖点1：」「Point 2」，这些数字没有信息量。
_ORDINAL_LINE = re.compile(r"(?im)^\s*\d+[.)、:：]\s*")
_LABEL_NUMBER = re.compile(r"(卖点|规格|feature|point|item|spec|step)\s*\d+", re.I)


def _claim_numbers(text: str) -> list[str]:
    """只取**声称的参数**，先把编号和标签里的数字去掉。"""
    cleaned = _ORDINAL_LINE.sub(" ", text)
    cleaned = _LABEL_NUMBER.sub(r"\1", cleaned)
    return _NUMBER_RE.findall(cleaned)

#: 判据权重（合计 100）
WEIGHTS = {
    "traceability": 30,
    "structure": 25,
    "feature_coverage": 20,
    "format": 15,
    "wording": 10,
}

#: 达到这个分数才算通过（红线不过则直接 0 分）。
#: 注意：**分数够也可能不通过**——条数、超长、绝对化用语属于硬性违规，
#: 平台要求不会因为别处做得好就被抵消。``passed`` 需要同时满足两条。
PASS_SCORE = 75


@dataclass
class DraftScore:
    case_id: str
    score: int
    passed: bool
    parts: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "score": self.score,
            "passed": self.passed,
            "parts": self.parts,
            "failures": self.failures,
        }


# ---------------------------------------------------------------------------
# 取值
# ---------------------------------------------------------------------------


def _bullet_texts(draft: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in draft.get("bullets") or []:
        if isinstance(item, dict):
            text = f"{item.get('headline') or ''} {item.get('body') or ''}".strip()
            out.append({"text": text, "facts": list(item.get("supporting_facts") or [])})
        elif str(item).strip():
            out.append({"text": str(item), "facts": []})
    return out


def _corpus(case: LLMCase) -> str:
    product = case.request.get("product") or {}
    parts = [
        " ".join(f"{k} {v}" for k, v in (product.get("specifications") or {}).items()),
        " ".join(product.get("key_features") or []),
        str(product.get("price") or ""),
        str(product.get("name") or ""),
    ]
    return " ".join(parts).lower()


def _visible_text(draft: dict[str, Any]) -> str:
    chunks = [str(draft.get("title") or ""), str(draft.get("description") or "")]
    for item in _bullet_texts(draft):
        chunks.append(item["text"])
    for keyword in draft.get("search_terms") or []:
        chunks.append(str(keyword))
    return " ".join(chunks)


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------


def score_draft(case: LLMCase, draft: dict[str, Any]) -> DraftScore:
    rubric = case.rubric
    failures: list[str] = []
    parts = {key: 0 for key in WEIGHTS}

    if not draft:
        return DraftScore(case.case_id, 0, False, parts, ["没有产出草稿"])

    title = str(draft.get("title") or "").strip()
    bullets = _bullet_texts(draft)
    description = str(draft.get("description") or "").strip()

    # -- 红线：编造数字 ----------------------------------------------------
    corpus = _corpus(case)
    fabricated: list[str] = []
    for token in _claim_numbers(_visible_text(draft)):
        if token not in corpus:
            fabricated.append(token)
    if fabricated:
        # 唯一一个"直接判 0"的地方：宁可误判，也不能放过不存在的参数
        return DraftScore(
            case.case_id,
            0,
            False,
            parts,
            [f"编造参数：{sorted(set(fabricated))} 不在输入事实里"],
        )
    parts["traceability"] = WEIGHTS["traceability"]

    # -- 结构完整 ----------------------------------------------------------
    structure = 0
    if title:
        structure += 8
    else:
        failures.append("缺少标题")
    low, high = rubric.get("min_bullets", 5), rubric.get("max_bullets", 5)
    if low <= len(bullets) <= high:
        structure += 10
    else:
        failures.append(f"要点条数 {len(bullets)} 不在 {low}-{high} 区间")
    if len(description) >= int(rubric.get("min_description_chars", 200)):
        structure += 4
    else:
        failures.append(f"描述太短（{len(description)} 字符）")
    if draft.get("search_terms"):
        structure += 3
    else:
        failures.append("缺少搜索词")
    parts["structure"] = structure

    # -- 卖点覆盖 ----------------------------------------------------------
    required = [str(f).lower() for f in (rubric.get("required_features") or [])]
    if required:
        haystack = _visible_text(draft).lower()
        covered = [f for f in required if f in haystack]
        ratio = len(covered) / len(required)
        parts["feature_coverage"] = int(round(WEIGHTS["feature_coverage"] * ratio))
        need = float(rubric.get("min_feature_coverage", 0.7))
        if ratio < need:
            missing = [f for f in required if f not in covered]
            failures.append(f"卖点覆盖 {ratio * 100:.0f}% 低于要求 {need * 100:.0f}%，缺：{missing}")
    else:
        parts["feature_coverage"] = WEIGHTS["feature_coverage"]

    # -- 格式合规 ----------------------------------------------------------
    fmt = 0
    max_title = int(rubric.get("max_title_chars", 200))
    if title and len(title) <= max_title:
        fmt += 8
    elif len(title) > max_title:
        failures.append(f"标题超长（{len(title)} > {max_title}）")
    max_bullet = int(rubric.get("max_bullet_chars", 500))
    too_long = [i for i, b in enumerate(bullets, 1) if len(b["text"]) > max_bullet]
    if not too_long:
        fmt += 7
    else:
        failures.append(f"第 {too_long} 条要点超过 {max_bullet} 字符")
    parts["format"] = fmt

    # -- 用语克制 ----------------------------------------------------------
    haystack = _visible_text(draft).lower()
    hits = [term for term in BANNED_TERMS if term in haystack]
    if hits:
        failures.append(f"出现绝对化用语：{hits}")
    else:
        parts["wording"] = WEIGHTS["wording"]

    score = sum(parts.values())
    return DraftScore(case.case_id, score, score >= PASS_SCORE and not failures, parts, failures)


__all__ = ["PASS_SCORE", "WEIGHTS", "DraftScore", "score_draft"]
