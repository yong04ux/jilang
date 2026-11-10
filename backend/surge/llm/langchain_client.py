"""原生协议厂商（Anthropic / Google Gemini）的聊天客户端。

为什么需要这一层：OpenAI 兼容协议只要换 ``base_url`` 就能接一家，但 Anthropic 的
Messages API 与 Gemini 的 generateContent 各有自己的消息结构、``system`` 位置与
返回体。项目里已经有 ``langgraph``，``langchain_core`` 本来就在依赖树里，所以这几家
走 LangChain 的官方适配包（``langchain-anthropic`` / ``langchain-google-genai``），
不用自己啃协议细节。

这一层的**唯一职责是把 LangChain 的模型对象伪装成 ``DeepSeekClient``**：
对外只暴露 ``chat()`` / ``chat_json()`` / ``list_models()``，内部把 LangChain 的
异常、消息、用量翻译回项目已有的 ``LLMError`` / ``Usage`` / ``ChatResult``。
上层（skills、API、任务时间线）完全感知不到差别。

适配包按需导入：没装依赖也能启动整个应用，只在真的选了这家厂商时报一条能看懂的错。
"""

from __future__ import annotations

from typing import Any

from .llm import ChatResult, LLMError, Usage, chat_json_via, parse_json_response

#: 走原生协议的厂商 → 适配包模块名（报错文案里要说清楚装什么）
NATIVE_PROVIDERS: dict[str, str] = {
    "anthropic": "langchain-anthropic",
    "google": "langchain-google-genai",
}


def _to_langchain_messages(messages: list[dict[str, str]]) -> list[Any]:
    """把 OpenAI 风格的 ``{role, content}`` 转成 LangChain 消息对象。"""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    mapping = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}
    converted: list[Any] = []
    for item in messages:
        role = (item.get("role") or "user").strip().lower()
        cls = mapping.get(role, HumanMessage)
        converted.append(cls(content=item.get("content") or ""))
    return converted


