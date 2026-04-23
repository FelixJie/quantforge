"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from quantforge.api.routes import (
    ai_picks, backtest, market, news, optimizer, portfolio,
    screener, sector, strategy, strategy_editor, system,
)
from quantforge.api.routes import (
    accounts, llm_stats, notification, predictions, yaml_strategy, stock_analysis,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    # Startup: warm up stock metadata cache in background (non-blocking)
    import asyncio
    from quantforge.data.storage.stock_meta_cache import refresh as refresh_meta
    asyncio.create_task(refresh_meta())

    yield

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

    # Register routers
    app.include_router(ai_picks.router, prefix="/api")
    app.include_router(system.router, prefix="/api")
    app.include_router(strategy.router, prefix="/api")
    app.include_router(backtest.router, prefix="/api")
    app.include_router(market.router, prefix="/api")
    app.include_router(portfolio.router, prefix="/api")
    app.include_router(optimizer.router, prefix="/api")
    app.include_router(strategy_editor.router, prefix="/api")
    app.include_router(screener.router, prefix="/api")
    app.include_router(sector.router, prefix="/api")
    app.include_router(news.router, prefix="/api")
    app.include_router(predictions.router, prefix="/api")
    app.include_router(notification.router, prefix="/api")
    app.include_router(yaml_strategy.router, prefix="/api")
    app.include_router(llm_stats.router, prefix="/api")
    app.include_router(stock_analysis.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")

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
