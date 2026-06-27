"""知识星球（zsxq）星球主题抓取 + 富文本解析。

入口 :func:`fetch_topics` 调用官方 Web 接口拉取某星球最新主题；
:func:`parse_topic` 把一条原始主题归一化成可入库的博客结构，并解析出正文里
内嵌的网页链接（含有道笔记，供上层抓取内联展示）。

鉴权
====
星球内容是会员私有的，必须带上你登录 ``wx.zsxq.com`` 后的
``zsxq_access_token`` cookie。token 会过期，过期后接口返回
``succeeded=false`` / 401，需要在站内重新粘贴更新。

接口
====
``GET https://api.zsxq.com/v2/groups/{group_id}/topics?scope=all&count=20``
返回 ``{"succeeded": true, "resp_data": {"topics": [...]}}``。

富文本
======
zsxq 的 ``text`` 字段把链接/话题/@人 以自闭合标签内嵌进正文，属性值是
URL 编码的，例如::

    <e type="web" href="https%3A%2F%2Fnote.youdao.com%2Fs%2Fxxx" title="%E6%A0%87%E9%A2%98" />
    <e type="hashtag" hid="123" title="%23%E8%82%A1%E7%A5%A8%23" />
    <e type="mention" uid="1" title="@%E6%9F%90%E4%BA%BA" />

:func:`_render_text` 把这些标签转成 HTML（``<a>/<span>/@名``），其余文本转义并
保留换行。
"""

from __future__ import annotations

import html as _html
import re
import time
import uuid
from datetime import datetime
from urllib.parse import unquote

import requests
from loguru import logger

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_TIMEOUT = 15
_API = "https://api.zsxq.com/v2/groups/{gid}/topics"

# 匹配 zsxq 内嵌标签 <e ... /> 或 <e ...></e>
_E_TAG = re.compile(r"<e\b([^>]*?)/?>", re.I)
_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


class ZsxqError(Exception):
    """抓取失败（凭证过期 / 接口异常 / 网络问题）。"""


class ZsxqRateLimited(ZsxqError):
    """code=1059 反爬限流（短时滚动窗口）。退避后重试大概率能成，cookie 仍有效。"""


# ── 抓取 ──────────────────────────────────────────────────────────────────

