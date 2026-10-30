"""100-stock reproducible pilot for verifiable OHLCV scanner rules. Research only."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path
from statistics import fmean

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scanstock.trading.scanstock_data import load_daily, symbols_with_daily
from scanstock.trading.learning import D, evaluate_setup
from scanstock.trading.historical import walkforward
from scanstock.trading.research_report import aggregate_symbol_reports

RULES = {
    "CHARTINK_20_CLOSE_VOLUME": "close > maximum prior 20 closes and volume > previous day's 20-volume SMA",
    "CHARTINK_EMA21_PULLBACK": "SMA50/SMA200 trend; EMA21>SMA50; low within 1% of EMA21; close > prior high; RSI14 45..65; volume > SMA20",
    "SCANSTOCK_20_HIGH_BREAKOUT": "close > prior 20-bar high and previous close did not break prior 20-bar high",
}
SOURCES = {
    "CHARTINK_20_CLOSE_VOLUME": "https://chartink.com/screener/daily-breakout-stocks",
    "CHARTINK_EMA21_PULLBACK": "https://chartink.com/%40sridevi-gujju-reddy",
    "SCANSTOCK_20_HIGH_BREAKOUT": "src/scanstock/trading/historical.py",
}

def ema_series(values, period):
    result = [None] * len(values)
    if len(values) < period:
        return result
    value = fmean(values[:period])
    result[period-1] = value
    alpha = 2 / (period+1)
    for i in range(period, len(values)):
        value = alpha*values[i] + (1-alpha)*value
        result[i] = value
    return result

def rsi_series(values, period=14):
    result = [None] * len(values)
    if len(values) <= period:
        return result
    gains = [max(values[i]-values[i-1], 0) for i in range(1,len(values))]
    losses = [max(values[i-1]-values[i], 0) for i in range(1,len(values))]
    gain = fmean(gains[:period]); loss = fmean(losses[:period])
    for i in range(period, len(values)):
        if i > period:
            gain = (gain*(period-1)+gains[i-1])/period
            loss = (loss*(period-1)+losses[i-1])/period
        result[i] = 100 if loss == 0 and gain > 0 else 50 if loss == 0 else 100-100/(1+gain/loss)
    return result

def signals(bars):
    closes = [float(b.close) for b in bars]
    volumes = [b.volume for b in bars]
    ema21 = ema_series(closes, 21)
    rsi = rsi_series(closes)
    found = {name: [] for name in RULES}
    for i in range(200, len(bars)-1):
        close = closes[i]
        if close > max(closes[i-20:i]) and volumes[i] > fmean(volumes[i-21:i-1]):
            found["CHARTINK_20_CLOSE_VOLUME"].append(i)
        high20 = max(float(b.high) for b in bars[i-20:i])
        previous_high20 = max(float(b.high) for b in bars[i-21:i-1])
        if close > high20 and closes[i-1] <= previous_high20:
            found["SCANSTOCK_20_HIGH_BREAKOUT"].append(i)
        sma50 = fmean(closes[i-49:i+1])
        sma200 = fmean(closes[i-199:i+1])
        avgvol20 = fmean(volumes[i-20:i])
        if (ema21[i] > sma50 > sma200 and abs(float(bars[i].low)/ema21[i]-1) <= 0.01
            and close > float(bars[i-1].high) and rsi[i] is not None
            and 45 <= rsi[i] <= 65 and volumes[i] > avgvol20):
            found["CHARTINK_EMA21_PULLBACK"].append(i)
    return found

def trades(symbol, bars, indices, horizon, fee_bps):
    records = []
    for i in indices:
        entry = bars[i+1].open
        stop = bars[i].low
        event = {"symbol":symbol, "signal_at":bars[i].timestamp, "status":"SKIPPED"}
        if stop <= 0 or entry <= stop:
            records.append(event); continue
        target = entry + D(2)*(entry-stop)
        result = evaluate_setup(symbol, "PILOT", i, bars, entry, stop, target, horizon)
        event.update(result)
        event["status"] = "COMPLETE" if result["complete"] else "PENDING"
        if result["complete"]:
            exit_price = D(result["exit_price"])
            event["r_multiple"] = str((exit_price-entry-(entry+exit_price)*D(fee_bps)/D(10000))/(entry-stop))
        records.append(event)
    return records

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/scanstock.db")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--split-at", default="2025-01-01")
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--fee-bps", type=float, default=10)
    p.add_argument("--output", default="data/scanner_pilot_100.json")
    args = p.parse_args()
    date.fromisoformat(args.split_at)
    if args.limit < 1 or args.horizon < 1 or args.fee_bps < 0:
        p.error("limit and horizon must be positive; fees must be nonnegative")
    symbols = symbols_with_daily(args.db)[:args.limit]
    results = {key:{} for key in RULES}
    excluded = {}
    for n, symbol in enumerate(symbols, 1):
        try:
            bars = load_daily(args.db, symbol)
            if len(bars) < 250:
                excluded[symbol] = "fewer than 250 daily candles"
                continue
            found = signals(bars)
            for key, indices in found.items():
                results[key][symbol] = walkforward(trades(symbol,bars,indices,args.horizon,args.fee_bps),args.split_at)
        except (ValueError,TypeError,KeyError,ZeroDivisionError) as exc:
            excluded[symbol] = str(exc)
        if n % 20 == 0:
            print(f"Processed {n}/{len(symbols)}", flush=True)
    report = {"research_only":True,"sample_method":"first N alphabetically sorted symbols with 1D data",
              "requested":args.limit,"selected":symbols,"excluded":excluded,
              "split_at":args.split_at,"fee_bps_each_side":args.fee_bps,
              "horizon":args.horizon,"setups":{}}
    for key, symbol_results in results.items():
        report["setups"][key] = {"rule":RULES[key],"source":SOURCES[key],
                                  "exact_source_status":"source-described rule; not audited against Chartink runtime",
                                  "summary":aggregate_symbol_reports(symbol_results)}
    report["not_tested"] = {
        "ATH_RETEST":"requires historical prior-ATH baseline audit",
        "VCP_BREAKOUT":"requires historical VCP pivot validation",
        "RSI_DIVERGENCE":"Chartink market-cap condition unavailable in OHLCV; no exact replication",
    }
    out = Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    tmp = out.with_suffix(out.suffix+".tmp")
    tmp.write_text(json.dumps(report,indent=2),encoding="utf-8");tmp.replace(out)
    print("Saved:",out)
    for key, value in report["setups"].items():
        print(key,json.dumps(value["summary"]["unseen"]))
    print("Excluded:",len(excluded),"— no live orders")
if __name__ == "__main__":
    main()
