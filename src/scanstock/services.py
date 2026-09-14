from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Iterable

from .contracts import MarketDataAuthenticationError, MarketDataProvider, MarketDataUnavailableError, MarketRepository
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
            synced_through = self.repository.last_sync_through(instrument.symbol, "1D")
            ranges: list[tuple[str, date, date]] = []
            if first is None or last is None:
                ranges.append(("FULL", self.initial_start, end))
            else:
                if self.initial_start < first and not self.repository.is_backfill_complete(instrument.symbol, "1D"):
                    ranges.append(("BACKFILL", self.initial_start, first))
                latest_covered = max(value for value in (last, synced_through) if value is not None)
                if latest_covered < end:
                    ranges.append(("FORWARD", last, end))
            if not ranges:
                print(f"[CURRENT] {instrument.symbol}: {first} -> {last}")
                continue
            for mode, start, range_end in ranges:
                print(f"[{mode}] {instrument.symbol}: {start} -> {range_end}")
                try:
                    candles = self._fetch(instrument, mode, start, range_end)
                    with self.repository.transaction() as transaction:
                        rows = transaction.upsert_candles(candles)
                        attempted_through = range_end if mode in {"FULL", "FORWARD"} else None
                        transaction.record_sync(instrument.symbol, "1D", "SUCCESS", rows, f"{mode} through {range_end}", attempted_through)
                        if mode == "FULL":
                            transaction.mark_backfill_complete(instrument.symbol, "1D", self.initial_start)
                    print(f"[OK] {instrument.symbol}: {rows} candles")
                except MarketDataAuthenticationError as exc:
                    with self.repository.transaction() as transaction:
                        transaction.record_sync(instrument.symbol, "1D", "AUTH_FAILED", 0, str(exc))
                    print(f"[STOPPED] {instrument.symbol}: {exc}")
                    raise
                except MarketDataUnavailableError as exc:
                    if mode == "BACKFILL":
                        with self.repository.transaction() as transaction:
                            transaction.mark_backfill_complete(instrument.symbol, "1D", start)
                            transaction.record_sync(instrument.symbol, "1D", "NO_EARLIER_DATA", 0, str(exc))
                        print(f"[COMPLETE] {instrument.symbol}: no earlier Dhan history")
                    else:
                        with self.repository.transaction() as transaction:
                            transaction.record_sync(instrument.symbol, "1D", "FAILED", 0, f"{mode}: {exc}")
                        print(f"[FAILED] {instrument.symbol}: {exc}")
                except Exception as exc:
                    with self.repository.transaction() as transaction:
                        transaction.record_sync(instrument.symbol, "1D", "FAILED", 0, f"{mode}: {exc}")
                    print(f"[FAILED] {instrument.symbol}: {exc}")
                time.sleep(self.delay)

    def _fetch(self, instrument: Instrument, mode: str, start: date, end: date):
        try:
            return self.provider.daily_history(instrument, start, end)
        except MarketDataUnavailableError:
            if mode != "FULL":
                raise

        # Some Dhan instruments reject one very large range. Fetch consecutive
        # five-year windows so pre-listing windows can be skipped without losing
        # the instrument's earliest available candles.
        candles = []
        window_start = start
        while window_start < end:
            window_end = min(date(window_start.year + 5, 1, 1), end)
            time.sleep(self.delay)
            try:
                candles.extend(self.provider.daily_history(instrument, window_start, window_end))
            except MarketDataUnavailableError:
                pass
            window_start = window_end
        if not candles:
            raise MarketDataUnavailableError(f"Dhan has no data for {start} -> {end}")
        print(f"[RECOVERED] {instrument.symbol}: {len(candles)} candles from chunked Dhan history")
        return candles
