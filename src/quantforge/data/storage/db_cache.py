"""Unified SQLite cache — single persistent store for all data modules.

Goals
=====
1. **One database file** (``data/cache.db``) replaces the scattered JSON files under
   ``data/cache/*``.  Every module (sector, market, news, ai_picks, stock_meta, …)
   writes into it via the same thin API.
2. **TTL-based freshness** — each entry carries a TTL in seconds.  ``get()``
   returns ``None`` when the entry is older than its TTL.  ``get_stale()`` is
   available as a graceful fallback when the live upstream source fails.
3. **Refresh-on-demand / overwrite** — ``set()`` always **replaces** (upserts)
   the previous row for the same key, so every new fetch overwrites the last.
   A companion ``POST /api/cache/refresh?key=…`` endpoint exposes this as an
   HTTP action so the frontend can trigger a forced refresh.
4. **Category index** — every entry is tagged with a ``category`` (``"sector"``,
   ``"market"``, ``"news"``, ``"ai_picks"``, ``"stock_meta"``, …).  This powers
   ``list_by_category()`` / ``delete_by_category()`` admin operations and lets
   the admin UI show how much data is cached per area.

Schema
======
``cache_entries`` table::

    key            TEXT PRIMARY KEY        -- unique lookup key, e.g. "sector:industry_boards"
    category       TEXT                    -- e.g. "sector", "market", "news", "ai_picks", "stock_meta"
    payload        TEXT                    -- JSON blob
    fetched_at     TEXT                    -- ISO-8601 timestamp, e.g. "2026-06-01T09:30:00.123456"
    ttl_seconds    INTEGER                 -- how long this entry is considered fresh

``stock_meta`` table (secondary, column-indexed so we can filter/search SQL-side)::

    code           TEXT PRIMARY KEY        -- 6-digit A-share code, e.g. "600519"
    name           TEXT                    -- 贵州茅台
    exchange       TEXT                    -- "SSE" / "SZSE"
    price          REAL
    change_pct     REAL
    change_val     REAL
    updated_at     TEXT                    -- ISO-8601

Additional per-module tables can be declared by calling ``ensure_schema()`` at
import time; the DDL is idempotent (``CREATE TABLE IF NOT EXISTS``).

Public API
==========
::

    # Core key/value cache
    get(key: str, ttl_seconds: int | None) -> dict | None
    get_stale(key: str) -> dict | None
    set(key: str, data: dict, ttl_seconds: int, category: str) -> None
    delete(key: str) -> None
    list_by_category(category: str) -> list[dict]  # [{key, fetched_at, size_b}]
    list_categories() -> list[dict]                # [{category, count, oldest, newest}]
    delete_by_category(category: str) -> int
    clear_all() -> None
    get_meta(ttl_seconds=43200) -> dict
    set_meta() -> dict                            # refreshes stock_meta from efinance
    get_stock(code) -> dict | None
    search_stocks(query, limit=50) -> list[dict]
    list_stocks(limit, sort_by, order, filter_type) -> list[dict]

Only the Python standard library (``sqlite3``) is required — no extra deps.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Paths & connection management
# ---------------------------------------------------------------------------

_DB_DIR = Path("data")
_DB_PATH = _DB_DIR / "cache.db"

# SQLite connections are *per-thread*; we share one ``Connection`` per thread
# through a simple lock-protected dict.  Using ``check_same_thread=False`` with
# a single write-lock is a common alternative, but thread-local keeps things
# trivially safe in a FastAPI / asyncio world (where each request runs in its
# own worker thread).
_local = threading.local()
# Reentrant on purpose: write helpers grab this lock and then call ``_conn()``,
# which on a thread's first DB op runs ``_ensure_schema()`` — and that ALSO grabs
# the lock. With a plain ``Lock`` that second acquisition self-deadlocks the
# thread (it holds the lock forever), freezing every other DB caller and, if it
# happens on the asyncio event-loop thread, the whole server. ``RLock`` lets the
# owning thread re-enter safely.
_write_lock = threading.RLock()


def _conn() -> sqlite3.Connection:
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is None:
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(_DB_PATH, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # Sensible pragmas for a small, frequently-written cache DB.
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _ensure_schema(conn)
        _local.conn = conn
    return conn


# ---------------------------------------------------------------------------
# Schema  (idempotent — safe to call repeatedly)
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    key         TEXT    PRIMARY KEY,
    category    TEXT    NOT NULL DEFAULT 'uncategorized',
    payload     TEXT    NOT NULL,
    fetched_at  TEXT    NOT NULL,
    ttl_seconds INTEGER NOT NULL DEFAULT 600
);
CREATE INDEX IF NOT EXISTS idx_cache_category ON cache_entries(category);
CREATE INDEX IF NOT EXISTS idx_cache_fetched  ON cache_entries(fetched_at);

CREATE TABLE IF NOT EXISTS stock_meta (
    code        TEXT PRIMARY KEY,
    name        TEXT,
    exchange    TEXT,
    price       REAL,
    change_pct  REAL,
    change_val  REAL,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_stock_meta_name     ON stock_meta(name);
CREATE INDEX IF NOT EXISTS idx_stock_meta_exchange ON stock_meta(exchange);

-- Whole-market realtime quote snapshot (one row per stock, current snapshot).
-- Refreshed by a background task; reads serve from here so display never blocks
-- on upstream APIs (<1s, network-independent / stale-but-instant).
CREATE TABLE IF NOT EXISTS stock_quote (
    code          TEXT PRIMARY KEY,
    name          TEXT,
    exchange      TEXT,
    price         REAL,
    change_pct    REAL,
    change        REAL,
    open          REAL,
    high          REAL,
    low           REAL,
    pre_close     REAL,
    volume        REAL,
    turnover      REAL,   -- 成交额 (元)
    turnover_rate REAL,   -- 换手率 (%)
    pe            REAL,
    pb            REAL,
    market_cap    REAL,
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_quote_change   ON stock_quote(change_pct);
CREATE INDEX IF NOT EXISTS idx_quote_turnover ON stock_quote(turnover);
CREATE INDEX IF NOT EXISTS idx_quote_price    ON stock_quote(price);
CREATE INDEX IF NOT EXISTS idx_quote_name     ON stock_quote(name);

-- Sector boards (one row per industry/concept board, current snapshot)
CREATE TABLE IF NOT EXISTS sector_boards (
    kind          TEXT NOT NULL,            -- 'industry' | 'concept'
    name          TEXT NOT NULL,
    node          TEXT,                      -- Sina node code (new_*/gn_*)
    change_pct    REAL,
    avg_pe        REAL,
    median_pe     REAL,
    avg_pb        REAL,
    pe_valid      INTEGER,
    turnover_rate REAL,
    market_cap    REAL,
    amount        REAL,
    up_count      INTEGER,
    down_count    INTEGER,
    total         INTEGER,
    leader        TEXT,
    leader_change REAL,
    index_value   REAL,                      -- 同花顺概念指数点位
    net_flow      REAL,                      -- 资金净流入(亿，概念用)
    updated_at    TEXT,
    PRIMARY KEY (kind, name)
);
CREATE INDEX IF NOT EXISTS idx_sector_boards_kind ON sector_boards(kind);

-- Sector constituents (one row per stock per board)
CREATE TABLE IF NOT EXISTS sector_constituents (
    kind          TEXT NOT NULL,
    board         TEXT NOT NULL,
    code          TEXT NOT NULL,
    name          TEXT,
    price         REAL,
    change_pct    REAL,
    turnover_rate REAL,
    turnover      REAL,                      -- 成交额 (元)
    pe            REAL,
    pb            REAL,
    market_cap    REAL,
    updated_at    TEXT,
    PRIMARY KEY (kind, board, code)
);
CREATE INDEX IF NOT EXISTS idx_sector_cons_board ON sector_constituents(kind, board);
CREATE INDEX IF NOT EXISTS idx_sector_cons_code  ON sector_constituents(code);

-- 板块拥挤度时序：每个板块每日一行快照，供「板块拥挤度」计算时序分位
-- (当前成交占比/换手 vs 自身历史)、N日动量、放量倍数。由 sector_summary_warmer
-- 每日追加(同日 upsert，保留当日最新一笔)。横截面分位无需历史即可算，历史
-- 攒够后自动叠加时序维度。
CREATE TABLE IF NOT EXISTS sector_metric_history (
    kind          TEXT NOT NULL,            -- 'industry' | 'concept'
    name          TEXT NOT NULL,
    date          TEXT NOT NULL,            -- 'YYYY-MM-DD'
    change_pct    REAL,
    turnover_rate REAL,
    amount        REAL,                      -- 板块成交额(元)
    market_cap    REAL,
    net_flow      REAL,
    amount_share  REAL,                      -- 板块成交额 / 当日全市场板块总成交额
    crowding      REAL,                      -- 当日合成拥挤度评分(0-100)，供趋势对比
    PRIMARY KEY (kind, name, date)
);
CREATE INDEX IF NOT EXISTS idx_sector_hist_kd ON sector_metric_history(kind, date);
CREATE INDEX IF NOT EXISTS idx_sector_hist_kn ON sector_metric_history(kind, name);

-- Per-account watchlist (durable user data, not wiped by cache clear)
CREATE TABLE IF NOT EXISTS watchlist (
    user_id    TEXT NOT NULL,
    code       TEXT NOT NULL,
    name       TEXT,
    notes      TEXT DEFAULT '',
    tags       TEXT DEFAULT '[]',     -- JSON array
    color      TEXT DEFAULT '',       -- 单只标色 (hex/'' 表示无)
    cost_price REAL,                  -- 持仓成本价 (NULL 表示未持仓)
    shares     REAL,                  -- 持仓股数
    added_at   TEXT,
    PRIMARY KEY (user_id, code)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);

-- Per-account watchlist verification snapshots
CREATE TABLE IF NOT EXISTS watchlist_verifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    period_days  INTEGER,
    start_date   TEXT,
    end_date     TEXT,
    total_return REAL,
    results      TEXT,                 -- JSON array
    created_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_wlverif_user ON watchlist_verifications(user_id);

-- 机构研报（东财 reportapi），一篇一行，本地缓存供展示/AI 精读复用
CREATE TABLE IF NOT EXISTS stock_reports (
    info_code     TEXT PRIMARY KEY,   -- 东财 infoCode（唯一）
    code          TEXT NOT NULL,      -- 6 位股票代码
    title         TEXT,
    org           TEXT,               -- 机构简称 (orgSName)
    rating        TEXT,               -- 评级 (emRatingName)
    rating_change TEXT,               -- 评级变动数值
    publish_date  TEXT,               -- YYYY-MM-DD
    target_price  REAL,               -- 目标价 (indvAimPriceT)
    eps_this      REAL,  pe_this   REAL,
    eps_next      REAL,  pe_next   REAL,
    eps_next2     REAL,  pe_next2  REAL,
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_code ON stock_reports(code);
CREATE INDEX IF NOT EXISTS idx_reports_date ON stock_reports(publish_date);

-- 行业/策略研报（东财 reportapi qType=1），一篇一行。个股研报有 stockCode 落
-- stock_reports；行业研报无个股归属，单独存这里，供产业链精读「优先读库」复用。
CREATE TABLE IF NOT EXISTS industry_reports (
    info_code      TEXT PRIMARY KEY,   -- 东财 infoCode（唯一）
    industry_code  TEXT,               -- 东财行业代码 (industryCode)
    industry_name  TEXT,               -- 行业名 (industryName)
    title          TEXT,
    org            TEXT,               -- 机构简称 (orgSName)
    rating         TEXT,
    publish_date   TEXT,               -- YYYY-MM-DD
    updated_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_indreports_date ON industry_reports(publish_date);
CREATE INDEX IF NOT EXISTS idx_indreports_indname ON industry_reports(industry_name);

-- 研报 PDF 库：下载并抽取正文后的持久化（DB 版，替代 data/cache/research_pdfs/_index.json）。
-- 产业链关键词分析每次「下载完研报」即落库于此，供「查看精读」与增量分析复用。
CREATE TABLE IF NOT EXISTS research_pdfs (
    info_code     TEXT PRIMARY KEY,   -- 东财 infoCode（唯一）
    code          TEXT,               -- 关联股票代码（行业研报可为空）
    title         TEXT,
    org           TEXT,
    publish_date  TEXT,               -- YYYY-MM-DD
    chars         INTEGER DEFAULT 0,  -- 抽取正文字数
    text          TEXT,               -- 抽取正文（截断）
    has_pdf       INTEGER DEFAULT 0,  -- 1=PDF 已成功下载
    downloaded_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_research_pdfs_code ON research_pdfs(code);
CREATE INDEX IF NOT EXISTS idx_research_pdfs_date ON research_pdfs(publish_date);

-- Durable app-wide key/value config (NOT wiped by cache clear_all()).
-- Used for things like the 知识星球 cookie & crawler settings.
CREATE TABLE IF NOT EXISTS app_config (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);

-- 知识星球(zsxq) 博客抓取库：一条主题(topic)一行，含正文 + 内联有道笔记内容。
CREATE TABLE IF NOT EXISTS blog_posts (
    post_id       TEXT PRIMARY KEY,   -- zsxq topic_id（唯一）
    group_id      TEXT,
    author        TEXT,
    title         TEXT,
    ai_title      TEXT,               -- AI 提炼的一句话标题（落库，不临时拉取）
    content_html  TEXT,               -- 渲染后的正文 HTML
    content_text  TEXT,               -- 纯文本（搜索/预览用）
    images        TEXT DEFAULT '[]',  -- JSON 数组：图片 URL
    youdao        TEXT DEFAULT '[]',  -- JSON 数组：{url,title,html,text,ok}
    created_at    TEXT,               -- zsxq create_time（ISO）
    fetched_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_blog_created ON blog_posts(created_at);
CREATE INDEX IF NOT EXISTS idx_blog_group   ON blog_posts(group_id);

-- Daily/weekly/monthly K-line bars (one row per code+period+date).
-- Historical bars never change → fetched incrementally (only the latest
-- session is re-pulled; older rows are kept forever).
CREATE TABLE IF NOT EXISTS stock_kline (
    code        TEXT NOT NULL,
    period      TEXT NOT NULL,          -- 'day' | 'week' | 'month'
    date        TEXT NOT NULL,          -- 'YYYY-MM-DD'
    open        REAL,
    close       REAL,
    high        REAL,
    low         REAL,
    volume      REAL,
    change_pct  REAL,
    PRIMARY KEY (code, period, date)
);
CREATE INDEX IF NOT EXISTS idx_kline_code_period ON stock_kline(code, period, date);

-- 用户活跃日志：每次带 token 的 API 请求经全局中间件打一条点。
-- 行级最细（user+path+方法+时间戳），上层 SQL 聚合出 DAU/功能热度/最近活跃。
-- 仅保留最近 N 天（默认 90），定期裁剪以约束体积。
CREATE TABLE IF NOT EXISTS activity_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  TEXT,                 -- users.json 里的 uuid（匿名/解析失败为空）
    username TEXT,                 -- 冗余存账号名，省去聚合时回查 users.json
    day      TEXT NOT NULL,        -- 'YYYY-MM-DD'（本地日），DAU/留存按此分组
    ts       TEXT NOT NULL,        -- ISO-8601 秒级时间戳
    feature  TEXT,                 -- 归一化后的功能名（自选/AI对话/个股分析/…）
    method   TEXT,                 -- HTTP 方法
    path     TEXT                  -- 原始请求路径（排查用）
);
CREATE INDEX IF NOT EXISTS idx_activity_day     ON activity_log(day);
CREATE INDEX IF NOT EXISTS idx_activity_user    ON activity_log(username);
CREATE INDEX IF NOT EXISTS idx_activity_feature ON activity_log(feature);

-- AI 聊股对话存档：每条消息一行（user / assistant）。后台据此回看用户对话。
-- session_id 来自前端会话（localStorage 里的稳定 id），同一会话的多轮消息共享，
-- 按 (user_id, session_id, seq) 还原顺序。title 冗余存会话标题，列表展示用。
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT,                 -- users.json 里的 uuid（匿名为空）
    username   TEXT,                 -- 冗余账号名，省去回查
    session_id TEXT NOT NULL,        -- 前端会话 id
    title      TEXT,                 -- 会话标题（冗余，取最近一次写入值）
    seq        INTEGER NOT NULL,     -- 同一会话内的递增序号
    role       TEXT NOT NULL,        -- 'user' | 'assistant'
    content    TEXT NOT NULL,
    ts         TEXT NOT NULL         -- ISO-8601 秒级时间戳
);
CREATE INDEX IF NOT EXISTS idx_chat_user    ON chat_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_us      ON chat_messages(user_id, session_id, seq);

-- AI 荐股预测记录（替代 data/cache/predictions.json）。一条荐股一行。
-- 结算字段由统一结算引擎 (prediction.tracker.settle) 路径扫描后写回；
-- verified=1 表示已「定格」（触发止盈/止损，或固定持仓窗口走完），不再变动；
-- verified=0 表示仍在持仓窗口内（进行中），每日调度会复算。
CREATE TABLE IF NOT EXISTS predictions (
    id                TEXT PRIMARY KEY,   -- "{date}_{code}"
    date              TEXT NOT NULL,      -- 预测日 = 买入日 (YYYY-MM-DD)
    code              TEXT NOT NULL,
    name              TEXT,
    predicted_at      TEXT,
    buy_price         REAL,               -- AI 建议买点（仅参考）
    stop_price        REAL,
    target_price      REAL,
    target_pct        REAL,
    stop_pct          REAL,
    confidence        REAL,
    risk_level        TEXT,
    strategy_name     TEXT,
    pick_strategy     TEXT DEFAULT 'momentum',  -- 哪种 AI 荐股策略产出(momentum|pring)
    hit_strategies    TEXT DEFAULT '[]',  -- JSON 数组
    verified          INTEGER DEFAULT 0,  -- 1=已定格
    entry_price       REAL,               -- 买入日开盘（结算基准）
    actual_close      REAL,               -- 结算价（触发价 / 窗口末收盘 / 现价）
    actual_change_pct REAL,               -- (actual_close-entry)/entry %
    outcome           TEXT,               -- hit_target|hit_stop|positive|negative|neutral|open
    trigger_date      TEXT,               -- 触发止盈/止损的交易日（未触发为空）
    hold_days         INTEGER,            -- 实际持仓交易日数
    bench_change_pct  REAL,               -- 同期沪深300涨跌（基准对比，可空）
    verified_at       TEXT,
    sector            TEXT,               -- 所属行业（来自 AI 荐股，行业维度统计用）
    window_return     REAL,               -- 反事实：硬扛到窗口末的收益%（不设止盈止损）
    mfe_pct           REAL,               -- 持仓窗口内最大有利波动(最高价 vs entry)%
    mae_pct           REAL,               -- 持仓窗口内最大不利波动(最低价 vs entry)%
    horizon_returns   TEXT DEFAULT '{}'   -- 各持仓窗口收益 JSON {"5":x,"10":y,"20":z,"60":w}
);
CREATE INDEX IF NOT EXISTS idx_predictions_date ON predictions(date);
CREATE INDEX IF NOT EXISTS idx_predictions_code ON predictions(code);

-- 研报 MAP 抽取结果全局缓存（按 infoCode 主键，跨主题/跨轮复用）。
-- 产业链研报「MAP 阶段」逐篇 LLM 抽取很耗 token；同一篇研报在不同主题/
-- 不同轮分析里会被重复抽取。这里按 infoCode 落最优一份：记录抽取模型、
-- 质量分级(model_tier)与 prompt 版本/正文 hash，做到「只升不降，保存最优」。
CREATE TABLE IF NOT EXISTS report_facts (
    info_code      TEXT PRIMARY KEY,   -- 东财 infoCode（唯一）
    fact_json      TEXT NOT NULL,      -- 抽取出的结构化事实 JSON
    model          TEXT,               -- 抽取所用模型名
    model_tier     INTEGER DEFAULT 0,  -- 模型质量分级（越大越好）
    prompt_version TEXT,               -- 抽取 prompt 版本
    text_hash      TEXT,               -- 研报正文 hash（正文变了需重抽）
    updated_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_report_facts_updated ON report_facts(updated_at);

-- 在线状态心跳：每个账号一行，前端每 30 s 发心跳更新 last_seen；
-- session_start 记录本次连续在线的起始时间，duration_secs 累计本次在线秒数。
-- gap > 90s 视为下线：下次心跳到来时重开新会话。
CREATE TABLE IF NOT EXISTS online_sessions (
    username       TEXT PRIMARY KEY,
    session_start  TEXT NOT NULL,   -- ISO-8601
    last_seen      TEXT NOT NULL,   -- ISO-8601
    duration_secs  INTEGER DEFAULT 0
);

-- 飞书群消息（OAuth user_access_token 拉取，按群增量存储）。
CREATE TABLE IF NOT EXISTS feishu_messages (
    message_id   TEXT PRIMARY KEY,
    chat_id      TEXT NOT NULL,
    chat_name    TEXT DEFAULT '',
    sender_id    TEXT DEFAULT '',
    sender_type  TEXT DEFAULT 'user',
    msg_type     TEXT DEFAULT 'text',
    content_text TEXT DEFAULT '',
    content_raw  TEXT DEFAULT '',
    created_at   TEXT DEFAULT '',   -- ISO-8601（由毫秒时间戳转换）
    fetched_at   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_feishu_msg_chat    ON feishu_messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_feishu_msg_created ON feishu_messages(created_at DESC);

-- 飞书群列表缓存（刷新时全量覆盖）。
CREATE TABLE IF NOT EXISTS feishu_chats (
    chat_id     TEXT PRIMARY KEY,
    name        TEXT DEFAULT '',
    description TEXT DEFAULT '',
    avatar      TEXT DEFAULT '',
    chat_type   TEXT DEFAULT '',
    updated_at  TEXT DEFAULT ''
);

-- 飞书四群每日汇总（昨天16:00→今天16:00 窗口，AI 总结，按 day 一份）。
CREATE TABLE IF NOT EXISTS feishu_daily_summary (
    day          TEXT PRIMARY KEY,   -- YYYY-MM-DD（窗口结束日）
    window_start TEXT DEFAULT '',    -- ISO-8601
    window_end   TEXT DEFAULT '',    -- ISO-8601
    summary      TEXT DEFAULT '',    -- AI 生成的 Markdown 汇总
    msg_count    INTEGER DEFAULT 0,
    generated_at TEXT DEFAULT ''     -- ISO-8601
);

-- 调度器 leader 锁：多 worker 部署下只让一个 worker 跑后台/定时任务，避免
-- 每日 LLM 重活翻倍、归档并发写竞态。一把锁一行(name)，owner 为持锁进程的
-- 唯一标识，heartbeat 为最近一次续约的 unix 时间戳。锁过期(now-heartbeat>ttl)
-- 即可被其他 worker 抢占，从而在原 leader 进程死掉后自动接管。
CREATE TABLE IF NOT EXISTS scheduler_lock (
    name      TEXT PRIMARY KEY,   -- 锁名，如 'background'
    owner     TEXT,               -- 持锁进程唯一标识，如 '12345-ab12cd34'
    heartbeat REAL                -- 最近续约的 unix 时间戳
);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    with _write_lock:
        conn.executescript(_SCHEMA)
        # 幂等补列：老库的 blog_posts 没有 ai_title，CREATE IF NOT EXISTS 不会补，
        # 这里 ALTER 一次（已存在则忽略）。
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(blog_posts)")}
            if "ai_title" not in cols:
                conn.execute("ALTER TABLE blog_posts ADD COLUMN ai_title TEXT")
        except Exception as exc:
            logger.debug(f"_ensure_schema: blog_posts ai_title 补列跳过: {exc}")
        # 幂等补列：老库的 predictions 没有 pick_strategy（区分动能/普林格荐股）。
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(predictions)")}
            if "pick_strategy" not in cols:
                conn.execute("ALTER TABLE predictions ADD COLUMN pick_strategy TEXT DEFAULT 'momentum'")
        except Exception as exc:
            logger.debug(f"_ensure_schema: predictions pick_strategy 补列跳过: {exc}")
        # 幂等补列：行业维度 + 结算反事实/窗口敏感性字段（深度分析用）。
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(predictions)")}
            for col, ddl in (
                ("sector",          "ALTER TABLE predictions ADD COLUMN sector TEXT"),
                ("window_return",   "ALTER TABLE predictions ADD COLUMN window_return REAL"),
                ("mfe_pct",         "ALTER TABLE predictions ADD COLUMN mfe_pct REAL"),
                ("mae_pct",         "ALTER TABLE predictions ADD COLUMN mae_pct REAL"),
                ("horizon_returns", "ALTER TABLE predictions ADD COLUMN horizon_returns TEXT DEFAULT '{}'"),
            ):
                if col not in cols:
                    conn.execute(ddl)
        except Exception as exc:
            logger.debug(f"_ensure_schema: predictions 分析字段补列跳过: {exc}")
        # 幂等补列：老库的 watchlist 没有 color/cost_price/shares（单只标色 + 持仓）。
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(watchlist)")}
            for col, ddl in (
                ("color",      "ALTER TABLE watchlist ADD COLUMN color TEXT DEFAULT ''"),
                ("cost_price", "ALTER TABLE watchlist ADD COLUMN cost_price REAL"),
                ("shares",     "ALTER TABLE watchlist ADD COLUMN shares REAL"),
            ):
                if col not in cols:
                    conn.execute(ddl)
        except Exception as exc:
            logger.debug(f"_ensure_schema: watchlist 标色/持仓字段补列跳过: {exc}")
        # 幂等补列：老库的 sector_boards 没有 index_value/net_flow（同花顺概念指数用）。
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(sector_boards)")}
            for col, ddl in (
                ("index_value", "ALTER TABLE sector_boards ADD COLUMN index_value REAL"),
                ("net_flow",    "ALTER TABLE sector_boards ADD COLUMN net_flow REAL"),
            ):
                if col not in cols:
                    conn.execute(ddl)
        except Exception as exc:
            logger.debug(f"_ensure_schema: sector_boards 指数字段补列跳过: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now().isoformat()


def _size_b(payload: str) -> int:
    try:
        return len(payload.encode("utf-8"))
    except Exception:
        return len(payload)


# ---------------------------------------------------------------------------
# Scheduler leader 选举（多 worker 部署只让一个 worker 跑后台/定时任务）
# ---------------------------------------------------------------------------

def try_acquire_leader(name: str, owner: str, ttl: float = 120.0) -> bool:
    """尝试抢占名为 ``name`` 的 leader 锁，成功返回 True、失败返回 False。

    判定规则（三者满足其一即可抢到）：该锁尚不存在；现有锁的 heartbeat 已过期
    (``now - heartbeat > ttl``，说明原持锁进程很可能已死)；或现有 owner 就是
    自己(幂等续约)。满足时把该行写/更新为自己并刷新 heartbeat 返回 True；否则
    锁仍被别的活着的 worker 持有，返回 False。

    用一条 ``INSERT ... ON CONFLICT(name) DO UPDATE ... WHERE`` 的 upsert 原子
    完成「插入或在条件满足时抢占」——WHERE 不满足时冲突更新被跳过、行数为 0，
    据此判断是否抢到。``isolation_level=None`` 为 autocommit，写操作用
    ``_write_lock`` 串行化，避免同进程多线程并发抢锁互相干扰。

    Args:
        name: 锁名（如 ``"background"``）。
        owner: 本进程唯一标识（如 ``f"{pid}-{uuid}"``）。
        ttl: 锁有效期(秒)；超过 ttl 未续约即视为过期可被抢占。

    Returns:
        bool: 抢到(或本就是自己)返回 True，否则 False。
    """
    now = time.time()
    with _write_lock:
        conn = _conn()
        cur = conn.execute(
            """
            INSERT INTO scheduler_lock (name, owner, heartbeat)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                owner = excluded.owner,
                heartbeat = excluded.heartbeat
            WHERE scheduler_lock.owner = excluded.owner
               OR scheduler_lock.heartbeat IS NULL
               OR (excluded.heartbeat - scheduler_lock.heartbeat) > ?
            """,
            (name, owner, now, ttl),
        )
        # 插入成功(此前无该行)或冲突更新命中(过期/自己)时 rowcount>0；
        # 冲突但 WHERE 不满足(锁被别人活着持有)时 rowcount==0。
        return cur.rowcount > 0


def refresh_leader(name: str, owner: str) -> bool:
    """续约 leader 心跳：仅当 ``owner`` 确为自己时刷新 heartbeat 返回 True。

    若该锁已被别的 worker 接管（owner 不再是自己），更新影响 0 行返回 False，
    调用方据此得知自己已失去 leader 身份。供 leader 周期性(如每 30s)调用以
    维持锁不过期。

    Args:
        name: 锁名。
        owner: 本进程唯一标识。

    Returns:
        bool: 仍持锁并续约成功返回 True，已被接管返回 False。
    """
    now = time.time()
    with _write_lock:
        conn = _conn()
        cur = conn.execute(
            "UPDATE scheduler_lock SET heartbeat = ? WHERE name = ? AND owner = ?",
            (now, name, owner),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Core key/value cache API
# ---------------------------------------------------------------------------

def get(key: str, ttl_seconds: int | None = None) -> dict | None:
    """Return cached payload for ``key`` if it exists and is fresh.

    ``ttl_seconds`` — if omitted, the TTL stored alongside the entry is used;
    if provided, it overrides the stored TTL (useful when a caller wants a
    shorter/longer freshness window than what the writer originally set).
    Returns ``None`` if the entry is missing or expired.
    """
    try:
        row = _conn().execute(
            "SELECT payload, fetched_at, ttl_seconds FROM cache_entries WHERE key=?",
            (key,),
        ).fetchone()
    except Exception as exc:
        logger.debug(f"db_cache.get({key!r}) failed: {exc}")
        return None
    if not row:
        return None
    fetched = _parse_iso(row["fetched_at"])
    if fetched is None:
        return None
    ttl = ttl_seconds if ttl_seconds is not None else int(row["ttl_seconds"])
    if (datetime.now() - fetched).total_seconds() > ttl:
        return None
    try:
        return json.loads(row["payload"])
    except Exception as exc:
        logger.debug(f"db_cache.get({key!r}) bad JSON: {exc}")
        return None


def get_stale(key: str) -> dict | None:
    """Return the cached payload regardless of age — used as graceful fallback
    when the live upstream call fails."""
    try:
        row = _conn().execute(
            "SELECT payload FROM cache_entries WHERE key=?", (key,)
        ).fetchone()
    except Exception as exc:
        logger.debug(f"db_cache.get_stale({key!r}) failed: {exc}")
        return None
    if not row:
        return None
    try:
        return json.loads(row["payload"])
    except Exception:
        return None


def set(
    key: str,
    data: Any,
    ttl_seconds: int,
    category: str = "uncategorized",
) -> None:
    """Upsert ``data`` under ``key`` — **always overwrites** previous row.

    ``data`` is JSON-serialised; any non-serialisable leaf (e.g. a ``datetime``,
    a ``Decimal``) is coerced to its string representation via ``default=str``.
    """
    payload = json.dumps(data, ensure_ascii=False, default=str)
    with _write_lock:
        try:
            _conn().execute(
                """
                INSERT INTO cache_entries(key, category, payload, fetched_at, ttl_seconds)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    category   = excluded.category,
                    payload    = excluded.payload,
                    fetched_at = excluded.fetched_at,
                    ttl_seconds = excluded.ttl_seconds
                """,
                (
                    key,
                    category,
                    payload,
                    _now_iso(),
                    int(ttl_seconds),
                ),
            )
        except Exception as exc:
            logger.warning(f"db_cache.set({key!r}) failed: {exc}")


def delete(key: str) -> None:
    with _write_lock:
        try:
            _conn().execute("DELETE FROM cache_entries WHERE key=?", (key,))
        except Exception as exc:
            logger.debug(f"db_cache.delete({key!r}) failed: {exc}")


def list_by_category(category: str) -> list[dict]:
    try:
        rows = _conn().execute(
            """SELECT key, fetched_at, payload
               FROM cache_entries
               WHERE category=?
               ORDER BY fetched_at DESC""",
            (category,),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.list_by_category({category!r}) failed: {exc}")
        return []
    return [
        {
            "key": r["key"],
            "fetched_at": r["fetched_at"],
            "size_b": _size_b(r["payload"]),
        }
        for r in rows
    ]


def list_categories() -> list[dict]:
    try:
        rows = _conn().execute(
            """SELECT category,
                      COUNT(*)                                    AS count,
                      MIN(fetched_at)                            AS oldest,
                      MAX(fetched_at)                            AS newest
               FROM cache_entries
               GROUP BY category
               ORDER BY count DESC""",
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.list_categories failed: {exc}")
        return []
    return [dict(r) for r in rows]


def delete_by_category(category: str) -> int:
    with _write_lock:
        try:
            cur = _conn().execute(
                "DELETE FROM cache_entries WHERE category=?", (category,)
            )
            return cur.rowcount or 0
        except Exception as exc:
            logger.debug(f"db_cache.delete_by_category({category!r}) failed: {exc}")
            return 0


def clear_all() -> None:
    with _write_lock:
        try:
            _conn().execute("DELETE FROM cache_entries;")
            _conn().execute("DELETE FROM stock_meta;")
        except Exception as exc:
            logger.warning(f"db_cache.clear_all failed: {exc}")


def stats() -> dict:
    try:
        conn = _conn()
        total = conn.execute("SELECT COUNT(*) AS c FROM cache_entries").fetchone()["c"]
        cats = list_categories()
        stock_total = conn.execute("SELECT COUNT(*) AS c FROM stock_meta").fetchone()["c"]
    except Exception:
        total = stock_total = 0
        cats = []
    return {
        "db_path": str(_DB_PATH),
        "entries_total": total,
        "entries_by_category": cats,
        "stock_meta_total": stock_total,
    }


# ---------------------------------------------------------------------------
# stock_meta table helpers
# ---------------------------------------------------------------------------
# ``stock_meta`` duplicates the JSON-file-based stock name table into a proper
# SQL table so callers can do SQL-side searches, pagination and sorting without
# having to materialise the entire universe in Python memory each time.
#
# ``get_meta`` / ``set_meta`` keep the existing ``get_all_names()`` /
# ``search_stocks()`` API contract intact — nothing else in the codebase needs
# to change.

def _row_to_stock(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "code": row["code"],
        "name": row["name"] or "",
        "exchange": row["exchange"] or "",
        "price": row["price"],
        "change_pct": row["change_pct"],
        "change": row["change_val"],
    }


def get_stock(code: str) -> dict | None:
    try:
        row = _conn().execute(
            "SELECT * FROM stock_meta WHERE code=?", (code,)
        ).fetchone()
    except Exception:
        return None
    return _row_to_stock(row)


def get_all_names() -> dict[str, str]:
    try:
        rows = _conn().execute("SELECT code, name FROM stock_meta").fetchall()
    except Exception:
        return {}
    return {r["code"]: (r["name"] or "") for r in rows}


def count_stocks() -> int:
    try:
        return _conn().execute("SELECT COUNT(*) AS c FROM stock_meta").fetchone()["c"]
    except Exception:
        return 0


def search_stocks(query: str, limit: int = 50) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    try:
        rows = _conn().execute(
            """SELECT * FROM stock_meta
               WHERE code LIKE ? OR name LIKE ?
               ORDER BY code ASC
               LIMIT ?""",
            (like, like, int(limit)),
        ).fetchall()
    except Exception:
        return []
    return [_row_to_stock(r) for r in rows if r]


def list_stocks(
    limit: int = 100,
    sort_by: str = "code",
    order: str = "asc",
    filter_type: str | None = None,
) -> list[dict]:
    sort_cols = {
        "code": "code",
        "name": "name",
        "change_pct": "change_pct",
        "price": "price",
    }
    col = sort_cols.get(sort_by, "code")
    direction = "DESC" if (order or "").lower() == "desc" else "ASC"

    where = ""
    params: list[Any] = []
    if filter_type == "gainers":
        where = "WHERE change_pct IS NOT NULL "
    elif filter_type == "losers":
        where = "WHERE change_pct IS NOT NULL "

    try:
        rows = _conn().execute(
            f"""SELECT * FROM stock_meta {where}
                ORDER BY {col} {direction}
                LIMIT ?""",
            params + [int(limit)],
        ).fetchall()
    except Exception:
        return []
    return [_row_to_stock(r) for r in rows if r]


def upsert_stocks(rows: list[dict]) -> int:
    """Bulk-upsert rows into the ``stock_meta`` table.

    ``rows`` items should include ``code`` + ``name`` (and optionally
    ``exchange``, ``price``, ``change_pct``, ``change``).  Rows without a
    ``code`` are skipped.
    """
    now = _now_iso()
    tuples = []
    for r in rows:
        code = r.get("code")
        if not code:
            continue
        tuples.append(
            (
                str(code),
                r.get("name", ""),
                r.get("exchange", ""),
                r.get("price"),
                r.get("change_pct"),
                r.get("change"),
                now,
            )
        )
    if not tuples:
        return 0
    with _write_lock:
        try:
            _conn().executemany(
                """
                INSERT INTO stock_meta(code, name, exchange, price, change_pct, change_val, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name       = excluded.name,
                    exchange   = excluded.exchange,
                    price      = excluded.price,
                    change_pct = excluded.change_pct,
                    change_val = excluded.change_val,
                    updated_at = excluded.updated_at
                """,
                tuples,
            )
        except Exception as exc:
            logger.warning(f"db_cache.upsert_stocks failed: {exc}")
            return 0
    return len(tuples)


def clear_stock_meta() -> None:
    with _write_lock:
        try:
            _conn().execute("DELETE FROM stock_meta;")
        except Exception as exc:
            logger.debug(f"db_cache.clear_stock_meta failed: {exc}")


# ---------------------------------------------------------------------------
# stock_kline table — incremental OHLCV bars
# ---------------------------------------------------------------------------

def kline_load(code: str, period: str = "day", limit: int | None = None) -> list[dict]:
    """Return stored bars for code+period, oldest→newest.

    ``limit`` keeps only the most recent N bars (still chronological)."""
    code = str(code).strip().upper()
    try:
        rows = _conn().execute(
            """SELECT date, open, close, high, low, volume, change_pct
               FROM stock_kline WHERE code=? AND period=? ORDER BY date ASC""",
            (code, period),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.kline_load({code},{period}) failed: {exc}")
        return []
    bars = [
        {
            "datetime": r["date"], "date": r["date"],
            "open": r["open"], "close": r["close"],
            "high": r["high"], "low": r["low"],
            "volume": r["volume"], "change_pct": r["change_pct"],
        }
        for r in rows
    ]
    if limit is not None and len(bars) > limit:
        bars = bars[-limit:]
    return bars


def kline_last_date(code: str, period: str = "day") -> str | None:
    code = str(code).strip().upper()
    try:
        row = _conn().execute(
            "SELECT MAX(date) AS d FROM stock_kline WHERE code=? AND period=?",
            (code, period),
        ).fetchone()
        return row["d"] if row and row["d"] else None
    except Exception as exc:
        logger.debug(f"db_cache.kline_last_date({code},{period}) failed: {exc}")
        return None


def kline_code_count(period: str = "day", min_bars: int = 40) -> int:
    """已缓存 K 线的股票数（bar 数≥min_bars 的 distinct code）。

    供全市场扫描覆盖度统计：能被动能扫描的票数大致等于此值。
    """
    try:
        row = _conn().execute(
            """SELECT COUNT(*) AS n FROM (
                   SELECT code FROM stock_kline WHERE period=?
                   GROUP BY code HAVING COUNT(*) >= ?
               )""",
            (period, min_bars),
        ).fetchone()
        return int(row["n"]) if row and row["n"] is not None else 0
    except Exception as exc:
        logger.debug(f"db_cache.kline_code_count failed: {exc}")
        return 0


def kline_upsert(code: str, period: str, bars: list[dict]) -> int:
    """Insert-or-replace bars. Each bar needs a date (``date`` or ``datetime``,
    'YYYY-MM-DD' prefix) + OHLCV. Returns number of rows written."""
    code = str(code).strip().upper()
    tuples = []
    for b in bars or []:
        d = str(b.get("date") or b.get("datetime") or "")[:10]
        if not d:
            continue
        tuples.append((
            code, period, d,
            b.get("open"), b.get("close"), b.get("high"), b.get("low"),
            b.get("volume"), b.get("change_pct"),
        ))
    if not tuples:
        return 0
    with _write_lock:
        try:
            _conn().executemany(
                """INSERT INTO stock_kline(code, period, date, open, close, high, low, volume, change_pct)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(code, period, date) DO UPDATE SET
                       open=excluded.open, close=excluded.close,
                       high=excluded.high, low=excluded.low,
                       volume=excluded.volume, change_pct=excluded.change_pct""",
                tuples,
            )
        except Exception as exc:
            logger.warning(f"db_cache.kline_upsert({code},{period}) failed: {exc}")
            return 0
    return len(tuples)


# ---------------------------------------------------------------------------
# predictions table — AI 荐股预测记录 + 结算
# ---------------------------------------------------------------------------
# 替代 data/cache/predictions.json：平文件全量读改写在双 worker / 后台结算
# 并发时会互相覆盖（同研报任务踩过的坑）。改为行级 upsert + 单写锁。

_PRED_COLS = [
    "id", "date", "code", "name", "predicted_at", "buy_price", "stop_price",
    "target_price", "target_pct", "stop_pct", "confidence", "risk_level",
    "strategy_name", "pick_strategy", "hit_strategies", "verified", "entry_price",
    "actual_close", "actual_change_pct", "outcome", "trigger_date", "hold_days",
    "bench_change_pct", "verified_at",
    "sector", "window_return", "mfe_pct", "mae_pct", "horizon_returns",
]


def _row_to_pred(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = {k: row[k] for k in _PRED_COLS}
    d["verified"] = bool(d.get("verified"))
    try:
        d["hit_strategies"] = json.loads(d.get("hit_strategies") or "[]")
    except Exception:
        d["hit_strategies"] = []
    try:
        d["horizon_returns"] = json.loads(d.get("horizon_returns") or "{}") if d.get("horizon_returns") else {}
    except Exception:
        d["horizon_returns"] = {}
    return d


def predictions_upsert_many(rows: list[dict]) -> int:
    """Bulk-upsert prediction rows (by id). Preserves existing settlement fields
    when a row only carries the pick fields (COALESCE keeps prior verify state)."""
    tuples = []
    for r in rows:
        rid = r.get("id")
        if not rid:
            continue
        hs = r.get("hit_strategies")
        hs = json.dumps(hs, ensure_ascii=False) if isinstance(hs, (list, dict)) else (hs or "[]")
        hr = r.get("horizon_returns")
        hr = json.dumps(hr, ensure_ascii=False) if isinstance(hr, (dict, list)) else hr
        tuples.append((
            rid, r.get("date"), r.get("code"), r.get("name"), r.get("predicted_at"),
            r.get("buy_price"), r.get("stop_price"), r.get("target_price"),
            r.get("target_pct"), r.get("stop_pct"), r.get("confidence"),
            r.get("risk_level"), r.get("strategy_name"),
            r.get("pick_strategy") or "momentum", hs,
            1 if r.get("verified") else 0, r.get("entry_price"), r.get("actual_close"),
            r.get("actual_change_pct"), r.get("outcome"), r.get("trigger_date"),
            r.get("hold_days"), r.get("bench_change_pct"), r.get("verified_at"),
            r.get("sector"), r.get("window_return"), r.get("mfe_pct"),
            r.get("mae_pct"), hr,
        ))
    if not tuples:
        return 0
    placeholders = ", ".join(["?"] * len(_PRED_COLS))
    sql = (
        f"INSERT INTO predictions({', '.join(_PRED_COLS)}) VALUES({placeholders}) "
        "ON CONFLICT(id) DO UPDATE SET "
        # pick 字段总是刷新（idempotent re-record）
        "date=excluded.date, code=excluded.code, name=excluded.name, "
        "predicted_at=excluded.predicted_at, buy_price=excluded.buy_price, "
        "stop_price=excluded.stop_price, target_price=excluded.target_price, "
        "target_pct=excluded.target_pct, stop_pct=excluded.stop_pct, "
        "confidence=excluded.confidence, risk_level=excluded.risk_level, "
        "strategy_name=excluded.strategy_name, pick_strategy=excluded.pick_strategy, "
        "sector=COALESCE(excluded.sector, predictions.sector), "
        # hit_strategies：新值非空才覆盖（回填友好）
        "hit_strategies=CASE WHEN excluded.hit_strategies NOT IN ('','[]') "
        "THEN excluded.hit_strategies ELSE predictions.hit_strategies END"
    )
    with _write_lock:
        conn = _conn()
        try:
            conn.execute("BEGIN")
            conn.executemany(sql, tuples)
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning(f"db_cache.predictions_upsert_many failed: {exc}")
            return 0
    return len(tuples)


def predictions_all() -> list[dict]:
    try:
        rows = _conn().execute(
            "SELECT * FROM predictions ORDER BY date DESC"
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.predictions_all failed: {exc}")
        return []
    return [p for r in rows if (p := _row_to_pred(r))]


def predictions_get(pred_id: str) -> dict | None:
    try:
        row = _conn().execute(
            "SELECT * FROM predictions WHERE id=?", (pred_id,)
        ).fetchone()
    except Exception:
        return None
    return _row_to_pred(row)


def predictions_update_settlement(pred_id: str, fields: dict) -> None:
    """Write settlement fields back to one prediction row."""
    cols = [c for c in (
        "verified", "entry_price", "actual_close", "actual_change_pct",
        "outcome", "trigger_date", "hold_days", "bench_change_pct", "verified_at",
        "window_return", "mfe_pct", "mae_pct", "horizon_returns",
    ) if c in fields]
    if not cols:
        return
    sets = ", ".join(f"{c}=?" for c in cols)

    def _enc(c):
        v = fields[c]
        if c == "verified":
            return 1 if v else 0
        if c == "horizon_returns" and isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return v
    vals = [_enc(c) for c in cols]
    with _write_lock:
        try:
            _conn().execute(
                f"UPDATE predictions SET {sets} WHERE id=?", (*vals, pred_id)
            )
        except Exception as exc:
            logger.warning(f"db_cache.predictions_update_settlement({pred_id!r}) failed: {exc}")


def predictions_delete(ids: list[str]) -> int:
    ids = [str(i) for i in (ids or []) if i]
    if not ids:
        return 0
    with _write_lock:
        try:
            conn = _conn()
            before = conn.execute("SELECT COUNT(*) AS c FROM predictions").fetchone()["c"]
            ph = ", ".join(["?"] * len(ids))
            conn.execute(f"DELETE FROM predictions WHERE id IN ({ph})", ids)
            after = conn.execute("SELECT COUNT(*) AS c FROM predictions").fetchone()["c"]
            return int(before - after)
        except Exception as exc:
            logger.debug(f"db_cache.predictions_delete failed: {exc}")
            return 0


def predictions_count() -> int:
    try:
        return _conn().execute("SELECT COUNT(*) AS c FROM predictions").fetchone()["c"]
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# stock_quote table — whole-market realtime snapshot
# ---------------------------------------------------------------------------
# One row per stock, refreshed by the background snapshot task
# (``data/feed/snapshot.py``).  Reads serve display from here so latency is
# decoupled from upstream APIs — always <1s and, when the network is down,
# stale-but-instant from the last snapshot.

_QUOTE_COLS = [
    "code", "name", "exchange", "price", "change_pct", "change",
    "open", "high", "low", "pre_close", "volume", "turnover",
    "turnover_rate", "pe", "pb", "market_cap", "updated_at",
]

# Whitelisted sort columns (prevents SQL injection via ``sort_by``).
_QUOTE_SORT_COLS = {
    "code": "code", "name": "name", "change_pct": "change_pct",
    "price": "price", "turnover": "turnover", "turnover_rate": "turnover_rate",
    "pe": "pe", "market_cap": "market_cap",
}


def _row_to_quote(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in _QUOTE_COLS}


def quote_upsert_many(rows: list[dict]) -> int:
    """Bulk-upsert realtime quotes into ``stock_quote`` (single transaction).

    Each row needs ``code``; other fields default to None.  ~5400 rows < 200ms.
    """
    now = _now_iso()
    tuples = []
    for r in rows:
        code = r.get("code")
        if not code:
            continue
        tuples.append((
            str(code), r.get("name"), r.get("exchange"), r.get("price"),
            r.get("change_pct"), r.get("change"), r.get("open"), r.get("high"),
            r.get("low"), r.get("pre_close"), r.get("volume"), r.get("turnover"),
            r.get("turnover_rate"), r.get("pe"), r.get("pb"), r.get("market_cap"),
            r.get("updated_at") or now,
        ))
    if not tuples:
        return 0
    placeholders = ", ".join(["?"] * len(_QUOTE_COLS))
    update_cols = [c for c in _QUOTE_COLS if c != "code"]
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
    sql = (
        f"INSERT INTO stock_quote({', '.join(_QUOTE_COLS)}) "
        f"VALUES({placeholders}) "
        f"ON CONFLICT(code) DO UPDATE SET {update_clause}"
    )
    with _write_lock:
        conn = _conn()
        try:
            conn.execute("BEGIN")
            conn.executemany(sql, tuples)
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning(f"db_cache.quote_upsert_many failed: {exc}")
            return 0
    return len(tuples)


def quote_query(
    *,
    sort_by: str = "code",
    order: str = "asc",
    filter_type: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    """Indexed query over the snapshot: filter + search + sort + paginate.

    Returns ``(rows, total)`` where ``total`` is the match count before paging.
    """
    col = _QUOTE_SORT_COLS.get(sort_by, "code")
    direction = "DESC" if (order or "").lower() == "desc" else "ASC"

    clauses: list[str] = []
    params: list[Any] = []
    if filter_type == "gainers":
        clauses.append("change_pct IS NOT NULL AND change_pct > 0")
    elif filter_type == "losers":
        clauses.append("change_pct IS NOT NULL AND change_pct < 0")
    q = (search or "").strip()
    if q:
        clauses.append("(code LIKE ? OR name LIKE ?)")
        like = f"%{q}%"
        params += [like, like]
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 500))
    offset = (page - 1) * page_size

    conn = _conn()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM stock_quote {where}", params
        ).fetchone()["c"]
        # NULLs sort last regardless of direction (keeps涨跌榜干净).
        rows = conn.execute(
            f"""SELECT * FROM stock_quote {where}
                ORDER BY ({col} IS NULL), {col} {direction}
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.quote_query failed: {exc}")
        return [], 0
    return [_row_to_quote(r) for r in rows if r], int(total)


def quote_get_many(codes: list[str]) -> dict[str, dict]:
    """Return {code: quote} for the given codes from the snapshot."""
    codes = [str(c) for c in (codes or []) if c]
    if not codes:
        return {}
    out: dict[str, dict] = {}
    conn = _conn()
    # chunk to stay under SQLite's parameter limit
    for i in range(0, len(codes), 500):
        chunk = codes[i:i + 500]
        ph = ", ".join(["?"] * len(chunk))
        try:
            rows = conn.execute(
                f"SELECT * FROM stock_quote WHERE code IN ({ph})", chunk
            ).fetchall()
        except Exception:
            continue
        for r in rows:
            q = _row_to_quote(r)
            if q:
                out[q["code"]] = q
    return out


def quote_distribution() -> dict | None:
    """全市场涨跌幅分布(直方图分桶)+ 上涨/下跌/平盘统计，SQL 聚合直接出。

    分桶边界(%)：跌停(≤-9.9)、(-9.9,-7]、(-7,-5]、(-5,-3]、(-3,-1]、(-1,0)、
    平(=0)、(0,1)、[1,3)、[3,5)、[5,7)、[7,9.9)、涨停(≥9.9)。返回 None 表示
    快照为空(冷启动)。"""
    conn = _conn()
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM stock_quote WHERE change_pct IS NOT NULL"
        ).fetchone()["c"]
        if not total:
            return None
        # CASE 分桶一次扫描，避免拉全表到 Python 端。
        row = conn.execute("""
            SELECT
              SUM(change_pct <= -9.9)                            AS limit_down,
              SUM(change_pct > -9.9 AND change_pct <= -7)        AS d7,
              SUM(change_pct > -7   AND change_pct <= -5)        AS d5,
              SUM(change_pct > -5   AND change_pct <= -3)        AS d3,
              SUM(change_pct > -3   AND change_pct <= -1)        AS d1,
              SUM(change_pct > -1   AND change_pct <  0)         AS d0,
              SUM(change_pct = 0)                                AS flat,
              SUM(change_pct > 0    AND change_pct <  1)         AS u0,
              SUM(change_pct >= 1   AND change_pct <  3)         AS u1,
              SUM(change_pct >= 3   AND change_pct <  5)         AS u3,
              SUM(change_pct >= 5   AND change_pct <  7)         AS u5,
              SUM(change_pct >= 7   AND change_pct <  9.9)       AS u7,
              SUM(change_pct >= 9.9)                             AS limit_up,
              SUM(change_pct > 0)                                AS up_total,
              SUM(change_pct < 0)                                AS down_total
            FROM stock_quote WHERE change_pct IS NOT NULL
        """).fetchone()
    except Exception as exc:
        logger.debug(f"db_cache.quote_distribution failed: {exc}")
        return None

    g = lambda k: int(row[k] or 0)
    buckets = [
        {"label": "跌停",      "key": "limit_down", "count": g("limit_down"), "side": "down"},
        {"label": "-7~-9.9",  "key": "d7",         "count": g("d7"),         "side": "down"},
        {"label": "-5~-7",    "key": "d5",         "count": g("d5"),         "side": "down"},
        {"label": "-3~-5",    "key": "d3",         "count": g("d3"),         "side": "down"},
        {"label": "-1~-3",    "key": "d1",         "count": g("d1"),         "side": "down"},
        {"label": "0~-1",     "key": "d0",         "count": g("d0"),         "side": "down"},
        {"label": "平",       "key": "flat",       "count": g("flat"),       "side": "flat"},
        {"label": "0~1",      "key": "u0",         "count": g("u0"),         "side": "up"},
        {"label": "1~3",      "key": "u1",         "count": g("u1"),         "side": "up"},
        {"label": "3~5",      "key": "u3",         "count": g("u3"),         "side": "up"},
        {"label": "5~7",      "key": "u5",         "count": g("u5"),         "side": "up"},
        {"label": "7~9.9",    "key": "u7",         "count": g("u7"),         "side": "up"},
        {"label": "涨停",     "key": "limit_up",   "count": g("limit_up"),   "side": "up"},
    ]
    up, down, flat = g("up_total"), g("down_total"), g("flat")
    return {
        "buckets": buckets,
        "up_count": up, "down_count": down, "flat_count": flat,
        "limit_up": g("limit_up"), "limit_down": g("limit_down"),
        "total": total,
        "advance_decline_ratio": round(up / down, 2) if down else None,
        "updated_at": quote_max_updated(),
    }


