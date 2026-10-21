"""``CROSSPILOT_SECRET_KEY`` 的来源优先级：显式配置 > 密钥文件。

背景（真实踩过的坑）：``SecretBox`` 原本只读 ``os.environ``，而 pydantic 读 ``.env``
文件时不会把值注入 ``os.environ``。``Settings`` 里又没有 ``secret_key`` 字段
（``extra="ignore"`` 会直接丢弃），因此在 ``.env`` 里写 ``CROSSPILOT_SECRET_KEY``
是**静默无效**的：本地照样能跑，但用的是自动生成的 ``data/.secret_key``，
与线上（真实环境变量）各一套密钥，将来搬数据时已存的 API Key 全部解不开。

这三个测试锁住修复后的行为。
"""

from __future__ import annotations

from pathlib import Path

from crosspilot.api.deps import make_secret_box
from crosspilot.config import Settings


def _env_file_with_secret(tmp_path: Path) -> Path:
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "CROSSPILOT_SECRET_KEY=from-dotenv-file-material\n", encoding="utf-8"
    )
    return env_file


def test_secret_key_is_read_from_env_file(tmp_path, monkeypatch):
    """写在 .env 文件里的密钥必须被 Settings 读到。"""
    env_file = _env_file_with_secret(tmp_path)
    monkeypatch.setenv("CROSSPILOT_ENV_FILE", str(env_file))
    monkeypatch.delenv("CROSSPILOT_SECRET_KEY", raising=False)

    settings = Settings(data_dir=tmp_path / "data")

    assert settings.secret_key == "from-dotenv-file-material"


def test_explicit_secret_key_does_not_create_key_file(tmp_path, monkeypatch):
    """显式配置主密钥时，不生成密钥文件，且加解密可用。"""
    env_file = _env_file_with_secret(tmp_path)
    monkeypatch.setenv("CROSSPILOT_ENV_FILE", str(env_file))
    monkeypatch.delenv("CROSSPILOT_SECRET_KEY", raising=False)

    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir)
    box = make_secret_box(settings)()

    token = box.encrypt("hello")
    assert token != "hello"
    assert box.decrypt(token) == "hello"
    assert not (data_dir / ".secret_key").exists()


def test_missing_secret_key_falls_back_to_file(tmp_path, monkeypatch):
    """未配置主密钥时回退到密钥文件，保证本地开箱可用。"""
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("CROSSPILOT_ENV_FILE", str(empty))
    monkeypatch.delenv("CROSSPILOT_SECRET_KEY", raising=False)

    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir)
    assert settings.secret_key == ""

    box = make_secret_box(settings)()
    token = box.encrypt("hello")
    assert box.decrypt(token) == "hello"
    assert (data_dir / ".secret_key").is_file()
