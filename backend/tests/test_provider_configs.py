"""多厂商 LLM 配置（M4）：白名单、加密、激活、掩码、demo 账号限制。"""
# check_secrets: allow-placeholders — 本文件的 API Key 都是构造的假值

from __future__ import annotations

import pytest

from crosspilot.llm.provider_configs import (
    ProviderConfigError,
    validate_base_url,
)


def register(client, username="alice") -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ---------------------------------------------------------------------------
# base_url 白名单（纯函数）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider,url",
    [
        ("deepseek", "https://api.deepseek.com"),
        ("openai", "https://api.openai.com/v1"),
        ("moonshot", "https://api.moonshot.cn/v1"),
        ("zhipu", "https://open.bigmodel.cn/api/paas/v4"),
        ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("siliconflow", "https://api.siliconflow.cn/v1"),
        ("openrouter", "https://openrouter.ai/api/v1"),
        ("ollama", "http://127.0.0.1:11434/v1"),
    ],
)
def test_preset_domains_are_allowed(provider, url):
    assert validate_base_url(provider, url, allow_custom=False) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://127.0.0.1:8080/v1",
        "https://evil.example.com/v1",
        "http://10.0.0.5/v1",
    ],
)
def test_foreign_hosts_are_rejected_for_presets(url):
    with pytest.raises(ProviderConfigError):
        validate_base_url("deepseek", url, allow_custom=False)


def test_custom_provider_requires_explicit_opt_in():
    with pytest.raises(ProviderConfigError) as exc:
        validate_base_url("custom", "https://my-llm.example.com/v1", allow_custom=False)
    assert "自定义" in str(exc.value)
    assert (
        validate_base_url("custom", "https://my-llm.example.com/v1", allow_custom=True)
        == "https://my-llm.example.com/v1"
    )


def test_custom_provider_cannot_target_internal_networks():
    with pytest.raises(ProviderConfigError):
        validate_base_url("custom", "http://192.168.1.10/v1", allow_custom=True)
    with pytest.raises(ProviderConfigError):
        validate_base_url("custom", "http://169.254.169.254/v1", allow_custom=True)


def test_rule_provider_needs_no_url():
    assert validate_base_url("rule", "", allow_custom=False) == ""


def test_missing_url_falls_back_to_preset_default():
    assert validate_base_url("deepseek", "", allow_custom=False) == "https://api.deepseek.com"


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


def test_list_providers_returns_presets(client):
    headers = register(client, "prov_list")
    body = client.get("/api/settings/providers", headers=headers).json()
    keys = {preset["key"] for preset in body["presets"]}
    # OpenAI 兼容那批 + 走原生协议的两家 + 自定义
    assert keys == {
        "deepseek", "openai", "anthropic", "google",
        "moonshot", "zhipu", "dashscope", "siliconflow", "openrouter",
        "ollama", "custom",
    }
    assert body["items"] == []
    assert body["active_config_id"] is None
    assert "rule" in body["providers"]
    assert "OpenAI" in body["note"]
    assert "Anthropic" in body["note"]


def test_save_config_masks_key_and_never_leaks_plaintext(client):
    headers = register(client, "prov_save")
    plaintext = "sk-very-secret-key-abcdef123456"
    resp = client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek",
            "label": "主 Key",
            "api_key": plaintext,
            "model": "deepseek-flash",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert plaintext not in resp.text, "接口回传了明文 Key"
    config = resp.json()["config"]
    assert config["api_key_masked"] == "sk-****3456"
    assert config["has_api_key"] is True
    assert config["base_url"] == "https://api.deepseek.com"
    # 账号的第一套配置会被自动激活（否则访客保存完仍是 428，见下方 auto_activate 测试）
    assert config["is_active"] is True


def test_first_config_is_activated_automatically(client):
    """演示站动线：保存第一套 Key 之后应当能直接跑，不用再找「设为当前」。

    否则访客看到「保存成功」却仍然 428，第一次使用就卡在这一步。
    """
    headers = register(client, "prov_autoact")
    first = client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek",
            "label": "我的 Key",
            "api_key": "sk-test-1234567890",
            "model": "deepseek-flash",
        },
        headers=headers,
    ).json()["config"]
    assert first["is_active"] is True
    assert client.get("/api/settings/providers", headers=headers).json()[
        "active_config_id"
    ] == first["config_id"]

    # 第二套配置不抢当前选择：多配置场景下用户的显式选择优先
    second = client.post(
        "/api/settings/providers",
        json={
            "provider": "openai",
            "label": "备用 Key",
            "api_key": "sk-test-1234567890",
            "model": "gpt-4o-mini",
        },
        headers=headers,
    ).json()["config"]
    assert second["is_active"] is False
    assert client.get("/api/settings/providers", headers=headers).json()[
        "active_config_id"
    ] == first["config_id"]


