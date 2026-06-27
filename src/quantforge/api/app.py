"""FastAPI application factory."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path


def _load_dotenv() -> None:
    """Load project-root .env into os.environ (best-effort, zero-dependency).

    python-dotenv 未安装，而 ai_client 等模块在 **import 时** 就读 os.getenv
    (如 ANTHROPIC_API_KEY → MiniMax key)。run_backend.bat 不会注入这些变量，
    所以必须在任何 quantforge 路由导入**之前**把 .env 灌进 os.environ，否则
    LLM key 为空 → MiniMax 报 "Authentication Fails"。已存在的环境变量不覆盖
    (真实 env 优先于 .env)。从本文件向上找 .env，兼容从任意 CWD 启动。
    """
    here = Path(__file__).resolve()
    for base in (Path.cwd(), *here.parents):
        f = base / ".env"
        if not f.exists():
            continue
        try:
            for raw in f.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        except Exception:
            pass
        break


_load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from quantforge.api.routes import (
    ai_picks, auth, backtest, capital_flow, market, news,
    research, screener, sector, signal_hub, strategy, strategy_editor, system,
)
from quantforge.api.routes import (
    llm_stats, notification, predictions, yaml_strategy, stock_analysis,
    watchlist, alert, stock_data, blog, fenchuan, chat, home, admin,
    stock_compare, morning, review, price_surge, feishu, quarterly,
)


# ── 活跃埋点：路径 → 功能名归一化 ──────────────────────────────────────────────
# 按前缀把 API 路径映射成对运营有意义的「功能」名。顺序敏感：先匹配更具体的。
# 未命中的有 token 请求归「其他」，仍计入 DAU；不在此表也不影响活跃判定。
_FEATURE_RULES = [
    ("/api/chat",            "AI对话"),
    ("/api/stock-analysis",  "个股分析"),
    ("/api/ai-picks",        "AI推荐"),
    ("/api/watchlist",       "自选股"),
    ("/api/research",        "研报精读"),
    ("/api/keyword",         "研报精读"),
    ("/api/screener",        "选股器"),
    ("/api/backtest",        "回测"),
    ("/api/strategy",        "策略"),
    ("/api/yaml",            "策略"),
    ("/api/sector",          "板块"),
    ("/api/capital-flow",    "资金流"),
    ("/api/market",          "行情"),
    ("/api/stock-data",      "行情"),
    ("/api/predictions",     "预测"),
    ("/api/signal",          "信号"),
    ("/api/notification",    "通知"),
    ("/api/alert",           "提醒"),
    ("/api/feishu",          "飞书"),
    ("/api/blog",            "博客"),
    ("/api/xingqiu",         "博客"),
    ("/api/home",            "首页"),
    ("/api/price-surge",     "涨价逻辑"),
]

# 不计入活跃的路径前缀：后台自查/统计端点（admin、llm-stats）会被运营反复刷新，
# 计入会把管理员自己刷成「最活跃用户」并放大 DAU；鉴权/系统心跳同理排除。
_ACTIVITY_SKIP_PREFIXES = (
    "/api/admin", "/api/llm-stats", "/api/auth", "/api/system", "/api/cache",
)


def _classify_feature(path: str) -> str | None:
    if not path.startswith("/api/"):
        return None
    for prefix in _ACTIVITY_SKIP_PREFIXES:
        if path.startswith(prefix):
            return None
    for prefix, name in _FEATURE_RULES:
        if path.startswith(prefix):
            return name
    return "其他"


def _maybe_log_activity(request: Request) -> None:
    """从请求里解析登录账号 + 功能，写一条活跃记录。匿名/无关路径直接跳过。"""
    path = request.url.path
    feature = _classify_feature(path)
    if feature is None:
        return
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return  # 匿名请求不计活跃（活跃 = 已登录账号在用）
    token = auth[7:].strip()

    from jose import JWTError, jwt
    from quantforge.api.routes.auth import _SECRET_KEY, _ALGORITHM, _get_user_by_username
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        username = payload.get("sub")
    except JWTError:
        return
    if not username:
        return
    user = _get_user_by_username(username)
    user_id = user["id"] if user else ""

    from quantforge.data.storage import db_cache
    db_cache.log_activity(user_id, username, feature, request.method, path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    import asyncio

    # 调大默认线程池：to_thread 承载了 sqlite 读写 + 各数据源网络拉取，
    # 默认池(~CPU+4)在后台预热器与慢上游(如被限速的 reportapi，单请求可达
    # 上百秒)并发时极易被占满，导致连缓存命中的请求也排队 → 全站挂起。
    from concurrent.futures import ThreadPoolExecutor
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=64, thread_name_prefix="qf-io"))

    # 后台任务开关：QF_NO_BG=1 全禁；QF_NO_<NAME>=1 单独禁（META/SNAPSHOT/KLINE/REPORT）
    # 用于隔离事件循环卡死源 + 让运维可按环境裁剪重型后台预热。
    import os
    import uuid

    from quantforge.data.storage import db_cache

    def _bg_on(name: str) -> bool:
        if os.getenv("QF_NO_BG") == "1":
            return False
        return os.getenv(f"QF_NO_{name}") != "1"

    # ── Leader 选举：多 worker 部署(uvicorn --workers N)下，每个 worker 进程都会
    # 跑一遍 lifespan。若不加约束，每日 LLM 重活(产业链精读/晨报复盘/季报/涨价归档/
    # 荐股结算)会跑 N 遍 → token 成本翻倍，且归档/落库并发写竞态。这里用 SQLite 抢一把
    # 'background' 锁，只有抢到的 worker(leader)才启动下面那批后台任务；非 leader 仅
    # 低频轮询尝试接管(原 leader 进程死掉、锁过期即被接管，避免后台全停)。
    owner = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    app.state.bg_owner = owner
    app.state.bg_started = False  # 守卫：保证那批后台任务全进程只启动一次
    is_leader = db_cache.try_acquire_leader("background", owner)

    def _start_background_tasks() -> None:
        """启动那一批后台/定时任务（仅 leader 调用一次，由 app.state.bg_started 守卫）。

        内部仍按各自的 _bg_on(...) / QF_ENABLE_* 单项开关决定是否真正起每一项——
        本函数只负责「是否由本 worker 来编排启动」这一层。
        """
        if app.state.bg_started:
            return
        app.state.bg_started = True
        _spawn_background_tasks()

    def _spawn_background_tasks() -> None:
        if _bg_on("META"):
            # warm up stock metadata cache in background (non-blocking)
            from quantforge.data.storage.stock_meta_cache import refresh as refresh_meta
            asyncio.create_task(refresh_meta())

        if _bg_on("SNAPSHOT"):
            # background whole-market quote-snapshot refresher (keeps the stock_quote
            # table fresh so list/quote displays serve from SQL in <1s).
            from quantforge.data.feed import snapshot
            app.state.snapshot_task = asyncio.create_task(snapshot.run_forever())

        if _bg_on("KLINE"):
            # background watchlist K-line prewarmer (pre-fetch daily K-lines for
            # watchlisted codes so the watchlist page draws mini-charts instantly).
            from quantforge.api.routes import market
            app.state.kline_warmer_task = asyncio.create_task(market.watchlist_kline_warmer())

        # 全市场日 K 线预热（供 AI 荐股全市场扫描读缓存）。默认开，QF_NO_MARKET_KLINE=1 关。
        # 低速分批灌库，盘后跑、盘中不抢带宽；稳态每 6h 增量。
        if _bg_on("MARKET_KLINE"):
            from quantforge.api.routes import market
            app.state.market_kline_warmer_task = asyncio.create_task(market.market_kline_warmer())

        # 个股详情预热：把「自选股 + 最近查询过的股」的 overview/technical/momentum/
        # fundamental 提前拉好落 SWR 缓存，让这些股的详情页首屏秒开（冷门股仍首访现拉，
        # 之后纳入下次预热）。默认开，QF_NO_DETAIL_WARM=1 关。低并发、盘中5min/盘后30min。
        if _bg_on("DETAIL_WARM"):
            from quantforge.api.routes import stock_analysis
            app.state.detail_warmer_task = asyncio.create_task(stock_analysis.stock_detail_warmer())

        # 机构研报预热：**默认关闭**（需显式 QF_ENABLE_REPORT=1 开启）。
        # 本环境东财 reportapi 被代理劫持，单请求可挂到上百秒，startup 定时预热会拖死
        # 事件循环 → 全站卡死。研报改为按需拉取（打开个股详情时 /research/summary 触发）。
        if os.getenv("QF_ENABLE_REPORT") == "1":
            from quantforge.api.routes import research
            app.state.report_warmer_task = asyncio.create_task(research.watchlist_report_warmer())

        # 全市场研报全量/增量同步：开机库空补近一年全量，之后每天 18:30 增量。
        # **默认关闭**（需 QF_ENABLE_REPORT_SYNC=1）——东财 reportapi 在本环境间歇被劫持，
        # 须运维确认网络可达后再开；首灌约几分钟、走独立 to_thread 不阻塞事件循环。
        if os.getenv("QF_ENABLE_REPORT_SYNC") == "1":
            from quantforge.api.routes import research
            app.state.report_sync_task = asyncio.create_task(research.report_sync_scheduler())

        # 每日定时产业链精读（默认开，QF_NO_RESEARCH_DAILY=1 关闭）：每天到起跑时刻
        # (QF_RESEARCH_START_HOUR，默认0点)后按关键词清单顺序「连跑」——前一个跑完立刻接力
        # 下一个，串行不并发；前端只读结果，不由用户点按钮触发重活。
        if _bg_on("RESEARCH_DAILY"):
            from quantforge.api.routes import research
            app.state.research_daily_task = asyncio.create_task(research.daily_keyword_scheduler())

        # 手动触发的等待队列消化器：有空闲并发名额时自动取队首开跑（跑完接着补位）。
        # 与每日定时任务解耦——即使关掉定时重跑(QF_NO_RESEARCH_DAILY=1)，手动排队仍要能消化。
        if _bg_on("RESEARCH_QUEUE"):
            from quantforge.api.routes import research
            app.state.research_queue_task = asyncio.create_task(research.research_queue_worker())

        # 知识星球博客抓取（机构荐股）：开机挂定时循环，整点每小时抓一轮增量落库。
        # 默认开（QF_NO_BLOG_CRAWL=1 关），与公众号同节奏——zsxq 间歇 1059 限流时
        # 整轮自动跳过仅记 warning，cookie 有效的整点即入库；走专属线程池不阻塞事件
        # 循环。手动触发仍可用 POST /api/xingqiu/refresh（单轮）/ /api/xingqiu/backfill。
        if _bg_on("BLOG_CRAWL"):
            from quantforge.api.routes import blog
            app.state.blog_crawl_task = asyncio.create_task(blog.crawl_loop())

        # 公众号（纷传圈子）抓取：与机构荐股同节奏——开机挂定时循环，整点每小时抓一轮。
        # 默认开（QF_NO_FENCHUAN_CRAWL=1 关）；登录态失效时轮次自动跳过，手动刷新仍可用
        # POST /api/fenchuan/refresh。走专属线程池不阻塞事件循环。
        if _bg_on("FENCHUAN_CRAWL"):
            from quantforge.api.routes import fenchuan
            app.state.fenchuan_crawl_task = asyncio.create_task(fenchuan.crawl_loop())

        # 飞书群消息抓取：OAuth 授权后每 30 分钟增量拉取用户所在全部群的消息。
        # 未授权时跳过（不报错），可用 GET /api/feishu/auth-url 跳转授权。
        # 默认开（QF_NO_FEISHU_CRAWL=1 关）。
        if _bg_on("FEISHU_CRAWL"):
            app.state.feishu_crawl_task = asyncio.create_task(feishu.crawl_loop())

        # 荐股预测每日自动结算（默认开，QF_NO_VERIFY_DAILY=1 关）：启动补一次 +
        # 每天 16:00 复算，路径扫描止盈/止损并定格，用户进验证页即最新。
        if _bg_on("VERIFY_DAILY"):
            from quantforge.api.routes import predictions as _predictions
            app.state.verify_daily_task = asyncio.create_task(_predictions.daily_verify_scheduler())

        # 自选股/个股预警轮询：盘中每 60s 批量拉行情比对各用户的到价/涨跌幅规则，
        # 命中即写通知并推送已配置渠道。默认开（QF_NO_ALERT_POLL=1 关）；批量行情走
        # datasource(腾讯/iFinD，可过代理)，非交易时段自动空转跳过。
        if _bg_on("ALERT_POLL"):
            from quantforge.api.routes import alert as _alert
            app.state.alert_poll_task = asyncio.create_task(_alert.alert_poll_loop(60))

        # 每日报告存档：盘前 08:40 晨报、盘后 15:30 复盘各自定时落档（无人访问也留底），
        # 启动补当天缺失的。默认开（QF_NO_DAILY_REPORT=1 关）。
        if _bg_on("DAILY_REPORT"):
            from quantforge.api.routes import review as _review
            app.state.daily_report_task = asyncio.create_task(_review.daily_snapshot_scheduler())

        # 超短量价盘前扫描：交易日 09:20–09:25 每 30s 滚动扫创业板/科创板的量价突破标的
        # （5日均量首次上穿60日均量+今日涨幅≥3%+近10日涨幅≤20%），结果落 AI 荐股 ultra 缓存。
        # 纯规则、不走 AI，开销小；默认开（QF_NO_ULTRA=1 关）。
        if _bg_on("ULTRA"):
            from quantforge.api.routes import ai_picks as _ai_picks
            app.state.ultra_scan_task = asyncio.create_task(_ai_picks.ultra_scalp_scanner())

        # 季报分析定时生成：每日 10:00 重算「季报预增」(多源搜集预增线索+AI 逐个分析幅度/理由→推荐)
        # 与「净利润断层」(全市场净利同比>20% + 公告后首日高开≥3%收阳)，启动补跑当天缺失的。
        # 默认开，QF_NO_QUARTERLY=1 关。
        if _bg_on("QUARTERLY"):
            from quantforge.api.routes import quarterly as _quarterly
            app.state.quarterly_task = asyncio.create_task(_quarterly.quarterly_scheduler())

        # 板块汇总预热：概念板块冷抓要逐个请求 ~373 个同花顺详情页(~30-75s)，缓存(20min)一过期
        # 就会让下一个用户撞整段冷抓。后台每 16min 重灌概念/行业汇总，使前台几乎永远命中缓存
        # (<0.1s)。默认开，QF_NO_SECTOR_WARM=1 关。
        if _bg_on("SECTOR_WARM"):
            from quantforge.api.routes import sector as _sector
            app.state.sector_warmer_task = asyncio.create_task(_sector.sector_summary_warmer())

        # 申万一级行业分类预热：AI 荐股「动能买点」页行业筛选维度用申万口径(akshare 拉 31 个
        # 一级行业成分落库, 按周刷新)。push2/efinance 行业被代理劫持不可用故单独走 akshare。
        # 默认开, QF_NO_SW_INDUSTRY=1 关。
        if _bg_on("SW_INDUSTRY"):
            from quantforge.data.feed import sw_industry as _sw
            app.state.sw_industry_task = asyncio.create_task(_sw.sw_industry_warmer())

        # 涨价逻辑每日归档：每晚 22:00 采集当日提价线索 + AI 归纳，落 price_surge:analysis:{date}，
        # 仅交易日 / 开盘前 1 日触发（跳过纯休市夜）。无人访问也留底，供「历史存档 / 时间脉络」每天有数据。
        # 启动补当天缺失的。默认开，QF_NO_PRICE_SURGE_DAILY=1 关。
        if _bg_on("PRICE_SURGE_DAILY"):
            app.state.price_surge_daily_task = asyncio.create_task(price_surge.daily_archive_scheduler())

        # 活跃日志裁剪：每天裁掉 90 天前的 activity_log，约束 DB 体积。
        async def _prune_activity_daily():
            from quantforge.data.storage import db_cache
            while True:
                try:
                    await asyncio.to_thread(db_cache.prune_activity, 90)
                except Exception:
                    pass
                await asyncio.sleep(86400)
        app.state.activity_prune_task = asyncio.create_task(_prune_activity_daily())

    # ── Leader 心跳续约：leader 每 ~30s 刷新一次锁的 heartbeat，使锁不过期。
    # 若某次 refresh 返回 False(说明锁已被别的 worker 接管)，记一条日志即可——
    # 不强制重启已起任务，保持简单(进程仍在跑、任务继续，下次重启会重新选举)。
    async def _leader_heartbeat():
        from loguru import logger
        while True:
            await asyncio.sleep(30)
            try:
                ok = await asyncio.to_thread(db_cache.refresh_leader, "background", owner)
                if not ok:
                    logger.warning(f"[leader] 心跳失败：'background' 锁已被接管(owner={owner})")
            except Exception:
                pass

    # ── 非 leader 的接管轮询：每 ~60s 尝试抢锁；一旦原 leader 进程死掉、锁过期被本
    # worker 抢到，就启动那批后台任务并升级为 leader(_start_background_tasks 用
    # app.state.bg_started 守卫，绝不重复启动同一批任务)，随后转入心跳续约。
    async def _leader_takeover_poll():
        from loguru import logger
        while True:
            await asyncio.sleep(60)
            try:
                if await asyncio.to_thread(db_cache.try_acquire_leader, "background", owner):
                    logger.info(f"[leader] 接管 'background' 锁，启动后台任务(owner={owner})")
                    _start_background_tasks()
                    app.state.bg_heartbeat_task = asyncio.create_task(_leader_heartbeat())
                    break  # 已成为 leader，停止接管轮询
            except Exception:
                pass

    if is_leader:
        # 本 worker 抢到锁 → 作为 leader 启动后台任务 + 起心跳续约。
        _start_background_tasks()
        app.state.bg_heartbeat_task = asyncio.create_task(_leader_heartbeat())
    else:
        # 非 leader → 只起低频接管轮询，平时不跑任何重活。
        app.state.bg_takeover_task = asyncio.create_task(_leader_takeover_poll())

    yield

    # Shutdown: stop the snapshot refresher
    for attr in ("snapshot_task", "kline_warmer_task", "market_kline_warmer_task",
                 "detail_warmer_task", "report_warmer_task", "report_sync_task",
                 "blog_crawl_task", "fenchuan_crawl_task", "feishu_crawl_task",
                 "research_daily_task", "verify_daily_task", "alert_poll_task",
                 "activity_prune_task", "daily_report_task", "ultra_scan_task",
                 "sector_warmer_task", "quarterly_task", "sw_industry_task",
                 "price_surge_daily_task", "research_queue_task",
                 "bg_heartbeat_task", "bg_takeover_task"):
        task = getattr(app.state, attr, None)
        if task:
            task.cancel()

    # Shutdown: stop real-time stream and save paper state
    from quantforge.api.deps import get_portfolio_manager
    mgr = get_portfolio_manager()
    mgr.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="QuantForge API",
        description="Quantitative trading system REST API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    # CORS — allow frontend dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 活跃埋点中间件：每个带 token 的 API 请求打一条点（user + 功能 + 时间），
    # 供管理后台出 DAU/功能热度/最近活跃/留存。匿名请求、静态资源、后台轮询类
    # 端点（自身 admin/活跃查询、心跳）一律跳过，避免污染或自我放大统计。
    @app.middleware("http")
    async def _activity_logger(request: Request, call_next):
        response = await call_next(request)
        try:
            _maybe_log_activity(request)
        except Exception:
            pass  # 埋点绝不能影响正常响应
        return response

    # Register routers
    app.include_router(auth.router, prefix="/api")
    app.include_router(ai_picks.router, prefix="/api")
    app.include_router(system.router, prefix="/api")
    app.include_router(strategy.router, prefix="/api")
    app.include_router(backtest.router, prefix="/api")
    app.include_router(market.router, prefix="/api")
    app.include_router(strategy_editor.router, prefix="/api")
    app.include_router(screener.router, prefix="/api")
    app.include_router(sector.router, prefix="/api")
    app.include_router(news.router, prefix="/api")
    app.include_router(predictions.router, prefix="/api")
    app.include_router(notification.router, prefix="/api")
    app.include_router(yaml_strategy.router, prefix="/api")
    app.include_router(llm_stats.router, prefix="/api")
    app.include_router(stock_analysis.router, prefix="/api")
    app.include_router(stock_compare.router, prefix="/api")
    app.include_router(research.router, prefix="/api")
    app.include_router(capital_flow.router, prefix="/api")
    app.include_router(signal_hub.router, prefix="/api")
    app.include_router(watchlist.router, prefix="/api")
    app.include_router(alert.router, prefix="/api")
    app.include_router(stock_data.router, prefix="/api")
    app.include_router(blog.router, prefix="/api")
    app.include_router(fenchuan.router, prefix="/api")
    app.include_router(feishu.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(home.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(morning.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(price_surge.router, prefix="/api")
    app.include_router(quarterly.router, prefix="/api")

    # Serve built frontend — resolve relative to this file's location
    # app.py lives at: <project_root>/src/quantforge/api/app.py
    # web/dist lives at: <project_root>/web/dist  (3 levels up)
    _project_root = Path(__file__).parent.parent.parent.parent
    web_dist = _project_root / "web" / "dist"
    if web_dist.exists():
        # Serve static assets (JS/CSS/images)
        app.mount("/assets", StaticFiles(directory=str(web_dist / "assets")), name="assets")

        # SPA fallback: all non-API routes serve index.html for Vue Router
        from fastapi.responses import FileResponse

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            index = web_dist / "index.html"
            return FileResponse(str(index))

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("quantforge.api.app:app", host="0.0.0.0", port=8000, reload=True)
