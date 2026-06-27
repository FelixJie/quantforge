"""纷传 (fenchuan8) 圈子博客抓取 API。

把某个纷传圈子（默认 qz_id 105371）的最新帖子抓到内存 + ``app_config`` 缓存，
前端 ``/fenchuan`` 页直接展示。与知识星球博客（:mod:`blog`）同构，但纷传一次接口
即返回完整帖子（正文/配图/互动数/外链），无需二次抓取，故不落 ``blog_posts`` 表，
仅把最近一轮快照存进 ``app_config``（key ``fenchuan:cache``），重启后仍可秒显。

鉴权 token 是浏览器里 pc.fenchuan8.com 的 ``fc-token``，存在 ``app_config``
（key ``fenchuan:token``）；未配置时回退读取 ``fenchuan_blog/token.txt``（既有扫码
登录脚本写入处），可通过 ``PUT /api/fenchuan/config`` 更新。

抓取改为**按需**：打开页面或点「立即刷新」时，若缓存过期（超过 INTERVAL）则后台抓
一轮（不阻塞当前请求，与 blog 一致，不在 startup 常驻定时循环）。

端点::

    GET  /api/fenchuan/posts     最新帖子列表（含正文，附带状态）
    POST /api/fenchuan/refresh   立即抓取一轮（阻塞至完成）
    GET  /api/fenchuan/status    抓取状态（数量/上次时间/上次错误/登录态）
    GET  /api/fenchuan/config    当前配置（token 仅返回是否已设）
    PUT  /api/fenchuan/config    更新 token / qz_id / 开关
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel

from quantforge.api.routes.auth import get_admin_user, get_current_user
from quantforge.data.storage import db_cache

router = APIRouter(prefix="/fenchuan", tags=["fenchuan"])

# ── 抓取常量（与 fenchuan_blog/server.py 保持一致）─────────────────────────────
_API_BASE = "https://api.leadshiptech.com/"
_SIGN_SECRET = "AS28@~#*shFG486shfksdfSDF@#%dsdf"  # 来自前端 app.js 的签名盐
_INTERVAL = 3600                                   # 缓存有效期，秒（与机构荐股一致：整点每小时）
_DEFAULT_QZ = "105371"
_COMMENT_PER_PAGE = 10        # sx/index/comment 每页固定 10 条
_COMMENT_MAX_PAGES = 60       # 单帖最多翻多少页评论（防止异常帖子无限翻）

# ── 配置键 ────────────────────────────────────────────────────────────────
_CFG_TOKEN = "fenchuan:token"
_CFG_QZ = "fenchuan:qz_id"
_CFG_ENABLED = "fenchuan:enabled"
_CFG_CACHE = "fenchuan:cache"

# token.txt 回退路径：<project_root>/fenchuan_blog/token.txt
_TOKEN_FILE = Path(__file__).parent.parent.parent.parent.parent / "fenchuan_blog" / "token.txt"

# 专属线程池：把阻塞的 urllib 调用挡在 uvicorn 事件循环之外。
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fenchuan")
_refresh_lock = asyncio.Lock()

# 扫码登录（Playwright）状态：在后台线程里弹浏览器扫码，前端轮询 /login/status。
_LOGIN_WAIT = 240   # 等待扫码秒数
_login_state = {"running": False, "ok": False, "error": "", "started_at": 0}
_login_lock = threading.Lock()


async def _run(fn, *args):
    return await asyncio.get_event_loop().run_in_executor(_EXECUTOR, fn, *args)


# ── 配置读写 ──────────────────────────────────────────────────────────────

def _read_token_file() -> str:
    """读取 fenchuan_blog/token.txt；兼容 JSON 串 {"token":"..."} 或裸 token。"""
    try:
        raw = _TOKEN_FILE.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return ""
    if not raw:
        return ""
    txt = raw
    try:
        txt = urllib.parse.unquote(raw)
    except Exception:
        pass
    for candidate in (txt, raw):
        s = candidate.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and obj.get("token"):
                    return str(obj["token"])
            except Exception:
                pass
    return raw


def _get_token() -> str:
    return db_cache.app_config_get(_CFG_TOKEN, "") or _read_token_file()


def _get_qz() -> str:
    return db_cache.app_config_get(_CFG_QZ, _DEFAULT_QZ) or _DEFAULT_QZ


def _is_enabled() -> bool:
    return (db_cache.app_config_get(_CFG_ENABLED, "1") or "1") == "1"


def _load_cache() -> dict:
    raw = db_cache.app_config_get(_CFG_CACHE, "") or ""
    if not raw:
        return {"posts": [], "updated_at": 0, "max_id": 0, "status": "init", "error": ""}
    try:
        return json.loads(raw)
    except Exception:
        return {"posts": [], "updated_at": 0, "max_id": 0, "status": "init", "error": ""}


def _save_cache(snap: dict) -> None:
    try:
        db_cache.app_config_set(_CFG_CACHE, json.dumps(snap, ensure_ascii=False))
    except Exception as exc:
        logger.warning(f"fenchuan: 缓存写入失败: {exc}")


def _set_token(raw_cookie: str) -> None:
    """保存扫到的 fc-token：写进 app_config（主源），并尽量同步回 token.txt（独立版/login.py 兼容）。"""
    db_cache.app_config_set(_CFG_TOKEN, raw_cookie.strip())
    try:
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(raw_cookie.strip(), encoding="utf-8")
    except OSError as exc:
        logger.debug(f"fenchuan: token.txt 回写失败（不影响主流程）: {exc}")


# ── 扫码登录（Playwright 弹微信扫码，自动捕获 fc-token）─────────────────────────

def _extract_token(cookie_value: str) -> str:
    """从 fc-token cookie 值里解析出 JWT；解析不出返回空串。"""
    if not cookie_value:
        return ""
    for s in (urllib.parse.unquote(cookie_value), cookie_value):
        s = s.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and obj.get("token"):
                    return str(obj["token"])
            except Exception:
                pass
    return ""


def _login_worker() -> None:
    """后台线程：弹浏览器扫码登录，成功后把 fc-token 写入配置并刷新一轮。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        with _login_lock:
            _login_state.update(running=False, ok=False,
                                error="缺少 playwright，请在主站环境运行 "
                                      "python -m pip install playwright && python -m playwright install chromium")
        return

    login_url = f"https://pc.fenchuan8.com/#/index?forum={_get_qz()}"
    captured = ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            ctx = browser.new_context(no_viewport=True)
            page = ctx.new_page()
            page.goto(login_url, wait_until="domcontentloaded")
            deadline = time.time() + _LOGIN_WAIT
            while time.time() < deadline:
                with _login_lock:
                    if not _login_state.get("running"):  # 被取消
                        break
                try:
                    cookies = ctx.cookies()
                except Exception:
                    cookies = []
                for c in cookies:
                    if c.get("name") == "fc-token":
                        val = c.get("value") or ""
                        if _extract_token(val):
                            # 用刚拿到的 token 验证一次登录态
                            resp = _api_post("sx/newindex/cinfo",
                                             {"qz_id": _get_qz(), "p": 1},
                                             _extract_token(val))
                            if not _is_login_error(resp):
                                captured = val
                                break
                if captured:
                    break
                time.sleep(1.5)
            browser.close()
    except Exception as exc:
        with _login_lock:
            _login_state.update(running=False, ok=False, error=f"扫码登录出错: {exc}")
        return

    if not captured:
        with _login_lock:
            _login_state.update(running=False, ok=False, error="超时未检测到有效登录，请重试")
        return

    _set_token(captured)
    with _login_lock:
        _login_state.update(running=False, ok=True, error="")
    logger.info("fenchuan: 扫码登录成功，token 已保存")


