"""DeepSeek 官方 API 客户端封装。

设计要点：
- 只依赖 openai SDK（DeepSeek 提供 OpenAI 兼容接口），不引入额外框架；
- 重试、超时、错误分类集中在这里，业务代码不感知网络细节；
- 记录 token 用量，便于成本核算；
- JSON 模式严格校验，失败可重试（LLM 偶尔会包 ```json 围栏）。

模型名以官方文档为准：``deepseek-flash`` 是当前推荐名（由 V4.1-Flash 服务），
``deepseek-v4-pro`` 为增强版本；``deepseek-v4-flash`` 等旧名仍被接受但已退役。
详见 https://api-docs.deepseek.com/
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from . import telemetry

# 官方文档给出的当前模型名
DEFAULT_MODEL = "deepseek-flash"
MODEL_ALIASES = {
    # 旧名 -> 当前推荐名（保持向后兼容，避免老配置直接失效）
    "deepseek-chat": "deepseek-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-v4-flash-vision-exp": "deepseek-flash",
}
KNOWN_MODELS = ("deepseek-flash", "deepseek-v4-pro")


class LLMError(RuntimeError):
    """LLM 调用失败（网络、鉴权、限流、响应不合规等）。"""

    def __init__(self, message: str, *, kind: str = "unknown", retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.calls += 1

    def merge(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.calls += other.calls

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "calls": self.calls,
        }


def normalize_model(model: str) -> str:
    """把旧模型名映射到当前可用名，未知模型原样返回（由服务端裁决）。"""
    key = (model or "").strip().lower()
    return MODEL_ALIASES.get(key, key or DEFAULT_MODEL)


def _strip_json_fence(text: str) -> str:
    """LLM 有时会返回 ```json ... ``` 围栏，这里剥掉。"""
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return cleaned


def parse_json_response(text: str) -> dict[str, Any]:
    """解析 LLM 返回的 JSON，失败抛出可重试的 LLMError。"""
    if not text or not text.strip():
        raise LLMError("LLM 返回空内容", kind="empty", retryable=True)
    candidate = _strip_json_fence(text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # 尝试截取第一个 { 到最后一个 }
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LLMError(f"LLM 返回的不是合法 JSON: {candidate[:200]}", kind="invalid_json", retryable=True) from exc
        else:
            raise LLMError(f"LLM 返回的不是合法 JSON: {candidate[:200]}", kind="invalid_json", retryable=True)
    if not isinstance(data, dict):
        raise LLMError(f"LLM 返回的 JSON 根节点不是对象: {type(data).__name__}", kind="invalid_json", retryable=True)
    return data


@dataclass
class ChatResult:
    content: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    finish_reason: str | None = None


class DeepSeekClient:
    """对 openai SDK 的薄封装，提供重试、超时与 JSON 输出。"""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.deepseek.com",
        model: str = DEFAULT_MODEL,
        timeout: float = 90.0,
        max_retries: int = 2,
        temperature: float = 0.4,
        thinking: bool = False,
        reasoning_effort: str | None = None,
    ):
        if not api_key:
            raise LLMError(
                "未配置 DeepSeek API Key。请在 .env 中设置 CROSSPILOT_DEEPSEEK_API_KEY，"
                "或切换 CROSSPILOT_PROVIDER=rule 使用本地规则引擎。",
                kind="no_key",
                retryable=False,
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = normalize_model(model)
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.temperature = temperature
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.usage = Usage()
        self._client = None
        # 遥测用的厂商标识；由 Provider 在构造后按需覆盖
        self.provider_kind = "deepseek"

    def _sdk(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise LLMError(
                "使用 DeepSeek Provider 需要安装 openai 包：pip install openai",
                kind="missing_dependency",
            ) from exc
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,  # 重试由本类控制，便于记录与分类
        )
        return self._client

    def _classify(self, exc: Exception) -> LLMError:
        """把 SDK 异常映射成带 kind 的 LLMError，便于上层决定是否降级。"""
        name = type(exc).__name__
        text = str(exc)
        if name in {"AuthenticationError", "PermissionDeniedError"} or "401" in text or "403" in text:
            return LLMError(f"API Key 无效或无权限：{text}", kind="auth", retryable=False)
        if name == "RateLimitError" or "429" in text:
            return LLMError(f"触发限流：{text}", kind="rate_limit", retryable=True)
        if name in {"APITimeoutError", "APIConnectionError", "TimeoutError"} or "timed out" in text.lower():
            return LLMError(f"请求超时或网络不可达：{text}", kind="network", retryable=True)
        if name in {"BadRequestError"} or "400" in text:
            return LLMError(f"请求参数被拒绝：{text}", kind="bad_request", retryable=False)
        if "500" in text or "502" in text or "503" in text:
            return LLMError(f"服务端错误：{text}", kind="server", retryable=True)
        return LLMError(f"LLM 调用失败（{name}）：{text}", kind="unknown", retryable=True)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """调用 chat.completions，带指数退避重试。"""
        client = self._sdk()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "stream": False,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.thinking:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            if self.reasoning_effort:
                kwargs["reasoning_effort"] = self.reasoning_effort

        last_error: LLMError | None = None
        started = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                response = client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                content = choice.message.content or ""
                usage_obj = getattr(response, "usage", None)
                prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
                completion_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0)
                self.usage.add(prompt_tokens, completion_tokens)
                telemetry.record(
                    provider=self.provider_kind,
                    model=getattr(response, "model", self.model),
                    started=started,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    attempts=attempt + 1,
                    ok=True,
                )
                return ChatResult(
                    content=content,
                    usage=Usage(prompt_tokens, completion_tokens, prompt_tokens + completion_tokens, 1),
                    model=getattr(response, "model", self.model),
                    finish_reason=getattr(choice, "finish_reason", None),
                )
            except LLMError as exc:
                # 调用方自己抛的错（例如配置缺失）：如实记一次失败
                telemetry.record(
                    provider=self.provider_kind,
                    model=self.model,
                    started=started,
                    attempts=attempt + 1,
                    ok=False,
                    error_code=getattr(exc, "kind", "") or "llm_error",
                )
                raise
            except Exception as exc:  # noqa: BLE001 - 统一分类
                last_error = self._classify(exc)
                if not last_error.retryable or attempt >= self.max_retries:
                    telemetry.record(
                        provider=self.provider_kind,
                        model=self.model,
                        started=started,
                        attempts=attempt + 1,
                        ok=False,
                        error_code=last_error.kind,
                    )
                    raise last_error from exc
                time.sleep(min(2 ** attempt * 0.8, 6.0))
        raise last_error or LLMError("LLM 调用失败")

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        schema_hint: str | None = None,
    ) -> tuple[dict[str, Any], ChatResult]:
        """要求模型返回 JSON 对象，并解析；解析失败会重试一次。"""
        request_messages = list(messages)
        if schema_hint:
            request_messages = [
                *request_messages,
                {
                    "role": "system",
                    "content": "只输出 JSON 对象，不要输出解释、Markdown 或代码围栏。字段要求：\n" + schema_hint,
                },
            ]
        attempts = 2
        last: LLMError | None = None
        for _ in range(attempts):
            result = self.chat(
                request_messages,
                json_mode=True,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            try:
                return parse_json_response(result.content), result
            except LLMError as exc:
                last = exc
                continue
        raise last or LLMError("LLM 未能返回合法 JSON", kind="invalid_json", retryable=False)


__all__ = [
    "ChatResult",
    "DEFAULT_MODEL",
    "DeepSeekClient",
    "KNOWN_MODELS",
    "LLMError",
    "MODEL_ALIASES",
    "Usage",
    "normalize_model",
    "parse_json_response",
]