def test_base_url_whitelist_is_enforced_through_api(client):
    headers = register(client, "prov_ssrf")
    resp = client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek",
            "label": "evil",
            "api_key": "sk-test-1234567890",
            "model": "deepseek-flash",
            "base_url": "http://169.254.169.254/v1",
        },
        headers=headers,
    )
    assert resp.status_code == 400
    assert "只允许" in resp.json()["detail"]


def test_duplicate_label_is_rejected(client):
    headers = register(client, "prov_dup")
    payload = {
        "provider": "deepseek",
        "label": "默认",
        "api_key": "sk-test-1234567890",
        "model": "deepseek-flash",
    }
    assert client.post("/api/settings/providers", json=payload, headers=headers).status_code == 200
    second = client.post("/api/settings/providers", json=payload, headers=headers)
    assert second.status_code == 400
    assert "同标签" in second.json()["detail"]


def test_activate_switches_effective_provider(client):
    headers = register(client, "prov_activate")
    created = client.post(
        "/api/settings/providers",
        json={
            "provider": "moonshot",
            "label": "Kimi",
            "api_key": "sk-test-1234567890",
            "model": "moonshot-v1-8k",
        },
        headers=headers,
    ).json()["config"]
    assert client.post(
        f"/api/settings/providers/{created['config_id']}/activate", json={}, headers=headers
    ).status_code == 200

    health = client.get("/api/health", headers=headers).json()
    assert health["configured_model"]["provider"] == "moonshot"
    assert health["provider"]["name"] == "moonshot"

    listing = client.get("/api/settings/providers", headers=headers).json()
    assert listing["active_config_id"] == created["config_id"]
    assert listing["items"][0]["is_active"] is True


def test_delete_active_config_falls_back(client):
    headers = register(client, "prov_delete")
    first = client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek", "label": "A",
            "api_key": "sk-test-1234567890", "model": "deepseek-flash",
        },
        headers=headers,
    ).json()["config"]
    second = client.post(
        "/api/settings/providers",
        json={
            "provider": "openai", "label": "B",
            "api_key": "sk-test-1234567890", "model": "gpt-4o-mini",
        },
        headers=headers,
    ).json()["config"]
    client.post(f"/api/settings/providers/{first['config_id']}/activate", json={}, headers=headers)
    resp = client.delete(f"/api/settings/providers/{first['config_id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["active_config_id"] == second["config_id"]


def test_delete_unknown_config_is_404(client):
    headers = register(client, "prov_404")
    assert client.delete("/api/settings/providers/nope", headers=headers).status_code == 404


def test_key_is_encrypted_in_database(client):
    headers = register(client, "prov_encrypted")
    plaintext = "sk-should-not-be-in-db-123456"
    client.post(
        "/api/settings/providers",
        json={
            "provider": "deepseek", "label": "enc",
            "api_key": plaintext, "model": "deepseek-flash",
        },
        headers=headers,
    )
    import psycopg

    from pg_support import database_url

    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            "SELECT api_key_encrypted FROM user_provider_configs"
        ).fetchone()
    assert row is not None
    stored = row[0] or ""
    assert plaintext not in stored
    assert stored.startswith("v1:")


