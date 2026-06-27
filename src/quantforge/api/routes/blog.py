"""知识星球博客抓取 API。

把某个知识星球（默认 group 28855458518111）的最新主题抓到本地 ``blog_posts``
表，并把帖子里内嵌的有道笔记链接抓取正文后内联保存，前端 ``/blog`` 页直接展示（接口前缀 ``/api/xingqiu``）。

后台每 10 分钟自动抓一轮（:func:`crawl_loop`，在 app 生命周期里启动）；也可在页
面点「立即刷新」触发 :func:`crawl_once`。

鉴权所需的 ``zsxq_access_token`` cookie 存在 ``app_config``（不随缓存清理被清），
可通过 ``PUT /api/xingqiu/config`` 更新。

端点::

    GET  /api/xingqiu/posts?page&page_size&search   列表（仅预览，不含正文）
    GET  /api/xingqiu/posts/{post_id}               单篇正文 + 内联有道笔记
    POST /api/xingqiu/refresh                        立即抓取一轮
    GET  /api/xingqiu/config                         当前配置（cookie 仅返回是否已设）
    PUT  /api/xingqiu/config                         更新 cookie / group_id / 开关
    GET  /api/xingqiu/status                         抓取状态（数量/上次时间/上次错误）
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from loguru import logger
from pydantic import BaseModel

from quantforge.api.routes.auth import get_current_user
from quantforge.data.storage import db_cache
from quantforge.data.feed import zsxq, youdao

router = APIRouter(prefix="/xingqiu", tags=["blog"])

# ── 配置键 & 默认值 ────────────────────────────────────────────────────────
_CFG_COOKIE = "blog:zsxq_cookie"
_CFG_GROUP = "blog:group_id"          # 旧单星球键（向后兼容/迁移用）
_CFG_GROUP_NAME = "blog:group_name"   # 旧单星球名（向后兼容）
_CFG_GROUPS = "blog:groups"           # 多星球：JSON [{id, name}]
_CFG_ENABLED = "blog:enabled"
_DEFAULT_GROUP = "28855458518111"
# 默认抓取的星球（机构荐股按星球分类：调研纪要 / 180K）。
_DEFAULT_GROUPS = [
    {"id": "28855458518111", "name": "调研纪要"},
    {"id": "28888222154481", "name": "180K"},
]
# 默认 zsxq cookie：未在配置里设置时直接使用，无需前端再输入。
_DEFAULT_COOKIE = ("zsxq_access_token=9A57848F-1B12-450D-B7CA-97D253CE3DCA_EC1B83038A4878DC; "
                   "abtest_env=product")
_CRAWL_INTERVAL = 600        # 10 分钟
_FETCH_COUNT = 20            # 每轮拉取最近 N 条主题
_MAX_YOUDAO_PER_CYCLE = 30   # 每轮最多抓取的有道笔记数（防止单轮过久；超额由懒加载兜底）

# 回填历史窗口：近半年（与研报口径一致）。
_BACKFILL_DAYS = 183
_BACKFILL_TARGET = 500       # 回填目标条数：翻够约 500 条即停（取 天数/条数 先到者）
# 每小时后台自动续传回填的单轮条数：密集圈（如调研纪要 ~60条/天）单次必撞 1059，
# 靠每小时挖一段、从库里已有最早一条继续往更早翻，逐步把窗口推进到 _BACKFILL_DAYS 前。
_AUTO_BACKFILL_TARGET = 300
# AI 标题生成并发上限（避免一次性打爆 LLM 限额/线程池）。
_AI_TITLE_CONCURRENCY = 4
# 大批量回填时的限流加固：超过该条数视为「批量回填」，自动降并发 + 每次生成后
# 节流间隔，避免一次性几百条把 MiniMax 瞬时速率打爆（429 Token Plan）。小批量
# （每轮增量 ≤20 条）不受影响、保持并发快速。
_AI_TITLE_BULK_THRESHOLD = 40    # 超过此条数启用限流模式
_AI_TITLE_BULK_CONCURRENCY = 2   # 批量模式并发
_AI_TITLE_BULK_INTERVAL = 1.5    # 批量模式每次生成后的节流间隔（秒）

# 专属线程池：把阻塞的 requests 调用挡在 uvicorn 事件循环之外。
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="blog")

# 最近一次抓取状态（供 status 端点 & 前端展示）。
_last_status: dict = {"at": None, "ok": None, "added": 0, "error": "", "youdao": 0}

# 懒加载锁：同一篇被多个账号同时打开时，只让一个请求去抓有道正文，其余等结果。
_post_locks: dict[str, asyncio.Lock] = {}


def _post_lock(post_id: str) -> asyncio.Lock:
    lock = _post_locks.get(post_id)
    if lock is None:
        lock = asyncio.Lock()
        _post_locks[post_id] = lock
    return lock


async def _run(fn, *args):
    return await asyncio.get_event_loop().run_in_executor(_EXECUTOR, fn, *args)


# ── 配置读写 ──────────────────────────────────────────────────────────────

def _get_cookie() -> str:
    return db_cache.app_config_get(_CFG_COOKIE, "") or _DEFAULT_COOKIE


def _get_group() -> str:
    """主星球 id（向后兼容：取多星球列表第一个）。"""
    groups = _get_groups()
    return groups[0]["id"] if groups else _DEFAULT_GROUP


def _get_groups() -> list[dict]:
    """抓取的星球列表 [{id, name}]。

    优先读多星球键 ``blog:groups``；缺失时从旧单星球键迁移（含其 group_name），
    再回退到内置默认（调研纪要 + 180K）。"""
    raw = db_cache.app_config_get(_CFG_GROUPS, "")
    if raw:
        try:
            groups = json.loads(raw)
            if isinstance(groups, list) and groups:
                return [{"id": str(g.get("id") or g.get("group_id")),
                         "name": str(g.get("name") or "")}
                        for g in groups if (g.get("id") or g.get("group_id"))]
        except Exception:
            pass
    # 迁移旧单星球配置
    old_id = db_cache.app_config_get(_CFG_GROUP, "")
    if old_id:
        old_name = db_cache.app_config_get(_CFG_GROUP_NAME, "") or ""
        merged = [{"id": old_id, "name": old_name}]
        # 补上默认里旧配置没有的星球（如旧库只有调研纪要，自动加上 180K）
        for g in _DEFAULT_GROUPS:
            if g["id"] != old_id:
                merged.append(dict(g))
        return merged
    return [dict(g) for g in _DEFAULT_GROUPS]


def _group_name_map() -> dict[str, str]:
    """group_id → 星球显示名。"""
    return {g["id"]: (g.get("name") or g["id"]) for g in _get_groups()}


def _is_enabled() -> bool:
    return (db_cache.app_config_get(_CFG_ENABLED, "1") or "1") == "1"


def _get_group_name() -> str:
    """主星球名（兼容旧 status 字段）。"""
    groups = _get_groups()
    return (groups[0].get("name") if groups else "") or ""


def blog_categories_with_names() -> list[dict]:
    """侧边子菜单/页面分类：按星球聚合 [{name, group_id, count}]，含星球显示名。"""
    name_map = _group_name_map()
    out = []
    for c in db_cache.blog_group_counts():
        gid = c["group_id"]
        out.append({"group_id": gid, "name": name_map.get(gid, gid), "count": c["count"]})
    return out


# ── 图片代理（zsxq/有道图片有防盗链，需带正确 Referer 由后端取回）────────────
_IMG_HOSTS = ("zsxq.com", "youdao.com", "ydstatic.com", "126.net", "127.net")
_IMG_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# 把 HTML 里的 <img src="http..."> 改写成走本代理的正则。
_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=)(["\'])(https?://[^"\']+)\2', re.I)


def _is_proxied_host(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in _IMG_HOSTS)


def _proxify_url(url: str) -> str:
    if not url or not _is_proxied_host(url):
        return url
    return "/api/xingqiu/image?u=" + urllib.parse.quote(url, safe="")


def _proxify_html(html: str) -> str:
    """把正文 HTML 里的图片地址改写为走 /api/xingqiu/image 代理。"""
    if not html:
        return html
    def repl(m):
        url = m.group(3)
        if not _is_proxied_host(url):
            return m.group(0)
        return f'{m.group(1)}{m.group(2)}{_proxify_url(url)}{m.group(2)}'
    return _IMG_SRC_RE.sub(repl, html)


# ── 个股标识：把正文里的股名/代码加黑 + 补 id + 可点击跳转 ────────────────────
# 机构荐股正文里出现个股时，渲染成「名称(代码)」的加粗可点链接，点击跳 /stock/<code>。
import functools

_TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")        # 把 HTML 切成「标签 / 文本」交替片段
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_CODE6_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")    # 独立 6 位数字（疑似股票代码）
# 仅由括号/分隔符构成的间隔：用于判定「名称」与其紧邻「代码」是否同一标的，避免双重链接。
_SEP_ONLY_RE = re.compile(r"[\s（）()【】\[\]、,，::：.·\-—_/|]*")


@functools.lru_cache(maxsize=4)
def _name_maps(_version: int) -> tuple[dict, dict]:
    """构建 ({code:name}, {name:code})；name2code 仅收长度≥3 的名字防误匹配。

    入参 ``_version`` 仅用于让 lru_cache 在股名缓存条数变化时失效重建。
    """
    from quantforge.data.storage import stock_meta_cache
    code2name, name2code = {}, {}
    for code, name in stock_meta_cache.get_all_names().items():
        code = str(code).strip()
        name = (name or "").strip()
        if len(code) == 6 and code.isdigit() and name and not name.isdigit():
            code2name[code] = name
            if len(name) >= 3:
                name2code[name] = code
    return code2name, name2code


def _stock_link(code: str, label: str) -> str:
    return (f'<a class="stock-ref" href="/stock/{code}" data-code="{code}">'
            f'<b>{label}</b></a>')


def annotate_stocks(html: str) -> str:
    """把正文里的个股名/代码替换成加粗可点链接（仅处理文本节点，跳过标签/已有<a>内）。"""
    if not html:
        return html
    from quantforge.data.storage import stock_meta_cache
    code2name, name2code = _name_maps(stock_meta_cache.count())
    if not code2name:
        return html

    # 先在去标签纯文本里挑出确实出现的股名，仅用这些构建正则（按长度降序，长名优先）。
    plain = _STRIP_TAGS_RE.sub(" ", html)
    present = sorted((nm for nm in name2code if nm in plain), key=len, reverse=True)
    alts = []
    if present:
        alts.append("(?P<name>" + "|".join(re.escape(n) for n in present) + ")")
    alts.append(r"(?P<code>(?<!\d)\d{6}(?!\d))")
    pat = re.compile("|".join(alts))

    def annotate_text(text: str) -> str:
        """单段纯文本内做替换；把紧邻的「名称(代码)」合并成一处链接，不重复显示。"""
        res, last_end = [], 0
        for m in pat.finditer(text):
            if m.start() < last_end:        # 已被上一处链接吞并的范围，跳过
                continue
            if m.lastgroup == "name":
                nm = m.group("name")
                code = name2code.get(nm)
            else:
                code = m.group("code")
                nm = code2name.get(code)
            if not (code and nm):           # 6 位数字但不是已知代码：原样保留
                continue
            res.append(text[last_end:m.start()])
            end = m.end()
            # 吞并紧跟的同一标的冗余写法：名称后的「(代码)」或代码后的「名称」。
            dup = re.compile(r"[（(]?\s*" + re.escape(code) + r"\s*[）)]?"
                             if m.lastgroup == "name" else re.escape(nm))
            mt = dup.match(text, end)
            if mt:
                end = mt.end()
            res.append(_stock_link(code, f"{nm}({code})"))
            last_end = end
        res.append(text[last_end:])
        return "".join(res)

    out, a_depth = [], 0
    for tok in _TAG_SPLIT_RE.split(html):
        if not tok:
            continue
        if tok.startswith("<"):
            low = tok.lower()
            if low.startswith("<a") and not low.startswith("<area"):
                a_depth += 1
            elif low.startswith("</a"):
                a_depth = max(0, a_depth - 1)
            out.append(tok)
        else:
            out.append(tok if a_depth > 0 else annotate_text(tok))
    return "".join(out)


# ── AI 标题生成 ───────────────────────────────────────────────────────────

_AI_TITLE_SYSTEM = (
    "你是财经资讯编辑。给定一篇知识星球帖子的正文，提炼一个精炼、信息密度高的中文标题。"
    "要求：一句话、不超过 25 个字、点出核心标的/事件/观点，不要书名号、不要引号、不要句号、"
    "不要『标题：』之类前缀，只输出标题本身。"
)


async def _gen_ai_title(text: str) -> str:
    """用 AI 把正文压成一句标题；失败返回空串（调用方回退原 title）。"""
    body = (text or "").strip()
    if not body:
        return ""
    # 正文过长时只取前段，足够提炼标题且省 token。
    snippet = body[:1500]
    try:
        from quantforge.api.ai_client import chat
        # 博客标题指定走 MiniMax（DeepSeek 账号常欠费/限流）；失败仍回退其余 preset。
        out = await chat(
            _AI_TITLE_SYSTEM, snippet, max_tokens=64, caller="blog_title",
            provider="minimax-m3",
        )
    except Exception as exc:
        logger.debug(f"blog._gen_ai_title 失败: {exc}")
        return ""
    title = (out or "").strip().strip("。.！!？?「」『』《》\"' \n")
    # 模型偶尔会带『标题：』前缀，去掉。
    title = re.sub(r"^(标题|题目)\s*[:：]\s*", "", title)
    return title[:40]


async def _fill_ai_titles(items: list[dict]) -> int:
    """为 items（含 post_id + content_text）批量生成 AI 标题并回写库。

    返回成功写入的条数。并发受 ``_AI_TITLE_CONCURRENCY`` 限制。
    """
    if not items:
        return 0
    # 大批量（回填）自动降并发并加节流，避免瞬时打爆 MiniMax 速率限额（429）。
    bulk = len(items) > _AI_TITLE_BULK_THRESHOLD
    concurrency = _AI_TITLE_BULK_CONCURRENCY if bulk else _AI_TITLE_CONCURRENCY
    interval = _AI_TITLE_BULK_INTERVAL if bulk else 0.0
    if bulk:
        logger.info(f"blog._fill_ai_titles: 批量 {len(items)} 条，限流模式 "
                    f"(并发 {concurrency}, 间隔 {interval}s)")
    sem = asyncio.Semaphore(concurrency)
    written = 0

    async def _one(it: dict):
        nonlocal written
        pid = it.get("post_id")
        if not pid:
            return
        async with sem:
            title = await _gen_ai_title(it.get("content_text", ""))
            if interval:
                await asyncio.sleep(interval)
        if title:
            ok = await _run(db_cache.blog_set_ai_title, str(pid), title)
            if ok:
                written += 1

    await asyncio.gather(*[_one(it) for it in items])
    return written


# ── 抓取核心 ──────────────────────────────────────────────────────────────

async def _crawl_group(group_id: str, group_name: str, cookie: str, reason: str,
                       youdao_budget: list[int]) -> dict:
    """抓单个星球一轮：拉主题 → 解析 → 新帖抓有道笔记 → 入库。

    ``youdao_budget`` 是 [剩余额度] 单元素列表，跨星球共享本轮有道抓取上限。
    返回 {group_id, name, added, youdao, ai_titles, error}。
    """
    try:
        topics = await _run(zsxq.fetch_topics, group_id, cookie, _FETCH_COUNT)
    except zsxq.ZsxqError as exc:
        logger.warning(f"blog._crawl_group({group_name}/{group_id}) zsxq 抓取失败: {exc}")
        return {"group_id": group_id, "name": group_name, "added": 0, "youdao": 0,
                "ai_titles": 0, "error": str(exc)}

    # 该星球名称缺失时回填一次（用接口名兜底配置里的名字）。
    if not group_name:
        try:
            group_name = await _run(zsxq.fetch_group_name, group_id, cookie) or group_id
        except Exception:
            group_name = group_id

    parsed = []
    for t in topics:
        try:
            parsed.append(zsxq.parse_topic(t))
        except Exception as exc:
            logger.debug(f"blog: parse_topic 失败: {exc}")

    all_ids = [p["post_id"] for p in parsed if p.get("post_id")]
    existing = await _run(db_cache.blog_existing_ids, all_ids)
    new_posts = [p for p in parsed if p.get("post_id") and p["post_id"] not in existing]

    youdao_fetched = 0
    rows = []
    for p in new_posts:
        yd_links = [u for u in p.get("links", []) if youdao.is_youdao_link(u)]
        yd_results = []
        for url in yd_links:
            if youdao_budget[0] <= 0:
                yd_results.append({"url": url, "ok": False, "title": "", "html": "",
                                   "text": "", "error": "本轮抓取额度已满，稍后重试"})
                continue
            try:
                res = await _run(youdao.fetch_youdao_note, url)
            except Exception as exc:
                res = {"url": url, "ok": False, "title": "", "html": "", "text": "",
                       "error": f"抓取异常: {exc}"}
            yd_results.append(res)
            youdao_fetched += 1
            youdao_budget[0] -= 1
        rows.append({
            "post_id": p["post_id"],
            "group_id": group_id,
            "author": p.get("author", ""),
            "title": p.get("title", ""),
            "content_html": p.get("content_html", ""),
            "content_text": p.get("content_text", ""),
            "images": p.get("images", []),
            "youdao": yd_results,
            "created_at": p.get("created_at", ""),
        })

    added = await _run(db_cache.blog_upsert_many, rows) if rows else 0
    titled = await _fill_ai_titles(rows) if rows else 0
    logger.info(f"blog._crawl_group({reason}): group={group_name}/{group_id} "
                f"topics={len(topics)} new={added} youdao={youdao_fetched} ai_titles={titled}")
    return {"group_id": group_id, "name": group_name, "added": added,
            "youdao": youdao_fetched, "ai_titles": titled, "error": ""}


async def crawl_once(reason: str = "manual") -> dict:
    """抓一轮：遍历所有配置的星球，各拉最近 N 条 → 入库。返回汇总摘要。"""
    cookie = _get_cookie()
    if not _is_enabled():
        _last_status.update(at=datetime.now().isoformat(), ok=False, added=0,
                            error="已暂停（enabled=0）", youdao=0)
        return dict(_last_status)
    if not cookie:
        _last_status.update(at=datetime.now().isoformat(), ok=False, added=0,
                            error="未配置 zsxq cookie / access_token", youdao=0)
        return dict(_last_status)

    groups = _get_groups()
    budget = [_MAX_YOUDAO_PER_CYCLE]   # 跨星球共享本轮有道额度
    per_group, errors = [], []
    total_added = total_youdao = total_titled = 0
    for g in groups:
        res = await _crawl_group(g["id"], g.get("name", ""), cookie, reason, budget)
        per_group.append(res)
        total_added += res["added"]
        total_youdao += res["youdao"]
        total_titled += res["ai_titles"]
        if res["error"]:
            errors.append(f"{res['name'] or res['group_id']}: {res['error']}")

    # 全部星球都失败才算整轮失败；部分失败仅记 error 文本但 ok=True（其余已入库）。
    ok = total_added > 0 or not errors or len(errors) < len(groups)
    _last_status.update(at=datetime.now().isoformat(), ok=ok, added=total_added,
                        error="；".join(errors), youdao=total_youdao,
                        ai_titles=total_titled, groups=per_group)
    logger.info(f"blog.crawl_once({reason}): groups={len(groups)} new={total_added} "
                f"youdao={total_youdao} ai_titles={total_titled}")
    return dict(_last_status)


async def _backfill_one_group(group_id: str, days: int,
                              target_count: int | None) -> dict:
    """回填单个星球的历史帖入库（不抓有道正文，懒加载兜底）。返回 {group_id, fetched, added}。"""
    from quantforge.data.feed.zsxq import fetch_topics_since
    from datetime import timezone
    from functools import partial

    cookie = _get_cookie()
    since = datetime.now(timezone.utc).astimezone() - timedelta(days=days)
    # 可续传：从库里已有最早一条继续往更早翻（密集圈单轮撞 1059 会提前停，
    # 多轮逐步把窗口推进到一年前），而不是每次都从最新重抓那批。
    oldest = await _run(db_cache.blog_oldest_created, group_id)
    start_cursor = zsxq._cursor_from(oldest) if oldest else None
    # 慢速回填：页间隔 3.5s 降低 1059 概率；target_count 控制总量。
    fetch = partial(fetch_topics_since, group_id, cookie, since,
                    sleep_s=3.5, max_pages=60, target_count=target_count,
                    start_end_time=start_cursor)
    try:
        topics = await _run(fetch)
    except Exception as exc:
        logger.warning(f"blog._backfill_one_group({group_id}) 抓取失败: {exc}")
        return {"group_id": group_id, "fetched": 0, "added": 0, "error": str(exc)}

    parsed = []
    for t in topics:
        try:
            parsed.append(zsxq.parse_topic(t))
        except Exception as exc:
            logger.debug(f"blog.backfill: parse_topic 失败: {exc}")

    all_ids = [p["post_id"] for p in parsed if p.get("post_id")]
    existing = await _run(db_cache.blog_existing_ids, all_ids)
    new_posts = [p for p in parsed if p.get("post_id") and p["post_id"] not in existing]

    rows = []
    for p in new_posts:
        yd_links = [u for u in p.get("links", []) if youdao.is_youdao_link(u)]
        yd_results = [{"url": u, "ok": False, "title": "", "html": "", "text": "",
                       "error": "历史回填未抓正文，打开自动补抓"} for u in yd_links]
        rows.append({
            "post_id": p["post_id"], "group_id": group_id,
            "author": p.get("author", ""), "title": p.get("title", ""),
            "content_html": p.get("content_html", ""),
            "content_text": p.get("content_text", ""),
            "images": p.get("images", []), "youdao": yd_results,
            "created_at": p.get("created_at", ""),
        })

    added = await _run(db_cache.blog_upsert_many, rows) if rows else 0
    logger.info(f"blog._backfill_one_group: group={group_id} window={days}d "
                f"target={target_count} fetched={len(topics)} new={added}")
    return {"group_id": group_id, "fetched": len(topics), "added": added, "error": ""}


async def backfill_history(days: int = _BACKFILL_DAYS,
                           target_count: int | None = _BACKFILL_TARGET,
                           group_id: str | None = None) -> dict:
    """回填历史帖子入库并补 AI 标题。``group_id`` 指定单星球；省略则遍历全部配置星球。

    每个星球分页向前翻：拉到 ``days`` 天前、或累计 ``target_count`` 条为止（取先到者）。
    遇 zsxq 1059 限流自动退避重试；持续限流则保留已拉部分，再次调用可继续累积。
    """
    cookie = _get_cookie()
    if not cookie:
        return {"ok": False, "error": "未配置 zsxq cookie / access_token"}

    groups = ([{"id": group_id, "name": _group_name_map().get(group_id, group_id)}]
              if group_id else _get_groups())
    per_group, errors = [], []
    total_fetched = total_added = 0
    for g in groups:
        res = await _backfill_one_group(g["id"], days, target_count)
        res["name"] = g.get("name", "")
        per_group.append(res)
        total_fetched += res["fetched"]
        total_added += res["added"]
        if res.get("error"):
            errors.append(f"{g.get('name') or g['id']}: {res['error']}")

    # 为库中所有缺 AI 标题的帖子补标题（含本次新入库 + 历史遗留）。
    missing = await _run(db_cache.blog_missing_ai_title, 2000)
    titled = await _fill_ai_titles(missing)

    total = await _run(db_cache.blog_count)
    logger.info(f"blog.backfill_history: groups={len(groups)} window={days}d "
                f"target={target_count} fetched={total_fetched} new={total_added} "
                f"ai_titles={titled} total={total}")
    return {"ok": True, "window_days": days, "target": target_count,
            "groups": per_group, "fetched": total_fetched, "added": total_added,
            "ai_titles": titled, "total": total,
            "error": "；".join(errors)}


async def _lazy_fill_youdao(post: dict) -> dict:
    """懒加载：补抓这篇里尚未取到正文的有道笔记，抓到就回写库（共享给所有账号）。

    后台抓取每轮有上限（``_MAX_YOUDAO_PER_CYCLE``），超额的先存占位；占位帖之后
    不会再进新帖流程，只能在用户打开时按需补抓。抓取结果落库，故第一个打开的账号
    触发后，其余账号直接读到正文。
    """
    pid = post.get("post_id")
    yd_list = post.get("youdao") or []
    if not pid or not any((not yd.get("ok")) and yd.get("url") for yd in yd_list):
        return post

    async with _post_lock(str(pid)):
        # 取锁后重读一遍：可能并发的另一个请求已经抓完。
        fresh = await _run(db_cache.blog_get, pid) or post
        yd_list = fresh.get("youdao") or []
        changed = False
        for i, yd in enumerate(yd_list):
            if yd.get("ok") or not yd.get("url"):
                continue
            try:
                res = await _run(youdao.fetch_youdao_note, yd["url"])
            except Exception as exc:
                res = {"url": yd["url"], "ok": False, "title": "", "html": "",
                       "text": "", "error": f"抓取异常: {exc}"}
            yd_list[i] = res
            if res.get("ok"):
                changed = True
        if changed:
            fresh["youdao"] = yd_list
            await _run(db_cache.blog_upsert_many, [fresh])
            logger.info(f"blog._lazy_fill_youdao: post={pid} 补抓有道正文")
        return fresh


def _seconds_until_next_hour() -> float:
    """距下一个整点（hh:00:00）的秒数。"""
    now = datetime.now()
    nxt = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return max((nxt - now).total_seconds(), 1.0)


async def _auto_backfill_step() -> None:
    """每小时增量后挖一段历史：对「库里已有最早一条仍晚于 _BACKFILL_DAYS 前」的星球，
    各做一轮续传回填（从该圈最早一条往更早翻），逐步把深度推进到半年前。
    已到窗口底的星球本轮近乎空跑（首页即触达窗口外，立即返回），开销极低。
    用 QF_BLOG_AUTO_BACKFILL=0 关闭。"""
    if os.environ.get("QF_BLOG_AUTO_BACKFILL", "1") == "0":
        return
    cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=_BACKFILL_DAYS)
    for g in _get_groups():
        gid = g["id"]
        oldest = await _run(db_cache.blog_oldest_created, gid)
        oct = zsxq._parse_ct(oldest) if oldest else None
        if oct is not None and oct <= cutoff:
            continue   # 该圈已回填到窗口底，无需再挖
        try:
            res = await _backfill_one_group(gid, _BACKFILL_DAYS, _AUTO_BACKFILL_TARGET)
            if res.get("added"):
                logger.info(f"blog.auto_backfill: group={gid}({g.get('name','')}) "
                            f"深挖 +{res['added']}（最早已到 {oldest}）")
        except Exception as exc:
            logger.warning(f"blog.auto_backfill({gid}) 出错: {exc}")
    # 给本轮新挖进来的历史帖补 AI 标题（批量限流模式自动生效）。
    try:
        missing = await _run(db_cache.blog_missing_ai_title, 1000)
        if missing:
            await _fill_ai_titles(missing)
    except Exception as exc:
        logger.debug(f"blog.auto_backfill 补标题失败: {exc}")


async def crawl_loop() -> None:
    """后台循环：整点每小时抓一轮增量 + 一段历史续传回填。app 生命周期里启动。"""
    logger.info("blog.crawl_loop: 启动知识星球博客抓取（整点每小时）")
    # 启动后稍等片刻再首抓，避免和其他 warmer 抢冷启动资源。
    await asyncio.sleep(20)
    while True:
        try:
            if _is_enabled() and _get_cookie():
                await crawl_once("scheduled")
                await _auto_backfill_step()
        except asyncio.CancelledError:
            logger.info("blog.crawl_loop: cancelled")
            raise
        except Exception as exc:
            logger.warning(f"blog.crawl_loop 轮次出错: {exc}")
        await asyncio.sleep(_seconds_until_next_hour())


# ── Schemas ───────────────────────────────────────────────────────────────

class BlogConfig(BaseModel):
    cookie: Optional[str] = None      # None=不改；""=清空
    group_id: Optional[str] = None
    enabled: Optional[bool] = None


# ── 端点 ──────────────────────────────────────────────────────────────────

@router.get("/posts")
def list_posts(page: int = 1, page_size: int = 20, search: Optional[str] = None,
               category: Optional[str] = None,
               _user: dict = Depends(get_current_user)):
    # category 现为星球 group_id（侧边子菜单/页面分类按星球分）。
    posts, total = db_cache.blog_query(
        search=search, group_id=category, page=page, page_size=page_size)
    return {
        "posts": posts,
        "total": total,
        "page": page,
        "page_size": page_size,
        "fetched_at": db_cache.blog_latest_fetch(),
        "count": db_cache.blog_count(),
        "categories": blog_categories_with_names(),
    }


@router.get("/posts/{post_id}")
async def get_post(post_id: str, _user: dict = Depends(get_current_user)):
    post = await _run(db_cache.blog_get, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    # 懒加载：补抓尚未取到的有道正文（在改写图片前，确保回写库的是原始地址）。
    post = await _lazy_fill_youdao(post)
    # 改写图片地址走代理（zsxq/有道防盗链），原始数据不变，仅在返回时处理。
    # 再把正文里的个股名/代码加黑、补 id 并改成可点链接（机构荐股专属）。
    post["content_html"] = annotate_stocks(_proxify_html(post.get("content_html", "")))
    post["images"] = [_proxify_url(u) for u in (post.get("images") or [])]
    for yd in post.get("youdao") or []:
        if yd.get("html"):
            yd["html"] = annotate_stocks(_proxify_html(yd["html"]))
    return post


@router.get("/image")
def proxy_image(u: str = Query(..., description="待代理的图片 URL")):
    """图片代理：zsxq/有道图片有防盗链，由后端带正确 Referer 取回再转给前端。

    无需鉴权（``<img>`` 标签无法携带 Bearer），但仅允许白名单图床，避免变成开放代理。
    """
    if not _is_proxied_host(u):
        raise HTTPException(status_code=400, detail="不允许的图片来源")
    host = (urllib.parse.urlparse(u).hostname or "")
    referer = "https://note.youdao.com/" if "youdao" in host else "https://wx.zsxq.com/"
    try:
        r = requests.get(u, headers={"User-Agent": _IMG_UA, "Referer": referer},
                         timeout=15)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"图片获取失败: {exc}")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail="上游图片返回非 200")
    ctype = r.headers.get("content-type", "image/jpeg")
    return Response(content=r.content, media_type=ctype,
                    headers={"Cache-Control": "public, max-age=86400"})


@router.post("/refresh")
async def refresh(_user: dict = Depends(get_current_user)):
    return await crawl_once("manual")


@router.post("/backfill")
async def backfill(days: int = Query(_BACKFILL_DAYS, ge=1, le=365),
                   target: int = Query(_BACKFILL_TARGET, ge=50, le=2000),
                   group: Optional[str] = Query(None, description="只回填指定星球 group_id；省略=全部"),
                   _user: dict = Depends(get_current_user)):
    """一次性回填历史帖子入库并生成 AI 标题。

    遍历所有配置星球（或 ``group`` 指定的单个），各拉到 ``days`` 天前 / 累计 ``target``
    条为止（默认半年 / 500 条）。慢速翻页 + 1059 退避重试；被持续限流提前停止时可再次
    调用继续累积。
    """
    return await backfill_history(days, target, group)


@router.get("/institution-winrate")
async def institution_winrate(
    lookback_days: int = Query(120, ge=7, le=400, description="回看天数（按发帖日筛选）"),
    min_samples: int = Query(3, ge=1, le=50, description="排名纳入的最少样本数"),
    group: Optional[str] = Query(None, description="星球 group_id；省略=调研纪要"),
    _user: dict = Depends(get_current_user),
):
    """调研纪要推荐机构胜率：解析【机构】标签 + 推荐个股，按发帖后 1/3/5/30
    交易日算绝对/相对(沪深300)胜率，按机构聚合排名。离线读 K 线，不联网。"""
    from quantforge.api import research_winrate as rw
    gid = group or rw.GROUP_ID
    return await asyncio.to_thread(rw.compute, lookback_days, min_samples, gid)


@router.get("/status")
def status(_user: dict = Depends(get_current_user)):
    return {
        "count": db_cache.blog_count(),
        "last_fetch": db_cache.blog_latest_fetch(),
        "enabled": _is_enabled(),
        "cookie_set": bool(_get_cookie()),
        "group_id": _get_group(),
        "group_name": _get_group_name(),
        "group_url": f"https://wx.zsxq.com/group/{_get_group()}",
        "groups": _get_groups(),
        "last_run": _last_status,
        "interval_seconds": _CRAWL_INTERVAL,
    }


@router.get("/config")
def get_config(_user: dict = Depends(get_current_user)):
    return {
        "cookie_set": bool(_get_cookie()),
        "group_id": _get_group(),
        "group_name": _get_group_name(),
        "group_url": f"https://wx.zsxq.com/group/{_get_group()}",
        "groups": _get_groups(),
        "enabled": _is_enabled(),
    }


@router.put("/config")
def set_config(cfg: BlogConfig, _user: dict = Depends(get_current_user)):
    if cfg.cookie is not None:
        db_cache.app_config_set(_CFG_COOKIE, cfg.cookie.strip())
    if cfg.group_id is not None and cfg.group_id.strip():
        db_cache.app_config_set(_CFG_GROUP, cfg.group_id.strip())
    if cfg.enabled is not None:
        db_cache.app_config_set(_CFG_ENABLED, "1" if cfg.enabled else "0")
    return {
        "cookie_set": bool(_get_cookie()),
        "group_id": _get_group(),
        "enabled": _is_enabled(),
    }
