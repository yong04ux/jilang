"""``CROSSPILOT_ENV_FILE`` / ``--env`` 的解析规则。

背景：一套配置连本地 Docker PostgreSQL，另一套连线上 Supabase。切换靠
``--env local|cloud``，底层都是改写 ``CROSSPILOT_ENV_FILE``。

这里锁住三件容易回归的事：

1. 相对文件名按 **backend/ 工程根**解析，不跟着当前工作目录跑
   （否则从仓库根启动就找不到配置，静默用上默认值）；
2. 文件不存在时**报错**，不退回默认配置。静默退回是最坏的失败方式：
   以为连着线上库，实际写进了本地库；
3. ``--env local`` 就是默认的 ``.env``，不额外复制一份内容。
"""

from __future__ import annotations

import pytest

from crosspilot import cli
from crosspilot.config import BACKEND_ROOT, resolve_env_file


def test_default_env_file_is_backend_dot_env(monkeypatch):
    monkeypatch.delenv("CROSSPILOT_ENV_FILE", raising=False)

    assert resolve_env_file() == str(BACKEND_ROOT / ".env")


def test_relative_name_resolves_against_backend_root(monkeypatch, tmp_path):
    """即使当前工作目录是别处，也必须在 backend/ 下找。"""
    env_file = BACKEND_ROOT / ".env.__pytest_probe__"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CROSSPILOT_ENV_FILE", ".env.__pytest_probe__")

    try:
        assert resolve_env_file() == str(env_file)
    finally:
        env_file.unlink()


def test_missing_env_file_raises_instead_of_silent_fallback(monkeypatch):
    monkeypatch.setenv("CROSSPILOT_ENV_FILE", ".env.definitely-not-here")

    with pytest.raises(FileNotFoundError) as excinfo:
        resolve_env_file()
    assert "不存在" in str(excinfo.value)


def test_env_alias_local_points_to_default_env(monkeypatch, tmp_path):
    """``--env local`` 与不带参数等价。"""
    monkeypatch.setattr(cli, "BACKEND_ROOT", tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / ".env.cloud").write_text("", encoding="utf-8")
    monkeypatch.delenv("CROSSPILOT_ENV_FILE", raising=False)

    chosen = cli._apply_env_choice("local")

    assert chosen == tmp_path / ".env"
    assert resolve_env_file() == str(tmp_path / ".env")


def test_env_name_builds_dot_env_prefix(monkeypatch, tmp_path):
    """``--env cloud`` → ``.env.cloud``。"""
    monkeypatch.setattr(cli, "BACKEND_ROOT", tmp_path)
    (tmp_path / ".env.cloud").write_text("CROSSPILOT_PORT=9000\n", encoding="utf-8")
    monkeypatch.delenv("CROSSPILOT_ENV_FILE", raising=False)

    chosen = cli._apply_env_choice("cloud")

    assert chosen == tmp_path / ".env.cloud"
    assert resolve_env_file() == str(tmp_path / ".env.cloud")


def test_unknown_env_name_exits_with_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "BACKEND_ROOT", tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        cli._apply_env_choice("staging")
    assert ".env.staging" in str(excinfo.value)
