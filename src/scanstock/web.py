from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .config import load_instruments
from .container import provider, repository, settings
from .contracts import MarketDataAuthenticationError
from .domain import ScanCondition
from .scanner import DAILY_HISTORY_LIMITS, FIELD_CATALOG, TIMEFRAMES, StrictScanner, aggregate_candles
from .services import DailyHistorySyncService

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"
PRESETS_PATH = ROOT / "config" / "scanners.json"
app = FastAPI(title="ScanStock", version="0.2.0")
app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="assets")
scanner = StrictScanner(repository(ROOT))
sync_lock = threading.RLock()
sync_job = {
    "running": False, "processed": 0, "total": 0, "message": "Market data has not been updated from this UI yet.",
    "started_at": None, "finished_at": None, "error": None,
}


def _sync_snapshot() -> dict:
    with sync_lock:
        return dict(sync_job)


def _needs_sync(repo, symbol: str, end: date) -> bool:
    first, last = repo.first_candle_date(symbol, "1D"), repo.last_candle_date(symbol, "1D")
    if first is None or last is None or not repo.is_backfill_complete(symbol, "1D"):
        return True
    synced = repo.last_sync_through(symbol, "1D")
    return max(value for value in (last, synced) if value is not None) < end


def _run_market_update() -> None:
    repo = repository(ROOT)
    end = date.today() + timedelta(days=1)
    try:
        instruments = list(load_instruments(ROOT).values())
        with repo.transaction() as transaction:
            transaction.upsert_instruments(instruments)
        pending = [item for item in instruments if _needs_sync(repo, item.symbol, end)]
        with sync_lock:
            sync_job.update(total=len(pending), processed=0,
                            message="Everything is already current." if not pending else f"Preparing {len(pending)} stocks…")
        service = DailyHistorySyncService(
            provider(ROOT), repo, settings(ROOT).initial_from_date, settings(ROOT).request_delay_seconds
        )
        for index, instrument in enumerate(pending, 1):
            with sync_lock:
                sync_job["message"] = f"Updating {instrument.symbol} · {index} of {len(pending)}"
            service.sync([instrument], end)
            with sync_lock:
                sync_job["processed"] = index
            if index % 100 == 0 and index < len(pending):
                for remaining in range(600, 0, -1):
                    with sync_lock:
                        sync_job["message"] = f"Batch complete · next 100 stocks in {remaining // 60}:{remaining % 60:02d}"
                    time.sleep(1)
        with sync_lock:
            sync_job["message"] = f"Market update complete · {len(pending)} stocks processed"
    except MarketDataAuthenticationError as exc:
        with sync_lock:
            sync_job.update(error=str(exc), message="Dhan login expired—update the token in .env and try again.")
    except Exception as exc:
        with sync_lock:
            sync_job.update(error=str(exc), message=f"Market update stopped: {exc}")
    finally:
        with sync_lock:
            sync_job.update(running=False, finished_at=datetime.now(timezone.utc).isoformat())


class ConditionRequest(BaseModel):
    field: str
    operator: Literal[">", ">=", "<", "<=", "=", "!="]
    compare_mode: Literal["field", "value"]
    compare_field: str | None = None
    compare_value: Decimal | None = None

    @field_validator("compare_value")
    @classmethod
    def finite_value(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("Value must be finite")
        return value


class ScanRequest(BaseModel):
    timeframe: Literal["1D", "1W", "1M", "3M", "6M", "1Y"] = "1D"
    match_mode: Literal["all", "any"] = "all"
    conditions: list[ConditionRequest] = Field(min_length=1, max_length=12)


@app.on_event("startup")
def initialize_database() -> None:
    repository(ROOT).migrate()


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/api/config")
def scanner_config() -> dict:
    return {
        "timeframes": [{"value": value, "label": label} for value, label in TIMEFRAMES.items()],
        "fields": [{"value": value, "label": label} for value, label in FIELD_CATALOG.items()],
        "operators": [
            {"value": ">", "label": "is above"}, {"value": ">=", "label": "is at least"},
            {"value": "<", "label": "is below"}, {"value": "<=", "label": "is at most"},
            {"value": "=", "label": "equals"}, {"value": "!=", "label": "does not equal"},
        ],
        "presets": json.loads(PRESETS_PATH.read_text(encoding="utf-8")),
    }


@app.get("/api/status")
def database_status() -> dict:
    rows = repository(ROOT).status_rows()
    loaded = sum(1 for row in rows if row[1] > 0)
    return {"configured_stocks": len(rows), "loaded_stocks": loaded, "total_candles": sum(row[1] for row in rows)}


@app.get("/api/market-update")
def market_update_status() -> dict:
    return _sync_snapshot()


@app.post("/api/market-update", status_code=202)
def start_market_update() -> dict:
    with sync_lock:
        if sync_job["running"]:
            raise HTTPException(status_code=409, detail="A market-data update is already running")
        sync_job.update(
            running=True, processed=0, total=0, error=None,
            started_at=datetime.now(timezone.utc).isoformat(), finished_at=None,
            message="Checking which stocks require data…",
        )
    threading.Thread(target=_run_market_update, name="scanstock-market-update", daemon=True).start()
    return _sync_snapshot()


@app.get("/api/chart/{symbol}")
def stock_chart(symbol: str, timeframe: Literal["1D", "1W", "1M", "3M", "6M", "1Y"] = "1D",
                limit: int = Query(default=120, ge=30, le=250)) -> dict:
    daily = repository(ROOT).candles_for_symbol(symbol, "1D", DAILY_HISTORY_LIMITS[timeframe])
    candles = aggregate_candles(daily, timeframe)[-limit:]
    if not candles:
        raise HTTPException(status_code=404, detail="No chart data is available for this stock")
    return {
        "symbol": candles[-1].symbol, "timeframe": TIMEFRAMES[timeframe],
        "candles": [{
            "timestamp": candle.timestamp.isoformat(), "open": float(candle.open),
            "high": float(candle.high), "low": float(candle.low), "close": float(candle.close),
            "volume": candle.volume,
        } for candle in candles],
    }


@app.post("/api/scan")
def run_scan(request: ScanRequest) -> dict:
    try:
        conditions = [ScanCondition(**condition.model_dump()) for condition in request.conditions]
        matches = scanner.run(request.timeframe, conditions, request.match_mode)
        return {"match_count": len(matches), "matches": matches}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
