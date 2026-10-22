"""API 与配置层测试：健康检查、分析/生成接口、错误处理、持久化。"""

from __future__ import annotations

import json

from crosspilot.demo.demo_data import (
    DEMO_ANALYSIS_REQUEST,
    DEMO_LISTING_REQUEST,
    DEMO_OWN_PRODUCT_SPARSE,
)


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "provider" in data
    assert data["provider"]["name"] in {"rule", "openai"}


def test_index_page_serves_spa_shell(client):
    """单一前端：根路径返回外壳，由前端路由渲染页面。"""
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "激浪" in body
    assert "/js/app.js" in body
    assert 'id="view-root"' in body


def test_spa_routes_serve_the_same_shell(client):
    """前端路由的深链必须能直接打开，不能 404。"""
    for path in ("/workbench", "/dashboard", "/tasks", "/tasks/tsk_1", "/skills", "/stores"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert 'id="view-root"' in response.text, path


def test_legacy_ui_is_gone(client):
    """旧版工作台已下线，不再提供 /legacy 与 /static 资源。"""
    assert client.get("/legacy").status_code == 404
    assert client.get("/static/app.js").status_code == 404


def test_frontend_assets_are_served(client):
    """前端依赖 /css 与 /js 两个挂载点。"""
    for path in ("/css/tokens.css", "/js/app.js", "/js/pages/workbench.js", "/js/render.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.text.strip(), path


def test_demo_dataset_is_flagged(client):
    response = client.get("/api/demo/dataset")
    assert response.status_code == 200
    data = response.json()
    assert data["is_demo"] is True
    assert "demo" in data["notice"].lower() or "模拟" in data["notice"]
    assert len(data["competitors"]) >= 2


def test_analyze_endpoint_returns_report_and_persists(auth_client):
    response = auth_client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST)
    assert response.status_code == 200
    data = response.json()
    report = data["report"]
    assert report["report_id"]
    assert data["persisted"] is True
    assert report["data_provenance"]["is_demo"] is True

    # 持久化后可通过 GET 取回
    fetched = auth_client.get(f"/api/reports/{report['report_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["report_id"] == report["report_id"]

    listing = auth_client.get("/api/reports")
    assert listing.status_code == 200
    assert any(item["report_id"] == report["report_id"] for item in listing.json()["items"])


def test_analyze_endpoint_rejects_invalid_payload(auth_client):
    payload = json.loads(json.dumps(DEMO_ANALYSIS_REQUEST))
    payload["competitors"] = []
    response = auth_client.post("/api/analyze", json=payload)
    assert response.status_code == 422


def test_analyze_endpoint_reports_field_level_errors(auth_client):
    payload = json.loads(json.dumps(DEMO_ANALYSIS_REQUEST))
    payload["product_name"] = ""
    response = auth_client.post("/api/analyze", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("商品名称" in err["field"] for err in detail["errors"])


def test_validate_endpoint(auth_client):
    response = auth_client.post("/api/analyze/validate", json=DEMO_ANALYSIS_REQUEST)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["review_samples"] == 17


def test_listing_endpoint_with_report_id(auth_client):
    analysis = auth_client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST).json()
    report_id = analysis["report"]["report_id"]

    payload = json.loads(json.dumps(DEMO_LISTING_REQUEST))
    payload["analysis_report_id"] = report_id
    response = auth_client.post("/api/listings/generate", json=payload)
    assert response.status_code == 200
    listing = response.json()["listing"]
    assert listing["analysis_report_id"] == report_id
    assert listing["title"]
    assert listing["quality_check"]["rules_applied"]


def test_listing_endpoint_unknown_report_id_404(auth_client):
    payload = json.loads(json.dumps(DEMO_LISTING_REQUEST))
    payload["analysis_report_id"] = "does-not-exist"
    response = auth_client.post("/api/listings/generate", json=payload)
    assert response.status_code == 404


def test_listing_endpoint_sparse_product_does_not_invent_specs(auth_client):
    payload = json.loads(json.dumps(DEMO_LISTING_REQUEST))
    payload["product"] = DEMO_OWN_PRODUCT_SPARSE
    response = auth_client.post("/api/listings/generate", json=payload)
    assert response.status_code == 200
    listing = response.json()["listing"]
    combined = listing["title"] + listing["description"] + " ".join(b["body"] for b in listing["bullets"])
    assert "750ml" not in combined
    assert listing["pending_confirmations"]
    codes = {i["code"] for i in listing["quality_check"]["issues"]}
    assert "missing_fact" in codes


def test_listing_endpoint_rejects_missing_product_name(auth_client):
    payload = json.loads(json.dumps(DEMO_LISTING_REQUEST))
    payload["product"]["name"] = ""
    response = auth_client.post("/api/listings/generate", json=payload)
    assert response.status_code == 422


def test_listing_endpoint_rejects_unknown_fields(auth_client):
    payload = json.loads(json.dumps(DEMO_LISTING_REQUEST))
    payload["unexpected_field"] = 1
    response = auth_client.post("/api/listings/generate", json=payload)
    assert response.status_code == 422


def test_platform_rules_endpoint(auth_client):
    response = auth_client.get("/api/platform-rules/amazon/US")
    assert response.status_code == 200
    data = response.json()
    assert data["title_max_chars"] == 200
    assert data["verified"] is False
    assert data["disclaimer"]


def test_ebay_title_limit_is_configured(auth_client):
    response = auth_client.get("/api/platform-rules/ebay/US")
    assert response.status_code == 200
    assert response.json()["title_max_chars"] == 80


def test_ban_lists_endpoint(auth_client):
    response = auth_client.get("/api/ban-lists")
    assert response.status_code == 200
    data = response.json()
    assert data["categories"]
    assert data["disclaimer"]


def test_listings_history_endpoint(auth_client):
    response = auth_client.post("/api/listings/generate", json=DEMO_LISTING_REQUEST)
    assert response.status_code == 200
    listing_id = response.json()["listing"]["listing_id"]

    items = auth_client.get("/api/listings").json()["items"]
    assert any(item["listing_id"] == listing_id for item in items)
    detail = auth_client.get(f"/api/listings/{listing_id}")
    assert detail.status_code == 200
    assert detail.json()["listing_id"] == listing_id


def test_db_isolated_between_tests(auth_client):
    """每个测试使用独立的临时数据库，不应看到其他测试的数据。"""
    assert auth_client.get("/api/reports").json()["items"] == []


def test_llm_failure_degrades_and_is_flagged(auth_client, monkeypatch):
    """DeepSeek 调用失败时降级为事实直出，但必须明确标注，不能假装成功。"""
    from crosspilot.config import get_settings

    monkeypatch.setenv("CROSSPILOT_PROVIDER", "deepseek")
    monkeypatch.setenv("CROSSPILOT_DEEPSEEK_API_KEY", "sk-placeholder")
    monkeypatch.setenv("CROSSPILOT_DEEPSEEK_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("CROSSPILOT_DEEPSEEK_TIMEOUT", "2")
    monkeypatch.setenv("CROSSPILOT_DEEPSEEK_MAX_RETRIES", "0")
    get_settings.cache_clear()
    try:
        response = auth_client.post("/api/listings/generate", json=DEMO_LISTING_REQUEST)
        assert response.status_code == 200
        listing = response.json()["listing"]
        assert listing["engine"] == "rule-fallback"
        assert listing["quality_check"]["passed"] is False
        assert any("降级" in r for r in listing["quality_check"]["rules_applied"])
    finally:
        get_settings.cache_clear()


def test_provider_error_returns_503(auth_client, monkeypatch):
    """Provider 不可用必须明确 503，不能假装成功返回结果。

    注入点选在 ``build_provider``，与具体 provider 种类无关：
    将来增删 provider 不会让这条防护失去覆盖。
    """
    import crosspilot.api.analyses as analyses_mod
    from crosspilot.llm.providers import ProviderError

    def boom(*args, **kwargs):
        raise ProviderError("模型不可用（测试注入）")

    monkeypatch.setattr(analyses_mod, "build_provider", boom)
    response = auth_client.post("/api/analyze", json=DEMO_ANALYSIS_REQUEST)
    assert response.status_code == 503
    assert "模型不可用" in response.json()["detail"]
