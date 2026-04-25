"""Factor-based strategy template.

Uses a pre-trained ML model to generate alpha signals.
Long the top-scored stocks, short (or avoid) the bottom-scored.

Subclass this and override configure() to inject your own factors and model.
"""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


class FactorBasedStrategy(Strategy):
    """Template for ML/factor-driven long-only strategies.

    Parameters (set via params dict):
        symbol       : Stock symbol to trade.
        exchange     : Exchange enum value.
        train_bars   : Number of bars to use for model training.
        retrain_freq : Re-train model every N bars.
        top_pct      : Buy when prediction score is in top percentile.
        bot_pct      : Sell when prediction score drops to bottom percentile.
        target_horizon: Forward return horizon for training labels.
    """

    name: ClassVar[str] = "factor_based"
    description: ClassVar[str] = "ML/factor-driven strategy template"
    author: ClassVar[str] = "QuantForge"
    parameters: ClassVar[list[str]] = [
        "symbol", "exchange", "train_bars", "retrain_freq", "top_pct", "bot_pct",
    ]

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    train_bars: int = 250
    retrain_freq: int = 60
    top_pct: float = 0.80      # buy signal threshold
    bot_pct: float = 0.30      # sell signal threshold
    target_horizon: int = 1

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)

        self._model_engine = None
        self._bar_count = 0
        self._last_prediction: float | None = None

    def _init_model_engine(self):
        """Lazy import to avoid hard dependency when not using ML."""
        from quantforge.model.engine import ModelEngine
        from quantforge.model.zoo.lightgbm_model import LightGBMModel

        me = ModelEngine()
        me.set_model(LightGBMModel(n_estimators=100))
        return me

    async def on_init(self) -> None:
        self._model_engine = self._init_model_engine()
        self.ctx.log(
            f"Initialized: symbol={self.symbol}, train_bars={self.train_bars}, "
            f"retrain_freq={self.retrain_freq}"
        )

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return

        self._bar_count += 1

        # Get bar history
        df = self.ctx.get_bars_df(self.symbol)
        if len(df) < self.train_bars + 5:
            return

        # (Re-)train the model when enough data and at retrain frequency
        should_train = (
            not self._model_engine.get_feature_importance() is not None
            or self._bar_count % self.retrain_freq == 0
        )
        if should_train and len(df) >= self.train_bars:
            train_df = df.tail(self.train_bars).copy()
            try:
                self._model_engine.train(train_df, target_horizon=self.target_horizon)
            except Exception as e:
                self.ctx.log(f"Model training failed: {e}", level="warning")
                return

        # Generate prediction for latest bar
        if self._model_engine._model is None or not self._model_engine._model.is_fitted():
            return

        try:
            preds = self._model_engine.predict(df.tail(self.train_bars))
            if preds.empty:
                return
            score = float(preds.iloc[-1])
            # Rank against recent predictions for percentile
            recent_preds = self._model_engine.predict(df.tail(self.train_bars))
            pct_rank = (recent_preds < score).mean()
            self._last_prediction = pct_rank
        except Exception as e:
            self.ctx.log(f"Prediction failed: {e}", level="warning")
            return

        pos = self.ctx.get_position(self.symbol)
        has_position = pos is not None and pos.volume > 0
        price = bar.close

        # Buy signal: prediction in top percentile
        if pct_rank >= self.top_pct and not has_position:
            account = self.ctx.get_account()
            invest = account.available * 0.9
            volume = int(invest / price / 100) * 100
            if volume > 0:
                await self.ctx.buy(
                    self.symbol,
                    volume=float(volume),
                    price=price,
                    exchange=self.exchange,
                    order_type=OrderType.LIMIT,
                )
                self.ctx.log(
                    f"ML BUY | price={price:.2f} | score_pct={pct_rank:.2%}"
                )

        # Sell signal: prediction dropped to bottom percentile
        elif pct_rank <= self.bot_pct and has_position:
            available = pos.volume - pos.frozen
            if available > 0:
                await self.ctx.sell(
                    self.symbol,
                    volume=available,
                    price=price,
                    exchange=self.exchange,
                    order_type=OrderType.LIMIT,
                )
                self.ctx.log(
                    f"ML SELL | price={price:.2f} | score_pct={pct_rank:.2%}"
                )

    async def on_stop(self) -> None:
        self.ctx.log("Strategy stopped.")