def quote_count() -> int:
    try:
        return _conn().execute("SELECT COUNT(*) AS c FROM stock_quote").fetchone()["c"]
    except Exception:
        return 0


def quote_max_updated() -> str | None:
    try:
        row = _conn().execute("SELECT MAX(updated_at) AS m FROM stock_quote").fetchone()
        return row["m"] if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Sector tables (structured storage for industry/concept boards + constituents)
# ---------------------------------------------------------------------------

_BOARD_COLS = [
    "kind", "name", "node", "change_pct", "avg_pe", "median_pe", "avg_pb",
    "pe_valid", "turnover_rate", "market_cap", "amount", "up_count",
    "down_count", "total", "leader", "leader_change", "index_value", "net_flow",
]

_CONS_COLS = [
    "code", "name", "price", "change_pct", "turnover_rate", "turnover",
    "pe", "pb", "market_cap",
]


def _newest_age_seconds(rows: list[sqlite3.Row]) -> float | None:
    """Seconds since the most recently updated row (None if no timestamps)."""
    stamps = [_parse_iso(r["updated_at"]) for r in rows if r["updated_at"]]
    stamps = [s for s in stamps if s is not None]
    if not stamps:
        return None
    return (datetime.now() - max(stamps)).total_seconds()


def replace_sector_boards(kind: str, boards: list[dict]) -> int:
    """Replace the whole snapshot of boards for ``kind`` (delete + insert)."""
    now = _now_iso()
    rows = []
    for b in boards:
        vals = [kind if c == "kind" else b.get(c) for c in _BOARD_COLS]
        rows.append(tuple(vals) + (now,))
    placeholders = ",".join("?" * (len(_BOARD_COLS) + 1))
    cols = ",".join(_BOARD_COLS) + ",updated_at"
    with _write_lock:
        try:
            conn = _conn()
            conn.execute("DELETE FROM sector_boards WHERE kind=?", (kind,))
            conn.executemany(
                f"INSERT INTO sector_boards({cols}) VALUES({placeholders})", rows
            )
        except Exception as exc:
            logger.warning(f"db_cache.replace_sector_boards({kind!r}) failed: {exc}")
            return 0
    return len(rows)


