"""应用配置：环境变量 + 项目内 config/ 目录下的可配置规则文件。

设计要点：
- 所有配置都有可用默认值，不依赖 .env 也能启动；
- 环境变量统一使用 ``CROSSPILOT_`` 前缀；
- 平台规则（字符限制、禁用词、合规声明）放在 config/ 下的 JSON 文件中，
  便于运营人员调整，且**不硬编码**成代码逻辑。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# monorepo 布局：backend/crosspilot/config.py -> backend/crosspilot（包目录）-> backend/（工程根）
PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_DIR.parent
# 前端静态资源与 backend/ 平级（仓库根/frontend），可用 CROSSPILOT_WEB_DIR 覆盖
FRONTEND_DIR = BACKEND_ROOT.parent / "frontend"

# 规则文件查找顺序（先找到先用）：
#   1. 当前工作目录的 config/（便于用户覆盖）
#   2. backend/ 工程根的 config/（源码运行 / pip 安装后同指一处）
_CANDIDATE_CONFIG_DIRS = (Path.cwd() / "config", BACKEND_ROOT / "config")


def find_config_dir() -> Path:
    """返回实际使用的 config 目录；找不到时退回 backend/ 工程根（后续会报明确错误）。"""
    for candidate in _CANDIDATE_CONFIG_DIRS:
        if (candidate / "platform_rules.json").is_file():
            return candidate
    return BACKEND_ROOT / "config"


CONFIG_DIR = find_config_dir()


class Settings(BaseSettings):
    """运行配置。字段名与环境变量一一对应（前缀 CROSSPILOT_）。"""

    model_config = SettingsConfigDict(
        env_prefix="CROSSPILOT_",
        # 注意：不在这里固定 env_file。改为实例化时计算（见 __init__），
        # 否则模块导入后修改变量不会生效，测试也无法隔离真实 .env。
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def __init__(self, **values: Any):
        env_file = os.environ.get("CROSSPILOT_ENV_FILE") or str(BACKEND_ROOT / ".env")
        super().__init__(_env_file=env_file, **values)

    # 服务
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    # 前端静态文件目录（monorepo：与 backend/ 平级的 frontend/）
    web_dir: Path = FRONTEND_DIR

    # 存储（相对路径一律相对 backend/ 工程根，不会因当前工作目录而变化）
    data_dir: Path = BACKEND_ROOT / "data"
    # PostgreSQL 连接串（唯一数据库后端）
    database_url: str = ""

    # 生成 / 分析提供者
    #   rule     : 纯本地规则引擎（离线、可测，文案为事实直出，需人工改写）
    #   deepseek : DeepSeek 官方 API（推荐，主力生成）
    #   openai   : 任意 OpenAI 兼容服务（兼容旧配置）
    provider: Literal["rule", "deepseek", "openai"] = "rule"

    # DeepSeek 官方 API（默认走官方 base_url）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_timeout: float = 90.0
    deepseek_max_retries: int = 2
    deepseek_temperature: float = 0.5
    # deepseek-v4-pro 支持思考模式；flash 默认关闭以降低延迟与成本
    deepseek_thinking: bool = False
    deepseek_reasoning_effort: str = ""

    # 兼容旧的 openai_* 变量名（若只填了旧变量，则作为 deepseek 的回退）
    openai_base_url: str = "https://api.deepseek.com"
    openai_api_key: str = ""
    openai_model: str = ""

    # 上传限制
    max_upload_bytes: int = 5 * 1024 * 1024

    # 注册策略：关闭后除首个用户外，注册必须携带租户邀请令牌
    allow_open_registration: bool = True

    # ---- 演示站机制 ------------------------------------------------------
    # BYOK：没有可用 Key 时，需要模型的任务返回 428（不静默降级）
    require_api_key: bool = True
    # 固定演示账号：共享、只读示例数据、禁止保存 API Key
    demo_username: str = "demo"
    demo_password: str = ""
    # 一键体验的临时账号有效期（小时）
    guest_ttl_hours: int = 24
    # 限流：每账号/IP 每小时的任务数与 Key 测试数
    rate_limit_tasks_per_hour: int = 10
    rate_limit_key_tests_per_hour: int = 5
    # 一键体验按 IP 限流：公网演示站最容易被刷的入口（无需凭据）
    rate_limit_guest_per_hour: int = 5
    rate_limit_enabled: bool = True

    # ---- 数据源 ----------------------------------------------------------
    # 默认全部走 mock；将来按连接逐个切换（store_connections.mode = "live"）
    marketplace_mode: Literal["mock", "live"] = "mock"

    # 长任务执行器：thread（进程内，默认）| arq（需 Redis + arq）
    task_queue: Literal["thread", "arq"] = "thread"
    redis_url: str = "redis://127.0.0.1:6379/0"
    # 强制同步执行：部署到 Serverless（Vercel 等）时必须打开。
    # 这类平台的实例在响应结束后会被冻结，进程内线程队列的后台任务会就地停摆，
    # 任务永远停在 running。打开后忽略 async_run，在本次请求内跑完再返回。
    force_sync_tasks: bool = False

    # ---- 加密主密钥 ------------------------------------------------------
    # 用户 API Key 的加密主密钥。留空时回退到 data/.secret_key 文件（本地开发）。
    # Serverless（Vercel 等）文件系统只读，无法持久化密钥文件，**必须显式设置**，
    # 否则保存 API Key 会返回 500「加密密钥不可用」。
    # 一旦设定不要更改：改了已保存的 Key 全部无法解密。
    #
    # 为什么要有这个字段：SecretBox 只读进程环境变量，而 .env 文件不会注入
    # os.environ。没有这个字段时，写在 .env 里的 CROSSPILOT_SECRET_KEY 会被
    # pydantic 的 extra="ignore" 直接丢弃，本地静默回退到自动生成的密钥文件，
    # 造成「本地与线上各一套密钥」。有此字段后两处行为一致。
    secret_key: str = ""

    # ---- 部署 ------------------------------------------------------------
    # 启动时自动执行迁移；生产环境建议 false 并由 CLI 显式迁移
    auto_migrate: bool = True
    # 迁移专用连接串（Supabase 直连 5432）；为空时用 database_url
    migration_database_url: str = ""
    # 会话 Cookie 是否加 Secure（HTTPS 部署时必须为 true）
    cookie_secure: bool = False
    # 导入文件存储后端：local | supabase
    storage_backend: Literal["local", "supabase"] = "local"
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_bucket: str = "crosspilot"
    # 允许的前端来源（CORS，逗号分隔）；空表示同源
    allowed_origins: str = ""

    # 规则文件
    platform_rules_path: Path = CONFIG_DIR / "platform_rules.json"
    banned_terms_path: Path = CONFIG_DIR / "banned_terms.json"

    # 明确标注本服务输出的数据性质
    demo_data_label: str = "demo"
    engine_version: str = "0.1.0"
    # 品牌名，出现在标题、OpenAPI 描述与系统提示中
    brand_name: str = "激浪"

    @property
    def origin_list(self) -> list[str]:
        return [item.strip() for item in (self.allowed_origins or "").split(",") if item.strip()]

    @property
    def is_demo_account_enabled(self) -> bool:
        """固定 demo 账号只有在配置了密码时才存在（避免默认弱口令）。"""
        return bool(self.demo_username and self.demo_password)

    def resolve_path(self, value: Path) -> Path:
        """相对路径按 backend/ 工程根解析（便于从任意工作目录启动）。"""
        return value if value.is_absolute() else (BACKEND_ROOT / value)

    @property
    def uploads_dir(self) -> Path:
        path = self.resolve_path(self.data_dir) / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def load_json_config(path: Path) -> dict[str, Any]:
    """读取 JSON 规则文件，失败时给出明确错误（不静默吞掉）。"""
    resolved = path if path.is_absolute() else BACKEND_ROOT / path
    if not resolved.exists():
        raise FileNotFoundError(f"规则文件不存在: {resolved}")
    with resolved.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"规则文件根节点必须是对象: {resolved}")
    return data


__all__ = [
    "BACKEND_ROOT",
    "CONFIG_DIR",
    "FRONTEND_DIR",
    "PACKAGE_DIR",
    "Settings",
    "get_settings",
    "load_json_config",
]
