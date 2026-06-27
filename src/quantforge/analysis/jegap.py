"""净利润断层（季报预增）选股分析。

一级板块「季报分析」/ 二级板块「净利润断层策略」的核心计算逻辑。纯规则、不走 AI。

策略来源（用户原文）：
  净利润断层 = ①净利润惊喜（业绩超预期）+ ②断层（业绩公告后首个交易日股价向上跳空）。
  · 股票池：**全市场**（已取消「消费/医药/电子/通信」四大行业限制；行业仅作展示标签）。
  · 选股：当季度「业绩预告 / 快报 / 财报」业绩超预期，且公布后一天高开 ≥3% 并收阳线。
  · 超预期难以爬取分析师一致预期，故用「净利润同比增长 > 20%」近似替代。

数据源：东方财富 datacenter（与 stock_analysis._fetch_financials 同host，本环境可用）：
  · 业绩报表 RPT_LICO_FN_CPD —— 全市场已披露财报，含公告日 NOTICE_DATE、净利同比 SJLTZ、行业 PUBLISHNAME。
  · 业绩预告 RPT_PUBLIC_OP_NEWPREDICT —— 含公告日、归母净利同比增幅区间/中值 INCREASE_JZ。

「断层」判定走本地日 K 缓存（市场 K 线预热器已灌库）：取公告日**之后首个交易日**，
判断其相对前一交易日收盘是否高开 ≥3% 且当日收阳线（收盘 > 开盘）。
"""

from __future__ import annotations

import datetime as _dt
from loguru import logger


# ── 阈值 ─────────────────────────────────────────────────────────────────────
GROWTH_MIN = 20.0      # 净利润同比增长下限(%)——「业绩超预期」的近似替代
GAP_MIN = 3.0          # 公告后首个交易日高开下限(%)
RECENT_DAYS = 120      # 断层日须落在近 N 个自然日内（覆盖当季披露窗，避免翻出陈旧断层）
_PAGE_SIZE = 500
_TIMEOUT = 12


# ── 行业映射：东财二级行业（申万口径）→ 消费 / 医药 / 电子 / 通信 ────────────────
# 用户股票池为「消费、医药、电子、通信」四大类。东财 PUBLISHNAME 为细分二级行业，
# 这里用显式白名单归类（比关键字匹配更稳，规避「Ⅱ」后缀与跨类误伤）。
SECTOR_INDUSTRIES: dict[str, set[str]] = {
    "电子": {
        "半导体", "光学光电子", "消费电子", "元件", "其他电子Ⅱ", "电子化学品Ⅱ",
    },
    "通信": {
        "通信设备", "通信服务",
    },
    "医药": {
        "化学制药", "医疗器械", "中药Ⅱ", "生物制品", "医疗服务", "医药商业",
        "动物保健Ⅱ", "医疗美容",
    },
    "消费": {
        # 食品饮料
        "白酒Ⅱ", "非白酒", "饮料乳品", "休闲食品", "食品加工", "调味发酵品Ⅱ", "农产品加工",
        # 家用电器
        "白色家电", "黑色家电", "小家电", "厨卫电器", "其他家电Ⅱ", "家电零部件Ⅱ",
        # 商贸零售
        "一般零售", "互联网电商", "贸易Ⅱ", "专业连锁Ⅱ", "旅游零售Ⅱ",
        # 纺织服饰
        "服装家纺", "纺织制造", "饰品",
        # 美容护理
        "化妆品", "个护用品",
        # 社会服务
        "旅游及景区", "酒店餐饮", "教育", "体育Ⅱ",
        # 农林牧渔
        "养殖业", "种植业", "饲料", "渔业", "林业Ⅱ", "农业综合Ⅱ",
        # 轻工消费品
        "家居用品", "文娱用品",
    },
}

# 反向索引：行业名 → 大类
_IND_TO_SECTOR: dict[str, str] = {
    ind: sector for sector, inds in SECTOR_INDUSTRIES.items() for ind in inds
}


def industry_to_sector(industry: str | None) -> str | None:
    """东财二级行业名 → 四大类（消费/医药/电子/通信），不属于则 None。"""
    if not industry:
        return None
    return _IND_TO_SECTOR.get(industry.strip())


