"""
研报 API (基于 a-stock-data 3.1)
- 东财 reportapi: 研报列表 + PDF下载
- 同花顺一致预期EPS
- 概念板块/产业链数据
- AI分析任务接口
"""

from __future__ import annotations

import asyncio
import json
import time
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks
from loguru import logger
import pandas as pd
import requests

router = APIRouter(prefix="/research", tags=["research"])

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"

# AI分析任务缓存和状态
_TASKS_DIR = Path("data/cache/industry_tasks")
_RUNNING_TASKS = {}  # topic -> {"status": "running|done|error", "result": dict, "updated_at": str}

# 预定义的热门概念/产业链
_PRESET_TOPICS = {
    "humanoid_robot": {
        "name": "人形机器人",
        "concepts": ["机器人", "工业4.0", "减速器", "伺服系统"],
        "default_stocks": ["300024", "300008", "002008", "002176", "603666"],
        "tabs": ["overview", "cost", "reducer", "ballscrew", "motor", "sensor", "material", "risk", "valuation"]
    },
    "solid_state_battery": {
        "name": "固态电池",
        "concepts": ["固态电池", "锂电池", "储能"],
        "default_stocks": ["002812", "300750", "600030", "002460"],
        "tabs": ["overview", "cost", "material", "electrolyte", "cathode", "anode", "risk", "valuation"]
    },
    "ai_chip": {
        "name": "AI芯片",
        "concepts": ["AI芯片", "芯片设计", "算力", "GPU"],
        "default_stocks": ["600584", "002230", "300661", "002049"],
        "tabs": ["overview", "cost", "design", "manufacturing", "packaging", "material", "risk", "valuation"]
    },
    "auto_intelligence": {
        "name": "智能驾驶",
        "concepts": ["智能驾驶", "自动驾驶", "新能源车"],
        "default_stocks": ["002594", "300750", "601012", "002230"],
        "tabs": ["overview", "cost", "sensing", "decision", "actuation", "material", "risk", "valuation"]
    },
    "custom": {
        "name": "自定义主题",
        "concepts": [],
        "default_stocks": [],
        "tabs": ["overview", "cost", "risk", "valuation"]
    }
}

