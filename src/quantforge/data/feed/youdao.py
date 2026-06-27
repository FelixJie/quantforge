"""有道云笔记（note.youdao.com）公开分享笔记的正文抓取。

知识星球帖子里常贴有道笔记分享链接，形态多样：

* ``https://note.youdao.com/s/<shareKey>``
* ``https://share.note.youdao.com/ynoteshare/...?id=<shareKey>&type=note``
* ``http://note.youdao.com/noteshare?id=<shareKey>``

正文取法（逆向自有道分享页 ``mobile.*.bundle.js``）：对 ``type=note`` 的分享，
内容接口是::

    GET https://note.youdao.com/yws/api/note/<shareKey>
        ?sev=j1&editorType=1&editorVersion=new-json-editor&unloginId=<任意>

关键在 ``sev=j1`` + ``editorVersion=new-json-editor``——否则旧 coremedia 接口
对「新版块编辑器」笔记只返回占位符（“当前笔记内容暂时无法查看/版本过低”）。

返回 JSON 里 ``tl`` 是标题，``content`` 是一段 JSON 字符串，为新版块编辑器结构：
``{"5":[<块>...]}``，块里 ``"8"`` 是文本、``"9"`` 是样式（``{"2":"b"}`` 加粗）、
``"4"."l"`` 是块级别（``h1``/``h2``…）。:func:`_render_new_json` 把它转成 HTML。

旧版 coremedia（``<para>/<text>``）笔记也兼容处理。任何一步失败则 ``ok=False``，
前端只展示原始链接。返回结构::

    {"url", "ok", "title", "html", "text", "error"}

只用标准库 + ``requests``（项目已依赖）。
"""

from __future__ import annotations

import html as _html
import json
import re
from html.parser import HTMLParser

import requests
from loguru import logger

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_TIMEOUT = 15
_NOTE_API = "https://note.youdao.com/yws/api/note/{key}"
_PLACEHOLDER_MARKS = ("暂时无法查看", "版本过低", "请勿编辑当前笔记")


# ── 链接判定 / 解析 ───────────────────────────────────────────────────────

def is_youdao_link(url: str) -> bool:
    u = (url or "").lower()
    return "note.youdao.com" in u or "ynote.163.com" in u


def _share_key(url: str, final_url: str = "") -> str | None:
    """从链接里解析 shareKey：优先 ``?id=``，其次 ``/s/<key>``。"""
    for u in (final_url, url):
        if not u:
            continue
        m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", u)
        if m:
            return m.group(1)
    for u in (url, final_url):
        if not u:
            continue
        m = re.search(r"/s/([A-Za-z0-9_-]+)", u)
        if m:
            return m.group(1)
    return None


# ── HTML 取纯文本 ─────────────────────────────────────────────────────────

class _Stripper(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "tr", "blockquote"}

    def __init__(self) -> None:
        super().__init__()
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCK:
            self._buf.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data:
            self._buf.append(data)

    def text(self) -> str:
        out = "".join(self._buf)
        out = re.sub(r"\n[ \t]+", "\n", out)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()


def _to_text(html_str: str) -> str:
    try:
        p = _Stripper()
        p.feed(html_str or "")
        return p.text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html_str or "").strip()


# ── 新版块编辑器（new-json-editor）解析 ────────────────────────────────────

def _collect_runs(node, parts: list[str]) -> None:
    """递归收集文本片段 ``"8"``，按样式 ``"9"`` 处理加粗，返回行内 HTML 片段。"""
    if isinstance(node, dict):
        if "8" in node and isinstance(node["8"], str):
            txt = _html.escape(node["8"])
            if txt:
                styles = node.get("9") or []
                bold = any(isinstance(s, dict) and s.get("2") == "b" for s in styles)
                parts.append(f"<b>{txt}</b>" if bold else txt)
            return  # 文本叶子，不再深入
        for v in node.values():
            _collect_runs(v, parts)
    elif isinstance(node, list):
        for x in node:
            _collect_runs(x, parts)


