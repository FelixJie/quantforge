"""统一数据源门面：优先 iFinD，自动回退到新浪/腾讯。

各业务模块（watchlist / market / sector）调用本模块，而不是直接调具体源；
iFinD 装好并登录成功后，相关能力自动切到 iFinD，无需改业务代码。

返回结构与腾讯行情保持一致（name/price/change_pct/pe_ttm/pb/...）。
"""

from __future__ import annotations

from quantforge.data.feed import ifind_feed


def active_source() -> str:
    """当前生效的主数据源标识。"""
    return "ifind" if ifind_feed.available() else "sina_tencent"


def status() -> dict:
    return {
        "active": active_source(),
        "ifind": ifind_feed.status(),
        "fallback": "sina_tencent",
    }


def quotes(codes: list[str]) -> dict:
    """批量实时行情 {code: {...}}。iFinD 优先，回退腾讯。"""
    if not codes:
        return {}
    q = ifind_feed.quote(codes)
    if q:
        return q
    from quantforge.data.feed.mootdx_feed import _tencent_quote
    try:
        return _tencent_quote(codes) or {}
    except Exception:
        return {}


def kline(code: str, start: str, end: str) -> list[dict] | None:
    """日 K 线。iFinD 优先；返回 None 表示调用方应走原有本地/下载逻辑。"""
    return ifind_feed.kline(code, start, end)