# ── 签名请求 ──────────────────────────────────────────────────────────────

def _api_post(path: str, params: dict, token: str) -> dict:
    ts = int(time.time())
    data = dict(params)
    data["_"] = ts
    data["app_name"] = "sx"
    data["task_token"] = token or "empty1"
    # 与前端一致: sign = md5(secret + 未编码的 querystring)
    qs = "&".join(f"{k}={v}" for k, v in data.items())
    data["sign"] = hashlib.md5((_SIGN_SECRET + qs).encode("utf-8")).hexdigest()
    data["apiversion"] = "2.3"
    data["clientfrom"] = "pc"
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        _API_BASE + path.lstrip("/"),
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://pc.fenchuan8.com",
            "Referer": "https://pc.fenchuan8.com/",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# 登录态失效判定：纷传用不同的码表达「token 失效/被踢」，需统一识别为需重新扫码。
#   900/401      → 通用未授权
#   inner 22222  → data.code 里的未登录
#   -102         → 账号在其他设备登录被强制下线（最常见，旧代码漏判）
# 兜底：任何非成功码（code 不为 1/None）且 msg 含登录类关键词，也按失效处理。
_LOGIN_ERR_CODES = {900, 401, -102, -101, -100}
_LOGIN_ERR_KW = ("登录", "登陆", "下线", "未登陆", "重新登")


