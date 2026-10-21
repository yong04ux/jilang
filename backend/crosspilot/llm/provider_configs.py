"""多厂商 LLM 配置（本期只做 OpenAI 兼容协议）。

设计要点：

1. **用 base_url + model 区分厂商**，不为每家写一个适配器；
   Anthropic / Gemini 原生协议本期不做（非 OpenAI 兼容，需要独立适配器）。
2. 一个用户可以保存**多套**配置（同一厂商也可多套，例如两把 Key），
   ``active_config_id`` 决定默认使用哪一套。
3. API Key 加密落库（``SecretBox``），接口只返回掩码。
4. ``base_url`` 做**白名单校验**：只允许预置厂商域名，或用户显式选择
   ``custom`` 时放行；同时拒绝内网/回环地址，防止 SSRF 探测。
5. 固定 ``demo`` 账号禁止写入任何 Provider 配置（演示站约束）。
"""

from __future__ import annotations

import ipaddress
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..persistence.db import Database
from .model_settings import EffectiveModelConfig
from ..persistence.secrets import SecretBox, SecretError

CLEAR_KEY_SENTINEL = "__CLEAR__"
RULE_PROVIDER = "rule"


class ProviderConfigError(ValueError):
    """配置非法（消息可直接展示）。"""


#: 图里唯一会调用 LLM 的两个节点。给其他节点配模型不会有任何效果，
#: 所以校验期就拒绝，避免"配了却静默不生效"。
OVERRIDE_NODES: tuple[str, ...] = ("analyze", "listing")

_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")


def parse_task_overrides(raw: Any) -> dict[str, Any]:
    """把库里的 TEXT/JSON 解析成对象；坏数据一律当空对象，不抛异常。

    历史行可能是 ``"{}"``、空串或非 JSON 文本，列表/详情接口不该因此 500。
    """
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# 预置厂商
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderPreset:
    key: str
    label: str
    base_url: str
    default_model: str
    note: str
    #: 允许的 host 后缀；custom 为空表示由用户自填
    allowed_hosts: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "note": self.note,
            "is_custom": self.key == "custom",
        }


PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        "deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-flash",
        "官方 API，OpenAI 兼容；按 token 计费，推荐主力生成。",
        ("api.deepseek.com",),
    ),
    ProviderPreset(
        "openai", "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini",
        "官方 API；需要可用的付费额度。",
        ("api.openai.com",),
    ),
    ProviderPreset(
        "moonshot", "Moonshot / Kimi", "https://api.moonshot.cn/v1", "moonshot-v1-8k",
        "月之暗面 Kimi，OpenAI 兼容。",
        ("api.moonshot.cn",),
    ),
    ProviderPreset(
        "zhipu", "智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash",
        "智谱 AI 开放平台，OpenAI 兼容。",
        ("open.bigmodel.cn",),
    ),
    ProviderPreset(
        "dashscope", "阿里通义", "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-plus", "阿里云百炼兼容模式。",
        ("dashscope.aliyuncs.com",),
    ),
    ProviderPreset(
        "siliconflow", "硅基流动", "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct",
        "开源模型聚合，OpenAI 兼容。",
        ("api.siliconflow.cn",),
    ),
    ProviderPreset(
        "openrouter", "OpenRouter", "https://openrouter.ai/api/v1",
        "openai/gpt-4o-mini", "多模型聚合网关。",
        ("openrouter.ai",),
    ),
    ProviderPreset(
        "ollama", "本地 Ollama", "http://127.0.0.1:11434/v1", "llama3.1",
        "本地模型；仅部署在本机时可用，服务器端调用会失败。",
        ("127.0.0.1", "localhost"),
    ),
    ProviderPreset(
        "custom", "自定义（OpenAI 兼容）", "", "",
        "任意 OpenAI 兼容服务；请自行确认 base_url 与模型名。",
        (),
    ),
)

PRESET_BY_KEY = {preset.key: preset for preset in PRESETS}
ALLOWED_PROVIDERS = tuple(PRESET_BY_KEY) + (RULE_PROVIDER,)

#: 明确禁止的 host：云元数据、常见内网网段由 IP 判断兜底
_BLOCKED_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}


