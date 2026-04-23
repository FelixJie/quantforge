"""FastAPI dependency injection."""

from __future__ import annotations

from functools import lru_cache

from quantforge.backtest.engine import BacktestEngine
from quantforge.core.settings import Settings
from quantforge.portfolio.manager import PortfolioManager


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_backtest_engine() -> BacktestEngine:
    settings = get_settings()
    data_dir = settings.get("system.data_dir", "data")
    return BacktestEngine(data_dir=data_dir, settings=settings)


@lru_cache(maxsize=1)
def get_portfolio_manager() -> PortfolioManager:
    settings = get_settings()
    poll_interval = float(settings.get("realtime.poll_interval", 5.0))
    return PortfolioManager(poll_interval=poll_interval)