def get_sector_boards(kind: str) -> list[dict] | None:
    """All stored boards for ``kind`` (regardless of age). None if empty."""
    try:
        rows = _conn().execute(
            "SELECT * FROM sector_boards WHERE kind=? ORDER BY name", (kind,)
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.get_sector_boards({kind!r}) failed: {exc}")
        return None
    if not rows:
        return None
    out = []
    for r in rows:
        d = dict(r)
        d.pop("updated_at", None)
        out.append(d)
    return out


def sector_boards_fresh(kind: str, ttl_seconds: int) -> bool:
    try:
        rows = _conn().execute(
            "SELECT updated_at FROM sector_boards WHERE kind=?", (kind,)
        ).fetchall()
    except Exception:
        return False
    age = _newest_age_seconds(rows)
    return age is not None and age <= ttl_seconds


def replace_sector_constituents(kind: str, board: str, stocks: list[dict]) -> int:
    """Replace the constituent snapshot for one (kind, board)."""
    now = _now_iso()
    rows = []
    for s in stocks:
        vals = [kind, board] + [s.get(c) for c in _CONS_COLS]
        rows.append(tuple(vals) + (now,))
    cols = "kind,board," + ",".join(_CONS_COLS) + ",updated_at"
    placeholders = ",".join("?" * (len(_CONS_COLS) + 3))
    with _write_lock:
        try:
            conn = _conn()
            conn.execute(
                "DELETE FROM sector_constituents WHERE kind=? AND board=?", (kind, board)
            )
            conn.executemany(
                f"INSERT INTO sector_constituents({cols}) VALUES({placeholders})", rows
            )
        except Exception as exc:
            logger.warning(
                f"db_cache.replace_sector_constituents({kind!r},{board!r}) failed: {exc}"
            )
            return 0
    return len(rows)


def get_sector_constituents(kind: str, board: str) -> list[dict] | None:
    try:
        rows = _conn().execute(
            "SELECT * FROM sector_constituents WHERE kind=? AND board=? "
            "ORDER BY change_pct DESC",
            (kind, board),
        ).fetchall()
    except Exception as exc:
        logger.debug(
            f"db_cache.get_sector_constituents({kind!r},{board!r}) failed: {exc}"
        )
        return None
    if not rows:
        return None
    out = []
    for r in rows:
        d = dict(r)
        d.pop("kind", None)
        d.pop("board", None)
        d.pop("updated_at", None)
        out.append(d)
    return out


def sector_constituents_fresh(kind: str, board: str, ttl_seconds: int) -> bool:
    try:
        rows = _conn().execute(
            "SELECT updated_at FROM sector_constituents WHERE kind=? AND board=?",
            (kind, board),
        ).fetchall()
    except Exception:
        return False
    age = _newest_age_seconds(rows)
    return age is not None and age <= ttl_seconds


_SECTOR_HIST_COLS = [
    "change_pct", "turnover_rate", "amount", "market_cap",
    "net_flow", "amount_share", "crowding",
]


def sector_history_append(kind: str, date: str, rows: list[dict]) -> int:
    """Upsert one daily snapshot per board into ``sector_metric_history``.

    Same (kind, name, date) is overwritten — the warmer runs many times a day,
    so the last write of the trading day wins. ``rows`` items need ``name`` plus
    any of the metric columns in :data:`_SECTOR_HIST_COLS`.
    """
    date = str(date)[:10]
    tuples = []
    for r in rows:
        name = r.get("name")
        if not name:
            continue
        tuples.append(
            (kind, name, date) + tuple(r.get(c) for c in _SECTOR_HIST_COLS)
        )
    if not tuples:
        return 0
    cols = "kind,name,date," + ",".join(_SECTOR_HIST_COLS)
    placeholders = ",".join("?" * (len(_SECTOR_HIST_COLS) + 3))
    update = ",".join(f"{c}=excluded.{c}" for c in _SECTOR_HIST_COLS)
    with _write_lock:
        try:
            _conn().executemany(
                f"INSERT INTO sector_metric_history({cols}) VALUES({placeholders}) "
                f"ON CONFLICT(kind, name, date) DO UPDATE SET {update}",
                tuples,
            )
        except Exception as exc:
            logger.warning(f"db_cache.sector_history_append({kind!r}) failed: {exc}")
            return 0
    return len(tuples)


def sector_history_load(kind: str, lookback_days: int = 90) -> dict[str, list[dict]]:
    """Return {board_name: [rows oldest→newest]} for the most recent dates.

    Limits to the latest ``lookback_days`` distinct dates to bound the scan.
    """
    try:
        dates = _conn().execute(
            "SELECT DISTINCT date FROM sector_metric_history WHERE kind=? "
            "ORDER BY date DESC LIMIT ?",
            (kind, int(lookback_days)),
        ).fetchall()
        if not dates:
            return {}
        cutoff = min(d["date"] for d in dates)
        rows = _conn().execute(
            "SELECT name, date, change_pct, turnover_rate, amount, market_cap, "
            "net_flow, amount_share, crowding FROM sector_metric_history "
            "WHERE kind=? AND date>=? ORDER BY name, date ASC",
            (kind, cutoff),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.sector_history_load({kind!r}) failed: {exc}")
        return {}
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["name"], []).append(dict(r))
    return out


def boards_of_code(code: str, kind: str = "concept") -> list[str]:
    """反查个股所属的板块名（默认概念）：扫已落库的 sector_constituents。

    成分股表里 code 多为 6 位裸代码；这里同时兼容带 SH/SZ/BJ 前后缀的入参。
    返回去重的板块名列表（可能为空——概念页未预热时该表无数据）。
    """
    c = str(code or "").strip().upper()
    for p in ("SH", "SZ", "BJ"):
        if c.startswith(p):
            c = c[2:]
            break
    c = c.split(".")[0]
    if not c:
        return []
    try:
        rows = _conn().execute(
            "SELECT DISTINCT board FROM sector_constituents WHERE kind=? AND code=?",
            (kind, c),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.boards_of_code({code!r},{kind!r}) failed: {exc}")
        return []
    return [r["board"] for r in rows if r["board"]]


# ---------------------------------------------------------------------------
# Watchlist (per-account)
# ---------------------------------------------------------------------------

def _row_to_watch(row: sqlite3.Row) -> dict:
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
    except Exception:
        tags = []
    keys = row.keys()
    return {
        "code": row["code"],
        "name": row["name"] or row["code"],
        "notes": row["notes"] or "",
        "tags": tags,
        "color": (row["color"] if "color" in keys else "") or "",
        "cost_price": row["cost_price"] if "cost_price" in keys else None,
        "shares": row["shares"] if "shares" in keys else None,
        "added_at": row["added_at"],
    }


def get_watchlist(user_id: str) -> list[dict]:
    try:
        rows = _conn().execute(
            "SELECT * FROM watchlist WHERE user_id=? ORDER BY added_at", (user_id,)
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.get_watchlist({user_id!r}) failed: {exc}")
        return []
    return [_row_to_watch(r) for r in rows]


def watchlist_all_codes() -> list[str]:
    """Distinct stock codes across every user's watchlist (for prewarming)."""
    try:
        rows = _conn().execute("SELECT DISTINCT code FROM watchlist").fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.watchlist_all_codes failed: {exc}")
        return []
    return [r["code"] for r in rows if r["code"]]


def watchlist_get_item(user_id: str, code: str) -> dict | None:
    try:
        row = _conn().execute(
            "SELECT * FROM watchlist WHERE user_id=? AND code=?", (user_id, code)
        ).fetchone()
    except Exception:
        return None
    return _row_to_watch(row) if row else None


def watchlist_add(user_id: str, code: str, name: str = "", notes: str = "",
                  tags: list[str] | None = None) -> dict | None:
    """Insert a watchlist row. Returns the new item, or None if it already existed."""
    if watchlist_get_item(user_id, code) is not None:
        return None
    item = {
        "code": code,
        "name": name or code,
        "notes": notes or "",
        "tags": tags or [],
        "added_at": _now_iso(),
    }
    with _write_lock:
        try:
            _conn().execute(
                "INSERT INTO watchlist(user_id, code, name, notes, tags, added_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (user_id, code, item["name"], item["notes"],
                 json.dumps(item["tags"], ensure_ascii=False), item["added_at"]),
            )
        except Exception as exc:
            logger.warning(f"db_cache.watchlist_add failed: {exc}")
            return None
    return item


def watchlist_remove(user_id: str, code: str) -> bool:
    with _write_lock:
        try:
            cur = _conn().execute(
                "DELETE FROM watchlist WHERE user_id=? AND code=?", (user_id, code)
            )
            return (cur.rowcount or 0) > 0
        except Exception as exc:
            logger.debug(f"db_cache.watchlist_remove failed: {exc}")
            return False


def watchlist_update_notes(user_id: str, code: str, notes: str) -> dict | None:
    with _write_lock:
        try:
            cur = _conn().execute(
                "UPDATE watchlist SET notes=? WHERE user_id=? AND code=?",
                (notes or "", user_id, code),
            )
            if (cur.rowcount or 0) == 0:
                return None
        except Exception as exc:
            logger.warning(f"db_cache.watchlist_update_notes failed: {exc}")
            return None
    return watchlist_get_item(user_id, code)


def watchlist_clear(user_id: str) -> int:
    with _write_lock:
        try:
            cur = _conn().execute("DELETE FROM watchlist WHERE user_id=?", (user_id,))
            return cur.rowcount or 0
        except Exception as exc:
            logger.debug(f"db_cache.watchlist_clear failed: {exc}")
            return 0


def watchlist_set_tags(user_id: str, code: str, tags: list[str]) -> dict | None:
    with _write_lock:
        try:
            cur = _conn().execute(
                "UPDATE watchlist SET tags=? WHERE user_id=? AND code=?",
                (json.dumps(tags or [], ensure_ascii=False), user_id, code),
            )
            if (cur.rowcount or 0) == 0:
                return None
        except Exception as exc:
            logger.warning(f"db_cache.watchlist_set_tags failed: {exc}")
            return None
    return watchlist_get_item(user_id, code)


def watchlist_set_color(user_id: str, code: str, color: str) -> dict | None:
    """Set (or clear with '') a single stock's marker color."""
    with _write_lock:
        try:
            cur = _conn().execute(
                "UPDATE watchlist SET color=? WHERE user_id=? AND code=?",
                (color or "", user_id, code),
            )
            if (cur.rowcount or 0) == 0:
                return None
        except Exception as exc:
            logger.warning(f"db_cache.watchlist_set_color failed: {exc}")
            return None
    return watchlist_get_item(user_id, code)


def watchlist_set_holding(user_id: str, code: str,
                          cost_price: float | None, shares: float | None) -> dict | None:
    """Set (or clear with None) a stock's holding cost & share count."""
    with _write_lock:
        try:
            cur = _conn().execute(
                "UPDATE watchlist SET cost_price=?, shares=? WHERE user_id=? AND code=?",
                (cost_price, shares, user_id, code),
            )
            if (cur.rowcount or 0) == 0:
                return None
        except Exception as exc:
            logger.warning(f"db_cache.watchlist_set_holding failed: {exc}")
            return None
    return watchlist_get_item(user_id, code)


def watchlist_tags(user_id: str) -> list[dict]:
    """Distinct tags for a user's watchlist with usage counts (desc)."""
    counts: dict[str, int] = {}
    for it in get_watchlist(user_id):
        for t in it.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": k, "count": v}
            for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


# ---------------------------------------------------------------------------
# Chat archive (AI 聊股对话存档)
# ---------------------------------------------------------------------------

def chat_log_turn(user_id: str | None, username: str | None, session_id: str,
                  title: str, user_text: str, assistant_text: str) -> None:
    """落库一轮对话：先写 user 消息，再写 assistant 回复（同一 session）。

    seq 在会话内递增（取当前 max+1）。两条消息共享同一 title（取最近值）。
    任何异常都吞掉——存档不应影响聊天主流程。
    """
    if not session_id:
        return
    ts = _now_iso()
    with _write_lock:
        try:
            conn = _conn()
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), -1) AS m FROM chat_messages "
                "WHERE session_id=?", (session_id,),
            ).fetchone()
            seq = int(row["m"]) + 1
            rows = []
            if user_text and user_text.strip():
                rows.append((user_id, username, session_id, title, seq,
                             "user", user_text, ts))
                seq += 1
            if assistant_text and assistant_text.strip():
                rows.append((user_id, username, session_id, title, seq,
                             "assistant", assistant_text, ts))
            if rows:
                conn.executemany(
                    "INSERT INTO chat_messages"
                    "(user_id, username, session_id, title, seq, role, content, ts) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?)", rows,
                )
        except Exception as exc:
            logger.debug(f"db_cache.chat_log_turn failed: {exc}")