def _text_of(content: Any) -> str:
    """``AIMessage.content`` 可能是字符串，也可能是内容块列表。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") in {None, "text"} and block.get("text"):
                    parts.append(str(block["text"]))
                elif block.get("text"):
                    parts.append(str(block["text"]))
        return "".join(parts)
    return str(content or "")


class LangChainChatClient:
    """把 LangChain 的 Chat 模型包成项目内部的聊天客户端。

    与 ``DeepSeekClient`` 保持同一套对外契约（``chat`` / ``chat_json`` /
    ``list_models`` / ``usage`` / ``model``），所以 Provider 层不用分叉。
    """

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        base_url: str = "",
        model: str = "",
        timeout: float = 90.0,
        max_retries: int = 2,
        temperature: float = 0.4,
        thinking: bool = False,
        reasoning_effort: str | None = None,
    ) -> None:
        if provider not in NATIVE_PROVIDERS:
            raise LLMError(f"不支持的模型厂商：{provider}", kind="config")
        if not api_key:
            raise LLMError(
                "这套配置还没有 API Key，请到设置里填写后再使用。",
                kind="no_key",
                retryable=False,
            )
        self.provider = provider
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model or ""
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.temperature = temperature
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.usage = Usage()
        self._model: Any = None

    # -- 构造 -------------------------------------------------------------
    def _build(self) -> Any:
        if self._model is not None:
            return self._model
        package = NATIVE_PROVIDERS[self.provider]
        try:
            if self.provider == "anthropic":
                from langchain_anthropic import ChatAnthropic

                self._model = ChatAnthropic(
                    model=self.model,
                    api_key=self.api_key,
                    base_url=self.base_url or None,
                    temperature=self.temperature,
                    timeout=self.timeout,
                    max_retries=0,  # 重试由本类控制，便于记录与分类
                )
            else:
                from langchain_google_genai import ChatGoogleGenerativeAI

                self._model = ChatGoogleGenerativeAI(
                    model=self.model,
                    api_key=self.api_key,
                    base_url=self.base_url or None,
                    temperature=self.temperature,
                    timeout=self.timeout,
                    max_retries=0,
                )
        except ImportError as exc:  # pragma: no cover - 只在缺依赖时触发
            raise LLMError(
                f"使用这家厂商需要安装适配包 {package}，当前环境里没有。",
                kind="missing_dependency",
            ) from exc
        return self._model

    # -- 错误分类 ---------------------------------------------------------
    def _classify(self, exc: Exception) -> LLMError:
        """把适配包/厂商 SDK 的异常翻成项目自己的分类。"""
        name = type(exc).__name__
        text = str(exc)
        lowered = text.lower()
        if name in {"AuthenticationError", "PermissionDeniedError"} or "401" in text or "403" in text:
            return LLMError(f"API Key 无效或无权限：{text}", kind="auth", retryable=False)
        if name == "RateLimitError" or "429" in text or "rate limit" in lowered:
            return LLMError(f"触发限流：{text}", kind="rate_limit", retryable=True)
        if name in {"APITimeoutError", "APIConnectionError", "ConnectError", "TimeoutError"} or "timed out" in lowered:
            return LLMError(f"请求超时或网络不可达：{text}", kind="network", retryable=True)
        if name in {"BadRequestError", "InvalidArgumentError", "NotFoundError"} or "400" in text or "404" in text:
            return LLMError(f"请求被拒绝：{text}", kind="bad_request", retryable=False)
        return LLMError(f"LLM 调用失败（{name}）：{text}", kind="unknown", retryable=True)

    # -- 调用 -------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        import time

        model = self._build()
        runnable = model
        if max_tokens:
            runnable = runnable.bind(max_tokens=max_tokens)
        if temperature is not None:
            runnable = runnable.bind(temperature=temperature)

        lc_messages = _to_langchain_messages(messages)
        last_error: LLMError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = runnable.invoke(lc_messages)
                return self._to_result(response)
            except LLMError:
                raise
            except Exception as exc:  # noqa: BLE001 - 统一分类
                last_error = self._classify(exc)
                if not last_error.retryable or attempt >= self.max_retries:
                    raise last_error from exc
                time.sleep(min(2 ** attempt * 0.8, 6.0))
        raise last_error or LLMError("LLM 调用失败")

    def _to_result(self, response: Any) -> ChatResult:
        content = _text_of(getattr(response, "content", ""))
        meta = getattr(response, "usage_metadata", None) or {}
        prompt_tokens = int(meta.get("input_tokens") or 0)
        output_tokens = int(meta.get("output_tokens") or 0)
        self.usage.add(prompt_tokens, output_tokens)
        response_meta = getattr(response, "response_metadata", None) or {}
        return ChatResult(
            content=content,
            usage=Usage(prompt_tokens, output_tokens, prompt_tokens + output_tokens, 1),
            model=str(response_meta.get("model_name") or response_meta.get("model") or self.model),
            finish_reason=response_meta.get("stop_reason") or response_meta.get("finish_reason"),
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        schema_hint: str | None = None,
    ) -> tuple[dict[str, Any], ChatResult]:
        """与 ``DeepSeekClient.chat_json`` 同一套重试与解析逻辑。"""
        return chat_json_via(
            self,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            schema_hint=schema_hint,
        )

    # -- 模型清单 ---------------------------------------------------------
    def list_models(self, *, limit: int = 200) -> list[str]:
        """问厂商要当前可用的模型名。

        这两家的模型名各家文档写法不一（带不带 ``models/`` 前缀、版本后缀），
        与其硬编码一份迟早过期的清单，不如直接读账号能看到的那份。
        """
        try:
            if self.provider == "anthropic":
                from anthropic import Anthropic

                client = Anthropic(
                    api_key=self.api_key,
                    base_url=self.base_url or None,
                    timeout=min(self.timeout, 20.0),
                )
                page = client.models.list(limit=limit)
                return sorted({str(item.id) for item in (getattr(page, "data", None) or []) if getattr(item, "id", None)})

            from google import genai

            client = genai.Client(api_key=self.api_key)
            names: list[str] = []
            for item in client.models.list():
                name = str(getattr(item, "name", "") or "")
                if name:
                    names.append(name.split("/")[-1])
            # 向量模型不能用于对话，列出来只会让人选错
            return sorted({n for n in names if n and "embed" not in n.lower()})[:limit]
        except LLMError:
            raise
        except ImportError as exc:  # pragma: no cover
            raise LLMError(
                f"读取模型清单需要安装 {NATIVE_PROVIDERS[self.provider]}，当前环境里没有。",
                kind="missing_dependency",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 统一分类
            raise self._classify(exc) from exc


__all__ = ["LangChainChatClient", "NATIVE_PROVIDERS", "parse_json_response"]
