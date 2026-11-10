"""渐进发现：目录只带描述，命中后才加载正文。

这组测试守住三条边界：
1. 目录接口不返回参数 schema 与正文（否则「渐进」就退化成一次全量拉取）；
2. 有模型时以模型选择为准，模型出错/缺失才关键词兜底且如实标注；
3. 导入的说明型技能同样能被发现，删除后立即从目录消失。
"""

from __future__ import annotations

from surge.skills.discovery import catalog, discover, load_instructions
from surge.skills.registry import SKILL_REGISTRY


def register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


IMPORTED_MD = """---
name: price_guard
title: 价格守门员
description: 当用户要检查定价是否低于成本线时使用。
category: 财务核算
keywords: [定价, 成本线]
---
# 价格守门员

先读取成本，再判断售价是否低于成本线。
"""


class FakeClient:
    def __init__(self, keys):
        self.keys = keys

    def chat_json(self, messages, schema_hint=None, temperature=0.0):
        return {"skill_keys": self.keys}, None


class BrokenClient:
    def chat_json(self, messages, schema_hint=None, temperature=0.0):
        raise RuntimeError("model down")


# ---------------------------------------------------------------------------
# 纯逻辑
# ---------------------------------------------------------------------------


def test_catalog_only_exposes_description():
    entries = catalog(None, "")
    assert {entry.key for entry in entries} == set(SKILL_REGISTRY)
    for entry in entries:
        assert entry.name and entry.description
        assert entry.source == "builtin"


def test_fallback_matches_when_model_is_missing():
    entries = catalog(None, "")
    result = discover("帮我分析这批竞品的价格和评论", entries=entries, client=None)
    assert result.degraded is True
    assert result.items, result
    assert result.items[0].entry.key == "competitor_analysis"
    assert result.items[0].instructions, "命中后应加载 SKILL.md 正文"


def test_model_selection_filters_unknown_keys():
    entries = catalog(None, "")
    result = discover(
        "随便什么目标",
        entries=entries,
        client=FakeClient(["profit_calc", "not_a_skill"]),
    )
    assert result.degraded is False
    assert [item.entry.key for item in result.items] == ["profit_calc"]


def test_model_empty_selection_is_respected():
    entries = catalog(None, "")
    result = discover("你好", entries=entries, client=FakeClient([]))
    assert result.degraded is False
    assert result.items == ()


def test_model_failure_falls_back_and_marks_degraded():
    entries = catalog(None, "")
    result = discover("计算这批货的利润和盈亏", entries=entries, client=BrokenClient())
    assert result.degraded is True
    assert any(item.entry.key == "profit_calc" for item in result.items)


def test_load_body_can_be_deferred():
    entries = catalog(None, "")
    result = discover("竞品分析", entries=entries, client=None, load_body=False)
    assert result.items
    assert all(item.instructions == "" for item in result.items)


def test_load_instructions_rejects_unknown_key():
    assert load_instructions(None, "", "not_a_skill") is None


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


def test_catalog_endpoint_is_lightweight(client):
    headers = register(client, "skill_catalog")
    items = client.get("/api/skills/catalog", headers=headers).json()["items"]
    assert {item["skill_key"] for item in items} == set(SKILL_REGISTRY)
    for item in items:
        assert "input_schema" not in item
        assert "instructions" not in item
        assert item["description"]


def test_discover_endpoint_returns_body_for_hits(client):
    headers = register(client, "skill_discover")
    resp = client.post(
        "/api/skills/discover",
        json={"goal": "帮我看看这批竞品的价格定位和评论痛点"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["degraded"] is True  # 测试环境没有模型，走关键词
    hits = {item["skill_key"]: item for item in body["items"]}
    assert "competitor_analysis" in hits
    assert "## 何时使用" in hits["competitor_analysis"]["instructions"]


def test_imported_skill_is_discoverable_and_removable(client):
    headers = register(client, "skill_discover_import")
    client.post("/api/skills/import", json={"content": IMPORTED_MD}, headers=headers)

    items = client.get("/api/skills/catalog", headers=headers).json()["items"]
    imported = next(item for item in items if item["skill_key"] == "price_guard")
    assert imported["source"] == "imported"
    assert imported["runnable"] is False

    body = client.post(
        "/api/skills/discover",
        json={"goal": "检查这个定价会不会低于成本线"},
        headers=headers,
    ).json()
    hit = next(item for item in body["items"] if item["skill_key"] == "price_guard")
    assert "先读取成本" in hit["instructions"]

    client.delete("/api/skills/price_guard", headers=headers)
    after = client.get("/api/skills/catalog", headers=headers).json()["items"]
    assert all(item["skill_key"] != "price_guard" for item in after)