def chat_sessions(user_id: str | None = None, limit: int = 200) -> list[dict]:
    """会话列表（按最近活跃倒序）。``user_id`` 为空时跨所有用户。

    每项：{session_id, user_id, username, title, message_count,
           first_ts, last_ts}。
    """
    try:
        where = "WHERE user_id=?" if user_id else ""
        params: tuple = (user_id,) if user_id else ()
        rows = _conn().execute(
            f"""SELECT session_id,
                       MAX(user_id)  AS user_id,
                       MAX(username) AS username,
                       MAX(title)    AS title,
                       COUNT(*)      AS message_count,
                       MIN(ts)       AS first_ts,
                       MAX(ts)       AS last_ts
                FROM chat_messages {where}
                GROUP BY session_id
                ORDER BY last_ts DESC
                LIMIT ?""",
            (*params, int(limit)),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.chat_sessions failed: {exc}")
        return []
    return [{
        "session_id":    r["session_id"],
        "user_id":       r["user_id"],
        "username":      r["username"],
        "title":         r["title"] or "新对话",
        "message_count": r["message_count"],
        "first_ts":      r["first_ts"],
        "last_ts":       r["last_ts"],
    } for r in rows]


def chat_session_messages(session_id: str) -> list[dict]:
    """某会话的全部消息（按 seq 升序）。"""
    try:
        rows = _conn().execute(
            "SELECT role, content, ts, username FROM chat_messages "
            "WHERE session_id=? ORDER BY seq", (session_id,),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.chat_session_messages failed: {exc}")
        return []
    return [{
        "role":     r["role"],
        "content":  r["content"],
        "ts":       r["ts"],
        "username": r["username"],
    } for r in rows]


def _row_to_verif(row: sqlite3.Row) -> dict:
    try:
        results = json.loads(row["results"]) if row["results"] else []
    except Exception:
        results = []
    return {
        "id": row["id"],
        "period_days": row["period_days"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "total_return": row["total_return"],
        "results": results,
        "created_at": row["created_at"],
    }


def add_watch_verification(user_id: str, period_days, start_date, end_date,
                           total_return, results) -> dict | None:
    created = _now_iso()
    with _write_lock:
        try:
            cur = _conn().execute(
                "INSERT INTO watchlist_verifications"
                "(user_id, period_days, start_date, end_date, total_return, results, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (user_id, period_days, start_date, end_date,
                 float(total_return or 0),
                 json.dumps(results or [], ensure_ascii=False), created),
            )
            vid = cur.lastrowid
        except Exception as exc:
            logger.warning(f"db_cache.add_watch_verification failed: {exc}")
            return None
    row = _conn().execute(
        "SELECT * FROM watchlist_verifications WHERE id=?", (vid,)
    ).fetchone()
    return _row_to_verif(row) if row else None


def get_watch_verifications(user_id: str) -> list[dict]:
    try:
        rows = _conn().execute(
            "SELECT * FROM watchlist_verifications WHERE user_id=? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.get_watch_verifications failed: {exc}")
        return []
    return [_row_to_verif(r) for r in rows]


def delete_watch_verification(user_id: str, vid: int) -> bool:
    with _write_lock:
        try:
            cur = _conn().execute(
                "DELETE FROM watchlist_verifications WHERE user_id=? AND id=?",
                (user_id, vid),
            )
            return (cur.rowcount or 0) > 0
        except Exception as exc:
            logger.debug(f"db_cache.delete_watch_verification failed: {exc}")
            return False


# ---------------------------------------------------------------------------
# Stock research reports (机构研报，东财 reportapi → 本地缓存)
# ---------------------------------------------------------------------------

_REPORT_COLS = [
    "info_code", "code", "title", "org", "rating", "rating_change",
    "publish_date", "target_price",
    "eps_this", "pe_this", "eps_next", "pe_next", "eps_next2", "pe_next2",
]


def _row_to_report(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in _REPORT_COLS}


def reports_upsert_many(rows: list[dict]) -> int:
    """Bulk-upsert research reports (keyed by ``info_code``)."""
    now = _now_iso()
    tuples = []
    for r in rows:
        ic = r.get("info_code")
        if not ic:
            continue
        tuples.append(tuple(r.get(c) for c in _REPORT_COLS) + (now,))
    if not tuples:
        return 0
    cols = ", ".join(_REPORT_COLS) + ", updated_at"
    placeholders = ", ".join(["?"] * (len(_REPORT_COLS) + 1))
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in _REPORT_COLS if c != "info_code")
    sql = (f"INSERT INTO stock_reports({cols}) VALUES({placeholders}) "
           f"ON CONFLICT(info_code) DO UPDATE SET {update_clause}, updated_at = excluded.updated_at")
    with _write_lock:
        conn = _conn()
        try:
            conn.execute("BEGIN")
            conn.executemany(sql, tuples)
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning(f"db_cache.reports_upsert_many failed: {exc}")
            return 0
    return len(tuples)


def reports_get(code: str, limit: int = 60) -> list[dict]:
    """Stored reports for a code, newest first."""
    try:
        rows = _conn().execute(
            "SELECT * FROM stock_reports WHERE code=? ORDER BY publish_date DESC LIMIT ?",
            (code, int(limit)),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.reports_get({code!r}) failed: {exc}")
        return []
    return [_row_to_report(r) for r in rows]


def reports_count(code: str) -> int:
    try:
        return _conn().execute(
            "SELECT COUNT(*) AS c FROM stock_reports WHERE code=?", (code,)
        ).fetchone()["c"]
    except Exception:
        return 0


def reports_latest_fetch_age(code: str) -> float | None:
    """Seconds since this code's reports were last refreshed (None if never)."""
    try:
        row = _conn().execute(
            "SELECT MAX(updated_at) AS m FROM stock_reports WHERE code=?", (code,)
        ).fetchone()
    except Exception:
        return None
    ts = _parse_iso(row["m"]) if row and row["m"] else None
    return (datetime.now() - ts).total_seconds() if ts else None


def reports_summary(code: str) -> dict:
    """Compact summary for display: 篇数 / 最新日期 / 评级分布 / 最新一致预期。"""
    reps = reports_get(code, limit=60)
    if not reps:
        return {"count": 0, "ratings": {}, "latest_date": None}
    ratings: dict[str, int] = {}
    # 注意：本模块定义了同名的 ``set()`` 缓存函数，遮蔽了内建 ``set``，
    # 直接 ``set()`` 会误调用它并抛 TypeError（吞在上层 except 里会让本函数静默失败）。
    # 故用 list 收集 + 集合字面量去重。
    org_names: list[str] = []
    for r in reps:
        rt = (r.get("rating") or "").strip()
        if rt:
            ratings[rt] = ratings.get(rt, 0) + 1
        og = (r.get("org") or "").strip()
        if og:
            org_names.append(og)

    # 目标价聚合：取近 6 个月内研报的有效目标价，给出一致(均值)/最高/最低/家数。
    import datetime as _dt
    cutoff = (_dt.date.today() - _dt.timedelta(days=180)).isoformat()
    targets: list[float] = []
    for r in reps:
        pd_ = (r.get("publish_date") or "")[:10]
        if pd_ and pd_ < cutoff:
            continue
        tp = r.get("target_price")
        try:
            tpf = float(tp)
        except (TypeError, ValueError):
            continue
        if tpf > 0:
            targets.append(tpf)
    target_block = None
    if targets:
        target_block = {
            "avg":  round(sum(targets) / len(targets), 2),
            "high": round(max(targets), 2),
            "low":  round(min(targets), 2),
            "count": len(targets),
        }

    latest = reps[0]
    return {
        "count": len(reps),
        "org_count": len({*org_names}),
        "latest_date": latest.get("publish_date"),
        "ratings": ratings,
        "top_rating": max(ratings.items(), key=lambda kv: kv[1])[0] if ratings else None,
        "target": target_block,
        "eps_this": latest.get("eps_this"), "pe_this": latest.get("pe_this"),
        "eps_next": latest.get("eps_next"), "pe_next": latest.get("pe_next"),
        "eps_next2": latest.get("eps_next2"), "pe_next2": latest.get("pe_next2"),
    }


def reports_summary_many(codes: list[str]) -> dict[str, dict]:
    """{code: {count, latest_date, top_rating}} for a set of codes (watchlist badge)."""
    codes = [str(c) for c in (codes or []) if c]
    if not codes:
        return {}
    out: dict[str, dict] = {}
    conn = _conn()
    for i in range(0, len(codes), 500):
        chunk = codes[i:i + 500]
        ph = ", ".join(["?"] * len(chunk))
        try:
            rows = conn.execute(
                f"""SELECT code, COUNT(*) AS count, MAX(publish_date) AS latest_date
                    FROM stock_reports WHERE code IN ({ph}) GROUP BY code""",
                chunk,
            ).fetchall()
        except Exception:
            continue
        for r in rows:
            out[r["code"]] = {"count": r["count"], "latest_date": r["latest_date"]}
    return out


def reports_global_latest_date() -> str | None:
    """全市场已入库个股研报的最新 publish_date（YYYY-MM-DD），库空时 None。

    全量/增量同步用它判断「该从哪天开始补」：每日增量只需从这天回拉几天。
    """
    try:
        row = _conn().execute(
            "SELECT MAX(publish_date) AS m FROM stock_reports"
        ).fetchone()
    except Exception:
        return None
    return (row["m"] or None) if row else None


def reports_total_count() -> int:
    """全库个股研报总篇数（用于判断是否已做过全量首灌）。"""
    try:
        return _conn().execute("SELECT COUNT(*) AS c FROM stock_reports").fetchone()["c"]
    except Exception:
        return 0


def reports_list(page: int = 1, page_size: int = 30, search: str | None = None,
                 days: int | None = None, rating: str | None = None) -> dict:
    """全市场个股研报分页浏览（newest first）。返回 {items, total, page, page_size}。

    供「研报」板块通览全库使用：search 命中标题/机构/代码任一即收录；
    days 给定时只取近 N 天；rating 精确匹配评级。
    """
    where: list[str] = []
    params: list = []
    if search and search.strip():
        like = f"%{search.strip()}%"
        where.append("(title LIKE ? OR org LIKE ? OR code LIKE ?)")
        params.extend([like, like, like])
    if days:
        cutoff = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")
        where.append("publish_date >= ?")
        params.append(cutoff)
    if rating and rating.strip():
        where.append("rating = ?")
        params.append(rating.strip())
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 30), 100))
    try:
        total = _conn().execute(
            f"SELECT COUNT(*) AS c FROM stock_reports {wsql}", params).fetchone()["c"]
        rows = _conn().execute(
            f"SELECT * FROM stock_reports {wsql} "
            f"ORDER BY publish_date DESC, updated_at DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.reports_list failed: {exc}")
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    return {"items": [_row_to_report(r) for r in rows], "total": total,
            "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# industry_reports table — 行业/策略研报（无个股归属）
# ---------------------------------------------------------------------------

_INDREPORT_COLS = [
    "info_code", "industry_code", "industry_name", "title",
    "org", "rating", "publish_date",
]


def _row_to_indreport(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in _INDREPORT_COLS}


def industry_reports_upsert_many(rows: list[dict]) -> int:
    """Bulk-upsert industry reports (keyed by ``info_code``)."""
    now = _now_iso()
    tuples = []
    for r in rows:
        if not r.get("info_code"):
            continue
        tuples.append(tuple(r.get(c) for c in _INDREPORT_COLS) + (now,))
    if not tuples:
        return 0
    cols = ", ".join(_INDREPORT_COLS) + ", updated_at"
    placeholders = ", ".join(["?"] * (len(_INDREPORT_COLS) + 1))
    update_clause = ", ".join(
        f"{c} = excluded.{c}" for c in _INDREPORT_COLS if c != "info_code")
    sql = (f"INSERT INTO industry_reports({cols}) VALUES({placeholders}) "
           f"ON CONFLICT(info_code) DO UPDATE SET {update_clause}, updated_at = excluded.updated_at")
    with _write_lock:
        conn = _conn()
        try:
            conn.execute("BEGIN")
            conn.executemany(sql, tuples)
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning(f"db_cache.industry_reports_upsert_many failed: {exc}")
            return 0
    return len(tuples)


def industry_reports_search(terms: list[str], begin_date: str | None = None,
                            limit: int = 600) -> list[dict]:
    """按行业名/标题包含任一关键词检索行业研报（newest first）。

    terms 命中其一即收录；begin_date 给定时只取该日期之后的。供产业链精读读库用。
    """
    terms = [str(t).strip() for t in (terms or []) if str(t).strip()]
    if not terms:
        return []
    where = ["(" + " OR ".join(["industry_name LIKE ? OR title LIKE ?"] * len(terms)) + ")"]
    params: list = []
    for t in terms:
        like = f"%{t}%"
        params.extend([like, like])
    if begin_date:
        where.append("publish_date >= ?")
        params.append(begin_date)
    sql = (f"SELECT * FROM industry_reports WHERE {' AND '.join(where)} "
           f"ORDER BY publish_date DESC LIMIT ?")
    params.append(int(limit))
    try:
        rows = _conn().execute(sql, params).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.industry_reports_search failed: {exc}")
        return []
    return [_row_to_indreport(r) for r in rows]


def industry_reports_latest_date() -> str | None:
    """已入库行业研报的最新 publish_date（YYYY-MM-DD），库空时 None。"""
    try:
        row = _conn().execute(
            "SELECT MAX(publish_date) AS m FROM industry_reports"
        ).fetchone()
    except Exception:
        return None
    return (row["m"] or None) if row else None


def industry_reports_total_count() -> int:
    try:
        return _conn().execute(
            "SELECT COUNT(*) AS c FROM industry_reports").fetchone()["c"]
    except Exception:
        return 0


def industry_reports_list(page: int = 1, page_size: int = 30, search: str | None = None,
                          days: int | None = None) -> dict:
    """全市场行业/策略研报分页浏览（newest first）。返回 {items, total, page, page_size}。"""
    where: list[str] = []
    params: list = []
    if search and search.strip():
        like = f"%{search.strip()}%"
        where.append("(title LIKE ? OR org LIKE ? OR industry_name LIKE ?)")
        params.extend([like, like, like])
    if days:
        cutoff = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")
        where.append("publish_date >= ?")
        params.append(cutoff)
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 30), 100))
    try:
        total = _conn().execute(
            f"SELECT COUNT(*) AS c FROM industry_reports {wsql}", params).fetchone()["c"]
        rows = _conn().execute(
            f"SELECT * FROM industry_reports {wsql} "
            f"ORDER BY publish_date DESC, updated_at DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.industry_reports_list failed: {exc}")
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    return {"items": [_row_to_indreport(r) for r in rows], "total": total,
            "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# research_pdfs table — 下载并抽取后的研报 PDF 库（持久化正文）
# ---------------------------------------------------------------------------

_RPDF_COLS = [
    "info_code", "code", "title", "org", "publish_date",
    "chars", "text", "has_pdf", "downloaded_at",
]


def research_pdf_upsert_many(rows: list[dict]) -> int:
    """Bulk-upsert downloaded/extracted research PDFs (keyed by ``info_code``)."""
    now = _now_iso()
    tuples = []
    for r in rows:
        ic = r.get("info_code")
        if not ic:
            continue
        tuples.append((
            str(ic), r.get("code", "") or "", r.get("title", "") or "",
            r.get("org", "") or "", r.get("publish_date", "") or "",
            int(r.get("chars") or 0), r.get("text", "") or "",
            1 if r.get("has_pdf") else 0, r.get("downloaded_at") or now,
        ))
    if not tuples:
        return 0
    cols = ", ".join(_RPDF_COLS)
    placeholders = ", ".join(["?"] * len(_RPDF_COLS))
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in _RPDF_COLS if c != "info_code")
    sql = (f"INSERT INTO research_pdfs({cols}) VALUES({placeholders}) "
           f"ON CONFLICT(info_code) DO UPDATE SET {update_clause}")
    with _write_lock:
        conn = _conn()
        try:
            conn.execute("BEGIN")
            conn.executemany(sql, tuples)
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning(f"db_cache.research_pdf_upsert_many failed: {exc}")
            return 0
    return len(tuples)


