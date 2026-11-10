"""技能协议层：注册表本身的结构与接口契约。

这一组断言的作用是「守住真源」：只要有人再手写第二份技能清单
（例如塞进 ``agent/registry.py``），这里就会先红。
"""

from __future__ import annotations

from surge.skills import SKILL_REGISTRY
from surge.skills.base import RENDERERS, SkillSpec

EXPECTED_KEYS = {
    "competitor_analysis",
    "data_validation",
    "listing_generation",
    "listing_quality",
    "market_summary",
    "profit_calc",
    "review_mining",
}


def register(client, username: str) -> dict:
    resp = client.post("/api/auth/register", json={"username": username, "password": "password123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


def test_registry_has_exactly_the_seven_promised_skills():
    assert set(SKILL_REGISTRY) == EXPECTED_KEYS


def test_offline_skill_is_not_in_registry():
    """没有实现的能力不上架。"""
    assert "keyword_layout" not in SKILL_REGISTRY


def test_every_spec_is_complete():
    for key, spec in SKILL_REGISTRY.items():
        assert isinstance(spec, SkillSpec)
        assert spec.key == key
        assert spec.name and spec.category and spec.summary
        assert callable(spec.executor)
        assert spec.renderer in RENDERERS
        assert isinstance(spec.requires, tuple)
        assert isinstance(spec.credits, int) and spec.credits >= 0
        assert spec.output_schema.get("type") == "object"
        assert spec.status == "available"


def test_listing_generation_is_model_optional():
    """Listing 不把模型当硬依赖：没 Key 用规则引擎，界面标明引擎即可。"""
    spec = SKILL_REGISTRY["listing_generation"]
    assert spec.uses_llm is True
    assert "llm" not in spec.requires


def test_every_input_model_generates_a_form_schema():
    """前端表单由 ``model_json_schema()`` 生成，出不来就等于这一页没法填。"""
    for key, spec in SKILL_REGISTRY.items():
        schema = spec.inputs.model_json_schema()
        assert schema.get("type") == "object", key
        assert schema.get("properties"), key


# ---------------------------------------------------------------------------
# 读接口
# ---------------------------------------------------------------------------


def test_list_skills_is_generated_from_registry(client):
    headers = register(client, "skill_list")
    items = client.get("/api/skills", headers=headers).json()["items"]

    keys = {item["skill_key"] for item in items}
    assert keys == EXPECTED_KEYS

    sample = next(item for item in items if item["skill_key"] == "competitor_analysis")
    # 既有字段必须保留：工作台与旧页面都在读它们
    for field in ("skill_key", "name", "summary", "input_schema", "output_schema", "status"):
        assert field in sample
    # 协议层新增字段
    assert sample["category"] == "竞品与Listing"
    assert sample["renderer"] == "report"
    assert sample["runnable"] is True
    assert sample["input_schema"]["properties"]


def test_retired_skill_detail_is_404(client):
    """老库里可能还留着 keyword_layout 的内置行，读接口必须挡住。"""
    headers = register(client, "skill_retired")
    assert client.get("/api/skills/keyword_layout", headers=headers).status_code == 404
    assert client.get("/api/skills/not_a_skill", headers=headers).status_code == 404
