from __future__ import annotations

import operator
import threading
from dataclasses import dataclass
from decimal import Decimal
from statistics import fmean

from .contracts import MarketRepository
from .domain import Candle, ScanCondition


FIELD_CATALOG = {
    "open": "Open Price", "high": "High Price", "low": "Low Price", "close": "Close Price", "volume": "Volume",
    "change_pct": "Period Change %", "range_pct": "Period Range %", "rsi14": "RSI (14)",
    "sma9": "SMA (9)", "sma20": "SMA (20)", "sma21": "SMA (21)", "sma50": "SMA (50)", "sma200": "SMA (200)",
    "ema9": "EMA (9)", "ema21": "EMA (21)", "ema50": "EMA (50)", "ema200": "EMA (200)",
    "wma9": "WMA (9)", "wma21": "WMA (21)", "wma50": "WMA (50)", "wma200": "WMA (200)",
    "ema9_cross_above_ema21": "EMA 9 Crossed Above EMA 21",
    "ema9_cross_below_ema21": "EMA 9 Crossed Below EMA 21",
    "volume_ratio20": "Volume / 20-Period Average", "previous_high20": "Previous 20-Period High",
    "previous_low20": "Previous 20-Period Low", "distance_52w_high_pct": "Distance From 52-Period High %",
    "distance_52w_low_pct": "Distance From 52-Period Low %", "doji": "Doji Pattern",
    "bullish_engulfing": "Bullish Engulfing", "bearish_engulfing": "Bearish Engulfing", "nr7": "Narrowest Range in 7 Days",
    "vcp_setup": "VCP Setup Detected", "vcp_breakout": "VCP Breakout Detected",
    "vcp_contractions": "VCP Contractions", "vcp_outer_range_pct": "VCP Outer Range %",
    "vcp_middle_range_pct": "VCP Middle Range %", "vcp_inner_range_pct": "VCP Inner Range %",
    "vcp_volume_dryup_ratio": "VCP Volume Dry-Up Ratio", "vcp_pivot": "VCP Pivot Price",
    "vcp_distance_to_pivot_pct": "Distance to VCP Pivot %", "vcp_breakout_volume_ratio": "VCP Breakout Volume Ratio",
    "vcp_quality_score": "VCP Quality Score",
}
OPERATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "=": operator.eq, "!=": operator.ne}
TIMEFRAMES = {"1D": "Daily", "1W": "Weekly", "1M": "Monthly", "3M": "3 Months", "6M": "6 Months", "1Y": "Yearly"}


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
        for period in (9, 20, 21, 50, 200):
            if len(closes) >= period:
                metrics[f"sma{period}"] = Decimal(str(fmean(closes[-period:])))
        for period in (9, 21, 50, 200):
            if len(closes) >= period:
                metrics[f"ema{period}"] = moving_ema(closes, period)
                metrics[f"wma{period}"] = moving_wma(closes, period)
        if len(closes) >= 22:
            previous_ema9, previous_ema21 = moving_ema(closes[:-1], 9), moving_ema(closes[:-1], 21)
            current_ema9, current_ema21 = metrics["ema9"], metrics["ema21"]
            metrics["ema9_cross_above_ema21"] = Decimal(1 if previous_ema9 <= previous_ema21 and current_ema9 > current_ema21 else 0)
            metrics["ema9_cross_below_ema21"] = Decimal(1 if previous_ema9 >= previous_ema21 and current_ema9 < current_ema21 else 0)
        if len(volumes) >= 20:
            average_volume = fmean(volumes[-20:])
            metrics["volume_ratio20"] = Decimal(str(current.volume / average_volume)) if average_volume else Decimal(0)
        if len(candles) >= 21:
            prior20 = candles[-21:-1]
            metrics["previous_high20"] = max(c.high for c in prior20)
            metrics["previous_low20"] = min(c.low for c in prior20)
        if len(candles) >= 52:
            window52 = candles[-52:]
            high52 = max(c.high for c in window52)
            low52 = min(c.low for c in window52)
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
        add_vcp_metrics(candles, metrics)
        return EvaluatedStock(current, metrics)