# ── 报告期推算 ───────────────────────────────────────────────────────────────

def latest_report_period(today: _dt.date | None = None) -> str:
    """推算「上一季度」最近一个已过披露截止日的报告期，返回 ``YYYY-MM-DD``。

    披露截止：一季报 4/30、半年报 8/31、三季报 10/31、年报次年 4/30。
    取最近一个截止日已到的报告期（确保数据较完整）。
    """
    today = today or _dt.date.today()
    y = today.year
    # (报告期, 披露截止日)，按时间从新到旧
    periods = [
        (f"{y}-12-31", _dt.date(y + 1, 4, 30)),
        (f"{y}-09-30", _dt.date(y, 10, 31)),
        (f"{y}-06-30", _dt.date(y, 8, 31)),
        (f"{y}-03-31", _dt.date(y, 4, 30)),
        (f"{y - 1}-12-31", _dt.date(y, 4, 30)),
        (f"{y - 1}-09-30", _dt.date(y - 1, 10, 31)),
        (f"{y - 1}-06-30", _dt.date(y - 1, 8, 31)),
    ]
    for report_date, deadline in periods:
        if today >= deadline:
            return report_date
    return f"{y - 1}-12-31"


def _period_label(period: str) -> str:
    """``2026-03-31`` → ``2026年一季报`` 之类的中文标签。"""
    md = period[5:]
    name = {"03-31": "一季报", "06-30": "中报", "09-30": "三季报", "12-31": "年报"}.get(md, period)
    return f"{period[:4]}年{name}"


_QUARTER_SEQ = ["03-31", "06-30", "09-30", "12-31"]


def next_report_period(period: str) -> str:
    """报告期 → 下一个季度报告期（年报后进入次年一季报）。"""
    y = int(period[:4])
    md = period[5:]
    if md not in _QUARTER_SEQ:
        return period
    i = _QUARTER_SEQ.index(md)
    if i == 3:
        return f"{y + 1}-03-31"
    return f"{y}-{_QUARTER_SEQ[i + 1]}"


def prev_report_period(period: str) -> str:
    """报告期 → 上一个季度报告期（一季报前为上年年报）。"""
    y = int(period[:4])
    md = period[5:]
    if md not in _QUARTER_SEQ:
        return period
    i = _QUARTER_SEQ.index(md)
    if i == 0:
        return f"{y - 1}-12-31"
    return f"{y}-{_QUARTER_SEQ[i - 1]}"


def current_report_period(today: _dt.date | None = None) -> str:
    """**本季度**报告期（用户口径）：最近一个已过披露截止日的报告期的**下一个季度**。

    例：6/26 已过 Q1(4/30) 截止日 → 本季度 = Q2(06-30)；公司多以业绩预告/快报先行披露，
    净利润断层与季报预增都以此「正在披露/预告」的当季为目标，未披露的标的自然为空。
    """
    return next_report_period(latest_report_period(today))


# ── 数据抓取（东财 datacenter） ─────────────────────────────────────────────────

def _fetch_pages(report_name: str, period: str, columns: str, sort_col: str,
                 source: str = "DataCenter", max_pages: int = 20) -> list[dict]:
    """分页拉取一个 datacenter 榜单的全部行（按报告期过滤）。"""
    import requests

    import time

    rows: list[dict] = []
    headers = {"User-Agent": "Mozilla/5.0",
               "Referer": "https://data.eastmoney.com/"}
    flt = (f"(REPORTDATE='{period}')" if report_name == "RPT_LICO_FN_CPD"
           else f"(REPORT_DATE='{period}')")
    total_pages = max_pages
    page = 1
    while page <= total_pages and page <= max_pages:
        result = None
        # 单页最多重试 2 次（东财间歇限流，直接 break 会静默截断、漏掉后续页）
        for attempt in range(3):
            try:
                r = requests.get(
                    "https://datacenter-web.eastmoney.com/api/data/v1/get",
                    params={
                        "reportName": report_name, "columns": columns,
                        "sortColumns": sort_col, "sortTypes": "-1",
                        "pageSize": str(_PAGE_SIZE), "pageNumber": str(page),
                        "source": source, "client": "WEB", "filter": flt,
                    },
                    headers=headers, timeout=_TIMEOUT,
                )
                result = (r.json() or {}).get("result") or {}
                break
            except Exception as e:
                logger.warning(
                    f"jegap: datacenter {report_name} page {page} try{attempt + 1} failed: {e}")
                time.sleep(0.6)
        if result is None:
            break
        data = result.get("data") or []
        if not data:
            break
        rows.extend(data)
        total_pages = result.get("pages") or 1
        page += 1
    return rows


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    except Exception:
        return None


