"""规则断言：每条用例跑完之后判它对不对。

原则
====

1. **断言只读观测结果，不重跑逻辑**。跑和判分开，判断才能被单独测试；
2. **每条失败都要说清理由**。输出一句话人能读懂，不是 `assert False`；
3. **不清楚就不判**。宁可少一条断言，也不加一条"大概如此"的检查——
   假绿比红灯更贵。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .cases import (
    DIM_COMPLETION,
    DIM_FACT,
    DIM_RECOVERY,
    DIM_TOOL_CALL,
    EvalCase,
    FAULT_QUALITY,
    KIND_COMPETITOR,
    KIND_LISTING,
)

#: 绝对化/夸大用语：Listing 里出现即不合格
BANNED_TERMS: tuple[str, ...] = (
    "best seller",
    "bestseller",
    "100%",
    "#1",
    "no.1",
    "cheapest",
    "world's best",
)

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


# ---------------------------------------------------------------------------
# 取值工具
# ---------------------------------------------------------------------------


def _bullets(listing: dict[str, Any]) -> list[dict[str, Any]]:
    """要点是对象（headline/body/supporting_facts），不是字符串。

    直接 ``str(b)`` 会把 ``character_count`` 算进正文，从而把"编造数字"
    这条检查变成自我触发——取值必须精确。
    """
    out: list[dict[str, Any]] = []
    for item in listing.get("bullets") or []:
        if isinstance(item, dict):
            text = f"{item.get('headline') or ''} {item.get('body') or ''}".strip()
            out.append({"text": text, "facts": [str(f) for f in (item.get("supporting_facts") or [])]})
        elif str(item).strip():
            out.append({"text": str(item), "facts": []})
    return out


def _report(observed: dict[str, Any]) -> dict[str, Any]:
    return observed.get("report") or observed.get("analysis_report") or {}


def _facts_corpus(case: EvalCase, observed: dict[str, Any]) -> str:
    """可核对的事实语料：自己的资料 + 竞品数据 + 报告里的统计。

    要点里的数字**必须**能在这里找到，否则就是编造参数。
    """
    payload = case.payload
    parts = [
        json.dumps(payload.get("own_specs") or {}, ensure_ascii=False),
        json.dumps(payload.get("own_key_features") or [], ensure_ascii=False),
        json.dumps(payload.get("competitors") or [], ensure_ascii=False),
        json.dumps(_report(observed), ensure_ascii=False),
        json.dumps(observed.get("listing", {}).get("fact_ledger") or {}, ensure_ascii=False),
    ]
    return " ".join(parts).lower()


def _numbers(text: str) -> list[str]:
    return _NUMBER_RE.findall(text)


# ---------------------------------------------------------------------------
# 各维度
# ---------------------------------------------------------------------------


def _check_tool_call(case: EvalCase, observed: dict[str, Any]) -> list[str]:
    """工具调用正确性 = 选对工作流 + 计划骨架正确 + 实跑步骤落在计划内且顺序正确。"""
    failures: list[str] = []
    expect = case.expect

    actual_kind = observed.get("spec_kind")
    if actual_kind != expect["kind"]:
        failures.append(f"分派错误：跑了 {actual_kind}，期望 {expect['kind']}")

    plan = observed.get("plan") or []
    if not plan:
        failures.append("计划为空：任务提交时前端拿不到步骤骨架")
    if plan[:2] != ["validate", "dispatch"] or (plan and plan[-1] != "finalize"):
        failures.append(f"计划骨架不对（应以 validate/dispatch 开头、finalize 结尾）：{plan[:3]}...")

    steps = [s["node"] for s in observed.get("steps") or []]
    if observed.get("outcome") not in {"failed"} and not steps:
        failures.append("没有任何步骤记录（除失败外都应留下步骤）")
    unknown = [s for s in steps if s not in plan]
    if unknown:
        failures.append(f"执行了计划外的节点：{unknown}")
    # 顺序按**首次出现**判：修订循环会让 generate_listing 合法地重复出现，
    # 用全部出现位置去比会把正常的回环判成错。
    seen: set[str] = set()
    first_positions: list[int] = []
    for step in steps:
        if step in seen or step not in plan:
            continue  # 计划外的节点已经在上面单独报过，这里跳过
        seen.add(step)
        first_positions.append(plan.index(step))
    if first_positions != sorted(first_positions):
        failures.append("步骤顺序与计划不一致")

    # 该产出的东西产出了，不该产出的没有
    produced = observed.get("outcome") in {"succeeded", "partial"}
    has_report = bool(_report(observed))
    has_listing = bool(observed.get("listing"))
    if produced and expect["kind"] == KIND_COMPETITOR and not has_report:
        failures.append("竞品分析跑完却没有报告")
    if produced and expect["kind"] == KIND_LISTING and not has_listing:
        failures.append("只写文案跑完却没有草稿")
    if has_listing and expect["kind"] == KIND_COMPETITOR:
        failures.append("只做分析的流程不该产出 Listing")
    return failures


def _check_fact_consistency(case: EvalCase, observed: dict[str, Any]) -> list[str]:
    """Listing 事实一致性：数字有出处、要点有依据、不出现绝对化用语。"""
    failures: list[str] = []
    listing = observed.get("listing") or {}
    if not listing:
        if observed.get("outcome") in {"succeeded", "partial"}:
            failures.append("结局是成功但没有草稿")
        return failures

    bullets = _bullets(listing)
    if not bullets:
        failures.append("草稿没有任何要点")
        return failures

    corpus = _facts_corpus(case, observed)
    for index, bullet in enumerate(bullets, start=1):
        if not bullet["facts"]:
            failures.append(f"第 {index} 条要点没有引用事实")
        for token in _numbers(bullet["text"]):
            if token not in corpus:
                failures.append(f"第 {index} 条要点里的数字「{token}」在事实里找不到")
                break

    haystack = " ".join([b["text"] for b in bullets] + [str(listing.get("title") or "")]).lower()
    for term in BANNED_TERMS:
        if term in haystack:
            failures.append(f"出现绝对化用语：{term}")

    # 示例数据必须留标记，不能让人以为是真实店铺数据。
    # 只对**真的用了竞品数据**的流程生效：只写文案时不消费竞品行，
    # 资料全是用户自己填的，来源本来就该是 manual。
    if case.kind != KIND_LISTING and case.payload.get("data_source") == "demo":
        provenance = observed.get("provenance") or listing.get("data_provenance") or {}
        if not provenance.get("is_demo"):
            failures.append("示例数据标记丢失")

    # 事实账本：有草稿就该有账本，否则质检无依据
    if not listing.get("fact_ledger"):
        failures.append("草稿缺少事实账本（fact_ledger）")
    return failures


def _check_completion(case: EvalCase, observed: dict[str, Any]) -> list[str]:
    """结局是否符合预期，且"暂停"没有被悄悄当成"完成"。"""
    failures: list[str] = []
    expect = case.expect
    outcome = observed.get("outcome")

    if expect.get("expects_pause"):
        if not observed.get("paused") and not observed.get("paused_once"):
            failures.append("竞品样本不足却没有暂停直接跑完")
        if not observed.get("pending"):
            failures.append("暂停了但没有待确认内容（界面无法继续）")
        # 确认之后才允许出 partial
        if outcome == "succeeded":
            failures.append("partial 被静默转换成了 succeeded")

    if not expect.get("expects_pause") and "outcome" in expect and outcome != expect["outcome"]:
        failures.append(f"结局是 {outcome}，期望 {expect['outcome']}")

    if expect.get("outcome") == "needs_user_input" and observed.get("listing"):
        failures.append("缺少商品事实却仍然产出了草稿")

    status = observed.get("task_status") or ""
    if expect.get("expects_pause") and status and status != "partial":
        failures.append(f"暂停并确认后的任务状态是 {status}，应为 partial")
    return failures


def _check_recovery(case: EvalCase, observed: dict[str, Any]) -> list[str]:
    """故障恢复：错误分类对、不误报成功、失败不留半成品。"""
    failures: list[str] = []
    expect = case.expect
    outcome = observed.get("outcome")

    if expect.get("fault_noop"):
        # 该故障在这条链路上不会触发，只要求任务没被判失败
        if outcome in {"failed", ""}:
            failures.append(f"注入的故障本应无效，实际结局是 {outcome or '空'}")
        return failures

    if case.fault == FAULT_QUALITY:
        # 质检恒不过时，Listing 子图停在人工复核（needs_review），
        # 组合流程在无法修订的情况下会走到 settle。两种收尾都算"没骗人"，
        # 真正要守的是：**不许标 succeeded**，且必须留下草稿供复核。
        if outcome == "succeeded":
            failures.append("质检未通过却被标成 succeeded")
        if not observed.get("listing"):
            failures.append("质检未通过必须留下草稿可复核")
        return failures

    if "error_code" in expect:
        actual = observed.get("error_code") or ""
        if actual != expect["error_code"]:
            failures.append(f"错误分类是「{actual or '空'}」，期望「{expect['error_code']}」")
        if outcome != "failed":
            failures.append(f"注入了 {case.fault} 却以 {outcome} 收尾（故障被吞掉了）")
        if observed.get("listing"):
            failures.append("失败的流程不该留下草稿")
        if not observed.get("error_message"):
            failures.append("失败任务没有可读的说明")
    return failures


_CHECKERS = {
    DIM_TOOL_CALL: _check_tool_call,
    DIM_FACT: _check_fact_consistency,
    DIM_COMPLETION: _check_completion,
    DIM_RECOVERY: _check_recovery,
}


def check(case: EvalCase, observed: dict[str, Any]) -> list[str]:
    """跑完之后调用：返回失败理由列表（空 = 通过）。"""
    checker = _CHECKERS.get(case.dimension)
    if checker is None:  # pragma: no cover - 维度是闭集
        return [f"未知维度：{case.dimension}"]
    failures = checker(case, observed)

    # 所有维度共用的底线：不能既没失败、也没有任何结果
    if not failures and observed.get("outcome") in {None, "", "unknown"}:
        failures.append("结局为空：既不是成功也不是失败")
    return failures


__all__ = ["BANNED_TERMS", "check"]
