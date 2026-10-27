"""竞品数据 Provider（Phase 2 · 计划 §9）测试。

核心验收：
1. 用户导入的数据是唯一可用来源，显式行优先于导入批次；
2. 批次按租户隔离，别人的批次当作不存在（不区分"不存在"与"不属于你"）；
3. **Live 未接入就必须报错**，绝不返回导入数据冒充实采。
"""

from __future__ import annotations

import pytest

from crosspilot.agent import tools
from crosspilot.market.competitor_provider import (
    MODE_IMPORTED,
    MODE_LIVE,
    SOURCE_IMPORT,
    SOURCE_MANUAL,
    CompetitorProviderError,
    CompetitorQuery,
    ImportedCompetitorProvider,
    LiveCompetitorProvider,
    ProviderNotConfigured,
    build_competitor_provider,
)

ROWS = [{"name": "Rival A", "price": 19.9}, {"name": "Rival B", "price": 24.5}]


class FakeDb:
    """只实现 Provider 用到的那一个方法，顺手记录被查询时的租户。"""

    def __init__(self, batches: dict[str, dict]) -> None:
        self.batches = batches
        self.asked: list[tuple[str, str]] = []

    def get_import_batch(self, batch_id: str, tenant_id: str | None = None):
        self.asked.append((batch_id, tenant_id or ""))
        return self.batches.get(batch_id)


# ---------------------------------------------------------------------------
# 导入：唯一可用来源
# ---------------------------------------------------------------------------


def test_explicit_rows_win_over_batch():
    db = FakeDb({"batch-1": {"competitors": [{"name": "from batch"}]}})
    provider = ImportedCompetitorProvider(db, "t1")

    data = provider.fetch(CompetitorQuery(product_name="X", batch_id="batch-1", rows=ROWS))

    assert data.rows == ROWS
    assert data.source == SOURCE_MANUAL
    assert db.asked == []  # 有显式行就不该去查库


def test_batch_rows_are_used_and_labelled_as_import():
    db = FakeDb({"batch-1": {"competitors": ROWS}})
    provider = ImportedCompetitorProvider(db, "t1")

    data = provider.fetch(CompetitorQuery(product_name="X", batch_id="batch-1"))

    assert data.rows == ROWS
    assert data.source == SOURCE_IMPORT
    assert data.fetched_at  # 获取时间必须带上
    assert db.asked == [("batch-1", "t1")]  # 租户上下文必须传下去


def test_batch_of_another_tenant_looks_absent():
    """不区分"不存在"与"不属于你"——区分等于泄露别人有没有这个 id。"""
    db = FakeDb({})
    provider = ImportedCompetitorProvider(db, "t1")

    data = provider.fetch(CompetitorQuery(product_name="X", batch_id="batch-of-t2"))

    assert data.rows == []
    assert data.notes == ["导入批次不存在或不属于当前空间"]


def test_no_source_at_all_returns_empty_with_reason():
    provider = ImportedCompetitorProvider(FakeDb({}), "t1")
    data = provider.fetch(CompetitorQuery(product_name="X"))

    assert data.empty is True
    assert data.notes  # 必须说明为什么没有数据，而不是静默空数组


def test_batch_rows_marked_demo_propagate():
    db = FakeDb({"batch-1": {"competitors": [{"name": "A", "is_demo": True}]}})
    data = ImportedCompetitorProvider(db, "t1").fetch(
        CompetitorQuery(product_name="X", batch_id="batch-1")
    )
    assert data.is_demo is True


# ---------------------------------------------------------------------------
# Live：未接入就必须报错，绝不回退
# ---------------------------------------------------------------------------


def test_live_without_credentials_says_not_connected():
    provider = LiveCompetitorProvider(FakeDb({}), "t1")
    with pytest.raises(ProviderNotConfigured) as exc:
        provider.fetch(CompetitorQuery(product_name="X"))
    assert "导入" in str(exc.value)  # 告诉用户当前能用什么替代


def test_live_with_credentials_still_refuses_instead_of_faking_data():
    """关键：配了凭据也不能返回任何数据——真实接口压根没接。"""
    provider = LiveCompetitorProvider(
        FakeDb({"batch-1": {"competitors": ROWS}}),
        "t1",
        connection={"credentials": {"app_id": "x"}},
    )
    assert provider.configured is True
    with pytest.raises(ProviderNotConfigured):
        provider.fetch(CompetitorQuery(product_name="X", batch_id="batch-1"))


def test_factory_refuses_unknown_mode():
    with pytest.raises(CompetitorProviderError):
        build_competitor_provider("telepathy", db=FakeDb({}), tenant_id="t1")


def test_factory_returns_imported_by_default():
    provider = build_competitor_provider(db=FakeDb({}), tenant_id="t1")
    assert provider.mode == MODE_IMPORTED
    assert build_competitor_provider(MODE_LIVE, db=FakeDb({}), tenant_id="t1").mode == MODE_LIVE


# ---------------------------------------------------------------------------
# Tool 层不再自己实现一遍来源判断
# ---------------------------------------------------------------------------


def test_tool_read_data_asset_delegates_to_provider():
    """``agent.tools.read_data_asset`` 保持原签名，但实现只剩 Provider 一份。"""
    db = FakeDb({"batch-1": {"competitors": ROWS}})
    assert tools.read_data_asset(db, "t1", batch_id="batch-1") == ROWS
    assert tools.read_data_asset(db, "t1", competitors=ROWS, batch_id="batch-1") == ROWS
    assert tools.read_data_asset(db, "t1") == []


# ---------------------------------------------------------------------------
# 接进 HTTP：坏批次要变成"缺输入"，而不是 500
# ---------------------------------------------------------------------------


def _register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def test_unknown_import_batch_becomes_missing_input(client):
    headers = _register(client, "cp_batch_missing")
    resp = client.post(
        "/api/agent/runs",
        json={
            "agent_key": "main",
            "product_name": "EcoSip Bottle",
            "import_batch_id": "batch-does-not-exist",
            "with_listing": False,
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["category"] == "missing_input"
