"""User authentication API — register, login, JWT tokens."""

from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from loguru import logger
from pydantic import BaseModel, EmailStr, Field
import bcrypt

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Security & Persistence ─────────────────────────────────────────────────
_DATA_DIR = Path(__file__).parent.parent.parent.parent.parent / "data"
_USERS_FILE = _DATA_DIR / "users.json"
def _resolve_secret_key() -> str:
    """决定 JWT 签名密钥。优先级：

    1. 环境变量 QF_JWT_SECRET（推荐，多机/多 worker 共用同一把）；
    2. 落盘的 data/.jwt_secret（首次自动生成并持久化）。

    绝不退回「进程内随机密钥」——那会让多 worker 各持一把、每次重启又换，
    导致 token 频繁失效、前端被反复踢回登录页（一直在登录的根因）。
    """
    env = os.getenv("QF_JWT_SECRET", "").strip()
    if env:
        return env

    secret_file = _DATA_DIR / ".jwt_secret"
    try:
        existing = secret_file.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    except Exception as exc:  # 读异常也不致命，继续尝试生成
        logger.warning(f"读取持久化 JWT 密钥失败：{exc}")

    # 首次生成并落盘。多 worker 同时首启会竞争写入：用 O_EXCL 排他创建，
    # 只有一个 worker 写成功，其余在 FileExistsError 后回读它写的密钥，
    # 保证所有进程内存里的密钥与文件一致。
    new_secret = secrets.token_urlsafe(48)
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(secret_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, new_secret.encode("utf-8"))
        finally:
            os.close(fd)
        logger.warning(
            "未设置 QF_JWT_SECRET，已生成并持久化到 data/.jwt_secret "
            "（多 worker/重启间共用，token 不再频繁失效）。"
            "生产建议在 .env 显式配置 QF_JWT_SECRET。"
        )
        return new_secret
    except FileExistsError:
        # 另一个 worker 抢先写了——回读它的密钥。
        try:
            return secret_file.read_text(encoding="utf-8").strip() or new_secret
        except Exception:
            return new_secret
    except Exception as exc:
        # 落盘失败（如只读文件系统）：最后再回读一次以防其他 worker 已写成功。
        try:
            existing = secret_file.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except Exception:
            pass
        logger.error(
            f"无法持久化 JWT 密钥（{exc}），本进程退回临时密钥——"
            "请尽快在 .env 设置 QF_JWT_SECRET。"
        )
        return new_secret


_SECRET_KEY = _resolve_secret_key()
_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")
# 软鉴权：和上面用同一个 tokenUrl，但 auto_error=False —— 没带/带错 token
# 时返回 None 而不是抛 401。用于「可匿名但想识别账号」的端点（如聊天记账）。
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


# ── 管理员判定（两级）───────────────────────────────────────────────────────
# 超级管理员（super admin）：全局最高权限，唯一可「配置管理员」（增删其他管理员）
#   的角色。固定为 liuhuajie，可经 QF_SUPER_ADMINS（逗号分隔）扩展。超管恒为
#   管理员、且不可被任何人撤销。
# 普通管理员（admin）：可访问后台各模块，但不能增删管理员。来源有三：
#   ①users.json 里 role=="admin"；②环境变量 QF_ADMIN_USERS / 内置默认清单
#   （锁定，后台不可撤销）；③超管在后台配置、持久化在 app_config 的名单（可撤销）。
# 后台模块对非管理员完全不可见（接口 403、前端无入口）。
_DEFAULT_ADMINS = {"liuhuajie", "Xin"}
# 超级管理员：全局最高，唯一能配置管理员。liuhuajie 写死，QF_SUPER_ADMINS 可补充。
_DEFAULT_SUPER_ADMINS = {"liuhuajie"}
# app_config 里持久化的、可由超管在后台增删的管理员名单（JSON 用户名数组）。
_MANAGED_ADMINS_KEY = "admin_usernames"


def _super_admins() -> set[str]:
    env = os.getenv("QF_SUPER_ADMINS", "")
    names = {n.strip() for n in env.split(",") if n.strip()}
    return names | _DEFAULT_SUPER_ADMINS


