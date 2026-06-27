"""鉴权模块纯逻辑回归测试。

只覆盖 src/quantforge/api/routes/auth.py 里不依赖网络/数据库的纯函数：
密码哈希与校验、JWT 生成/解码/过期、管理员判定。
不发起任何网络或 LLM 调用，也不读写真实 users.json。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from jose import jwt

from quantforge.api.routes import auth


# ── 密码哈希与校验 ──────────────────────────────────────────────────────────
def test_password_hash_roundtrip():
    """_get_password_hash 生成的哈希能被 _verify_password 验证通过。"""
    plain = "S3cret-pw"
    hashed = auth._get_password_hash(plain)
    # bcrypt 哈希不应等于明文
    assert hashed != plain
    assert auth._verify_password(plain, hashed) is True


def test_password_verify_wrong_password_fails():
    """错误密码验证失败。"""
    hashed = auth._get_password_hash("correct-horse")
    assert auth._verify_password("wrong-horse", hashed) is False


def test_password_hash_is_salted():
    """同一明文两次哈希结果不同（加盐），但都能各自验证通过。"""
    plain = "same-input"
    h1 = auth._get_password_hash(plain)
    h2 = auth._get_password_hash(plain)
    assert h1 != h2
    assert auth._verify_password(plain, h1)
    assert auth._verify_password(plain, h2)


# ── JWT ────────────────────────────────────────────────────────────────────
def test_create_access_token_decodes_username():
    """_create_access_token 生成的 token 能被 jwt.decode 用同一 secret 解出用户名。

    注意：payload 里用户名放在 'sub' 字段（见 login/register 的 data={"sub": ...}）。
    测试直接 import 模块里的 _SECRET_KEY，不依赖固定密钥值。
    """
    token = auth._create_access_token(data={"sub": "alice"})
    payload = jwt.decode(token, auth._SECRET_KEY, algorithms=[auth._ALGORITHM])
    assert payload["sub"] == "alice"
    assert "exp" in payload


def test_expired_token_is_rejected():
    """过期 token 被拒（jwt.decode 抛 ExpiredSignatureError / JWTError）。"""
    token = auth._create_access_token(
        data={"sub": "bob"},
        expires_delta=timedelta(seconds=-1),  # 立即过期
    )
    with pytest.raises(jwt.JWTError):
        jwt.decode(token, auth._SECRET_KEY, algorithms=[auth._ALGORITHM])


def test_token_wrong_secret_is_rejected():
    """用错误密钥解 token 失败。"""
    token = auth._create_access_token(data={"sub": "carol"})
    with pytest.raises(jwt.JWTError):
        jwt.decode(token, "definitely-not-the-secret", algorithms=[auth._ALGORITHM])


# ── 管理员判定 ──────────────────────────────────────────────────────────────
def test_admin_usernames_contains_defaults():
    """默认管理员（_DEFAULT_ADMINS）始终在 _admin_usernames() 中。"""
    names = auth._admin_usernames()
    assert auth._DEFAULT_ADMINS.issubset(names)


def test_admin_usernames_extends_via_env(monkeypatch):
    """通过 QF_ADMIN_USERS 环境变量可追加管理员（逗号分隔，去空白）。"""
    monkeypatch.setenv("QF_ADMIN_USERS", "newadmin, spaced_admin ")
    names = auth._admin_usernames()
    assert "newadmin" in names
    assert "spaced_admin" in names
    # 默认管理员仍在
    assert auth._DEFAULT_ADMINS.issubset(names)


def test_is_admin_by_role():
    """role=='admin' 即为管理员，不区分大小写。"""
    assert auth.is_admin({"username": "nobody", "role": "Admin"}) is True
    assert auth.is_admin({"username": "nobody", "role": "user"}) is False


def test_is_admin_by_username(monkeypatch):
    """用户名落在 _admin_usernames() 里即为管理员。"""
    monkeypatch.setenv("QF_ADMIN_USERS", "envadmin")
    assert auth.is_admin({"username": "envadmin"}) is True
    assert auth.is_admin({"username": "randomuser"}) is False


def test_is_admin_empty_user():
    """空 user 不是管理员。"""
    assert auth.is_admin({}) is False
    assert auth.is_admin(None) is False