class StrictScanner:
    def __init__(self, repository: MarketRepository) -> None:
        self.repository = repository
        self._cache_lock = threading.RLock()
        self._cache_version: tuple[int, int] | None = None
        self._daily_series: dict[str, list[Candle]] | None = None
        self._evaluated_by_timeframe: dict[str, tuple[EvaluatedStock, ...]] = {}

    def run(self, timeframe: str, conditions: list[ScanCondition], match_mode: str = "all") -> list[dict]:
        if timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported timeframe")
        if not conditions:
            raise ValueError("At least one condition is required")
        if match_mode not in {"all", "any"}:
            raise ValueError("Match mode must be all or any")
        self._validate(conditions)
        matches: list[dict] = []
        for stock in self._evaluated(timeframe):
            checks = [self._matches(stock.metrics, condition) for condition in conditions]
            if (all(checks) if match_mode == "all" else any(checks)):
                candle = stock.candle
                matches.append({
                    "symbol": candle.symbol, "timestamp": candle.timestamp.isoformat(),
                    "open": float(candle.open), "high": float(candle.high), "low": float(candle.low),
                    "close": float(candle.close), "volume": candle.volume,
                    "change_pct": float(stock.metrics.get("change_pct", 0)),
                    "rsi14": float(stock.metrics["rsi14"]) if "rsi14" in stock.metrics else None,
                    "details": self._details(stock, conditions, timeframe),
                })
        return matches

    @staticmethod
    def _details(stock: EvaluatedStock, conditions: list[ScanCondition], timeframe: str) -> dict:
        checks = []
        for condition in conditions:
            left = stock.metrics.get(condition.field)
            right = stock.metrics.get(condition.compare_field) if condition.compare_mode == "field" else condition.compare_value
            passed = left is not None and right is not None and OPERATORS[condition.operator](left, right)
            checks.append({
                "metric": FIELD_CATALOG[condition.field], "actual": float(left) if left is not None else None,
                "operator": condition.operator,
                "comparison": FIELD_CATALOG.get(condition.compare_field, "Fixed value"),
                "target": float(right) if right is not None else None, "passed": passed,
            })
        vcp = None
        if any(condition.field.startswith("vcp_") for condition in conditions):
            keys = (
                "vcp_contractions", "vcp_outer_range_pct", "vcp_middle_range_pct", "vcp_inner_range_pct",
                "vcp_volume_dryup_ratio", "vcp_pivot", "vcp_distance_to_pivot_pct",
                "vcp_breakout_volume_ratio", "vcp_quality_score",
            )
            vcp = [{"metric": FIELD_CATALOG[key], "value": float(stock.metrics[key])} for key in keys if key in stock.metrics]
        return {"timeframe": TIMEFRAMES[timeframe], "checks": checks, "vcp": vcp}

    def _evaluated(self, timeframe: str) -> tuple[EvaluatedStock, ...]:
        version = self.repository.data_version()
        with self._cache_lock:
            if version != self._cache_version:
                self._cache_version = version
                self._daily_series = None
                self._evaluated_by_timeframe.clear()
            cached = self._evaluated_by_timeframe.get(timeframe)
            if cached is not None:
                return cached
            if self._daily_series is None:
                self._daily_series = self.repository.candle_series("1D")
            evaluated = []
            for daily_candles in self._daily_series.values():
                stock = MetricEngine.evaluate(aggregate_candles(daily_candles, timeframe))
                if stock is not None:
                    evaluated.append(stock)
            result = tuple(evaluated)
            self._evaluated_by_timeframe[timeframe] = result
            return result

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


def moving_ema(values: list[float], period: int) -> Decimal:
    multiplier = 2 / (period + 1)
    result = fmean(values[:period])
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return Decimal(str(result))


def moving_wma(values: list[float], period: int) -> Decimal:
    window = values[-period:]
    denominator = period * (period + 1) / 2
    return Decimal(str(sum(value * weight for weight, value in enumerate(window, 1)) / denominator))


