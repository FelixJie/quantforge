"""微信公众号抓取——最小可行性验证脚本（独立，不碰主工程）。

目的：在把功能集成进 quantforge 之前，先用你「自己的订阅号后台」cookie/token，
验证三件事真能跑通：
    1. 按公众号名搜出目标号的 fakeid              （searchbiz 接口）
    2. 按 fakeid 翻页拉出它的全量文章列表          （appmsgpublish 接口）
    3. 本机 IP 直抓单篇文章正文（绕过机房 IP 风控）  （直接 GET 文章页）

用法
====
1. 注册并登录你自己的订阅号后台 https://mp.weixin.qq.com
2. 取两样东西填到下面 COOKIE / TOKEN：
   - TOKEN：登录后地址栏 ...?token=123456789... 里的那串数字
   - COOKIE：F12 → Network → 刷新 → 任一 mp.weixin.qq.com 请求 → 请求头里
             整行 Cookie 复制过来
3. 运行：  python _wechat_mp_probe.py

注意
====
- 这些是公众号后台自家接口，必须带登录态；token/cookie 会过期，过期重取。
- 微信对该接口有频控（ret=200013 「freq control」）。脚本已降速；若仍被限，
  等几分钟再跑，别狂刷。
- 本脚本只读、只打印，不写库、不改任何工程文件。
"""

from __future__ import annotations

import sys
import time
import json
import requests

# ── 在这里填你的后台凭证 ────────────────────────────────────────────────────
ACCOUNT_NAME = "睡前一股"          # 要抓的目标公众号名
TOKEN = ""                         # 地址栏 token=后面那串数字
COOKIE = ""                        # F12 复制的整行 Cookie
MAX_ARTICLES = 20                  # 验证阶段只拉前 N 篇，确认通了再放开
# ───────────────────────────────────────────────────────────────────────────

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_BASE = "https://mp.weixin.qq.com"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": _UA,
        "Referer": f"{_BASE}/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=10&token={TOKEN}&lang=zh_CN",
        "Cookie": COOKIE,
    })
    return s


def _check_ret(data: dict, where: str) -> None:
    base = data.get("base_resp") or {}
    ret = base.get("ret")
    if ret not in (0, None):
        msg = base.get("err_msg", "")
        hint = ""
        if ret == 200013:
            hint = "（freq control 频控，等几分钟再试，别连刷）"
        elif ret in (-1, 200002, 200003):
            hint = "（登录态失效：token/cookie 过期，重新登录后台再取）"
        raise SystemExit(f"[{where}] 接口返回 ret={ret} {msg} {hint}")


def search_account(s: requests.Session, name: str) -> dict:
    """按名字搜公众号，返回第一个匹配（含 fakeid）。"""
    url = f"{_BASE}/cgi-bin/searchbiz"
    params = {
        "action": "search_biz", "begin": 0, "count": 5,
        "query": name, "token": TOKEN, "lang": "zh_CN", "f": "json", "ajax": 1,
    }
    r = s.get(url, params=params, timeout=15)
    data = r.json()
    _check_ret(data, "searchbiz")
    lst = data.get("list") or []
    if not lst:
        raise SystemExit(f"没搜到「{name}」，换个准确的全名再试。")
    return lst[0]


def fetch_article_list(s: requests.Session, fakeid: str, limit: int) -> list[dict]:
    """按 fakeid 翻页拉文章列表（标题/链接/时间）。"""
    url = f"{_BASE}/cgi-bin/appmsgpublish"
    out: list[dict] = []
    begin = 0
    while len(out) < limit:
        params = {
            "sub": "list", "search_field": "null", "begin": begin, "count": 5,
            "query": "", "fakeid": fakeid, "type": "101_1", "free_publish_type": 1,
            "sub_action": "list_ex", "token": TOKEN, "lang": "zh_CN", "f": "json", "ajax": 1,
        }
        r = s.get(url, params=params, timeout=15)
        data = r.json()
        _check_ret(data, "appmsgpublish")
        # publish_page 是一段被转义的 JSON 字符串，需二次解析
        raw = data.get("publish_page")
        if not raw:
            break
        page = json.loads(raw)
        items = page.get("publish_list") or []
        if not items:
            break
        for it in items:
            info_raw = it.get("publish_info")
            if not info_raw:
                continue
            info = json.loads(info_raw)
            for art in info.get("appmsgex") or []:
                out.append({
                    "title": art.get("title", ""),
                    "link": art.get("link", ""),
                    "create_time": art.get("create_time"),
                })
        begin += 5
        time.sleep(1.0)  # 降速防频控
    return out[:limit]


def fetch_article_body(url: str) -> tuple[bool, str]:
    """本机直抓单篇正文，判断是否拿到真实内容（而非验证页）。"""
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
    except Exception as exc:
        return False, f"请求异常: {exc}"
    html = r.text or ""
    if "环境异常" in html or "completing the verification" in html.lower():
        return False, "命中验证页（本机 IP 也被风控？换网络/稍后再试）"
    # 公众号正文容器特征
    ok = ('id="js_content"' in html) or ('rich_media_content' in html)
    return ok, f"HTTP {r.status_code}, 长度 {len(html)}, 正文容器={'有' if ok else '无'}"


def main() -> None:
    if not TOKEN or not COOKIE:
        print("请先在脚本顶部填好 TOKEN 和 COOKIE（见文件头说明）。")
        sys.exit(1)

    s = _session()

    print(f"① 搜索公众号「{ACCOUNT_NAME}」…")
    acc = search_account(s, ACCOUNT_NAME)
    print(f"   命中: {acc.get('nickname')}  fakeid={acc.get('fakeid')}  "
          f"已认证={acc.get('service_type')}")
    fakeid = acc["fakeid"]

    print(f"\n② 拉取文章列表（最多 {MAX_ARTICLES} 篇）…")
    arts = fetch_article_list(s, fakeid, MAX_ARTICLES)
    print(f"   拿到 {len(arts)} 篇：")
    for i, a in enumerate(arts[:10], 1):
        ts = time.strftime("%Y-%m-%d", time.localtime(a["create_time"])) if a.get("create_time") else "?"
        print(f"   {i:>2}. [{ts}] {a['title'][:30]}")
    if len(arts) > 10:
        print(f"   …还有 {len(arts) - 10} 篇")

    if arts:
        print(f"\n③ 本机直抓第一篇正文，验证 IP 能过风控…")
        ok, info = fetch_article_body(arts[0]["link"])
        print(f"   {'✅ 成功' if ok else '❌ 失败'} — {info}")
        if ok:
            print("\n🎉 三步全通！接口可用，可以集成进主工程做全量抓取+落库了。")
        else:
            print("\n⚠️ 列表能拉到，但正文这次没抓到——多半是这台机器当前网络也被风控，"
                  "换个网络或稍后重试 fetch_article_body。")


if __name__ == "__main__":
    main()