def _render_new_json(content_str: str) -> str:
    """把 new-json-editor 的 content 字符串转为 HTML（段落/标题/加粗）。"""
    data = json.loads(content_str)
    blocks = data.get("5")
    if not isinstance(blocks, list):
        return ""
    html_parts: list[str] = []
    for blk in blocks:
        meta = blk.get("4", {}) if isinstance(blk, dict) else {}
        level = meta.get("l") if isinstance(meta, dict) else None
        runs: list[str] = []
        _collect_runs(blk, runs)
        inner = "".join(runs).strip()
        if not inner:
            continue
        if isinstance(level, str) and re.fullmatch(r"h[1-6]", level):
            html_parts.append(f"<{level}>{inner}</{level}>")
        else:
            html_parts.append(f"<p>{inner}</p>")
    return "".join(html_parts)


# ── 旧版 coremedia（<para>/<text>）解析 ────────────────────────────────────

def _coremedia_to_html(xml: str) -> str:
    s = xml
    s = re.sub(r"(?is)<image[^>]*source=\"([^\"]+)\"[^>]*/?>", r'<img src="\1"/>', s)
    s = re.sub(r"(?is)<heading[^>]*>", "<p><b>", s)
    s = re.sub(r"(?is)</heading>", "</b></p>", s)
    s = re.sub(r"(?is)<para[^>]*>", "<p>", s)
    s = re.sub(r"(?is)</para>", "</p>", s)
    s = re.sub(r"(?is)</?(?:text|inline-styles|styles|coId|align|list)[^>]*>", "", s)
    s = re.sub(r"(?is)<br[^>]*/?>", "<br/>", s)
    s = re.sub(r"(?is)<(?!/?(?:p|b|br|img)\b)[^>]+>", "", s)
    return s.strip()


# ── 主入口 ────────────────────────────────────────────────────────────────

def _build_result(url: str) -> dict:
    return {"url": url, "ok": False, "title": "", "html": "", "text": "", "error": ""}


def fetch_youdao_note(url: str) -> dict:
    """抓取一个有道笔记分享链接的正文。"""
    result = _build_result(url)
    if not url:
        result["error"] = "empty url"
        return result

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": _UA,
        "Referer": "https://share.note.youdao.com/",
        "Accept": "application/json, text/html, */*",
    })

    # 1) /s/ 短链先跟随重定向，拿到带 ?id= 的最终地址。
    final_url = ""
    if "/s/" in url:
        try:
            r = sess.get(url, timeout=_TIMEOUT, allow_redirects=True)
            final_url = r.url
        except Exception as exc:
            result["error"] = f"短链跳转失败: {exc}"

    key = _share_key(url, final_url)
    if not key:
        result["error"] = result["error"] or "无法解析 shareKey"
        return result

    # 2) 新版块编辑器内容接口（sev=j1 是关键）。
    try:
        r = sess.get(
            _NOTE_API.format(key=key),
            params={"sev": "j1", "editorType": "1",
                    "editorVersion": "new-json-editor", "unloginId": "qf-reader"},
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        result["error"] = f"内容接口请求失败: {exc}"
        return result

    if r.status_code != 200:
        result["error"] = f"内容接口 HTTP {r.status_code}"
        return result
    try:
        data = r.json()
    except Exception:
        result["error"] = "内容接口未返回 JSON（可能为私有/需登录）"
        return result

    title = (data.get("tl") or "").strip()
    content = data.get("content") or ""
    if not isinstance(content, str) or not content.strip():
        result["error"] = "笔记无正文内容"
        result["title"] = title
        return result

    # 3) 按内容形态选择解析器。
    html_out = ""
    cs = content.lstrip()
    try:
        if cs.startswith("{"):
            # 占位符也常被包成 coremedia，但 new-json 解析对它得到空 → 触发兜底
            html_out = _render_new_json(content)
        if not html_out and ("<para" in content or "<note" in content or "<text" in content):
            if not any(m in content for m in _PLACEHOLDER_MARKS):
                html_out = _coremedia_to_html(content)
    except Exception as exc:
        logger.debug(f"youdao 正文解析失败: {exc}")

    if not html_out:
        # 仍拿不到 → 多半是占位符（旧接口）或未知格式
        if any(m in content for m in _PLACEHOLDER_MARKS):
            result["error"] = "有道返回占位符（新版编辑器笔记，接口未放行）"
        else:
            result["error"] = "未识别的笔记正文格式"
        result["title"] = title
        return result

    text_out = _to_text(html_out)
    result.update(ok=True, title=title, html=html_out, text=text_out, error="")
    return result