def _locked_admins() -> set[str]:
    """锁定管理员：环境变量 QF_ADMIN_USERS + 内置默认清单 + 超级管理员。后台不可撤销。"""
    env = os.getenv("QF_ADMIN_USERS", "")
    names = {n.strip() for n in env.split(",") if n.strip()}
    return names | _DEFAULT_ADMINS | _super_admins()


def _managed_admins() -> set[str]:
    """超管在后台增删的管理员名单（持久化在 app_config，跨重启/多 worker 共享）。"""
    from quantforge.data.storage import db_cache

    raw = db_cache.app_config_get(_MANAGED_ADMINS_KEY)
    if not raw:
        return set()
    try:
        return {str(n).strip() for n in json.loads(raw) if str(n).strip()}
    except Exception:
        return set()


def _save_managed_admins(names: set[str]) -> None:
    from quantforge.data.storage import db_cache

    db_cache.app_config_set(
        _MANAGED_ADMINS_KEY,
        json.dumps(sorted(n for n in names if n), ensure_ascii=False),
    )


def _admin_usernames() -> set[str]:
    return _locked_admins() | _managed_admins()


def is_admin(user: dict) -> bool:
    if not user:
        return False
    if str(user.get("role", "")).lower() == "admin":
        return True
    return user.get("username") in _admin_usernames()


def is_super_admin(user: dict) -> bool:
    """是否为超级管理员（全局最高，唯一可配置管理员）。"""
    if not user:
        return False
    return user.get("username") in _super_admins()


def is_env_admin(username: str) -> bool:
    """该账号是否为锁定管理员（环境/内置/超管）——后台不可撤销。"""
    return username in _locked_admins()


def add_managed_admin(username: str) -> None:
    """把某用户名加入后台管理员名单（即便尚未注册，登录后即生效＝预授权）。"""
    username = (username or "").strip()
    if not username:
        return
    names = _managed_admins()
    names.add(username)
    _save_managed_admins(names)


def remove_managed_admin(username: str) -> None:
    """从后台管理员名单移除某用户名，并清掉其在 users.json 可能存在的 role=admin。

    锁定管理员（env/内置/超管）不在此名单内、清不掉，调用方需先用 ``is_env_admin``
    或 ``is_super_admin`` 拦下。
    """
    username = (username or "").strip()
    names = _managed_admins()
    if username in names:
        names.discard(username)
        _save_managed_admins(names)
    # 历史上可能通过 role 字段授予过，一并清掉，避免撤销后仍是管理员
    data = _load_users()
    changed = False
    for u in data["users"]:
        if u["username"] == username and str(u.get("role", "")).lower() == "admin":
            u.pop("role", None)
            changed = True
    if changed:
        _save_users(data)


def list_admins() -> list[dict]:
    """当前所有管理员，供后台配置面板展示。

    合并：超管 + 锁定清单(env/内置) + 后台名单 + users.json 里 role==admin 的账号。
    每条标 ``super``（超级管理员）、``locked``（不可撤销）、``registered``（是否已注册）。
    """
    users = _load_users().get("users", [])
    registered = {u["username"] for u in users}
    role_admins = {u["username"] for u in users
                   if str(u.get("role", "")).lower() == "admin"}
    supers = _super_admins()
    locked = _locked_admins()
    managed = _managed_admins()
    out = []
    for name in sorted(locked | managed | role_admins):
        out.append({
            "username": name,
            "super": name in supers,
            "locked": name in locked,
            "registered": name in registered,
        })
    # 超管排最前
    out.sort(key=lambda a: (not a["super"], a["username"]))
    return out


def _load_users() -> dict:
    if _USERS_FILE.exists():
        try:
            return json.loads(_USERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"users": []}


