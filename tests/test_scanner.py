from datetime import datetime, timezone
from decimal import Decimal

from scanstock.domain import Candle, Instrument, ScanCondition
from scanstock.scanner import StrictScanner, aggregate_candles
from scanstock.storage.sqlite_repository import SQLiteMarketRepository


def test_strict_field_comparison_returns_only_matches(tmp_path):
    repo = SQLiteMarketRepository(tmp_path / "scanner.db")
    repo.migrate()
    instruments = [Instrument("UP", "1", "Up"), Instrument("DOWN", "2", "Down")]
    candles = [
        Candle("UP", "1D", datetime(2026, 1, 1, tzinfo=timezone.utc), Decimal("10"), Decimal("12"), Decimal("9"), Decimal("11"), 100, "fake"),
        Candle("DOWN", "1D", datetime(2026, 1, 1, tzinfo=timezone.utc), Decimal("10"), Decimal("11"), Decimal("8"), Decimal("9"), 100, "fake"),
    ]
    with repo.transaction() as tx:
        tx.upsert_instruments(instruments)
        tx.upsert_candles(candles)
    matches = StrictScanner(repo).run("1D", [ScanCondition("close", ">", "field", compare_field="open")])
    assert [row["symbol"] for row in matches] == ["UP"]


def test_multiple_conditions_support_all_and_any(tmp_path):
    repo = SQLiteMarketRepository(tmp_path / "multi.db")
    repo.migrate()
    with repo.transaction() as tx:
        tx.upsert_instruments([Instrument("UP", "1", "Up"), Instrument("DOWN", "2", "Down")])
        tx.upsert_candles([
            Candle("UP", "1D", datetime(2026, 1, 1, tzinfo=timezone.utc), Decimal("10"), Decimal("13"), Decimal("9"), Decimal("12"), 200, "fake"),
            Candle("DOWN", "1D", datetime(2026, 1, 1, tzinfo=timezone.utc), Decimal("10"), Decimal("11"), Decimal("7"), Decimal("8"), 150, "fake"),
        ])
    conditions = [
        ScanCondition("close", ">", "field", compare_field="open"),
        ScanCondition("volume", ">=", "value", compare_value=Decimal("100")),
    ]
    assert [row["symbol"] for row in StrictScanner(repo).run("1D", conditions, "all")] == ["UP"]
    assert [row["symbol"] for row in StrictScanner(repo).run("1D", conditions, "any")] == ["DOWN", "UP"]


def test_daily_candles_are_aggregated_into_weekly_ohlcv():
    candles = [
        Candle("TEST", "1D", datetime(2026, 1, day, tzinfo=timezone.utc), Decimal(str(9 + day)), Decimal(str(11 + day)), Decimal(str(8 + day)), Decimal(str(10 + day)), day * 100, "fake")
        for day in range(1, 6)
    ]
    weekly = aggregate_candles(candles, "1W")
    assert len(weekly) == 2
    assert weekly[0].open == Decimal("10")
    assert weekly[0].close == Decimal("14")
    assert weekly[0].volume == 1000
