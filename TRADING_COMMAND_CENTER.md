# Trading Command Center — staged integration

ScanStock is the only intended user-facing application. The existing `data/scanstock.db` remains the market-data source of truth. No additional market database, paid LLM, broker order or automated paper entry is required for research.

## Available now
- Existing scanners and Update Market Data UI.
- RSI/EMA historical research on 1D candles, by stock through the dashboard and API.
- Whole-universe offline RSI/EMA research through `scripts/trading_rsi_research.py --all`.
- Trade-weighted training/unseen summaries and rankings (default minimum five unseen trades per stock).
- Existing SQLite database is read-only for offline research; output is a separate JSON report.
- India market-time display for the research trade list.

## Run
```powershell
cd F:\projects\ScanStock
git switch feature/trading-command-center
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\trading_rsi_research.py --all --split-at 2025-01-01 --output data\trading_rsi_all.json
.\scripts\start_ui.ps1
```

The full-universe report includes per-symbol summaries, a trade-weighted aggregate, and rankings. This is research, not a recommendation or proof of profitability. A small unseen sample or a small number of positive stocks must not be treated as validated performance. The data universe may contain survivorship bias and incomplete or stale histories. Trading costs are modeled as 10 bps each side, not full Indian brokerage/tax/slippage.

## Still gated
- No live broker orders.
- No automatic paper entries or risk-control UI: copied engine references a safety module not yet integrated and tested.
- No 1H/15m evidence without those candles in ScanStock.
- No Fib HH/HL strategy comparison until causal pivots and exits are tested.
- No promise of model prediction accuracy based on RSI backtests alone.

## Validation before paper trading
1. Run all tests and inspect full-universe report and missing-data/error counts.
2. Compare baseline and strict variants with unchanged unseen dates.
3. Add realistic costs, overlapping-position exposure, and date/market-calendar checks.
4. Implement and test an independent safety gate and paper journal; enable observation mode first.
5. Only consider real execution after explicit future authorization and separate safety review.