def add_vcp_metrics(candles: list[Candle], metrics: dict[str, Decimal]) -> None:
    defaults = {
        "vcp_setup": 0, "vcp_breakout": 0, "vcp_contractions": 0,
        "vcp_outer_range_pct": 0, "vcp_middle_range_pct": 0, "vcp_inner_range_pct": 0,
        "vcp_volume_dryup_ratio": 0, "vcp_pivot": 0, "vcp_distance_to_pivot_pct": 0,
        "vcp_breakout_volume_ratio": 0, "vcp_quality_score": 0,
    }
    metrics.update({key: Decimal(value) for key, value in defaults.items()})
    if len(candles) < 62 or "sma50" not in metrics:
        return

    current, history = candles[-1], candles[:-1]

    def range_pct(window: list[Candle]) -> Decimal:
        high, low = max(c.high for c in window), min(c.low for c in window)
        return ((high - low) / low) * 100 if low else Decimal(0)

    outer, middle, inner = range_pct(history[-60:]), range_pct(history[-30:]), range_pct(history[-15:])
    contractions = 1 + int(middle < outer) + int(inner < middle)
    recent_volume = fmean(c.volume for c in history[-10:])
    prior_volume = fmean(c.volume for c in history[-40:-10])
    dryup = Decimal(str(recent_volume / prior_volume)) if prior_volume else Decimal(0)
    average20 = fmean(c.volume for c in history[-20:])
    breakout_volume = Decimal(str(current.volume / average20)) if average20 else Decimal(0)
    pivot = max(c.high for c in history[-60:])
    distance = ((pivot - current.close) / pivot) * 100 if pivot else Decimal(0)
    trend = current.close > metrics["sma50"] and current.close > history[-60].close
    contracting = contractions == 3 and middle <= Decimal(25) and inner <= Decimal(15)
    volume_dry = dryup <= Decimal("0.8")
    near_pivot = Decimal(0) <= distance <= Decimal(8)
    setup = trend and contracting and volume_dry and near_pivot
    breakout = trend and contracting and current.close > pivot and breakout_volume >= Decimal("1.5")
    score = (
        (25 if trend else 0) + (25 if contractions == 3 else 10 if contractions == 2 else 0)
        + (20 if volume_dry else 0) + (15 if near_pivot else 0) + (15 if inner <= Decimal(10) else 0)
    )
    metrics.update({
        "vcp_setup": Decimal(int(setup)), "vcp_breakout": Decimal(int(breakout)),
        "vcp_contractions": Decimal(contractions), "vcp_outer_range_pct": outer,
        "vcp_middle_range_pct": middle, "vcp_inner_range_pct": inner,
        "vcp_volume_dryup_ratio": dryup, "vcp_pivot": pivot,
        "vcp_distance_to_pivot_pct": distance, "vcp_breakout_volume_ratio": breakout_volume,
        "vcp_quality_score": Decimal(score),
    })


def aggregate_candles(candles: list[Candle], timeframe: str) -> list[Candle]:
    if timeframe == "1D":
        return candles
    buckets: dict[tuple[int, ...], list[Candle]] = {}
    for candle in candles:
        dt = candle.timestamp
        if timeframe == "1W":
            iso = dt.isocalendar(); key = (iso.year, iso.week)
        elif timeframe == "1M":
            key = (dt.year, dt.month)
        elif timeframe == "3M":
            key = (dt.year, (dt.month - 1) // 3)
        elif timeframe == "6M":
            key = (dt.year, (dt.month - 1) // 6)
        else:
            key = (dt.year,)
        buckets.setdefault(key, []).append(candle)
    result: list[Candle] = []
    for period in buckets.values():
        first, last = period[0], period[-1]
        result.append(Candle(
            symbol=last.symbol, timeframe=timeframe, timestamp=last.timestamp,
            open=first.open, high=max(item.high for item in period), low=min(item.low for item in period),
            close=last.close, volume=sum(item.volume for item in period), provider=last.provider,
        ))
    return result
