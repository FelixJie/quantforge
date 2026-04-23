"""Capital allocators for multi-strategy portfolios.

Three allocation strategies:
- EqualWeightAllocator: equal fraction to each session
- RiskParityAllocator: weight inversely proportional to volatility (needs history)
- MomentumAllocator: weight proportional to recent return (needs history)
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAllocator(ABC):
    """Abstract base class for capital allocation strategies."""

    @abstractmethod
    def allocate(
        self,
        total_capital: float,
        session_ids: list[str],
        metrics: dict[str, dict] | None = None,
    ) -> dict[str, float]:
        """Return a mapping of session_id → allocated capital."""


class EqualWeightAllocator(BaseAllocator):
    """Splits capital equally across all sessions."""

    def allocate(
        self,
        total_capital: float,
        session_ids: list[str],
        metrics: dict[str, dict] | None = None,
    ) -> dict[str, float]:
        if not session_ids:
            return {}
        per_session = total_capital / len(session_ids)
        return {sid: per_session for sid in session_ids}


class RiskParityAllocator(BaseAllocator):
    """Allocates inversely proportional to each session's volatility.

    Falls back to equal weight when volatility history is unavailable.
    Metrics dict should contain: {session_id: {"volatility": float}}
    """

    def allocate(
        self,
        total_capital: float,
        session_ids: list[str],
        metrics: dict[str, dict] | None = None,
    ) -> dict[str, float]:
        if not session_ids:
            return {}
        if not metrics:
            return EqualWeightAllocator().allocate(total_capital, session_ids)

        inv_vols: dict[str, float] = {}
        for sid in session_ids:
            vol = (metrics.get(sid) or {}).get("volatility", 0)
            inv_vols[sid] = 1.0 / vol if vol > 0 else 1.0

        total_inv = sum(inv_vols.values())
        return {
            sid: total_capital * (inv_vol / total_inv)
            for sid, inv_vol in inv_vols.items()
        }


class MomentumAllocator(BaseAllocator):
    """Allocates proportional to recent returns (positive only).

    Falls back to equal weight when returns are unavailable or all negative.
    Metrics dict should contain: {session_id: {"return": float}}
    """

    def allocate(
        self,
        total_capital: float,
        session_ids: list[str],
        metrics: dict[str, dict] | None = None,
    ) -> dict[str, float]:
        if not session_ids:
            return {}
        if not metrics:
            return EqualWeightAllocator().allocate(total_capital, session_ids)

        returns: dict[str, float] = {}
        for sid in session_ids:
            ret = (metrics.get(sid) or {}).get("return", 0)
            returns[sid] = max(ret, 0)  # only positive momentum

        total_pos = sum(returns.values())
        if total_pos <= 0:
            return EqualWeightAllocator().allocate(total_capital, session_ids)

        return {
            sid: total_capital * (ret / total_pos)
            for sid, ret in returns.items()
        }