def test_missing_key_is_rejected(client):
    headers = register(client, "prov_nokey")
    resp = client.post(
        "/api/settings/providers",
        json={"provider": "deepseek", "label": "none", "model": "deepseek-flash"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "API Key" in resp.json()["detail"]


def test_demo_account_cannot_save_provider_config(client, monkeypatch):
    from crosspilot.config import get_settings

    monkeypatch.setenv("CROSSPILOT_DEMO_PASSWORD", "demo-pass-1234")
    get_settings.cache_clear()
    try:
        from pg_support import database_url, reset_schema

        reset_schema(database_url())
        # 重新建 app 才会创建 demo 账号
        from fastapi.testclient import TestClient

        from crosspilot.app import create_app

        app = create_app()
        with TestClient(app) as fresh:
            login = fresh.post(
                "/api/auth/login",
                json={"username": "demo", "password": "demo-pass-1234"},
            )
            assert login.status_code == 200, login.text
            headers = {"Authorization": f"Bearer {login.json()['token']}"}
            resp = fresh.post(
                "/api/settings/providers",
                json={
                    "provider": "deepseek", "label": "x",
                    "api_key": "sk-test-1234567890", "model": "deepseek-flash",
                },
                headers=headers,
            )
            assert resp.status_code == 403
            assert "共享" in resp.json()["detail"]
    finally:
        get_settings.cache_clear()


def test_provider_test_failure_shows_chinese_hint_not_vendor_raw():
    """连通性测试失败时，给访客看中文提示；厂商原文只放 raw 字段。

    演示站里访客看到 ``Error code: 401 - {'error': {...}}`` 会一头雾水。
    """
    from crosspilot.api.settings import _test_failure
    from crosspilot.llm.llm import LLMError

    hint, raw = _test_failure(
        LLMError(
            "API Key 无效或无权限：Error code: 401 - {'error': {'code': 'invalid_api_key'}}",
            kind="auth",
        )
    )
    assert "Key" in hint
    assert "401" not in hint and "invalid_api_key" not in hint
    assert "401" in raw

    # 未知类型也要给一句能看懂的兜底
    hint2, _ = _test_failure(ValueError("boom"))
    assert hint2 and "boom" not in hint2


# ---------------------------------------------------------------------------
# 选模型：预置候选 + 现场读取可用模型
# ---------------------------------------------------------------------------


def test_presets_expose_common_models():
    """预置表要带上候选模型名，设置页的下拉才有货。"""
    from crosspilot.llm.provider_configs import PRESET_BY_KEY, provider_presets

    presets = provider_presets()
    deepseek = next(p for p in presets if p["key"] == "deepseek")
    assert deepseek["default_model"] == "deepseek-flash"
    assert "deepseek-flash" in deepseek["common_models"]
    # 每个预置厂商都要有 common_models 字段（哪怕是空列表），前端不用判空
    assert all("common_models" in p for p in presets)
    # 本地 Ollama 装了什么模型只有用户自己知道，不该预设
    assert PRESET_BY_KEY["ollama"].common_models == ()


def test_list_models_requires_key(client):
    headers = register(client, "model_list_nokey")
    resp = client.post(
        "/api/settings/providers/models",
        json={"provider": "deepseek"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Key" in resp.json()["detail"]


def test_list_models_rejects_rule_provider(client):
    headers = register(client, "model_list_rule")
    resp = client.post(
        "/api/settings/providers/models",
        json={"provider": "rule"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "规则引擎" in resp.json()["detail"]


def test_list_models_returns_provider_catalog(client, monkeypatch):
    """拿到的是服务端返回的清单，不是本地硬编码那份。"""
    from crosspilot.llm.providers import DeepSeekProvider

    monkeypatch.setattr(
        DeepSeekProvider,
        "list_models",
        lambda self: ["deepseek-flash", "deepseek-v4-pro"],
    )
    headers = register(client, "model_list_ok")
    resp = client.post(
        "/api/settings/providers/models",
        json={"provider": "deepseek", "api_key": "sk-fake-1234567890"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "deepseek"
    assert body["items"] == ["deepseek-flash", "deepseek-v4-pro"]
    assert body["count"] == 2


def test_list_models_reports_auth_failure_in_chinese(client, monkeypatch):
    """读取失败要给中文原因，不能把 SDK 异常原文甩给访客。"""
    from crosspilot.llm.llm import LLMError
    from crosspilot.llm.providers import DeepSeekProvider

    def boom(self):
        raise LLMError("Error code: 401 - invalid_api_key", kind="auth")

    monkeypatch.setattr(DeepSeekProvider, "list_models", boom)
    headers = register(client, "model_list_auth")
    resp = client.post(
        "/api/settings/providers/models",
        json={"provider": "openai", "api_key": "sk-fake-1234567890"},
        headers=headers,
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "Key" in detail
    assert "401" not in detail and "invalid_api_key" not in detail
