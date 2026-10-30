"""Paper execution with mandatory pre-order hard checks; never calls Dhan."""
from dataclasses import dataclass
from decimal import Decimal
from .core import TradePlan
from .hard_checks import AccountState, HardLimits, OrderRequest, validate_order

@dataclass(frozen=True)
class PaperFill:
    symbol: str
    side: str
    quantity: int
    price: Decimal
    mode: str = "PAPER"

class PaperBroker:
    def __init__(self):
        self.fills = []

    def enter(self, plan: TradePlan, state: AccountState, limits: HardLimits = HardLimits()) -> PaperFill:
        validate_order(OrderRequest(plan.symbol, "BUY", plan.quantity, plan.entry), state, limits)
        if plan.take_profit != plan.entry + 2 * (plan.entry - plan.stop_loss):
            raise ValueError("Trade plan must maintain exactly 1:2 RR")
        if plan.risk_rupees > limits.max_risk_per_trade:
            raise ValueError("Per-trade risk limit exceeded")
        fill = PaperFill(plan.symbol, "BUY", plan.quantity, plan.entry)
        self.fills.append(fill)
        return fill
