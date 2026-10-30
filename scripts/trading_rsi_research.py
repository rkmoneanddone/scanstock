"""Run existing TinyMarketLLM RSI research against ScanStock SQLite, without orders."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scanstock.trading.scanstock_data import load_daily, symbols_with_daily
from scanstock.trading.rsi_retest import detect_rsi_retests
from scanstock.trading.historical import walkforward
from scanstock.trading.learning import D

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/scanstock.db")
    p.add_argument("--symbol", default="MOREPENLAB")
    p.add_argument("--all", action="store_true")
    p.add_argument("--split-at", default="2025-01-01")
    p.add_argument("--fee-bps", type=float, default=10)
    p.add_argument("--output", default="data/trading_rsi_research.json")
    args = p.parse_args()
    if args.fee_bps < 0: p.error("fee-bps must be nonnegative")
    symbols = symbols_with_daily(args.db) if args.all else [args.symbol.upper()]
    report = {"split_at": args.split_at, "fee_bps": args.fee_bps,
              "paper_only": True, "symbols": {}}
    for i, symbol in enumerate(symbols, 1):
        try:
            bars = load_daily(args.db, symbol)
            if len(bars) < 250: continue
            records = detect_rsi_retests(symbol, bars)
            for r in records:
                if r.get("status") != "COMPLETE": continue
                entry, exit_price = D(r["entry"]), D(r["exit_price"])
                risk = entry - D(r["stop"])
                r["r_multiple"] = str((exit_price-entry-(entry+exit_price)*D(args.fee_bps)/D(10000))/risk)
            report["symbols"][symbol] = walkforward(records, args.split_at)
        except (ValueError, TypeError, KeyError) as exc:
            report["symbols"][symbol] = {"error": str(exc)}
        if i % 100 == 0: print(f"Processed {i}/{len(symbols)}", flush=True)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temp.replace(out)
    print("Saved:", out, "Symbols:", len(report["symbols"]))
if __name__ == "__main__": main()
