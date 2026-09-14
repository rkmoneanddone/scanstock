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
    "close_cross_above_ema9": "Close Crossed Above EMA 9", "close_cross_above_sma9": "Close Crossed Above SMA 9",
    "close_cross_above_wma9": "Close Crossed Above WMA 9",
    "volume_ratio20": "Volume / 20-Period Average", "previous_high20": "Previous 20-Period High",
    "previous_low20": "Previous 20-Period Low", "distance_52w_high_pct": "Distance From 52-Period High %",
    "distance_52w_low_pct": "Distance From 52-Period Low %", "doji": "Doji Pattern",
    "bullish_engulfing": "Bullish Engulfing", "bearish_engulfing": "Bearish Engulfing", "nr7": "Narrowest Range in 7 Days",
    "morning_star": "Morning Star", "evening_star": "Evening Star",
    "three_white_soldiers": "Three White Soldiers", "three_black_crows": "Three Black Crows",
    "bullish_fvg": "Bullish Fair Value Gap", "bearish_fvg": "Bearish Fair Value Gap",
    "fvg_gap_pct": "Fair Value Gap %", "volume_increasing": "Volume Increasing",
    "volume_decreasing": "Volume Decreasing", "volume_trend_ratio": "Recent / Previous 5-Period Volume",
    "price_trend_pct5": "5-Period Price Change %",
    "volume_up_price_down": "Volume Increasing / Price Decreasing",
    "volume_down_price_up": "Volume Decreasing / Price Increasing",
    "bearish_rsi_divergence": "Negative RSI Divergence", "bullish_rsi_divergence": "Positive RSI Divergence",
    "double_top": "Confirmed Double Top", "double_bottom": "Confirmed Double Bottom",
    "rsi_double_top": "RSI Double Top", "rsi_double_bottom": "RSI Double Bottom",
    "pattern_pivot_1": "First Pivot", "pattern_pivot_2": "Second Pivot",
    "pattern_neckline": "Pattern Neckline", "pattern_separation": "Pivot Separation",
    "all_time_high_breakout": "All-Time High Breakout", "previous_all_time_high": "Previous All-Time High",
    "distance_from_previous_ath_pct": "Distance From Previous All-Time High %",
    "ath_approach_first": "Approaching ATH — First Visit", "ath_approach_second": "Approaching ATH — Second Visit",
    "ath_approach_count": "ATH Approach Number", "ath_distance_below_pct": "Distance Below ATH %",
    "ath_first_close_above": "First Close Above ATH", "ath_second_close_above": "Second Close Above ATH",
    "ath_breakout_retest": "ATH Breakout Retest", "ath_breakout_reference": "ATH Breakout Reference",
    "ath_retest_distance_pct": "Retest Distance From ATH %",
    "vcp_setup": "VCP Setup Detected", "vcp_breakout": "VCP Breakout Detected",
    "vcp_contractions": "VCP Contractions", "vcp_outer_range_pct": "VCP Outer Range %",
    "vcp_middle_range_pct": "VCP Middle Range %", "vcp_inner_range_pct": "VCP Inner Range %",
    "vcp_volume_dryup_ratio": "VCP Volume Dry-Up Ratio", "vcp_pivot": "VCP Pivot Price",
    "vcp_distance_to_pivot_pct": "Distance to VCP Pivot %", "vcp_breakout_volume_ratio": "VCP Breakout Volume Ratio",
    "vcp_quality_score": "VCP Quality Score",
}
OPERATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "=": operator.eq, "!=": operator.ne}
TIMEFRAMES = {"1D": "Daily", "1W": "Weekly", "1M": "Monthly", "3M": "3 Months", "6M": "6 Months", "1Y": "Yearly"}
DAILY_HISTORY_LIMITS = {"1D": 260, "1W": 1600, "1M": 6500, "3M": 6500, "6M": 6500, "1Y": 6500}
METRIC_SCHEMA_VERSION = Decimal(4)


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
            "close": current.close, "volume": Decimal(current.volume), "__schema_version": METRIC_SCHEMA_VERSION,
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
        if len(closes) >= 10:
            prior_closes = closes[:-1]
            previous_close_decimal = candles[-2].close
            previous_ma9 = {
                "ema": moving_ema(prior_closes, 9),
                "sma": Decimal(str(fmean(prior_closes[-9:]))),
                "wma": moving_wma(prior_closes, 9),
            }
            for method, previous_average in previous_ma9.items():
                metrics[f"close_cross_above_{method}9"] = Decimal(int(
                    previous_close_decimal <= previous_average and current.close > metrics[f"{method}9"]
                ))
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
        add_candlestick_metrics(candles, metrics)
        add_volume_trend_metrics(candles, metrics)
        add_swing_pattern_metrics(candles, metrics)
        add_vcp_metrics(candles, metrics)
        return EvaluatedStock(current, metrics)


