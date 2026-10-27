"""按图节点解析 Provider。

图里只有 ``listing``（文案生成）会真正调用模型。``analyze`` **不调模型**——
它是 ``engine.analysis.run_analysis`` 的纯统计计算，所以 2026-10-27 起已从
``OVERRIDE_NODES`` 移除，不再支持给它单独配模型（之前的配置项永远不生效）。
``integrity`` / ``summary`` / ``quality`` 同样是确定性规则。

这里把「某用户某节点该用哪个 Provider」收敛成一个函数，HTTP 请求、后台线程、
arq worker 三条执行路径共用，避免各写一份解析逻辑导致行为不一致。

优先级：激活配置里的 ``task_overrides[node]`` > 激活配置 > 旧 ``user_model_settings``
> 进程默认。override 指向的配置失效时回落激活配置，不抛错。
"""

from __future__ import annotations

from typing import Any

from ..persistence.db import Database
from ..persistence.secrets import SecretBox
from .model_settings import ModelSettingsService
from .provider_configs import OVERRIDE_NODES, ProviderConfigService
from .providers import build_provider


def _secret_box(settings) -> SecretBox:
    return SecretBox(settings.resolve_path(settings.data_dir) / ".secret_key")


def build_step_providers(
    db: Database, settings, user_id: str
) -> dict[str, tuple[Any, str]]:
    """返回 ``{node: (provider, 说明)}``，只含会调模型的节点。

    ``说明`` 会拼进任务时间线的步骤描述（例如 ``deepseek/deepseek-flash（override）``），
    让「这一步用的哪个模型」能直接在某一步上看到。
    """
    secrets = _secret_box(settings)
    provider_service = ProviderConfigService(
        db=db, secrets=secrets, settings=settings
    )
    # 兜底配置：优先新表（多套配置），其次旧的单套 user_model_settings
    fallback_config = provider_service.effective(user_id, settings)
    if fallback_config is None:
        fallback_config = ModelSettingsService(db, secrets).effective(user_id, settings)

    result: dict[str, tuple[Any, str]] = {}
    for node in OVERRIDE_NODES:
        config, note = provider_service.resolve_node(user_id, settings, node)
        provider = build_provider(settings, config or fallback_config)
        result[node] = (provider, note)
    return result


__all__ = ["build_step_providers"]
