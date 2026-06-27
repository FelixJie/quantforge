"""飞书消息抓取 — OAuth 用户授权 + 群消息拉取。

授权流程
========
1. 前端打开 GET /api/feishu/auth-url 返回的链接（飞书网页授权）
2. 用户确认，飞书跳回 GET /api/feishu/callback?code=xxx
3. 后端用 code + app_access_token 换 user_access_token / refresh_token，存 app_config
4. 后台每 90 分钟用 refresh_token 自动续期（UAT 有效期 2h，RT 有效期 30 天）

所需飞书权限
============
im:message:readonly   读取消息
im:chat:readonly      读取群列表
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.parse
from typing import Optional

import requests
from loguru import logger

_BASE = "https://open.feishu.cn/open-apis"
_TIMEOUT = 15

# app_access_token 内存缓存（有效期 2h，提前 5min 刷新）
_aat: dict = {"token": "", "expire_at": 0.0}
_aat_lock = threading.Lock()

# tenant_access_token 内存缓存（应用身份，自动授权用，有效期 2h，提前 5min 刷新）
_tat: dict = {"token": "", "expire_at": 0.0}
_tat_lock = threading.Lock()


class FeishuError(Exception):
    pass


class FeishuAuthError(FeishuError):
    """user_access_token / refresh_token 失效，需重新 OAuth 授权。"""


# ── app_access_token ──────────────────────────────────────────────────────

def get_app_access_token(app_id: str, app_secret: str) -> str:
    now = time.time()
    with _aat_lock:
        if _aat["token"] and _aat["expire_at"] > now + 300:
            return _aat["token"]
    try:
        r = requests.post(
            f"{_BASE}/auth/v3/app_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=_TIMEOUT,
        )
        d = r.json()
    except Exception as exc:
        raise FeishuError(f"获取 app_access_token 失败: {exc}") from exc
    if d.get("code") != 0:
        raise FeishuError(f"app_access_token 错误: {d}")
    token = d["app_access_token"]
    expire = int(d.get("expire", 7200))
    with _aat_lock:
        _aat["token"] = token
        _aat["expire_at"] = now + expire
    return token


# ── tenant_access_token（应用身份，自动授权，无需用户 OAuth）────────────────

def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    """换取 tenant_access_token（应用身份），用于直接读取机器人所在群的消息。

    与用户授权不同，这条通路完全不需要用户点确认；前提是应用（机器人）已被拉进
    目标群，且具备 im:message / im:chat 读权限。
    """
    now = time.time()
    with _tat_lock:
        if _tat["token"] and _tat["expire_at"] > now + 300:
            return _tat["token"]
    try:
        r = requests.post(
            f"{_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=_TIMEOUT,
        )
        d = r.json()
    except Exception as exc:
        raise FeishuError(f"获取 tenant_access_token 失败: {exc}") from exc
    if d.get("code") != 0:
        raise FeishuError(f"tenant_access_token 错误: {d}")
    token = d["tenant_access_token"]
    expire = int(d.get("expire", 7200))
    with _tat_lock:
        _tat["token"] = token
        _tat["expire_at"] = now + expire
    return token


# ── OAuth ─────────────────────────────────────────────────────────────────

def build_auth_url(app_id: str, redirect_uri: str) -> str:
    params = {
        "app_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": "im:message:readonly im:chat:readonly",
        "state": "feishu_oauth",
    }
    return f"{_BASE}/authen/v1/authorize?" + urllib.parse.urlencode(params)


def exchange_code(app_id: str, app_secret: str, code: str) -> dict:
    """用 code 换 user_access_token + refresh_token。

    返回 {access_token, refresh_token, expire_in, open_id, name}。
    """
    aat = get_app_access_token(app_id, app_secret)
    try:
        r = requests.post(
            f"{_BASE}/authen/v1/oidc/access_token",
            json={"grant_type": "authorization_code", "code": code},
            headers={"Authorization": f"Bearer {aat}"},
            timeout=_TIMEOUT,
        )
        d = r.json()
    except Exception as exc:
        raise FeishuError(f"换取 user_access_token 失败: {exc}") from exc
    if d.get("code") != 0:
        raise FeishuError(f"exchange_code 失败: {d}")
    data = d.get("data") or {}
    return {
        "access_token": data.get("access_token", ""),
        "refresh_token": data.get("refresh_token", ""),
        "expire_in": data.get("expires_in", 7200),
        "open_id": data.get("open_id", ""),
        "name": data.get("name", ""),
    }


def refresh_user_token(app_id: str, app_secret: str, refresh_token: str) -> dict:
    """用 refresh_token 续期，返回新的 {access_token, refresh_token, expire_in}。"""
    aat = get_app_access_token(app_id, app_secret)
    try:
        r = requests.post(
            f"{_BASE}/authen/v1/oidc/refresh_access_token",
            json={"grant_type": "refresh_token", "refresh_token": refresh_token},
            headers={"Authorization": f"Bearer {aat}"},
            timeout=_TIMEOUT,
        )
        d = r.json()
    except Exception as exc:
        raise FeishuError(f"刷新 user_access_token 失败: {exc}") from exc
    if d.get("code") != 0:
        if d.get("code") in (99991663, 99991661, 99991664, 99991668):
            raise FeishuAuthError(f"refresh_token 已失效（code={d.get('code')}），需重新授权")
        raise FeishuError(f"refresh_user_token 失败: {d}")
    data = d.get("data") or {}
    return {
        "access_token": data.get("access_token", ""),
        "refresh_token": data.get("refresh_token", ""),
        "expire_in": data.get("expires_in", 7200),
    }


# ── 群列表 ────────────────────────────────────────────────────────────────

def _uat_headers(uat: str) -> dict:
    return {"Authorization": f"Bearer {uat}", "Content-Type": "application/json; charset=utf-8"}


def _is_auth_error(code: int) -> bool:
    return code in (99991663, 99991661, 99991664, 99991668)


def list_chats(uat: str, page_size: int = 100) -> list[dict]:
    """列出用户所在的全部群（分页，最多 400 个）。"""
    chats: list[dict] = []
    page_token: Optional[str] = None
    for _ in range(4):
        params: dict = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        try:
            r = requests.get(f"{_BASE}/im/v1/chats", headers=_uat_headers(uat),
                             params=params, timeout=_TIMEOUT)
            d = r.json()
        except Exception as exc:
            raise FeishuError(f"list_chats 失败: {exc}") from exc
        if d.get("code") != 0:
            if _is_auth_error(d.get("code", 0)):
                raise FeishuAuthError(f"list_chats 鉴权失败: {d}")
            raise FeishuError(f"list_chats 错误: {d}")
        data = d.get("data") or {}
        for item in (data.get("items") or []):
            chats.append({
                "chat_id": item.get("chat_id", ""),
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "avatar": item.get("avatar", ""),
                "chat_type": item.get("chat_type", ""),
            })
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return chats


# ── 消息列表 ──────────────────────────────────────────────────────────────

def fetch_messages(uat: str, chat_id: str,
                   start_time: Optional[int] = None,
                   end_time: Optional[int] = None,
                   page_size: int = 50) -> list[dict]:
    """拉取某群一页消息（按时间范围，时间戳单位：秒）。"""
    params: dict = {
        "container_id_type": "chat",
        "container_id": chat_id,
        "page_size": page_size,
        "sort_type": "ByCreateTimeDesc",
    }
    if start_time:
        params["start_time"] = str(start_time)
    if end_time:
        params["end_time"] = str(end_time)
    try:
        r = requests.get(f"{_BASE}/im/v1/messages", headers=_uat_headers(uat),
                         params=params, timeout=_TIMEOUT)
        d = r.json()
    except Exception as exc:
        raise FeishuError(f"fetch_messages({chat_id}) 失败: {exc}") from exc
    if d.get("code") != 0:
        if _is_auth_error(d.get("code", 0)):
            raise FeishuAuthError(f"fetch_messages 鉴权失败: {d}")
        logger.debug(f"fetch_messages({chat_id}) code={d.get('code')}: {d}")
        return []
    return (d.get("data") or {}).get("items") or []


# ── 消息解析 ──────────────────────────────────────────────────────────────

def parse_message(msg: dict, chat_id: str = "", chat_name: str = "") -> dict:
    """把一条原始飞书消息归一化为入库结构。"""
    msg_id = msg.get("message_id", "")
    msg_type = msg.get("msg_type", "text")
    sender = msg.get("sender") or {}
    sender_id = sender.get("id", "")
    sender_type = sender.get("sender_type", "user")
    create_ms = int(msg.get("create_time") or 0)
    created_at = (dt.datetime.fromtimestamp(create_ms / 1000).isoformat()
                  if create_ms else "")
    content_raw = (msg.get("body") or {}).get("content", "")
    content_text = _extract_text(msg_type, content_raw)
    return {
        "message_id": msg_id,
        "chat_id": chat_id,
        "chat_name": chat_name,
        "sender_id": sender_id,
        "sender_type": sender_type,
        "msg_type": msg_type,
        "content_text": content_text,
        "content_raw": content_raw,
        "created_at": created_at,
    }


def _extract_text(msg_type: str, content_raw: str) -> str:
    """从 body.content（JSON 字符串）提取纯文本。"""
    if not content_raw:
        return ""
    try:
        data = json.loads(content_raw)
    except Exception:
        return content_raw[:500]

    if msg_type == "text":
        return (data.get("text") or "").strip()

    # 富文本(post)/卡片(interactive)：结构相近，统一解析
    #   post:        {zh_cn|en_us: {title, content: [[{tag,text}]]}} 或直接 {title, content}
    #   interactive: {title, elements: [[{tag:text}, {tag:a, href}]]}（多为图片）
    if msg_type in ("post", "interactive"):
        return _extract_rich(data)

    if msg_type == "system":
        return _extract_system(data)

    _TYPE_LABELS = {
        "image": "[图片]", "file": "[文件]", "sticker": "[表情包]",
        "audio": "[语音]", "video": "[视频]", "merge_forward": "[合并转发]",
        "location": "[位置]", "share_user": "[名片]", "share_chat": "[群名片]",
    }
    if msg_type in _TYPE_LABELS:
        if msg_type == "file":
            name = data.get("file_name", "")
            return f"[文件: {name}]" if name else "[文件]"
        return _TYPE_LABELS[msg_type]

    return str(data)[:200]


def _extract_rich(data: dict) -> str:
    """解析富文本/卡片为纯文本(含图片用 markdown ![](url) 表达，前端可渲染)。

    兼容 post 的 {zh_cn:{title,content}} / {title,content} 与 interactive 的
    {title, elements}。元素 tag 支持 text / a / at / img。
    """
    node = data.get("zh_cn") or data.get("en_us") or data
    title = (node.get("title") or "").strip()
    rows = node.get("content") or node.get("elements") or []

    lines: list[str] = []
    if title:
        lines.append(title)
    for row in (rows or []):
        seg: list[str] = []
        for elem in (row or []):
            if not isinstance(elem, dict):
                continue
            tag = (elem.get("tag") or "").lower()
            if tag == "text":
                seg.append(elem.get("text", ""))
            elif tag == "a":
                # 飞书卡片里图片常以 ![图片]( + a.href(末尾带")") 两段拼出
                seg.append(elem.get("href", "") or elem.get("text", ""))
            elif tag == "at":
                seg.append(f"@{elem.get('user_name', '')}")
            elif tag in ("img", "image"):
                url = elem.get("image_url") or elem.get("url") or ""
                if url:
                    seg.append(f"![图片]({url})")
        line = "".join(seg).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def _extract_system(data: dict) -> str:
    """系统消息(入群/撤回等)：套用模板并填充用户名，英文常见入群语翻成中文。"""
    tmpl = (data.get("template") or "").strip()
    if not tmpl:
        return "[系统消息]"

    def _names(key: str) -> str:
        vals = data.get(key) or []
        return "、".join(str(v) for v in vals) if isinstance(vals, list) else str(vals)

    out = tmpl.replace("{to_chatters}", _names("to_chatters")) \
              .replace("{from_user}", _names("from_user"))
    # 高频英文入群提示 → 中文
    if "joined the group" in tmpl:
        to = _names("to_chatters") or "新成员"
        frm = _names("from_user")
        return f"{to} 加入了群聊" + (f"（由 {frm} 邀请）" if frm else "")
    return out.strip() or "[系统消息]"
