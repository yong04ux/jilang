"""每用户的模型配置：读写、校验、加密存储、即时生效。

与 ``config.Settings`` 的关系：
- ``Settings`` 是**进程级默认值**（来自 .env），用于没有个性化配置时兜底；
- 本模块管理**每用户覆盖值**，存在 ``user_model_settings`` 表里；
- 生成时优先用用户配置，缺失字段逐项回退到进程默认值；
- 保存后**立即生效**：Provider 在每次请求时按当前用户配置重建，不需要重启服务。

安全边界：
- API Key 加密后落库，接口只返回掩码；
- 前端提交 ``api_key`` 为空表示"不修改"，提交 ``__CLEAR__`` 表示"清除"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..persistence.db import Database
from ..persistence.secrets import SecretBox, SecretError

PROVIDER_CHOICES = ("rule", "deepseek", "openai")
CLEAR_KEY_SENTINEL = "__CLEAR__"
# 官方文档给出的模型名（前端下拉用；允许手填其他兼容模型）
KNOWN_MODELS = ("deepseek-flash", "deepseek-v4-pro")


class ModelSettingsError(ValueError):
    """配置非法（消息可直接展示）。"""


# ---------------------------------------------------------------------------
# 输入模型
# ---------------------------------------------------------------------------


class ModelSettingsUpdate(BaseModel):
    """前端提交的配置。字段都可选：未提交的保持原值。"""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["rule", "deepseek", "openai"] | None = None
    model: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=300)
    api_key: str | None = Field(default=None, max_length=400)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=16, le=64000)
    timeout: float | None = Field(default=None, ge=5.0, le=600.0)
    max_retries: int | None = Field(default=None, ge=0, le=8)
    thinking: bool | None = None
    reasoning_effort: str | None = Field(default=None, max_length=40)

    @field_validator("model", "base_url", "reasoning_effort")
    @classmethod
    def _clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("base_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("base_url 必须以 http:// 或 https:// 开头")
        return value

    @model_validator(mode="after")
    def _thinking_only_for_reasoning_models(self) -> "ModelSettingsUpdate":
        if self.thinking and self.model:
            model = self.model.lower()
            if model in {"deepseek-flash"} and not self.reasoning_effort:
                # flash 关闭思考是默认行为，开启也可，但不强制报错，仅保持宽松
                pass
        return self


# ---------------------------------------------------------------------------
# 解析后的生效配置
# ---------------------------------------------------------------------------


@dataclass
class EffectiveModelConfig:
    """生成时真正使用的一组参数（用户配置 + 进程默认值合并后）。"""

    provider: str
    model: str
    base_url: str
    api_key: str
    temperature: float
    max_tokens: int | None
    timeout: float
    max_retries: int
    thinking: bool
    reasoning_effort: str
    source: str = "default"  # default / user
    warnings: list[str] = field(default_factory=list)

    def as_dict(self, *, mask_key: bool = True) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key": SecretBox.mask(self.api_key) if mask_key else "",
            "has_api_key": bool(self.api_key),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "thinking": self.thinking,
            "reasoning_effort": self.reasoning_effort,
            "source": self.source,
            "warnings": self.warnings,
        }


def _defaults_from_settings(settings) -> EffectiveModelConfig:
    api_key = settings.deepseek_api_key or settings.openai_api_key or ""
    return EffectiveModelConfig(
        provider=settings.provider,
        model=settings.deepseek_model or settings.openai_model or "deepseek-flash",
        base_url=settings.deepseek_base_url or settings.openai_base_url or "https://api.deepseek.com",
        api_key=api_key,
        temperature=settings.deepseek_temperature,
        max_tokens=None,
        timeout=settings.deepseek_timeout,
        max_retries=settings.deepseek_max_retries,
        thinking=settings.deepseek_thinking,
        reasoning_effort=settings.deepseek_reasoning_effort or "",
        source="default",
    )


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------


class ModelSettingsService:
    def __init__(self, db: Database, secret_box: SecretBox | None = None):
        self.db = db
        self.secrets = secret_box or SecretBox()

    # -- 读 ---------------------------------------------------------------
    def effective(self, user_id: str | None, settings) -> EffectiveModelConfig:
        """返回该用户实际生效的配置；没有用户配置时回退到进程默认值。"""
        base = _defaults_from_settings(settings)
        if not user_id:
            return base
        row = self.db.get_model_settings(user_id)
        if row is None:
            return base

        config = EffectiveModelConfig(
            provider=row["provider"] or base.provider,
            model=row["model"] or base.model,
            base_url=row["base_url"] or base.base_url,
            api_key=base.api_key,
            temperature=row["temperature"] if row["temperature"] is not None else base.temperature,
            max_tokens=row["max_tokens"],
            timeout=row["timeout"] if row["timeout"] is not None else base.timeout,
            max_retries=row["max_retries"] if row["max_retries"] is not None else base.max_retries,
            thinking=bool(row["thinking"]),
            reasoning_effort=row["reasoning_effort"] or "",
            source="user",
        )
        encrypted = row.get("api_key_encrypted")
        if encrypted:
            try:
                config.api_key = self.secrets.decrypt(encrypted)
            except SecretError as exc:
                # 解不开不是"没配置"，必须明确告知，否则用户会以为 Key 失效是模型问题
                config.warnings.append(str(exc))
                config.api_key = ""
        return config

    def to_public(self, user_id: str | None, settings) -> dict[str, Any]:
        """给前端的视图：含掩码、默认值、可选模型，不含任何明文密钥。"""
        effective = self.effective(user_id, settings)
        defaults = _defaults_from_settings(settings)
        row = self.db.get_model_settings(user_id) if user_id else None
        return {
            "effective": effective.as_dict(),
            "has_custom": row is not None,
            "defaults": defaults.as_dict(),
            "options": {
                "providers": list(PROVIDER_CHOICES),
                "models": list(KNOWN_MODELS),
                "provider_notes": {
                    "rule": "本地规则引擎：无需 Key，离线可用；英文文案质量有限，建议仅用于演示或降级。",
                    "deepseek": "DeepSeek 官方 API：推荐。需要 API Key，按 token 计费。",
                    "openai": "任意 OpenAI 兼容服务：自填 base_url 与模型名。",
                },
            },
            "updated_at": row["updated_at"] if row else None,
        }

    # -- 写 ---------------------------------------------------------------
    def update(self, user_id: str, payload: ModelSettingsUpdate, settings) -> dict[str, Any]:
        """合并式更新；保存后立即对后续请求生效。"""
        current = self.db.get_model_settings(user_id)
        effective = self.effective(user_id, settings)

        provider = payload.provider or (current["provider"] if current else effective.provider)
        if provider not in PROVIDER_CHOICES:
            raise ModelSettingsError(f"不支持的 provider：{provider}")

        model = payload.model or (current["model"] if current else effective.model)
        base_url = payload.base_url or (current["base_url"] if current else effective.base_url)

        if provider != "rule" and not model:
            raise ModelSettingsError("使用 deepseek / openai 时必须填写模型名")
        if provider == "openai" and not base_url:
            raise ModelSettingsError("使用 openai 兼容服务时必须填写 base_url")

        # API Key 三态：None=不改，__CLEAR__=清除，其他=更新
        encrypted = current["api_key_encrypted"] if current else None
        warnings: list[str] = []
        if payload.api_key is not None:
            submitted = payload.api_key.strip()
            if submitted == CLEAR_KEY_SENTINEL:
                encrypted = None
            elif submitted == "":
                pass  # 空串表示"保持原值"，避免前端回填掩码导致覆盖
            else:
                if not SecretBox.looks_like_key(submitted):
                    raise ModelSettingsError(
                        "API Key 格式看起来不对（至少 8 位、不能是 URL、不能含空格）"
                    )
                encrypted = self.secrets.encrypt(submitted)

        final_key = self.secrets.decrypt(encrypted) if encrypted else ""
        if provider != "rule" and not final_key:
            warnings.append("当前未保存 API Key，生成时会降级为本地规则引擎。")

        values = {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "api_key_encrypted": encrypted,
            "temperature": payload.temperature
            if payload.temperature is not None
            else (current["temperature"] if current else effective.temperature),
            "max_tokens": payload.max_tokens
            if payload.max_tokens is not None
            else (current["max_tokens"] if current else None),
            "timeout": payload.timeout
            if payload.timeout is not None
            else (current["timeout"] if current else effective.timeout),
            "max_retries": payload.max_retries
            if payload.max_retries is not None
            else (current["max_retries"] if current else effective.max_retries),
            "thinking": payload.thinking
            if payload.thinking is not None
            else (bool(current["thinking"]) if current else effective.thinking),
            "reasoning_effort": payload.reasoning_effort
            if payload.reasoning_effort is not None
            else (current["reasoning_effort"] if current else effective.reasoning_effort),
        }
        self.db.save_model_settings(user_id, values)

        result = self.to_public(user_id, settings)
        result["warnings"] = warnings
        return result

    def reset(self, user_id: str, settings) -> dict[str, Any]:
        """删除用户配置，回退到进程默认值。"""
        self.db.delete_model_settings(user_id)
        out = self.to_public(user_id, settings)
        out["warnings"] = ["已重置为服务默认配置"]
        return out


__all__ = [
    "CLEAR_KEY_SENTINEL",
    "EffectiveModelConfig",
    "KNOWN_MODELS",
    "ModelSettingsError",
    "ModelSettingsService",
    "ModelSettingsUpdate",
    "PROVIDER_CHOICES",
]