class StrictScanner:
    def __init__(self, repository: MarketRepository) -> None:
        self.repository = repository
        self._cache_lock = threading.RLock()
        self._cache_version: tuple[int, int] | None = None
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
        pattern_fields = {
            "morning_star", "evening_star", "three_white_soldiers", "three_black_crows",
            "bullish_fvg", "bearish_fvg", "volume_increasing", "volume_decreasing",
            "volume_up_price_down", "volume_down_price_up", "bearish_rsi_divergence",
            "bullish_rsi_divergence", "double_top", "double_bottom", "rsi_double_top", "rsi_double_bottom",
            "all_time_high_breakout",
            "ath_approach_first", "ath_approach_second", "ath_first_close_above", "ath_second_close_above",
            "ath_breakout_retest",
        }
        measurements = None
        if any(condition.field in pattern_fields for condition in conditions):
            selected = {condition.field for condition in conditions}
            keys = []
            if selected & {"bullish_fvg", "bearish_fvg"}:
                keys += ["fvg_gap_pct"]
            if selected & {"volume_increasing", "volume_decreasing", "volume_up_price_down", "volume_down_price_up"}:
                keys += ["volume_trend_ratio", "price_trend_pct5"]
            if selected & {"bearish_rsi_divergence", "bullish_rsi_divergence", "double_top", "double_bottom",
                           "rsi_double_top", "rsi_double_bottom"}:
                keys += ["pattern_pivot_1", "pattern_pivot_2", "pattern_neckline", "pattern_separation"]
            if "all_time_high_breakout" in selected:
                keys += ["previous_all_time_high", "distance_from_previous_ath_pct"]
            if selected & {"ath_approach_first", "ath_approach_second"}:
                keys += ["previous_all_time_high", "ath_distance_below_pct", "ath_approach_count"]
            if selected & {"ath_first_close_above", "ath_second_close_above"}:
                keys += ["ath_breakout_reference", "distance_from_previous_ath_pct"]
            if "ath_breakout_retest" in selected:
                keys += ["ath_breakout_reference", "ath_retest_distance_pct"]
            measurements = [{"metric": FIELD_CATALOG[key], "value": float(stock.metrics[key])}
                            for key in keys if key in stock.metrics]
        return {"timeframe": TIMEFRAMES[timeframe], "checks": checks, "vcp": vcp, "measurements": measurements}

    def _evaluated(self, timeframe: str) -> tuple[EvaluatedStock, ...]:
        version = self.repository.data_version()
        with self._cache_lock:
            if version != self._cache_version:
                self._cache_version = version
                self._evaluated_by_timeframe.clear()
            cached = self._evaluated_by_timeframe.get(timeframe)
            if cached is not None:
                return cached
            saved = self.repository.metric_snapshots(timeframe)
            stale_symbols = [symbol for symbol, (_, metrics) in saved.items()
                             if metrics.get("__schema_version") != METRIC_SCHEMA_VERSION]
            if stale_symbols:
                self.repository.delete_metric_snapshots(stale_symbols)
                for symbol in stale_symbols:
                    saved.pop(symbol, None)
            missing_symbols = self.repository.symbols_without_metric_snapshots(timeframe)
            if not missing_symbols:
                result = tuple(EvaluatedStock(candle, metrics) for candle, metrics in saved.values())
                self._evaluated_by_timeframe[timeframe] = result
                return result
            daily_series = self.repository.candle_series_for_symbols(
                missing_symbols, "1D", DAILY_HISTORY_LIMITS[timeframe]
            )
            missing_symbol_set = set(missing_symbols)
            evaluated = [EvaluatedStock(candle, metrics) for candle, metrics in saved.values()]
            for daily_candles in daily_series.values():
                aggregated = aggregate_candles(daily_candles, timeframe)
                stock = MetricEngine.evaluate(aggregated)
                if stock is not None:
                    previous_ath = self.repository.previous_all_time_high(stock.candle.symbol, timeframe)
                    breakout_reference = self.repository.previous_all_time_high(
                        stock.candle.symbol, timeframe, aggregated[-2].timestamp
                    ) if len(aggregated) >= 2 else None
                    add_ath_interaction_metrics(aggregated, stock.metrics, previous_ath, breakout_reference)
                    evaluated.append(stock)
            missing = [(stock.candle, stock.metrics) for stock in evaluated if stock.candle.symbol in missing_symbol_set]
            self.repository.save_metric_snapshots(timeframe, missing)
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


