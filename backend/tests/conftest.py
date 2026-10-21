"""pytest 公共 fixture：隔离的数据目录、临时数据库和测试客户端。

重要：测试**不能**读取仓库根目录的 .env。否则开发者填入真实 DeepSeek Key 后，
"未配置 Key 应降级"之类的断言会失败，而且可能触发真实计费请求。
这里统一清空相关环境变量，由各测试按需显式设置。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 测试进程中一律清空，避免误用真实凭据
_CREDENTIAL_ENV = (
    "CROSSPILOT_DEEPSEEK_API_KEY",
    "CROSSPILOT_OPENAI_API_KEY",
    "CROSSPILOT_DEEPSEEK_BASE_URL",
    "CROSSPILOT_OPENAI_BASE_URL",
    "CROSSPILOT_PROVIDER",
    "CROSSPILOT_DEEPSEEK_MODEL",
    "CROSSPILOT_OPENAI_MODEL",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolate_credentials(monkeypatch, tmp_path):
    """每个测试都从「无密钥、默认配置」出发。

    同时把 CROSSPILOT_ENV_FILE 指向一个空文件，确保仓库根的 .env
    里的真实 Key 不会渗进测试（否则"缺 Key 应降级"的断言会失败）。
    """
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("CROSSPILOT_ENV_FILE", str(empty))
    for name in _CREDENTIAL_ENV:
        monkeypatch.delenv(name, raising=False)
    # BYOK 在演示站默认强制；测试默认走"显式关闭"，这样确定性流程仍然可测。
    # 需要验证 428 的测试会自己把它打开（见 tests/test_demo_mode.py）。
    monkeypatch.setenv("CROSSPILOT_REQUIRE_API_KEY", "false")
    from crosspilot.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def sample_analysis_request() -> dict:
    from crosspilot.demo.demo_data import DEMO_ANALYSIS_REQUEST

    return DEMO_ANALYSIS_REQUEST


@pytest.fixture()
def sample_listing_request() -> dict:
    from crosspilot.demo.demo_data import DEMO_LISTING_REQUEST

    return DEMO_LISTING_REQUEST


def _pg_url() -> str:
    from pg_support import database_url

    return database_url()


@pytest.fixture()
def temp_settings(tmp_path, monkeypatch):
    """隔离数据目录与密钥，并把数据库指向测试用 PostgreSQL。"""
    from crosspilot.config import get_settings

    monkeypatch.setenv("CROSSPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CROSSPILOT_DATABASE_URL", _pg_url())
    # 固定测试密钥，避免每个测试生成新的密钥文件
    monkeypatch.setenv("CROSSPILOT_SECRET_KEY", "pytest-fixed-secret-material")
    get_settings.cache_clear()
    settings = get_settings()
    yield settings
    get_settings.cache_clear()


@pytest.fixture()
def client(temp_settings):
    from fastapi.testclient import TestClient

    from crosspilot.app import create_app
    from pg_support import reset_schema

    reset_schema(temp_settings.database_url)
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_client(client):
    """已注册并登录的客户端；业务接口需要登录后才有意义。"""
    response = client.post(
        "/api/auth/register",
        json={"username": "tester", "password": "password123"},
    )
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    yield client
