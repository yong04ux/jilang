"""按步骤分配模型（task_overrides）：校验、读取形状、按节点解析、运行时生效。

设计约束（见 docs/12-task-overrides.md）：
- 只有 ``listing`` 会调 LLM，其他节点配了也要拒绝。
  （``analyze`` 2026-10-27 起也归入"其他节点"：它是纯统计，从不调模型，
  原来的配置入口永远不生效，已按用户决定移除。）
- override 指向同用户的另一套配置，Key / base_url 复用，不新增密钥副本；
- override 失效（配置被删/禁用）时回落激活配置，不抛错。
"""

from __future__ import annotations

import uuid

import pytest

from crosspilot.agent.runtime import create_agent_task, execute_agent
from crosspilot.config import get_settings
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST
from crosspilot.llm.provider_configs import (
    ProviderConfigError,
    ProviderConfigService,
)
from crosspilot.llm.providers import build_provider
from crosspilot.llm.step_providers import build_step_providers
from crosspilot.persistence.secrets import SecretBox


def register(client, username: str) -> dict[str, str]:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def identity(client, headers: dict[str, str]) -> dict[str, str]:
    body = client.get("/api/tenants/current", headers=headers).json()
    return {"user_id": body["user_id"], "tenant_id": body["tenant_id"]}


def service_of(client) -> ProviderConfigService:
    settings = get_settings()
    secrets = SecretBox(settings.resolve_path(settings.data_dir) / ".secret_key")
    return ProviderConfigService(
        db=client.app.state.db, secrets=secrets, settings=settings
    )


def save_config(
    client, headers, *, label: str, model: str, key: str, config_id: str | None = None,
    task_overrides=None,
):
    payload = {
        "provider": "deepseek",
        "label": label,
        "model": model,
        "api_key": key,
    }
    if config_id:
        payload["config_id"] = config_id
        payload.pop("api_key")  # 更新时留空表示保持原 Key
    if task_overrides is not None:
        payload["task_overrides"] = task_overrides
    resp = client.post("/api/settings/providers", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["config"]


def activate(client, headers, config_id: str) -> None:
    resp = client.post(
        f"/api/settings/providers/{config_id}/activate", headers=headers
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 校验（写入期严格）
# ---------------------------------------------------------------------------


def test_unknown_node_is_rejected(client):
    headers = register(client, "ov_node")
    resp = client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek",
            "label": "主",
            "model": "deepseek-flash",
            "api_key": "sk-test-1234567890",
            "task_overrides": {"summary": {"model": "gpt-4o"}},
        },
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "summary" in resp.text


def test_empty_spec_and_empty_model_are_rejected(client):
    headers = register(client, "ov_empty")
    for bad in ({"listing": {}}, {"listing": {"model": "   "}}, {"analyze": "x"}):
        resp = client.post(
            "/api/settings/providers",
            json={
                "provider": "deepseek",
                "label": "主",
                "model": "deepseek-flash",
                "api_key": "sk-test-1234567890",
                "task_overrides": bad,
            },
            headers=headers,
        )
        assert resp.status_code == 400, resp.text


def test_bad_model_name_is_rejected(client):
    headers = register(client, "ov_model")
    resp = client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek",
            "label": "主",
            "model": "deepseek-flash",
            "api_key": "sk-test-1234567890",
            "task_overrides": {"listing": {"model": "bad model!"}},
        },
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "模型名" in resp.text


def test_foreign_config_id_is_rejected(client):
    headers_a = register(client, "ov_owner")
    b_cfg = save_config(
        client, headers_a, label="别人的", model="deepseek-flash", key="sk-bbb-1234567890"
    )

    headers_b = register(client, "ov_other")
    resp = client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek",
            "label": "主",
            "model": "deepseek-flash",
            "api_key": "sk-aaa-1234567890",
            "task_overrides": {"listing": {"config_id": b_cfg["config_id"]}},
        },
        headers=headers_b,
    )
    assert resp.status_code == 400, resp.text
    assert "不属于当前账号" in resp.text


def test_rule_config_cannot_be_override_target(client):
    headers = register(client, "ov_rule")
    # 直接落一条 rule 配置：走接口会被 "rule 不需要 Key" 的校验挡住构造路径
    db = client.app.state.db
    ident = identity(client, headers)
    config_id = uuid.uuid4().hex
    db.save_provider_config(
        {
            "config_id": config_id,
            "user_id": ident["user_id"],
            "provider": "rule",
            "label": "规则",
            "base_url": "",
            "model": "",
            "api_key_encrypted": None,
            "enabled": 1,
            "last_tested_at": None,
            "last_test_ok": None,
            "last_test_detail": None,
            "task_overrides": "{}",
        }
    )
    resp = client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek",
            "label": "主",
            "model": "deepseek-flash",
            "api_key": "sk-aaa-1234567890",
            "task_overrides": {"listing": {"config_id": config_id}},
        },
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "rule" in resp.text


# ---------------------------------------------------------------------------
# 读取形状：对象而不是 JSON 字符串
# ---------------------------------------------------------------------------


def test_task_overrides_are_returned_as_object(client):
    headers = register(client, "ov_shape")
    strong = save_config(
        client, headers, label="强力档", model="deepseek-reasoner", key="sk-strong-123456"
    )
    cheap = save_config(
        client,
        headers,
        label="便宜档",
        model="deepseek-flash",
        key="sk-cheap-1234567",
        task_overrides={"listing": {"config_id": strong["config_id"]}},
    )
    body = client.get("/api/settings/providers", headers=headers).json()
    item = next(i for i in body["items"] if i["config_id"] == cheap["config_id"])
    assert item["task_overrides"] == {"listing": {"config_id": strong["config_id"]}}
    # 没配的那套是空对象，不是字符串 "{}"
    plain = next(i for i in body["items"] if i["config_id"] == strong["config_id"])
    assert plain["task_overrides"] == {}


