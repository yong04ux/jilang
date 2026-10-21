"""演示种子数据（``python -m crosspilot seed-demo``）。

写入什么：
- ``demo`` 账号（仅在配置了 ``CROSSPILOT_DEMO_PASSWORD`` 时创建）及其个人租户；
- 3 份示例竞品报告 + 3 份示例 Listing 草稿 + 若干任务；
- 全部带 ``seed_demo=1`` / ``is_demo=1``，页面显示「示例」徽章。

幂等：重复执行不会重复插入（按固定的种子 ID 判断）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..engine.analysis import run_analysis
from ..persistence.db import Database
from .demo_data import DEMO_ANALYSIS_REQUEST, DEMO_LISTING_REQUEST
from ..engine.listing import generate_listing
from ..models import CompetitorAnalysisRequest, ListingGenerationRequest
from ..llm.providers import RuleProvider
from ..tenancy import create_personal_tenant

#: 固定的种子 ID 前缀，保证幂等
SEED_PREFIX = "seed-"

SEED_PRODUCTS = [
    {
        "name": "EcoSip Insulated Water Bottle",
        "platform": "amazon",
        "marketplace": "US",
        "language": "en-US",
    },
    {
        "name": "PeakTrail Hiking Backpack 40L",
        "platform": "amazon",
        "marketplace": "US",
        "language": "en-US",
    },
    {
        "name": "LumiGlow Desk Lamp Pro",
        "platform": "amazon",
        "marketplace": "US",
        "language": "en-US",
    },
]

#: 英文商品事实：种子 Listing 用英文目标语言，事实也必须英文，
#: 否则质检会（正确地）报「目标语言为英文但文案含中文」。
SEED_PRODUCTS_EN: list[dict[str, Any]] = [
    {
        "name": "EcoSip Insulated Water Bottle",
        "brand": "EcoSip",
        "category": "Sports Water Bottles",
        "specifications": {
            "Capacity": "750 ml",
            "Material": "304 stainless steel",
            "Lid": "Leak-proof silicone seal",
            "Insulation": "Double-wall vacuum",
        },
        "key_features": [
            "Double-wall vacuum insulation keeps drinks cold for 24 hours",
            "One-piece seamless liner resists stains and odours",
            "Wide mouth for easy ice loading and cleaning",
            "Leak-proof silicone gasket tested to 500 open/close cycles",
        ],
        "certifications": [],
        "price": 22.9,
        "target_audience": "Commuters and gym-goers",
    },
    {
        "name": "PeakTrail Hiking Backpack 40L",
        "brand": "PeakTrail",
        "category": "Hiking Backpacks",
        "specifications": {
            "Capacity": "40 L",
            "Weight": "1.2 kg",
            "Fabric": "210D ripstop nylon",
            "Frame": "Internal aluminium stay",
        },
        "key_features": [
            "Adjustable torso length fits 43-53 cm back lengths",
            "Ventilated back panel with four airflow channels",
            "Hydration sleeve fits 3 L reservoirs",
            "Rain cover stowed in the base pocket",
        ],
        "certifications": [],
        "price": 89.0,
        "target_audience": "Day hikers and weekend campers",
    },
    {
        "name": "LumiGlow Desk Lamp Pro",
        "brand": "LumiGlow",
        "category": "Desk Lamps",
        "specifications": {
            "Color temperature": "2700-6500 K",
            "Brightness": "900 lux at 40 cm",
            "Power": "12 W USB-C",
            "Body": "Anodised aluminium",
        },
        "key_features": [
            "Stepless dimming from 5% to 100%",
            "Five colour temperature presets",
            "Memory function restores the last setting",
            "Flicker-free driver rated at 100 Hz or higher",
        ],
        "certifications": [],
        "price": 45.5,
        "target_audience": "Home-office workers and students",
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_demo_user(db: Database, username: str, password: str) -> dict[str, Any]:
    """取得（或创建）demo 账号。未配置密码时退回最早的用户。"""
    if username and password:
        from ..auth import hash_password

        existing = db.get_user_by_username(username)
        if existing is None:
            user_id = uuid.uuid4().hex
            db.create_user(
                user_id, username, hash_password(password),
                display_name="演示账号", is_admin=False,
            )
            create_personal_tenant(db, user_id, username)
            existing = db.get_user(user_id)
        return existing or {}
    users = db.list_users()
    if not users:
        raise RuntimeError(
            "数据库里没有任何用户，且未配置 CROSSPILOT_DEMO_PASSWORD；"
            "请先注册一个账号或设置 demo 密码。"
        )
    return db.get_user(users[0]["user_id"]) or {}


def _tenant_id_for(db: Database, user_id: str) -> str:
    membership = db.get_membership(user_id)
    if membership is not None:
        return membership["tenant_id"]
    return create_personal_tenant(db, user_id, "demo")


def _seed_task(
    db: Database,
    *,
    task_id: str,
    user_id: str,
    tenant_id: str,
    task_type: str,
    title: str,
    status: str,
    output: dict[str, Any],
    created_at: str,
) -> bool:
    """写入一个种子任务；已存在时返回 False（保证幂等）。"""
    if db.get_task_by_id(task_id) is not None:
        return False
    db.create_task(
        {
            "task_id": task_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "origin": "seed",
            "type": task_type,
            "title": title,
            "status": status,
            "input": {"seeded": True},
            "output": output,
            "error_code": None,
            "error_message": None,
            "result_ref": output.get("report_id") or output.get("listing_id"),
            "trace_id": uuid.uuid4().hex[:12],
            "created_at": created_at,
            "started_at": created_at,
            "finished_at": created_at,
            "conversation_id": None,
            "degraded": 0,
        }
    )
    for index, name in enumerate(
        ("生成执行计划", "竞品分析", "数据完整性检查", "生成市场机会总结", "保存报告与任务记录"),
        start=1,
    ):
        db.add_task_step(
            {
                "step_id": uuid.uuid4().hex,
                "task_id": task_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "seq": index,
                "name": name,
                "status": "succeeded",
                "detail": "种子数据：步骤为写入时生成，耗时不可用",
                "started_at": created_at,
                "finished_at": created_at,
                "duration_ms": 0,
            }
        )
    return True


def seed_demo(db: Database, *, demo_username: str = "demo", demo_password: str = "") -> dict[str, Any]:
    """写入演示数据，返回统计。可重复执行。"""
    user = _ensure_demo_user(db, demo_username, demo_password)
    if not user:
        raise RuntimeError("无法确定 demo 账号")
    user_id = user["user_id"]
    tenant_id = _tenant_id_for(db, user_id)

    provider = RuleProvider()
    reports_created = 0
    listings_created = 0
    tasks_created = 0

    base_time = datetime.now(timezone.utc) - timedelta(days=3)

    for index, product in enumerate(SEED_PRODUCTS):
        report_id = f"{SEED_PREFIX}report-{index + 1}"
        task_id = f"{SEED_PREFIX}task-report-{index + 1}"
        created_at = (base_time + timedelta(hours=index * 5)).isoformat()

        request_payload = dict(DEMO_ANALYSIS_REQUEST)
        request_payload["product_name"] = product["name"]
        request_payload["platform"] = product["platform"]
        request_payload["marketplace"] = product["marketplace"]
        request_payload["data_source"] = "demo"
        request = CompetitorAnalysisRequest(**request_payload)
        report = run_analysis(request)

        payload = report.model_dump(mode="json")
        payload["report_id"] = report_id
        payload["created_at"] = created_at

        if db.get_report(report_id, user_id=user_id, tenant_id=tenant_id) is None:
            db.save_report(payload, user_id=user_id, tenant_id=tenant_id, task_id=task_id)
            reports_created += 1

        if _seed_task(
            db,
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
            task_type="competitor_analysis",
            title=f"竞品分析：{product['name']}",
            status="succeeded",
            output={"report_id": report_id, "is_demo": True, "seeded": True},
            created_at=created_at,
        ):
            tasks_created += 1

        # 每份报告配一份示例 Listing（英文事实 + 英文站点，质检才有意义）
        listing_request_payload = json.loads(json.dumps(DEMO_LISTING_REQUEST))
        facts = SEED_PRODUCTS_EN[index]
        listing_request_payload["product"] = {
            **listing_request_payload["product"],
            "name": facts["name"],
            "brand": facts["brand"],
            "category": facts["category"],
            "specifications": facts["specifications"],
            "key_features": facts["key_features"],
            "certifications": facts["certifications"],
            "price": facts["price"],
            "target_audience": facts["target_audience"],
            "marketplace": product["marketplace"],
        }
        listing_request_payload["marketplace"] = product["marketplace"]
        listing_request_payload["language"] = product["language"]
        listing_request = ListingGenerationRequest(**listing_request_payload)
        # 用纯规则引擎（engine="rule"）而不是 rule-fallback：
        # 种子数据不是"模型失败后的降级产物"，不该继承 passed=False 的终态。
        listing = generate_listing(listing_request, analysis_report=payload)
        listing_payload = listing.model_dump(mode="json")
        listing_id = f"{SEED_PREFIX}listing-{index + 1}"
        listing_payload["listing_id"] = listing_id
        listing_payload["created_at"] = created_at
        listing_payload["analysis_report_id"] = report_id
        listing_payload["product_snapshot"] = listing_request.product.model_dump(mode="json")

        if db.get_listing(listing_id, user_id=user_id, tenant_id=tenant_id) is None:
            db.save_listing(
                listing_payload,
                user_id=user_id,
                tenant_id=tenant_id,
                task_id=None,
            )
            listings_created += 1

        listing_task_id = f"{SEED_PREFIX}task-listing-{index + 1}"
        if _seed_task(
            db,
            task_id=listing_task_id,
            user_id=user_id,
            tenant_id=tenant_id,
            task_type="listing_generation",
            title=f"Listing 生成：{product['name']}",
            status="succeeded",
            output={"listing_id": listing_id, "is_demo": True, "seeded": True},
            created_at=created_at,
        ):
            tasks_created += 1

    # 标记种子来源（迁移里加了 seed_demo 列）
    try:
        with db.connect() as connection:
            for table, key in (
                ("competitor_reports", "report_id"),
                ("listing_drafts", "listing_id"),
                ("tasks", "task_id"),
            ):
                connection.execute(
                    f"UPDATE {table} SET seed_demo = 1 WHERE {key} LIKE ?",
                    (f"{SEED_PREFIX}%",),
                )
    except Exception:  # noqa: BLE001 - 标记失败不影响已有数据可用性
        pass

    # 演示店铺：让访问者进「店铺与渠道」就有东西可看（幂等，已同步过的不重复同步）
    from .store_seed import seed_demo_stores

    stores = seed_demo_stores(db, tenant_id, user_id=user_id)

    return {
        "user": user.get("username"),
        "user_id": user_id,
        "tenant_id": tenant_id,
        "reports": reports_created,
        "listings": listings_created,
        "tasks": tasks_created,
        "stores": stores,
        "seeded_at": _now(),
    }


__all__ = ["SEED_PREFIX", "seed_demo"]
