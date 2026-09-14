# ScanStock

Local-first NSE stock screening foundation. V1 stores Daily OHLC in SQLite, downloads through a replaceable Dhan adapter, and keeps scanning/persistence contracts independent of any cloud backend.

## V1 scope

- No Firebase, Supabase, login, subscription, trading or AI prediction.
- 1,789 unique NSE equity instruments from the current Dhan/NSE master.
- Full available Daily history, with progressive forward updates.
- Resumable incremental updates with atomic per-stock transactions.
- SQLite now; PostgreSQL/Supabase can later be added as a repository adapter.
- Strict structured conditions will be built above the stored data.
- One-page local UI with strict dropdown conditions and latest-candle results.

## Windows setup

```powershell
cd F:\projects\ScanStock
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
notepad .env
.\scripts\update_daily.ps1
.\scripts\start_ui.ps1
```

Equivalent manual commands:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
notepad .env
scanstock init-db
scanstock sync-daily
scanstock status
pytest
```

The UI opens at `http://127.0.0.1:8765` and supports ready-made scanners, configurable multi-condition scans, multiple timeframes, VCP evidence and pageable results.

The first sync starts at the configured `initial_from_date`. Subsequent runs prepend missing older history and append new candles without deleting existing rows.

To populate the entire configured NSE universe progressively, run:

```powershell
.\scripts\sync_all_stocks.ps1
```

It processes only stocks requiring work, in batches of 100, keeps a three-second interval between Dhan calls, waits ten minutes between batches, and resumes safely after interruption.

## Structure

```text
config/                     application and starter-universe configuration
data/                       local SQLite database (not committed)
src/scanstock/contracts.py  provider and repository boundaries
src/scanstock/providers/    Dhan now; other providers later
src/scanstock/storage/      SQLite now; PostgreSQL/Supabase later
tests/                      deterministic tests
```