def fetch_reports(period: str) -> list[dict]:
    """业绩报表（已披露财报）→ 预增公告清单。

    每项：``{code, name, industry, sector, growth, notice_date, source, period_label}``。
    仅保留四大行业、净利同比 > GROWTH_MIN、非 ST/退市的个股。
    """
    raw = _fetch_pages(
        "RPT_LICO_FN_CPD", period,
        "SECURITY_CODE,SECURITY_NAME_ABBR,NOTICE_DATE,SJLTZ,YSTZ,PARENT_NETPROFIT,PUBLISHNAME",
        "NOTICE_DATE",
    )
    label = _period_label(period)
    out: list[dict] = []
    for row in raw:
        code = (row.get("SECURITY_CODE") or "").strip()
        name = (row.get("SECURITY_NAME_ABBR") or "").strip()
        if not code or "ST" in name.upper() or "退" in name:
            continue
        # 取消「消费/医药/电子/通信」四大行业限制：全市场扫描。四大类仍归大类标签，
        # 其余行业用申万二级行业名兜底作 sector 标签（仅供展示/分组）。
        ind = (row.get("PUBLISHNAME") or "").strip()
        sector = industry_to_sector(ind) or ind
        growth = _safe_float(row.get("SJLTZ"))
        if growth is None or growth <= GROWTH_MIN:
            continue
        notice = str(row.get("NOTICE_DATE") or "")[:10]
        if not notice:
            continue
        out.append({
            "code": code, "name": name,
            "industry": ind, "sector": sector,
            "growth": round(growth, 1), "notice_date": notice,
            "rev_yoy": _safe_float(row.get("YSTZ")),
            "netprofit": _safe_float(row.get("PARENT_NETPROFIT")),  # 累计归母净利(算环比用)
            "source": "财报", "period_label": label,
        })
    return out


def fetch_netprofit_map(period: str) -> dict[str, float]:
    """某报告期全市场「累计归母净利润」映射 {code: 累计净利}（用于单季环比计算）。"""
    raw = _fetch_pages(
        "RPT_LICO_FN_CPD", period,
        "SECURITY_CODE,PARENT_NETPROFIT", "NOTICE_DATE",
    )
    out: dict[str, float] = {}
    for row in raw:
        code = (row.get("SECURITY_CODE") or "").strip()
        v = _safe_float(row.get("PARENT_NETPROFIT"))
        if code and v is not None:
            out[code] = v
    return out


def compute_qoq_map(period: str) -> dict[str, dict]:
    """全市场**单季归母净利润环比**映射 {code: {qoq, note, cur_single}}。

    单季净利 = 当期累计 − 上一期累计（一季报单季=累计）。环比 = 当季单季 / 上一季单季 − 1。
    需要当期/上一期(/上上期)的累计财报数据，未披露则跳过；一季报因需上年Q4单季、数据多缺，返回空。
    """
    md = period[5:]
    if md not in _QUARTER_SEQ or md == "03-31":
        return {}
    p1 = period
    p2 = prev_report_period(p1)            # 上一报告期
    cum1 = fetch_netprofit_map(p1)
    cum2 = fetch_netprofit_map(p2)
    cum3: dict[str, float] = {}
    if md in ("09-30", "12-31"):
        cum3 = fetch_netprofit_map(prev_report_period(p2))  # 上上报告期(算上一季单季)

    out: dict[str, dict] = {}
    for code, c1 in cum1.items():
        c2 = cum2.get(code)
        if c2 is None:
            continue
        cur_single = c1 - c2               # 当季单季净利
        if md == "06-30":
            prev_single = c2               # 一季单季 = 一季累计
        else:
            c3 = cum3.get(code)
            if c3 is None:
                continue
            prev_single = c2 - c3
        if prev_single > 0:
            qoq = round((cur_single / prev_single - 1.0) * 100.0, 1)
            note = None
        elif prev_single <= 0 < cur_single:
            qoq = None
            note = "环比扭亏"
        else:
            continue                       # 上一季亏、本季也亏，环比无意义
        out[code] = {"qoq": qoq, "note": note, "cur_single": round(cur_single, 0)}
    return out


