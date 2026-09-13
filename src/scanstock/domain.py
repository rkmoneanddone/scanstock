from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    security_id: str
    display_name: str
    exchange_segment: str = "NSE_EQ"
    instrument_type: str = "EQUITY"


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    provider: str


@dataclass(frozen=True, slots=True)
class ScanCondition:
    field: str
    operator: str
    compare_mode: str
    compare_value: Decimal | None = None
    compare_field: str | None = None