def add_ath_interaction_metrics(
    candles: list[Candle], metrics: dict[str, Decimal], previous_ath: Decimal | None,
    breakout_reference: Decimal | None,
) -> None:
    """Add deterministic ATH visit, breakout and immediate-retest signals."""
    for key in (
        "ath_approach_first", "ath_approach_second", "ath_first_close_above",
        "ath_second_close_above", "ath_breakout_retest",
    ):
        metrics[key] = Decimal(0)
    metrics.update({
        "previous_all_time_high": previous_ath or Decimal(0),
        "ath_breakout_reference": breakout_reference or Decimal(0),
        "ath_approach_count": Decimal(0), "ath_distance_below_pct": Decimal(0),
        "distance_from_previous_ath_pct": Decimal(0), "ath_retest_distance_pct": Decimal(0),
    })
    if not candles or previous_ath is None or previous_ath <= 0:
        return

    current = candles[-1]
    metrics["ath_distance_below_pct"] = ((previous_ath - current.close) / previous_ath) * 100
    metrics["distance_from_previous_ath_pct"] = ((current.close / previous_ath) - 1) * 100

    # Count separate entries into the zone from 3% below ATH up to ATH itself.
    formation_indexes = [index for index, candle in enumerate(candles[:-1]) if candle.high >= previous_ath]
    start = max(len(candles) - 60, (formation_indexes[-1] + 1) if formation_indexes else 0)
    in_zone = [previous_ath * Decimal("0.97") <= candle.close <= previous_ath for candle in candles[start:]]
    visits = sum(1 for index, value in enumerate(in_zone) if value and (index == 0 or not in_zone[index - 1]))
    metrics["ath_approach_count"] = Decimal(visits)
    if in_zone and in_zone[-1]:
        metrics["ath_approach_first"] = Decimal(int(visits == 1))
        metrics["ath_approach_second"] = Decimal(int(visits == 2))

    previous_close = candles[-2].close if len(candles) >= 2 else None
    metrics["ath_first_close_above"] = Decimal(int(
        previous_close is not None and previous_close <= previous_ath < current.close
    ))

    if breakout_reference is None or breakout_reference <= 0 or len(candles) < 2:
        return
    before_previous = candles[-3].close if len(candles) >= 3 else None
    previous = candles[-2]
    first_breakout_was_previous = (
        previous.close > breakout_reference
        and (before_previous is None or before_previous <= breakout_reference)
    )
    metrics["ath_second_close_above"] = Decimal(int(
        first_breakout_was_previous and current.close > breakout_reference
    ))

    # Immediate post-breakout retest: latest candle trades within 2% of the old ATH,
    # never closes below it, and follows the first confirmed close above that ATH.
    distance = ((current.low - breakout_reference) / breakout_reference) * 100
    metrics["ath_retest_distance_pct"] = distance
    touched_level = current.low <= breakout_reference * Decimal("1.02")
    held_as_support = current.close >= breakout_reference
    metrics["ath_breakout_retest"] = Decimal(int(
        first_breakout_was_previous and touched_level and held_as_support
    ))


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


