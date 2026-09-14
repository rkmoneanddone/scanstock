from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from scanstock.domain import Candle, Instrument
from scanstock.storage.sqlite_repository import SQLiteMarketRepository


def test_bulk_symbol_series_returns_latest_limit_in_chronological_order(tmp_path):
    repository = SQLiteMarketRepository(tmp_path / "bulk.db")
    repository.migrate()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    symbols = ["ONE", "TWO"]
    with repository.transaction() as transaction:
        transaction.upsert_instruments([Instrument(symbol, symbol, symbol) for symbol in symbols])
        transaction.upsert_candles([
            Candle(symbol, "1D", start + timedelta(days=index), Decimal("10"), Decimal("12"),
                   Decimal("9"), Decimal(str(10 + index)), 100, "fake")
            for symbol in symbols for index in range(3)
        ])
    series = repository.candle_series_for_symbols(symbols, "1D", 2)
    assert list(series) == symbols
    assert [candle.close for candle in series["ONE"]] == [Decimal("11"), Decimal("12")]
    assert [candle.timestamp for candle in series["TWO"]] == sorted(candle.timestamp for candle in series["TWO"])


def test_identical_candle_upsert_preserves_metric_cache(tmp_path):
    repository = SQLiteMarketRepository(tmp_path / "cache.db")
    repository.migrate()
    candle = Candle("ONE", "1D", datetime(2026, 1, 1, tzinfo=timezone.utc),
                    Decimal("10"), Decimal("12"), Decimal("9"), Decimal("11"), 100, "fake")
    with repository.transaction() as transaction:
        transaction.upsert_instruments([Instrument("ONE", "1", "One")])
        transaction.upsert_candles([candle])
    repository.save_metric_snapshots("1D", [(candle, {"close": Decimal("11")})])
    with repository.transaction() as transaction:
        transaction.upsert_candles([candle])
    assert "ONE" in repository.metric_snapshots("1D")

    changed = Candle("ONE", "1D", candle.timestamp, Decimal("10"), Decimal("13"),
                     Decimal("9"), Decimal("12"), 120, "fake")
    with repository.transaction() as transaction:
        transaction.upsert_candles([changed])
    assert "ONE" not in repository.metric_snapshots("1D")


def test_atomic_upsert_is_idempotent(tmp_path):
    repo = SQLiteMarketRepository(tmp_path / "test.db")
    repo.migrate()
    instrument = Instrument("TEST", "1", "Test")
    candle = Candle("TEST", "1D", datetime(2026, 1, 1, tzinfo=timezone.utc), Decimal("10"), Decimal("12"), Decimal("9"), Decimal("11"), 100, "fake")
    with repo.transaction() as transaction:
        transaction.upsert_instruments([instrument])
        transaction.upsert_candles([candle])
        transaction.upsert_candles([candle])
    assert repo.status_rows()[0][1] == 1
    assert repo.first_candle_date("TEST", "1D").isoformat() == "2026-01-01"
    assert repo.last_candle_date("TEST", "1D").isoformat() == "2026-01-01"


def test_transaction_rolls_back(tmp_path):
    repo = SQLiteMarketRepository(tmp_path / "test.db")
    repo.migrate()
    instrument = Instrument("TEST", "1", "Test")
    try:
        with repo.transaction() as transaction:
            transaction.upsert_instruments([instrument])
            raise RuntimeError("stop")
    except RuntimeError:
        pass
    assert repo.status_rows() == []


def test_sync_watermarks_and_history_bounds_are_independent(tmp_path):
    repo = SQLiteMarketRepository(tmp_path / "sync.db")
    repo.migrate()
    with repo.transaction() as tx:
        tx.upsert_instruments([Instrument("TEST", "1", "Test")])
        tx.record_sync("TEST", "1D", "SUCCESS", 0, "forward", date(2026, 9, 15))
        tx.mark_backfill_complete("TEST", "1D", date(1990, 1, 1))
    assert repo.last_sync_through("TEST", "1D") == date(2026, 9, 15)
    assert repo.is_backfill_complete("TEST", "1D")


def test_migration_recognizes_legacy_successful_full_history(tmp_path):
    repo = SQLiteMarketRepository(tmp_path / "legacy.db")
    repo.migrate()
    with repo.transaction() as tx:
        tx.upsert_instruments([Instrument("TEST", "1", "Test")])
        tx.record_sync("TEST", "1D", "SUCCESS", 100, "BACKFILL")
    assert not repo.is_backfill_complete("TEST", "1D")
    repo.migrate()
    assert repo.is_backfill_complete("TEST", "1D")


def test_candle_series_can_limit_each_symbol_to_recent_history(tmp_path):
    repo = SQLiteMarketRepository(tmp_path / "recent.db")
    repo.migrate()
    instrument = Instrument("TEST", "1", "Test")
    candles = [
        Candle("TEST", "1D", datetime(2026, 1, day, tzinfo=timezone.utc), Decimal("10"), Decimal("12"), Decimal("9"), Decimal("11"), 100, "fake")
        for day in range(1, 6)
    ]
    with repo.transaction() as tx:
        tx.upsert_instruments([instrument])
        tx.upsert_candles(candles)
    recent = repo.candle_series("1D", limit_per_symbol=2)["TEST"]
    assert [candle.timestamp.day for candle in recent] == [4, 5]


def test_chart_query_returns_only_requested_symbol_in_time_order(tmp_path):
    repo = SQLiteMarketRepository(tmp_path / "chart.db")
    repo.migrate()
    instruments = [Instrument("ONE", "1", "One"), Instrument("TWO", "2", "Two")]
    candles = [
        Candle(symbol, "1D", datetime(2026, 1, day, tzinfo=timezone.utc), Decimal("10"),
               Decimal("12"), Decimal("9"), Decimal("11"), 100, "fake")
        for symbol in ("ONE", "TWO") for day in range(1, 6)
    ]
    with repo.transaction() as tx:
        tx.upsert_instruments(instruments)
        tx.upsert_candles(candles)
    recent = repo.candles_for_symbol("one", "1D", 3)
    assert [candle.symbol for candle in recent] == ["ONE", "ONE", "ONE"]
    assert [candle.timestamp.day for candle in recent] == [3, 4, 5]