def _save_users(data: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _USERS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _get_user_by_username(username: str) -> Optional[dict]:
    data = _load_users()
    for user in data["users"]:
        if user["username"] == username:
            return user
    return None


def _get_user_by_email(email: str) -> Optional[dict]:
    data = _load_users()
    for user in data["users"]:
        if user["email"] == email:
            return user
    return None


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def _get_password_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')


def _create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, _SECRET_KEY, algorithm=_ALGORITHM)
    return encoded_jwt


# ── Schemas ────────────────────────────────────────────────────────────────
class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=64)


class User(UserBase):
    id: str
    created_at: str
    is_admin: bool = False
    is_super: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str
    user: User


class TokenData(BaseModel):
    username: Optional[str] = None


# ── Dependency: Get current user ──────────────────────────────────────────
async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = _get_user_by_username(token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme_optional),
) -> Optional[dict]:
    """Resolve the current user if a valid token is present, else None.

    Never raises — used by endpoints that work anonymously but want to attribute
    activity (e.g. LLM token usage) to a logged-in account when possible.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        username = payload.get("sub")
    except JWTError:
        return None
    if not username:
        return None
    return _get_user_by_username(username)


async def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Require an authenticated **admin** user; 403 for everyone else."""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


async def get_super_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Require an authenticated **super admin**; only they can configure admins."""
    if not is_super_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅超级管理员可配置管理员",
        )
    return current_user


def list_users_public() -> list[dict]:
    """All users without secrets (for the admin console)."""
    out = []
    for u in _load_users().get("users", []):
        out.append({
            "id": u["id"],
            "username": u["username"],
            "email": u.get("email", ""),
            "created_at": u.get("created_at", ""),
            "is_admin": is_admin(u),
            "is_super": is_super_admin(u),
            # 锁定管理员（环境/内置/超管），后台开关无法撤销——前端据此禁用操作
            "env_admin": is_env_admin(u["username"]),
        })
    return out


def set_user_admin(user_id: str, make_admin: bool) -> dict:
    """授予 / 撤销某已注册账号的管理员权限（写后台名单，超管专用）。

    通过 ``add/remove_managed_admin`` 落到 app_config 的可撤销名单。锁定管理员
    （环境/内置/超管）不受影响。返回更新后的公开用户信息。找不到账号抛 KeyError。
    """
    target = None
    for u in _load_users()["users"]:
        if u["id"] == user_id:
            target = u
            break
    if target is None:
        raise KeyError(user_id)
    username = target["username"]
    if make_admin:
        add_managed_admin(username)
    else:
        remove_managed_admin(username)
    target = _get_user_by_username(username) or target
    return {
        "id": target["id"],
        "username": username,
        "email": target.get("email", ""),
        "created_at": target.get("created_at", ""),
        "is_admin": is_admin(target),
        "is_super": is_super_admin(target),
        "env_admin": is_env_admin(username),
    }


# ── Routes ────────────────────────────────────────────────────────────────
@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate):
    data = _load_users()
    if _get_user_by_username(user_in.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )
    if _get_user_by_email(user_in.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = {
        "id": str(uuid.uuid4()),
        "username": user_in.username,
        "email": user_in.email,
        "hashed_password": _get_password_hash(user_in.password),
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    data["users"].append(user)
    _save_users(data)

    access_token = _create_access_token(data={"sub": user["username"]})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": User(
            id=user["id"],
            username=user["username"],
            email=user["email"],
            created_at=user["created_at"],
            is_admin=is_admin(user),
            is_super=is_super_admin(user),
        ),
    }


@router.post("/token", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = _get_user_by_username(form_data.username)
    if not user or not _verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = _create_access_token(data={"sub": user["username"]})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": User(
            id=user["id"],
            username=user["username"],
            email=user["email"],
            created_at=user["created_at"],
            is_admin=is_admin(user),
            is_super=is_super_admin(user),
        ),
    }


@router.get("/me", response_model=User)
def read_users_me(current_user: dict = Depends(get_current_user)):
    return User(
        id=current_user["id"],
        username=current_user["username"],
        email=current_user["email"],
        created_at=current_user["created_at"],
        is_admin=is_admin(current_user),
        is_super=is_super_admin(current_user),
    )
