"""Performance metrics computation for backtest results."""

import numpy as np
import pandas as pd

from quantforge.core.constants import Direction


def compute_metrics(
    equity_curve: pd.DataFrame,
    trades: list,
    initial_capital: float,
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 252,
) -> dict:
    """Compute comprehensive performance metrics.

    Args:
        equity_curve: DataFrame with columns [date, equity]
        trades: list of TradeData objects
        initial_capital: starting capital
        risk_free_rate: annual risk-free rate (default 2%)
        trading_days_per_year: trading days (252 for A-shares)

    Returns:
        dict with all metrics
    """
    metrics: dict = {}

    if equity_curve.empty or len(equity_curve) < 2:
        return _empty_metrics()

    equity = equity_curve["equity"].values
    final_equity = float(equity[-1])

    # ── Return metrics ────────────────────────────────────────────────
    total_return = (final_equity - initial_capital) / initial_capital
    metrics["total_return"] = total_return
    metrics["final_equity"] = final_equity
    metrics["profit"] = final_equity - initial_capital

    # Annualized return
    n_days = len(equity)
    years = n_days / trading_days_per_year
    if years > 0 and final_equity > 0:
        annualized_return = (final_equity / initial_capital) ** (1 / years) - 1
    else:
        annualized_return = 0.0
    metrics["annualized_return"] = annualized_return

    # ── Risk metrics ─────────────────────────────────────────────────
    # Daily returns
    daily_returns = pd.Series(equity).pct_change().dropna()
    metrics["daily_returns"] = daily_returns.tolist()

    if len(daily_returns) > 1:
        volatility = float(daily_returns.std() * np.sqrt(trading_days_per_year))
    else:
        volatility = 0.0
    metrics["volatility"] = volatility

    # Sharpe ratio
    daily_rf = risk_free_rate / trading_days_per_year
    excess_returns = daily_returns - daily_rf
    if volatility > 0 and len(excess_returns) > 1:
        sharpe = float(
            excess_returns.mean() / excess_returns.std() * np.sqrt(trading_days_per_year)
        )
    else:
        sharpe = 0.0
    metrics["sharpe_ratio"] = sharpe

    # Sortino ratio (downside deviation)
    downside = daily_returns[daily_returns < daily_rf]
    if len(downside) > 1:
        downside_std = float(downside.std() * np.sqrt(trading_days_per_year))
        sortino = annualized_return / downside_std if downside_std > 0 else 0.0
    else:
        sortino = 0.0
    metrics["sortino_ratio"] = sortino

    # ── Drawdown metrics ─────────────────────────────────────────────
    equity_series = pd.Series(equity)
    rolling_max = equity_series.cummax()
    drawdowns = (equity_series - rolling_max) / rolling_max
    max_drawdown = float(drawdowns.min())
    metrics["max_drawdown"] = max_drawdown

    # Calmar ratio
    if max_drawdown < 0:
        calmar = annualized_return / abs(max_drawdown)
    else:
        calmar = 0.0
    metrics["calmar_ratio"] = calmar

    # ── Trade metrics ────────────────────────────────────────────────
    metrics["trade_count"] = len(trades)

    # Pair buy/sell trades into round-trips
    round_trips = _compute_round_trips(trades)
    metrics["round_trip_count"] = len(round_trips)

    if round_trips:
        pnls = [rt["pnl"] for rt in round_trips]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        metrics["win_rate"] = len(wins) / len(pnls) if pnls else 0.0
        metrics["avg_win"] = float(np.mean(wins)) if wins else 0.0
        metrics["avg_loss"] = float(np.mean(losses)) if losses else 0.0
        metrics["profit_factor"] = (
            abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")
        )
        metrics["avg_trade_pnl"] = float(np.mean(pnls))
    else:
        metrics["win_rate"] = 0.0
        metrics["avg_win"] = 0.0
        metrics["avg_loss"] = 0.0
        metrics["profit_factor"] = 0.0
        metrics["avg_trade_pnl"] = 0.0

    return metrics


def _compute_round_trips(trades: list) -> list[dict]:
    """Pair buy and sell trades into round-trips for win-rate calculation."""
    by_symbol: dict[str, list] = {}
    for trade in trades:
        sym = trade.symbol
        if sym not in by_symbol:
            by_symbol[sym] = []
        by_symbol[sym].append(trade)

    round_trips = []
    for sym, sym_trades in by_symbol.items():
        buy_queue: list = []
        for trade in sym_trades:
            if trade.direction == Direction.LONG:
                buy_queue.append(trade)
            elif trade.direction == Direction.SHORT and buy_queue:
                buy = buy_queue.pop(0)
                pnl = (trade.price - buy.price) * min(trade.volume, buy.volume)
                pnl -= trade.commission + buy.commission
                round_trips.append({"symbol": sym, "pnl": pnl})

    return round_trips


def _empty_metrics() -> dict:
    return {
        "total_return": 0.0,
        "annualized_return": 0.0,
        "volatility": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "trade_count": 0,
        "round_trip_count": 0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "profit_factor": 0.0,
        "avg_trade_pnl": 0.0,
        "profit": 0.0,
        "final_equity": 0.0,
    }
