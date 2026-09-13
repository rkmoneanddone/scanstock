from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from .container import repository
from .domain import ScanCondition
from .scanner import FIELDS, OPERATORS, StrictScanner


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"
app = FastAPI(title="ScanStock", version="0.1.0")
app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="assets")


class ScanRequest(BaseModel):
    timeframe: Literal["1D"] = "1D"
    field: Literal["open", "high", "low", "close", "volume"]
    operator: Literal[">", ">=", "<", "<=", "=", "!="]
    compare_mode: Literal["field", "value"]
    compare_field: Literal["open", "high", "low", "close", "volume"] | None = None
    compare_value: Decimal | None = None

    @field_validator("compare_value")
    @classmethod
    def finite_value(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("Value must be finite")
        return value


@app.on_event("startup")
def initialize_database() -> None:
    repository(ROOT).migrate()


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/api/config")
def scanner_config() -> dict:
    return {"timeframes": [{"value": "1D", "label": "Daily"}], "fields": FIELDS, "operators": tuple(OPERATORS)}


@app.get("/api/status")
def database_status() -> dict:
    rows = repository(ROOT).status_rows()
    loaded = sum(1 for row in rows if row[1] > 0)
    return {"configured_stocks": len(rows), "loaded_stocks": loaded, "total_candles": sum(row[1] for row in rows)}


@app.post("/api/scan")
def run_scan(request: ScanRequest) -> dict:
    try:
        condition = ScanCondition(
            field=request.field, operator=request.operator, compare_mode=request.compare_mode,
            compare_field=request.compare_field, compare_value=request.compare_value,
        )
        matches = StrictScanner(repository(ROOT)).run(request.timeframe, condition)
        return {"match_count": len(matches), "matches": matches}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

