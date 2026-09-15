from datetime import date

from scanstock.contracts import MarketDataAuthenticationError, MarketDataRangeError, MarketDataUnavailableError
from scanstock.domain import Instrument
from scanstock.services import DailyHistorySyncService


class RecoveringProvider:
    name = "fake"

    def __init__(self):
        self.starts = []

    def daily_history(self, instrument, start, end):
        self.starts.append(start)
        if (end - start).days > 366 * 5:
            raise MarketDataRangeError("range too broad")
        if end.year <= 1995:
            raise MarketDataUnavailableError("no data")
        return [object()]


def test_full_fetch_moves_past_pre_listing_years():
    provider = RecoveringProvider()
    service = DailyHistorySyncService(provider, None, date(1990, 1, 1), 0)
    candles = service._fetch(Instrument("TEST", "1", "Test"), "FULL", date(1990, 1, 1), date(2026, 9, 15))
    assert len(candles) == 7
    assert provider.starts == [date(1990, 1, 1), date(1990, 1, 1), date(1995, 1, 1), date(2000, 1, 1), date(2005, 1, 1), date(2010, 1, 1), date(2015, 1, 1), date(2020, 1, 1), date(2025, 1, 1)]


class ExpiredProvider:
    name = "fake"

    def daily_history(self, instrument, start, end):
        raise MarketDataAuthenticationError("expired")


def test_authentication_failure_is_not_treated_as_missing_market_data():
    service = DailyHistorySyncService(ExpiredProvider(), None, date(1990, 1, 1), 0)
    try:
        service._fetch(Instrument("TEST", "1", "Test"), "FULL", date(1990, 1, 1), date(2026, 9, 15))
    except MarketDataAuthenticationError:
        pass
    else:
        raise AssertionError("authentication failure must stop the sync")
