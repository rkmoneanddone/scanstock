from __future__ import annotations

import time
from datetime import date, datetime, timezone
from decimal import Decimal

from dhanhq import DhanContext, dhanhq

from scanstock.domain import Candle, Instrument


class DhanMarketDataProvider:
    name = "dhan"

    def __init__(self, client_id: str, token: str, max_retries: int = 7, request_delay: float = 3.0) -> None:
        self._client = dhanhq(DhanContext(client_id, token))
        self._max_retries = max_retries
        self._request_delay = request_delay

    def daily_history(self, instrument: Instrument, start: date, end: date) -> list[Candle]:
        response = None
        for attempt in range(self._max_retries):
            response = self._client.historical_daily_data(
                security_id=instrument.security_id,
                exchange_segment=instrument.exchange_segment,
                instrument_type=instrument.instrument_type,
                from_date=start.isoformat(),
                to_date=end.isoformat(),
            )
            remarks = response.get("remarks", {}) if isinstance(response, dict) else {}
            if not isinstance(remarks, dict) or remarks.get("error_code") != "DH-904":
                break
            time.sleep(max(self._request_delay, min(2**attempt, 30)))
        if not isinstance(response, dict) or response.get("status") != "success":
            raise RuntimeError(f"Dhan request failed: {response}")
        data = response.get("data", {})
        required = ("timestamp", "open", "high", "low", "close", "volume")
        if any(key not in data for key in required):
            raise RuntimeError(f"Dhan response lacks candle fields: {response}")
        candles: list[Candle] = []
        for values in zip(*(data[key] for key in required), strict=True):
            timestamp, open_, high, low, close, volume = values
            dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
            candles.append(Candle(
                symbol=instrument.symbol, timeframe="1D", timestamp=dt,
                open=Decimal(str(open_)), high=Decimal(str(high)), low=Decimal(str(low)),
                close=Decimal(str(close)), volume=int(volume), provider=self.name,
            ))
        return candles
