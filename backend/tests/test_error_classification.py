"""统一错误分类（Phase 2 · 计划 §7.3）测试。

要点：
1. 分类由**异常类型**决定，不靠猜消息；
2. 面向用户的文案里不出现异常类名、路径、环境变量；
3. 分类结论要能一路贯到任务记录与 HTTP 状态码。
"""

from __future__ import annotations

import pytest

from crosspilot.agent import errors
from crosspilot.agent.contracts import (
    SkillDependencyMissing,
    SkillForbidden,
    SkillInputInvalid,
    SkillNotExecutable,
)
from crosspilot.agent.errors import ErrorCategory
from crosspilot.llm.llm import LLMError
from crosspilot.persistence.db import DatabaseError
from crosspilot.services.competitor_service import AnalysisInputError
from crosspilot.services.tasks import TaskCancelled


# ---------------------------------------------------------------------------
# 分类本身
# ---------------------------------------------------------------------------


def test_unknown_exception_is_internal_and_hides_technical_text():
    info = errors.classify(RuntimeError("boom at /srv/secret/app.py line 42"))

    assert info.category is ErrorCategory.INTERNAL_ERROR
    assert info.http_status == 500
    assert info.retryable is False
    # 面向用户的文案不能泄漏异常类名与路径
    assert "RuntimeError" not in info.message
    assert "secret" not in info.message
    # 原始文本只留在日志字段里
    assert "RuntimeError" in info.log_message


def test_cancelled_is_control_flow_not_failure():
    info = errors.classify(TaskCancelled("用户取消"))
    assert info.category is ErrorCategory.CANCELLED
    assert info.http_status == 409
    assert info.task_code == "cancelled"


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("rate_limit", ErrorCategory.RATE_LIMITED),
        ("network", ErrorCategory.MODEL_TIMEOUT),
        ("auth", ErrorCategory.PROVIDER_UNAVAILABLE),
        ("bad_request", ErrorCategory.VALIDATION_ERROR),
        ("server", ErrorCategory.PROVIDER_UNAVAILABLE),
        ("invalid_json", ErrorCategory.MODEL_OUTPUT_INVALID),
        ("empty", ErrorCategory.MODEL_OUTPUT_INVALID),
        ("unknown", ErrorCategory.INTERNAL_ERROR),
    ],
)
def test_llm_error_kinds_map_to_categories(kind, expected):
    info = errors.classify(LLMError("x", kind=kind))
    assert info.category is expected


def test_invalid_model_key_is_not_retryable_and_points_to_settings():
    info = errors.classify(LLMError("401", kind="auth"))
    assert info.retryable is False
    assert info.user_action == "open_settings"


def test_missing_llm_dependency_is_a_config_problem():
    """缺模型 Key 不是"服务挂了"，用户需要去设置页，而不是等一会儿重试。"""
    info = errors.classify(
        SkillDependencyMissing("需要模型", detail={"missing": ["llm"]})
    )
    assert info.category is ErrorCategory.PROVIDER_UNAVAILABLE
    assert info.retryable is False
    assert info.user_action == "open_settings"
    assert info.code == "llm_not_configured"


def test_skill_input_error_carries_field_names():
    info = errors.classify(
        SkillInputInvalid("参数不合法", detail={"errors": [{"field": "competitors", "message": "必填"}]})
    )
    assert info.category is ErrorCategory.VALIDATION_ERROR
    assert info.http_status == 422
    assert info.as_payload()["errors"][0]["field"] == "competitors"


def test_skill_not_executable_is_a_choice_problem():
    info = errors.classify(SkillNotExecutable("尚未实现执行器"))
    assert info.category is ErrorCategory.VALIDATION_ERROR
    assert info.user_action == "choose_skill"


def test_forbidden_is_permission_denied():
    info = errors.classify(SkillForbidden("无权限"))
    assert info.category is ErrorCategory.PERMISSION_DENIED
    assert info.http_status == 403


def test_analysis_input_error_is_validation():
    info = errors.classify(AnalysisInputError(["缺少竞品"], ["样本偏少"]))
    assert info.category is ErrorCategory.VALIDATION_ERROR


def test_database_error_is_retryable_but_never_leaks_dsn():
    info = errors.classify(
        DatabaseError("无法连接 postgresql://user:pw@db.internal:5432/app")
    )
    assert info.category is ErrorCategory.PROVIDER_UNAVAILABLE
    assert info.retryable is True
    assert info.code == "database_unavailable"
    assert "pw" not in info.message
    assert "db.internal" not in info.message


def test_payload_is_flat_for_the_frontend():
    """前端只读 detail.errors 这一层，再套一层就拿不到字段名。"""
    info = errors.make(
        ErrorCategory.VALIDATION_ERROR,
        message="参数不合法",
        detail={"errors": [{"field": "x", "message": "必填"}]},
    )
    payload = info.as_payload()
    assert "errors" in payload
    assert "detail" not in payload
    assert payload["category"] == "validation_error"
    assert payload["retryable"] is False


def test_task_code_is_the_category_not_the_class_name():
    assert errors.classify(ValueError("x")).task_code == "validation_error"
    assert errors.classify(RuntimeError("x")).task_code == "internal_error"


# ---------------------------------------------------------------------------
# 一路贯到 HTTP 与任务记录
# ---------------------------------------------------------------------------


def _register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _payload(**overrides) -> dict:
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    payload = {
        "agent_key": "main",
        "product_name": "EcoSip Insulated Water Bottle",
        "platform": "amazon",
        "marketplace": "US",
        "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
        "with_listing": False,
        "data_source": "demo",
    }
    payload.update(overrides)
    return payload


def test_missing_competitors_is_missing_input_not_validation(client):
    """缺数据 ≠ 参数写错：两者的引导动作不同。"""
    headers = _register(client, "err_missing")
    resp = client.post("/api/agent/runs", json=_payload(competitors=[]), headers=headers)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["category"] == "missing_input"
    assert detail["missing"] == ["competitors"]
    assert detail["action"] == "provide_input"


def test_rate_limited_model_call_maps_to_429_and_persists_category(client, monkeypatch):
    """最贵的一类失败：模型限流必须让任务记成 rate_limited，而不是"未知错误"。

    打桩点在 Provider 而不是 ``agent.skills``：Phase 3 起 Listing 生成走子图，
    链路是 ``子图 → provider.generate``，不再经过 ``skills.generate_listing``。
    """
    from crosspilot.llm.providers import RuleProvider

    def boom(*args, **kwargs):
        raise LLMError("429 too many requests", kind="rate_limit")

    monkeypatch.setattr(RuleProvider, "generate", boom)
    headers = _register(client, "err_ratelimit")
    resp = client.post(
        "/api/agent/runs",
        json=_payload(
            with_listing=True,
            own_specs={"容量": "750ml"},
            own_key_features=["双层真空保温"],
        ),
        headers=headers,
    )
    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["category"] == "rate_limited"
    assert detail["retryable"] is True

    tasks = client.get("/api/tasks", headers=headers).json()["items"]
    failed = next(t for t in tasks if t["status"] == "failed")
    assert failed["error_code"] == "rate_limited"