# ---------------------------------------------------------------------------
# 按节点解析与运行时生效
# ---------------------------------------------------------------------------


def test_step_providers_resolve_override(client):
    headers = register(client, "ov_resolve")
    ident = identity(client, headers)
    strong = save_config(
        client, headers, label="强力档", model="deepseek-reasoner", key="sk-strong-123456"
    )
    cheap = save_config(
        client,
        headers,
        label="便宜档",
        model="deepseek-flash",
        key="sk-cheap-1234567",
        task_overrides={"listing": {"config_id": strong["config_id"]}},
    )
    activate(client, headers, cheap["config_id"])

    providers = build_step_providers(
        client.app.state.db, get_settings(), ident["user_id"]
    )
    listing_provider, listing_note = providers["listing"]

    # 只有 listing 会按节点取模型。analyze 不调模型，2026-10-27 起不再支持覆盖，
    # 因此它压根不该出现在结果里。
    assert "analyze" not in providers
    assert listing_provider.model
    assert "override" in listing_note


def test_override_falls_back_when_target_disabled(client):
    headers = register(client, "ov_fallback")
    ident = identity(client, headers)
    strong = save_config(
        client, headers, label="强力档", model="deepseek-reasoner", key="sk-strong-123456"
    )
    cheap = save_config(
        client,
        headers,
        label="便宜档",
        model="deepseek-flash",
        key="sk-cheap-1234567",
        task_overrides={"listing": {"config_id": strong["config_id"]}},
    )
    activate(client, headers, cheap["config_id"])

    # 停用被引用的配置：任务不该因此失败，而是回落
    db = client.app.state.db
    config_id = strong["config_id"]
    db.delete_provider_config(ident["user_id"], config_id)

    providers = build_step_providers(
        client.app.state.db, get_settings(), ident["user_id"]
    )
    listing_provider, listing_note = providers["listing"]
    # 「已回落」这个标注本身就是回落分支产出的，断言它等于断言回落发生了
    assert "已回落" in listing_note
    # 回落后拿到的是激活配置（便宜档）的模型，不是被删掉的那套
    assert listing_provider.model
    assert "analyze" not in providers


class RecordingProvider:
    """记录被哪个节点调用过，内部仍走 rule 引擎（不发网络请求）。"""

    def __init__(self, tag: str, inner) -> None:
        self.tag = tag
        self.inner = inner
        self.calls: list[str] = []

    def analyze(self, request):
        self.calls.append("analyze")
        return self.inner.analyze(request)

    def generate(self, request, report_payload):
        self.calls.append("generate")
        return self.inner.generate(request, report_payload)


def test_execute_agent_uses_listing_provider_only(client):
    """端到端：只有 listing 会取按节点配置的 Provider。

    ``analyze`` 是纯统计（``engine.analysis.run_analysis``），从不调模型，
    所以给它传 Provider 必须**没有任何效果**。这条断言是 2026-10-27
    「不给 analyze 配模型」这一决定的回归保护——一旦有人把 analyze 改回
    "调模型"而没同步这里，测试会立刻失败。
    """
    headers = register(client, "ov_runtime")
    ident = identity(client, headers)
    db = client.app.state.db

    rule = build_provider(get_settings(), None)
    analyze_fake = RecordingProvider("analyze-档", rule)
    listing_fake = RecordingProvider("listing-档", rule)

    payload = {
        "product_name": "EcoSip Insulated Water Bottle",
        "platform": "amazon",
        "marketplace": "US",
        # 没有事实就会被 Phase 3 的子图拦在"等待补充资料"，生成根本不会发生
        "own_specs": {"容量": "750ml"},
        "own_key_features": ["双层真空保温"],
        "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
        "with_listing": True,
        "data_source": "demo",
    }
    recorder = create_agent_task(
        db=db,
        user_id=ident["user_id"],
        tenant_id=ident["tenant_id"],
        payload=payload,
        title="按步骤分配模型",
    )
    execute_agent(
        recorder,
        db=db,
        provider=rule,
        payload=payload,
        providers={"analyze": (analyze_fake, "A"), "listing": (listing_fake, "B")},
    )

    assert analyze_fake.calls == []  # 传了也不会被调用
    assert listing_fake.calls == ["generate"]

    detail = client.get(f"/api/tasks/{recorder.task_id}", headers=headers).json()
    steps = {step.get("node"): step for step in detail["steps"]}
    # 统计节点（竞品分析）不该带模型标注
    assert "A" not in (steps["run_analysis"]["detail"] or "")
    # 生成节点带上了按节点分配的那套配置说明
    assert "B" in steps["run_listing"]["detail"]
    # 其它节点不该带 Listing 的模型标注
    assert "B" not in (steps["settle"]["detail"] or "")


def test_a_service_rejects_non_object_overrides(client):
    headers = register(client, "ov_type")
    ident = identity(client, headers)
    service = service_of(client)
    for bad in ("not-json", 123, ["listing"], {"listing": {"model": "ok"}} | {"bad": {}}):
        with pytest.raises(ProviderConfigError):
            service.validate_task_overrides(ident["user_id"], bad)