def research_pdf_get_text(info_code: str) -> str | None:
    """已抽取正文（前端「查看精读」/ 增量复用）。"""
    try:
        row = _conn().execute(
            "SELECT text FROM research_pdfs WHERE info_code=?", (str(info_code),)
        ).fetchone()
    except Exception:
        return None
    return row["text"] if row and row["text"] else None


def research_pdf_have_codes(info_codes: list[str]) -> set[str]:
    """已成功抽取正文(text 非空)的 info_code 集合 — 供下载/精读增量跳过。

    注意：本模块定义了同名的 ``set()`` 缓存函数，遮蔽了内建 ``set``，
    故此处用集合推导式构造，避免误调用。
    """
    codes = [str(c) for c in (info_codes or []) if c]
    found: list[str] = []
    conn = _conn()
    for i in range(0, len(codes), 500):
        chunk = codes[i:i + 500]
        ph = ", ".join(["?"] * len(chunk))
        try:
            rows = conn.execute(
                f"SELECT info_code FROM research_pdfs "
                f"WHERE info_code IN ({ph}) AND text IS NOT NULL AND text != ''",
                chunk,
            ).fetchall()
        except Exception:
            continue
        found.extend(r["info_code"] for r in rows)
    return {x for x in found}


def research_pdf_count() -> int:
    try:
        return _conn().execute("SELECT COUNT(*) AS c FROM research_pdfs").fetchone()["c"]
    except Exception:
        return 0