def add_candlestick_metrics(candles: list[Candle], metrics: dict[str, Decimal]) -> None:
    for key in ("morning_star", "evening_star", "three_white_soldiers", "three_black_crows",
                "bullish_fvg", "bearish_fvg"):
        metrics[key] = Decimal(0)
    metrics["fvg_gap_pct"] = Decimal(0)
    if len(candles) < 3:
        return
    first, middle, last = candles[-3:]

    def body(candle: Candle) -> Decimal:
        return abs(candle.close - candle.open)

    def body_ratio(candle: Candle) -> Decimal:
        span = candle.high - candle.low
        return body(candle) / span if span else Decimal(0)

    first_midpoint = (first.open + first.close) / 2
    small_middle = body(middle) <= body(first) * Decimal("0.5")
    metrics["morning_star"] = Decimal(int(
        first.close < first.open and body_ratio(first) >= Decimal("0.5") and small_middle
        and last.close > last.open and last.close > first_midpoint
    ))
    metrics["evening_star"] = Decimal(int(
        first.close > first.open and body_ratio(first) >= Decimal("0.5") and small_middle
        and last.close < last.open and last.close < first_midpoint
    ))

    bullish = all(c.close > c.open and body_ratio(c) >= Decimal("0.5") for c in (first, middle, last))
    bearish = all(c.close < c.open and body_ratio(c) >= Decimal("0.5") for c in (first, middle, last))
    opens_inside = first.open <= middle.open <= first.close and middle.open <= last.open <= middle.close
    bearish_opens_inside = first.close <= middle.open <= first.open and middle.close <= last.open <= middle.open
    metrics["three_white_soldiers"] = Decimal(int(bullish and opens_inside and first.close < middle.close < last.close))
    metrics["three_black_crows"] = Decimal(int(bearish and bearish_opens_inside and first.close > middle.close > last.close))

    if last.low > first.high:
        metrics["bullish_fvg"] = Decimal(1)
        metrics["fvg_gap_pct"] = ((last.low - first.high) / first.high) * 100 if first.high else Decimal(0)
    elif last.high < first.low:
        metrics["bearish_fvg"] = Decimal(1)
        metrics["fvg_gap_pct"] = ((first.low - last.high) / first.low) * 100 if first.low else Decimal(0)


def add_volume_trend_metrics(candles: list[Candle], metrics: dict[str, Decimal]) -> None:
    for key in ("volume_increasing", "volume_decreasing", "volume_up_price_down", "volume_down_price_up"):
        metrics[key] = Decimal(0)
    if len(candles) < 11:
        return
    previous_volume = fmean(c.volume for c in candles[-11:-6])
    recent_volume = fmean(c.volume for c in candles[-5:])
    ratio = Decimal(str(recent_volume / previous_volume)) if previous_volume else Decimal(0)
    price_change = ((candles[-1].close / candles[-6].close) - 1) * 100 if candles[-6].close else Decimal(0)
    increasing, decreasing = ratio >= Decimal("1.15"), ratio <= Decimal("0.85")
    metrics.update({
        "volume_trend_ratio": ratio, "price_trend_pct5": price_change,
        "volume_increasing": Decimal(int(increasing)), "volume_decreasing": Decimal(int(decreasing)),
        "volume_up_price_down": Decimal(int(increasing and price_change < 0)),
        "volume_down_price_up": Decimal(int(decreasing and price_change > 0)),
    })