def fetch_forecasts(period: str) -> list[dict]:
    """业绩预告 → 预增公告清单（归母净利同比增幅中值 > GROWTH_MIN）。"""
    raw = _fetch_pages(
        "RPT_PUBLIC_OP_NEWPREDICT", period,
        "SECURITY_CODE,SECURITY_NAME_ABBR,NOTICE_DATE,PREDICT_FINANCE_CODE,"
        "ADD_AMP_LOWER,ADD_AMP_UPPER,INCREASE_JZ,PREDICT_TYPE,FORECAST_STATE",
        "NOTICE_DATE",
    )
    label = _period_label(period)
    out: list[dict] = []
    for row in raw:
        # 只看归母净利润口径（004）
        if (row.get("PREDICT_FINANCE_CODE") or "") != "004":
            continue
        code = (row.get("SECURITY_CODE") or "").strip()
        name = (row.get("SECURITY_NAME_ABBR") or "").strip()
        if not code or "ST" in name.upper() or "退" in name:
            continue
        # 预告无行业字段，行业归类在合并阶段用财报/快照补；先收下，sector 暂空
        growth = _safe_float(row.get("INCREASE_JZ"))
        if growth is None:
            lo = _safe_float(row.get("ADD_AMP_LOWER"))
            hi = _safe_float(row.get("ADD_AMP_UPPER"))
            if lo is not None and hi is not None:
                growth = (lo + hi) / 2.0
        if growth is None or growth <= GROWTH_MIN:
            continue
        notice = str(row.get("NOTICE_DATE") or "")[:10]
        if not notice:
            continue
        out.append({
            "code": code, "name": name,
            "industry": None, "sector": None,
            "growth": round(growth, 1), "notice_date": notice,
            "predict_type": row.get("PREDICT_TYPE"),
            "source": "预告", "period_label": label,
        })
    return out


# ── 断层检测 ─────────────────────────────────────────────────────────────────

def detect_gap(bars: list[dict], notice_date: str,
               gap_min: float = GAP_MIN) -> dict | None:
    """公告日后首个交易日是否「高开 ≥gap_min% 且收阳线」。

    ``bars`` 为升序日 K（``{date, open, high, low, close, volume}``，date='YYYY-MM-DD'）。
    取**严格晚于** notice_date 的首个交易日作为反应日（业绩多于盘后/非交易时段披露，
    市场在次个交易日反应），相对其前一交易日收盘计算跳空。命中返回断层元数据，否则 None。
    """
    if not bars or len(bars) < 2:
        return None
    # 定位反应日：第一根 date > notice 的 K 线（须有前一根作为前收）
    idx = None
    for i in range(1, len(bars)):
        if str(bars[i].get("date") or "") > notice_date:
            idx = i
            break
    if idx is None:
        return None
    b = bars[idx]
    prev = bars[idx - 1]
    o = _safe_float(b.get("open"))
    h = _safe_float(b.get("high"))
    lo = _safe_float(b.get("low"))
    cl = _safe_float(b.get("close"))
    pc = _safe_float(prev.get("close"))
    if None in (o, h, lo, cl, pc) or pc <= 0:
        return None
    gap_open_pct = (o / pc - 1.0) * 100.0
    if gap_open_pct < gap_min:
        return None          # 高开不足
    if cl <= o:
        return None          # 非阳线（收盘未站上开盘）
    return {
        "gap_date": str(b.get("date")),
        "prev_close": round(pc, 2),
        "gap_open": round(o, 2),
        "gap_open_pct": round(gap_open_pct, 2),     # 高开幅度
        "gap_close": round(cl, 2),
        "gap_day_chg": round((cl / pc - 1.0) * 100.0, 2),   # 断层日全天涨幅
        "body_pct": round((cl / o - 1.0) * 100.0, 2),       # 阳线实体幅度
        "gap_high": round(h, 2),
        "gap_low": round(lo, 2),     # 缺口下沿附近——支撑/止损参考
    }
