from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Iterable

from .contracts import MarketDataProvider, MarketRepository
from .domain import Instrument


class DailyHistorySyncService:
    def __init__(self, provider: MarketDataProvider, repository: MarketRepository, initial_start: date, delay: float) -> None:
        self.provider = provider
        self.repository = repository
        self.initial_start = initial_start
        self.delay = delay

    def sync(self, instruments: Iterable[Instrument], end: date) -> None:
        for instrument in instruments:
            first = self.repository.first_candle_date(instrument.symbol, "1D")
            last = self.repository.last_candle_date(instrument.symbol, "1D")
            ranges: list[tuple[str, date, date]] = []
            if first is None or last is None:
                ranges.append(("FULL", self.initial_start, end))
            else:
                if self.initial_start < first:
                    ranges.append(("BACKFILL", self.initial_start, first))
                if last < end:
                    ranges.append(("FORWARD", last, end))
            if not ranges:
                print(f"[CURRENT] {instrument.symbol}: {first} -> {last}")
                continue
            for mode, start, range_end in ranges:
                print(f"[{mode}] {instrument.symbol}: {start} -> {range_end}")
                try:
                    candles = self.provider.daily_history(instrument, start, range_end)
                    with self.repository.transaction() as transaction:
                        rows = transaction.upsert_candles(candles)
                        transaction.record_sync(instrument.symbol, "1D", "SUCCESS", rows, mode)
                    print(f"[OK] {instrument.symbol}: {rows} candles")
                except Exception as exc:
                    with self.repository.transaction() as transaction:
                        transaction.record_sync(instrument.symbol, "1D", "FAILED", 0, f"{mode}: {exc}")
                    print(f"[FAILED] {instrument.symbol}: {exc}")
                time.sleep(self.delay)
