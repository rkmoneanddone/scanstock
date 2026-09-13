from datetime import datetime, timezone
from decimal import Decimal

from scanstock.domain import Candle, Instrument
from scanstock.storage.sqlite_repository import SQLiteMarketRepository


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
