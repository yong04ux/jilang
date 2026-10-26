"""多厂商接入：OpenAI 兼容一批 + Anthropic / Google 原生协议一批。

这一层的契约是「上层感知不到厂商差异」：无论哪家，Provider 都只暴露
``chat`` / ``chat_json`` / ``list_models``，异常都收口成 ``LLMError``。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from crosspilot.llm.langchain_client import (
    NATIVE_PROVIDERS,
    LangChainChatClient,
    _text_of,
    _to_langchain_messages,
)
from crosspilot.llm.llm import DeepSeekClient, LLMError, create_chat_client
from crosspilot.llm.provider_configs import (
    ALLOWED_PROVIDERS,
    PRESET_BY_KEY,
    ProviderConfigError,
    validate_base_url,
)
from crosspilot.llm.providers import build_provider


# ---------------------------------------------------------------------------
# 预置表与白名单
# ---------------------------------------------------------------------------


def test_native_providers_are_registered():
    """Anthropic / Google 要在预置表里，设置页的厂商下拉才有它们。"""
    assert {"anthropic", "google"} <= set(PRESET_BY_KEY)
    assert "anthropic" in ALLOWED_PROVIDERS and "google" in ALLOWED_PROVIDERS
    # 原生协议的这两家不该被当成 OpenAI 兼容
    assert set(NATIVE_PROVIDERS) == {"anthropic", "google"}


@pytest.mark.parametrize(
    "provider,url",
    [
        ("anthropic", "https://api.anthropic.com"),
        ("google", "https://generativelanguage.googleapis.com"),
    ],
)
def test_native_hosts_are_whitelisted(provider, url):
    assert validate_base_url(provider, url, allow_custom=False) == url.rstrip("/")


def test_native_providers_reject_foreign_hosts():
    for provider in ("anthropic", "google"):
        with pytest.raises(ProviderConfigError):
            validate_base_url(provider, "https://evil.example.com", allow_custom=False)


def test_google_has_no_hardcoded_model_names():
    """Gemini 的模型名更新频繁，不预设，让用户点「读取可用模型」现场拿。"""
    assert PRESET_BY_KEY["google"].common_models == ()
    assert PRESET_BY_KEY["google"].default_model == ""


# ---------------------------------------------------------------------------
# 客户端工厂
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["anthropic", "google"])
def test_native_providers_get_langchain_client(provider):
    client = create_chat_client(
        provider,
        api_key="sk-fake-1234567890",
        base_url=PRESET_BY_KEY[provider].base_url,
        model="whatever",
    )
    assert isinstance(client, LangChainChatClient)


@pytest.mark.parametrize(
    "provider", ["deepseek", "openai", "moonshot", "zhipu", "dashscope", "custom", "ollama"]
)
def test_openai_compatible_providers_keep_one_client(provider):
    """其余厂商仍共用一个 OpenAI 兼容客户端，不该为每家写适配器。"""
    client = create_chat_client(
        provider, api_key="sk-fake-1234567890", base_url="https://example.com/v1"
    )
    assert isinstance(client, DeepSeekClient)


def test_build_provider_routes_native_vendor():
    from crosspilot.config import get_settings
    from crosspilot.llm.model_settings import EffectiveModelConfig

    settings = get_settings()
    config = EffectiveModelConfig(
        provider="anthropic",
        model="claude-sonnet-5-5",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-fake-1234567890",
        temperature=0.4,
        max_tokens=None,
        timeout=30.0,
        max_retries=0,
        thinking=False,
        reasoning_effort="",
    )
    provider = build_provider(settings, config)
    assert provider.name == "anthropic"
    assert isinstance(provider.chat_client(), LangChainChatClient)
    # 界面文案要用厂商名，不是内部 key
    assert "Claude" in provider.info().detail


def test_native_client_requires_key():
    with pytest.raises(LLMError) as exc:
        LangChainChatClient(provider="anthropic", api_key="", model="m")
    assert exc.value.kind == "no_key"


# ---------------------------------------------------------------------------
# 消息与响应翻译
# ---------------------------------------------------------------------------


def test_messages_are_translated_to_langchain_types():
    converted = _to_langchain_messages(
        [
            {"role": "system", "content": "你是选品助手"},
            {"role": "user", "content": "帮我写标题"},
        ]
    )
    assert [type(m).__name__ for m in converted] == ["SystemMessage", "HumanMessage"]
    assert converted[0].content == "你是选品助手"


def test_content_blocks_are_flattened():
    """Anthropic 的 content 是内容块列表，不是字符串。"""
    assert _text_of([{"type": "text", "text": "标题"}, "草稿"]) == "标题草稿"
    assert _text_of("纯文本") == "纯文本"


class _FakeModel:
    """替身模型：不发网络请求，只记录被怎么调用。"""

    def __init__(self, content: str):
        self.content = content
        self.bound: dict = {}

    def bind(self, **kwargs):
        self.bound.update(kwargs)
        return self

    def invoke(self, messages):
        return AIMessage(
            content=self.content,
            usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            response_metadata={"model_name": "claude-sonnet-5-5", "stop_reason": "end_turn"},
        )


def _client_with(content: str, provider: str = "anthropic") -> LangChainChatClient:
    client = LangChainChatClient(provider=provider, api_key="sk-fake-1234567890", model="m")
    client._model = _FakeModel(content)  # noqa: SLF001 - 测试里换掉真实的模型对象
    return client


def test_chat_translates_usage_and_model():
    client = _client_with("hello")
    result = client.chat([{"role": "user", "content": "hi"}], max_tokens=64, temperature=0.2)
    assert result.content == "hello"
    assert result.model == "claude-sonnet-5-5"
    assert result.finish_reason == "end_turn"
    # 用量要记进累计账，成本核算才准
    assert result.usage.prompt_tokens == 11
    assert client.usage.total_tokens == 18


def test_chat_json_strips_code_fence():
    client = _client_with('```json\n{"title": "无线耳机"}\n```')
    data, _ = client.chat_json([{"role": "user", "content": "给我 JSON"}], schema_hint="title")
    assert data == {"title": "无线耳机"}


def test_unknown_exception_is_classified_not_leaked():
    class Boom(Exception):
        pass

    client = LangChainChatClient(provider="google", api_key="k", model="m")
    err = client._classify(Boom("socket hang up"))  # noqa: SLF001
    assert isinstance(err, LLMError)
    assert err.kind == "unknown"


# ---------------------------------------------------------------------------
# 顶栏状态：测试通过后必须显示「已验证」
# ---------------------------------------------------------------------------


def _save_dashscope_config(client, headers, *, model: str = "qwen3.7-plus") -> str:
    resp = client.post(
        "/api/settings/providers",
        json={
            "provider": "dashscope",
            "label": "默认",
            "model": model,
            "api_key": "sk-fake-1234567890",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["config"]["config_id"]


def _register(client, username: str) -> dict:
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def test_health_reports_verified_after_successful_test(client, monkeypatch):
    """用户点了「测试」且通过，顶栏就不该再说「未验证」。"""
    from crosspilot.llm.providers import DeepSeekProvider

    # 打桩 ping，避开真实网络调用；测试接口本身照常走
    monkeypatch.setattr(DeepSeekProvider, "ping", lambda self: (True, "响应正常"))
    headers = _register(client, "health_verified")
    config_id = _save_dashscope_config(client, headers)

    before = client.get("/api/health", headers=headers).json()["provider"]
    assert before["available"] is True
    assert before["verified"] is False

    tested = client.post(
        f"/api/settings/providers/{config_id}/test", headers=headers
    )
    assert tested.status_code == 200 and tested.json()["ok"] is True

    after = client.get("/api/health", headers=headers).json()["provider"]
    assert after["verified"] is True
    assert after["model"] == "qwen3.7-plus"


def test_health_reports_unverified_after_failed_test(client, monkeypatch):
    from crosspilot.llm.llm import LLMError
    from crosspilot.llm.providers import DeepSeekProvider

    def boom(self):
        raise LLMError("Error code: 401 - invalid_api_key", kind="auth")

    monkeypatch.setattr(DeepSeekProvider, "ping", boom)
    headers = _register(client, "health_unverified")
    config_id = _save_dashscope_config(client, headers)
    client.post(f"/api/settings/providers/{config_id}/test", headers=headers)

    provider = client.get("/api/health", headers=headers).json()["provider"]
    assert provider["available"] is True
    assert provider["verified"] is False


# ---------------------------------------------------------------------------
# 回归：配好 Key 的用户不该被当成「降级」
# ---------------------------------------------------------------------------


def _enable_byok(monkeypatch) -> None:
    """conftest 默认把 BYOK 关掉；这两个用例必须打开才能验到网关。"""
    from crosspilot.config import get_settings

    monkeypatch.setenv("CROSSPILOT_REQUIRE_API_KEY", "true")
    get_settings.cache_clear()


def test_configured_user_is_not_treated_as_fallback(client, monkeypatch):
    """曾经这里用 isinstance(provider, RuleProvider) 判断降级。

    但 ``DeepSeekProvider`` 继承自 ``RuleProvider``，于是**每一家真实厂商**
    都被判成降级，配好 Key 的用户点「开始执行」一律 428——整条主流程跑不动。
    正确判据是「纯粹的规则引擎」，不是「是不是 RuleProvider 的子类」。
    """
    from crosspilot.llm.providers import DeepSeekProvider

    class _FakeClient:
        def chat_json(self, messages, **kwargs):
            return ({"product_name": "EcoSip 保温杯", "with_listing": True}, None)

    monkeypatch.setattr(DeepSeekProvider, "chat_client", lambda self: _FakeClient())
    headers = _register(client, "flow_not_fallback")
    _save_dashscope_config(client, headers)
    _enable_byok(monkeypatch)

    resp = client.post(
        "/api/agent/resolve",
        json={"goal": "给 EcoSip 保温杯写一份英文 Listing"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["degraded"] is False
    assert body["spec"]["product_name"] == "EcoSip 保温杯"


def test_user_without_key_gets_rules_engine_not_a_wall(client, monkeypatch):
    """没有 Key 不再拦人：照样解析目标，但要说清是规则推断的。"""
    headers = _register(client, "flow_no_key")
    _enable_byok(monkeypatch)
    resp = client.post(
        "/api/agent/resolve", json={"goal": "随便写个 Listing"}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is True
    assert body["reason"]
