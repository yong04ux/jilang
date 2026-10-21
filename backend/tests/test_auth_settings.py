"""用户认证、每用户模型配置、加密与数据隔离的测试。"""
# check_secrets: allow-placeholders — 本文件的 API Key 都是构造的假值

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crosspilot.app import create_app
from crosspilot.auth import hash_password, verify_password
from crosspilot.persistence.secrets import SecretBox, SecretError


@pytest.fixture()
def fresh_app(tmp_path, monkeypatch):
    """每个测试用独立 schema 与独立加密密钥，互不干扰。"""
    monkeypatch.setenv("CROSSPILOT_SECRET_KEY", "test-secret-material")
    from crosspilot.config import get_settings
    from pg_support import database_url, reset_schema

    url = database_url()
    reset_schema(url)
    monkeypatch.setenv("CROSSPILOT_DATABASE_URL", url)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def register(client, username="alice", password="password123"):
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 加密
# ---------------------------------------------------------------------------


def test_secret_box_roundtrip_and_mask():
    box = SecretBox(material=b"unit-test")
    secret = "sk-abcdefghijklmnop1234"
    token = box.encrypt(secret)
    assert token.startswith("v1:")
    assert secret not in token
    assert box.decrypt(token) == secret
    assert SecretBox.mask(secret) == "sk-****1234"
    assert SecretBox.mask("") == ""


def test_secret_box_rejects_tampering_and_wrong_key():
    box = SecretBox(material=b"unit-test")
    token = box.encrypt("sk-abcdefghijkl")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(SecretError):
        box.decrypt(tampered)
    with pytest.raises(SecretError):
        SecretBox(material=b"another").decrypt(token)


def test_secret_box_randomizes_ciphertext():
    box = SecretBox(material=b"unit-test")
    assert box.encrypt("same-value") != box.encrypt("same-value")


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("password123")
    second = hash_password("password123")
    assert first != second, "相同密码必须产生不同哈希（加盐）"
    assert verify_password("password123", first)
    assert not verify_password("wrong-password", first)


def test_password_minimum_length():
    with pytest.raises(Exception):
        hash_password("short")


# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------


def test_first_user_becomes_admin(fresh_app):
    status = fresh_app.get("/api/auth/status").json()
    assert status["needs_setup"] is True
    assert status["user_count"] == 0

    data = register(fresh_app, "alice", "password123")
    assert data["user"]["is_admin"] is True
    assert data["user"]["username"] == "alice"
    assert "password_hash" not in data["user"]


def test_second_user_is_not_admin(fresh_app):
    register(fresh_app, "alice", "password123")
    data = register(fresh_app, "bob", "password456")
    assert data["user"]["is_admin"] is False


def test_duplicate_username_rejected(fresh_app):
    register(fresh_app, "alice", "password123")
    response = fresh_app.post(
        "/api/auth/register", json={"username": "alice", "password": "password123"}
    )
    assert response.status_code == 400
    assert "已被使用" in response.json()["detail"]


def test_weak_password_rejected(fresh_app):
    response = fresh_app.post(
        "/api/auth/register", json={"username": "alice", "password": "123"}
    )
    assert response.status_code == 400


def test_invalid_username_rejected(fresh_app):
    response = fresh_app.post(
        "/api/auth/register", json={"username": "a b", "password": "password123"}
    )
    assert response.status_code == 400


def test_login_and_me(fresh_app):
    register(fresh_app, "alice", "password123")
    fresh_app.post("/api/auth/logout")

    bad = fresh_app.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    assert bad.status_code == 401

    good = fresh_app.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert good.status_code == 200
    token = good.json()["token"]

    me = fresh_app.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "alice"


def test_protected_endpoint_requires_login(fresh_app):
    assert fresh_app.get("/api/reports").status_code == 401
    assert fresh_app.get("/api/settings/model").status_code == 401
    assert fresh_app.post("/api/analyze", json={}).status_code == 401


def test_logout_invalidates_token(fresh_app):
    token = register(fresh_app, "alice", "password123")["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert fresh_app.get("/api/auth/me", headers=headers).status_code == 200
    fresh_app.post("/api/auth/logout", headers=headers)
    assert fresh_app.get("/api/auth/me", headers=headers).status_code == 401


def test_bogus_token_rejected(fresh_app):
    assert (
        fresh_app.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}).status_code
        == 401
    )


def test_admin_only_endpoint(fresh_app):
    register(fresh_app, "alice", "password123")  # 管理员
    fresh_app.post("/api/auth/logout")
    bob = register(fresh_app, "bob", "password456")
    bob_headers = {"Authorization": f"Bearer {bob['token']}"}
    assert fresh_app.get("/api/admin/users", headers=bob_headers).status_code == 403

    fresh_app.post("/api/auth/logout")
    alice = fresh_app.post(
        "/api/auth/login", json={"username": "alice", "password": "password123"}
    ).json()
    admin_headers = {"Authorization": f"Bearer {alice['token']}"}
    response = fresh_app.get("/api/admin/users", headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json()["users"]) == 2


