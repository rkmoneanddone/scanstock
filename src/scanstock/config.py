from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .domain import Instrument


@dataclass(frozen=True, slots=True)
class Settings:
    root: Path
    database_url: str
    provider: str
    timeframe: str
    initial_from_date: date
    request_delay_seconds: float
    max_retries: int
    symbols: tuple[str, ...]


def load_settings(root: Path) -> Settings:
    raw = tomllib.loads((root / "config" / "app.toml").read_text(encoding="utf-8"))
    return Settings(
        root=root,
        database_url=raw["app"]["database_url"],
        provider=raw["market_data"]["provider"],
        timeframe=raw["market_data"]["timeframe"],
        initial_from_date=date.fromisoformat(raw["market_data"]["initial_from_date"]),
        request_delay_seconds=float(raw["market_data"]["request_delay_seconds"]),
        max_retries=int(raw["market_data"]["max_retries"]),
        symbols=tuple(raw["universe"]["symbols"]),
    )


def load_instruments(root: Path) -> dict[str, Instrument]:
    rows = json.loads((root / "config" / "instruments.json").read_text(encoding="utf-8"))
    return {row["symbol"]: Instrument(**row) for row in rows}