def add_swing_pattern_metrics(candles: list[Candle], metrics: dict[str, Decimal]) -> None:
    keys = ("bearish_rsi_divergence", "bullish_rsi_divergence", "double_top", "double_bottom",
            "rsi_double_top", "rsi_double_bottom")
    metrics.update({key: Decimal(0) for key in keys})
    if len(candles) < 35:
        return
    window = candles[-80:]
    closes = [float(c.close) for c in window]
    rsi_values = [calculate_rsi(closes[:index + 1]) for index in range(len(closes))]

    def pivots(values: list[Decimal | None], high: bool) -> list[int]:
        found = []
        for index in range(2, len(values) - 2):
            value = values[index]
            neighbors = values[index - 2:index] + values[index + 1:index + 3]
            if value is not None and all(item is not None and (value > item if high else value < item) for item in neighbors):
                found.append(index)
        return found

    price_highs = pivots([c.high for c in window], True)
    price_lows = pivots([c.low for c in window], False)
    rsi_highs, rsi_lows = pivots(rsi_values, True), pivots(rsi_values, False)

    def record(first: Decimal, second: Decimal, neckline: Decimal, separation: int) -> None:
        metrics.update({"pattern_pivot_1": first, "pattern_pivot_2": second,
                        "pattern_neckline": neckline, "pattern_separation": Decimal(separation)})

    if len(price_highs) >= 2:
        a, b = price_highs[-2:]
        first, second = window[a].high, window[b].high
        valley = min(c.low for c in window[a:b + 1])
        close_enough = abs(second - first) / first <= Decimal("0.03") if first else False
        meaningful_valley = (min(first, second) - valley) / min(first, second) >= Decimal("0.03") if min(first, second) else False
        metrics["double_top"] = Decimal(int(close_enough and meaningful_valley and window[-1].close < valley))
        rsi_a, rsi_b = rsi_values[a], rsi_values[b]
        metrics["bearish_rsi_divergence"] = Decimal(int(rsi_a is not None and rsi_b is not None and second > first and rsi_b < rsi_a))
        if metrics["double_top"] or metrics["bearish_rsi_divergence"]:
            record(first, second, valley, b - a)
    if len(price_lows) >= 2:
        a, b = price_lows[-2:]
        first, second = window[a].low, window[b].low
        peak = max(c.high for c in window[a:b + 1])
        close_enough = abs(second - first) / first <= Decimal("0.03") if first else False
        meaningful_peak = (peak - max(first, second)) / max(first, second) >= Decimal("0.03") if max(first, second) else False
        metrics["double_bottom"] = Decimal(int(close_enough and meaningful_peak and window[-1].close > peak))
        rsi_a, rsi_b = rsi_values[a], rsi_values[b]
        metrics["bullish_rsi_divergence"] = Decimal(int(rsi_a is not None and rsi_b is not None and second < first and rsi_b > rsi_a))
        if metrics["double_bottom"] or metrics["bullish_rsi_divergence"]:
            record(first, second, peak, b - a)
    if len(rsi_highs) >= 2:
        a, b = rsi_highs[-2:]
        first, second = rsi_values[a], rsi_values[b]
        valley = min(value for value in rsi_values[a:b + 1] if value is not None)
        metrics["rsi_double_top"] = Decimal(int(abs(second - first) <= 5 and min(first, second) - valley >= 5 and rsi_values[-1] is not None and rsi_values[-1] < valley))
    if len(rsi_lows) >= 2:
        a, b = rsi_lows[-2:]
        first, second = rsi_values[a], rsi_values[b]
        peak = max(value for value in rsi_values[a:b + 1] if value is not None)
        metrics["rsi_double_bottom"] = Decimal(int(abs(second - first) <= 5 and peak - max(first, second) >= 5 and rsi_values[-1] is not None and rsi_values[-1] > peak))


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
