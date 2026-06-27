"""AI 推荐策略的可回测包装。

把「AI 每日推荐」里两个**日线、单标的**可表达的规则策略包装成标准 Strategy，
让它们能进回测引擎跑历史，与 AI 推荐页保持同一套信号逻辑（直接复用
``analysis.momentum`` / ``analysis.pring``，不重写指标）：

  - ``MomentumPickStrategy``  动能买点（四维动能 + 阈值穿越 + ATR 止盈止损）
  - ``PringPickStrategy``     普林格 KST 周期（低位金叉 + 长周期向上 + 站上MA50）

逐根 K 线把「截至当前」的历史喂给扫描器，状态转为 buy 时开仓、转为 sell 或触及
止损/止盈时平仓——等价于「每次该信号触发就买入、按策略规则离场」的回测。

超短量价(ultra)是盘前竞价 30s 滚动的日内策略、试盘点(probe)是事件型，均无法在
日线单标的回测引擎中如实还原，故不在此包装。
"""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from quantforge.core.constants import Exchange, OrderType
from quantforge.core.datatypes import BarData
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext


def _df_to_bars(df: pd.DataFrame) -> list[dict]:
    """ctx.get_bars_df 的 DataFrame → 扫描器所需的升序 OHLCV dict 列表（带 date）。"""
    out: list[dict] = []
    for r in df.itertuples(index=False):
        dt = getattr(r, "datetime", None)
        date = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        out.append({
            "date": date,
            "open": float(r.open), "high": float(r.high), "low": float(r.low),
            "close": float(r.close), "volume": float(r.volume),
        })
    return out


class _BaseAiPickStrategy(Strategy):
    """共享的开/平仓骨架：子类只需实现 ``_signal(bars) -> (action, levels)``。"""

    symbol: str = "000001"
    exchange: Exchange = Exchange.SZSE
    warmup: int = 60          # 评分稳定所需的最少 K 线数
    use_levels: bool = True   # 是否启用 ATR 止盈/止损离场

    parameters: ClassVar[list[str]] = ["symbol", "exchange", "warmup", "use_levels"]

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        if isinstance(self.exchange, str):
            self.exchange = Exchange(self.exchange)
        self._stop: float | None = None
        self._target: float | None = None

    async def on_init(self) -> None:
        self.ctx.log(f"{self.name} initialized: symbol={self.symbol}")

    # 子类实现：返回 ("buy"|"sell"|None, {"stop": x, "target": y})
    def _signal(self, bars: list[dict]) -> tuple[str | None, dict]:
        raise NotImplementedError

    async def on_bar(self, bar: BarData) -> None:
        if bar.symbol != self.symbol:
            return
        df = self.ctx.get_bars_df(self.symbol)
        if len(df) < self.warmup:
            return

        bars = _df_to_bars(df)
        try:
            action, levels = self._signal(bars)
        except Exception as e:
            self.ctx.log(f"signal error: {e}", level="warning")
            return

        price = bar.close
        pos = self.ctx.get_position(self.symbol)
        has_position = pos is not None and pos.volume > 0

        # ── 止损/止盈优先于策略信号 ──
        if has_position and self.use_levels:
            if self._stop and price <= self._stop:
                await self._close(pos, price, f"触发止损 {self._stop}")
                return
            if self._target and price >= self._target:
                await self._close(pos, price, f"触发止盈 {self._target}")
                return

        if action == "buy" and not has_position:
            account = self.ctx.get_account()
            volume = int(account.available * 0.95 / price / 100) * 100
            if volume > 0:
                await self.ctx.buy(self.symbol, volume=float(volume), price=price,
                                   exchange=self.exchange, order_type=OrderType.LIMIT)
                self._stop = levels.get("stop") if self.use_levels else None
                self._target = levels.get("target") if self.use_levels else None
                self.ctx.log(f"BUY {self.symbol} @ {price:.2f} vol={volume} "
                             f"stop={self._stop} target={self._target}")
        elif action == "sell" and has_position:
            await self._close(pos, price, "策略离场信号")

    async def _close(self, pos, price: float, reason: str) -> None:
        available = pos.volume - pos.frozen
        if available > 0:
            await self.ctx.sell(self.symbol, volume=available, price=price,
                                exchange=self.exchange, order_type=OrderType.LIMIT)
            self.ctx.log(f"SELL {self.symbol} @ {price:.2f} | {reason}")
        self._stop = self._target = None

    async def on_stop(self) -> None:
        self.ctx.log(f"{self.name} stopped.")


class MomentumPickStrategy(_BaseAiPickStrategy):
    """动能买点（AI 推荐「动能买点」页的回测版）。"""

    name: ClassVar[str] = "ai_momentum_pick"
    description: ClassVar[str] = "四维动能买卖点（AI 推荐·动能买点 回测版）"
    author: ClassVar[str] = "QuantForge"

    def _signal(self, bars: list[dict]) -> tuple[str | None, dict]:
        from quantforge.analysis.momentum import compute_momentum, MomentumConfig
        res = compute_momentum(bars, MomentumConfig())
        cur = res.get("current") or {}
        signals = res.get("signals") or []
        last_date = bars[-1]["date"]
        action = None
        if signals:
            sig = signals[-1]
            # 仅当最后一次状态转换恰好落在当前 K 线，才视为「当根触发」
            if str(sig.get("date")) == last_date:
                action = sig.get("type")  # "buy" / "sell"
        levels = {"stop": cur.get("stop_price"), "target": cur.get("target_price")}
        return action, levels


class PringPickStrategy(_BaseAiPickStrategy):
    """普林格 KST 周期（AI 推荐「普林格KST周期」页的回测版）。"""

    name: ClassVar[str] = "ai_pring_pick"
    description: ClassVar[str] = "普林格 KST 周期金叉（AI 推荐·普林格 回测版）"
    author: ClassVar[str] = "QuantForge"
    warmup: int = 80          # KST 长周期需要更长预热

    def __init__(self, ctx: StrategyContext, params: dict | None = None):
        super().__init__(ctx, params)
        self._prev_state: str | None = None

    def _signal(self, bars: list[dict]) -> tuple[str | None, dict]:
        from quantforge.analysis import pring
        k = pring.analyze(bars, pring.PringConfig())
        if not k:
            return None, {}
        state = k.get("state")
        action = None
        # 状态由非买入翻成 buy → 开仓；翻成 sell → 平仓（边沿触发，避免重复下单）
        if state == "buy" and self._prev_state != "buy":
            action = "buy"
        elif state == "sell" and self._prev_state not in (None, "sell"):
            action = "sell"
        self._prev_state = state
        levels = {"stop": k.get("stop_price"), "target": k.get("target_price")}
        return action, levels