def _is_login_error(resp: dict) -> bool:
    code = resp.get("code")
    data = resp.get("data")
    inner = data.get("code") if isinstance(data, dict) else None
    if code in _LOGIN_ERR_CODES or inner == 22222:
        return True
    if code not in (1, None):
        msg = resp.get("msg")
        if isinstance(msg, str) and any(k in msg for k in _LOGIN_ERR_KW):
            return True
    return False


# ── 网页内扫码（纯 HTTP，无需 Playwright/浏览器）─────────────────────────────
#
# 复刻 pc.fenchuan8.com 登录页的三步：
#   1) POST sx/loginh5/scanurl  (multipart scene=null&yqm=) → {scene, url(二维码图)}
#   2) GET  {url}                                          → 二维码 PNG（前端展示）
#   3) POST sx/loginh5/scanstat (scene=..&is_check=1)      → stat==1 时 data.token 即登录态
# 这样任何管理员在自己的浏览器里用微信扫码即可授权，不依赖后端宿主机弹窗。

def _scanurl() -> dict:
    """取一对新的 scene + 二维码图片地址。multipart 表单，字段同前端。"""
    boundary = "----qf" + uuid.uuid4().hex
    parts = []
    for k, v in (("scene", "null"), ("yqm", "")):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        )
    body = ("".join(parts) + f"--{boundary}--\r\n").encode("utf-8")
    req = urllib.request.Request(
        _API_BASE + "sx/loginh5/scanurl",
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://pc.fenchuan8.com",
            "Referer": "https://pc.fenchuan8.com/",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        resp = json.loads(r.read().decode("utf-8", "replace"))
    data = resp.get("data") or {}
    return {"scene": data.get("scene", ""), "url": data.get("url", "")}


def _qr_data_url(img_url: str) -> str:
    """把二维码图片拉成 data URL，前端可直接 <img :src> 展示（免跨域/混合内容）。"""
    if not img_url:
        return ""
    req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "image/png")
    return f"data:{ctype};base64," + base64.b64encode(raw).decode("ascii")