_RPDF_SORT_COLS = {"date": "publish_date", "chars": "chars", "downloaded": "downloaded_at"}


def research_pdf_query(
    *,
    q: str | None = None,
    code: str | None = None,
    org: str | None = None,
    start: str | None = None,
    end: str | None = None,
    has_text: bool = False,
    sort_by: str = "date",
    order: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    """检索研报库：标题/机构/代码模糊 + 日期区间 + 排序 + 分页。

    返回 ``(rows, total)``；列表项不含全文，仅含 120 字预览（全文走 report-text）。
    """
    col = _RPDF_SORT_COLS.get(sort_by, "publish_date")
    direction = "DESC" if (order or "").lower() == "desc" else "ASC"

    clauses: list[str] = []
    params: list[Any] = []
    qs = (q or "").strip()
    if qs:
        clauses.append("(title LIKE ? OR org LIKE ? OR code LIKE ?)")
        like = f"%{qs}%"
        params += [like, like, like]
    if code:
        clauses.append("code = ?")
        params.append(str(code).strip())
    if org:
        clauses.append("org LIKE ?")
        params.append(f"%{org.strip()}%")
    if start:
        clauses.append("publish_date >= ?")
        params.append(start.strip())
    if end:
        clauses.append("publish_date <= ?")
        params.append(end.strip())
    if has_text:
        clauses.append("text IS NOT NULL AND text != ''")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    offset = (page - 1) * page_size

    conn = _conn()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM research_pdfs {where}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"""SELECT info_code, code, title, org, publish_date, chars, has_pdf,
                       downloaded_at, substr(text, 1, 120) AS preview
                FROM research_pdfs {where}
                ORDER BY ({col} IS NULL), {col} {direction}
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.research_pdf_query failed: {exc}")
        return [], 0
    return [dict(r) for r in rows], int(total)


def research_pdf_stats() -> dict:
    """研报库概览：总数 / 已抽取数 / 日期区间 / Top 机构。"""
    conn = _conn()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM research_pdfs").fetchone()["c"]
        with_text = conn.execute(
            "SELECT COUNT(*) AS c FROM research_pdfs WHERE text IS NOT NULL AND text != ''"
        ).fetchone()["c"]
        rng = conn.execute(
            "SELECT MIN(publish_date) AS f, MAX(publish_date) AS t FROM research_pdfs "
            "WHERE publish_date != ''"
        ).fetchone()
        orgs = conn.execute(
            """SELECT org, COUNT(*) AS c FROM research_pdfs
               WHERE org != '' GROUP BY org ORDER BY c DESC LIMIT 12"""
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.research_pdf_stats failed: {exc}")
        return {"total": 0, "with_text": 0, "date_from": None, "date_to": None, "top_orgs": []}
    return {
        "total": int(total),
        "with_text": int(with_text),
        "date_from": rng["f"] if rng else None,
        "date_to": rng["t"] if rng else None,
        "top_orgs": [{"org": r["org"], "count": r["c"]} for r in orgs],
    }


# ---------------------------------------------------------------------------
# report_facts table — 研报 MAP 抽取结果全局缓存（按 infoCode 复用，只升不降）
# ---------------------------------------------------------------------------
# 产业链研报「MAP 阶段」逐篇 LLM 抽取很耗 token。这里按 infoCode 主键落最优一份，
# 跨主题/跨轮复用：记录抽取模型(model)、质量分级(model_tier)、prompt 版本与正文
# hash。upsert 走「只升不降」——更优模型的旧结果不会被低质模型覆盖，仅当版本/正文
# 变了或新模型不更差时才覆盖（见 report_facts_upsert_many）。

_FACT_COLS = [
    "info_code", "fact_json", "model", "model_tier", "prompt_version",
    "text_hash", "updated_at",
]


def report_facts_get_many(info_codes: list[str]) -> dict[str, dict]:
    """批量按 info_code 主键查 MAP 抽取结果（空列表返回 {}）。

    返回 ``{info_code: {"fact": <已 json.loads 的 dict>, "model": str,
    "model_tier": int, "prompt_version": str, "text_hash": str, "updated_at": str}}``。
    fact_json 解析失败的行跳过（不抛）。IN 参数量大时分批（每 500 个一批），
    info_codes 可能上千。
    """
    codes = [str(c) for c in (info_codes or []) if c]
    if not codes:
        return {}
    out: dict[str, dict] = {}
    conn = _conn()
    for i in range(0, len(codes), 500):
        chunk = codes[i:i + 500]
        ph = ", ".join(["?"] * len(chunk))
        try:
            rows = conn.execute(
                f"SELECT * FROM report_facts WHERE info_code IN ({ph})", chunk
            ).fetchall()
        except Exception as exc:
            logger.debug(f"db_cache.report_facts_get_many failed: {exc}")
            continue
        for r in rows:
            try:
                fact = json.loads(r["fact_json"])
            except Exception:
                # 坏 JSON 行跳过，不影响其余命中
                continue
            out[r["info_code"]] = {
                "fact": fact,
                "model": r["model"],
                "model_tier": int(r["model_tier"] or 0),
                "prompt_version": r["prompt_version"],
                "text_hash": r["text_hash"],
                "updated_at": r["updated_at"],
            }
    return out


def report_facts_upsert_many(rows: list[dict]) -> int:
    """Bulk-upsert MAP 抽取结果（keyed by ``info_code``），**只升不降**。

    每个 row：``{"info_code": str, "fact": dict, "model": str,
    "model_tier": int, "prompt_version": str, "text_hash": str}``。fact 是 dict，
    函数内 ``json.dumps(ensure_ascii=False)`` 存入 fact_json；无 info_code 的 row 跳过。

    只升不降语义：仅当版本不同、或新模型不更差(model_tier >=)时才覆盖，否则保留原行。
    text_hash **不参与**写回判断：hash 漂移（PDF 重提取、格式差异）不允许低质模型覆盖高质
    模型的结果；正文口径升级请 bump _MAP_PROMPT_VERSION 触发强制重抽。返回写入/更新行数（近似）。
    """
    now = datetime.now().isoformat(timespec="seconds")
    tuples = []
    for r in rows:
        ic = r.get("info_code")
        if not ic:
            continue
        fact = r.get("fact")
        tuples.append((
            str(ic),
            json.dumps(fact, ensure_ascii=False),
            r.get("model"),
            int(r.get("model_tier") or 0),
            r.get("prompt_version"),
            r.get("text_hash"),
            now,
        ))
    if not tuples:
        return 0
    cols = ", ".join(_FACT_COLS)
    placeholders = ", ".join(["?"] * len(_FACT_COLS))
    update_cols = [c for c in _FACT_COLS if c != "info_code"]
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
    sql = (
        f"INSERT INTO report_facts({cols}) VALUES({placeholders}) "
        f"ON CONFLICT(info_code) DO UPDATE SET {update_clause} "
        # 只升不降：版本变了（口径升级）或新模型质量 >= 旧模型，才覆盖。
        # text_hash 不参与写回判定——hash 轻微漂移（PDF 重提取排版差异）不允许
        # 低质量模型（minimax）趁机覆盖高质量模型（opus）的抽取结果。
        "WHERE excluded.prompt_version IS NOT report_facts.prompt_version "
        "OR excluded.model_tier >= report_facts.model_tier"
    )
    written = 0
    with _write_lock:
        conn = _conn()
        try:
            conn.execute("BEGIN")
            for t in tuples:
                cur = conn.execute(sql, t)
                written += cur.rowcount or 0
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning(f"db_cache.report_facts_upsert_many failed: {exc}")
            return 0
    return written


def report_facts_purge(ttl_days: int = 400) -> int:
    """删除 updated_at 早于 now - ttl_days 的行，返回删除行数。

    研报本身一年滚动，facts 同步过期（默认 400 天，略宽于一年）。
    """
    cutoff = (datetime.now() - timedelta(days=ttl_days)).isoformat(timespec="seconds")
    with _write_lock:
        try:
            cur = _conn().execute(
                "DELETE FROM report_facts WHERE updated_at IS NOT NULL AND updated_at < ?",
                (cutoff,),
            )
            return cur.rowcount or 0
        except Exception as exc:
            logger.debug(f"db_cache.report_facts_purge failed: {exc}")
            return 0


def report_facts_stats() -> dict:
    """MAP 抽取缓存的模型分布：总篇数 + 按模型分组（篇数/质量分/最新时间）。

    供管理后台可视化「多少篇研报由哪个模型读过」。model 为空的归到「未知」。
    """
    conn = _conn()
    try:
        total = conn.execute("SELECT COUNT(*) AS n FROM report_facts").fetchone()["n"]
        rows = conn.execute(
            "SELECT model, MAX(model_tier) AS tier, COUNT(*) AS cnt, "
            "MAX(updated_at) AS latest FROM report_facts "
            "GROUP BY model ORDER BY cnt DESC"
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.report_facts_stats failed: {exc}")
        return {"total": 0, "by_model": []}
    by_model = [
        {"model": r["model"] or "未知", "model_tier": int(r["tier"] or 0),
         "count": int(r["cnt"] or 0), "latest": r["latest"]}
        for r in rows
    ]
    return {"total": int(total or 0), "by_model": by_model}


# ---------------------------------------------------------------------------
# app_config — durable key/value (survives cache clear_all)
# ---------------------------------------------------------------------------

def app_config_get(key: str, default: str | None = None) -> str | None:
    try:
        row = _conn().execute(
            "SELECT value FROM app_config WHERE key=?", (key,)
        ).fetchone()
    except Exception:
        return default
    return row["value"] if row and row["value"] is not None else default


def app_config_set(key: str, value: str | None) -> None:
    with _write_lock:
        try:
            _conn().execute(
                """INSERT INTO app_config(key, value, updated_at) VALUES(?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                                  updated_at=excluded.updated_at""",
                (key, value, _now_iso()),
            )
        except Exception as exc:
            logger.warning(f"db_cache.app_config_set({key!r}) failed: {exc}")


def app_config_prefix(prefix: str) -> dict[str, str]:
    """返回所有 key 以 ``prefix`` 开头的 {key: value}。用于跨 worker 枚举共享状态
    （如研报分析进度 ``research:job:*``）。"""
    try:
        rows = _conn().execute(
            "SELECT key, value FROM app_config WHERE key LIKE ? ESCAPE '\\'",
            (prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
        ).fetchall()
    except Exception:
        return {}
    return {r["key"]: r["value"] for r in rows if r["value"] is not None}


def app_config_delete(key: str) -> None:
    with _write_lock:
        try:
            _conn().execute("DELETE FROM app_config WHERE key=?", (key,))
        except Exception as exc:
            logger.warning(f"db_cache.app_config_delete({key!r}) failed: {exc}")


# ---------------------------------------------------------------------------
# blog_posts — 知识星球抓取库
# ---------------------------------------------------------------------------

_BLOG_COLS = [
    "post_id", "group_id", "author", "title", "ai_title", "content_html", "content_text",
    "images", "youdao", "created_at",
]


def _row_to_blog(row: sqlite3.Row, *, with_body: bool = True) -> dict:
    try:
        images = json.loads(row["images"]) if row["images"] else []
    except Exception:
        images = []
    try:
        youdao = json.loads(row["youdao"]) if row["youdao"] else []
    except Exception:
        youdao = []
    d = {
        "post_id": row["post_id"],
        "group_id": row["group_id"],
        "author": row["author"],
        "title": row["title"],
        "ai_title": (row["ai_title"] if "ai_title" in row.keys() else "") or "",
        "images": images,
        "youdao": youdao,
        "created_at": row["created_at"],
        "fetched_at": row["fetched_at"],
    }
    if with_body:
        d["content_html"] = row["content_html"]
        d["content_text"] = row["content_text"]
    else:
        txt = row["content_text"] or ""
        d["preview"] = txt[:160]
        d["has_youdao"] = bool(youdao)
    return d


def blog_upsert_many(rows: list[dict]) -> int:
    """Bulk-upsert blog posts (keyed by ``post_id``). Overwrites existing rows
    so re-crawled posts pick up newly-fetched Youdao content."""
    now = _now_iso()
    tuples = []
    for r in rows:
        pid = r.get("post_id")
        if not pid:
            continue
        tuples.append((
            str(pid), r.get("group_id", ""), r.get("author", ""),
            r.get("title", ""), r.get("ai_title", "") or "",
            r.get("content_html", ""), r.get("content_text", ""),
            json.dumps(r.get("images") or [], ensure_ascii=False),
            json.dumps(r.get("youdao") or [], ensure_ascii=False),
            r.get("created_at", ""), now,
        ))
    if not tuples:
        return 0
    cols = ", ".join(_BLOG_COLS) + ", fetched_at"
    placeholders = ", ".join(["?"] * (len(_BLOG_COLS) + 1))
    # ai_title 特殊处理：空值不覆盖已有标题（重抓帖子时别把已生成的 AI 标题擦掉）。
    def _upd(c: str) -> str:
        if c == "ai_title":
            return "ai_title = COALESCE(NULLIF(excluded.ai_title, ''), blog_posts.ai_title)"
        return f"{c} = excluded.{c}"
    update_clause = ", ".join(_upd(c) for c in _BLOG_COLS if c != "post_id")
    sql = (f"INSERT INTO blog_posts({cols}) VALUES({placeholders}) "
           f"ON CONFLICT(post_id) DO UPDATE SET {update_clause}, fetched_at = excluded.fetched_at")
    with _write_lock:
        conn = _conn()
        try:
            conn.execute("BEGIN")
            conn.executemany(sql, tuples)
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning(f"db_cache.blog_upsert_many failed: {exc}")
            return 0
    return len(tuples)


def blog_existing_ids(post_ids: list[str]) -> set[str]:
    """Subset of ``post_ids`` already stored — lets the crawler skip refetching."""
    ids = [str(p) for p in (post_ids or []) if p]
    found: list[str] = []
    conn = _conn()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ", ".join(["?"] * len(chunk))
        try:
            rows = conn.execute(
                f"SELECT post_id FROM blog_posts WHERE post_id IN ({ph})", chunk
            ).fetchall()
        except Exception:
            continue
        found.extend(r["post_id"] for r in rows)
    return {x for x in found}


def blog_query(
    *, search: str | None = None, group_id: str | None = None,
    page: int = 1, page_size: int = 20
) -> tuple[list[dict], int]:
    """List blog posts (newest first), with optional text search / 星球(group_id) 过滤。
    Returns ``(rows_without_body, total)`` — list items carry only a preview."""
    clauses: list[str] = []
    params: list[Any] = []
    q = (search or "").strip()
    if q:
        clauses.append(
            "(title LIKE ? OR ai_title LIKE ? OR author LIKE ? OR content_text LIKE ?)"
        )
        like = f"%{q}%"
        params += [like, like, like, like]
    gid = (group_id or "").strip()
    if gid:
        clauses.append("group_id = ?")
        params.append(gid)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 100))
    offset = (page - 1) * page_size

    conn = _conn()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM blog_posts {where}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"""SELECT * FROM blog_posts {where}
                ORDER BY (created_at IS NULL), created_at DESC
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.blog_query failed: {exc}")
        return [], 0
    return [_row_to_blog(r, with_body=False) for r in rows], int(total)


def blog_get(post_id: str) -> dict | None:
    try:
        row = _conn().execute(
            "SELECT * FROM blog_posts WHERE post_id=?", (str(post_id),)
        ).fetchone()
    except Exception:
        return None
    return _row_to_blog(row, with_body=True) if row else None


def blog_count() -> int:
    try:
        return _conn().execute("SELECT COUNT(*) AS c FROM blog_posts").fetchone()["c"]
    except Exception:
        return 0


def blog_group_counts() -> list[dict]:
    """按星球(group_id)聚合 [{group_id, count}]，篇数降序。
    星球显示名由路由层用配置补上（db 只存 group_id）。"""
    try:
        rows = _conn().execute(
            """SELECT group_id, COUNT(*) AS count FROM blog_posts
               WHERE group_id IS NOT NULL AND group_id != ''
               GROUP BY group_id ORDER BY count DESC"""
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.blog_group_counts failed: {exc}")
        return []
    return [{"group_id": str(r["group_id"]), "count": int(r["count"])} for r in rows]


def blog_missing_ai_title(limit: int = 500) -> list[dict]:
    """返回尚无 AI 标题的帖子（post_id + content_text），供回填生成标题。"""
    try:
        rows = _conn().execute(
            """SELECT post_id, content_text FROM blog_posts
               WHERE ai_title IS NULL OR ai_title = ''
               ORDER BY created_at DESC LIMIT ?""",
            (int(limit),),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.blog_missing_ai_title failed: {exc}")
        return []
    return [{"post_id": r["post_id"], "content_text": r["content_text"] or ""} for r in rows]


def blog_set_ai_title(post_id: str, ai_title: str) -> bool:
    """单独回写一篇的 AI 标题（不动正文/抓取时间）。"""
    if not post_id or not ai_title:
        return False
    with _write_lock:
        try:
            _conn().execute(
                "UPDATE blog_posts SET ai_title=? WHERE post_id=?",
                (ai_title.strip(), str(post_id)),
            )
            return True
        except Exception as exc:
            logger.debug(f"db_cache.blog_set_ai_title failed: {exc}")
            return False


def blog_latest_fetch() -> str | None:
    try:
        row = _conn().execute("SELECT MAX(fetched_at) AS m FROM blog_posts").fetchone()
        return row["m"] if row else None
    except Exception:
        return None


def blog_posts_search(terms: list[str], begin_date: str | None = None,
                      group_id: str | None = None, limit: int = 400) -> list[dict]:
    """按标题/AI标题/正文包含任一关键词检索机构荐股(调研纪要)博文（newest first）。

    供产业链精读把「机构荐股」里的所有文章一并纳入分析。terms 命中其一即收录；
    begin_date 给定时只取该 created_at 之后的；group_id 给定时限定某星球。
    """
    terms = [str(t).strip() for t in (terms or []) if str(t).strip()]
    if not terms:
        return []
    where = ["(" + " OR ".join(
        ["title LIKE ? OR ai_title LIKE ? OR content_text LIKE ?"] * len(terms)) + ")"]
    params: list = []
    for t in terms:
        like = f"%{t}%"
        params.extend([like, like, like])
    if begin_date:
        where.append("substr(created_at,1,10) >= ?")
        params.append(begin_date)
    if group_id:
        where.append("group_id = ?")
        params.append(str(group_id))
    sql = (f"SELECT post_id, group_id, author, title, ai_title, content_text, created_at "
           f"FROM blog_posts WHERE {' AND '.join(where)} "
           f"ORDER BY created_at DESC LIMIT ?")
    params.append(int(limit))
    try:
        rows = _conn().execute(sql, params).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.blog_posts_search failed: {exc}")
        return []
    return [dict(r) for r in rows]


def blog_oldest_created(group_id: str) -> str | None:
    """返回某星球已入库最早一条的 ``created_at``（供回填可续传：从此处继续往更早翻）。
    无数据返回 None。"""
    if not group_id:
        return None
    try:
        row = _conn().execute(
            "SELECT MIN(created_at) AS m FROM blog_posts WHERE group_id=?",
            (str(group_id),),
        ).fetchone()
        return row["m"] if row and row["m"] else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Feishu message storage
# ---------------------------------------------------------------------------

_FEISHU_MSG_COLS = [
    "message_id", "chat_id", "chat_name", "sender_id", "sender_type",
    "msg_type", "content_text", "content_raw", "created_at",
]


def feishu_upsert_messages(rows: list[dict]) -> int:
    """Bulk-upsert feishu messages (keyed by message_id)."""
    now = _now_iso()
    tuples = []
    for r in rows:
        mid = r.get("message_id")
        if not mid:
            continue
        tuples.append((
            str(mid),
            r.get("chat_id", ""), r.get("chat_name", ""),
            r.get("sender_id", ""), r.get("sender_type", "user"),
            r.get("msg_type", "text"),
            r.get("content_text", ""), r.get("content_raw", ""),
            r.get("created_at", ""), now,
        ))
    if not tuples:
        return 0
    cols = ", ".join(_FEISHU_MSG_COLS) + ", fetched_at"
    placeholders = ", ".join(["?"] * (len(_FEISHU_MSG_COLS) + 1))
    update_clause = ", ".join(
        f"{c} = excluded.{c}" for c in _FEISHU_MSG_COLS if c != "message_id"
    )
    sql = (f"INSERT INTO feishu_messages({cols}) VALUES({placeholders}) "
           f"ON CONFLICT(message_id) DO UPDATE SET {update_clause}, fetched_at = excluded.fetched_at")
    with _write_lock:
        conn = _conn()
        try:
            conn.execute("BEGIN")
            conn.executemany(sql, tuples)
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning(f"db_cache.feishu_upsert_messages failed: {exc}")
            return 0
    return len(tuples)


def feishu_existing_ids(message_ids: list[str]) -> set[str]:
    ids = [str(m) for m in (message_ids or []) if m]
    found: list[str] = []
    conn = _conn()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ", ".join(["?"] * len(chunk))
        try:
            rows = conn.execute(
                f"SELECT message_id FROM feishu_messages WHERE message_id IN ({ph})", chunk
            ).fetchall()
        except Exception:
            continue
        found.extend(r["message_id"] for r in rows)
    # NB: 模块级 ``set()`` 是本文件的缓存写入函数，遮蔽了内建 set —— 用集合推导式规避。
    return {m for m in found}


def _like_escape(s: str) -> str:
    """转义 LIKE 通配符，配合 ESCAPE '\\' 使用（防止 % _ 被当通配）。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def feishu_query(
    *, search: str | None = None, chat_id: str | None = None,
    content_prefixes: list[str] | None = None,
    page: int = 1, page_size: int = 50
) -> tuple[list[dict], int]:
    """List feishu messages newest first, with optional text/chat filter.

    ``content_prefixes`` —— 正文须以其中**任一**前缀开头（OR；如震哥群「3：」「3:」），
    与搜索/群过滤取交集（AND）。空则不限。
    """
    clauses: list[str] = []
    params: list[Any] = []
    q = (search or "").strip()
    if q:
        clauses.append("(content_text LIKE ? OR chat_name LIKE ?)")
        like = f"%{q}%"
        params += [like, like]
    if chat_id:
        clauses.append("chat_id = ?")
        params.append(chat_id)
    prefixes = [p for p in (content_prefixes or []) if p]
    if prefixes:
        ors = " OR ".join(["content_text LIKE ? ESCAPE '\\'"] * len(prefixes))
        clauses.append(f"({ors})")
        params += [f"{_like_escape(p)}%" for p in prefixes]
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    conn = _conn()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM feishu_messages {where}", params
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT message_id, chat_id, chat_name, sender_id, sender_type, msg_type, "
            f"content_text, created_at, fetched_at "
            f"FROM feishu_messages {where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
    except Exception as exc:
        logger.warning(f"db_cache.feishu_query failed: {exc}")
        return [], 0
    return [dict(r) for r in rows], total


def feishu_message_count() -> int:
    try:
        return _conn().execute("SELECT COUNT(*) FROM feishu_messages").fetchone()[0]
    except Exception:
        return 0


def feishu_latest_fetch() -> str | None:
    try:
        row = _conn().execute(
            "SELECT MAX(fetched_at) AS m FROM feishu_messages"
        ).fetchone()
        return row["m"] if row else None
    except Exception:
        return None


def feishu_upsert_chats(chats: list[dict]) -> None:
    """全量覆盖群列表缓存。"""
    now = _now_iso()
    tuples = [(c["chat_id"], c.get("name", ""), c.get("description", ""),
               c.get("avatar", ""), c.get("chat_type", ""), now)
              for c in chats if c.get("chat_id")]
    if not tuples:
        return
    with _write_lock:
        conn = _conn()
        try:
            conn.execute("BEGIN")
            conn.executemany(
                "INSERT INTO feishu_chats(chat_id,name,description,avatar,chat_type,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET "
                "name=excluded.name, description=excluded.description, "
                "avatar=excluded.avatar, chat_type=excluded.chat_type, updated_at=excluded.updated_at",
                tuples,
            )
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning(f"db_cache.feishu_upsert_chats failed: {exc}")


def feishu_list_chats() -> list[dict]:
    try:
        rows = _conn().execute(
            "SELECT chat_id, name, description, avatar, chat_type, updated_at "
            "FROM feishu_chats ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def feishu_latest_msg_time(chat_id: str) -> str | None:
    """最新一条消息的 created_at（用于增量拉取起点）。"""
    try:
        row = _conn().execute(
            "SELECT MAX(created_at) AS m FROM feishu_messages WHERE chat_id=?",
            (chat_id,),
        ).fetchone()
        return row["m"] if row and row["m"] else None
    except Exception:
        return None


def feishu_window_messages(
    chat_id: str, start_iso: str, end_iso: str,
    content_prefixes: list[str] | None = None,
) -> list[dict]:
    """取某群在 [start_iso, end_iso) 时间窗内的消息（升序，供汇总用）。

    ``content_prefixes`` —— 正文须以其中任一前缀开头（震哥群「3：」「3:」），空则不限。
    """
    clauses = ["chat_id = ?", "created_at >= ?", "created_at < ?"]
    params: list[Any] = [chat_id, start_iso, end_iso]
    prefixes = [p for p in (content_prefixes or []) if p]
    if prefixes:
        ors = " OR ".join(["content_text LIKE ? ESCAPE '\\'"] * len(prefixes))
        clauses.append(f"({ors})")
        params += [f"{_like_escape(p)}%" for p in prefixes]
    where = " AND ".join(clauses)
    try:
        rows = _conn().execute(
            f"SELECT message_id, chat_id, chat_name, sender_type, msg_type, "
            f"content_text, created_at FROM feishu_messages WHERE {where} "
            f"ORDER BY created_at ASC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning(f"db_cache.feishu_window_messages failed: {exc}")
        return []


def feishu_summary_upsert(day: str, window_start: str, window_end: str,
                          summary: str, msg_count: int) -> None:
    """落库某日四群汇总（同日覆盖）。"""
    now = _now_iso()
    with _write_lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO feishu_daily_summary"
                "(day, window_start, window_end, summary, msg_count, generated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(day) DO UPDATE SET "
                "window_start=excluded.window_start, window_end=excluded.window_end, "
                "summary=excluded.summary, msg_count=excluded.msg_count, "
                "generated_at=excluded.generated_at",
                (day, window_start, window_end, summary, int(msg_count), now),
            )
        except Exception as exc:
            logger.warning(f"db_cache.feishu_summary_upsert failed: {exc}")


def feishu_summary_get(day: str) -> dict | None:
    try:
        row = _conn().execute(
            "SELECT day, window_start, window_end, summary, msg_count, generated_at "
            "FROM feishu_daily_summary WHERE day=?",
            (day,),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def feishu_summary_list(limit: int = 60) -> list[dict]:
    """汇总历史日期列表（新到旧，不含正文）。"""
    try:
        rows = _conn().execute(
            "SELECT day, window_start, window_end, msg_count, generated_at "
            "FROM feishu_daily_summary ORDER BY day DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Optional: one-shot migration from legacy JSON caches
# ---------------------------------------------------------------------------

_OLD_DIRS = [
    Path("data/cache/sector"),
    Path("data/cache/news"),
    Path("data/cache/ai_picks"),
    Path("data/cache/intraday"),
]


def migrate_legacy_json_files() -> dict:
    """Best-effort: load old ``.json`` cache files into the SQLite store.

    Run once at startup.  After that, modules write only to SQLite.  Returns a
    small report of how many entries were migrated per category.
    """
    report: dict[str, int] = {}
    category_by_dir = {
        Path("data/cache/sector"): "sector",
        Path("data/cache/news"): "news",
        Path("data/cache/ai_picks"): "ai_picks",
        Path("data/cache/intraday"): "market_intraday",
    }
    for old_dir in _OLD_DIRS:
        if not old_dir.exists():
            continue
        cat = category_by_dir.get(old_dir, "legacy")
        migrated = 0
        for f in old_dir.rglob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            ts = data.get("_cached_at") or data.get("fetched_at") or data.get("generated_at")
            key = f"{cat}:{f.relative_to(old_dir).as_posix().rstrip('.json')}"
            # If there's already a newer entry for this key, skip.
            existing = get_stale(key)
            if existing is not None:
                continue
            set(key, data, ttl_seconds=600, category=cat)
            migrated += 1
        report[cat] = report.get(cat, 0) + migrated
        if migrated:
            logger.info(f"db_cache: migrated {migrated} {cat} entries from {old_dir}")
    return report


# ---------------------------------------------------------------------------
# Activity log — DAU / 功能热度 / 用户最近活跃 / 留存（管理后台用）
# ---------------------------------------------------------------------------
#
# 写入由 app.py 的全局中间件负责（每个带 token 的 API 请求一条）。聚合查询全部
# SQL 侧完成，避免把成千上万条 raw row 拉进 Python。所有读写都 best-effort：
# 任何异常都吞掉并返回空，活跃统计绝不能拖垮正常请求。


def log_activity(user_id: str | None, username: str | None, feature: str,
                 method: str, path: str) -> None:
    """记一条活跃事件。匿名请求（无 token）由中间件直接跳过，不会进到这里。"""
    now = datetime.now()
    with _write_lock:
        try:
            _conn().execute(
                "INSERT INTO activity_log(user_id, username, day, ts, feature, method, path) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (user_id or "", username or "", now.strftime("%Y-%m-%d"),
                 now.isoformat(timespec="seconds"), feature, method, path),
            )
        except Exception as exc:
            logger.debug(f"db_cache.log_activity failed: {exc}")


def prune_activity(keep_days: int = 90) -> int:
    """裁剪超过 keep_days 天的活跃记录，返回删除条数。"""
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    with _write_lock:
        try:
            cur = _conn().execute("DELETE FROM activity_log WHERE day < ?", (cutoff,))
            return cur.rowcount or 0
        except Exception as exc:
            logger.debug(f"db_cache.prune_activity failed: {exc}")
            return 0


def activity_dau_series(days: int = 30) -> list[dict]:
    """近 days 天每日活跃用户数 / 事件数。返回按日升序、零活跃日补 0 的完整序列。"""
    start = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    counts: dict[str, dict] = {}
    try:
        rows = _conn().execute(
            "SELECT day, COUNT(DISTINCT username) AS users, COUNT(*) AS events "
            "FROM activity_log WHERE day >= ? AND username != '' GROUP BY day",
            (start,),
        ).fetchall()
        counts = {r["day"]: {"users": r["users"], "events": r["events"]} for r in rows}
    except Exception as exc:
        logger.debug(f"db_cache.activity_dau_series failed: {exc}")
    out = []
    base = datetime.now() - timedelta(days=days - 1)
    for i in range(days):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        c = counts.get(d, {})
        out.append({"day": d, "users": c.get("users", 0), "events": c.get("events", 0)})
    return out


def activity_active_counts() -> dict:
    """今日 / 昨日 / 近 7 日 / 近 30 日活跃用户数（去重账号）。"""
    def _distinct_since(start_day: str, end_day: str | None = None) -> int:
        try:
            if end_day is None:
                row = _conn().execute(
                    "SELECT COUNT(DISTINCT username) AS n FROM activity_log "
                    "WHERE day >= ? AND username != ''", (start_day,),
                ).fetchone()
            else:
                row = _conn().execute(
                    "SELECT COUNT(DISTINCT username) AS n FROM activity_log "
                    "WHERE day = ? AND username != ''", (start_day,),
                ).fetchone()
            return row["n"] if row else 0
        except Exception:
            return 0

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return {
        "dau":  _distinct_since(today, today),
        "yesterday": _distinct_since(yesterday, yesterday),
        "wau":  _distinct_since((datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")),
        "mau":  _distinct_since((datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")),
    }


def activity_feature_counts(days: int = 30) -> list[dict]:
    """近 days 天各功能的事件数 / 去重用户数，按事件数降序。"""
    start = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    try:
        rows = _conn().execute(
            "SELECT feature, COUNT(*) AS events, COUNT(DISTINCT username) AS users "
            "FROM activity_log WHERE day >= ? AND feature != '' "
            "GROUP BY feature ORDER BY events DESC",
            (start,),
        ).fetchall()
        return [{"feature": r["feature"], "events": r["events"], "users": r["users"]} for r in rows]
    except Exception as exc:
        logger.debug(f"db_cache.activity_feature_counts failed: {exc}")
        return []


def activity_user_last_seen() -> dict[str, dict]:
    """{username: {last_seen, days_7, days_30, events_30}}，供后台用户表叠加活跃列。"""
    today = datetime.now().strftime("%Y-%m-%d")
    d7 = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    d30 = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")
    out: dict[str, dict] = {}
    try:
        rows = _conn().execute(
            "SELECT username, MAX(ts) AS last_seen, "
            "COUNT(DISTINCT CASE WHEN day >= ? THEN day END) AS days_7, "
            "COUNT(DISTINCT CASE WHEN day >= ? THEN day END) AS days_30, "
            "SUM(CASE WHEN day >= ? THEN 1 ELSE 0 END) AS events_30 "
            "FROM activity_log WHERE username != '' GROUP BY username",
            (d7, d30, d30),
        ).fetchall()
        for r in rows:
            out[r["username"]] = {
                "last_seen": r["last_seen"],
                "days_7": r["days_7"] or 0,
                "days_30": r["days_30"] or 0,
                "events_30": r["events_30"] or 0,
                "active_today": (r["last_seen"] or "")[:10] == today,
            }
    except Exception as exc:
        logger.debug(f"db_cache.activity_user_last_seen failed: {exc}")
    return out


def activity_retention(cohort_days: int = 14) -> list[dict]:
    """新增/留存：按注册日为队列，统计每日新增用户数与其次日留存。

    新增日取每个 username 在 activity_log 里的**首次活跃日**（首登近似注册）。
    次日留存 = 该队列中在「首活日+1天」仍有活跃的用户占比。
    """
    start = (datetime.now() - timedelta(days=cohort_days - 1)).strftime("%Y-%m-%d")
    try:
        # 每个用户的首次活跃日
        firsts = _conn().execute(
            "SELECT username, MIN(day) AS first_day FROM activity_log "
            "WHERE username != '' GROUP BY username"
        ).fetchall()
        first_day = {r["username"]: r["first_day"] for r in firsts}
        # 每个用户活跃过的日集合（只取队列窗口附近，省内存）
        active_rows = _conn().execute(
            "SELECT DISTINCT username, day FROM activity_log "
            "WHERE username != '' AND day >= ?",
            ((datetime.now() - timedelta(days=cohort_days)).strftime("%Y-%m-%d"),),
        ).fetchall()
    except Exception as exc:
        logger.debug(f"db_cache.activity_retention failed: {exc}")
        return []

    # NB: 模块级 ``set()`` 是本文件的缓存写入函数，遮蔽了内建 set —— 这里用
    # set 字面量 `{...}` 累积 (username, day) 对，避免误调到那个 set。
    active_pairs = {(r["username"], r["day"]) for r in active_rows}

    cohorts: dict[str, dict] = {}
    for user, fd in first_day.items():
        if fd < start:
            continue
        c = cohorts.setdefault(fd, {"new": 0, "retained_d1": 0})
        c["new"] += 1
        next_day = (datetime.strptime(fd, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        if (user, next_day) in active_pairs:
            c["retained_d1"] += 1

    out = []
    base = datetime.now() - timedelta(days=cohort_days - 1)
    for i in range(cohort_days):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        c = cohorts.get(d, {"new": 0, "retained_d1": 0})
        rate = round(c["retained_d1"] / c["new"] * 100, 1) if c["new"] else 0.0
        out.append({"day": d, "new_users": c["new"],
                    "retained_d1": c["retained_d1"], "retention_d1_pct": rate})
    return out


# ── 在线心跳 & 在线时长 ─────────────────────────────────────────────────────────

_ONLINE_TIMEOUT = 90   # 超过此秒数无心跳即视为下线


def heartbeat(username: str) -> dict:
    """记录/更新一次心跳。返回本次会话的在线时长(秒)和是否是新会话。

    逻辑：
    - 若该账号无记录，或距上次心跳超过 _ONLINE_TIMEOUT 秒 → 开新会话
    - 否则累加 (now - last_seen) 到 duration_secs，更新 last_seen
    """
    now = datetime.now()
    now_str = now.isoformat(timespec="seconds")
    with _write_lock:
        try:
            row = _conn().execute(
                "SELECT session_start, last_seen, duration_secs FROM online_sessions WHERE username=?",
                (username,),
            ).fetchone()
            if row is None:
                _conn().execute(
                    "INSERT INTO online_sessions(username, session_start, last_seen, duration_secs) "
                    "VALUES(?,?,?,0)",
                    (username, now_str, now_str),
                )
                return {"username": username, "duration_secs": 0, "new_session": True}

            last = datetime.fromisoformat(row["last_seen"])
            gap = (now - last).total_seconds()
            if gap > _ONLINE_TIMEOUT:
                # 新会话
                _conn().execute(
                    "UPDATE online_sessions SET session_start=?, last_seen=?, duration_secs=0 WHERE username=?",
                    (now_str, now_str, username),
                )
                return {"username": username, "duration_secs": 0, "new_session": True}

            new_dur = int(row["duration_secs"] or 0) + int(gap)
            _conn().execute(
                "UPDATE online_sessions SET last_seen=?, duration_secs=? WHERE username=?",
                (now_str, new_dur, username),
            )
            return {"username": username, "duration_secs": new_dur, "new_session": False}
        except Exception as exc:
            logger.debug(f"db_cache.heartbeat failed: {exc}")
            return {"username": username, "duration_secs": 0, "new_session": False}


def get_online_users(timeout_secs: int = _ONLINE_TIMEOUT) -> list[dict]:
    """返回当前在线用户列表（last_seen 在 timeout_secs 内的账号）。"""
    cutoff = (datetime.now() - timedelta(seconds=timeout_secs)).isoformat(timespec="seconds")
    try:
        rows = _conn().execute(
            "SELECT username, session_start, last_seen, duration_secs "
            "FROM online_sessions WHERE last_seen >= ? ORDER BY last_seen DESC",
            (cutoff,),
        ).fetchall()
        return [
            {
                "username": r["username"],
                "session_start": r["session_start"],
                "last_seen": r["last_seen"],
                "duration_secs": r["duration_secs"] or 0,
                "duration_mins": round((r["duration_secs"] or 0) / 60, 1),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug(f"db_cache.get_online_users failed: {exc}")
        return []


# ── 查询量级与分布 ───────────────────────────────────────────────────────────────

def activity_hourly_distribution(days: int = 7) -> list[dict]:
    """近 days 天按小时统计请求分布（0-23 时），返回 [{hour, events, pct}]。"""
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        rows = _conn().execute(
            "SELECT CAST(strftime('%H', ts) AS INTEGER) AS hour, COUNT(*) AS events "
            "FROM activity_log WHERE day >= ? AND username != '' GROUP BY hour ORDER BY hour",
            (start,),
        ).fetchall()
        counts = {r["hour"]: r["events"] for r in rows}
        total = sum(counts.values()) or 1
        return [
            {"hour": h, "events": counts.get(h, 0), "pct": round(counts.get(h, 0) / total * 100, 1)}
            for h in range(24)
        ]
    except Exception as exc:
        logger.debug(f"db_cache.activity_hourly_distribution failed: {exc}")
        return [{"hour": h, "events": 0, "pct": 0.0} for h in range(24)]


def activity_query_volume(days: int = 30) -> dict:
    """查询量级：总量、日均、峰值日，近7天 vs 前7天环比。"""
    start = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    d7_start = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    d7_prev_start = (datetime.now() - timedelta(days=13)).strftime("%Y-%m-%d")
    d7_prev_end = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        rows = _conn().execute(
            "SELECT day, COUNT(*) AS events FROM activity_log "
            "WHERE day >= ? AND username != '' GROUP BY day",
            (start,),
        ).fetchall()
        by_day = {r["day"]: r["events"] for r in rows}
        total = sum(by_day.values())
        peak = max(by_day.values()) if by_day else 0
        peak_day = max(by_day, key=by_day.get) if by_day else ""
        recent_7 = sum(v for d, v in by_day.items() if d >= d7_start)
        prev_7 = sum(v for d, v in by_day.items() if d7_prev_start <= d <= d7_prev_end)
        return {
            "total": total,
            "daily_avg": round(total / days, 1),
            "peak": peak,
            "peak_day": peak_day,
            "recent_7d": recent_7,
            "prev_7d": prev_7,
            "week_over_week_pct": round((recent_7 - prev_7) / prev_7 * 100, 1) if prev_7 else 0.0,
        }
    except Exception as exc:
        logger.debug(f"db_cache.activity_query_volume failed: {exc}")
        return {"total": 0, "daily_avg": 0, "peak": 0, "peak_day": "",
                "recent_7d": 0, "prev_7d": 0, "week_over_week_pct": 0.0}


# Kick off the migration at import time (one shot; idempotent on re-runs).
try:
    migrate_legacy_json_files()
except Exception as exc:  # pragma: no cover - best-effort only
    logger.debug(f"db_cache: legacy migration skipped: {exc}")