def test_change_password(fresh_app):
    token = register(fresh_app, "alice", "password123")["token"]
    headers = {"Authorization": f"Bearer {token}"}
    bad = fresh_app.post(
        "/api/auth/password",
        json={"current_password": "wrong", "new_password": "newpassword123"},
        headers=headers,
    )
    assert bad.status_code == 400

    ok = fresh_app.post(
        "/api/auth/password",
        json={"current_password": "password123", "new_password": "newpassword123"},
        headers=headers,
    )
    assert ok.status_code == 200

    fresh_app.post("/api/auth/logout")
    assert (
        fresh_app.post("/api/auth/login", json={"username": "alice", "password": "password123"}).status_code
        == 401
    )
    assert (
        fresh_app.post("/api/auth/login", json={"username": "alice", "password": "newpassword123"}).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# 模型配置
# ---------------------------------------------------------------------------


def test_default_settings_when_no_custom(fresh_app):
    token = register(fresh_app)["token"]
    headers = {"Authorization": f"Bearer {token}"}
    data = fresh_app.get("/api/settings/model", headers=headers).json()
    assert data["has_custom"] is False
    assert data["effective"]["source"] == "default"
    assert data["options"]["providers"] == ["rule", "deepseek", "openai"]


def test_save_model_settings_and_mask_key(fresh_app):
    token = register(fresh_app)["token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = fresh_app.put(
        "/api/settings/model",
        json={
            "provider": "deepseek",
            "model": "deepseek-flash",
            "api_key": "sk-live-abcdefghijklmnop",
            "temperature": 0.7,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["has_custom"] is True
    assert data["effective"]["source"] == "user"
    assert data["effective"]["provider"] == "deepseek"
    assert data["effective"]["has_api_key"] is True
    # 关键：绝不能回传明文
    assert "sk-live-abcdefghijklmnop" not in response.text
    assert data["effective"]["api_key"] == "sk-****mnop"


def test_api_key_is_encrypted_at_rest(fresh_app):
    token = register(fresh_app)["token"]
    headers = {"Authorization": f"Bearer {token}"}
    plaintext = "sk-should-never-appear-in-db"
    fresh_app.put(
        "/api/settings/model",
        json={"provider": "deepseek", "api_key": plaintext},
        headers=headers,
    )
    # SQLite 已移除，数据库是 PostgreSQL：直接查库确认密文而非明文
    import psycopg

    from pg_support import database_url

    with psycopg.connect(database_url()) as connection:
        row = connection.execute(
            "SELECT api_key_encrypted FROM user_model_settings"
        ).fetchone()
    assert row is not None, "配置没有落库"
    stored = row[0] or ""
    assert plaintext not in stored, "API Key 以明文写入了数据库"
    assert stored.startswith("v1:"), "未找到加密密文"


def test_empty_key_keeps_existing(fresh_app):
    token = register(fresh_app)["token"]
    headers = {"Authorization": f"Bearer {token}"}
    fresh_app.put(
        "/api/settings/model",
        json={"provider": "deepseek", "api_key": "sk-original-key-1234"},
        headers=headers,
    )
    # 只改温度，api_key 传空串表示不修改
    response = fresh_app.put(
        "/api/settings/model",
        json={"temperature": 0.2, "api_key": ""},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["effective"]["has_api_key"] is True
    assert response.json()["effective"]["temperature"] == 0.2


def test_clear_key_sentinel(fresh_app):
    token = register(fresh_app)["token"]
    headers = {"Authorization": f"Bearer {token}"}
    fresh_app.put(
        "/api/settings/model",
        json={"provider": "deepseek", "api_key": "sk-original-key-1234"},
        headers=headers,
    )
    response = fresh_app.put(
        "/api/settings/model", json={"api_key": "__CLEAR__"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["effective"]["has_api_key"] is False


def test_invalid_settings_rejected(fresh_app):
    token = register(fresh_app)["token"]
    headers = {"Authorization": f"Bearer {token}"}
    # 非法 provider
    assert (
        fresh_app.put("/api/settings/model", json={"provider": "nope"}, headers=headers).status_code
        == 422
    )
    # 温度越界
    assert (
        fresh_app.put("/api/settings/model", json={"temperature": 5}, headers=headers).status_code
        == 422
    )
    # base_url 格式
    assert (
        fresh_app.put("/api/settings/model", json={"base_url": "ftp://x"}, headers=headers).status_code
        == 422
    )
    # 把 URL 当 Key 填
    response = fresh_app.put(
        "/api/settings/model", json={"provider": "deepseek", "api_key": "https://api.x.com"}, headers=headers
    )
    assert response.status_code == 400
    assert "格式" in response.json()["detail"]


def test_settings_are_isolated_per_user(fresh_app):
    alice = register(fresh_app, "alice", "password123")
    fresh_app.post("/api/auth/logout")
    bob = register(fresh_app, "bob", "password456")

    fresh_app.put(
        "/api/settings/model",
        json={"provider": "deepseek", "model": "deepseek-v4-pro", "api_key": "sk-alice-key-9999"},
        headers={"Authorization": f"Bearer {alice['token']}"},
    )

    bob_view = fresh_app.get(
        "/api/settings/model", headers={"Authorization": f"Bearer {bob['token']}"}
    ).json()
    assert bob_view["has_custom"] is False
    assert bob_view["effective"]["source"] == "default"
    assert bob_view["effective"]["has_api_key"] is False


def test_reset_settings(fresh_app):
    token = register(fresh_app)["token"]
    headers = {"Authorization": f"Bearer {token}"}
    fresh_app.put(
        "/api/settings/model",
        json={"provider": "deepseek", "api_key": "sk-something-1234"},
        headers=headers,
    )
    response = fresh_app.delete("/api/settings/model", headers=headers)
    assert response.status_code == 200
    assert response.json()["has_custom"] is False
    assert response.json()["effective"]["source"] == "default"


def test_settings_take_effect_immediately_without_restart(fresh_app):
    """核心诉求：保存即生效，不需要重启服务。"""
    token = register(fresh_app)["token"]
    headers = {"Authorization": f"Bearer {token}"}

    before = fresh_app.get("/api/providers", headers=headers).json()
    assert before["source"] == "default"

    fresh_app.put(
        "/api/settings/model",
        json={"provider": "deepseek", "model": "deepseek-flash", "api_key": "sk-immediate-1234"},
        headers=headers,
    )

    after = fresh_app.get("/api/providers", headers=headers).json()
    assert after["source"] == "user"
    assert after["model"] == "deepseek-flash"
    assert after["active"] == "deepseek"


def test_test_endpoint_reports_missing_key(fresh_app):
    token = register(fresh_app)["token"]
    headers = {"Authorization": f"Bearer {token}"}
    response = fresh_app.post(
        "/api/settings/model/test",
        json={"provider": "deepseek", "model": "deepseek-flash"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "API Key" in response.json()["detail"]


def test_test_endpoint_rule_always_ok(fresh_app):
    token = register(fresh_app)["token"]
    headers = {"Authorization": f"Bearer {token}"}
    response = fresh_app.post("/api/settings/model/test", json={"provider": "rule"}, headers=headers)
    assert response.json()["ok"] is True


# ---------------------------------------------------------------------------
# 数据隔离
# ---------------------------------------------------------------------------


DEMO_ANALYSIS = {
    "product_name": "Test Bottle",
    "platform": "amazon",
    "marketplace": "US",
    "competitors": [
        {
            "name": "Comp A",
            "price": 20,
            "key_features": ["leak proof"],
            "reviews": [{"rating": 1, "text": "The lid leaked after a week."}],
        }
    ],
    "keywords": [],
}


def test_history_is_isolated_between_users(fresh_app):
    alice = register(fresh_app, "alice", "password123")
    alice_headers = {"Authorization": f"Bearer {alice['token']}"}
    fresh_app.post("/api/auth/logout", headers=alice_headers)
    bob = register(fresh_app, "bob", "password456")
    bob_headers = {"Authorization": f"Bearer {bob['token']}"}

    created = fresh_app.post("/api/analyze", json=DEMO_ANALYSIS, headers=bob_headers)
    assert created.status_code == 200
    report_id = created.json()["report"]["report_id"]

    bob_list = fresh_app.get("/api/reports", headers=bob_headers).json()["items"]
    assert any(item["report_id"] == report_id for item in bob_list)

    # Alice 之前登出过，重新登录拿新令牌
    alice_token = fresh_app.post(
        "/api/auth/login", json={"username": "alice", "password": "password123"}
    ).json()["token"]
    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    alice_list = fresh_app.get("/api/reports", headers=alice_headers).json()["items"]
    assert alice_list == [], "Alice 不应看到 Bob 的报告"

    # 跨用户直接按 id 访问必须 404，而不是泄露内容
    cross = fresh_app.get(f"/api/reports/{report_id}", headers=alice_headers)
    assert cross.status_code == 404


def test_legacy_records_are_not_auto_assigned(fresh_app, tmp_path):
    """启用账号前产生的历史数据，不应被自动塞给第一个用户。"""
    # 直接写入一条 user_id 为空的记录，模拟旧数据
    from crosspilot.persistence.db import Database
    from pg_support import database_url

    db = Database(database_url())
    db.save_report({"report_id": "legacy-1", "product_name": "Old", "platform": "amazon", "marketplace": "US", "data_provenance": {}}, user_id=None)

    alice = register(fresh_app, "alice", "password123")
    headers = {"Authorization": f"Bearer {alice['token']}"}
    listed = fresh_app.get("/api/reports", headers=headers).json()["items"]
    assert listed == [], "遗留数据不应自动归属"

    legacy = fresh_app.get("/api/admin/users", headers=headers).json()["legacy"]
    assert legacy["reports"] == 1

    claimed = fresh_app.post("/api/admin/claim-legacy", headers=headers).json()
    assert claimed["claimed"]["reports"] == 1
    after = fresh_app.get("/api/reports", headers=headers).json()["items"]
    assert len(after) == 1


def test_health_is_public(fresh_app):
    response = fresh_app.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["configured_model"] is None
