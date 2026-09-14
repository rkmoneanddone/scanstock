from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .container import repository
from .domain import ScanCondition
from .scanner import FIELD_CATALOG, TIMEFRAMES, StrictScanner

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"
PRESETS_PATH = ROOT / "config" / "scanners.json"
app = FastAPI(title="ScanStock", version="0.2.0")
app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="assets")
scanner = StrictScanner(repository(ROOT))


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


@app.post("/api/scan")
def run_scan(request: ScanRequest) -> dict:
    try:
        conditions = [ScanCondition(**condition.model_dump()) for condition in request.conditions]
        matches = scanner.run(request.timeframe, conditions, request.match_mode)
        return {"match_count": len(matches), "matches": matches}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