# ── 东财数据中心通用查询 ──
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def _eastmoney_datacenter(report_name: str, columns: str = "ALL",
                          filter_str: str = "", page_size: int = 50,
                          sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    """东财数据中心统一查询 — 龙虎榜/解禁/融资融券/大宗交易/股东户数/分红 共用"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    try:
        r = requests.get(DATACENTER_URL, params=params, headers={"User-Agent": UA}, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
    except Exception:
        pass
    return []

# ── 研报查询 ──
def _eastmoney_reports(code: str, max_pages: int = 10, page_size: int = 100, 
                        begin_time: str = None, end_time: str = None) -> list[dict]:
    """拉取指定股票的研报列表
    
    Args:
        code: 股票代码
        max_pages: 最大页数
        page_size: 每页数量
        begin_time: 开始时间 YYYY-MM-DD，默认1年前
        end_time: 结束时间 YYYY-MM-DD，默认今天
    """
    if not begin_time:
        # 默认1年前
        from datetime import timedelta
        begin_time = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    if not end_time:
        end_time = "2030-01-01"
        
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    all_records = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": str(page_size), "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin_time, "endTime": end_time,
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        try:
            r = session.get(REPORT_API, params=params, timeout=30)
            d = r.json()
            rows = d.get("data") or []
            if not rows:
                break
            all_records.extend(rows)
            if page >= (d.get("TotalPage", 1) or 1):
                break
            time.sleep(0.1)  # 减少延迟
        except Exception as e:
            print(f"第 {page} 页获取失败: {e}")
            break
    return all_records

@router.get("/reports/{code}")
async def get_reports(code: str, max_pages: int = 10, page_size: int = 100):
    """获取股票研报列表（默认最近1年）"""
    def fetch():
        return _eastmoney_reports(code, max_pages, page_size)
    reports = await asyncio.to_thread(fetch)
    return {"code": code, "count": len(reports), "reports": reports}

@router.get("/pdf/{info_code}")
async def get_pdf_url(info_code: str):
    """获取研报PDF下载地址"""
    return {"info_code": info_code, "pdf_url": PDF_TPL.format(info_code=info_code)}

# ── 同花顺一致预期EPS ──
def _ths_consensus_eps(code: str) -> list[dict]:
    """同花顺一致预期EPS — 直连 basic.10jqka.com.cn"""
    url = f"https://basic.10jqka.com.cn/{code}/gsyj.html"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.select("table tbody tr")
        result = []
        for tr in rows:
            tds = tr.select("td")
            if len(tds) >= 4:
                result.append({
                    "year": tds[0].text.strip(),
                    "eps": tds[1].text.strip(),
                    "institution_count": tds[2].text.strip(),
                    "rating": tds[3].text.strip(),
                })
        return result
    except Exception:
        return []

@router.get("/consensus/{code}")
async def get_consensus(code: str):
    """获取机构一致预期EPS"""
    def fetch():
        return _ths_consensus_eps(code)
    data = await asyncio.to_thread(fetch)
    return {"code": code, "consensus": data}

# ── 个股估值 ──
@router.get("/valuation/{code}")
async def get_valuation(code: str):
    """个股估值综合报告 — PE/PB/PEG/PE消化"""
    from quantforge.data.feed.mootdx_feed import _tencent_quote, _normalize_code
    code_norm = _normalize_code(code)
    
    q = await asyncio.to_thread(_tencent_quote, [code_norm])
    quote = q.get(code_norm, {})
    
    reports = await asyncio.to_thread(_eastmoney_reports, code_norm, 2)
    
    eps_next = None
    eps_this = None
    for r in reports[:10]:
        if r.get("predictNextYearEps"):
            eps_next = float(r.get("predictNextYearEps"))
        if r.get("predictThisYearEps"):
            eps_this = float(r.get("predictThisYearEps"))
        if eps_next and eps_this:
            break
    
    price = quote.get("price", 0)
    pe_ttm = quote.get("pe_ttm", 0)
    
    peg = None
    pe_digest = None
    if eps_next and eps_this and eps_this > 0:
        growth = (eps_next - eps_this) / eps_this * 100
        if growth > 0:
            peg = pe_ttm / growth if growth != 0 else None
            pe_digest = f"{round(peg, 1)}年" if peg else None
    
    return {
        "code": code,
        "name": quote.get("name", ""),
        "price": price,
        "pe_ttm": pe_ttm,
        "pe_static": quote.get("pe_static", 0),
        "pb": quote.get("pb", 0),
        "mcap_yi": quote.get("mcap_yi", 0),
        "float_mcap_yi": quote.get("float_mcap_yi", 0),
        "limit_up": quote.get("limit_up", 0),
        "limit_down": quote.get("limit_down", 0),
        "consensus_eps_this": eps_this,
        "consensus_eps_next": eps_next,
        "peg": peg,
        "pe_digest_years": pe_digest,
    }

# ── 概念板块相关 API ──
def _get_concept_stocks(concept_name: str) -> list[dict]:
    """根据概念名称获取成分股 (使用百度股市通或同花顺)"""
    try:
        # 简单实现：先尝试获取百度概念
        search_url = f"https://finance.pae.baidu.com/api/getrelatedstock?code=&market=ab&newFormat=1&finClientType=pc&query={concept_name}"
        headers = {"User-Agent": UA, "Origin": "https://gushitong.baidu.com", "Referer": "https://gushitong.baidu.com/"}
        r = requests.get(search_url, headers=headers, timeout=10)
        data = r.json()
        if data.get("Result") and data["Result"].get("list"):
            return [{"code": s["code"], "name": s["name"]} for s in data["Result"]["list"][:30]]
    except Exception as e:
        logger.warning(f"Failed to fetch concept {concept_name}: {e}")
    return []

@router.get("/topics")
def get_preset_topics():
    """获取预定义的主题/产业链列表"""
    return {
        "topics": [
            {"id": k, "name": v["name"], "concepts": v["concepts"]}
            for k, v in _PRESET_TOPICS.items()
        ]
    }

@router.get("/topic/{topic_id}")
def get_topic_detail(topic_id: str):
    """获取特定主题的详细信息"""
    topic = _PRESET_TOPICS.get(topic_id) or _PRESET_TOPICS.get("custom")
    return {
        "id": topic_id,
        "name": topic["name"],
        "concepts": topic["concepts"],
        "default_stocks": topic["default_stocks"],
        "tabs": topic.get("tabs", ["overview", "cost", "risk", "valuation"])
    }

@router.get("/concept/{concept_name}")
async def get_concept_stocks(concept_name: str):
    """获取概念板块的成分股列表"""
    def fetch():
        return _get_concept_stocks(concept_name)
    stocks = await asyncio.to_thread(fetch)
    return {"concept": concept_name, "count": len(stocks), "stocks": stocks}


# ── AI智能选股功能 ───────────────────────────────────────────────────────────
async def _ai_suggest_stocks(topic: str, sector: str = None, limit: int = 20) -> list[dict]:
    """使用AI分析推荐产业链相关股票
    
    Args:
        topic: 主题/产业链名称
        sector: 行业板块名称（可选）
        limit: 返回数量限制
    """
    try:
        # 1. 先从板块获取成分股
        sector_stocks = []
        if sector:
            try:
                import akshare as ak
                df = await asyncio.to_thread(ak.stock_board_industry_cons_em, sector)
                for _, row in df.iterrows():
                    try:
                        sector_stocks.append({
                            "code": str(row.iloc[1]),
                            "name": str(row.iloc[2]),
                            "price": float(row.iloc[3]) if pd.notna(row.iloc[3]) else None,
                            "change_pct": float(row.iloc[5]) if pd.notna(row.iloc[5]) else None,
                            "pe": float(row.iloc[14]) if len(row) > 14 and pd.notna(row.iloc[14]) else None,
                            "turnover_rate": float(row.iloc[13]) if len(row) > 13 and pd.notna(row.iloc[13]) else None,
                        })
                    except:
                        continue
                logger.info(f"Got {len(sector_stocks)} stocks from sector {sector}")
            except Exception as e:
                logger.warning(f"Failed to get sector stocks: {e}")
        
        # 2. 获取概念相关股票
        concept_stocks = await asyncio.to_thread(_get_concept_stocks, topic)
        
        # 3. 合并去重
        all_stocks_map = {}
        for s in concept_stocks:
            all_stocks_map[s["code"]] = s
        for s in sector_stocks:
            if s["code"] not in all_stocks_map:
                all_stocks_map[s["code"]] = s
        
        all_stocks = list(all_stocks_map.values())[:100]  # 最多100个用于AI分析
        
        if not all_stocks:
            return []
        
        # 4. 使用AI分析推荐最佳股票
        from quantforge.api.ai_client import chat
        
        stock_list_text = "\n".join([
            f"{s['code']} {s['name']} 现价:{s.get('price', 'N/A')} PE:{s.get('pe', 'N/A')} 换手:{s.get('turnover_rate', 'N/A')}%"
            for s in all_stocks[:50]
        ])
        
        prompt = f"""你是一位专业的股票分析师。请从以下{topic}产业链相关的股票中，筛选出最值得研究的股票。

股票列表：
{stock_list_text}

请分析并推荐不超过{limit}只最值得关注的股票，考虑因素：
1. 行业地位和市场份额
2. 估值合理性（PE、换手率）
3. 近期价格走势
4. 主营业务相关性

请以JSON格式返回：
{{
  "recommended": [
    {{"code": "股票代码", "name": "股票名称", "reason": "推荐理由", "priority": 1-5}},
    ...
  ],
  "summary": "整体分析总结（100字以内）"
}}

只返回JSON，不要其他文字。"""
        
        try:
            result_text = await chat(
                system="你是一位专业的股票分析师，擅长产业链研究和投资分析。",
                user=prompt,
                max_tokens=4096,
                caller="stock_suggestion"
            )
            
            # 解析JSON结果
            text = result_text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            if text.endswith("```"):
                text = text[:text.rfind("```")].strip()
            
            result = json.loads(text)
            recommended_codes = [s["code"] for s in result.get("recommended", [])]
            
            # 返回推荐的股票详细信息
            recommended_stocks = []
            for code in recommended_codes[:limit]:
                stock_info = all_stocks_map.get(code)
                if stock_info:
                    recommended_stocks.append(stock_info)
            
            return {
                "topic": topic,
                "sector": sector,
                "recommended": recommended_stocks,
                "all_count": len(all_stocks),
                "summary": result.get("summary", ""),
            }
        except Exception as e:
            logger.warning(f"AI analysis failed: {e}")
            # 如果AI失败，返回按换手率排序的股票
            sorted_stocks = sorted(
                [s for s in all_stocks if s.get("turnover_rate")],
                key=lambda x: x.get("turnover_rate", 0),
                reverse=True
            )[:limit]
            return {
                "topic": topic,
                "sector": sector,
                "recommended": sorted_stocks,
                "all_count": len(all_stocks),
                "summary": "按换手率排序推荐",
            }
            
    except Exception as e:
        logger.error(f"AI suggest stocks failed: {e}")
        return {"error": str(e), "recommended": [], "all_count": 0}


@router.get("/ai-suggest-stocks")
async def suggest_stocks(topic: str, sector: str = None, limit: int = 20):
    """AI智能推荐产业链相关股票
    
    Args:
        topic: 主题/产业链名称（如"人形机器人"、"固态电池"等）
        sector: 行业板块名称（可选，如"自动化设备"）
        limit: 返回数量限制（默认20）
    """
    result = await _ai_suggest_stocks(topic, sector, limit)
    return result


@router.get("/sectors")
async def get_all_sectors():
    """获取所有行业板块列表（用于选择）"""
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_industry_name_em)
        sectors = []
        for _, row in df.iterrows():
            try:
                sectors.append({
                    "name": str(row.iloc[1]),
                    "code": str(row.iloc[2]),
                    "change_pct": float(row.iloc[5]) if pd.notna(row.iloc[5]) else None,
                    "up_count": int(row.iloc[8]) if pd.notna(row.iloc[8]) else 0,
                    "down_count": int(row.iloc[9]) if pd.notna(row.iloc[9]) else 0,
                })
            except:
                continue
        # 按涨跌幅排序
        sectors.sort(key=lambda x: x.get("change_pct") or 0, reverse=True)
        return {"sectors": sectors, "count": len(sectors)}
    except Exception as e:
        logger.error(f"Get sectors failed: {e}")
        return {"sectors": [], "count": 0, "error": str(e)}


@router.get("/sector-stocks/{sector_name}")
async def get_sector_stocks(sector_name: str):
    """获取指定行业板块的成分股
    
    Args:
        sector_name: 板块名称（如"自动化设备"）
    """
    try:
        import akshare as ak
        df = await asyncio.to_thread(ak.stock_board_industry_cons_em, sector_name)
        stocks = _normalise_cons_stocks(df)
        return {"sector": sector_name, "stocks": stocks, "count": len(stocks)}
    except Exception as e:
        logger.error(f"Get sector stocks failed: {e}")
        return {"sector": sector_name, "stocks": [], "count": 0, "error": str(e)}


def _normalise_cons_stocks(df: pd.DataFrame) -> list[dict]:
    """标准化成分股数据"""
    import math
    result = []
    for _, row in df.iterrows():
        try:
            result.append({
                "code": str(row.iloc[1]),
                "name": str(row.iloc[2]),
                "price": float(row.iloc[3]) if pd.notna(row.iloc[3]) else None,
                "change_pct": float(row.iloc[5]) if pd.notna(row.iloc[5]) else None,
                "volume": float(row.iloc[6]) if pd.notna(row.iloc[6]) else None,
                "turnover": float(row.iloc[7]) if pd.notna(row.iloc[7]) else None,
                "high": float(row.iloc[9]) if pd.notna(row.iloc[9]) else None,
                "low": float(row.iloc[10]) if pd.notna(row.iloc[10]) else None,
                "turnover_rate": float(row.iloc[13]) if len(row) > 13 and pd.notna(row.iloc[13]) else None,
                "pe": float(row.iloc[14]) if len(row) > 14 and pd.notna(row.iloc[14]) else None,
                "pb": float(row.iloc[15]) if len(row) > 15 and pd.notna(row.iloc[15]) else None,
            })
        except:
            continue
    return result

@router.get("/stocks/quotes")
async def get_stock_quotes(codes: str):
    """批量获取股票实时报价"""
    from quantforge.data.feed.mootdx_feed import _tencent_quote, _normalize_code
    code_list = [_normalize_code(c.strip()) for c in codes.split(",") if c.strip()]
    quotes = await asyncio.to_thread(_tencent_quote, code_list)
    return {"count": len(quotes), "quotes": quotes}

# ── AI分析任务系统 ──
def _task_path(topic: str) -> Path:
    return _TASKS_DIR / f"{topic}.json"

def _load_task(topic: str) -> dict | None:
    path = _task_path(topic)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None

def _save_task(topic: str, data: dict):
    try:
        _TASKS_DIR.mkdir(parents=True, exist_ok=True)
        _task_path(topic).write_text(
            json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"Task save failed for {topic}: {e}")

_INDUSTRY_ANALYSIS_PROMPT = """你是一位专业的产业链研究分析师，负责撰写深度行业研报。
请针对给定的产业链/概念主题进行深度分析。

分析要求：
1. 分析产业链上下游构成，识别关键环节
2. 分析当前行业发展阶段和未来趋势
3. 识别核心受益标的及投资逻辑
4. 提示投资风险和注意事项
5. 估算BOM成本构成

输入数据包括：
- 主题/概念名称
- 核心标的列表及其基本资料
- 相关机构研报摘要

请返回 JSON 格式分析报告，不要其他文字：
{
  "overview": "产业链整体分析（300字）",
  "market_size": "当前市场规模和增长预估",
  "key_players": ["核心标的1", "核心标的2"],
  "key_segments": [
    {
      "name": "环节名称",
      "importance": "高|中|低",
      "leader": "龙头公司",
      "description": "环节说明"
    }
  ],
  "bom": [
    {"name": "部件名称1", "percent": 35, "color": "#6366f1"},
    {"name": "部件名称2", "percent": 25, "color": "#3b82f6"},
    {"name": "部件名称3", "percent": 20, "color": "#06d6c8"},
    {"name": "部件名称4", "percent": 12, "color": "#f59e0b"},
    {"name": "其他", "percent": 8, "color": "#22d97a"}
  ],
  "risks": ["风险1", "风险2"],
  "summary": "投资建议（200字）"
}
"""

async def _run_industry_analysis(topic_id: str, custom_stocks: str = ""):
    """在后台执行产业链分析"""
    topic = _PRESET_TOPICS.get(topic_id) or _PRESET_TOPICS["custom"]
    
    # 1. 先通过主题名称搜索相关概念股票
    search_query = topic["name"]
    logger.info(f"Searching concept stocks for: {search_query}")
    
    concept_stocks = await asyncio.to_thread(_get_concept_stocks, search_query)
    logger.info(f"Found {len(concept_stocks)} concept stocks for {search_query}")
    
    # 2. 使用用户自定义股票，或者搜索到的股票，或者默认股票
    stock_codes = [s.strip() for s in custom_stocks.split(",") if s.strip()]
    if not stock_codes:
        if concept_stocks:
            stock_codes = [s["code"] for s in concept_stocks]  # 使用搜索到的股票
            logger.info(f"Using {len(stock_codes)} searched concept stocks")
        else:
            stock_codes = topic.get("default_stocks", [])
            logger.info(f"Using {len(stock_codes)} default stocks")
    
    # 3. 收集行情数据
    from quantforge.data.feed.mootdx_feed import _tencent_quote, _normalize_code
    quotes = {}
    if stock_codes:
        codes_normalized = [_normalize_code(c) for c in stock_codes]
        quotes = await asyncio.to_thread(_tencent_quote, codes_normalized)
        logger.info(f"Got quotes for {len(quotes)} stocks")
    
    # 4. 收集研报（获取所有搜索到的股票的研报）
    reports_agg = []
    for code in stock_codes:
        try:
            reps = await asyncio.to_thread(_eastmoney_reports, code, max_pages=5, page_size=100)
            if reps:
                reports_agg.extend(reps)
                logger.info(f"Got {len(reps)} reports for {code}")
        except Exception as e:
            logger.warning(f"Failed to get reports for {code}: {e}")
    
    logger.info(f"Total reports collected: {len(reports_agg)}")
    
    # 构建提示词
    from quantforge.api.ai_client import chat
    user_parts = [
        f"分析主题：{topic['name']}",
        "核心标的（含行情数据）："
    ]
    for code, q in quotes.items():
        user_parts.append(f"{code} {q.get('name','')} 价格{q.get('price',0)} PE={q.get('pe_ttm',0)} PB={q.get('pb',0)}")
    
    user_parts.append("相关研报：")
    for r in reports_agg[:20]:
        user_parts.append(f"[{r.get('orgSName','')}] {r.get('title','')}")
    
    try:
        ai_text = await chat(
            system=_INDUSTRY_ANALYSIS_PROMPT,
            user="\n".join(user_parts),
            max_tokens=8192,
            caller="industry_research"
        )
        # 解析JSON
        text = ai_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        if text.endswith("```"):
            text = text[:text.rfind("```")].strip()
        
        result = json.loads(text)
    except Exception as e:
        result = {
            "error": str(e),
            "overview": f"{topic['name']}是当前市场热点板块",
            "key_players": stock_codes,
            "key_segments": [{"name": "全产业链", "importance": "高"}],
            "risks": ["市场波动风险"],
            "summary": "建议关注龙头公司"
        }
    
    # 保存结果
    task_result = {
        "topic": topic_id,
        "topic_name": topic["name"],
        "status": "done",
        "result": result,
        "quotes": quotes,
        "reports": reports_agg,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    _save_task(topic_id, task_result)
    _RUNNING_TASKS[topic_id] = task_result
    logger.info(f"Industry analysis complete for {topic_id}")

@router.post("/analyze")
async def start_analysis(topic_id: str, background_tasks: BackgroundTasks, custom_stocks: str = "", refresh: bool = True):
    """启动产业链AI分析"""
    if topic_id in _RUNNING_TASKS and _RUNNING_TASKS[topic_id].get("status") == "running":
        return {"status": "already_running", "message": "该主题分析正在进行中"}
    
    # 不再使用缓存，每次都重新生成
    task_record = {
        "status": "running",
        "topic": topic_id,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    _RUNNING_TASKS[topic_id] = task_record
    background_tasks.add_task(_run_industry_analysis, topic_id, custom_stocks)
    return {"status": "started", "message": "AI分析已在后台启动，约1分钟后刷新查看结果"}

@router.get("/analysis/{topic_id}")
async def get_analysis_result(topic_id: str):
    """获取分析结果"""
    running = _RUNNING_TASKS.get(topic_id)
    if running and running.get("status") == "running":
        return {"status": "running", "message": "分析正在进行中"}
    
    cached = _load_task(topic_id)
    if cached:
        return {"status": "done", "data": cached}
    
    return {"status": "not_found", "message": "未找到该主题分析，请先启动分析"}

@router.get("/analysis-status/{topic_id}")
async def get_analysis_status(topic_id: str):
    """获取分析状态"""
    running = _RUNNING_TASKS.get(topic_id)
    if running:
        return {
            "status": running.get("status"),
            "topic": topic_id,
            "updated_at": running.get("updated_at")
        }
    cached = _load_task(topic_id)
    if cached:
        return {
            "status": cached.get("status"),
            "topic": topic_id,
            "updated_at": cached.get("updated_at")
        }
    return {"status": "not_found"}