def _scanstat(scene: str) -> dict:
    """轮询扫码状态。stat: 10=待扫/未确认, 1=已确认(data.token 为登录态), 20=需注册。"""
    data = {
        "scene": scene,
        "is_check": 1,
        "_": int(time.time()),
        "app_name": "sx",
        "apiversion": "2.3",
        "clientfrom": "pc",
    }
    req = urllib.request.Request(
        _API_BASE + "sx/loginh5/scanstat",
        data=urllib.parse.urlencode(data).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://pc.fenchuan8.com",
            "Referer": "https://pc.fenchuan8.com/",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ── 解析 ──────────────────────────────────────────────────────────────────

_NAV_RE = re.compile(r'<navigator\b[^>]*?\bhref="([^"]*)"[^>]*>(.*?)</navigator>', re.I | re.S)
_NAV_NOHREF_RE = re.compile(r'<navigator\b[^>]*>(.*?)</navigator>', re.I | re.S)
_TAG_RE = re.compile(r'<[^>]+>')


def _clean_content(raw: str):
    """把帖子正文里的小程序 <navigator> 标签转成纯文本, 并抽出其中的外链。"""
    if not raw:
        return "", []
    links = []

    def _nav(m):
        href = html.unescape(m.group(1) or "").strip()
        text = _TAG_RE.sub("", m.group(2) or "").strip()
        if href:
            links.append({"text": text or href, "url": href})
        return text

    s = _NAV_RE.sub(_nav, raw)
    s = _NAV_NOHREF_RE.sub(lambda m: _TAG_RE.sub("", m.group(1) or ""), s)
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    return s.strip(), links


def _normalize_one(it: dict) -> Optional[dict]:
    if not isinstance(it, dict):
        return None
    images = []
    for m in (it.get("media_list") or []):
        if isinstance(m, dict):
            thumb = m.get("min_img") or m.get("url")
            full = m.get("url") or m.get("min_img")
            if thumb:
                images.append({"thumb": thumb, "full": full})
    text, links = _clean_content(it.get("content") or "")
    if not text:
        text = (it.get("summary") or "").strip()
    return {
        "id": str(it.get("id", "")),
        "title": str(it.get("title") or "").strip(),
        "text": text,
        "links": links,
        "author": str(it.get("username") or "").strip(),
        "avatar": str(it.get("avatar") or "").strip(),
        "time": str(it.get("fbtime") or it.get("create_time") or "").strip(),
        "images": images,
        "url": str(it.get("h5_url") or "").strip(),
        "is_top": bool(it.get("show_top") or it.get("is_top")),
        "stats": {
            "zan": it.get("zan_num", 0),
            "comment": it.get("comment_num", 0),
            "view": it.get("view_num", 0),
        },
    }


def _normalize(api_data) -> list[dict]:
    rows = []
    if isinstance(api_data, dict):
        lst = api_data.get("list")
        if isinstance(lst, dict):
            rows = lst.get("data") or []
        elif isinstance(lst, list):
            rows = lst
    out = [n for it in rows if (n := _normalize_one(it))]
    # 置顶优先（接口本身已大致按时间倒序）
    out.sort(key=lambda p: (not p["is_top"],))
    return out


def _first_str(v) -> str:
    """avatar 等字段有时是 list（取首个），有时是 str。"""
    if isinstance(v, list):
        return str(v[0]).strip() if v else ""
    return str(v or "").strip()


def _normalize_comment(c: dict) -> Optional[dict]:
    if not isinstance(c, dict):
        return None
    text, _ = _clean_content(c.get("content") or "")
    replies = []
    for r in (c.get("ej_pinglun_list") or []):
        if not isinstance(r, dict):
            continue
        rt, _ = _clean_content(r.get("content") or "")
        replies.append({
            "id": str(r.get("id", "")),
            "user": _first_str(r.get("username")),
            "avatar": _first_str(r.get("avatar")),
            "text": rt,
            "time": str(r.get("add_time") or r.get("pinglun_time") or "").strip(),
            "is_master": bool(r.get("is_master")),
        })
    return {
        "id": str(c.get("id", "")),
        "user": _first_str(c.get("username")),
        "avatar": _first_str(c.get("avatar")),
        "text": text,
        "img": _first_str(c.get("img")),
        "time": str(c.get("add_time") or c.get("pinglun_time") or "").strip(),
        "zan": c.get("zan_num", 0) or 0,
        "is_top": bool(c.get("is_top") or c.get("top")),
        "is_master": bool(c.get("is_master")),
        "reply_num": c.get("ej_pinglun_num", 0) or 0,
        "replies": replies,
    }


def _fetch_all_comments(qz_id: str, tz_id: str, token: str) -> list[dict]:
    """翻页拉取某帖的全部评论（含二级回复 ``ej_pinglun_list``）。

    接口 ``sx/index/comment`` + ``dopost=new_list`` + ``p``，``data.list`` 每页 10 条，
    空页即终止；``data.pinglun_num`` 为总评论数（含回复）。
    """
    out: list[dict] = []
    for page in range(1, _COMMENT_MAX_PAGES + 1):
        try:
            resp = _api_post("sx/index/comment",
                             {"qz_id": qz_id, "tz_id": tz_id, "dopost": "new_list", "p": page},
                             token)
        except Exception as exc:
            logger.debug(f"fenchuan: 评论抓取失败 tz={tz_id} p={page}: {exc}")
            break
        if resp.get("code") != 1:
            break
        data = resp.get("data") or {}
        lst = data.get("list") if isinstance(data, dict) else None
        # ``list`` 可能是分页对象 {total,current_page,last_page,data:[...]}，也可能直接是数组
        last_page = None
        if isinstance(lst, dict):
            last_page = lst.get("last_page")
            lst = lst.get("data")
        if not isinstance(lst, list) or not lst:
            break
        out.extend(n for c in lst if (n := _normalize_comment(c)))
        if last_page is not None:
            if page >= int(last_page or 0):
                break
        elif len(lst) < _COMMENT_PER_PAGE:
            break
    return out


# ── 抓取核心 ──────────────────────────────────────────────────────────────
#
# cinfo 的翻页参数是 ``p``（``page`` 形同虚设，永远返回第 1 页），每页 10 条，
# ``data.list`` 形如 {total, current_page, last_page, per_page, data:[...]}。
# 默认抓到约半年前为止（QF_FENCHUAN_DAYS 可调），并以 last_page / 翻页上限兜底。

_HISTORY_DAYS = int(os.environ.get("QF_FENCHUAN_DAYS", "190"))  # 默认回溯约半年
_MAX_PAGES = int(os.environ.get("QF_FENCHUAN_MAX_PAGES", "40"))  # 翻页硬上限（防异常无限翻）


def _parse_post_time(s: str) -> Optional[float]:
    """把 '2026-06-12 17:47' / '2026-06-12 17:47:30' 解析成 epoch 秒；失败返回 None。"""
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    return None


def _cinfo_page(qz: str, page: int, token: str) -> tuple[list[dict], Optional[int]]:
    """抓 cinfo 第 ``page`` 页，返回 (本页归一化帖子, last_page)。

    抛出异常交由上层捕获；登录失效用哨兵 ``RuntimeError('login_required:...')`` 上抛。
    """
    resp = _api_post("sx/newindex/cinfo", {"qz_id": qz, "p": page}, token)
    code = resp.get("code")
    data = resp.get("data")
    inner_code = data.get("code") if isinstance(data, dict) else None
    if _is_login_error(resp):
        msg = (resp.get("msg") or "").strip() or "登录态失效"
        raise RuntimeError(
            f"login_required:{msg}（code={code}），请重新扫码授权")
    last_page = None
    if isinstance(data, dict) and isinstance(data.get("list"), dict):
        try:
            last_page = int(data["list"].get("last_page") or 0) or None
        except (TypeError, ValueError):
            last_page = None
    return _normalize(data), last_page


def _fetch_once_blocking() -> dict:
    """阻塞抓一轮，返回新的快照 dict（不写库，由调用方决定）。"""
    snap = _load_cache()
    token = _get_token()
    if not _is_enabled():
        snap.update(status="disabled", error="已暂停（enabled=0）")
        return snap
    if not token:
        snap.update(status="login_required",
                    error="未配置 fc-token，请在设置里粘贴，或运行 fenchuan_blog/login.py 扫码登录")
        return snap

    qz = _get_qz()
    cutoff = time.time() - _HISTORY_DAYS * 86400
    seen: dict[str, dict] = {}
    page = 1
    last_page = None
    try:
        while page <= _MAX_PAGES:
            posts, lp = _cinfo_page(qz, page, token)
            if lp:
                last_page = lp
            if not posts:
                break
            for p in posts:
                seen.setdefault(p["id"], p)  # 去重：置顶帖会在第 1 页重复出现
            # 截断判定基于「非置顶」帖的最早时间（置顶老帖会扰乱时间序）
            page_ts = [ts for p in posts if not p.get("is_top")
                       and (ts := _parse_post_time(p.get("time", ""))) is not None]
            if page_ts and min(page_ts) < cutoff:
                break
            if last_page and page >= last_page:
                break
            page += 1
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("login_required:"):
            snap.update(status="login_required", error=msg.split(":", 1)[1])
            return snap
        snap.update(status="error", error=f"请求失败: {exc}")
        return snap
    except Exception as exc:
        # 已抓到一些就保留这部分，否则报错
        if not seen:
            snap.update(status="error", error=f"请求失败: {exc}")
            return snap
        logger.warning(f"fenchuan: 翻页中断（已得 {len(seen)} 帖）: {exc}")

    # 抓到 0 帖（多为 token 半失效/接口异常返回空列表，而非硬错误码）——绝不用空结果
    # 覆盖已有缓存，否则旧帖会整页消失。保留上一轮帖子，仅标记状态提示重新授权。
    if not seen and snap.get("posts"):
        snap.update(status="stale",
                    error="本轮抓取为空，已沿用上次缓存（多为 fc-token 失效，建议重新扫码授权）")
        return snap

    posts = sorted(seen.values(), key=lambda p: (not p["is_top"], -(_idnum(p))))

    # 评论：复用上一轮已缓存的评论，仅为「新帖」抓评论，避免每 10 分钟把上百帖评论全量重抓。
    prev_comments = {p.get("id"): p.get("comments")
                     for p in snap.get("posts", []) if isinstance(p, dict)}
    for p in posts:
        cached = prev_comments.get(p["id"])
        if cached is not None:
            p["comments"] = cached
            continue
        try:
            p["comments"] = _fetch_all_comments(qz, p["id"], token)
        except Exception as exc:
            logger.debug(f"fenchuan: 评论汇总失败 tz={p.get('id')}: {exc}")
            p["comments"] = []

    cur_max = max((_idnum(p) for p in posts), default=0)
    prev_max = snap.get("max_id", 0)
    return {
        "posts": posts,
        "updated_at": int(time.time()),
        "max_id": max(prev_max, cur_max),
        "status": "ok",
        "error": "",
        "qz_id": qz,
    }


def _idnum(p: dict) -> int:
    try:
        return int(p.get("id") or 0)
    except (TypeError, ValueError):
        return 0


async def crawl_once(reason: str = "manual") -> dict:
    """抓一轮（线程池里执行阻塞 IO），写入缓存，返回状态摘要。"""
    async with _refresh_lock:
        snap = await _run(_fetch_once_blocking)
        _save_cache(snap)
        if snap.get("status") == "ok":
            logger.info(f"fenchuan.crawl_once({reason}): posts={len(snap.get('posts', []))} "
                        f"qz={_get_qz()}")
        else:
            logger.warning(f"fenchuan.crawl_once({reason}) 失败: {snap.get('error')}")
        return _status_of(snap)


def _status_of(snap: dict) -> dict:
    return {
        "status": snap.get("status", "init"),
        "error": snap.get("error", ""),
        "count": len(snap.get("posts", [])),
        "updated_at": snap.get("updated_at", 0),
        "qz_id": _get_qz(),
        "enabled": _is_enabled(),
        "token_set": bool(_get_token()),
        "forum_url": f"https://pc.fenchuan8.com/#/index?forum={_get_qz()}",
        "interval_seconds": _INTERVAL,
    }


async def _maybe_refresh() -> None:
    """缓存过期且已配置则后台抓一轮（不阻塞当前请求）。"""
    if not (_is_enabled() and _get_token()):
        return
    snap = _load_cache()
    if int(time.time()) - int(snap.get("updated_at") or 0) < _INTERVAL:
        return
    if _refresh_lock.locked():
        return
    asyncio.create_task(crawl_once("auto"))


def _seconds_until_next_hour() -> float:
    """距下一个整点（hh:00:00）的秒数。"""
    now = datetime.now()
    nxt = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return max((nxt - now).total_seconds(), 1.0)


async def crawl_loop() -> None:
    """后台循环：整点每小时抓一轮增量（与机构荐股 blog.crawl_loop 同节奏）。

    app 生命周期里启动。手动触发仍可用 ``POST /api/fenchuan/refresh``。
    """
    logger.info("fenchuan.crawl_loop: 启动公众号(纷传)抓取（整点每小时）")
    # 启动后稍等片刻再首抓，避免和其他 warmer 抢冷启动资源。
    await asyncio.sleep(20)
    while True:
        try:
            if _is_enabled() and _get_token():
                await crawl_once("scheduled")
        except asyncio.CancelledError:
            logger.info("fenchuan.crawl_loop: cancelled")
            raise
        except Exception as exc:
            logger.warning(f"fenchuan.crawl_loop 轮次出错: {exc}")
        await asyncio.sleep(_seconds_until_next_hour())


# ── Schemas ───────────────────────────────────────────────────────────────

class FenchuanConfig(BaseModel):
    token: Optional[str] = None       # None=不改；""=清空
    qz_id: Optional[str] = None
    enabled: Optional[bool] = None


# ── 端点 ──────────────────────────────────────────────────────────────────

def _category_of(p: dict) -> str:
    """帖子的分类名：纷传一个圈子对应一个发帖人，作者名即分类（如 Henry）。"""
    return (p.get("author") or "").strip() or "未分类"


def _categories_of(posts: list) -> list[dict]:
    """聚合分类（按作者）：返回 [{name, count}]，按数量降序。"""
    counts: dict[str, int] = {}
    for p in posts:
        c = _category_of(p)
        counts[c] = counts.get(c, 0) + 1
    return [{"name": n, "count": c}
            for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


@router.get("/posts")
async def list_posts(search: Optional[str] = None,
                     category: Optional[str] = None,
                     _user: dict = Depends(get_current_user)):
    await _maybe_refresh()
    snap = _load_cache()
    posts = snap.get("posts", [])
    # 分类（作者）聚合基于全量帖子，不受搜索/筛选影响，方便前端展示标签计数。
    categories = _categories_of(posts)
    if category and category.strip():
        cat = category.strip()
        posts = [p for p in posts if _category_of(p) == cat]
    if search:
        kw = search.strip().lower()
        posts = [p for p in posts
                 if kw in (p.get("title", "") + p.get("text", "")
                           + p.get("author", "")).lower()]
    return {"posts": posts, "categories": categories, "status": _status_of(snap)}


@router.post("/refresh")
async def refresh(_user: dict = Depends(get_current_user)):
    return await crawl_once("manual")


@router.get("/status")
async def status(_user: dict = Depends(get_current_user)):
    await _maybe_refresh()
    return _status_of(_load_cache())


@router.get("/config")
def get_config(_user: dict = Depends(get_current_user)):
    return {
        "token_set": bool(_get_token()),
        "qz_id": _get_qz(),
        "enabled": _is_enabled(),
        "forum_url": f"https://pc.fenchuan8.com/#/index?forum={_get_qz()}",
    }


@router.post("/login")
async def qr_login(_user: dict = Depends(get_current_user)):
    """弹出浏览器用微信扫码登录纷传，自动捕获 fc-token。前端轮询 ``/login/status``。

    注意：浏览器会在**运行主站后端的那台机器**上弹出，需在本机操作。
    """
    with _login_lock:
        if _login_state.get("running"):
            return {"started": False, **_login_state}
        _login_state.update(running=True, ok=False, error="", started_at=int(time.time()))
    threading.Thread(target=_login_worker, name="fenchuan-login", daemon=True).start()
    with _login_lock:
        return {"started": True, **_login_state}


@router.get("/login/status")
def login_status(_user: dict = Depends(get_current_user)):
    with _login_lock:
        st = dict(_login_state)
    st["token_set"] = bool(_get_token())
    return st


# ── 网页内扫码授权（管理后台用，任一管理员均可）─────────────────────────────

@router.post("/qr/start")
async def qr_start(_admin: dict = Depends(get_admin_user)):
    """取一张新的微信扫码二维码（base64 内联）+ scene，前端展示后轮询 ``/qr/poll``。

    与「在后端宿主机弹 Playwright 浏览器」的 ``/login`` 不同，这里是纯 HTTP：
    任何管理员在自己浏览器里用微信扫码即可授权，不依赖后端那台机器。
    """
    try:
        pair = await _run(_scanurl)
    except Exception as exc:
        return {"ok": False, "error": f"获取二维码失败: {exc}"}
    scene = pair.get("scene") or ""
    if not scene:
        return {"ok": False, "error": "纷传未返回 scene，请重试"}
    try:
        qr = await _run(_qr_data_url, pair.get("url") or "")
    except Exception as exc:
        return {"ok": False, "error": f"二维码图片加载失败: {exc}"}
    return {"ok": True, "scene": scene, "qr": qr}


@router.get("/qr/poll")
async def qr_poll(scene: str, _admin: dict = Depends(get_admin_user)):
    """轮询某 scene 的扫码状态。

    返回 ``state``：``pending`` 待扫/未确认；``done`` 已授权(token 已保存)；
    ``register`` 该微信未注册纷传；``expired`` 二维码失效需重取。
    """
    if not scene:
        return {"state": "expired", "error": "缺少 scene"}
    try:
        resp = await _run(_scanstat, scene)
    except Exception as exc:
        return {"state": "pending", "error": f"查询失败: {exc}"}
    stat = resp.get("stat")
    if stat == 1:
        token = ((resp.get("data") or {}).get("token") or "").strip()
        if not token:
            return {"state": "pending", "error": "已扫码但未拿到 token，请重试"}
        _set_token(token)
        logger.info("fenchuan: 网页内扫码授权成功，token 已保存")
        # 立即抓一轮，让公众号页面马上有内容
        if _is_enabled():
            asyncio.create_task(crawl_once("qr-login"))
        return {"state": "done", "token_set": True}
    if stat == 20:
        return {"state": "register", "error": "该微信尚未注册纷传，无法授权"}
    if resp.get("code") not in (1, None):
        return {"state": "expired", "error": resp.get("msg") or "二维码已失效"}
    return {"state": "pending"}


@router.put("/config")
async def set_config(cfg: FenchuanConfig, _user: dict = Depends(get_current_user)):
    if cfg.token is not None:
        db_cache.app_config_set(_CFG_TOKEN, cfg.token.strip())
    if cfg.qz_id is not None and cfg.qz_id.strip():
        db_cache.app_config_set(_CFG_QZ, cfg.qz_id.strip())
    if cfg.enabled is not None:
        db_cache.app_config_set(_CFG_ENABLED, "1" if cfg.enabled else "0")
    # 配置变更后立即抓一轮，让前端马上看到效果
    st = await crawl_once("config-change") if (_is_enabled() and _get_token()) else _status_of(_load_cache())
    return st
