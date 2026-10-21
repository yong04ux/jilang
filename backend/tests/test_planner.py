"""目标解析（planner）测试（阶段 D5）。

不需要真实模型：假客户端覆盖"成功 / 不合规 / 网络失败"三条路径。
"""

from __future__ import annotations


from crosspilot.agent.planner import resolve_goal, rule_resolve
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.messages: list[dict[str, str]] = []
        self.schema_hint = ""

    def chat_json(self, messages, *, schema_hint=None, temperature=None):
        self.messages = messages
        self.schema_hint = schema_hint or ""
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload, None


def test_rule_resolve_extracts_marketplace_and_language():
    spec = rule_resolve("帮我分析 EcoSip 保温杯在日本的竞品，不要生成 Listing")
    assert spec.marketplace == "JP"
    assert spec.listing_language == "ja-JP"
    assert spec.with_listing is False
    assert "EcoSip" in spec.product_name


def test_rule_resolve_prefers_quoted_product_name():
    spec = rule_resolve("分析“Stainless Steel Tumbler 20oz”在美国的竞品并生成英文 Listing")
    assert spec.product_name == "Stainless Steel Tumbler 20oz"
    assert spec.marketplace == "US"
    assert spec.with_listing is True


def test_llm_success_is_not_degraded():
    client = FakeClient(
        {
            "product_name": "EcoSip Insulated Water Bottle",
            "platform": "amazon",
            "marketplace": "DE",
            "category": "水杯",
            "with_listing": False,
            "listing_language": "de-DE",
            "keywords": ["insulated bottle"],
            "notes": "",
        }
    )
    resolution = resolve_goal("分析德国站的 EcoSip 竞品", client=client)
    assert resolution.degraded is False
    assert resolution.reason == ""
    assert resolution.spec.product_name == "EcoSip Insulated Water Bottle"
    assert resolution.spec.marketplace == "DE"
    assert resolution.spec.with_listing is False
    assert client.messages  # 确实调用了模型


def test_llm_invalid_output_falls_back_and_is_marked_degraded():
    client = FakeClient({"marketplace": "US"})  # 缺 product_name
    resolution = resolve_goal("分析 EcoSip 保温杯", client=client)
    assert resolution.degraded is True
    assert "不合规" in resolution.reason
    assert resolution.spec.product_name


def test_llm_failure_falls_back_and_reports_reason():
    client = FakeClient(RuntimeError("network down"))
    resolution = resolve_goal("分析 EcoSip 保温杯", client=client)
    assert resolution.degraded is True
    assert "network down" in resolution.reason


def test_goal_is_scrubbed_before_sending_to_model():
    client = FakeClient({"product_name": "EcoSip", "marketplace": "US"})
    goal = "分析 EcoSip，api_key=sk-should-not-leak-12345678，token=abc"
    resolve_goal(goal, client=client)
    sent = " ".join(message["content"] for message in client.messages)
    assert "sk-should-not-leak-12345678" not in sent
    assert "api_key=***" in sent


def test_resolve_endpoint_without_llm_is_explicitly_degraded(client):
    headers = _register(client, "plan_resolve")
    resp = client.post(
        "/api/agent/resolve",
        json={"goal": "分析“EcoSip Bottle”在日本站的竞品"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["degraded"] is True
    assert body["spec"]["product_name"] == "EcoSip Bottle"
    assert body["spec"]["marketplace"] == "JP"
    assert "规则解析" in body["reason"]


def test_run_with_goal_without_competitors_explains_what_is_missing(client):
    headers = _register(client, "plan_missing")
    resp = client.post(
        "/api/agent/runs",
        json={"goal": "分析“EcoSip Bottle”的竞品并生成 Listing"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["missing"] == ["competitors"]
    assert detail["goal_spec"]["product_name"] == "EcoSip Bottle"
    assert "不会凭空生成" in detail["message"]


def test_run_with_goal_and_data_uses_resolved_parameters(client):
    headers = _register(client, "plan_run")
    resp = client.post(
        "/api/agent/runs",
        json={
            "goal": "分析“EcoSip Insulated Bottle”在美国的竞品并生成英文 Listing",
            "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
            "data_source": "demo",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["degraded"] is True
    assert body["report"]["product_name"] == "EcoSip Insulated Bottle"
    assert body["listing"] is not None
    assert body["plan"] == [
        "analyze",
        "integrity",
        "summary",
        "listing",
        "quality",
        "persist",
    ]


def test_degraded_flag_is_persisted_on_the_task(client):
    headers = _register(client, "plan_task")
    body = client.post(
        "/api/agent/runs",
        json={
            "goal": "分析“EcoSip Bottle”在美国的竞品",
            "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
            "with_listing": False,
            "data_source": "demo",
        },
        headers=headers,
    ).json()
    detail = client.get(f"/api/tasks/{body['task_id']}", headers=headers).json()
    assert detail["task"]["degraded"] == 1
    assert detail["result"]["degraded"] is True
    assert detail["result"]["degraded_reason"]


def _register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}
