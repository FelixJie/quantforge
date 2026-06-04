"""iFinD (同花顺) 数据源适配器。

依赖官方 iFinDPy SDK（随同花顺 iFinD 客户端 / 数据接口分发，**不在公网 PyPI**）
及凭证（环境变量或项目根 .env）::

    IFIND_USER=你的账号
    IFIND_PWD=你的密码

当 SDK 未安装或凭证缺失/登录失败时，``available()`` 返回 False，
调用方（见 :mod:`quantforge.data.feed.datasource`）自动回退到新浪/腾讯。

返回结构与腾讯行情（``mootdx_feed._tencent_quote``）保持一致，便于无缝切换。

注意：本模块的 iFinD API 调用（指标名/函数签名）需在装好 SDK 后按实际
版本校准——已用 try/except 包裹，任何异常都回退，不会影响线上。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from loguru import logger

_lock = threading.Lock()
_state: dict = {"checked": False, "ok": False, "ths": None}


# ── 凭证 & 登录 ───────────────────────────────────────────────────────────────

def _load_creds() -> tuple[str | None, str | None]:
    user = os.environ.get("IFIND_USER")
    pwd = os.environ.get("IFIND_PWD")
    if user and pwd:
        return user, pwd
    for p in (Path(".env"), Path("data/.env")):
        try:
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("IFIND_USER="):
                    user = user or line.split("=", 1)[1].strip()
                elif line.startswith("IFIND_PWD="):
                    pwd = pwd or line.split("=", 1)[1].strip()
        except Exception:
            pass
    return user, pwd


def _ensure_login() -> bool:
    if _state["checked"]:
        return _state["ok"]
    with _lock:
        if _state["checked"]:
            return _state["ok"]
        _state["checked"] = True
        try:
            import iFinDPy as THS  # type: ignore
        except Exception:
            logger.info("iFinD: SDK 未安装，回退到新浪/腾讯数据源")
            return False
        user, pwd = _load_creds()
        if not user or not pwd:
            logger.info("iFinD: 凭证缺失 (IFIND_USER/IFIND_PWD)，回退到新浪/腾讯数据源")
            return False
        try:
            ret = THS.THS_iFinDLogin(user, pwd)
            ok = ret in (0, "0") or (isinstance(ret, dict) and ret.get("errorcode") == 0)
            if ok:
                _state["ths"] = THS
                _state["ok"] = True
                logger.info("iFinD: 登录成功，已启用 iFinD 数据源")
            else:
                logger.warning(f"iFinD: 登录失败 ret={ret}，回退到新浪/腾讯")
        except Exception as e:
            logger.warning(f"iFinD: 登录异常 {e}，回退到新浪/腾讯")
        return _state["ok"]


def available() -> bool:
    """SDK 已安装、凭证有效且登录成功时为 True。"""
    return _ensure_login()


def reset() -> None:
    """清除登录状态（改了凭证后可调用以重新尝试）。"""
    with _lock:
        _state.update(checked=False, ok=False, ths=None)


def status() -> dict:
    return {"available": available(), "checked": _state["checked"]}


# ── 代码格式 ──────────────────────────────────────────────────────────────────

def _ths_code(code: str) -> str:
    c = str(code).strip().upper()
    if c.endswith((".SH", ".SZ", ".BJ")):
        return c
    if c.startswith(("SH", "SZ", "BJ")):
        return f"{c[2:]}.{c[:2]}"
    if c.startswith(("6", "9")):
        return f"{c}.SH"
    if c.startswith(("4", "8")):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _plain_code(ths_code: str) -> str:
    return str(ths_code).split(".")[0]


# ── 行情 ──────────────────────────────────────────────────────────────────────

# iFinD 基础数据指标 → 归一化字段（指标名需按实际 SDK 版本校准）
_QUOTE_INDICATORS = (
    "ths_last_price_stock;ths_chg_ratio_stock;ths_chg_stock;"
    "ths_open_price_stock;ths_high_price_stock;ths_low_stock;"
    "ths_pre_close_stock;ths_pe_ttm_stock;ths_pb_stock;"
    "ths_turnover_ratio_stock;ths_amt_stock;ths_total_market_value_stock"
)
_QUOTE_MAP = [
    ("price", float), ("change_pct", float), ("change_amt", float),
    ("open", float), ("high", float), ("low", float),
    ("last_close", float), ("pe_ttm", float), ("pb", float),
    ("turnover_pct", float), ("amount_wan", float), ("mcap_yi", float),
]


def quote(codes: list[str]) -> dict | None:
    """批量实时行情，返回 {code: {price, change_pct, pe_ttm, pb, ...}}。

    返回 None 表示 iFinD 不可用或调用失败，调用方应回退。
    """
    if not available() or not codes:
        return None
    THS = _state["ths"]
    ths_codes = ",".join(_ths_code(c) for c in codes)
    try:
        resp = THS.THS_BD(ths_codes, _QUOTE_INDICATORS, "")
        rows = _bd_rows(resp)
        if not rows:
            return None
        out: dict[str, dict] = {}
        for r in rows:
            code = _plain_code(r.get("thscode") or r.get("code") or "")
            if not code:
                continue
            vals = r.get("values") or []
            d: dict = {}
            for (field, caster), v in zip(_QUOTE_MAP, vals):
                try:
                    d[field] = caster(v) if v not in (None, "", "--") else None
                except (TypeError, ValueError):
                    d[field] = None
            d.setdefault("name", r.get("name", ""))
            out[code] = d
        return out or None
    except Exception as e:
        logger.debug(f"iFinD quote failed: {e}")
        return None


def kline(code: str, start: str, end: str) -> list[dict] | None:
    """日 K 线，返回 [{datetime, open, high, low, close, volume}]，None 表示回退。"""
    if not available():
        return None
    THS = _state["ths"]
    try:
        resp = THS.THS_HQ(_ths_code(code), "open;high;low;close;volume", "", start, end)
        series = _hq_series(resp)
        return series or None
    except Exception as e:
        logger.debug(f"iFinD kline failed for {code}: {e}")
        return None


# ── 板块（待装好 SDK 后用 THS_DataPool 实现，目前回退到新浪）─────────────────

def industry_boards() -> list[dict] | None:
    return None


def industry_stocks(name: str) -> list[dict] | None:
    return None


def concept_boards() -> list[dict] | None:
    return None


def concept_stocks(name: str) -> list[dict] | None:
    return None


def all_stocks() -> list[dict] | None:
    return None


# ── iFinDPy 返回解析（不同版本结构不一，尽量兼容）─────────────────────────────

def _bd_rows(resp) -> list[dict]:
    """把 THS_BD 返回归一化为 [{thscode, name, values:[...]}]。"""
    if resp is None:
        return []
    # 新版常见：dict(errorcode, tables=[{thscode, table:{ind:[v]}}])
    if isinstance(resp, dict):
        if resp.get("errorcode") not in (0, None):
            return []
        tables = resp.get("tables") or resp.get("data") or []
        rows = []
        for t in tables:
            tbl = t.get("table") or {}
            # 每个指标一列，取首个值（快照）
            vals = [v[0] if isinstance(v, list) and v else v for v in tbl.values()]
            rows.append({"thscode": t.get("thscode"), "name": "", "values": vals})
        return rows
    # 旧版可能返回带 .data (DataFrame)
    data = getattr(resp, "data", None)
    if data is not None:
        try:
            import pandas as pd
            if isinstance(data, pd.DataFrame):
                rows = []
                for _, row in data.iterrows():
                    rows.append({
                        "thscode": row.get("thscode"),
                        "name": row.get("ths_stock_short_name_stock", ""),
                        "values": [row[c] for c in data.columns if c != "thscode"],
                    })
                return rows
        except Exception:
            pass
    return []


def _hq_series(resp) -> list[dict]:
    """把 THS_HQ 返回归一化为日 K 列表。"""
    if resp is None:
        return []
    data = resp.get("tables") if isinstance(resp, dict) else getattr(resp, "data", None)
    out: list[dict] = []
    try:
        if isinstance(resp, dict):
            tables = resp.get("tables") or []
            if not tables:
                return []
            t = tables[0]
            times = t.get("time") or t.get("times") or []
            tbl = t.get("table") or {}
            o = tbl.get("open", []); h = tbl.get("high", [])
            lo = tbl.get("low", []); c = tbl.get("close", []); v = tbl.get("volume", [])
            for i, dt in enumerate(times):
                out.append({
                    "datetime": str(dt),
                    "open": _f(o[i]), "high": _f(h[i]), "low": _f(lo[i]),
                    "close": _f(c[i]), "volume": _f(v[i]),
                })
        elif data is not None:
            import pandas as pd
            if isinstance(data, pd.DataFrame):
                for _, row in data.iterrows():
                    out.append({
                        "datetime": str(row.get("time") or row.get("date")),
                        "open": _f(row.get("open")), "high": _f(row.get("high")),
                        "low": _f(row.get("low")), "close": _f(row.get("close")),
                        "volume": _f(row.get("volume")),
                    })
    except Exception:
        return []
    return out


def _f(v):
    try:
        return float(v) if v not in (None, "", "--") else None
    except (TypeError, ValueError):
        return None
