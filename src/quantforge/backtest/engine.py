"""Event-driven backtest engine."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from loguru import logger

from quantforge.core.constants import EventType, Exchange, Interval, OrderStatus
from quantforge.core.datatypes import BarData, Event
from quantforge.core.event import EventEngine
from quantforge.core.settings import Settings
from quantforge.data.manager import DataManager
from quantforge.execution.gateway.sim import SimGateway
from quantforge.risk.manager import RiskManager
from quantforge.risk.rules.concentration import ConcentrationRule
from quantforge.risk.rules.drawdown_limit import DrawdownLimitRule
from quantforge.risk.rules.position_limit import PositionLimitRule
from quantforge.risk.rules.stop_loss import StopLossRule
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class BacktestEngine:
    """Replays historical bar data through the event bus, feeding a strategy.

    Usage:
        engine = BacktestEngine()
        result = await engine.run(
            strategy_cls=DualMAStrategy,
            symbols=["000001"],
            start=datetime(2022, 1, 1),
            end=datetime(2023, 12, 31),
            params={"fast_period": 10, "slow_period": 30},
        )
    """

    def __init__(
        self,
        data_dir: str = "data",
        settings: Settings | None = None,
    ):
        self._data_dir = data_dir
        self._settings = settings or Settings()
        self._data_manager = DataManager(data_dir)

    async def run(
        self,
        strategy_cls: type[Strategy],
        symbols: list[str],
        start: datetime,
        end: datetime,
        exchange: Exchange = Exchange.SSE,
        interval: Interval = Interval.DAILY,
        initial_capital: float | None = None,
        params: dict | None = None,
        download_missing: bool = True,
        enable_risk: bool = True,
    ) -> "BacktestResult":
        """Run a backtest and return performance metrics."""

        capital = initial_capital or self._settings.get(
            "backtest.initial_capital", 1_000_000.0
        )
        commission_rate = self._settings.get("backtest.commission_rate", 0.0003)
        min_commission = self._settings.get("backtest.min_commission", 5.0)
        stamp_tax_rate = self._settings.get("backtest.stamp_tax_rate", 0.001)
        t_plus_1 = self._settings.get("backtest.t_plus_1", True)

        # Set up core components
        event_engine = EventEngine()
        gateway = SimGateway(
            event_engine,
            commission_rate=commission_rate,
            min_commission=min_commission,
            stamp_tax_rate=stamp_tax_rate,
            t_plus_1=t_plus_1,
        )
        ctx = StrategyContext(
            strategy_name=strategy_cls.name or strategy_cls.__name__,
            event_engine=event_engine,
            initial_capital=capital,
        )
        gateway.register_context(ctx)

        strategy = strategy_cls(ctx, params or {})

        # Optional risk manager
        risk_mgr: RiskManager | None = None
        if enable_risk:
            risk_mgr = RiskManager(event_engine, ctx, capital)
            risk_mgr.add_rule(DrawdownLimitRule(
                max_daily_drawdown=self._settings.get("risk.max_daily_drawdown", 0.05),
                max_total_drawdown=self._settings.get("risk.max_total_drawdown", 0.20),
            ))
            risk_mgr.add_rule(PositionLimitRule(
                max_single_pct=self._settings.get("risk.max_position_pct", 0.10),
            ))
            risk_mgr.add_rule(ConcentrationRule(
                max_holdings=self._settings.get("risk.max_holdings", 20),
                max_top1_pct=self._settings.get("risk.max_top1_pct", 0.95),
            ))
            risk_mgr.add_rule(StopLossRule())

        # Wire event handlers: PENDING orders → risk check → gateway
        async def handle_order(event: Event):
            order = event.data
            if order.status != OrderStatus.PENDING:
                ctx.update_order(order)
                return
            if risk_mgr is not None:
                passed = await risk_mgr.check_order(order)
                if not passed:
                    return
            await gateway.send_order(order)

        event_engine.register(EventType.ORDER, handle_order)

        # Load bar data for all symbols
        all_bars: list[BarData] = []
        for symbol in symbols:
            if not self._data_manager.has_data(symbol, exchange, interval):
                if download_missing:
                    logger.info(f"Downloading missing data for {symbol}...")
                    await self._data_manager.download(
                        symbol, interval, start, end, exchange
                    )
                else:
                    logger.warning(f"No data for {symbol}, skipping.")
                    continue

            df = self._data_manager.load_bars(symbol, interval, start, end, exchange)
            if df.empty:
                logger.warning(f"No bars loaded for {symbol}")
                continue
            bars = self._data_manager.bars_to_bar_data_list(df, symbol, exchange, interval)
            all_bars.extend(bars)
            logger.info(f"Loaded {len(bars)} bars for {symbol}")

        if not all_bars:
            raise ValueError("No bar data available for backtest.")

        # Sort all bars chronologically
        all_bars.sort(key=lambda b: b.datetime)

        # Initialize strategy
        await strategy.on_init()
        strategy.inited = True
        logger.info(
            f"Backtest started: {strategy_cls.__name__} | "
            f"{start:%Y-%m-%d} → {end:%Y-%m-%d} | capital={capital:,.0f}"
        )

        # Equity curve tracking
        equity_curve: list[dict] = []
        prev_date = None

        # Replay bars
        for bar in all_bars:
            # New trading day: update risk daily tracking
            bar_date = bar.datetime.date()
            if bar_date != prev_date and risk_mgr is not None:
                risk_mgr.update_daily(bar_date)

            # Record bar in context (for indicator access)
            ctx.record_bar(bar)

            # Notify gateway (handles T+1 unfreeze and pending fill attempts)
            await gateway.on_bar(bar)

            # Drain any events from gateway fills before calling strategy
            while await event_engine.process_one():
                pass

            # Call strategy
            await strategy.on_bar(bar)

            # Drain strategy-generated events (orders, etc.)
            while await event_engine.process_one():
                pass

            # Record daily equity
            if bar_date != prev_date:
                account = ctx.get_account()
                equity_curve.append(
                    {"date": bar.datetime, "equity": account.balance}
                )
                prev_date = bar_date

        await strategy.on_stop()

        account = ctx.get_account()
        trades = ctx._trades

        result = BacktestResult(
            strategy_name=ctx.strategy_name,
            symbols=symbols,
            start=start,
            end=end,
            initial_capital=capital,
            final_equity=account.balance,
            trades=trades,
            equity_curve=pd.DataFrame(equity_curve),
            positions=ctx.get_all_positions(),
        )

        logger.info(
            f"Backtest finished | "
            f"Return: {result.total_return:.2%} | "
            f"Sharpe: {result.sharpe_ratio:.3f} | "
            f"MaxDD: {result.max_drawdown:.2%} | "
            f"Trades: {len(trades)}"
        )

        return result


class BacktestResult:
    """Backtest performance metrics and raw data."""

    def __init__(
        self,
        strategy_name: str,
        symbols: list[str],
        start: datetime,
        end: datetime,
        initial_capital: float,
        final_equity: float,
        trades: list,
        equity_curve: pd.DataFrame,
        positions: list,
    ):
        self.strategy_name = strategy_name
        self.symbols = symbols
        self.start = start
        self.end = end
        self.initial_capital = initial_capital
        self.final_equity = final_equity
        self.trades = trades
        self.equity_curve = equity_curve
        self.positions = positions

        # Compute metrics
        self._metrics = self._compute_metrics()

    def _compute_metrics(self) -> dict:
        from quantforge.backtest.analyzer import compute_metrics
        return compute_metrics(
            self.equity_curve,
            self.trades,
            self.initial_capital,
        )

    @property
    def total_return(self) -> float:
        return self._metrics.get("total_return", 0.0)

    @property
    def sharpe_ratio(self) -> float:
        return self._metrics.get("sharpe_ratio", 0.0)

    @property
    def max_drawdown(self) -> float:
        return self._metrics.get("max_drawdown", 0.0)

    @property
    def win_rate(self) -> float:
        return self._metrics.get("win_rate", 0.0)

    @property
    def metrics(self) -> dict:
        return self._metrics

    def summary(self) -> str:
        """Human-readable performance summary."""
        lines = [
            f"\n{'='*50}",
            f"  Strategy : {self.strategy_name}",
            f"  Period   : {self.start:%Y-%m-%d} → {self.end:%Y-%m-%d}",
            f"  Capital  : {self.initial_capital:>12,.0f}",
            f"  Final    : {self.final_equity:>12,.2f}",
            f"{'─'*50}",
            f"  Return   : {self.total_return:>11.2%}",
            f"  Sharpe   : {self.sharpe_ratio:>11.3f}",
            f"  Max DD   : {self.max_drawdown:>11.2%}",
            f"  Win Rate : {self.win_rate:>11.2%}",
            f"  Trades   : {len(self.trades):>11}",
            f"{'='*50}",
        ]
        return "\n".join(lines)