def provider_presets() -> list[dict[str, Any]]:
    return [preset.as_dict() for preset in PRESETS]


def _host_of(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def _is_private_host(host: str) -> bool:
    """拦截回环/私网/链路本地地址，除显式允许的 ollama 场景。"""
    if not host:
        return True
    if host in _BLOCKED_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # 域名交给白名单判定
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def validate_base_url(provider: str, base_url: str, *, allow_custom: bool) -> str:
    """白名单校验，返回规范化后的 base_url。

    - 预置厂商：host 必须匹配允许列表；
    - ``custom``：必须显式 ``allow_custom=True``，且不能指向内网；
    - ``rule``：不需要 base_url。
    """
    text = (base_url or "").strip().rstrip("/")
    preset = PRESET_BY_KEY.get(provider)

    if provider == RULE_PROVIDER:
        return ""

    if preset is None:
        raise ProviderConfigError(f"不支持的 provider：{provider}")

    if not text:
        if preset.base_url:
            return preset.base_url
        raise ProviderConfigError("自定义 provider 必须填写 base_url")

    if not text.startswith(("http://", "https://")):
        raise ProviderConfigError("base_url 必须以 http:// 或 https:// 开头")

    host = _host_of(text)
    if not host:
        raise ProviderConfigError("base_url 无法解析出主机名")

    if provider == "custom":
        if not allow_custom:
            raise ProviderConfigError(
                "使用自定义 base_url 需要显式勾选「自定义服务」，"
                "否则只允许预置厂商域名（防止 SSRF 探测内网）"
            )
        # ollama 场景例外：显式选择 custom 且 host 是本机时放行
        if _is_private_host(host) and host not in {"127.0.0.1", "localhost"}:
            raise ProviderConfigError("自定义 base_url 不能指向内网或保留地址")
        return text

    allowed = preset.allowed_hosts
    if allowed and not any(host == item or host.endswith("." + item) for item in allowed):
        raise ProviderConfigError(
            f"{preset.label} 只允许 {', '.join(allowed)} 域名；"
            "如需其他地址，请选择「自定义」并显式确认"
        )
    return text


# ---------------------------------------------------------------------------
# 输入模型
# ---------------------------------------------------------------------------


class ProviderConfigInput(BaseModel):
    """新增/更新一套配置；未提交的字段保持原值。"""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=40)
    label: str = Field(default="默认", max_length=60)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, max_length=400)
    enabled: bool | None = None
    allow_custom_base_url: bool = False
    #: 按步骤分配模型：``{"analyze": {"config_id"?: str, "model"?: str}, ...}``
    #: 只有 ``analyze`` / ``listing`` 两个节点会调模型，其他键一律 400。
    #: 传 ``None`` 表示"不修改"，传 ``{}`` 表示"清空"。
    task_overrides: Any = None
    #: 更新已有配置时传入；新建时留空
    config_id: str | None = Field(default=None, max_length=64)

    @field_validator("provider", "label", "base_url", "model")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        key = (value or "").strip().lower()
        if key not in ALLOWED_PROVIDERS:
            raise ValueError(
                f"不支持的 provider：{key}；可选：{', '.join(ALLOWED_PROVIDERS)}"
            )
        return key


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProviderConfigService:
    db: Database
    secrets: SecretBox
    settings: Any = None

    # -- 读 ---------------------------------------------------------------
    def list_public(self, user_id: str) -> dict[str, Any]:
        rows = self.db.list_provider_configs(user_id)
        active_id = self._active_config_id(user_id)
        items = [self._public_row(row, active_id) for row in rows]
        return {
            "items": items,
            "active_config_id": active_id,
            "presets": provider_presets(),
            "providers": list(ALLOWED_PROVIDERS),
            "rule_provider": RULE_PROVIDER,
            "note": (
                "本期只支持 OpenAI 兼容协议，用 base_url + model 区分厂商。"
                "Anthropic / Gemini 原生协议未实现。"
            ),
        }

    def _active_config_id(self, user_id: str) -> str | None:
        row = self.db.get_model_settings(user_id)
        return row.get("active_config_id") if row else None

    def public_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """把一行配置转成可外发的视图（Key 只出掩码）。"""
        active_id = self._active_config_id(row["user_id"])
        return self._public_row(row, active_id)

    def _public_row(self, row: dict[str, Any], active_id: str | None) -> dict[str, Any]:
        masked = ""
        has_key = False
        encrypted = row.get("api_key_encrypted")
        if encrypted:
            try:
                masked = SecretBox.mask(self.secrets.decrypt(encrypted))
                has_key = True
            except SecretError:
                # 解不开不是"没配置"，但也不能把异常抛给列表接口
                masked = ""
                has_key = False
        return {
            "config_id": row["config_id"],
            "provider": row["provider"],
            "label": row["label"],
            "base_url": row.get("base_url") or "",
            "model": row.get("model") or "",
            "api_key_masked": masked,
            "has_api_key": has_key,
            "enabled": bool(row.get("enabled")),
            "is_active": row["config_id"] == active_id,
            "last_tested_at": row.get("last_tested_at"),
            "last_test_ok": None if row.get("last_test_ok") is None else bool(row["last_test_ok"]),
            "last_test_detail": row.get("last_test_detail") or "",
            # 直接给对象，前端不必再 JSON.parse；坏数据回落 {}
            "task_overrides": parse_task_overrides(row.get("task_overrides")),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def get_row(self, user_id: str, config_id: str) -> dict[str, Any]:
        row = self.db.get_provider_config(user_id, config_id)
        if row is None:
            raise ProviderConfigError("配置不存在")
        return row

    def decrypt_key(self, row: dict[str, Any]) -> str:
        encrypted = row.get("api_key_encrypted")
        if not encrypted:
            return ""
        try:
            return self.secrets.decrypt(encrypted)
        except SecretError:
            return ""

    # -- 写 ---------------------------------------------------------------
    def save(
        self,
        user_id: str,
        payload: ProviderConfigInput,
        *,
        config_id: str | None = None,
    ) -> dict[str, Any]:
        provider = payload.provider
        existing = (
            self.db.get_provider_config(user_id, config_id)
            if config_id
            else None
        )
        if config_id and existing is None:
            raise ProviderConfigError("配置不存在或不属于当前账号")

        label = payload.label or (existing or {}).get("label") or "默认"
        preset = PRESET_BY_KEY.get(provider)

        base_url = payload.base_url
        if base_url is None and existing is not None:
            base_url = existing.get("base_url") or ""
        if base_url is None:
            base_url = preset.base_url if preset else ""
        resolved_base_url = validate_base_url(
            provider, base_url, allow_custom=payload.allow_custom_base_url
        )

        model = payload.model
        if model is None and existing is not None:
            model = existing.get("model") or ""
        if not model:
            model = preset.default_model if preset else ""
        if provider != RULE_PROVIDER and not model:
            raise ProviderConfigError("必须填写模型名（model）")

        encrypted = (existing or {}).get("api_key_encrypted")
        if payload.api_key is not None:
            submitted = payload.api_key.strip()
            if submitted == CLEAR_KEY_SENTINEL:
                encrypted = None
            elif submitted == "":
                pass  # 空串表示保持原值
            else:
                if not SecretBox.looks_like_key(submitted):
                    raise ProviderConfigError(
                        "API Key 格式看起来不对（至少 8 位、不能是 URL、不能含空格）"
                    )
                encrypted = self.secrets.encrypt(submitted)

        if provider != RULE_PROVIDER and not encrypted:
            raise ProviderConfigError("这套配置还没有 API Key，请填写后再保存")

        # 同一用户同一厂商下的 label 唯一：新建时若冲突则明确报错
        if existing is None:
            clash = self.db.find_provider_config(user_id, provider, label)
            if clash is not None:
                raise ProviderConfigError(
                    f"已存在同厂商同标签的配置（{provider} / {label}），请换一个标签"
                )

        # 按步骤分配模型：None = 不改；{} = 清空；其余走严格校验
        override_text = (existing or {}).get("task_overrides") or "{}"
        if payload.task_overrides is not None:
            cleaned = self.validate_task_overrides(user_id, payload.task_overrides)
            override_text = json.dumps(cleaned, ensure_ascii=False)

        record = {
            "config_id": (existing or {}).get("config_id") or uuid.uuid4().hex,
            "user_id": user_id,
            "provider": provider,
            "label": label,
            "base_url": resolved_base_url,
            "model": model,
            "api_key_encrypted": encrypted,
            "enabled": payload.enabled if payload.enabled is not None
            else bool((existing or {}).get("enabled", True)),
            "last_tested_at": (existing or {}).get("last_tested_at"),
            "last_test_ok": (existing or {}).get("last_test_ok"),
            "last_test_detail": (existing or {}).get("last_test_detail"),
            "task_overrides": override_text,
        }
        self.db.save_provider_config(record)
        row = self.db.find_provider_config(user_id, provider, label) or record
        return self._public_row(row, self._active_config_id(user_id))

    def delete(self, user_id: str, config_id: str) -> None:
        row = self.get_row(user_id, config_id)
        self.db.delete_provider_config(user_id, config_id)
        if self._active_config_id(user_id) == config_id:
            # 删掉当前激活的配置后回落到下一个可用配置
            remaining = self.db.list_provider_configs(user_id)
            fallback = next((r["config_id"] for r in remaining if r.get("enabled")), None)
            self.db.set_active_provider_config(user_id, fallback)

    def activate(self, user_id: str, config_id: str) -> dict[str, Any]:
        row = self.get_row(user_id, config_id)
        if not row.get("enabled"):
            raise ProviderConfigError("该配置已被禁用，无法激活")
        self.db.set_active_provider_config(user_id, config_id)
        return self._public_row(row, config_id)

    def record_test(
        self, user_id: str, config_id: str, *, ok: bool, detail: str
    ) -> dict[str, Any]:
        row = self.get_row(user_id, config_id)
        record = dict(row)
        record.update(
            {
                "last_tested_at": _now(),
                "last_test_ok": ok,
                "last_test_detail": detail[:500],
                "api_key_encrypted": None,  # 不覆盖已有 Key
                "task_overrides": row.get("task_overrides") or "{}",
            }
        )
        self.db.save_provider_config(record)
        fresh = self.get_row(user_id, config_id)
        return self._public_row(fresh, self._active_config_id(user_id))

    # -- 生成时解析 -------------------------------------------------------
    def effective(
        self,
        user_id: str,
        settings,
        *,
        config_id: str | None = None,
        model: str | None = None,
    ) -> EffectiveModelConfig | None:
        """返回某套配置对应的 EffectiveModelConfig；不可用时返回 None。

        ``config_id`` / ``model`` 让「按步骤分配模型」复用同一套合并逻辑：
        前者换配置（连带 key / base_url），后者只换模型名。
        """
        active_id = config_id or self._active_config_id(user_id)
        if not active_id:
            return None
        row = self.db.get_provider_config(user_id, active_id)
        if row is None or not row.get("enabled"):
            return None
        provider = row["provider"]
        model_row = self.db.get_model_settings(user_id) or {}
        return EffectiveModelConfig(
            provider=provider,
            model=model or row.get("model") or "",
            base_url=row.get("base_url") or "",
            api_key=self.decrypt_key(row),
            temperature=(
                model_row["temperature"]
                if model_row.get("temperature") is not None
                else settings.deepseek_temperature
            ),
            max_tokens=model_row.get("max_tokens"),
            timeout=(
                model_row["timeout"]
                if model_row.get("timeout") is not None
                else settings.deepseek_timeout
            ),
            max_retries=(
                model_row["max_retries"]
                if model_row.get("max_retries") is not None
                else settings.deepseek_max_retries
            ),
            thinking=bool(model_row.get("thinking")),
            reasoning_effort=model_row.get("reasoning_effort") or "",
            source="user",
        )

    def active_provider_key(self, user_id: str) -> str | None:
        """当前激活配置的 provider 名；没有激活配置时返回 None。"""
        active_id = self._active_config_id(user_id)
        if not active_id:
            return None
        row = self.db.get_provider_config(user_id, active_id)
        return row["provider"] if row else None

    def active_config_id(self, user_id: str) -> str | None:
        return self._active_config_id(user_id)

    # -- 按步骤分配模型 ----------------------------------------------------

    def validate_task_overrides(
        self, user_id: str, raw: Any
    ) -> dict[str, dict[str, str]]:
        """校验并规范化 ``task_overrides``；非法直接抛 ``ProviderConfigError``。

        返回形如 ``{"listing": {"config_id": "...", "model": "..."}}`` 的干净对象，
        可直接 ``json.dumps`` 落库。写入期严格，运行时才允许回落（见 ``resolve_node``）。
        """
        if raw is None:
            return {}
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return {}
            try:
                raw = json.loads(text)
            except ValueError as exc:
                raise ProviderConfigError("task_overrides 不是合法 JSON") from exc
        if not isinstance(raw, dict):
            raise ProviderConfigError("task_overrides 必须是对象")

        cleaned: dict[str, dict[str, str]] = {}
        for node, value in raw.items():
            if node not in OVERRIDE_NODES:
                raise ProviderConfigError(
                    f"不支持为节点 {node} 指定模型；"
                    f"只有 {', '.join(OVERRIDE_NODES)} 会调用模型"
                )
            if not isinstance(value, dict):
                raise ProviderConfigError(f"{node} 的配置必须是对象")
            unknown = set(value) - {"config_id", "model"}
            if unknown:
                raise ProviderConfigError(
                    f"{node} 含未知字段：{', '.join(sorted(str(k) for k in unknown))}"
                )

            item: dict[str, str] = {}
            config_id = str(value.get("config_id") or "").strip()
            model = str(value.get("model") or "").strip()
            if not config_id and not model:
                raise ProviderConfigError(f"{node} 至少要指定 config_id 或 model")
            if config_id:
                row = self.db.get_provider_config(user_id, config_id)
                if row is None:
                    raise ProviderConfigError(
                        f"{node} 指定的配置不存在或不属于当前账号"
                    )
                if not row.get("enabled"):
                    raise ProviderConfigError(f"{node} 指定的配置已被禁用")
                if row.get("provider") == RULE_PROVIDER:
                    raise ProviderConfigError(
                        f"{node} 不能指定规则引擎（rule）配置：它不调用模型"
                    )
                item["config_id"] = config_id
            if model:
                if not _MODEL_RE.match(model):
                    raise ProviderConfigError(
                        f"{node} 的模型名不合法（1–128 位字母数字与 . _ : / -）"
                    )
                item["model"] = model
            cleaned[node] = item
        return cleaned

    def resolve_node(self, user_id: str, settings, node: str) -> tuple[Any, str]:
        """按节点解析配置，返回 ``(EffectiveModelConfig | None, 说明)``。

        优先级：配置级 ``task_overrides[node]`` > 激活配置。
        override 指向的配置被删/禁用时**不报错**，回落激活配置并在说明里标注
        （已排队的任务不该因为设置变更而失败）。
        """
        active_id = self._active_config_id(user_id)
        active_row = (
            self.db.get_provider_config(user_id, active_id) if active_id else None
        )
        overrides = parse_task_overrides((active_row or {}).get("task_overrides"))
        spec = overrides.get(node) if isinstance(overrides, dict) else None

        base = self.effective(user_id, settings)
        if not isinstance(spec, dict):
            return base, _config_label(base)

        config = self.effective(
            user_id,
            settings,
            config_id=spec.get("config_id") or None,
            model=spec.get("model") or None,
        )
        if config is None:
            return base, f"{_config_label(base)}（override 失效，已回落）"
        return config, f"{_config_label(config)}（override）"


def _config_label(config: Any) -> str:
    """时间线里展示的「厂商/模型」。"""
    if config is None:
        return "默认配置"
    model = getattr(config, "model", "") or ""
    provider = getattr(config, "provider", "") or ""
    return f"{provider}/{model}" if model else (provider or "默认配置")


__all__ = [
    "ALLOWED_PROVIDERS",
    "CLEAR_KEY_SENTINEL",
    "OVERRIDE_NODES",
    "PRESETS",
    "PRESET_BY_KEY",
    "ProviderConfigError",
    "ProviderConfigInput",
    "ProviderConfigService",
    "ProviderPreset",
    "RULE_PROVIDER",
    "parse_task_overrides",
    "provider_presets",
    "validate_base_url",
]
