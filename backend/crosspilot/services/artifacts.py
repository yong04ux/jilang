"""业务产物持久化：Graph 节点不再直接写库。

如果 ``persist`` 节点在 ``agent/runtime.py`` 里直接调 ``db.save_report`` /
``db.save_listing``，会有三个后果：

1. 节点即事务边界——想调整保存顺序或加校验，得改工作流；
2. 租户/用户为空时会静默写入一条无主数据，没有统一守卫；
3. 谁来保存这件事散落在节点里，将来组合工作流要么复制一份，要么绕过它。

这里把「保存什么、按什么顺序、缺上下文怎么办」收拢成一个函数。
节点只负责调用它并收尾任务状态。

**幂等**
========================

严格幂等需要唯一约束，仅靠保存前查一下在**并发**下并不成立；但重试与断点
续跑是**顺序**发生的，同一个任务会把结果重算一遍再保存一次，这是更常见的一半。
所以这里做的是「同一任务的产物复用」：

- 保存前按 ``(task_id, tenant_id)`` 找这个任务已有的产物；
- 找到就沿用**原 id**，靠 ``ON CONFLICT(id) DO UPDATE`` 覆盖内容。

效果：重试不会新增一条重复的报告/草稿，界面不会并排出现两份一样的结果。
**仍然不是并发安全**——两个请求同时跑同一任务时仍可能各插一条。
那条路要靠 ``(task_id, kind)`` 唯一索引或任务级互斥，属于后续工作，
写在这里是为了不让"已做幂等"这句话被误读成"并发也安全"。
"""

from __future__ import annotations

from typing import Any

from ..persistence.db import Database


class ArtifactError(RuntimeError):
    """保存产物失败（配置/上下文问题，不是数据问题）。"""


def save_run_artifacts(
    db: Database,
    *,
    tenant_id: str,
    user_id: str,
    task_id: str | None,
    report: dict[str, Any] | None = None,
    listing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把一次运行的报告与草稿写入业务表，返回产物引用。

    只写**调用方明确给出**的产物：报告为空就不写报告，草稿为空就不写草稿。
    不会为了"结构完整"生成空记录。
    """
    if not tenant_id:
        # 不落无主数据：多租户下这条记录以后谁都查不到，等于静默丢数据
        raise ArtifactError("缺少租户上下文，不能写入业务产物")
    if not user_id:
        raise ArtifactError("缺少用户上下文，不能写入业务产物")
    if not report and not listing:
        return {"report_id": None, "listing_id": None}

    if report is not None and not isinstance(report, dict):
        raise ArtifactError("报告数据格式不正确")
    if listing is not None and not isinstance(listing, dict):
        raise ArtifactError("草稿数据格式不正确")

    saved: dict[str, Any] = {"report_id": None, "listing_id": None}

    if report:
        # 同一任务复用原报告 id：重试不该在列表里留下第二份一样的报告
        if task_id:
            existing = db.find_report_by_task(task_id, tenant_id)
            if existing and existing.get("report_id"):
                report = {**report, "report_id": existing["report_id"]}
        db.save_report(
            report,
            user_id=user_id,
            tenant_id=tenant_id,
            task_id=task_id,
        )
        saved["report_id"] = report.get("report_id")

    if listing:
        # 草稿同理：幂等判断统一放在这一层，节点里不要再各写一份
        if task_id:
            existing_listing = db.find_listing_by_task(task_id, tenant_id)
            if existing_listing and existing_listing.get("listing_id"):
                listing = {**listing, "listing_id": existing_listing["listing_id"]}
        db.save_listing(
            listing,
            user_id=user_id,
            tenant_id=tenant_id,
            task_id=task_id,
        )
        saved["listing_id"] = listing.get("listing_id")

    return saved


__all__ = ["ArtifactError", "save_run_artifacts"]
