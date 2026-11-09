"""Agent 能力路由：显式选择优先，未选择时按目标自动挑技能。

守住三件事：
1. 显式 skill_key 决定执行语义，且不能绕过参数校验（专属技能明确拒绝）；
2. 自动路由只映射到现有工作流开关，不改执行图；
3. 模型/关键词选错时不把用户显式给的参数覆盖掉。
"""

from __future__ import annotations

from crosspilot.agent.routing import decide
from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST
from crosspilot.skills.discovery import catalog


class FakeClient:
    def __init__(self, keys):
        self.keys = keys

    def chat_json(self, messages, schema_hint=None, temperature=0.0):
        return {"skill_keys": self.keys}, None


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


ENTRIES = catalog(None, "")


# ---------------------------------------------------------------------------
# 纯路由
# ---------------------------------------------------------------------------


def test_explicit_competitor_only_analysis():
    decision = decide(
        skill_key="competitor_analysis", goal="随便", entries=ENTRIES
    )
    assert decision.mode == "explicit"
    assert decision.with_listing is False
    assert decision.listing_only is False
    assert decision.skill_keys == ("competitor_analysis",)


def test_explicit_listing_skips_competitors():
    decision = decide(
        skill_key="listing_generation", goal="随便", entries=ENTRIES
    )
    assert decision.with_listing is True
    assert decision.listing_only is True


def test_auto_listing_only_when_no_competitor_skill():
    decision = decide(
        skill_key=None,
        goal="帮我写一份英文 Listing 文案",
        entries=ENTRIES,
        client=FakeClient(["listing_generation"]),
    )
    assert decision.mode == "auto"
    assert decision.with_listing is True
    assert decision.listing_only is True


def test_auto_combined_when_listing_and_competitor():
    decision = decide(
        skill_key=None,
        goal="分析竞品并写 Listing",
        entries=ENTRIES,
        client=FakeClient(["competitor_analysis", "listing_generation"]),
    )
    assert decision.with_listing is True
    assert decision.listing_only is False


def test_auto_competitor_implies_no_listing():
    decision = decide(
        skill_key=None,
        goal="分析竞品价格",
        entries=ENTRIES,
        client=FakeClient(["competitor_analysis"]),
    )
    assert decision.with_listing is False
    assert decision.listing_only is False


def test_auto_respects_explicit_with_listing():
    decision = decide(
        skill_key=None,
        goal="分析竞品价格",
        entries=ENTRIES,
        client=FakeClient(["competitor_analysis"]),
        with_listing_explicit=True,
    )
    assert decision.with_listing is None


def test_auto_model_empty_changes_nothing():
    decision = decide(
        skill_key=None,
        goal="你好",
        entries=ENTRIES,
        client=FakeClient([]),
    )
    assert decision.mode == "auto"
    assert decision.with_listing is None
    assert decision.listing_only is None


def test_auto_unsupported_skill_is_blocked_with_guidance():
    decision = decide(
        skill_key=None,
        goal="算一下这批货的利润和盈亏",
        entries=ENTRIES,
        client=FakeClient(["profit_calc"]),
    )
    assert decision.mode == "unsupported"
    assert decision.with_listing is None
    assert "专属参数" in decision.note


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


def test_explicit_unsupported_skill_is_rejected(client):
    headers = register(client, "route_unsupported")
    resp = client.post(
        "/api/agent/runs",
        json={
            "agent_key": "main",
            "skill_key": "market_summary",
            "product_name": "测试商品",
            "competitors": DEMO_ANALYSIS_REQUEST["competitors"],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert "专属参数" in resp.text


def test_explicit_competitor_runs_without_listing_steps(client):
    headers = register(client, "route_explicit")
    payload = dict(DEMO_ANALYSIS_REQUEST)
    payload.pop("locale", None)
    payload.update({"agent_key": "main", "skill_key": "competitor_analysis"})
    resp = client.post("/api/agent/runs", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["routing"]["mode"] == "explicit"
    assert [item["skill_key"] for item in body["selected_skills"]] == [
        "competitor_analysis"
    ]
    assert "run_listing" not in body["plan"]


def test_auto_routing_uses_goal_when_no_skill_selected(client):
    headers = register(client, "route_auto")
    payload = dict(DEMO_ANALYSIS_REQUEST)
    payload.pop("locale", None)
    payload.update(
        {
            "agent_key": "main",
            "goal": "只分析这批竞品的价格定位",
        }
    )
    # 明确不给 with_listing / skill_key：让 Agent 按目标决定
    payload.pop("with_listing", None)
    resp = client.post("/api/agent/runs", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["routing"]["mode"] == "auto"
    assert any(
        item["skill_key"] == "competitor_analysis" for item in body["selected_skills"]
    )
    assert "run_listing" not in body["plan"]
