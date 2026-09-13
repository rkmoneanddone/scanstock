from datetime import datetime, timezone
from decimal import Decimal

from scanstock.domain import Candle, Instrument, ScanCondition
from scanstock.scanner import StrictScanner
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
    matches = StrictScanner(repo).run("1D", ScanCondition("close", ">", "field", compare_field="open"))
    assert [row["symbol"] for row in matches] == ["UP"]

