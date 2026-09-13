from __future__ import annotations

import operator
from decimal import Decimal

from .contracts import MarketRepository
from .domain import Candle, ScanCondition


FIELDS = ("open", "high", "low", "close", "volume")
OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "=": operator.eq,
    "!=": operator.ne,
}


class StrictScanner:
    def __init__(self, repository: MarketRepository) -> None:
        self.repository = repository

    def run(self, timeframe: str, condition: ScanCondition) -> list[dict]:
        if timeframe != "1D":
            raise ValueError("V1 currently supports Daily candles only")
        if condition.field not in FIELDS or condition.operator not in OPERATORS:
            raise ValueError("Unsupported field or operator")
        if condition.compare_mode == "field":
            if condition.compare_field not in FIELDS:
                raise ValueError("A valid comparison field is required")
        elif condition.compare_mode == "value":
            if condition.compare_value is None:
                raise ValueError("A comparison value is required")
        else:
            raise ValueError("Comparison mode must be field or value")

        matches: list[dict] = []
        compare = OPERATORS[condition.operator]
        for candle in self.repository.latest_candles(timeframe):
            left = self._value(candle, condition.field)
            right = self._value(candle, condition.compare_field) if condition.compare_mode == "field" else condition.compare_value
            if compare(left, right):
                matches.append({
                    "symbol": candle.symbol,
                    "timestamp": candle.timestamp.isoformat(),
                    "open": float(candle.open), "high": float(candle.high),
                    "low": float(candle.low), "close": float(candle.close),
                    "volume": candle.volume,
                    "left_value": float(left), "right_value": float(right),
                })
        return matches

    @staticmethod
    def _value(candle: Candle, field: str | None) -> Decimal:
        if field is None:
            raise ValueError("Missing field")
        return Decimal(candle.volume) if field == "volume" else getattr(candle, field)

