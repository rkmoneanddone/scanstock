"""Watchlist, quote handling and fixed 1:2 risk/reward plans.

No strategy is activated here. Dhan connectivity is a future adapter.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

WATCHLIST = (
    "SBIN", "ICICIBANK", "HDFCBANK", "BEL", "TATAPOWER", "NTPC",
    "ONGC", "HINDALCO", "TATASTEEL", "ITC", "INFY", "RELIANCE",
)

@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    ltp: Decimal
    volume: Optional[int] = None
    oi: Optional[int] = None
    oi_change_pct: Optional[Decimal] = None
    breakout_retest: str = "NOT_IMPLEMENTED"

@dataclass(frozen=True)
class TradePlan:
    symbol: str
    side: str
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    quantity: int
    risk_rupees: Decimal

def make_trade_plan(symbol: str, entry, stop_loss, capital=10000, risk_limit=100, side="BUY") -> TradePlan:
    """Cash-equity long-only plan; target is always exactly twice stop distance."""
    if side != "BUY":
        raise ValueError("V1 supports BUY cash-equity plans only")
    entry, stop_loss = Decimal(str(entry)), Decimal(str(stop_loss))
    capital, risk_limit = Decimal(str(capital)), Decimal(str(risk_limit))
    if not (entry > stop_loss > 0 and capital > 0 and risk_limit > 0):
        raise ValueError("Invalid entry, stop, capital or risk limit")
    per_share_risk = entry - stop_loss
    quantity = min(int(capital // entry), int(risk_limit // per_share_risk))
    if quantity < 1:
        raise ValueError("Insufficient capital or risk budget for one share")
    return TradePlan(symbol, side, entry, stop_loss, entry + 2 * per_share_risk, quantity, per_share_risk * quantity)
