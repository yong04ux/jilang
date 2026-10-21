"""生成/分析 Provider 抽象。

- ``DeepSeekProvider`` : 主力实现，调用 DeepSeek 官方 API（OpenAI 兼容接口）；
- ``RuleProvider``     : 无模型降级，事实直出，离线可测。

关键约定：无论走哪个 Provider，产出都要经过同一套事实对齐质检；
模型输出**不被信任**，只作为"候选文案"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..engine.analysis import run_analysis
from ..engine.listing_llm import generate_listing
from .llm import DeepSeekClient, LLMError, normalize_model
from ..models import AnalysisReport, CompetitorAnalysisRequest, ListingDraft, ListingGenerationRequest
from ..engine.rules import RuleSet, get_rules


class ProviderError(RuntimeError):
    """Provider 配置或调用失败（不是业务校验失败）。"""


@dataclass
class ProviderInfo:
    name: str
    available: bool
    detail: str
    verified: bool = False
    model: str = ""
    base_url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = {
            "name": self.name,
            "available": self.available,
            "detail": self.detail,
            "verified": self.verified,
        }
        if self.model:
            data["model"] = self.model
        if self.base_url:
            data["base_url"] = self.base_url
        if self.extra:
            data.update(self.extra)
        return data


@runtime_checkable
class AnalysisProvider(Protocol):
    name: str

    def analyze(self, request: CompetitorAnalysisRequest) -> AnalysisReport: ...


@runtime_checkable
class ListingProvider(Protocol):
    name: str

    def generate(
        self,
        request: ListingGenerationRequest,
        analysis_report: dict[str, Any] | None = None,
    ) -> ListingDraft: ...


# ---------------------------------------------------------------------------
# 规则引擎（无模型）
# ---------------------------------------------------------------------------


class RuleProvider:
    """默认降级 Provider：不需要任何外部服务。"""

    name = "rule"

    def __init__(self, ruleset: RuleSet | None = None, engine_version: str = "0.2.0"):
        self.ruleset = ruleset or get_rules()
        self.engine_version = engine_version
        self.last_usage: dict[str, int] = {}
        self.fallback_reason: str | None = None

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name,
            available=True,
            detail="本地规则引擎：无需 API Key，离线可运行；Listing 为事实直出草案，需人工改写。",
            verified=True,
        )

    def chat_client(self) -> Any | None:
        """返回可用于目标解析的 LLM 客户端；规则引擎没有模型，返回 None。"""
        return None

    def analyze(self, request: CompetitorAnalysisRequest) -> AnalysisReport:
        return run_analysis(request, engine=self.name, engine_version=self.engine_version)

    def generate(
        self,
        request: ListingGenerationRequest,
        analysis_report: dict[str, Any] | None = None,
    ) -> ListingDraft:
        return generate_listing(
            request,
            analysis_report=analysis_report,
            client=None,
            ruleset=self.ruleset,
            engine="rule-fallback",
            engine_version=self.engine_version,
        )


# ---------------------------------------------------------------------------
# DeepSeek
# ---------------------------------------------------------------------------


class DeepSeekProvider(RuleProvider):
    """DeepSeek 官方 API：LLM 生成 + 事实对齐质检。

    竞品分析仍走本地统计（统计必须可复现），LLM 只用于把统计结论组织成
    可读建议——这样"数字"永远来自计算而不是模型。
    """

    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-flash",
        timeout: float = 90.0,
        max_retries: int = 2,
        temperature: float = 0.5,
        thinking: bool = False,
        reasoning_effort: str = "",
        ruleset: RuleSet | None = None,
        engine_version: str = "0.2.0",
    ):
        super().__init__(ruleset=ruleset, engine_version=engine_version)
        self._api_key = api_key
        self.base_url = base_url
        self.model = normalize_model(model)
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort

    def info(self) -> ProviderInfo:
        if not self._api_key:
            return ProviderInfo(
                name=self.name,
                available=False,
                detail="未配置 CROSSPILOT_DEEPSEEK_API_KEY；启动或生成时会降级为 rule。",
                verified=False,
                model=self.model,
                base_url=self.base_url,
            )
        return ProviderInfo(
            name=self.name,
            available=True,
            detail=f"DeepSeek 官方 API（{self.base_url}），模型 {self.model}",
            verified=False,  # 只有真正调用成功才算验证
            model=self.model,
            base_url=self.base_url,
        )

    def _client(self) -> DeepSeekClient:
        return DeepSeekClient(
            api_key=self._api_key,
            base_url=self.base_url,
            model=self.model,
            timeout=self.timeout,
            max_retries=self.max_retries,
            temperature=self.temperature,
            thinking=self.thinking,
            reasoning_effort=self.reasoning_effort or None,
        )

    def chat_client(self) -> Any | None:
        return self._client()

    def generate(
        self,
        request: ListingGenerationRequest,
        analysis_report: dict[str, Any] | None = None,
    ) -> ListingDraft:
        client = self._client()
        draft = generate_listing(
            request,
            analysis_report=analysis_report,
            client=client,
            ruleset=self.ruleset,
            engine=self.name,
            engine_version=self.engine_version,
        )
        self.last_usage = client.usage.as_dict()
        return draft

    def ping(self) -> tuple[bool, str]:
        """最小成本连通性测试：只发一个极小请求。

        失败时**抛异常**而不是返回 ``(False, "...")``：文案（中文提示 vs 厂商原文）
        属于 API 层的事，provider 层只负责把错误如实抛出来。
        """
        client = DeepSeekClient(
            api_key=self._api_key,
            base_url=self.base_url,
            model=self.model,
            timeout=min(self.timeout, 20.0),
            max_retries=0,
        )
        result = client.chat(
            [{"role": "user", "content": "reply with the single word: ok"}],
            max_tokens=8,
            temperature=0,
        )
        return True, f"模型 {result.model} 响应正常（tokens={result.usage.total_tokens}）"


# 兼容旧名
OpenAIProvider = DeepSeekProvider


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------


def _resolve_deepseek_settings(settings) -> tuple[str, str, str]:
    """兼容新旧变量名，返回 (api_key, base_url, model)。"""
    api_key = settings.deepseek_api_key or settings.openai_api_key
    base_url = settings.deepseek_base_url or settings.openai_base_url
    model = settings.deepseek_model or settings.openai_model or "deepseek-flash"
    return api_key, base_url, model


def build_provider(settings, config=None) -> RuleProvider:
    """按配置构建 Provider。

    ``config`` 可传 ``model_settings.EffectiveModelConfig``（每用户配置），
    不传则退回 ``settings`` 的进程级默认值，保持旧调用方式兼容。

    注意：缺少 Key 时返回带 ``fallback_reason`` 的 RuleProvider，**不抛异常**，
    以免健康检查直接失败；但生成结果的 engine 会明确标为 rule-fallback。
    """
    if config is not None:
        kind = (config.provider or "rule").lower()
        api_key = config.api_key
        base_url = config.base_url
        model = config.model
        timeout = config.timeout
        max_retries = config.max_retries
        temperature = config.temperature
        thinking = config.thinking
        reasoning_effort = config.reasoning_effort
    else:
        kind = (settings.provider or "rule").lower()
        api_key, base_url, model = _resolve_deepseek_settings(settings)
        timeout = settings.deepseek_timeout
        max_retries = settings.deepseek_max_retries
        temperature = settings.deepseek_temperature
        thinking = settings.deepseek_thinking
        reasoning_effort = settings.deepseek_reasoning_effort

    if kind == "rule":
        return RuleProvider(engine_version=settings.engine_version)

    if kind in {"deepseek", "openai"}:
        # 用户配了 openai 兼容服务但没填模型时，给一个保守默认，避免直接 400
        model = model or "deepseek-flash"
        provider = DeepSeekProvider(
            api_key=api_key,
            base_url=base_url or "https://api.deepseek.com",
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            temperature=temperature,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            engine_version=settings.engine_version,
        )
        if not api_key:
            fallback = RuleProvider(engine_version=settings.engine_version)
            fallback.fallback_reason = (
                f"provider={kind} 但未配置 API Key，已降级为 rule"
            )
            return fallback
        return provider

    raise ProviderError(f"未知的 provider={kind!r}，可选：deepseek / rule / openai")


def provider_status(settings, config=None) -> dict[str, Any]:
    """/api/health 用的状态汇总，不触发网络调用。"""
    try:
        provider = build_provider(settings, config)
        info = provider.info().as_dict()
    except ProviderError as exc:
        name = config.provider if config is not None else settings.provider
        return {"name": name, "available": False, "detail": str(exc)}
    info["fallback_reason"] = getattr(provider, "fallback_reason", None)
    return info


__all__ = [
    "AnalysisProvider",
    "DeepSeekProvider",
    "ListingProvider",
    "OpenAIProvider",
    "ProviderError",
    "ProviderInfo",
    "RuleProvider",
    "build_provider",
    "provider_status",
]
