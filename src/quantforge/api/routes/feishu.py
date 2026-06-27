"""飞书群消息抓取 API。

OAuth 用户授权 → 拉取用户所在全部群的消息 → 存入 feishu_messages 表。
后台每 30 分钟增量拉一轮。

端点::
    GET  /api/feishu/auth-url      获取飞书授权 URL（前端跳转用）
    GET  /api/feishu/callback      OAuth 回调（飞书跳回，code→token）
    GET  /api/feishu/chats         已缓存群列表
    GET  /api/feishu/messages      消息列表（分页/搜索/群过滤）
    POST /api/feishu/refresh       立即抓取一轮
    GET  /api/feishu/status        抓取状态
    GET  /api/feishu/config        当前配置
    PUT  /api/feishu/config        更新 App ID / App Secret
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from loguru import logger
from pydantic import BaseModel

from quantforge.api.routes.auth import get_current_user
from quantforge.api import ai_client
from quantforge.data.storage import db_cache
from quantforge.data.feed import feishu as _fs

router = APIRouter(prefix="/feishu", tags=["feishu"])

# ── 群标签偏好（全部群可见 + 自定义顺序 + 每群多前缀过滤 + 计入汇总）─────────
# 偏好存 app_config 一个 JSON（feishu:group_prefs）：
#   {
#     "order":   [chat_id, ...],          # 标签显示顺序（不在表里的群按群名补到末尾）
#     "summary": [chat_id, ...],          # 计入每日汇总的群（空=全部群都汇总）
#     "markers": {chat_id: [前缀, ...]},   # 该群只看「机器人转发中以此开头」的消息（可多选）
#   }
# 例：震哥群 markers=["3","胡汉三"] = 只看正文以「3：」「3:」「胡汉三：」「胡汉三:」开头的转发。
_CFG_GROUP_PREFS = "feishu:group_prefs"
_LEGACY_ZHENGE_MARKER = "feishu:marker_zhenge"   # 旧单群标记，启动时迁移一次


def _markers_to_prefixes(markers: list[str] | None) -> list[str]:
    """多标记 → 正文起始前缀列表（每个标记产生全角/半角冒号两种）；空返回 []。"""
    out: list[str] = []
    for m in markers or []:
        m = (m or "").strip()
        if m:
            out += [f"{m}：", f"{m}:"]
    return out


_WS_RE = re.compile(r"\s+")
_MARKER_HEAD_RE = re.compile(r"^[^\s：:]{1,12}[：:]")  # 去掉「发言人/标记：」前缀再比对


def _norm_content(text: str) -> str:
    """正文归一化指纹（用于跨群去重）：去发言前缀、压空白、取前 120 字。"""
    t = (text or "").strip()
    t = _MARKER_HEAD_RE.sub("", t, count=1).strip()
    t = _WS_RE.sub("", t)
    return t[:120]


def _dedup_messages(msgs: list[dict]) -> list[dict]:
    """同一条（或转发同源）消息在多个群重复时只保留第一条。"""
    seen: set[str] = set()
    out: list[dict] = []
    for m in msgs:
        key = _norm_content(m.get("content_text", ""))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(m)
    return out

# ── 配置键 ────────────────────────────────────────────────────────────────
_CFG_APP_ID       = "feishu:app_id"
_CFG_APP_SECRET   = "feishu:app_secret"
_CFG_UAT          = "feishu:user_access_token"
_CFG_RT           = "feishu:refresh_token"
_CFG_UAT_EXPIRE   = "feishu:uat_expire_at"   # Unix 时间戳（字符串）
_CFG_OPEN_ID      = "feishu:open_id"
_CFG_USER_NAME    = "feishu:user_name"
_CFG_ENABLED      = "feishu:enabled"
_CFG_REDIRECT_URI = "feishu:redirect_uri"
_CFG_AUTH_MODE    = "feishu:auth_mode"   # "tenant"=应用身份自动授权(默认) / "user"=OAuth用户授权

_DEFAULT_APP_ID     = os.getenv("QF_FEISHU_APP_ID", "")
_DEFAULT_APP_SECRET = os.getenv("QF_FEISHU_APP_SECRET", "")
_DEFAULT_REDIRECT   = os.getenv("QF_FEISHU_REDIRECT", "http://106.12.146.52/api/feishu/callback")

_CRAWL_INTERVAL = 1800   # 30 分钟增量拉一轮
_MSG_PAGE_SIZE  = 50     # 每次每群拉 N 条
_LOOKBACK_DAYS  = 7      # 首次抓取回溯天数

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="feishu")
_last_status: dict = {"at": None, "ok": None, "added": 0, "error": "", "chats": 0}


async def _run(fn, *args):
    return await asyncio.get_event_loop().run_in_executor(_EXECUTOR, fn, *args)


# ── 配置读写 ──────────────────────────────────────────────────────────────

def _cfg(key: str, default: str = "") -> str:
    return db_cache.app_config_get(key, default) or default


def _set_cfg(key: str, val: str) -> None:
    db_cache.app_config_set(key, val)


def _get_app_id() -> str:
    return _cfg(_CFG_APP_ID, _DEFAULT_APP_ID)


def _get_app_secret() -> str:
    return _cfg(_CFG_APP_SECRET, _DEFAULT_APP_SECRET)


def _get_redirect_uri() -> str:
    return _cfg(_CFG_REDIRECT_URI, _DEFAULT_REDIRECT)


def _get_uat() -> str:
    return _cfg(_CFG_UAT, "")


def _get_rt() -> str:
    return _cfg(_CFG_RT, "")


def _is_enabled() -> bool:
    return _cfg(_CFG_ENABLED, "1") == "1"


def _auth_mode() -> str:
    """授权模式：默认 'tenant'（应用身份自动授权，无需用户点确认）。"""
    return _cfg(_CFG_AUTH_MODE, "tenant").strip() or "tenant"


def _is_tenant_mode() -> bool:
    return _auth_mode() == "tenant"


def _has_auth() -> bool:
    """是否具备抓取所需凭据：应用身份模式恒为真（自动授权）；用户模式看是否已 OAuth。"""
    return True if _is_tenant_mode() else bool(_get_uat())


# ── 群标签偏好读写 ──────────────────────────────────────────────────────────

def _load_prefs() -> dict:
    """读取群标签偏好 JSON（容错 + 补默认键）。"""
    raw = _cfg(_CFG_GROUP_PREFS, "")
    prefs: dict = {}
    if raw:
        try:
            prefs = json.loads(raw)
        except Exception:
            prefs = {}
    if not isinstance(prefs, dict):
        prefs = {}
    prefs.setdefault("order", [])
    prefs.setdefault("summary", [])
    prefs.setdefault("markers", {})
    # 旧单群「震哥」标记一次性迁移：按群名找到 chat_id 写进 markers
    legacy = _cfg(_LEGACY_ZHENGE_MARKER, "")
    if legacy and not prefs["markers"]:
        for c in db_cache.feishu_list_chats():
            if "震哥" in (c.get("name") or ""):
                prefs["markers"][c.get("chat_id", "")] = [legacy.strip()]
                _save_prefs(prefs)
                _set_cfg(_LEGACY_ZHENGE_MARKER, "")
                break
    return prefs


def _save_prefs(prefs: dict) -> None:
    _set_cfg(_CFG_GROUP_PREFS, json.dumps(prefs, ensure_ascii=False))


def _resolve_groups() -> list[dict]:
    """全部已抓到的群 + 偏好，按用户自定义顺序返回。

    每项 {chat_id, name, markers:[...], in_summary:bool}。
    """
    prefs = _load_prefs()
    order = prefs.get("order") or []
    markers = prefs.get("markers") or {}
    sel = set(prefs.get("summary") or [])
    idx = {cid: i for i, cid in enumerate(order)}
    chats = db_cache.feishu_list_chats()
    chats.sort(key=lambda c: (idx.get(c.get("chat_id", ""), 10 ** 6), c.get("name", "")))
    out: list[dict] = []
    for c in chats:
        cid = c.get("chat_id", "")
        if not cid:
            continue
        out.append({
            "chat_id": cid,
            "name": c.get("name", "") or cid,
            "markers": [m for m in markers.get(cid, []) if m],
            # 未做任何选择时默认全部计入汇总
            "in_summary": (cid in sel) if sel else True,
        })
    return out


def _markers_for_chat(chat_id: str) -> list[str]:
    """某 chat_id 的正文前缀过滤标记列表（无则空）。"""
    if not chat_id:
        return []
    return [m for m in (_load_prefs().get("markers") or {}).get(chat_id, []) if m]


def _uat_expired() -> bool:
    """user_access_token 是否已过期（保守：提前 5min 认为过期）。"""
    expire_str = _cfg(_CFG_UAT_EXPIRE, "")
    if not expire_str:
        return True
    try:
        return time.time() > float(expire_str) - 300
    except Exception:
        return True


def _save_token(data: dict) -> None:
    """把换/续期结果写入 app_config。"""
    if data.get("access_token"):
        _set_cfg(_CFG_UAT, data["access_token"])
    if data.get("refresh_token"):
        _set_cfg(_CFG_RT, data["refresh_token"])
    expire_in = int(data.get("expire_in", 7200))
    _set_cfg(_CFG_UAT_EXPIRE, str(time.time() + expire_in))
    if data.get("open_id"):
        _set_cfg(_CFG_OPEN_ID, data["open_id"])
    if data.get("name"):
        _set_cfg(_CFG_USER_NAME, data["name"])


# ── token 自动续期 ────────────────────────────────────────────────────────

async def _ensure_token() -> str:
    """返回可用于读群/读消息的 Bearer token。

    - 应用身份模式（默认）：换 tenant_access_token，完全自动、无需用户点确认。
    - 用户授权模式：返回有效的 user_access_token（过期自动续期）。
    """
    if _is_tenant_mode():
        try:
            return await _run(_fs.get_tenant_access_token, _get_app_id(), _get_app_secret())
        except _fs.FeishuError as exc:
            logger.warning(f"feishu: 取 tenant_access_token 失败: {exc}")
            raise HTTPException(status_code=502, detail=f"飞书应用鉴权失败: {exc}")
    return await _ensure_valid_uat()


async def _ensure_valid_uat() -> str:
    """返回有效的 user_access_token；过期则自动用 refresh_token 续期。

    若无 RT 或 RT 也失效，抛 HTTPException 401 提示重新授权。
    """
    uat = _get_uat()
    if not uat:
        raise HTTPException(status_code=401, detail="feishu_not_authed")
    if not _uat_expired():
        return uat
    rt = _get_rt()
    if not rt:
        raise HTTPException(status_code=401, detail="feishu_not_authed")
    try:
        data = await _run(_fs.refresh_user_token, _get_app_id(), _get_app_secret(), rt)
        _save_token(data)
        return data["access_token"]
    except _fs.FeishuAuthError as exc:
        logger.warning(f"feishu: refresh_token 失效，需重新授权: {exc}")
        raise HTTPException(status_code=401, detail="feishu_token_expired")
    except _fs.FeishuError as exc:
        logger.warning(f"feishu: 续期失败: {exc}")
        raise HTTPException(status_code=502, detail=f"飞书续期失败: {exc}")


# ── 抓取逻辑 ──────────────────────────────────────────────────────────────

async def crawl_once(reason: str = "manual") -> dict:
    """增量抓取一轮：更新群列表 → 各群拉新消息 → 入库。"""
    if not _is_enabled():
        return {"ok": False, "error": "已暂停（enabled=0）", "added": 0}

    try:
        uat = await _ensure_token()
    except HTTPException as exc:
        err = f"未授权: {exc.detail}"
        _last_status.update(at=datetime.now().isoformat(), ok=False, added=0, error=err, chats=0)
        return dict(_last_status)

    # 刷新群列表
    try:
        chats = await _run(_fs.list_chats, uat)
        await _run(db_cache.feishu_upsert_chats, chats)
    except _fs.FeishuAuthError as exc:
        err = f"鉴权失败: {exc}"
        _last_status.update(at=datetime.now().isoformat(), ok=False, added=0, error=err, chats=0)
        return dict(_last_status)
    except Exception as exc:
        logger.warning(f"feishu.crawl_once: list_chats 失败: {exc}")
        chats = db_cache.feishu_list_chats()

    total_added = 0
    errors = []

    for chat in chats:
        chat_id = chat.get("chat_id", "")
        chat_name = chat.get("name", "")
        if not chat_id:
            continue

        # 增量：从库里最新一条往后拉；首次则回溯 _LOOKBACK_DAYS 天
        latest = await _run(db_cache.feishu_latest_msg_time, chat_id)
        if latest:
            try:
                start_dt = datetime.fromisoformat(latest)
                start_ts = int(start_dt.timestamp()) + 1
            except Exception:
                start_ts = None
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
            start_ts = int(cutoff.timestamp())

        try:
            msgs = await _run(_fs.fetch_messages, uat, chat_id, start_ts, None, _MSG_PAGE_SIZE)
        except _fs.FeishuAuthError as exc:
            errors.append(f"{chat_name}: 鉴权失败")
            logger.warning(f"feishu.crawl_once: {chat_name} 鉴权失败: {exc}")
            break
        except Exception as exc:
            errors.append(f"{chat_name}: {exc}")
            logger.debug(f"feishu.crawl_once: {chat_name} 拉消息失败: {exc}")
            continue

        if not msgs:
            continue

        # 去重
        all_ids = [m.get("message_id", "") for m in msgs if m.get("message_id")]
        existing = await _run(db_cache.feishu_existing_ids, all_ids)
        new_msgs = [m for m in msgs if m.get("message_id") and m["message_id"] not in existing]

        rows = [_fs.parse_message(m, chat_id=chat_id, chat_name=chat_name) for m in new_msgs]
        if rows:
            added = await _run(db_cache.feishu_upsert_messages, rows)
            total_added += added

    ok = not errors or total_added > 0
    _last_status.update(
        at=datetime.now().isoformat(), ok=ok, added=total_added,
        error="；".join(errors), chats=len(chats),
    )
    logger.info(f"feishu.crawl_once({reason}): chats={len(chats)} new={total_added}")
    return dict(_last_status)


async def crawl_loop() -> None:
    logger.info("feishu.crawl_loop: 启动（每 30 分钟增量抓取）")
    await asyncio.sleep(30)
    while True:
        try:
            if _is_enabled() and _has_auth():
                await crawl_once("scheduled")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"feishu.crawl_loop 出错: {exc}")
        # 每天 16:00 后自动生成当日四群汇总（昨天16:00→今天16:00），缺则补。
        try:
            await _maybe_auto_summary()
        except Exception as exc:
            logger.debug(f"feishu auto-summary skipped: {exc}")
        await asyncio.sleep(_CRAWL_INTERVAL)


# ── 四群每日汇总 ───────────────────────────────────────────────────────────
# 窗口：昨天 16:00 → 今天 16:00（「刷新」时把结束点延到当前时刻）。每天存一份，
# day = 窗口结束日。AI 逐群提炼要点 + 综述。

_CUTOFF_HOUR = 16          # 4 点切日
_MAX_MSGS_PER_GROUP = 400  # 进 prompt 的每群消息上限（防 token 爆）
_MAX_CHARS_PER_GROUP = 8000
_CUSTOM_SUMMARY_TTL = 5 * 86400   # 用户自选群汇总缓存保鲜期（仍可 get_stale 回看历史）


def _parse_groups(groups: Optional[str]) -> Optional[list[str]]:
    """逗号分隔的 chat_id 串 → 列表；空/None → None（=用全局默认汇总范围）。"""
    if groups is None:
        return None
    ids = [g.strip() for g in groups.split(",") if g.strip()]
    return ids or None


def _groups_sig(chat_ids: list[str]) -> str:
    """一组群（与顺序无关）的稳定指纹，用于自选汇总缓存键。"""
    s = ",".join(sorted({c for c in chat_ids if c}))
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:12]


def _custom_summary_key(day: str, chat_ids: list[str]) -> str:
    return f"feishu:summary:{day}:{_groups_sig(chat_ids)}"


def _store_custom_summary(day: str, ws: datetime, we: datetime,
                          summary: str, total: int, chat_ids: list[str]) -> dict:
    """把用户自选群的汇总存进通用缓存（按 day+群指纹），返回记录。"""
    rec = {
        "day": day, "window_start": ws.isoformat(), "window_end": we.isoformat(),
        "summary": summary, "msg_count": int(total),
        "generated_at": datetime.now().isoformat(), "custom": True,
    }
    try:
        db_cache.set(_custom_summary_key(day, chat_ids), rec,
                     _CUSTOM_SUMMARY_TTL, category="feishu_summary")
    except Exception as exc:
        logger.debug(f"feishu: 存自选汇总失败: {exc}")
    return rec


def _get_custom_summary(day: str, chat_ids: list[str]) -> Optional[dict]:
    """取用户自选群的历史汇总（忽略 TTL，便于回看往日）。"""
    return db_cache.get_stale(_custom_summary_key(day, chat_ids))


def _summary_window(now: Optional[datetime] = None) -> tuple[datetime, datetime, str]:
    """返回 (window_start, window_end, day)。

    window_start = 昨天 16:00；window_end = min(今天16:00, now) 取「到现在」(now)；
    day = window_end 所在日。created_at 存的是本地时间，故全用本地 naive datetime。
    """
    now = now or datetime.now()
    today_cut = now.replace(hour=_CUTOFF_HOUR, minute=0, second=0, microsecond=0)
    window_start = today_cut - timedelta(days=1)
    window_end = now            # 刷新即「昨天4点→现在」
    day = window_end.strftime("%Y-%m-%d")
    return window_start, window_end, day


def _collect_window_messages(chat_ids: Optional[list[str]] = None) -> tuple[list[dict], datetime, datetime, str, int]:
    """收集选定群在窗口内的消息（套用每群标记过滤 + 跨群去重）。

    返回 (per_group, ws, we, day, total)；per_group=[{name, messages:[...]}, ...]。
    - chat_ids 显式给出（用户自选）时只汇总这些群；
    - 否则用全局偏好里勾「汇总」的群（未选任何群时默认全部）。
    """
    ws, we, day = _summary_window()
    ws_iso, we_iso = ws.isoformat(), we.isoformat()
    if chat_ids is not None:
        sel = {c for c in chat_ids if c}
        groups = [g for g in _resolve_groups() if g["chat_id"] in sel]
    else:
        groups = [g for g in _resolve_groups() if g["in_summary"]]
    per_group: list[dict] = []
    total = 0
    seen: set[str] = set()   # 跨群去重：同源转发只在第一个群计一次
    for g in groups:
        msgs = db_cache.feishu_window_messages(
            g["chat_id"], ws_iso, we_iso,
            content_prefixes=_markers_to_prefixes(g["markers"]),
        )
        uniq: list[dict] = []
        for m in msgs:
            key = _norm_content(m.get("content_text", ""))
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            uniq.append(m)
        total += len(uniq)
        per_group.append({"name": g["name"], "messages": uniq})
    return per_group, ws, we, day, total


def _build_summary_prompt(per_group: list[dict], ws: datetime, we: datetime) -> tuple[str, str]:
    """构造 (system, user) prompt。user 含各群消息文本（按上限截断）。"""
    system = (
        "你是资深A股投研助理。下面是若干个股票交流群在指定时间窗内的聊天记录"
        "（每条格式为「发言人：内容」）。请为每个群分别提炼当日要点，再给一段总览。\n"
        "要求：\n"
        "1. 按群分小节（## 群名），每节用要点列出：讨论的主要个股/板块、核心观点与逻辑、"
        "明确的操作建议（买/卖/止盈止损/仓位）、整体情绪（看多/看空/分歧）。\n"
        "2. 个股尽量带上代码或便于识别的名称；剔除寒暄、表情、广告、防失联等噪声。\n"
        "3. 若同一观点/标的在多个群重复出现，合并表述、不要重复罗列。\n"
        "4. 最后用「## 综述」给出各群共识、分歧点与值得关注的标的（3-6条）。\n"
        "5. 用简体中文、Markdown 输出，简洁克制，不编造记录里没有的信息。"
    )
    lines = [
        f"时间窗：{ws.strftime('%Y-%m-%d %H:%M')} → {we.strftime('%Y-%m-%d %H:%M')}\n",
    ]
    for grp in per_group:
        lines.append(f"\n===== 群：{grp['name']} =====")
        msgs = grp["messages"]
        if not msgs:
            lines.append("（本时间窗内无消息）")
            continue
        if len(msgs) > _MAX_MSGS_PER_GROUP:
            msgs = msgs[-_MAX_MSGS_PER_GROUP:]
        buf, used = [], 0
        for m in msgs:
            t = (m.get("content_text") or "").strip()
            if not t or m.get("msg_type") == "system":
                continue
            clock = (m.get("created_at") or "")[11:16]
            line = f"[{clock}] {t}"
            if used + len(line) > _MAX_CHARS_PER_GROUP:
                lines.append("……（更多消息略）")
                break
            buf.append(line)
            used += len(line)
        lines.extend(buf if buf else ["（无有效文本消息）"])
    return system, "\n".join(lines)


async def generate_summary(chat_ids: Optional[list[str]] = None) -> dict:
    """生成当日汇总并返回记录。

    - chat_ids 给出（用户自选群）：结果按 day+群指纹存进通用缓存，不动全局当日表。
    - 否则：用全局汇总范围，落库到当日表（供历史列表 / 16:00 自动补）。
    """
    custom = chat_ids is not None
    per_group, ws, we, day, total = _collect_window_messages(chat_ids)
    if total == 0:
        summary = ("## 综述\n\n所选群在该时间窗内暂无可汇总的消息。"
                   "可先点「立即抓取」拉取最新群消息，或调整要汇总的群后再试。")
        if custom:
            return _store_custom_summary(day, ws, we, summary, 0, chat_ids)
        await _run(db_cache.feishu_summary_upsert, day, ws.isoformat(),
                   we.isoformat(), summary, 0)
        return dict(db_cache.feishu_summary_get(day) or {})

    system, user = _build_summary_prompt(per_group, ws, we)
    try:
        summary = await ai_client.chat(
            system=system, user=user, max_tokens=3500,
            caller="feishu_summary", timeout=180,
        )
    except Exception as exc:
        logger.warning(f"feishu.generate_summary: AI 失败: {exc}")
        raise HTTPException(status_code=502, detail=f"汇总生成失败：{exc}")

    logger.info(f"feishu.generate_summary: day={day} groups={len(per_group)} "
                f"msgs={total} custom={custom}")
    if custom:
        return _store_custom_summary(day, ws, we, summary.strip(), total, chat_ids)
    await _run(db_cache.feishu_summary_upsert, day, ws.isoformat(),
               we.isoformat(), summary.strip(), total)
    return dict(db_cache.feishu_summary_get(day) or {})


async def _maybe_auto_summary() -> None:
    """16:00 后若当日汇总缺失则自动补一份（每日存一份）。"""
    now = datetime.now()
    if now.hour < _CUTOFF_HOUR:
        return
    day = now.strftime("%Y-%m-%d")
    if db_cache.feishu_summary_get(day):
        return
    if not _has_auth():
        return
    await generate_summary()


# ── Schemas ───────────────────────────────────────────────────────────────

class FeishuConfig(BaseModel):
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    redirect_uri: Optional[str] = None
    enabled: Optional[bool] = None
    auth_mode: Optional[str] = None   # "tenant"=应用身份自动授权 / "user"=OAuth用户授权


class GroupPrefs(BaseModel):
    order: Optional[list[str]] = None                 # 标签显示顺序（chat_id 列表）
    summary: Optional[list[str]] = None               # 计入每日汇总的群（chat_id 列表）
    markers: Optional[dict[str, list[str]]] = None    # {chat_id: [前缀, ...]}


# ── 端点 ──────────────────────────────────────────────────────────────────

@router.get("/auth-url")
def get_auth_url(_user: dict = Depends(get_current_user)):
    """返回飞书 OAuth 授权链接，前端跳转用。"""
    url = _fs.build_auth_url(_get_app_id(), _get_redirect_uri())
    return {"url": url}


@router.get("/callback", include_in_schema=False)
async def oauth_callback(code: str = Query(...), state: str = Query("")):
    """飞书 OAuth 回调，交换 code → user_access_token，然后跳回首页。"""
    try:
        data = await _run(_fs.exchange_code, _get_app_id(), _get_app_secret(), code)
        _save_token(data)
        logger.info(f"feishu: OAuth 授权成功，用户 {data.get('name')} ({data.get('open_id')})")
    except Exception as exc:
        logger.warning(f"feishu: OAuth 回调失败: {exc}")
        return RedirectResponse(url="/?feishu_auth=error")
    return RedirectResponse(url="/?feishu_auth=ok")


@router.get("/chats")
async def list_chats(_user: dict = Depends(get_current_user)):
    """返回已缓存的群列表（上次抓取时刷新）。"""
    chats = db_cache.feishu_list_chats()
    return {"chats": chats, "total": len(chats)}


@router.get("/groups")
def list_groups(_user: dict = Depends(get_current_user)):
    """全部群标签：按用户自定义顺序返回 {chat_id,name,markers,in_summary}。"""
    return {"groups": _resolve_groups()}


@router.put("/groups/prefs")
def set_group_prefs(p: GroupPrefs, _user: dict = Depends(get_current_user)):
    """保存群标签偏好（顺序 / 汇总选择 / 每群前缀过滤），返回最新群列表。"""
    prefs = _load_prefs()
    if p.order is not None:
        prefs["order"] = [c for c in p.order if c]
    if p.summary is not None:
        prefs["summary"] = [c for c in p.summary if c]
    if p.markers is not None:
        clean: dict[str, list[str]] = {}
        for cid, ms in p.markers.items():
            ms2 = [m.strip() for m in (ms or []) if m and m.strip()]
            if ms2:
                clean[cid] = ms2
        prefs["markers"] = clean
    _save_prefs(prefs)
    return {"groups": _resolve_groups()}


@router.get("/messages")
def list_messages(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    chat_id: Optional[str] = Query(None),
    dedup: bool = Query(False),
    _user: dict = Depends(get_current_user),
):
    # 带标记的群：自动只看「正文以『标记：』开头」的机器人转发（可多标记）。
    prefixes = _markers_to_prefixes(_markers_for_chat(chat_id)) if chat_id else []
    msgs, total = db_cache.feishu_query(
        search=search, chat_id=chat_id, content_prefixes=prefixes,
        page=page, page_size=page_size,
    )
    # 看「全部群」时按需在本页内去重（同源转发只留一条）。
    if dedup and not chat_id:
        msgs = _dedup_messages(msgs)
    return {
        "messages": msgs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/refresh")
async def refresh(_user: dict = Depends(get_current_user)):
    return await crawl_once("manual")


# ── 四群每日汇总端点 ───────────────────────────────────────────────────────

@router.get("/summary")
def get_summary(
    date: Optional[str] = Query(None),
    groups: Optional[str] = Query(None, description="逗号分隔 chat_id，传则取该自选群组合的汇总"),
    _user: dict = Depends(get_current_user),
):
    """返回某日汇总（默认今天）。

    传 groups（用户自选群）时取该组合的自选汇总缓存；否则取全局当日汇总。
    无则返回空 summary。
    """
    day = (date or datetime.now().strftime("%Y-%m-%d")).strip()
    chat_ids = _parse_groups(groups)
    if chat_ids is not None:
        rec = _get_custom_summary(day, chat_ids)
        return rec or {"day": day, "summary": "", "msg_count": 0, "window_start": "",
                       "window_end": "", "generated_at": "", "custom": True}
    rec = db_cache.feishu_summary_get(day)
    return rec or {"day": day, "summary": "", "msg_count": 0,
                   "window_start": "", "window_end": "", "generated_at": ""}


@router.get("/summary/list")
def list_summaries(_user: dict = Depends(get_current_user)):
    """汇总历史日期列表（新到旧）。"""
    return {"items": db_cache.feishu_summary_list()}


@router.post("/summary/refresh")
async def refresh_summary(
    groups: Optional[str] = Query(None, description="逗号分隔 chat_id，传则只汇总这些自选群"),
    _user: dict = Depends(get_current_user),
):
    """先增量抓取，再重新生成当日（昨天16:00→现在）汇总。

    传 groups 时只汇总用户自选的群（结果按群组合单独缓存，不影响全局当日汇总）。
    """
    chat_ids = _parse_groups(groups)
    try:
        await crawl_once("summary")
    except Exception as exc:
        logger.debug(f"feishu.refresh_summary: 抓取忽略: {exc}")
    return await generate_summary(chat_ids)


@router.get("/status")
def status(_user: dict = Depends(get_current_user)):
    return {
        "count": db_cache.feishu_message_count(),
        "last_fetch": db_cache.feishu_latest_fetch(),
        "enabled": _is_enabled(),
        "auth_mode": _auth_mode(),
        # 应用身份模式恒为已授权（无需用户点确认）；用户模式看是否已 OAuth
        "authed": _has_auth(),
        "user_name": _cfg(_CFG_USER_NAME, ""),
        "open_id": _cfg(_CFG_OPEN_ID, ""),
        "uat_expired": False if _is_tenant_mode() else _uat_expired(),
        "last_run": _last_status,
        "interval_seconds": _CRAWL_INTERVAL,
    }


@router.get("/config")
def get_config(_user: dict = Depends(get_current_user)):
    return {
        "app_id": _get_app_id(),
        "app_secret_set": bool(_get_app_secret()),
        "redirect_uri": _get_redirect_uri(),
        "enabled": _is_enabled(),
        "auth_mode": _auth_mode(),
        "authed": _has_auth(),
        "uat_expired": False if _is_tenant_mode() else _uat_expired(),
        "user_name": _cfg(_CFG_USER_NAME, ""),
    }


@router.put("/config")
def set_config(cfg: FeishuConfig, _user: dict = Depends(get_current_user)):
    if cfg.app_id is not None:
        _set_cfg(_CFG_APP_ID, cfg.app_id.strip())
    if cfg.app_secret is not None:
        _set_cfg(_CFG_APP_SECRET, cfg.app_secret.strip())
    if cfg.redirect_uri is not None:
        _set_cfg(_CFG_REDIRECT_URI, cfg.redirect_uri.strip())
    if cfg.enabled is not None:
        _set_cfg(_CFG_ENABLED, "1" if cfg.enabled else "0")
    if cfg.auth_mode is not None:
        mode = cfg.auth_mode.strip().lower()
        _set_cfg(_CFG_AUTH_MODE, "user" if mode == "user" else "tenant")
    return get_config(_user)