def _headers(cookie: str) -> dict:
    cookie = (cookie or "").strip()
    # 用户可能只粘贴了 token，也可能粘贴了整段 cookie；都规整成 cookie 头。
    if cookie and "=" not in cookie:
        cookie = f"zsxq_access_token={cookie}"
    return {
        "User-Agent": _UA,
        "Cookie": cookie,
        "Referer": "https://wx.zsxq.com/",
        "Origin": "https://wx.zsxq.com",
        "Accept": "application/json, text/plain, */*",
        # 贴近浏览器客户端，降低被反爬限流（code 1059）的概率。
        "x-version": "2.64.0",
        "x-request-id": str(uuid.uuid4()),
        "x-timestamp": str(int(time.time())),
        "sec-fetch-site": "same-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }


def _fetch_topics_page(group_id: str, cookie: str, count: int = 20,
                       end_time: str | None = None) -> list[dict]:
    """拉一页主题（最多 30 条）。``end_time`` 为分页游标（拉早于该时刻的主题）。

    失败抛 ZsxqError。
    """
    if not cookie or not cookie.strip():
        raise ZsxqError("未配置 zsxq cookie / access_token")
    url = _API.format(gid=group_id)
    params = {"scope": "all", "count": max(1, min(int(count), 30))}
    if end_time:
        params["end_time"] = end_time
    try:
        resp = requests.get(url, headers=_headers(cookie), params=params, timeout=_TIMEOUT)
    except Exception as exc:
        raise ZsxqError(f"网络请求失败: {exc}") from exc

    if resp.status_code in (401, 403):
        raise ZsxqError(f"鉴权失败（{resp.status_code}）—— cookie/token 可能已过期，请重新粘贴")
    if resp.status_code != 200:
        raise ZsxqError(f"接口返回 HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
    except Exception as exc:
        raise ZsxqError(f"响应不是 JSON（可能被风控/验证码拦截）: {resp.text[:200]}") from exc

    if not data.get("succeeded"):
        code = data.get("code")
        info = data.get("info") or data.get("error") or ""
        # 1059 = 反爬限流（非官方工具访问），多为短时滚动窗口，下个周期自动重试即可，
        # 与 cookie/token 失效无关。
        if code == 1059:
            raise ZsxqRateLimited(f"被反爬限流 code=1059（短时限流，下个周期自动重试；cookie 仍有效）{info}")
        raise ZsxqError(f"接口失败 code={code} {info}（cookie/token 可能已失效）")

    topics = (data.get("resp_data") or {}).get("topics") or []
    if not isinstance(topics, list):
        return []
    return topics


def fetch_topics(group_id: str, cookie: str, count: int = 20) -> list[dict]:
    """拉取某星球最新 ``count`` 条主题，返回原始 topic 列表。失败抛 ZsxqError。"""
    return _fetch_topics_page(group_id, cookie, count)


def _cursor_from(create_time: str) -> str:
    """由一条主题的 create_time 推出下一页 end_time 游标。

    zsxq 的 end_time 是“拉早于此刻的主题”。直接用最后一条的 create_time 会把它自己
    再带进来（边界重复），故减 1 毫秒。create_time 形如
    ``2024-01-02T15:04:05.123+0800``。
    """
    if not create_time:
        return ""
    try:
        # 拆出毫秒前的主体与时区尾巴
        m = re.match(r"(.*\.)(\d{3})(.*)$", create_time)
        if m:
            head, ms, tz = m.group(1), int(m.group(2)), m.group(3)
            ms -= 1
            if ms < 0:
                # 借位到秒级；简单起见退一秒、毫秒置 999
                ms = 999
            return f"{head}{ms:03d}{tz}"
    except Exception:
        pass
    return create_time


# 1059 限流退避：分页回填会连续打多页，极易触发 1059 滚动窗口限流。
# 遇 1059 不立刻放弃，退避后重试本页；重试仍失败才中断（已拉到的照常返回）。
_RL_RETRIES = 4
_RL_BACKOFF = [8, 20, 45, 90]   # 秒；第 N 次重试前等待（限流窗口偏长，给足时间）


def _fetch_page_with_backoff(group_id: str, cookie: str, count: int,
                             end_time: str | None) -> list[dict]:
    """拉一页；遇 1059 限流退避重试。非限流错误（鉴权失效等）直接抛出。"""
    for attempt in range(_RL_RETRIES + 1):
        try:
            return _fetch_topics_page(group_id, cookie, count, end_time)
        except ZsxqRateLimited:
            if attempt >= _RL_RETRIES:
                raise
            wait = _RL_BACKOFF[min(attempt, len(_RL_BACKOFF) - 1)]
            logger.warning(f"zsxq 1059 限流，退避 {wait}s 后重试本页 "
                           f"({attempt + 1}/{_RL_RETRIES})")
            time.sleep(wait)
    return []


def fetch_topics_since(group_id: str, cookie: str, since_ts: datetime,
                       *, page_count: int = 30, max_pages: int = 60,
                       sleep_s: float = 0.5, target_count: int | None = None,
                       start_end_time: str | None = None) -> list[dict]:
    """分页向前翻，拉取 ``since_ts`` 之后（更晚）的全部主题。

    zsxq 单页最多 30 条，用 end_time 游标逐页向更早翻，直到翻到早于 since_ts、
    拉够 ``target_count`` 条（若指定）、或没有更多。``max_pages`` 兜底防止无限翻页。
    遇 1059 限流自动退避重试本页（见 ``_fetch_page_with_backoff``）；若退避后仍被限流，
    则停止翻页并返回**已拉到的部分**（不丢弃，便于多轮慢速累积）。

    ``start_end_time`` 为**起始游标**（拉早于该时刻的主题）：用于**可续传回填**——
    密集发帖的星球单次会撞 1059 提前停，下次从「库里已有最早一条」继续往更早翻，
    每轮把窗口往一年前推进，而非反复重抓最近那批。省略时从最新开始。
    返回去重后的原始 topic 列表（新→旧）。
    """
    out: list[dict] = []
    seen: set[str] = set()
    end_time: str | None = start_end_time or None
    for _page in range(max_pages):
        try:
            batch = _fetch_page_with_backoff(group_id, cookie, page_count, end_time)
        except ZsxqRateLimited:
            # 退避后仍 1059：保留已拉到的，停止本轮（下一轮回填继续往更早翻）
            logger.warning(f"zsxq 回填遇持续 1059，本轮提前停止，已拉 {len(out)} 条")
            break
        if not batch:
            break
        reached_old = False
        last_ct = ""
        for t in batch:
            pid = str(t.get("topic_id", ""))
            ct = t.get("create_time", "")
            last_ct = ct or last_ct
            if pid and pid in seen:
                continue
            ctd = _parse_ct(ct)
            if ctd is not None and ctd < since_ts:
                reached_old = True
                continue  # 早于窗口，丢弃但继续扫完本页以拿到游标
            if pid:
                seen.add(pid)
            out.append(t)
        if target_count is not None and len(out) >= target_count:
            break  # 已拉够目标条数
        if reached_old:
            break  # 已翻到时间窗口外，停止
        if not last_ct:
            break
        end_time = _cursor_from(last_ct)
        if sleep_s:
            time.sleep(sleep_s)  # 降速，避免触发 1059 限流
    return out


def _parse_ct(create_time: str) -> datetime | None:
    """解析 zsxq create_time（含时区）为 datetime；失败返回 None。"""
    if not create_time:
        return None
    s = create_time.strip()
    # 把 +0800 规整成 +08:00 供 fromisoformat 解析
    m = re.match(r"^(.*[+-]\d{2})(\d{2})$", s)
    if m:
        s = f"{m.group(1)}:{m.group(2)}"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def fetch_group_name(group_id: str, cookie: str) -> str | None:
    """取星球名称（如「调研纪要」）。失败返回 None（不抛异常）。"""
    if not cookie:
        return None
    try:
        r = requests.get(f"https://api.zsxq.com/v2/groups/{group_id}",
                         headers=_headers(cookie), timeout=_TIMEOUT)
        d = r.json()
    except Exception:
        return None
    if not d.get("succeeded"):
        return None
    g = (d.get("resp_data") or {}).get("group") or {}
    return g.get("name")


# ── 富文本渲染 ────────────────────────────────────────────────────────────

def _render_e_tag(attrs_raw: str, links_out: list[str]) -> str:
    attrs = {k: v for k, v in _ATTR.findall(attrs_raw)}
    etype = (attrs.get("type") or "").lower()
    title = unquote(attrs.get("title", ""))
    if etype == "web":
        href = unquote(attrs.get("href", ""))
        if href:
            links_out.append(href)
        label = title or href
        return (f'<a href="{_html.escape(href, quote=True)}" target="_blank" '
                f'rel="noopener">{_html.escape(label)}</a>')
    if etype == "hashtag":
        return f'<span class="zsxq-tag">{_html.escape(title)}</span>'
    if etype == "mention":
        return f'<span class="zsxq-at">{_html.escape(title)}</span>'
    # 未知类型：保留可见标题（若有）
    return _html.escape(title)


def _render_text(text: str, links_out: list[str]) -> str:
    """把 zsxq 富文本 ``text`` 转为安全 HTML，并把网页链接收集到 links_out。"""
    if not text:
        return ""
    parts: list[str] = []
    pos = 0
    for m in _E_TAG.finditer(text):
        # 标签前的普通文本：转义 + 换行转 <br>
        chunk = text[pos:m.start()]
        if chunk:
            parts.append(_html.escape(chunk).replace("\n", "<br/>"))
        parts.append(_render_e_tag(m.group(1), links_out))
        pos = m.end()
    tail = text[pos:]
    if tail:
        parts.append(_html.escape(tail).replace("\n", "<br/>"))
    return "".join(parts)


def _collect_images(node: dict) -> list[str]:
    out: list[str] = []
    for img in (node.get("images") or []):
        for key in ("original", "large", "thumbnail"):
            sub = img.get(key) or {}
            u = sub.get("url")
            if u:
                out.append(u)
                break
    return out


# ── 归一化 ────────────────────────────────────────────────────────────────

def parse_topic(topic: dict) -> dict:
    """把一条原始 topic 归一化为博客入库结构 + 内嵌链接列表。

    返回字段：post_id, author, title, content_html, content_text, images, links。
    """
    post_id = str(topic.get("topic_id", "")).strip()
    created = topic.get("create_time", "")
    ttype = (topic.get("type") or "").lower()

    links: list[str] = []
    images: list[str] = []
    author = ""
    html_parts: list[str] = []
    text_parts: list[str] = []

    def _emit(node_text: str, label: str | None = None):
        rendered = _render_text(node_text or "", links)
        if label:
            html_parts.append(f'<p class="zsxq-label">{label}</p>')
        if rendered:
            html_parts.append(f"<p>{rendered}</p>")
        if node_text:
            # 纯文本：去掉内嵌标签
            text_parts.append(_E_TAG.sub("", node_text))

    if ttype in ("q&a", "qa"):
        q = topic.get("question") or {}
        a = topic.get("answer") or {}
        author = ((a.get("owner") or {}).get("name")
                  or (q.get("owner") or {}).get("name") or "")
        _emit(q.get("text", ""), label="❓ 问题")
        images += _collect_images(q)
        _emit(a.get("text", ""), label="💬 回答")
        images += _collect_images(a)
    else:
        talk = topic.get("talk") or {}
        author = (talk.get("owner") or {}).get("name", "")
        _emit(talk.get("text", ""))
        images += _collect_images(talk)
        # 附带的文章/文件标题也收进链接（若有 article）
        article = talk.get("article") or {}
        if article.get("article_url"):
            links.append(article["article_url"])
            html_parts.append(
                f'<p><a href="{_html.escape(article["article_url"], quote=True)}" '
                f'target="_blank" rel="noopener">📄 {_html.escape(article.get("title", "原文链接"))}</a></p>'
            )

    content_text = "\n".join(t.strip() for t in text_parts if t.strip())
    title = (topic.get("title") or "").strip()
    if not title:
        # 用正文首行当标题（完整，不截断）
        first = content_text.splitlines()[0] if content_text else ""
        title = first or "无标题"

    return {
        "post_id": post_id,
        "author": author,
        "title": title,
        "content_html": "".join(html_parts),
        "content_text": content_text,
        "images": images,
        "links": links,
        "created_at": created,
    }
