from __future__ import annotations

import operator
from dataclasses import dataclass
from decimal import Decimal
from statistics import fmean

from .contracts import MarketRepository
from .domain import Candle, ScanCondition


FIELD_CATALOG = {
    "open": "Open Price", "high": "High Price", "low": "Low Price", "close": "Close Price", "volume": "Volume",
    "change_pct": "Daily Change %", "range_pct": "Daily Range %", "rsi14": "RSI (14)",
    "sma20": "SMA (20)", "sma50": "SMA (50)", "sma200": "SMA (200)",
    "volume_ratio20": "Volume / 20-Day Average", "previous_high20": "Previous 20-Day High",
    "previous_low20": "Previous 20-Day Low", "distance_52w_high_pct": "Distance From 52-Week High %",
    "distance_52w_low_pct": "Distance From 52-Week Low %", "doji": "Doji Pattern",
    "bullish_engulfing": "Bullish Engulfing", "bearish_engulfing": "Bearish Engulfing", "nr7": "Narrowest Range in 7 Days",
}
OPERATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "=": operator.eq, "!=": operator.ne}


@dataclass(frozen=True, slots=True)
class EvaluatedStock:
    candle: Candle
    metrics: dict[str, Decimal]


class MetricEngine:
    @staticmethod
    def evaluate(candles: list[Candle]) -> EvaluatedStock | None:
        if not candles:
            return None
        current = candles[-1]
        closes = [float(c.close) for c in candles]
        volumes = [c.volume for c in candles]
        metrics: dict[str, Decimal] = {
            "open": current.open, "high": current.high, "low": current.low,
            "close": current.close, "volume": Decimal(current.volume),
        }
        previous_close = candles[-2].close if len(candles) >= 2 else None
        metrics["change_pct"] = ((current.close / previous_close) - 1) * 100 if previous_close else Decimal(0)
        metrics["range_pct"] = ((current.high - current.low) / current.low) * 100 if current.low else Decimal(0)
        for period in (20, 50, 200):
            if len(closes) >= period:
                metrics[f"sma{period}"] = Decimal(str(fmean(closes[-period:])))
        if len(volumes) >= 20:
            average_volume = fmean(volumes[-20:])
            metrics["volume_ratio20"] = Decimal(str(current.volume / average_volume)) if average_volume else Decimal(0)
        if len(candles) >= 21:
            prior20 = candles[-21:-1]
            metrics["previous_high20"] = max(c.high for c in prior20)
            metrics["previous_low20"] = min(c.low for c in prior20)
        if len(candles) >= 252:
            year = candles[-252:]
            high52 = max(c.high for c in year)
            low52 = min(c.low for c in year)
            metrics["distance_52w_high_pct"] = ((high52 - current.close) / high52) * 100 if high52 else Decimal(0)
            metrics["distance_52w_low_pct"] = ((current.close - low52) / low52) * 100 if low52 else Decimal(0)
        rsi = calculate_rsi(closes)
        if rsi is not None:
            metrics["rsi14"] = rsi
        candle_range = current.high - current.low
        body = abs(current.close - current.open)
        metrics["doji"] = Decimal(1 if candle_range and body / candle_range <= Decimal("0.1") else 0)
        if len(candles) >= 2:
            previous = candles[-2]
            metrics["bullish_engulfing"] = Decimal(1 if previous.close < previous.open and current.close > current.open and current.open <= previous.close and current.close >= previous.open else 0)
            metrics["bearish_engulfing"] = Decimal(1 if previous.close > previous.open and current.close < current.open and current.open >= previous.close and current.close <= previous.open else 0)
        if len(candles) >= 7:
            ranges = [c.high - c.low for c in candles[-7:]]
            metrics["nr7"] = Decimal(1 if ranges[-1] == min(ranges) else 0)
        return EvaluatedStock(current, metrics)


class StrictScanner:
    def __init__(self, repository: MarketRepository) -> None:
        self.repository = repository

    def run(self, timeframe: str, conditions: list[ScanCondition], match_mode: str = "all") -> list[dict]:
        if timeframe != "1D":
            raise ValueError("V1 currently supports Daily candles only")
        if not conditions:
            raise ValueError("At least one condition is required")
        if match_mode not in {"all", "any"}:
            raise ValueError("Match mode must be all or any")
        self._validate(conditions)
        matches: list[dict] = []
        for candles in self.repository.candle_series(timeframe).values():
            stock = MetricEngine.evaluate(candles)
            if stock is None:
                continue
            checks = [self._matches(stock.metrics, condition) for condition in conditions]
            if (all(checks) if match_mode == "all" else any(checks)):
                candle = stock.candle
                matches.append({
                    "symbol": candle.symbol, "timestamp": candle.timestamp.isoformat(),
                    "open": float(candle.open), "high": float(candle.high), "low": float(candle.low),
                    "close": float(candle.close), "volume": candle.volume,
                    "change_pct": float(stock.metrics.get("change_pct", 0)),
                    "rsi14": float(stock.metrics["rsi14"]) if "rsi14" in stock.metrics else None,
                })
        return matches

    @staticmethod
    def _validate(conditions: list[ScanCondition]) -> None:
        for condition in conditions:
            if condition.field not in FIELD_CATALOG or condition.operator not in OPERATORS:
                raise ValueError("Unsupported field or operator")
            if condition.compare_mode == "field" and condition.compare_field not in FIELD_CATALOG:
                raise ValueError("A valid comparison field is required")
            if condition.compare_mode == "value" and condition.compare_value is None:
                raise ValueError("A comparison value is required")
            if condition.compare_mode not in {"field", "value"}:
                raise ValueError("Comparison mode must be field or value")

    @staticmethod
    def _matches(metrics: dict[str, Decimal], condition: ScanCondition) -> bool:
        if condition.field not in metrics:
            return False
        right = metrics.get(condition.compare_field) if condition.compare_mode == "field" else condition.compare_value
        return right is not None and OPERATORS[condition.operator](metrics[condition.field], right)


def calculate_rsi(values: list[float], period: int = 14) -> Decimal | None:
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(len(values) - period, len(values))]
    average_gain = fmean(max(change, 0) for change in changes)
    average_loss = fmean(max(-change, 0) for change in changes)
    if average_loss == 0:
        return Decimal(100)
    return Decimal(str(100 - (100 / (1 + average_gain / average_loss))))
