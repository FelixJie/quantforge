"""数据源门面 datasource.py 回退链回归测试。

被测：src/quantforge/data/feed/datasource.py
门面优先 iFinD，回退新浪/腾讯。这里全部用 monkeypatch 替身，不发任何真实网络请求。

回退逻辑（按当前源码实测）：
- quotes(): 先调 ifind_feed.quote(codes)，结果为真则直接返回；否则在函数内部
  import mootdx_feed._tencent_quote 兜底，其异常被吞为 {}。
- kline(): 直接透传 ifind_feed.kline，返回 None 表示调用方走本地逻辑。
- active_source()/status(): 取决于 ifind_feed.available()。
"""

from __future__ import annotations

from quantforge.data.feed import datasource
from quantforge.data.feed import ifind_feed
from quantforge.data.feed import mootdx_feed


# ── 公开接口/签名存在性 ─────────────────────────────────────────────────────
def test_public_api_exists():
    """门面的关键公开函数都存在且可调用。"""
    for name in ("active_source", "status", "quotes", "kline"):
        assert hasattr(datasource, name), f"datasource 缺少 {name}"
        assert callable(getattr(datasource, name))


# ── quotes 回退链 ───────────────────────────────────────────────────────────
def test_quotes_prefers_ifind(monkeypatch):
    """iFinD 有数据时直接返回 iFinD 结果，不触碰腾讯兜底。"""
    ifind_payload = {"600000": {"name": "浦发银行", "price": 10.0}}
    monkeypatch.setattr(ifind_feed, "quote", lambda codes: ifind_payload)

    # 腾讯兜底若被调用就让测试炸掉，证明没走回退
    def _boom(codes):
        raise AssertionError("不应回退到腾讯：iFinD 已有数据")

    monkeypatch.setattr(mootdx_feed, "_tencent_quote", _boom)

    out = datasource.quotes(["600000"])
    assert out == ifind_payload


def test_quotes_falls_back_to_tencent_when_ifind_empty(monkeypatch):
    """iFinD 返回空时，自动回退腾讯并返回腾讯的兜底数据。"""
    calls = {"tencent": 0}
    tencent_payload = {"000001": {"name": "平安银行", "price": 12.3}}

    monkeypatch.setattr(ifind_feed, "quote", lambda codes: {})  # iFinD 无数据

    def _tencent(codes):
        calls["tencent"] += 1
        return tencent_payload

    monkeypatch.setattr(mootdx_feed, "_tencent_quote", _tencent)

    out = datasource.quotes(["000001"])
    assert calls["tencent"] == 1, "iFinD 空时应回退调用腾讯一次"
    assert out == tencent_payload


def test_quotes_tencent_exception_swallowed(monkeypatch):
    """回退源（腾讯）抛异常时被吞为空字典，门面不向上抛错。"""
    monkeypatch.setattr(ifind_feed, "quote", lambda codes: {})

    def _boom(codes):
        raise RuntimeError("network down")

    monkeypatch.setattr(mootdx_feed, "_tencent_quote", _boom)

    out = datasource.quotes(["000001"])
    assert out == {}


def test_quotes_tencent_returns_none_normalized(monkeypatch):
    """腾讯返回 None 时被规整为 {}。"""
    monkeypatch.setattr(ifind_feed, "quote", lambda codes: {})
    monkeypatch.setattr(mootdx_feed, "_tencent_quote", lambda codes: None)
    assert datasource.quotes(["000001"]) == {}


def test_quotes_empty_codes_short_circuits(monkeypatch):
    """codes 为空直接返回 {}，连 iFinD 都不调。"""
    def _boom(codes):
        raise AssertionError("空 codes 不应触发任何数据源调用")

    monkeypatch.setattr(ifind_feed, "quote", _boom)
    monkeypatch.setattr(mootdx_feed, "_tencent_quote", _boom)
    assert datasource.quotes([]) == {}


# ── kline 透传 ──────────────────────────────────────────────────────────────
def test_kline_passthrough(monkeypatch):
    """kline() 透传 ifind_feed.kline 的返回。"""
    bars = [{"date": "2025-01-02", "close": 9.9}]
    captured = {}

    def _kline(code, start, end):
        captured["args"] = (code, start, end)
        return bars

    monkeypatch.setattr(ifind_feed, "kline", _kline)
    out = datasource.kline("600000", "2025-01-01", "2025-01-31")
    assert out == bars
    assert captured["args"] == ("600000", "2025-01-01", "2025-01-31")


def test_kline_none_means_local(monkeypatch):
    """iFinD 无数据返回 None，门面原样返回 None（调用方走本地逻辑）。"""
    monkeypatch.setattr(ifind_feed, "kline", lambda c, s, e: None)
    assert datasource.kline("600000", "2025-01-01", "2025-01-31") is None


# ── active_source / status ─────────────────────────────────────────────────
def test_active_source_reflects_ifind_availability(monkeypatch):
    """available()==True 走 ifind，否则 sina_tencent。"""
    monkeypatch.setattr(ifind_feed, "available", lambda: True)
    assert datasource.active_source() == "ifind"
    monkeypatch.setattr(ifind_feed, "available", lambda: False)
    assert datasource.active_source() == "sina_tencent"


def test_status_shape(monkeypatch):
    """status() 返回 active/ifind/fallback 三个键，fallback 恒为 sina_tencent。"""
    monkeypatch.setattr(ifind_feed, "available", lambda: False)
    monkeypatch.setattr(ifind_feed, "status", lambda: {"logged_in": False})
    st = datasource.status()
    assert set(st.keys()) == {"active", "ifind", "fallback"}
    assert st["fallback"] == "sina_tencent"
    assert st["active"] == "sina_tencent"
